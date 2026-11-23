from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


BoundingBox = tuple[float, float, float, float]
Point = tuple[float, float]


@dataclass
class FaceDetection:
    bbox: BoundingBox
    confidence: float
    landmarks: tuple[Point, Point, Point, Point, Point]
    track_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PersonDetection:
    bbox: BoundingBox
    confidence: float
    class_id: int = 0
    track_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FrameAnalysis:
    frame_number: int
    timestamp: float
    faces: list[dict[str, Any]] = field(default_factory=list)
    persons: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    total_counts: dict[str, int] = field(default_factory=dict)
    truncated: bool = False
    truncation: dict[str, int] = field(default_factory=dict)
    quality_total: float = 0.0
    quality_count: int = 0
    flag_counts: dict[str, int] = field(default_factory=dict)
    face_track_ids: list[int] = field(default_factory=list)
    person_track_ids: list[int] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VideoAnalysis:
    source: str
    source_id: str
    fps: float
    frame_count: int
    analyzed_frame_count: int
    analysis_run_id: str = ""
    frames: list[FrameAnalysis] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    truncation: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ProgressCallback = Callable[[int, int], None]
