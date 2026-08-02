from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NLPResult:
    topic: str = ""
    author: str = ""
    organization: str = ""
    project: str = ""
    location: str = ""
    document_type: str = ""
    summary: str = ""
    keywords: list[str] = field(default_factory=list)
    date: str = ""
    confidence: float = 0.0
    smart_filename: str = ""
    smart_destination: str = ""
    camera_model: str = ""
    artist: str = ""
    album: str = ""
    nlp_generated: bool = False
    file_type: str = ""
