from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import urlparse


SITE_HOSTS = {
    "printables.com": "Printables",
    "files.printables.com": "Printables",
    "media.printables.com": "Printables",
    "makerworld.com": "MakerWorld",
    "bblmw.com": "MakerWorld",
    "thingiverse.com": "Thingiverse",
    "thangs.com": "Thangs",
    "crealitycloud.com": "Creality Cloud",
    "yeggi.com": "Yeggi",
    "three-drop.com": "3Drop",
    "cults3d.com": "Cults3D",
}


def site_for_url(url: str) -> str:
    host = urlparse(url).hostname or ""
    host = host.lower().removeprefix("www.")
    for suffix, site in SITE_HOSTS.items():
        if host == suffix or host.endswith("." + suffix):
            return site
    return host or "Website"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = value
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    text = re.sub(r"<\s*br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*(p|li|h[1-6])\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def slug_title(path: Path | str) -> str:
    stem = Path(path).stem if not isinstance(path, Path) else path.stem
    stem = re.sub(r"[+_-]+", " ", stem)
    stem = re.sub(r"\b(stl|3mf|obj|model files?)\b", " ", stem, flags=re.I)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem.title()


def safe_filename(value: str, fallback: str = "project") -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value or fallback)[:150]


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result

