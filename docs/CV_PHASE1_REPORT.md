# ATM Sentinel CV Phase 1 Report

Date: 2026-11-22  
Root: `/Users/yps/Dev/web/atm`  
Status: historical Phase 1 report. Phase 1 was remediated and later phases added the CV UI, persistent runs, review, candidate search, and explicit CV export references.

## Outcome

Phase 1 provides a local, modular CV engine for face detection, five-landmark pose proxies, person detection, clip-local tracking, face crops, explainable quality scoring, candidate embeddings, ranking, synthetic benchmark assets and automated tests. No UI source files were changed. No new Python dependencies were installed; existing `opencv-python-headless==5.1.0.95` and NumPy were used.

The pipeline never confirms identity. Similarity results are candidate retrieval only, and track IDs are local to one analysis run and may be reused in later runs.

## Remediation changes

- `backend/app/cv/tracking.py`: deterministic one-to-one assignment; a track or detection is mutated at most once per frame.
- `backend/app/config.py`: conservative configurable frame, duration, stride, decode, crop, top-k and concurrency limits.
- `backend/app/schemas.py`: request validation for the new limits, `save_crops=false` default and `summary_only` option.
- `backend/app/routers/cv.py`: bounded synchronous analysis, HTTP 503 busy response, safe 4xx errors, summary-only responses, per-model status, person-detector status and limit reporting.
- `backend/app/cv/pipeline.py`: resource budgets, crop caps, run IDs, provenance metadata, per-model runtime reporting and whole-query-clip exclusion from ranking.
- `backend/app/cv/detection.py`: per-model backend/target creation with CPU fallback handling.
- `backend/app/cv/runtime.py`: facade-aware runtime profiles and fallback reporting.
- `backend/app/cv/embeddings.py`: generation-based persistence, checksums, manifest-last writes, prior-generation recovery, legacy/unknown provenance and `exclude_source_id`.
- `backend/app/cv/models.py`: immutable SFace/YOLOX source revisions and YuNet upstream revision note.
- `backend/app/cv/crop.py`: bounded crop retention.
- `backend/app/cv/types.py`: analysis run ID and source ID in results.
- `backend/tests/test_cv_engine.py`: tracker, persistence, limit, status, error-sanitization, busy-response and summary-only regression tests.
- `scripts/benchmark_cv.py`: isolated index, query-clip-excluded ranking, hard negatives and per-model runtime reporting.
- `docs/licenses/`: full MIT and Apache-2.0 texts with model mapping and attribution.
- `docs/CV_MODEL_SELECTION.md`: corrected track-ID, provenance, runtime, license, source-pin and limit documentation.
- `docs/CV_PHASE1_BENCHMARK.md` and `data/cv/benchmark.json`: regenerated with corrected methodology.

## Models and licensing

| Purpose | Model | License | SHA256 |
| --- | --- | --- | --- |
| Face detection | YuNet 2026may dynamic ONNX | MIT weights | `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0` |
| Embeddings | SFace 2021dec ONNX | Apache-2.0 | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |
| Person detection | OpenCV Zoo YOLOX-s 2022nov ONNX | Apache-2.0 | `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` |

Full notices are in `docs/licenses/MIT-YuNet.txt`, `docs/licenses/APACHE-2.0.txt` and `docs/licenses/README.md`. Source URLs for SFace and YOLOX are pinned to immutable Hugging Face revisions; SHA256 verification remains authoritative.

Rejected: InsightFace pretrained weights, QMagFace/SER-FIQ, Ultralytics YOLO, MediaPipe Face Landmarker and cloud vision APIs. Reasons are recorded in `docs/CV_MODEL_SELECTION.md`.

## Verification

Historical commands and results at the end of Phase 1 remediation:

- `.venv/bin/python -m pytest -q backend/tests` → `58 passed, 1 warning in 4.46s`.
- `npm test -- --run` in `frontend/` → `4 passed`.
- `npm run typecheck` in `frontend/` → passed.
- `npm run build` in `frontend/` → `✓ built in 1.00s`.
- `.venv/bin/python scripts/download_cv_models.py` → all three models `already_present` with matching SHA256 values; no downloads occurred.
- `.venv/bin/python scripts/benchmark_cv.py` → 6 clips processed; corrected benchmark JSON and report generated.
- OpenCV emits a harmless graph-engine warning when CPU target IDs are passed to the facade; runtime status reports CPU/fallback `false` for all three models.

The pytest warning is the existing `StarletteDeprecationWarning` about `httpx` with `starlette.testclient`.

## Benchmark correction

The previous benchmark was invalid: query-clip embeddings remained in the gallery, so candidate rank@1 leaked the query clip into its own search index. The corrected benchmark uses an isolated index per run, a gallery of `subject_a_front`, `subject_b_front`, `multi_subject` and `challenges`, a query clip of `subject_a_side`, and hard negatives from `subject_b_front` and `challenges`. The whole query clip is excluded by source ID.

| Clip | Face frames / expected | Person detections | Avg frame ms | Est. FPS | Cross-pose Rank@1 | Hard negatives in top 5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `subject_a_front` | 40 / 40 | 9 | 105.87 | 9.445 | — | — |
| `subject_a_side` | 17 / 30 | 0 | 95.82 | 10.436 | 17/17 (1.0) | 0 |
| `subject_b_front` | 40 / 40 | 0 | 101.44 | 9.858 | — | — |
| `multi_subject` | 35 / 35 | 0 | 116.15 | 8.609 | — | — |
| `challenges` | 30 / 40 | 17 | 105.53 | 9.476 | — | — |
| `no_face` | 0 / 0 | 0 | 98.93 | 10.108 | — | — |

This is a synthetic cross-pose smoke test, not a real-world accuracy estimate. Peak process memory was `373,620,736` bytes (`ru_maxrss` on macOS).

## API behavior and compatibility

- Endpoints and response keys were preserved; new keys were added.
- `save_crops` now defaults to `false`; callers that need crops must opt in.
- `summary_only=true` omits per-frame details and ranked candidates.
- `max_frames` and `frame_stride` are validated with 422 responses when above configured limits.
- CV/model/runtime errors return controlled 400 responses without absolute paths, stack traces or internal details.
- Concurrent analysis is limited to one request; additional requests receive 503 with `Retry-After: 5`.

## Limitations

- Analysis remains synchronous; there is no background job queue in Phase 1.
- One-concurrent-request default prevents unbounded memory/CPU use but does not provide queueing.
- Synthetic results validate pipeline mechanics only; they do not establish real CCTV accuracy.
- YuNet misses some turned-face synthetic frames (`subject_a_side`: 17/30).
- YOLOX-s detects procedural bodies only at the lowered benchmark threshold; the application default `0.45` remains unvalidated. Zero detections do not prove absence of a person.
- Pose values are geometric proxies from five landmarks, not calibrated 3D pose.
- Mask, helmet and cap states are `not_assessed`; occlusion is only a heuristic review flag.
- Legacy embedding records without provenance are retained but marked `legacy_unknown`.

## Runtime note

Historical Phase 1 note: no processes were restarted during that remediation, and the then-current ports were `5174`/`8001`. Current service ownership and ports are reported in `reports/acceptance/acceptance.md`; the acceptance runner did not start, stop, or reconfigure any service.
