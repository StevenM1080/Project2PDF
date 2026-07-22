from __future__ import annotations

import os
import re
from pathlib import Path

from pypdf import PdfReader

from project2pdf.models import ProjectRecord
from project2pdf.pdf import generate_pdf, render_html


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_html_contains_original_link_and_project_sections() -> None:
    record = ProjectRecord(
        title="Test Model",
        creator="A Maker",
        source_url="https://www.printables.com/model/42-test",
        site="Printables",
        description="A useful model.",
        print_instructions="Use 0.2 mm layers.",
        model_files=["test.stl"],
        license_name="CC BY 4.0",
        confidence=0.99,
        evidence=["Exact filename/title web search"],
        category="All categories / Tools",
        tags=["widget", "tool"],
        print_settings={
            "Printer": "Example Printer",
            "Print profile": "0.20mm Standard",
            "Layer height": "0.2 mm",
        },
    )
    html = render_html(record)
    assert "VIEW ORIGINAL ON PRINTABLES" in html
    assert "Print details" in html
    assert "test.stl" in html
    assert "Layer height" in html
    assert "Source: Printables" not in html
    assert "confidence" not in html.casefold()
    assert "All categories" not in html
    assert "widget" not in html
    assert "Example Printer" not in html
    assert "0.20mm Standard" not in html
    assert "Source evidence" not in html
    assert "Exact filename/title web search" not in html
    assert html.count('class="section"') == 4
    assert "page-break-inside: avoid" in html


def test_dark_pdf_theme_uses_dark_page_and_section_colors() -> None:
    record = ProjectRecord(title="Night Model", description="Comfortable after dark.")
    html = render_html(record, theme="dark")
    assert "background: #1b2028" in html
    assert "background: #242c36" in html
    assert "color: #e7ebf0" in html


def test_gallery_section_always_starts_on_a_fresh_page() -> None:
    record = ProjectRecord(title="Photo Model")
    html = render_html(record, image_uris=["hero", "gallery-one", "gallery-two"])
    assert "gallery-section { page-break-before: always; }" in html
    assert 'class="section gallery-section"' in html


def test_long_print_details_are_moved_to_a_fresh_page() -> None:
    record = ProjectRecord(
        title="Settings Model",
        description=" ".join(["A long project description."] * 80),
        print_settings={f"Setting {index}": str(index) for index in range(5)},
    )
    html = render_html(record)
    assert 'class="section section-new-page"' in html


def test_model_files_use_a_compact_two_column_grid() -> None:
    record = ProjectRecord(title="Parts", model_files=["one.stl", "two.stl", "three.stl"])
    html = render_html(record)
    assert 'class="file-grid"' in html
    assert "one.stl" in html and "three.stl" in html


def test_pdf_is_searchable_and_contains_clickable_source(tmp_path: Path) -> None:
    record = ProjectRecord(
        title="Test Model",
        creator="A Maker",
        source_url="https://www.printables.com/model/42-test",
        site="Printables",
        description="Searchable project summary.",
        model_files=["test.stl"],
        confidence=0.99,
    )
    output = generate_pdf(record, tmp_path / "test.pdf")
    reader = PdfReader(str(output))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    normalized = re.sub(r"\s+", " ", text)
    assert "Test Model" in normalized
    assert "Searchable project summary" in normalized
    links = []
    for page in reader.pages:
        for annotation_ref in page.get("/Annots") or []:
            annotation = annotation_ref.get_object()
            uri = (annotation.get("/A") or {}).get("/URI")
            if uri:
                links.append(str(uri))
    assert "https://www.printables.com/model/42-test" in links


def test_dark_pdf_paints_the_entire_page_background(tmp_path: Path) -> None:
    record = ProjectRecord(title="Dark Model", description="Dark page test.")
    output = generate_pdf(record, tmp_path / "dark.pdf", theme="dark")
    page = PdfReader(str(output)).pages[0]
    contents = page.get("/Contents")
    first_stream = contents[0].get_object() if isinstance(contents, list) else contents.get_object()
    assert b"0 0" in first_stream.get_data()
    assert b" re f" in first_stream.get_data()
