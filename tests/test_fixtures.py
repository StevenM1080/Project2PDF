from __future__ import annotations

from pathlib import Path

import pytest

from project2pdf.extractors import extract_stl, read_zone_identifier
from project2pdf.ingest import analyze_path


RESOURCES = Path(__file__).parents[1] / "Resources"


@pytest.mark.skipif(not RESOURCES.exists(), reason="Local sample projects are not present")
def test_wandermark_companion_pdf_finds_printables_model() -> None:
    record = analyze_path(RESOURCES / "Wandermark")
    assert record.site == "Printables"
    assert record.source_url == "https://printables.com/model/801761-wondermark-bookmark"
    assert record.confidence >= 0.95
    assert record.model_files
    assert record.embedded_images


@pytest.mark.skipif(not RESOURCES.exists(), reason="Local sample projects are not present")
def test_makerworld_3mf_reconstructs_canonical_model_url() -> None:
    record = analyze_path(RESOURCES / "CSGO")
    assert record.title == "Butterfly Balisong Knife MKII Set"
    assert record.creator == "Noir"
    assert record.license_name == "Standard Digital File License"
    assert record.source_url.startswith("https://makerworld.com/en/models/1639165-")
    assert record.confidence >= 0.95
    assert len(record.embedded_images) >= 2


@pytest.mark.skipif(not RESOURCES.exists(), reason="Local sample projects are not present")
def test_stl_only_project_uses_windows_download_provenance() -> None:
    folder = RESOURCES / "Level 5 Pyramid - Vase Mode"
    stl = next(folder.glob("*.stl"))
    geometry = extract_stl(stl)
    zone = read_zone_identifier(stl)
    record = analyze_path(folder)

    assert geometry["facets"] == 235468
    assert geometry["dimensions_mm"] == (200.0, 200.0, 141.421)
    assert zone["referrerurl"] == "https://www.printables.com/"
    assert "files.printables.com" in zone["hosturl"]
    assert record.site == "Printables"
    assert record.dimensions_mm == (200.0, 200.0, 141.421)


@pytest.mark.skipif(not RESOURCES.exists(), reason="Local sample projects are not present")
def test_project2pdf_companion_pdf_does_not_mix_sections_into_summary() -> None:
    record = analyze_path(RESOURCES / "Floral+Bookmark+-+Just+one+more+page")
    assert record.description == "Cute floral bookmark"
