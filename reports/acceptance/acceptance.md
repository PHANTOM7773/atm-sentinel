# ATM Sentinel Acceptance Report

- Generated: `2026-11-23T03:51:55+00:00`
- Overall status: **PASS**
- Runner version: `1.0.0`
- App version: `0.1.0`
- Scope: local synthetic acceptance; no real CCTV/R4C validation

## Summary

| Area | Status | Evidence |
| --- | --- | --- |
| A Environment, local models, configured limits | PASS | Python package checks, ffmpeg/ffprobe paths, model SHA-256 verification, /api/cv/status limit source |
| B Multi-format input and normalization | PASS | backend tests: security, video, pipeline; isolated 12-clip synthetic scenario |
| C Transaction timestamp and aligned windows | PASS | backend tests: timestamps and CV alignment |
| D Quality scores and best-frame support | PASS | backend tests: quality, CV engine, CV accuracy evidence; synthetic scenario |
| E Face/person detection and clip-local tracking | PASS | backend tests: CV engine and CV accuracy evidence |
| F Cross-video candidate search and source exclusion | PASS | 12-clip scenario plus backend CV candidate search suite |
| G Investigator review and candidate integrity | PASS | 12-clip scenario plus backend CV review suite |
| H Explicit CV-reference export and provenance | PASS | 12-clip scenario plus backend export/CV export tests |
| I1 Audit recording | PASS | backend pipeline, CV review, and CV candidate search tests; scenario audit assertion |
| I2 Role-based access control | NOT IMPLEMENTED | No per-user or per-case authorization layer exists |
| I3 Tamper-proof/WORM audit and certified chain of custody | NOT IMPLEMENTED | No tamper-evident storage, WORM backend, or custody certification exists |
| I4 Protected-route and browser smoke checks | NOT ASSESSED | Frontend unit tests and typecheck/build executed |
| J Frontend regression, typecheck, production build | PASS | vitest, tsc --noEmit, vite build |
| K Data and service isolation | PASS | listener snapshots and production data snapshot before/after |
| L R4C validation | NOT ASSESSED | No approved R4C dataset or protocol is present |

## Commands and results

| Label | Status | Return code | Duration (s) | Command |
| --- | --- | ---: | ---: | --- |
| Configured CV limits | PASS | 0 | 0.033 | `/Users/yps/Dev/web/atm/.venv/bin/python -c import json,sys; sys.path.insert(0,'backend'); from app.config import cv_limits, MAX_UPLOAD_BYTES; print(json.dumps({**cv_limits(), 'max_upload_bytes': MAX_UPLOAD_BYTES}))` |
| Node version | PASS | 0 | 0.119 | `node --version` |
| npm version | PASS | 0 | 0.216 | `npm --version` |
| Backend pytest full suite | PASS | 0 | 29.096 | `/Users/yps/Dev/web/atm/.venv/bin/python -m pytest backend/tests -q --deselect=backend/tests/test_cv_engine.py::test_synthetic_generator_writes_labelled_clips` |
| Frontend vitest | PASS | 0 | 1.822 | `npm run test -- --run` |
| Frontend typecheck | PASS | 0 | 1.891 | `npm run typecheck` |
| Frontend production build | PASS | 0 | 3.096 | `npm run build` |
| 12-clip synthetic CV scenario | PASS | 0 | 3.435 | `/Users/yps/Dev/web/atm/.venv/bin/python /Users/yps/Dev/web/atm/scripts/acceptance_runner.py --run-scenario --scenario-temp <ACCEPTANCE_TMP> --scenario-output <ACCEPTANCE_TMP>/scenario-result.json` |

## Test counts

| Suite | Result |
| --- | --- |
| Backend pytest | 215 passed, 0 failed, 0 errors, 0 skipped, 1 deselected |
| Frontend vitest | 65 passed of 65; 9 files passed of 9 |

## 12-clip synthetic scenario

- Status: **PASS**
- Counts: `{"clips_total": 12, "control_case_clips": 2, "face_observations_published": 12, "no_face_clips": 1, "runs_total": 12, "target_case_clips": 10}`
- Timing: `{"memory_note": "Approximate process high-water mark (ru_maxrss), not an isolated container measurement.", "peak_process_rss_bytes": 111067136, "search_seconds": 0.0069, "selected_scope_search_seconds": 0.0052, "total_processing_seconds": 1.9438}`
- Search: `{"actual_observation_ids": ["obs-c01", "obs-c02", "obs-c03", "obs-c04", "obs-c05"], "case_scope_isolation_verified": true, "cross_case_selected_rejection_status": 404, "expected_observation_ids": ["obs-c01", "obs-c02", "obs-c03", "obs-c04", "obs-c05"], "scope": "case_all_eligible_videos", "scores": [0.995037, 0.980581, 0.957826, 0.928477, 0.894427], "selected_scope_ids": ["obs-c07", "obs-c08"], "source_exclusion_verified": true, "top_k": 5}`
- Review: `{"reference_decision": "relevant", "reviewer_note_not_exposed_in_search": true, "top_candidate_decision": "relevant"}`
- Export: `{"association_limitation_present": true, "cv_candidate_count": 1, "cv_observation_count": 1, "cv_selection_count": 2, "pdf_valid": true, "raw_vector_and_path_fields_absent": true}`
- Audit: `{"candidate_search_events": 2, "result_count_recorded": 5, "temp_paths_absent": true}`
- Data classification: synthetic clips, synthetic observations/embeddings, stubbed CV inference, no real people/CCTV.

## Configured limits

```json
{
  "concurrent_analyses": 1,
  "max_analysis_frames": 300,
  "max_clip_duration_seconds": 300.0,
  "max_crops_per_analysis": 100,
  "max_decoded_frames": 3000,
  "max_face_detections_per_analysis": 6000,
  "max_face_detections_per_frame": 64,
  "max_face_observations_per_analysis": 120,
  "max_face_observations_per_frame": 8,
  "max_frame_stride": 20,
  "max_person_detections_per_analysis": 12000,
  "max_person_detections_per_frame": 128,
  "max_person_observations_per_analysis": 200,
  "max_person_observations_per_frame": 12,
  "max_ranked_candidates": 100,
  "max_response_bytes": 750000,
  "max_retained_crop_files": 2000,
  "max_top_k": 25,
  "max_upload_bytes": 524288000,
  "synchronous": true
}
```

## Safety and data isolation

- Production data snapshot unchanged: `True`
- Listener snapshot unchanged: `True`
- Service control commands invoked: `[]`
- Prohibited scripts invoked: `[]`
- Before listeners: `{"5173": {"pids": ["90347"], "returncode": 0}, "8000": {"pids": ["90317"], "returncode": 0}, "8001": {"pids": [], "returncode": 1}}`
- After listeners: `{"5173": {"pids": ["90347"], "returncode": 0}, "8000": {"pids": ["90317"], "returncode": 0}, "8001": {"pids": [], "returncode": 1}}`

## R4C and remaining gaps

- R4C: NOT ASSESSED; no approved dataset/protocol was used.
- Real DVR/NVR exports and vendor-specific formats were not tested.
- No OCR or automatic CCTV clock extraction is implemented; alignment uses investigator-entered timestamps.
- Per-user/per-case RBAC, tamper-proof/WORM audit storage, and certified chain of custody are not implemented.
- R4C validation and real-world identity/detection accuracy are NOT ASSESSED.
- The 12-clip scenario is one local synthetic run; no broader 10–15 clip scalability sweep or configured-limit boundary stress was executed.
- CV inference was stubbed with deterministic synthetic observations; real model detection/embedding behavior in the scenario is NOT ASSESSED.
- Browser-level smoke automation was not run.
- Mask, helmet, cap, and occlusion robustness remain not_assessed or heuristic review signals only.

## Report files

- `reports/acceptance/acceptance.md`
- `reports/acceptance/acceptance.json`
