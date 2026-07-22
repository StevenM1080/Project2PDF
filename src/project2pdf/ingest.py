from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from .extractors import (
    extract_3mf,
    extract_pdf,
    extract_stl,
    parse_url_shortcut,
    read_zone_identifier,
    strongest_site_url,
    urls_from_metadata,
)
from .models import ProjectRecord, ProvenanceCandidate
from .util import clean_text, site_for_url, slug_title, unique_strings


SUPPORTED_FILES = {".3mf", ".stl", ".obj", ".step", ".stp", ".pdf", ".url", ".jpg", ".jpeg", ".png", ".webp"}


def _collect_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in SUPPORTED_FILES)
    return []


def _url_candidate(url: str, confidence: float, evidence: str) -> ProvenanceCandidate:
    return ProvenanceCandidate(
        url=url,
        site=site_for_url(url),
        confidence=confidence,
        evidence=[evidence],
    )


def _candidate_confidence(url: str, base: float) -> float:
    lowered = url.lower()
    if any(token in lowered for token in ("/model/", "/models/", "/thing:", "/3d-model/", "/model-detail/")):
        if "?category" not in lowered:
            return min(1.0, base + 0.02)
    if "creativecommons.org/licenses" in lowered:
        return 0.35
    if "/@" in lowered or "/user/" in lowered or "/users/" in lowered:
        return min(base, 0.78)
    if any(host in lowered for host in ("schemas.microsoft.com", "schemas.openxmlformats.org", "schemas.bambulab.com")):
        return 0.1
    return base


def analyze_path(path: Path) -> ProjectRecord:
    path = path.expanduser().resolve()
    root = path if path.is_dir() else path.parent
    files = _collect_files(path)
    record = ProjectRecord(input_root=root, source_files=files, title=slug_title(root.name))
    discovered_urls: list[str] = []
    candidates: list[ProvenanceCandidate] = []

    local_images = [item for item in files if item.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    record.images.extend(str(item) for item in local_images)

    for file_path in files:
        zone = read_zone_identifier(file_path)
        host_url = zone.get("hosturl", "")
        referrer = zone.get("referrerurl", "")
        if host_url:
            discovered_urls.append(host_url)
            candidates.append(_url_candidate(host_url, 0.93, f"Windows download URL on {file_path.name}"))
        if referrer:
            discovered_urls.append(referrer)
            candidates.append(_url_candidate(referrer, 0.88, f"Windows referrer on {file_path.name}"))

        suffix = file_path.suffix.lower()
        if suffix == ".url":
            for url in parse_url_shortcut(file_path):
                discovered_urls.append(url)
                candidates.append(_url_candidate(url, 0.98, f"URL shortcut {file_path.name}"))
        elif suffix == ".pdf":
            pdf = extract_pdf(file_path)
            record.raw_metadata[f"pdf:{file_path.name}"] = pdf
            for url in pdf.get("urls", []):
                if not url.startswith(("http://", "https://")):
                    continue
                discovered_urls.append(url)
                candidates.append(
                    _url_candidate(url, _candidate_confidence(url, 0.97), f"Clickable link in {file_path.name}")
                )
                if "creativecommons.org/licenses" in url.lower():
                    record.license_url = record.license_url or url
                    match = re.search(r"/licenses/([a-z-]+)/([0-9.]+)", url, re.I)
                    if match and not record.license_name:
                        record.license_name = f"CC {match.group(1).upper()} {match.group(2)}"
            text = pdf.get("text", "")
            if text and not record.description:
                summary_match = re.search(
                    r"Summary\s+(.*?)(?:Print details|Project images|Model files|License|Source evidence|$)",
                    text,
                    re.I | re.S,
                )
                if summary_match:
                    record.description = clean_text(summary_match.group(1))
        elif suffix == ".3mf":
            data = extract_3mf(file_path)
            record.raw_metadata[f"3mf:{file_path.name}"] = data
            metadata = data.get("metadata", {})
            record.title = clean_text(metadata.get("Title") or metadata.get("ProfileTitle")) or record.title
            record.creator = clean_text(metadata.get("Designer") or metadata.get("ProfileUserName")) or record.creator
            record.license_name = clean_text(metadata.get("License")) or record.license_name
            embedded_description = clean_text(metadata.get("Description"))
            instruction_match = re.search(
                r"(?:🧰\s*)?(?:Print(?:ing)? (?:settings|instructions)|Consigli per l[’']assemblaggio)\b",
                embedded_description,
                re.I,
            )
            if instruction_match:
                record.description = embedded_description[: instruction_match.start()].strip() or record.description
                record.print_instructions = embedded_description[instruction_match.start() :].strip()
            else:
                record.description = embedded_description or record.description
            record.published = clean_text(metadata.get("CreationDate")) or record.published
            record.updated = clean_text(metadata.get("ModificationDate")) or record.updated
            record.model_files.extend(data.get("model_files", []))
            record.images.extend(data.get("images", []))
            record.embedded_images.extend(data.get("image_bytes", []))
            record.print_settings.update(data.get("print_settings", {}))
            urls = data.get("urls", []) + urls_from_metadata(metadata)
            for url in urls:
                confidence = _candidate_confidence(url, 0.82)
                title_tokens = {
                    token for token in re.findall(r"[a-z0-9]+", record.title.lower()) if len(token) > 3
                }
                url_tokens = set(re.findall(r"[a-z0-9]+", url.lower()))
                related_listing = bool(title_tokens & url_tokens) and any(
                    token in url.lower() for token in ("/model/", "/models/", "/thing:", "/3d-model/")
                )
                if confidence >= 0.3 and related_listing:
                    candidates.append(_url_candidate(url, confidence, f"Embedded in {file_path.name}"))
            if metadata.get("DesignModelId"):
                record.raw_metadata["makerworld_design_model_id"] = metadata["DesignModelId"]
                dsm_match = next(
                    (re.search(r"DSM0*([1-9]\d*)", url, re.I) for url in urls if re.search(r"DSM0*([1-9]\d*)", url, re.I)),
                    None,
                )
                if dsm_match:
                    numeric_id = dsm_match.group(1)
                    slug = re.sub(r"[^a-z0-9]+", "-", record.title.lower()).strip("-")
                    model_url = f"https://makerworld.com/en/models/{numeric_id}-{slug}"
                    discovered_urls.append(model_url)
                    candidates.append(
                        ProvenanceCandidate(
                            url=model_url,
                            site="MakerWorld",
                            confidence=0.99,
                            evidence=[f"MakerWorld design ID DSM{numeric_id} embedded in {file_path.name}"],
                            title=record.title,
                        )
                    )
                else:
                    candidates.append(
                        ProvenanceCandidate(
                            url="https://makerworld.com/",
                            site="MakerWorld",
                            confidence=0.86,
                            evidence=[f"MakerWorld DesignModelId {metadata['DesignModelId']} in {file_path.name}"],
                            title=record.title,
                        )
                    )
        elif suffix == ".stl":
            data = extract_stl(file_path)
            record.raw_metadata[f"stl:{file_path.name}"] = data
            record.dimensions_mm = data.get("dimensions_mm") or record.dimensions_mm
            record.model_files.append(file_path.name)
        elif suffix in {".obj", ".step", ".stp"}:
            record.model_files.append(file_path.name)

    record.model_files = unique_strings(record.model_files)
    record.images = unique_strings(record.images)
    record.candidates = _merge_candidates(candidates)
    best = _best_candidate(record.candidates)
    if best:
        record.select_candidate(best)
        record.discovery_url = best.url
        canonical, canonical_site = strongest_site_url(discovered_urls)
        if canonical:
            record.source_url = canonical
            record.site = canonical_site
    else:
        record.warnings.append("No embedded source URL was found; an online filename search is needed.")
    if not files:
        record.warnings.append("No supported project files were found.")
    return record


def analyze_url(url: str) -> ProjectRecord:
    parsed = urlparse(url)
    title = parsed.path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title() or parsed.netloc
    candidate = _url_candidate(url, 1.0, "URL supplied directly")
    record = ProjectRecord(
        title=title,
        source_url=url,
        discovery_url=url,
        site=candidate.site,
        confidence=1.0,
        evidence=list(candidate.evidence),
        candidates=[candidate],
    )
    return record


def analyze_inputs(inputs: list[str | Path]) -> list[ProjectRecord]:
    records: list[ProjectRecord] = []
    for value in inputs:
        text = str(value).strip()
        if re.match(r"^https?://", text, re.I):
            records.append(analyze_url(text))
        else:
            records.append(analyze_path(Path(text)))
    return records


def _merge_candidates(candidates: list[ProvenanceCandidate]) -> list[ProvenanceCandidate]:
    by_url: dict[str, ProvenanceCandidate] = {}
    for candidate in candidates:
        key = candidate.url.rstrip("/").casefold()
        existing = by_url.get(key)
        if not existing:
            by_url[key] = candidate
            continue
        existing.confidence = max(existing.confidence, candidate.confidence)
        existing.evidence = unique_strings(existing.evidence + candidate.evidence)
    return sorted(by_url.values(), key=lambda item: item.confidence, reverse=True)


def _best_candidate(candidates: list[ProvenanceCandidate]) -> ProvenanceCandidate | None:
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda item: (
            item.confidence,
            item.site not in {"Yeggi", "3Drop", "Website"},
            any(token in item.url.lower() for token in ("/model/", "/models/", "/thing:")),
        ),
        reverse=True,
    )
    return ranked[0]
