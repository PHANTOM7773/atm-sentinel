export interface CaseRecord {
  id: string;
  case_number: string;
  title: string;
  location: string;
  tags: string;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
}

export interface TransactionRecord {
  id: string;
  case_id: string;
  reference: string;
  atm_id: string;
  transaction_ts: string;
  cctv_ts: string;
  transaction_type: string;
  amount: string;
  note: string;
  created_at: string;
}

export interface VideoRecord {
  id: string;
  case_id: string;
  original_filename: string;
  stored_path: string;
  size_bytes: number;
  sha256: string;
  tags: string;
  container: string;
  codec: string;
  width: number;
  height: number;
  fps: number;
  duration: number;
  stream_count: number;
  integrity_status: string;
  integrity_detail: string;
  uploaded_at: string;
  metadata?: Record<string, unknown>;
}

export interface JobRecord {
  id: string;
  case_id: string;
  video_id: string;
  transaction_id: string;
  status: string;
  stage: string;
  progress: number;
  message: string;
  config_json: string;
  alignment_json: string;
  cancel_requested: number;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  alignment?: AlignmentResult;
  config?: Record<string, unknown>;
}

export interface AlignmentResult {
  transaction_utc: string;
  cctv_utc: string;
  derived_offset_seconds: number;
  offset_seconds: number;
  offset_minutes: number;
  offset_source: string;
  video_start_utc: string;
  transaction_cctv_utc: string;
  transaction_video_seconds: number;
  video_duration: number;
  window_start_seconds: number;
  window_end_seconds: number;
  analysis_span_seconds: number;
  warnings: string[];
}

export interface FrameRecord {
  id: string;
  job_id: string;
  video_id: string;
  case_id: string;
  frame_number: number;
  timestamp: number;
  relative_time: number;
  image_path: string;
  thumb_path: string;
  sha256: string;
  sharpness: number;
  brightness: number;
  contrast: number;
  quality_score: number;
  warnings: string[];
  metrics: Record<string, unknown>;
  source: string;
  created_at: string;
  selected: boolean;
  selection_note: string;
  selection_reason: string;
  frame_notes: NoteRecord[];
}

export interface NoteRecord {
  id: string;
  case_id: string;
  video_id: string | null;
  frame_id: string | null;
  body: string;
  created_at: string;
}

export interface ClipLink {
  id: string;
  case_id: string;
  video_a: string;
  video_b: string;
  reason: string;
  created_at: string;
}

export interface ExportRecord {
  id: string;
  case_id: string;
  pdf_path: string;
  manifest_path: string;
  report_hash: string;
  pdf_sha256: string;
  frame_count: number;
  cv_selection_count?: number;
  cv_candidate_count?: number;
  cv_observation_count?: number;
  created_at: string;
}

export const CV_EXPORT_SELECTION_KEY = "atm:cv-export-selection" as const;
export const CV_EXPORT_MAX_ITEMS = 25;
export const CV_EXPORT_ITEM_KINDS = ["observation", "candidate"] as const;
export type CvExportItemKind = (typeof CV_EXPORT_ITEM_KINDS)[number];
export interface CvExportSelectionContext {
  rank?: number;
  similarity_score?: number;
  score_meaning?: string;
  candidate_disclaimer?: string;
}
export interface CvExportItem {
  kind: CvExportItemKind;
  cv_run_id: string;
  observation_id: string;
  query_cv_run_id?: string;
  query_observation_id?: string;
  candidate_id?: string;
  expected_review_updated_at?: string;
  expected_model_sha256?: string;
  selection_context?: CvExportSelectionContext;
}
export interface ExportRequestPayload {
  case_id: string;
  frame_ids: string[];
  cv_items?: CvExportItem[];
}

export interface AuditEvent {
  id: number;
  case_id: string | null;
  action: string;
  detail_json: string;
  created_at: string;
}

export interface SystemStatus {
  app: string;
  version: string;
  counts: Record<string, number>;
  dependencies: Record<string, boolean>;
  tool_versions: Record<string, string>;
  quality_score_limitations: string;
  recent_activity: AuditEvent[];
  disclaimer: string;
}

export type SessionMode = "open" | "secured";
export interface SessionResponse {
  mode: SessionMode;
}
export interface SessionState {
  mode: SessionMode;
  protectedAccess: boolean;
}
export type ServiceHealthState = "loading" | "healthy" | "degraded" | "error";

export interface TimelineEvent {
  at: string;
  type: string;
  label: string;
  detail: string;
}

export const CV_RUN_STATUSES = ["queued", "running", "completed", "completed_with_warnings", "failed"] as const;
export const CV_REVIEW_DECISIONS = ["relevant", "irrelevant", "needs_review"] as const;
export const CV_WINDOW_MODES = ["full_video", "transaction_aligned"] as const;
export const CV_CANDIDATE_VERIFICATION_STATUS = "candidate_only" as const;
export const CV_CANDIDATE_DISCLAIMER = "Similarity candidate only; requires human verification. Never identity confirmation." as const;
export const CV_ASSOCIATION_LIMITATION = "Detected faces, person detections, track IDs, similarity scores and review decisions do not identify the ATM operator, cardholder, cashier or any transaction participant. A proposed transaction-person association is a reviewable link hypothesis from observed zone, dwell and timing evidence; it is never identity confirmation." as const;
export const CV_ATM_ZONE_COORDINATE_CONVENTION = "Frame-relative normalized top-left coordinates: x, y, width and height are fractions of source frame width and height in 0..1, with x+width<=1 and y+height<=1." as const;
export const CV_ASSOCIATION_EVIDENCE_MEANING = "Heuristic evidence-strength score from 0 to 1 combining zone overlap, observed dwell, transaction-window timing, track continuity and detector confidence; it is not a calibrated probability or identity likelihood." as const;
export const CV_ASSOCIATION_REVIEW_STATES = ["proposed", "confirmed", "rejected", "insufficient_evidence"] as const;
export const CV_ASSOCIATION_EVIDENCE_STRENGTHS = ["strong", "moderate", "weak", "insufficient"] as const;
export const CV_UNSUPPORTED_ATTRIBUTE_STATUS = "not_assessed" as const;
export const CV_CROP_STATUSES = ["not_generated", "available", "unavailable", "retired"] as const;
export const CV_CROP_RETRIEVAL_STATES = ["not_requested", "retrievable", "pending", "expired", "not_supported"] as const;
export const CV_VIDEO_DERIVATIVE_KINDS = ["none", "normalized"] as const;
export const CV_CANDIDATE_SEARCH_SCOPES = ["case_all_eligible_videos", "case_selected_videos"] as const;
export const CV_CANDIDATE_SCAN_REASONS = ["scan_limit", "top_k_reached", "exhausted"] as const;

export type CvRunStatus = (typeof CV_RUN_STATUSES)[number];
export type CvReviewDecision = (typeof CV_REVIEW_DECISIONS)[number];
export type CvWindowMode = (typeof CV_WINDOW_MODES)[number];
export type CvCandidateVerification = typeof CV_CANDIDATE_VERIFICATION_STATUS;
export type CvReviewTargetType = "face_observation" | "candidate";
export type CvModelRuntimeState = "configured" | "observed" | "fallback" | "unknown";
export type CvUnsupportedAttributeStatus = typeof CV_UNSUPPORTED_ATTRIBUTE_STATUS;
export type CvCropStatus = (typeof CV_CROP_STATUSES)[number];
export type CvCropRetrievalState = (typeof CV_CROP_RETRIEVAL_STATES)[number];
export type CvVideoDerivativeKind = (typeof CV_VIDEO_DERIVATIVE_KINDS)[number];
export type CvCandidateSearchScope = (typeof CV_CANDIDATE_SEARCH_SCOPES)[number];
export type CvCandidateScanReason = (typeof CV_CANDIDATE_SCAN_REASONS)[number];
export type CvAssociationReviewState = (typeof CV_ASSOCIATION_REVIEW_STATES)[number];
export type CvAssociationEvidenceStrength = (typeof CV_ASSOCIATION_EVIDENCE_STRENGTHS)[number];
export type CvPage<T> = { items: T[]; total: number; limit: number; offset: number };
export interface CvReviewUpsertRequest {
  case_id: string;
  cv_run_id: string;
  target_type: "face_observation";
  decision: CvReviewDecision;
  reviewer_note?: string | null;
}

export interface CvEmbeddingStatus {
  record_count: number;
  embedding_dim?: number;
  generation?: number;
  storage?: string;
  schema_version?: number;
  consistency?: string;
  provenance?: { known: number; legacy_unknown: number };
  index_path?: string;
  vectors_path?: string;
  disclaimer?: string;
}

export interface CvStatusResponse {
  models: Record<string, { verification?: string; usable?: boolean; [key: string]: unknown }>;
  runtime: Record<string, unknown>;
  opencv_version: string;
  thresholds: Record<string, number>;
  person_detection: Record<string, unknown>;
  limits: Record<string, unknown>;
  synchronous_analysis: boolean;
  embedding_store: CvEmbeddingStatus;
  limitations: string[];
  disclaimer: string;
}

export interface CvAnalyzeRequest {
  video_id: string;
  max_frames?: number | null;
  frame_stride?: number;
  save_crops?: boolean;
  add_to_index?: boolean;
  rank?: boolean;
  summary_only?: boolean;
  top_k?: number;
  labels?: Record<string, string> | null;
}

export interface CvAnalyzeResponse {
  analysis: {
    analysis_run_id: string;
    frames?: unknown[];
    summary?: Record<string, unknown>;
    [key: string]: unknown;
  };
  ranking: Record<string, unknown> | null;
  embedding_store: CvEmbeddingStatus;
  analysis_run_id: string;
  summary_only: boolean;
  limits: Record<string, unknown>;
  disclaimer: string;
}

export interface CvEmbeddingsResponse {
  store: CvEmbeddingStatus;
  disclaimer: string;
}

export interface CvVideoProvenance {
  source_video_id: string;
  source_video_sha256: string;
  derivative_kind: CvVideoDerivativeKind;
  normalized_video_id?: string | null;
  normalized_video_sha256?: string | null;
}

export interface AtmInteractionZone {
  name?: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CvRunCreateRequest extends CvAnalyzeRequest {
  case_id: string;
  transaction_id?: string | null;
  transaction_ts?: string | null;
  cctv_ts?: string | null;
  normalized_video_id?: string | null;
  normalized_video_sha256?: string | null;
  window_mode?: CvWindowMode;
  before_seconds?: number | null;
  after_seconds?: number | null;
  video_start_ts?: string | null;
  cctv_reference_video_time?: number;
  clock_offset_minutes?: number | null;
  atm_zone?: AtmInteractionZone | null;
}

export interface CvBusyResponse {
  status: "busy";
  detail: "CV analysis busy; retry later";
  retryable: true;
  retry_after_seconds: number;
  disclaimer: string;
}

export interface CvAnalysisWindow {
  mode: CvWindowMode;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  source_video_duration_seconds: number;
  is_full_video: boolean;
  before_seconds?: number | null;
  after_seconds?: number | null;
  clamped: boolean;
  warnings: string[];
}

export interface CvTimestampProvenance {
  cv_run_id: string;
  analysis_run_id: string;
  video_provenance: CvVideoProvenance;
  transaction_id?: string | null;
  transaction_utc?: string | null;
  cctv_clock_utc?: string | null;
  applied_alignment_offset_seconds?: number | null;
  alignment_source?: string | null;
  video_start_utc?: string | null;
  transaction_video_seconds?: number | null;
  window_start_seconds: number;
  window_end_seconds: number;
  timebase: "source_video_seconds";
  warnings: string[];
}

export interface CvModelProvenance {
  model_key: string;
  model_filename: string;
  model_sha256: string;
  model_source_url?: string | null;
  backend: string;
  target: string;
  runtime_state: CvModelRuntimeState;
  runtime: Record<string, unknown>;
  opencv_version: string;
  pipeline_version: string;
  embedding_schema_version: number;
  generated_at: string;
}

export interface CvBudgetSummary {
  requested_max_frames: number;
  analyzed_frames: number;
  frame_stride: number;
  max_analysis_frames: number;
  max_frame_stride: number;
  max_decoded_frames: number;
  max_clip_duration_seconds: number;
  max_top_k: number;
  max_response_bytes: number;
  concurrent_analyses: number;
  synchronous: true;
}

export interface CvTruncationSummary {
  truncated: boolean;
  face_observations_omitted: number;
  person_observations_omitted: number;
  ranking_candidates_omitted: number;
  frames_omitted: number;
  near_duplicate_faces_suppressed?: number;
  crop_observations_unavailable?: number;
  reasons: string[];
}

export interface CvProcessingProvenance {
  cv_run_id: string;
  analysis_run_id: string;
  pipeline_version: string;
  stage: string;
  message: string;
  model_provenance: CvModelProvenance[];
  budget: CvBudgetSummary;
  truncation: CvTruncationSummary;
}

export interface CvCropSummary {
  crop_id?: string | null;
  available: boolean;
  status: CvCropStatus;
  retrieval_state: CvCropRetrievalState;
}

export interface CvQualitySummary {
  quality_score: number;
  sharpness: number;
  brightness: number;
  contrast: number;
  face_size_px: number;
  crop_size_px?: number;
  occlusion_status?: string;
  components: Record<string, number>;
  warnings: string[];
  disclaimer: string;
}

export interface CvReviewFlags {
  low_sharpness: boolean;
  underexposed: boolean;
  overexposed: boolean;
  small_face: boolean;
  pose_away: boolean;
  partial_occlusion_suspected: boolean;
  occlusion_review?: boolean;
  mask: CvUnsupportedAttributeStatus;
  helmet: CvUnsupportedAttributeStatus;
  cap: CvUnsupportedAttributeStatus;
}

export interface CvPoseSummary {
  roll_proxy_deg?: number | null;
  yaw_proxy?: number | null;
  pitch_proxy?: number | null;
  frontal_score: number;
  warnings: string[];
  method: string;
}

export interface CvFaceObservationSummary {
  observation_id: string;
  cv_sample_id: string;
  cv_run_id: string;
  case_id: string;
  video_provenance: CvVideoProvenance;
  original_frame_number: number;
  original_video_timestamp_seconds: number;
  analysis_relative_timestamp_seconds?: number | null;
  extracted_frame_id?: string | null;
  bbox: number[];
  detector_confidence: number;
  track_id?: number | null;
  quality: CvQualitySummary;
  review_flags: CvReviewFlags;
  pose: CvPoseSummary;
  crop: CvCropSummary;
  verification_status: CvCandidateVerification;
  requires_human_verification: true;
  candidate_disclaimer: string;
}

export interface CvCandidateSearchRequest {
  case_id: string;
  query_cv_run_id: string;
  query_observation_id: string;
  top_k?: number;
  scope?: CvCandidateSearchScope;
  source_video_ids?: string[];
  disclaimer?: string;
}

export interface CvCandidateSummary {
  candidate_id: string;
  case_id: string;
  query_cv_run_id: string;
  query_observation_id: string;
  candidate_cv_run_id: string;
  candidate_observation_id: string;
  candidate_video_provenance: CvVideoProvenance;
  candidate_original_frame_number: number;
  candidate_original_video_timestamp_seconds: number;
  candidate_analysis_relative_timestamp_seconds?: number | null;
  candidate_extracted_frame_id?: string | null;
  similarity_score: number;
  rank: number;
  model_provenance: CvModelProvenance[];
  human_review_status?: CvReviewDecision | null;
  candidate_quality: CvQualitySummary | null;
  candidate_review_flags: CvReviewFlags | null;
  candidate_crop: CvCropSummary | null;
  verification_status: CvCandidateVerification;
  requires_human_verification: true;
  candidate_disclaimer: string;
  score_meaning: string;
}

export interface CvCandidateSearchResponse {
  items: CvCandidateSummary[];
  count: number;
  limit: number;
  scope: CvCandidateSearchScope;
  source_video_ids: string[];
  query: { case_id: string; cv_run_id: string; observation_id: string };
  score_meaning: string;
  disclaimer: string;
  index: {
    generation: number;
    schema_version: number;
    record_count: number;
    provenance: { known: number; legacy_unknown: number };
  };
  limits: {
    max_top_k: number;
    concurrent_analyses: number;
    candidate_scan: {
      limit: number;
      scanned: number;
      truncated: boolean;
      reason: CvCandidateScanReason;
    };
  };
}

export interface CvHumanReviewDecision {
  decision_id: string;
  case_id: string;
  cv_run_id: string;
  target_type: CvReviewTargetType;
  target_id: string;
  decision: CvReviewDecision;
  reviewer_note?: string | null;
  created_at: string;
  updated_at?: string | null;
  disclaimer?: string;
}

export interface CvFaceReliabilityIndicator {
  name: string;
  status: string;
  evidence: string[];
  limitation: string;
  assessment_type: "measured" | "heuristic" | "not_assessed";
  measured: Record<string, unknown>;
}

export interface CvFaceReliabilityAssessment {
  status: "usable" | "limited" | "poor" | "not_assessed";
  summary: string;
  limitation: string;
  requires_human_verification: true;
  indicators: CvFaceReliabilityIndicator[];
}

export interface CvBestFaceSelectionSummary {
  status: "selected" | "no_selection";
  selected_observation_id?: string | null;
  selected_frame_number?: number | null;
  selected_timestamp_seconds?: number | null;
  selected_selection_score?: number | null;
  selected_reliability_status?: "usable" | "limited" | "poor" | "not_assessed" | null;
  selected_reliability_summary?: string | null;
  ranked_frame_count: number;
  rejected_frame_count: number;
  other_person_frame_count: number;
  no_selection_reason?: string | null;
  score_meaning: string;
  limitation: string;
}

export interface CvBestFaceLinkSummary {
  method: string;
  person_track_id: number;
  face_track_id?: number | null;
  person_observation_id: string;
  original_frame_number: number;
  original_video_timestamp_seconds: number;
  bbox_containment_ratio: number;
  limitations: string[];
}

export interface CvBestFaceRankedFrame {
  observation: CvFaceObservationSummary;
  rank: number | null;
  selection_score: number;
  eligible: boolean;
  reason_codes: string[];
  rationale: string[];
  quality_indicators: Record<string, number>;
  reliability?: CvFaceReliabilityAssessment | null;
  link?: CvBestFaceLinkSummary | null;
}

export interface CvBestFaceSelectionResponse {
  case_id: string;
  cv_run_id: string;
  association_id: string;
  person_track_id?: number | null;
  association_review_state: string;
  selected?: CvBestFaceRankedFrame | null;
  ranked_frames: CvBestFaceRankedFrame[];
  rejected_frames: CvBestFaceRankedFrame[];
  other_person_frames: CvBestFaceRankedFrame[];
  no_selection_reason?: string | null;
  methodology: Record<string, unknown>;
  score_meaning: string;
  limitation: string;
  requires_human_verification: true;
  original_evidence_preserved: true;
}

export interface TransactionPersonAssociationRecord {
  association_id: string;
  case_id: string;
  transaction_id?: string | null;
  cv_run_id: string;
  video_provenance: CvVideoProvenance;
  zone_id: string;
  person_track_id?: number | null;
  review_state: CvAssociationReviewState;
  evidence_strength: CvAssociationEvidenceStrength;
  heuristic_score: number;
  score_meaning: string;
  dwell_seconds: number;
  zone_frame_count: number;
  transaction_window_overlap_seconds: number;
  first_video_timestamp_seconds?: number | null;
  last_video_timestamp_seconds?: number | null;
  transaction_video_seconds?: number | null;
  window_start_seconds: number;
  window_end_seconds: number;
  evidence: Record<string, unknown>;
  reviewer_note?: string | null;
  reviewed_at?: string | null;
  created_at: string;
  updated_at: string;
  verification_status: CvCandidateVerification;
  requires_human_verification: true;
  association_disclaimer: string;
  best_face?: CvBestFaceSelectionSummary | null;
}

export interface CvPersonAssociationPage extends CvPage<TransactionPersonAssociationRecord> {
  status: "proposed" | "insufficient_evidence";
  disclaimer: string;
}

export interface TransactionPersonAssociationReviewRequest {
  case_id: string;
  cv_run_id: string;
  decision: "confirmed" | "rejected";
  reviewer_note?: string | null;
}

export interface CvRunSummary {
  cv_run_id: string;
  case_id: string;
  video_provenance: CvVideoProvenance;
  transaction_id?: string | null;
  status: CvRunStatus;
  window_mode: CvWindowMode;
  analysis_run_id: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  message: string;
  warnings: string[];
  budget: CvBudgetSummary;
  truncation: CvTruncationSummary;
  timestamp_provenance?: CvTimestampProvenance | null;
  model_provenance?: CvModelProvenance[];
  disclaimer: string;
  window?: CvAnalysisWindow | null;
  atm_zone?: AtmInteractionZone | null;
  observation_count?: number | null;
}

export interface CvRunCreateResponse {
  run: CvRunSummary;
  observations: CvPage<CvFaceObservationSummary>;
  associations?: CvPersonAssociationPage;
}
