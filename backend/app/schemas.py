from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import CV_ANALYZE_MAX_FRAMES, CV_MAX_FRAME_STRIDE, CV_MAX_TOP_K


class CaseCreate(BaseModel):
    case_number: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    tags: str = Field(default="", max_length=400)


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    tags: str | None = Field(default=None, max_length=400)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class TransactionCreate(BaseModel):
    reference: str = Field(min_length=1, max_length=120)
    atm_id: str = Field(default="", max_length=120)
    transaction_ts: str = Field(min_length=1, max_length=80)
    cctv_ts: str = Field(default="", max_length=80)
    transaction_type: str = Field(default="withdrawal", max_length=60)
    amount: str = Field(default="", max_length=60)
    note: str = Field(default="", max_length=4000)


class AlignmentRequest(BaseModel):
    transaction_ts: str
    cctv_ts: str
    video_duration: float = Field(ge=0)
    video_start_ts: str | None = None
    cctv_reference_video_time: float = 0
    clock_offset_minutes: float | None = None
    before_seconds: float = 20
    after_seconds: float = 20


class JobCreate(BaseModel):
    video_id: str
    transaction_id: str
    config: dict[str, Any] = Field(default_factory=dict)


class VideoUpdate(BaseModel):
    tags: str = Field(default="", max_length=400)


class FrameUpdate(BaseModel):
    selected: bool | None = None
    note: str | None = None
    reason: str | None = None


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    video_id: str | None = None
    frame_id: str | None = None


class ManualCaptureRequest(BaseModel):
    case_id: str
    video_id: str
    timestamp: float = Field(ge=0)
    note: str = Field(default="", max_length=4000)


class ClipLinkCreate(BaseModel):
    video_a: str
    video_b: str
    reason: str = Field(min_length=1, max_length=4000)


class CvExportSelectionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int | None = Field(default=None, ge=1, le=CV_MAX_TOP_K)
    similarity_score: float | None = Field(default=None, ge=-1, le=1)
    score_meaning: str | None = Field(default=None, max_length=400)
    candidate_disclaimer: str | None = Field(default=None, max_length=400)

    @field_validator("similarity_score")
    @classmethod
    def validate_similarity_score(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("similarity_score must be finite")
        return value


class CvExportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["observation", "candidate"]
    cv_run_id: str = Field(min_length=1, max_length=120)
    observation_id: str = Field(min_length=1, max_length=120)
    query_cv_run_id: str | None = Field(default=None, max_length=120)
    query_observation_id: str | None = Field(default=None, max_length=120)
    candidate_id: str | None = Field(default=None, max_length=120)
    expected_review_updated_at: str | None = Field(default=None, max_length=80)
    expected_model_sha256: str | None = Field(default=None, max_length=64)
    selection_context: CvExportSelectionContext | None = None

    @field_validator(
        "cv_run_id",
        "observation_id",
        "query_cv_run_id",
        "query_observation_id",
        "candidate_id",
    )
    @classmethod
    def validate_opaque_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validated_opaque_id(value)

    @field_validator("expected_model_sha256")
    @classmethod
    def validate_model_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validated_sha256(value)

    @field_validator("expected_review_updated_at")
    @classmethod
    def validate_review_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("must be an ISO 8601 timestamp") from exc
        return value

    @model_validator(mode="after")
    def validate_selection_shape(self) -> "CvExportItem":
        if self.kind == "candidate":
            if not self.query_cv_run_id or not self.query_observation_id:
                raise ValueError("candidate selections require query_cv_run_id and query_observation_id")
            if self.selection_context is None:
                raise ValueError("candidate selections require selection_context")
        elif self.query_cv_run_id or self.query_observation_id or self.candidate_id or self.selection_context:
            raise ValueError("candidate context is only valid for candidate selections")
        return self


class ExportRequest(BaseModel):
    case_id: str
    frame_ids: list[str] = Field(min_length=1, max_length=200)
    cv_items: list[CvExportItem] = Field(default_factory=list, max_length=CV_MAX_TOP_K)

    @model_validator(mode="after")
    def validate_cv_selections(self) -> "ExportRequest":
        seen: set[tuple[str, str, str]] = set()
        for item in self.cv_items:
            key = (item.kind, item.cv_run_id, item.observation_id)
            if key in seen:
                raise ValueError("duplicate CV selections are not allowed")
            seen.add(key)
        return self


class CVAnalyzeRequest(BaseModel):
    video_id: str = Field(min_length=1, max_length=120)
    max_frames: int | None = Field(default=None, ge=1, le=CV_ANALYZE_MAX_FRAMES)
    frame_stride: int = Field(default=1, ge=1, le=CV_MAX_FRAME_STRIDE)
    save_crops: bool = False
    add_to_index: bool = False
    rank: bool = False
    summary_only: bool = False
    top_k: int = Field(default=5, ge=1, le=CV_MAX_TOP_K)
    labels: dict[str, str] | None = Field(default=None, max_length=CV_ANALYZE_MAX_FRAMES)


CV_RUN_STATUSES = ("queued", "running", "completed", "completed_with_warnings", "failed")
CV_REVIEW_DECISIONS = ("relevant", "irrelevant", "needs_review")
CV_WINDOW_MODES = ("full_video", "transaction_aligned")
CV_CANDIDATE_VERIFICATION_STATUS = "candidate_only"
CV_CANDIDATE_DISCLAIMER = "Similarity candidate only; requires human verification. Never identity confirmation."
CV_ASSOCIATION_LIMITATION = (
    "Detected faces, person detections, track IDs, similarity scores and review decisions do not identify the ATM operator, "
    "cardholder, cashier or any transaction participant. A proposed transaction-person association is a reviewable "
    "link hypothesis from observed zone, dwell and timing evidence; it is never identity confirmation."
)
CV_ATM_ZONE_COORDINATE_CONVENTION = (
    "Frame-relative normalized top-left coordinates: x, y, width and height are fractions of source frame width and height "
    "in 0..1, with x+width<=1 and y+height<=1."
)
CV_ASSOCIATION_EVIDENCE_MEANING = (
    "Heuristic evidence-strength score from 0 to 1 combining zone overlap, observed dwell, transaction-window timing, "
    "track continuity and detector confidence; it is not a calibrated probability or identity likelihood."
)
CV_BEST_FACE_SCORE_MEANING = (
    "Heuristic quality-ranking score from 0 to 1 combining existing face-quality components and detector confidence; "
    "it is not identity confidence, biometric match probability, or a calibrated accuracy measure."
)
CV_BEST_FACE_LIMITATION = (
    "Best-face selection is a deterministic review aid for a run-local person track. Face-to-person linkage uses "
    "same-frame bbox containment, not identity; original observations and frames are unchanged; mask, helmet and cap "
    "remain not assessed; no enhancement restores information that was not captured."
)
CV_ASSOCIATION_REVIEW_STATES = ("proposed", "confirmed", "rejected", "insufficient_evidence")
CV_ASSOCIATION_EVIDENCE_STRENGTHS = ("strong", "moderate", "weak", "insufficient")
CV_SIMILARITY_SCORE_MEANING = (
    "Cosine similarity of normalized SFace vectors, from -1 to 1; higher means greater visual similarity only, "
    "not identity verification."
)
CV_UNSUPPORTED_ATTRIBUTE_STATUS = "not_assessed"
CV_CROP_STATUSES = ("not_generated", "available", "unavailable", "retired")
CV_CROP_RETRIEVAL_STATES = ("not_requested", "retrievable", "pending", "expired", "not_supported")
CV_VIDEO_DERIVATIVE_KINDS = ("none", "normalized")
CV_CANDIDATE_SEARCH_SCOPES = ("case_all_eligible_videos", "case_selected_videos")

CvRunStatus = Literal["queued", "running", "completed", "completed_with_warnings", "failed"]
CvReviewDecision = Literal["relevant", "irrelevant", "needs_review"]
CvWindowMode = Literal["full_video", "transaction_aligned"]
CvCandidateVerification = Literal["candidate_only"]
CvUnsupportedAttributeStatus = Literal["not_assessed"]
CvCropStatus = Literal["not_generated", "available", "unavailable", "retired"]
CvCropRetrievalState = Literal["not_requested", "retrievable", "pending", "expired", "not_supported"]
CvVideoDerivativeKind = Literal["none", "normalized"]
CvCandidateSearchScope = Literal["case_all_eligible_videos", "case_selected_videos"]
CvAssociationReviewState = Literal["proposed", "confirmed", "rejected", "insufficient_evidence"]
CvAssociationEvidenceStrength = Literal["strong", "moderate", "weak", "insufficient"]


def _validated_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError("must be a 64-character hexadecimal SHA-256 digest")
    return normalized


def _validated_opaque_id(value: str) -> str:
    if not value or any(character in value for character in ("/", "\\", ":", "\0")) or ".." in value:
        raise ValueError("must be an opaque identifier, not a filesystem path")
    return value


class CvVideoProvenance(BaseModel):
    source_video_id: str = Field(min_length=1, max_length=120)
    source_video_sha256: str
    derivative_kind: CvVideoDerivativeKind = "none"
    normalized_video_id: str | None = Field(default=None, max_length=120)
    normalized_video_sha256: str | None = None

    @field_validator("source_video_sha256", "normalized_video_sha256")
    @classmethod
    def validate_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validated_sha256(value)

    @model_validator(mode="after")
    def validate_derivative(self) -> "CvVideoProvenance":
        has_derivative = self.normalized_video_id is not None or self.normalized_video_sha256 is not None
        if self.derivative_kind == "normalized" and not has_derivative:
            raise ValueError("normalized_video_id and normalized_video_sha256 are required for a normalized derivative")
        if self.derivative_kind == "none" and has_derivative:
            raise ValueError("derivative_kind must be normalized when derivative identity is supplied")
        if has_derivative and (self.normalized_video_id is None or self.normalized_video_sha256 is None):
            raise ValueError("normalized_video_id and normalized_video_sha256 must be supplied together")
        return self


class AtmInteractionZone(BaseModel):
    name: str = Field(default="atm_interaction", min_length=1, max_length=120)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @field_validator("x", "y", "width", "height")
    @classmethod
    def validate_finite_coordinates(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("zone coordinates must be finite")
        return value

    @model_validator(mode="after")
    def validate_zone_geometry(self) -> "AtmInteractionZone":
        if self.x + self.width > 1:
            raise ValueError("zone extends beyond the right frame boundary")
        if self.y + self.height > 1:
            raise ValueError("zone extends beyond the bottom frame boundary")
        return self


class CvRunCreateRequest(CVAnalyzeRequest):
    case_id: str = Field(min_length=1, max_length=120)
    transaction_id: str | None = Field(default=None, max_length=120)
    transaction_ts: str | None = Field(default=None, max_length=80)
    cctv_ts: str | None = Field(default=None, max_length=80)
    normalized_video_id: str | None = Field(default=None, max_length=120)
    normalized_video_sha256: str | None = None
    window_mode: CvWindowMode = "full_video"
    before_seconds: float | None = Field(default=None, ge=0)
    after_seconds: float | None = Field(default=None, ge=0)
    video_start_ts: str | None = Field(default=None, max_length=80)
    cctv_reference_video_time: float = Field(default=0, ge=0)
    clock_offset_minutes: float | None = None
    atm_zone: AtmInteractionZone | None = None

    @field_validator("normalized_video_sha256")
    @classmethod
    def validate_normalized_video_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validated_sha256(value)

    @model_validator(mode="after")
    def validate_video_derivative(self) -> "CvRunCreateRequest":
        has_derivative = self.normalized_video_id is not None or self.normalized_video_sha256 is not None
        if has_derivative and (self.normalized_video_id is None or self.normalized_video_sha256 is None):
            raise ValueError("normalized_video_id and normalized_video_sha256 must be supplied together")
        return self

    @model_validator(mode="after")
    def validate_window_request(self) -> "CvRunCreateRequest":
        if self.window_mode == "transaction_aligned":
            if not self.transaction_id:
                raise ValueError("transaction_id is required for transaction_aligned analysis")
            if not self.transaction_ts or not self.cctv_ts:
                raise ValueError("transaction_ts and cctv_ts are required for transaction_aligned analysis")
            if self.before_seconds is None or self.after_seconds is None:
                raise ValueError("before_seconds and after_seconds are required for transaction_aligned analysis")
            if self.before_seconds + self.after_seconds < 1:
                raise ValueError("transaction_aligned analysis window must span at least 1 second")
        elif self.before_seconds is not None or self.after_seconds is not None:
            raise ValueError("before_seconds and after_seconds are only valid for transaction_aligned analysis")
        return self

    @model_validator(mode="after")
    def validate_atm_zone_request(self) -> "CvRunCreateRequest":
        if self.atm_zone is not None and (
            self.window_mode != "transaction_aligned" or not self.transaction_id
        ):
            raise ValueError("ATM zone association requires a transaction_aligned run with a transaction_id")
        return self


class CvBusyResponse(BaseModel):
    status: Literal["busy"] = "busy"
    detail: Literal["CV analysis busy; retry later"] = "CV analysis busy; retry later"
    retryable: Literal[True] = True
    retry_after_seconds: int = Field(default=5, ge=1)
    disclaimer: str = CV_CANDIDATE_DISCLAIMER


class CvAnalysisWindow(BaseModel):
    mode: CvWindowMode
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    source_video_duration_seconds: float = Field(ge=0)
    is_full_video: bool
    before_seconds: float | None = Field(default=None, ge=0)
    after_seconds: float | None = Field(default=None, ge=0)
    clamped: bool = False
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_window(self) -> "CvAnalysisWindow":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        if abs(self.duration_seconds - (self.end_seconds - self.start_seconds)) > 0.001:
            raise ValueError("duration_seconds must equal end_seconds minus start_seconds")
        if self.is_full_video != (self.mode == "full_video"):
            raise ValueError("is_full_video must match mode")
        if self.start_seconds > self.source_video_duration_seconds or self.end_seconds > self.source_video_duration_seconds:
            raise ValueError("window bounds must remain within source_video_duration_seconds")
        return self


class CvTimestampProvenance(BaseModel):
    cv_run_id: str = Field(min_length=1, max_length=120)
    analysis_run_id: str = Field(min_length=1, max_length=120)
    video_provenance: CvVideoProvenance
    transaction_id: str | None = Field(default=None, max_length=120)
    transaction_utc: str | None = Field(default=None, max_length=80)
    cctv_clock_utc: str | None = Field(default=None, max_length=80)
    applied_alignment_offset_seconds: float | None = None
    alignment_source: str | None = Field(default=None, max_length=120)
    video_start_utc: str | None = Field(default=None, max_length=80)
    transaction_video_seconds: float | None = None
    window_start_seconds: float = Field(ge=0)
    window_end_seconds: float = Field(ge=0)
    timebase: Literal["source_video_seconds"] = "source_video_seconds"
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_window_seconds(self) -> "CvTimestampProvenance":
        if self.window_end_seconds <= self.window_start_seconds:
            raise ValueError("window_end_seconds must be greater than window_start_seconds")
        return self


class CvModelProvenance(BaseModel):
    model_key: str = Field(min_length=1, max_length=80)
    model_filename: str = Field(min_length=1, max_length=200)
    model_sha256: str
    model_source_url: str | None = Field(default=None, max_length=500)
    backend: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    runtime_state: Literal["configured", "observed", "fallback", "unknown"] = "configured"
    runtime: dict[str, Any] = Field(default_factory=dict)
    opencv_version: str = Field(min_length=1, max_length=80)
    pipeline_version: str = Field(min_length=1, max_length=120)
    embedding_schema_version: int = Field(ge=1)
    generated_at: str = Field(min_length=1, max_length=80)

    @field_validator("model_sha256")
    @classmethod
    def validate_model_sha256(cls, value: str) -> str:
        return _validated_sha256(value)


class CvBudgetSummary(BaseModel):
    requested_max_frames: int = Field(ge=1)
    analyzed_frames: int = Field(ge=0)
    frame_stride: int = Field(ge=1)
    max_analysis_frames: int = Field(ge=1)
    max_frame_stride: int = Field(ge=1)
    max_decoded_frames: int = Field(ge=1)
    max_clip_duration_seconds: float = Field(gt=0)
    max_top_k: int = Field(ge=1)
    max_response_bytes: int = Field(ge=1)
    concurrent_analyses: int = Field(ge=1)
    synchronous: Literal[True] = True


class CvTruncationSummary(BaseModel):
    truncated: bool = False
    face_observations_omitted: int = Field(default=0, ge=0)
    person_observations_omitted: int = Field(default=0, ge=0)
    ranking_candidates_omitted: int = Field(default=0, ge=0)
    frames_omitted: int = Field(default=0, ge=0)
    near_duplicate_faces_suppressed: int = Field(default=0, ge=0)
    crop_observations_unavailable: int = Field(default=0, ge=0)
    reasons: list[str] = Field(default_factory=list)


class CvProcessingProvenance(BaseModel):
    cv_run_id: str = Field(min_length=1, max_length=120)
    analysis_run_id: str = Field(min_length=1, max_length=120)
    pipeline_version: str = Field(min_length=1, max_length=120)
    stage: str = Field(default="", max_length=120)
    message: str = Field(default="", max_length=1000)
    model_provenance: list[CvModelProvenance] = Field(default_factory=list)
    budget: CvBudgetSummary
    truncation: CvTruncationSummary


class CvCropSummary(BaseModel):
    crop_id: str | None = Field(default=None, max_length=120)
    available: bool = False
    status: CvCropStatus = "not_generated"
    retrieval_state: CvCropRetrievalState = "not_supported"

    @field_validator("crop_id")
    @classmethod
    def validate_crop_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validated_opaque_id(value)

    @model_validator(mode="after")
    def validate_crop_consistency(self) -> "CvCropSummary":
        if self.status == "available" and (not self.available or not self.crop_id):
            raise ValueError("an available crop requires crop_id and available=true")
        if self.status != "available" and self.available:
            raise ValueError("available=true requires status=available")
        return self


class CvQualitySummary(BaseModel):
    quality_score: float = Field(ge=0, le=100)
    sharpness: float = Field(ge=0)
    brightness: float = Field(ge=0)
    contrast: float = Field(ge=0)
    face_size_px: int = Field(ge=0)
    crop_size_px: int = Field(default=0, ge=0)
    occlusion_status: str = "unknown"
    components: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = "Image usability only; not an identity, biometric or attribute-classification result."


class CvReviewFlags(BaseModel):
    low_sharpness: bool = False
    underexposed: bool = False
    overexposed: bool = False
    small_face: bool = False
    pose_away: bool = False
    partial_occlusion_suspected: bool = False
    occlusion_review: bool = False
    mask: CvUnsupportedAttributeStatus = CV_UNSUPPORTED_ATTRIBUTE_STATUS
    helmet: CvUnsupportedAttributeStatus = CV_UNSUPPORTED_ATTRIBUTE_STATUS
    cap: CvUnsupportedAttributeStatus = CV_UNSUPPORTED_ATTRIBUTE_STATUS


class CvPoseSummary(BaseModel):
    roll_proxy_deg: float | None = Field(default=None, ge=0, le=180)
    yaw_proxy: float | None = Field(default=None, ge=0, le=2)
    pitch_proxy: float | None = Field(default=None, ge=0, le=2)
    frontal_score: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)
    method: str = "geometric proxies from five facial landmarks; not calibrated 3D pose"


class CvFaceObservationSummary(BaseModel):
    observation_id: str = Field(min_length=1, max_length=120)
    cv_sample_id: str = Field(min_length=1, max_length=200)
    cv_run_id: str = Field(min_length=1, max_length=120)
    case_id: str = Field(min_length=1, max_length=120)
    video_provenance: CvVideoProvenance
    original_frame_number: int = Field(ge=0)
    original_video_timestamp_seconds: float = Field(ge=0)
    analysis_relative_timestamp_seconds: float | None = None
    extracted_frame_id: str | None = Field(default=None, max_length=120)
    bbox: list[float]
    detector_confidence: float = Field(ge=0, le=1)
    track_id: int | None = None
    quality: CvQualitySummary
    review_flags: CvReviewFlags
    pose: CvPoseSummary
    crop: CvCropSummary = Field(default_factory=CvCropSummary)
    verification_status: CvCandidateVerification = CV_CANDIDATE_VERIFICATION_STATUS
    requires_human_verification: Literal[True] = True
    candidate_disclaimer: str = CV_CANDIDATE_DISCLAIMER

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError("bbox must contain exactly four values")
        return value


class CvCandidateSearchRequest(BaseModel):
    case_id: str = Field(min_length=1, max_length=120)
    query_cv_run_id: str = Field(min_length=1, max_length=120)
    query_observation_id: str = Field(min_length=1, max_length=120)
    top_k: int = Field(default=5, ge=1, le=CV_MAX_TOP_K)
    scope: CvCandidateSearchScope = "case_all_eligible_videos"
    source_video_ids: list[str] = Field(default_factory=list, max_length=CV_MAX_TOP_K)
    disclaimer: str = CV_CANDIDATE_DISCLAIMER

    @field_validator("case_id", "query_cv_run_id", "query_observation_id", "source_video_ids")
    @classmethod
    def validate_opaque_identifiers(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [_validated_opaque_id(str(item)) for item in value]
        return _validated_opaque_id(str(value))

    @model_validator(mode="after")
    def validate_scope(self) -> "CvCandidateSearchRequest":
        if self.scope == "case_selected_videos" and not self.source_video_ids:
            raise ValueError("source_video_ids are required for case_selected_videos scope")
        if self.scope == "case_all_eligible_videos" and self.source_video_ids:
            raise ValueError("source_video_ids are only valid for case_selected_videos scope")
        return self


class CvCandidateSummary(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=120)
    case_id: str = Field(min_length=1, max_length=120)
    query_cv_run_id: str = Field(min_length=1, max_length=120)
    query_observation_id: str = Field(min_length=1, max_length=120)
    candidate_cv_run_id: str = Field(min_length=1, max_length=120)
    candidate_observation_id: str = Field(min_length=1, max_length=120)
    candidate_video_provenance: CvVideoProvenance
    candidate_original_frame_number: int = Field(ge=0)
    candidate_original_video_timestamp_seconds: float = Field(ge=0)
    candidate_analysis_relative_timestamp_seconds: float | None = None
    candidate_extracted_frame_id: str | None = Field(default=None, max_length=120)
    similarity_score: float = Field(ge=-1, le=1)
    rank: int = Field(ge=1)
    model_provenance: list[CvModelProvenance]
    human_review_status: CvReviewDecision | None = None
    candidate_quality: CvQualitySummary | None = None
    candidate_review_flags: CvReviewFlags | None = None
    candidate_crop: CvCropSummary | None = None
    verification_status: CvCandidateVerification = CV_CANDIDATE_VERIFICATION_STATUS
    requires_human_verification: Literal[True] = True
    candidate_disclaimer: str = CV_CANDIDATE_DISCLAIMER
    score_meaning: str = CV_SIMILARITY_SCORE_MEANING


class CvReviewUpsertRequest(BaseModel):
    case_id: str = Field(min_length=1, max_length=120)
    cv_run_id: str = Field(min_length=1, max_length=120)
    target_type: Literal["face_observation"] = "face_observation"
    decision: CvReviewDecision
    reviewer_note: str | None = Field(default=None, max_length=4000)


class CvHumanReviewDecision(BaseModel):
    decision_id: str = Field(min_length=1, max_length=120)
    case_id: str = Field(min_length=1, max_length=120)
    cv_run_id: str = Field(min_length=1, max_length=120)
    target_type: Literal["face_observation", "candidate"]
    target_id: str = Field(min_length=1, max_length=120)
    decision: CvReviewDecision
    reviewer_note: str | None = Field(default=None, max_length=4000)
    created_at: str = Field(min_length=1, max_length=80)
    updated_at: str | None = Field(default=None, max_length=80)
    disclaimer: str = CV_CANDIDATE_DISCLAIMER


class CvBestFaceLinkSummary(BaseModel):
    method: str = Field(min_length=1, max_length=200)
    person_track_id: int
    face_track_id: int | None = None
    person_observation_id: str = Field(min_length=1, max_length=120)
    original_frame_number: int = Field(ge=0)
    original_video_timestamp_seconds: float = Field(ge=0)
    bbox_containment_ratio: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)


class CvFaceReliabilityIndicator(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    status: str = Field(min_length=1, max_length=120)
    evidence: list[str] = Field(default_factory=list)
    limitation: str = Field(min_length=1, max_length=500)
    assessment_type: Literal["measured", "heuristic", "not_assessed"]
    measured: dict[str, Any] = Field(default_factory=dict)


class CvFaceReliabilityAssessment(BaseModel):
    status: Literal["usable", "limited", "poor", "not_assessed"]
    summary: str = Field(min_length=1, max_length=500)
    limitation: str = Field(min_length=1, max_length=500)
    requires_human_verification: Literal[True] = True
    indicators: list[CvFaceReliabilityIndicator] = Field(default_factory=list)


class CvBestFaceRankedFrame(BaseModel):
    observation: CvFaceObservationSummary
    rank: int | None = Field(default=None, ge=1)
    selection_score: float = Field(ge=0, le=1)
    eligible: bool
    reason_codes: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    quality_indicators: dict[str, float] = Field(default_factory=dict)
    reliability: CvFaceReliabilityAssessment | None = None
    link: CvBestFaceLinkSummary | None = None


class CvBestFaceSelectionSummary(BaseModel):
    status: Literal["selected", "no_selection"]
    selected_observation_id: str | None = Field(default=None, max_length=120)
    selected_frame_number: int | None = Field(default=None, ge=0)
    selected_timestamp_seconds: float | None = Field(default=None, ge=0)
    selected_selection_score: float | None = Field(default=None, ge=0, le=1)
    selected_reliability_status: Literal["usable", "limited", "poor", "not_assessed"] | None = None
    selected_reliability_summary: str | None = Field(default=None, max_length=500)
    ranked_frame_count: int = Field(ge=0)
    rejected_frame_count: int = Field(ge=0)
    other_person_frame_count: int = Field(ge=0)
    no_selection_reason: str | None = Field(default=None, max_length=200)
    score_meaning: str = CV_BEST_FACE_SCORE_MEANING
    limitation: str = CV_BEST_FACE_LIMITATION


class CvBestFaceSelectionResponse(BaseModel):
    case_id: str = Field(min_length=1, max_length=120)
    cv_run_id: str = Field(min_length=1, max_length=120)
    association_id: str = Field(min_length=1, max_length=120)
    person_track_id: int | None = None
    association_review_state: str = Field(min_length=1, max_length=80)
    selected: CvBestFaceRankedFrame | None = None
    ranked_frames: list[CvBestFaceRankedFrame] = Field(default_factory=list)
    rejected_frames: list[CvBestFaceRankedFrame] = Field(default_factory=list)
    other_person_frames: list[CvBestFaceRankedFrame] = Field(default_factory=list)
    no_selection_reason: str | None = Field(default=None, max_length=200)
    methodology: dict[str, Any] = Field(default_factory=dict)
    score_meaning: str = CV_BEST_FACE_SCORE_MEANING
    limitation: str = CV_BEST_FACE_LIMITATION
    requires_human_verification: Literal[True] = True
    original_evidence_preserved: Literal[True] = True


class TransactionPersonAssociationRecord(BaseModel):
    association_id: str = Field(min_length=1, max_length=120)
    case_id: str = Field(min_length=1, max_length=120)
    transaction_id: str | None = Field(default=None, max_length=120)
    cv_run_id: str = Field(min_length=1, max_length=120)
    video_provenance: CvVideoProvenance
    zone_id: str = Field(min_length=1, max_length=120)
    person_track_id: int | None = None
    review_state: CvAssociationReviewState
    evidence_strength: CvAssociationEvidenceStrength
    heuristic_score: float = Field(ge=0, le=1)
    score_meaning: str = CV_ASSOCIATION_EVIDENCE_MEANING
    dwell_seconds: float = Field(ge=0)
    zone_frame_count: int = Field(ge=0)
    transaction_window_overlap_seconds: float = Field(ge=0)
    first_video_timestamp_seconds: float | None = None
    last_video_timestamp_seconds: float | None = None
    transaction_video_seconds: float | None = None
    window_start_seconds: float = Field(ge=0)
    window_end_seconds: float = Field(ge=0)
    evidence: dict[str, Any] = Field(default_factory=dict)
    reviewer_note: str | None = Field(default=None, max_length=4000)
    reviewed_at: str | None = Field(default=None, max_length=80)
    created_at: str = Field(min_length=1, max_length=80)
    updated_at: str = Field(min_length=1, max_length=80)
    verification_status: CvCandidateVerification = CV_CANDIDATE_VERIFICATION_STATUS
    requires_human_verification: Literal[True] = True
    association_disclaimer: str = CV_ASSOCIATION_LIMITATION
    best_face: CvBestFaceSelectionSummary | None = None


class TransactionPersonAssociationReviewRequest(BaseModel):
    case_id: str = Field(min_length=1, max_length=120)
    cv_run_id: str = Field(min_length=1, max_length=120)
    decision: Literal["confirmed", "rejected"]
    reviewer_note: str | None = Field(default=None, max_length=4000)


class CvRunSummary(BaseModel):
    cv_run_id: str = Field(min_length=1, max_length=120)
    case_id: str = Field(min_length=1, max_length=120)
    video_provenance: CvVideoProvenance
    transaction_id: str | None = Field(default=None, max_length=120)
    status: CvRunStatus
    window_mode: CvWindowMode
    window: CvAnalysisWindow | None = None
    analysis_run_id: str = Field(min_length=1, max_length=120)
    created_at: str = Field(min_length=1, max_length=80)
    started_at: str | None = Field(default=None, max_length=80)
    finished_at: str | None = Field(default=None, max_length=80)
    message: str = Field(default="", max_length=1000)
    warnings: list[str] = Field(default_factory=list)
    budget: CvBudgetSummary
    truncation: CvTruncationSummary
    timestamp_provenance: CvTimestampProvenance | None = None
    model_provenance: list[CvModelProvenance] = Field(default_factory=list)
    atm_zone: AtmInteractionZone | None = None
    disclaimer: str = CV_CANDIDATE_DISCLAIMER
