from __future__ import annotations

import base64
from datetime import datetime
import io
import math
import os
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup, escape
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, NameObject
from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QFont, QFontDatabase, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication

from .models import ProjectRecord
from .sites import CachedWebClient
from .util import safe_filename, unique_strings


def _nl2br(value: str) -> Markup:
    paragraphs = [str(escape(part.strip())).replace("\n", "<br>") for part in value.split("\n\n") if part.strip()]
    return Markup("".join(f"<p>{part}</p>" for part in paragraphs))


def _template_environment() -> Environment:
    environment = Environment(
        loader=PackageLoader("project2pdf", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    environment.filters["nl2br"] = _nl2br
    environment.filters["friendly_date"] = _friendly_date
    return environment


def _friendly_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return f"{parsed.day} {parsed.strftime('%b %Y')}"
    except ValueError:
        return value


def _image_data_uri(data: bytes, max_size: tuple[int, int] = (620, 440)) -> str:
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
    except Exception:
        return ""
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def collect_images(
    record: ProjectRecord,
    web: CachedWebClient | None = None,
    limit: int = 6,
) -> list[str]:
    result: list[str] = []
    for source in record.images:
        if len(result) >= limit:
            break
        if source.startswith("3mf://"):
            continue
        data = b""
        if source.startswith(("http://", "https://")):
            if not web:
                continue
            try:
                data = web.get_bytes(source)
            except Exception:
                continue
        else:
            try:
                data = Path(source).read_bytes()
            except OSError:
                continue
        uri = _image_data_uri(data)
        if uri:
            result.append(uri)
    for data in record.embedded_images:
        if len(result) >= limit:
            break
        uri = _image_data_uri(data)
        if uri:
            result.append(uri)
    return unique_strings(result)


PDF_PALETTES = {
    "light": {
        "background": "#f5f6f8",
        "surface": "#ffffff",
        "heading": "#171a20",
        "text": "#20242b",
        "muted": "#66707d",
        "border": "#d9dee5",
        "soft": "#f0f2f5",
        "accent": "#e9572b",
        "button_text": "#ffffff",
    },
    "dark": {
        "background": "#1b2028",
        "surface": "#242c36",
        "heading": "#f1f4f8",
        "text": "#e7ebf0",
        "muted": "#b0bac6",
        "border": "#465362",
        "soft": "#303a47",
        "accent": "#ff7043",
        "button_text": "#ffffff",
    },
}


def render_html(record: ProjectRecord, image_uris: Iterable[str] = (), theme: str = "light") -> str:
    images = list(image_uris)
    template = _template_environment().get_template("project.html")
    dimensions = ""
    if record.dimensions_mm:
        dimensions = " × ".join(f"{value:g}" for value in record.dimensions_mm) + " mm"
    excluded_settings = {
        "printer",
        "printer model",
        "print profile",
        "printer profile",
        "default print profile",
    }
    print_settings = {
        key: value
        for key, value in record.print_settings.items()
        if key.strip().casefold() not in excluded_settings
    }
    display_model_files = record.model_files or [path.name for path in record.source_files]
    summary_lines = sum(
        max(1, math.ceil(len(paragraph) / 82))
        for paragraph in record.description.splitlines()
        if paragraph.strip()
    )
    instruction_lines = sum(
        max(1, math.ceil(len(paragraph) / 82))
        for paragraph in record.print_instructions.splitlines()
        if paragraph.strip()
    )
    hero_and_summary_height = 360 + (75 + summary_lines * 22 if record.description else 0)
    print_section_height = 85 + len(print_settings) * 38 + instruction_lines * 22
    print_section_new_page = hero_and_summary_height + print_section_height > 930
    current_page_height = print_section_height if print_section_new_page else hero_and_summary_height + print_section_height
    model_section_height = 75 + math.ceil(len(display_model_files) / 2) * 38
    model_section_new_page = current_page_height + model_section_height > 930
    current_page_height = model_section_height if model_section_new_page else current_page_height + model_section_height
    license_section_height = 125 if record.license_name or record.license_url else 0
    license_section_new_page = bool(license_section_height and current_page_height + license_section_height > 930)
    return template.render(
        project=record,
        hero=images[0] if images else "",
        gallery=images[1:],
        dimensions=dimensions,
        print_settings=print_settings,
        display_model_files=display_model_files,
        model_file_count=len(display_model_files),
        print_section_new_page=print_section_new_page,
        model_section_new_page=model_section_new_page,
        license_section_new_page=license_section_new_page,
        palette=PDF_PALETTES.get(theme, PDF_PALETTES["light"]),
    )


def _paint_pdf_page_background(output_path: Path, color: str) -> None:
    red, green, blue = (int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))
    reader = PdfReader(output_path)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    for page in writer.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        background = DecodedStreamObject()
        background.set_data(
            f"q {red:.6f} {green:.6f} {blue:.6f} rg 0 0 {width:.6f} {height:.6f} re f Q\n".encode()
        )
        background_reference = writer._add_object(background)
        contents = page.get(NameObject("/Contents"))
        if isinstance(contents, ArrayObject):
            page[NameObject("/Contents")] = ArrayObject([background_reference, *contents])
        elif contents is not None:
            page[NameObject("/Contents")] = ArrayObject([background_reference, contents])
        else:
            page[NameObject("/Contents")] = background_reference
    temporary_path = output_path.with_suffix(".background.tmp.pdf")
    try:
        with temporary_path.open("wb") as handle:
            writer.write(handle)
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def ensure_qapplication() -> QApplication:
    app = QApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication(["Project2PDF"])
        app.setApplicationName("Project2PDF")
    if sys_font := next(
        (
            path
            for path in (
                Path("C:/Windows/Fonts/segoeui.ttf"),
                Path("C:/Windows/Fonts/arial.ttf"),
            )
            if path.exists()
        ),
        None,
    ):
        QFontDatabase.addApplicationFont(str(sys_font))
    return app


def generate_pdf(
    record: ProjectRecord,
    output_path: Path,
    web: CachedWebClient | None = None,
    theme: str = "light",
) -> Path:
    ensure_qapplication()
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    images = collect_images(record, web=web)
    html_text = render_html(record, images, theme=theme)

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(output_path))
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageMargins(QMarginsF(13, 13, 13, 14), QPageLayout.Unit.Millimeter)
    printer.setResolution(150)

    document = QTextDocument()
    document.setDocumentMargin(printer.resolution() * 13 / 25.4)
    document.setDefaultFont(QFont("Segoe UI", 10))
    document.documentLayout().setPaintDevice(printer)
    document.setPageSize(printer.paperRect(QPrinter.Unit.DevicePixel).size())
    document.setHtml(html_text)
    document.print_(printer)
    if theme == "dark":
        _paint_pdf_page_background(output_path, PDF_PALETTES["dark"]["background"])
    if not output_path.exists() or output_path.stat().st_size < 1000:
        raise RuntimeError("Qt did not create a valid PDF")
    return output_path


def default_output_path(record: ProjectRecord, directory: Path) -> Path:
    return directory / f"{safe_filename(record.display_name)}.pdf"
