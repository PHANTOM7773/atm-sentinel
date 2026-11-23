# ATM Sentinel — CV Integration Contract

Status: Phase 2.1.1 contract definitions were subsequently implemented and extended through Stage 12. This document is the authoritative CV contract; current code is the source of truth for endpoint paths and response fields.

## Scope

This document defines the backend/frontend contract for the local CV investigation workflow. The Phase 1 modules under `backend/app/cv/` remain locally bounded. Persistent CV runs, observations, human review, candidate search, crops, and explicitly selected CV export references are implemented.

Locked decisions:

- A CV run belongs to one case and one source video.
- A transaction link is optional.
- CV runs are independent of frame-extraction processing jobs.
- Analysis supports `transaction_aligned` windows and an explicit `full_video` option.
- Candidate search is strictly case-scoped.
- The server always excludes the query source video from its candidate gallery; clients cannot change this.
- Candidates are similarity candidates requiring human verification, not identity findings.
- Review decisions are limited to `relevant`, `irrelevant`, and `needs_review`; reviewer notes are optional for every decision.
- Original video and extracted original frames are never modified.
- CV crops are derived supporting artifacts, not replacements for original evidence.
- No public DTO exposes a local filesystem path.

## Lifecycle

`CvRunStatus` values:

- `queued`: accepted for future processing; no asynchronous execution exists today.
- `running`: analysis in progress.
- `completed`: analysis finished without warnings.
- `completed_with_warnings`: analysis finished with alignment, truncation, quality, or budget warnings.
- `failed`: terminal failure.

Allowed transitions: `queued -> running -> completed | completed_with_warnings | failed`. Terminal states do not transition.

`POST /api/cv/analyze` remains synchronous and does not create a CV run record; `POST /api/cv/runs` is the persistent CV run entry point.

## Busy responses

Today `POST /api/cv/analyze` returns HTTP 503 with body `{"detail":"CV analysis busy; retry later"}` and header `Retry-After: 5`.

A typed `CvBusyResponse` schema exists for a future richer response, but the current endpoint returns only `detail`:

- `status: "busy"`
- `detail: "CV analysis busy; retry later"`
- `retryable: true`
- `retry_after_seconds: >= 1`
- `disclaimer`

HTTP 503 remains the transport-level response. `retry_after_seconds` must mirror `Retry-After` when both are present.

## DTOs

Backend DTOs are defined in `backend/app/schemas.py`; TypeScript mirrors are in `frontend/src/lib/types.ts`.

### Request DTOs

- `CvRunCreateRequest`: inherits `CVAnalyzeRequest`; adds `case_id`, `transaction_id`, `transaction_ts`, `cctv_ts`, optional normalized video identity, `window_mode`, `before_seconds`, `after_seconds`, `video_start_ts`, `cctv_reference_video_time`, and `clock_offset_minutes`.
  - `transaction_aligned` requires a transaction ID, transaction timestamp, CCTV clock timestamp, and both window bounds.
  - `full_video` rejects `before_seconds`/`after_seconds`.
  - `normalized_video_id` and `normalized_video_sha256` must be supplied together and never replace the original source identity.
- `CvCandidateSearchRequest`: `case_id`, query run/observation, `top_k`, `scope`, and optional `source_video_ids`.
  - Default scope is `case_all_eligible_videos`.
  - Optional scope is `case_selected_videos`, which requires a non-empty selected video list.
  - No client field controls query-source exclusion.

### Window and provenance DTOs

- `CvAnalysisWindow`: `mode`, `start_seconds`, `end_seconds`, `duration_seconds`, `source_video_duration_seconds`, `is_full_video`, `before_seconds`, `after_seconds`, `clamped`, `warnings`.
- `CvTimestampProvenance`: run/analysis IDs, `video_provenance`, transaction/CCTV/video-start timestamps in UTC, `applied_alignment_offset_seconds`, `alignment_source`, `transaction_video_seconds`, `window_start_seconds`, `window_end_seconds`, `timebase`, `warnings`.
- `CvVideoProvenance`: `source_video_id`, `source_video_sha256`, `derivative_kind`, optional `normalized_video_id`, optional `normalized_video_sha256`.
- `CvModelProvenance`: one model's key, filename, SHA-256, source URL, backend/target/runtime, OpenCV version, pipeline version, embedding schema version, and generation time.
- `CvBudgetSummary`: requested and analyzed frames, stride, configured limits, concurrency, and synchronous flag.
- `CvTruncationSummary`: truncation flag, omitted observations/candidates/frames, and reasons.
- `CvProcessingProvenance`: run/analysis IDs, pipeline stage/message, `model_provenance` list, budget, and truncation.

### Observation, crop, and candidate DTOs

- `CvFaceObservationSummary`: observation/sample/run IDs, case, `video_provenance`, original frame/timestamp, optional analysis-relative timestamp, optional extracted-frame ID, bbox, confidence, track ID, quality, review flags, pose, `crop`, and candidate-only fields.
- `CvCropSummary`: opaque `crop_id`, `available`, `status`, and `retrieval_state`.
- `CvQualitySummary`: explainable image-usability metrics and warnings.
- `CvReviewFlags`: boolean review flags plus `mask`, `helmet`, and `cap` fixed to `not_assessed`.
- `CvPoseSummary`: geometric pose proxies and warnings.
- `CvCandidateSummary`: query/candidate run and observation IDs, case, `candidate_video_provenance`, original timestamp/frame reference, similarity score/rank, `model_provenance` list, optional human review status, and candidate-only fields.
- `CvHumanReviewDecision`: decision ID, case/run/target, one of `relevant`/`irrelevant`/`needs_review`, optional `reviewer_note`, timestamp, and disclaimer.

Every observation and candidate carries:

- `verification_status: "candidate_only"`
- `requires_human_verification: true`
- `candidate_disclaimer: "Similarity candidate only; requires human verification. Never identity confirmation."`

Raw embedding vectors and crop bytes are intentionally absent from all DTOs.

## Timestamp semantics

### Sign convention

- `clock_offset_minutes` is `CCTV_clock - transaction_clock`, in minutes.
- Positive means the CCTV clock is ahead of the transaction clock.
- Negative means the CCTV clock is behind the transaction clock.
- `applied_alignment_offset_seconds` is the same offset in seconds: `clock_offset_minutes * 60`.
- If `clock_offset_minutes` is omitted, the server derives the offset from `cctv_ts - transaction_ts`.

### Exact conversion

All parsed timestamps are normalized to UTC. Naive timestamps are interpreted as UTC and produce a warning.

```text
offset_seconds = clock_offset_minutes * 60
              if clock_offset_minutes is provided
              else (cctv_ts - transaction_ts).total_seconds()

transaction_in_cctv_utc = transaction_ts + offset_seconds

video_start_utc = video_start_ts
              if provided
              else cctv_ts - cctv_reference_video_time_seconds

transaction_video_seconds = (transaction_in_cctv_utc - video_start_utc).total_seconds()
```

`timebase` is always `source_video_seconds`. `transaction_video_seconds`, `window_start_seconds`, `window_end_seconds`, `original_video_timestamp_seconds`, and `analysis_relative_timestamp_seconds` are measured from the authoritative source video's start. No other timebase field exists.

`analysis_relative_timestamp_seconds` equals `original_video_timestamp_seconds - window_start_seconds` and is only meaningful for windowed analysis.

### Window clamping and out-of-range behavior

For `full_video`:

```text
start_seconds = 0
end_seconds = source_video_duration_seconds
```

For `transaction_aligned`:

```text
raw_start = transaction_video_seconds - before_seconds
raw_end = transaction_video_seconds + after_seconds
start_seconds = clamp(raw_start, 0, source_video_duration_seconds)
end_seconds = clamp(raw_end, 0, source_video_duration_seconds)
```

Clamping is allowed only at the source-video boundaries. When either bound changes, `clamped` is `true` and a warning is added.

Out-of-range behavior:

- If `end_seconds <= start_seconds`, the request is invalid.
- If `transaction_video_seconds - before_seconds >= source_video_duration_seconds`, the requested window is after the video and is invalid.
- If `transaction_video_seconds + after_seconds <= 0`, the requested window is before the video and is invalid.
- No negative timestamps or synthetic frames are produced.

## Video provenance

- `source_video_id` and `source_video_sha256` are authoritative original evidence identity.
- A normalized derivative, when used, carries its own `normalized_video_id` and `normalized_video_sha256`.
- `derivative_kind` is `none` when no derivative is used and `normalized` when derivative identity is supplied.
- Original identity is never replaced by derivative identity in runs, observations, candidates, timestamps, or exports.

## Crop representation

- Public DTOs use only `CvCropSummary` with opaque `crop_id`, `available`, `status`, and `retrieval_state`.
- `crop_status` values: `not_generated`, `available`, `unavailable`, `retired`.
- `crop_retrieval_state` values: `not_requested`, `retrievable`, `pending`, `expired`, `not_supported`.
- The crop endpoint serves only derived crops marked retrievable; `retrieval_state` must not claim retrievability for expired or unavailable artifacts.
- Absolute or relative local filesystem paths are never exposed.

## Unsupported visual attributes

- `mask`, `helmet`, and `cap` default to `not_assessed` and do not accept presence or absence values.
- `partial_occlusion_suspected` is a heuristic review signal only and is distinct from validated object detection.
- No public DTO carries an identity-state field or identity decision.

## Candidate-search security semantics

- Scope defaults to all eligible videos in the requested `case_id`.
- `case_selected_videos` narrows the search to `source_video_ids`.
- The server must validate every selected video belongs to `case_id` before searching.
- If any selected video is outside the case, the server must reject the request.
- The server always excludes the query source video from its own candidate gallery.
- Query-source exclusion is an unconditional server invariant, not a client option.
- Candidates must never be presented as identity findings and require human verification.

## Existing versus proposed endpoints

Implemented today:

- `GET /api/cv/status`
- `GET /api/cv/embeddings`
- `POST /api/cv/analyze`
- `POST /api/cv/runs` using `CvRunCreateRequest`, returning `CvRunSummary`
- `GET /api/cv/runs/{cv_run_id}` returning `CvRunSummary`
- `GET /api/cv/runs/{cv_run_id}/observations` returning `CvFaceObservationSummary` rows
- `GET /api/cv/runs/{cv_run_id}/observations/{observation_id}/review`
- `POST /api/cv/runs/{cv_run_id}/observations/{observation_id}/review`
- `GET /api/cv/runs/{cv_run_id}/observations/{observation_id}/crop`
- `POST /api/cv/candidates/search` using `CvCandidateSearchRequest`, returning `CvCandidateSummary` rows

Typed client methods for these endpoints are in `frontend/src/lib/api.ts` under `cvApi`.

## Backward compatibility

The original synchronous CV endpoint contracts are unchanged. Persistent-run, review, crop, candidate-search, and export-selection DTOs are additive. The generic `api` helper is unchanged; a separate `cvApi` object adds typed methods for CV endpoints.

## Remaining ambiguities

- Browser-level smoke automation is optional hardening, not a functional requirement.
- Advanced timeline visualization is optional future work.
- Evidence export accepts only explicit CV selections; automatic inclusion of all candidates remains intentionally unsupported.
