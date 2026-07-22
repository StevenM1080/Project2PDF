from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ProvenanceCandidate:
    url: str
    site: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    title: str = ""

    @property
    def confidence_label(self) -> str:
        if self.confidence >= 0.9:
            return "High"
        if self.confidence >= 0.65:
            return "Medium"
        return "Low"


@dataclass(slots=True)
class ProjectRecord:
    input_root: Path | None = None
    source_files: list[Path] = field(default_factory=list)
    title: str = ""
    creator: str = ""
    creator_url: str = ""
    source_url: str = ""
    discovery_url: str = ""
    site: str = ""
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    description: str = ""
    print_instructions: str = ""
    license_name: str = ""
    license_url: str = ""
    published: str = ""
    updated: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    model_files: list[str] = field(default_factory=list)
    dimensions_mm: tuple[float, float, float] | None = None
    print_settings: dict[str, str] = field(default_factory=dict)
    images: list[str] = field(default_factory=list)
    embedded_images: list[bytes] = field(default_factory=list, repr=False)
    candidates: list[ProvenanceCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def display_name(self) -> str:
        if self.title:
            return self.title
        if self.input_root:
            return self.input_root.stem
        return "Untitled project"

    def select_candidate(self, candidate: ProvenanceCandidate) -> None:
        self.source_url = candidate.url
        self.site = candidate.site
        self.confidence = candidate.confidence
        self.evidence = list(candidate.evidence)
        if not self.title and candidate.title:
            self.title = candidate.title

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["input_root"] = str(self.input_root) if self.input_root else None
        data["source_files"] = [str(path) for path in self.source_files]
        data.pop("embedded_images", None)
        return data

