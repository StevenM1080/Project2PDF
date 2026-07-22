from __future__ import annotations

from project2pdf.models import ProjectRecord, ProvenanceCandidate
from project2pdf.sites import SourceService, parse_makerworld_api, parse_page_metadata


def test_generic_metadata_parser_normalizes_open_graph_and_json_ld() -> None:
    html = """
    <html><head>
      <link rel="canonical" href="https://example.com/models/42-widget">
      <meta property="og:title" content="Useful Widget">
      <meta property="og:description" content="A useful printable widget.">
      <meta property="og:image" content="/images/widget.jpg">
      <script type="application/ld+json">
        {"@type":"CreativeWork","name":"Useful Widget","author":{"name":"Ada","url":"/users/ada"},
         "datePublished":"2025-01-02","license":"https://creativecommons.org/licenses/by/4.0/"}
      </script>
    </head><body><h2>Print settings</h2><p>0.2 mm layer height</p></body></html>
    """
    page = parse_page_metadata(html, "https://example.com/view")
    assert page.url == "https://example.com/models/42-widget"
    assert page.creator == "Ada"
    assert page.creator_url == "https://example.com/users/ada"
    assert page.images == ["https://example.com/images/widget.jpg"]
    assert "0.2 mm" in page.print_instructions


def test_three_drop_model_url_resolves_without_network() -> None:
    service = object.__new__(SourceService)
    assert (
        service.resolve_aggregator("https://three-drop.com/model/makerworld/1639165")
        == "https://makerworld.com/en/models/1639165"
    )


def test_page_metadata_application_preserves_richer_local_values() -> None:
    record = ProjectRecord(title="Local title", description="Embedded 3MF details")
    page = parse_page_metadata(
        '<meta property="og:title" content="Web title"><meta property="og:description" content="Web summary">',
        "https://example.com/models/1",
    )
    SourceService.apply_page(record, page)
    assert record.title == "Web title"
    assert record.description == "Web summary"


def test_makerworld_api_parser_extracts_normalized_project_data() -> None:
    page = parse_makerworld_api(
        {
            "id": 42,
            "slug": "useful-widget",
            "title": "Useful Widget",
            "summary": "<p>A useful model.</p><h3>Print settings</h3><p>0.2 mm layers</p>",
            "coverUrl": "https://cdn.example/cover.jpg",
            "designCreator": {"name": "Ada", "handle": "ada"},
            "license": "Standard Digital File License",
            "createTime": "2025-01-01T00:00:00Z",
            "tags": ["tool", "widget"],
            "categories": [{"name": "Tools"}],
            "instances": [],
        },
        "https://makerworld.com/en/models/42",
    )
    assert page.url == "https://makerworld.com/en/models/42-useful-widget"
    assert page.creator == "Ada"
    assert page.license_name == "Standard Digital File License"
    assert page.category == "Tools"
    assert page.images == ["https://cdn.example/cover.jpg"]


def test_page_enrichment_keeps_local_project_photo_first(tmp_path) -> None:
    local_photo = tmp_path / "completed-print.png"
    local_photo.write_bytes(b"image fixture")
    record = ProjectRecord(images=[str(local_photo)])
    page = parse_page_metadata(
        '<meta property="og:image" content="https://example.com/creator-photo.jpg">',
        "https://example.com/models/1",
    )
    SourceService.apply_page(record, page)
    assert record.images == [str(local_photo), "https://example.com/creator-photo.jpg"]


def test_cults_parser_extracts_listing_specific_details() -> None:
    html = """
    <html><head>
      <meta property="og:title" content="Useful Cults Model">
      <meta property="og:image" content="https://images.cults3d.com/illustration-file/cover.jpg">
    </head><body>
      <table>
        <tr><th>License</th><td><a href="/en/licenses/cults-pu">CULTS PU</a></td></tr>
        <tr><th>3D design format</th><td><span>body.stl</span><span>parts.zip</span></td></tr>
        <tr><th>Last update</th><td><time datetime="2026-05-29T19:18:22Z">May 29</time></td></tr>
        <tr><th>Publication date</th><td><time datetime="2025-08-19T14:30:10Z">Aug 19</time></td></tr>
        <tr><th>Design author</th><td>MUBA</td></tr>
      </table>
      <a href="/en/users/MUBA">MUBA</a>
      <div class="creation-page__tab-section"><h2>3D model description</h2><p>A handy opener.</p></div>
      <div class="creation-page__tab-section"><h2>3D printing settings</h2><p>Use PETG.</p></div>
      <div class="creation-page__tab-section"><h2>Tags</h2><a>tool</a><a>kitchen</a></div>
    </body></html>
    """
    page = parse_page_metadata(
        html,
        "https://cults3d.com/en/3d-model/home/useful-model",
    )
    assert page.creator == "MUBA"
    assert page.creator_url == "https://cults3d.com/en/users/MUBA"
    assert page.license_name == "CULTS PU"
    assert page.license_url == "https://cults3d.com/en/licenses/cults-pu"
    assert page.published == "2025-08-19T14:30:10Z"
    assert page.updated == "2026-05-29T19:18:22Z"
    assert page.description == "A handy opener."
    assert page.print_instructions == "Use PETG."
    assert page.tags == ["tool", "kitchen"]
    assert page.model_files == ["body.stl", "parts.zip"]


def test_successful_source_selection_removes_stale_discovery_warning() -> None:
    class StubSourceService(SourceService):
        def search_for_record(self, record: ProjectRecord):
            return ProvenanceCandidate(
                url="https://www.printables.com/model/42-test",
                site="Printables",
                confidence=0.8,
                evidence=["Filename search"],
            )

    class StubWeb:
        def get_text(self, url: str, max_age: int = 86400):
            return '<meta property="og:title" content="Test Model">', url

    record = ProjectRecord(
        title="Test Model",
        warnings=["No embedded source URL was found; an online filename search is needed."],
    )
    enriched = StubSourceService(StubWeb()).enrich(record)
    assert enriched.source_url == "https://www.printables.com/model/42-test"
    assert enriched.warnings == []
