from __future__ import annotations

import configparser
import json
import re
import struct
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from pypdf import PdfReader

from .util import site_for_url, unique_strings


URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def read_zone_identifier(path: Path) -> dict[str, str]:
    """Read the Windows Mark-of-the-Web stream without failing on other platforms."""
    stream_path = f"{path}:Zone.Identifier"
    try:
        raw = Path(stream_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    parser = configparser.ConfigParser()
    try:
        parser.read_string(raw)
        return dict(parser["ZoneTransfer"])
    except (configparser.Error, KeyError):
        return {}


def parse_url_shortcut(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    return unique_strings(URL_RE.findall(text))


def extract_pdf(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"urls": [], "text": "", "metadata": {}}
    try:
        reader = PdfReader(str(path))
        result["metadata"] = dict(reader.metadata or {})
        pages: list[str] = []
        urls: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
            annotations = page.get("/Annots") or []
            for annotation_ref in annotations:
                try:
                    annotation = annotation_ref.get_object()
                    action = annotation.get("/A") or {}
                    uri = action.get("/URI")
                    if uri:
                        urls.append(str(uri))
                except Exception:
                    continue
        result["text"] = "\n\n".join(pages).strip()
        result["urls"] = unique_strings(urls + URL_RE.findall(result["text"]))
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _xml_metadata(root: ET.Element) -> dict[str, str]:
    data: dict[str, str] = {}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "metadata":
            continue
        name = element.attrib.get("name") or element.attrib.get("key")
        value = element.attrib.get("value")
        if value is None:
            value = element.text or ""
        if name and value and name not in data:
            data[name] = value
    return data


def extract_3mf(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "metadata": {},
        "urls": [],
        "model_files": [],
        "images": [],
        "image_bytes": [],
        "print_settings": {},
    }
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            xml_names = [
                name
                for name in names
                if name.lower().endswith((".model", ".config", ".xml"))
            ]
            all_text: list[str] = []
            for name in xml_names:
                try:
                    raw = archive.read(name)
                except KeyError:
                    continue
                text = raw.decode("utf-8", errors="replace")
                all_text.append(text)
                if name.lower().endswith((".model", ".config", ".xml")):
                    try:
                        root = ET.fromstring(raw)
                        result["metadata"].update(
                            {k: v for k, v in _xml_metadata(root).items() if k not in result["metadata"]}
                        )
                    except ET.ParseError:
                        pass

            metadata = result["metadata"]
            result["urls"] = unique_strings(URL_RE.findall("\n".join(all_text)))
            result["model_files"] = unique_strings(
                [
                    unquote(value).replace("\\", "/").rsplit("/", 1)[-1]
                    for key, value in metadata.items()
                    if key.lower() in {"name", "source_file"}
                    and Path(value.replace("\\", "/")).suffix.lower()
                    in {".stl", ".obj", ".3mf", ".step", ".stp"}
                ]
            )
            preferred_images = [
                name
                for name in names
                if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                and (
                    "model pictures" in name.lower()
                    or "thumbnail" in name.lower()
                    or re.search(r"plate_\d+\.", name.lower())
                )
            ]
            for name in preferred_images[:12]:
                try:
                    result["image_bytes"].append(archive.read(name))
                    result["images"].append(f"3mf://{path.name}/{name}")
                except KeyError:
                    continue

            settings_name = next(
                (name for name in names if name.lower() == "metadata/project_settings.config"),
                "",
            )
            if settings_name:
                try:
                    settings = json.loads(archive.read(settings_name).decode("utf-8"))
                    keys = {
                        "printer_model": "Printer",
                        "default_print_profile": "Print profile",
                        "layer_height": "Layer height",
                        "sparse_infill_density": "Infill",
                        "support_type": "Supports",
                        "brim_type": "Brim",
                        "nozzle_diameter": "Nozzle",
                        "filament_type": "Filament",
                    }
                    for key, label in keys.items():
                        value = settings.get(key)
                        if isinstance(value, list):
                            value = ", ".join(str(item) for item in value if str(item))
                        if value not in (None, "", []):
                            result["print_settings"][label] = str(value)
                except (ValueError, KeyError):
                    pass
    except (OSError, zipfile.BadZipFile) as exc:
        result["error"] = str(exc)
    return result


def extract_stl(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"header": "", "dimensions_mm": None, "facets": 0}
    try:
        with path.open("rb") as handle:
            header = handle.read(80)
            result["header"] = header.rstrip(b"\0 ").decode("utf-8", errors="replace")
            count_bytes = handle.read(4)
            binary_size = 84
            if len(count_bytes) == 4:
                count = struct.unpack("<I", count_bytes)[0]
                binary_size += count * 50
            else:
                count = 0
            if binary_size == path.stat().st_size and count:
                mins = [float("inf")] * 3
                maxs = [float("-inf")] * 3
                for _ in range(count):
                    record = handle.read(50)
                    if len(record) != 50:
                        break
                    values = struct.unpack("<12fH", record)
                    for axis in range(3):
                        for offset in (3 + axis, 6 + axis, 9 + axis):
                            mins[axis] = min(mins[axis], values[offset])
                            maxs[axis] = max(maxs[axis], values[offset])
                result["facets"] = count
                result["dimensions_mm"] = tuple(
                    round(maxs[index] - mins[index], 3) for index in range(3)
                )
            else:
                handle.seek(0)
                text = handle.read().decode("utf-8", errors="ignore")
                vertices = [
                    tuple(float(part) for part in match.groups())
                    for match in re.finditer(
                        r"vertex\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)", text, re.I
                    )
                ]
                if vertices:
                    result["dimensions_mm"] = tuple(
                        round(max(vertex[axis] for vertex in vertices) - min(vertex[axis] for vertex in vertices), 3)
                        for axis in range(3)
                    )
                    result["facets"] = len(vertices) // 3
    except (OSError, ValueError, struct.error) as exc:
        result["error"] = str(exc)
    return result


def urls_from_metadata(metadata: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in metadata.values():
        if isinstance(value, str):
            values.extend(URL_RE.findall(value))
    return unique_strings(values)


def strongest_site_url(urls: list[str]) -> tuple[str, str]:
    for url in urls:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host.startswith(("files.", "media.")) or host.endswith("bblmw.com"):
            continue
        if Path(parsed.path).suffix.lower() in {".stl", ".3mf", ".obj", ".step", ".stp", ".png", ".jpg", ".jpeg", ".webp"}:
            continue
        site = site_for_url(url)
        if site not in {"Website", "Yeggi", "3Drop"} and any(
            token in url.lower() for token in ("/model/", "/models/", "/thing:", "/3d-model/")
        ):
            return url, site
    for url in urls:
        site = site_for_url(url)
        if site not in {"Website", "Yeggi", "3Drop"}:
            return url, site
    return (urls[0], site_for_url(urls[0])) if urls else ("", "")
