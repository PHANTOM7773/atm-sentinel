# TASK 21 — Demo Runbook

## Purpose

Repeatable, synthetic-data-only demonstration of ATM Sentinel. This runbook documents what to show, what to say, what to expect, and how to recover. It does not start, restart, or stop services and does not modify protected case data, evidence, exports, datasets, models, or human annotations.

## Verification labels

- **TEST-VERIFIED** — behavior is covered by executed automated tests or API workflow verification.
- **LIVE DEMO REQUIRED** — must be shown interactively; automated tests do not prove this exact browser path.
- **FIXTURE-SMOKE VERIFIED** — TASK-20 Chrome/CDP smoke passed with `/api` fixtures; backend persistence was not part of that smoke.

## Prerequisites

- Application already available at `http://127.0.0.1:5173`; backend API at `http://127.0.0.1:8000`. Do not restart or stop running services for this documentation task.
- Normal local startup, when needed by an operator outside this documentation task, is `scripts/dev.sh`, which starts Uvicorn on `127.0.0.1:8000` and Vite on `127.0.0.1:5173`.
- Existing authorized synthetic assets only:
  - `data/demo/synthetic_atm.mp4`
  - `data/datasets/synthetic/cv/subject_a_front.mp4`
  - `data/datasets/synthetic/cv/subject_a_side.mp4`
  - `data/datasets/synthetic/cv/subject_b_front.mp4`
  - `data/datasets/synthetic/cv/multi_subject.mp4`
  - `data/datasets/synthetic/cv/challenges.mp4`
  - `data/datasets/synthetic/cv/no_face.mp4`
  - `data/models/SHA256SUMS.json` and pinned ONNX files
- Dataset notice: `data/datasets/synthetic/cv/README.txt` says all faces/scenes are procedurally generated fictional assets, no real people or real footage are present, and results validate pipeline mechanics only.
- To avoid writing into protected runtime data, use a separate `ATM_SENTINEL_DATA_DIR` for demonstration copies of pinned models. Do not run model downloaders or dataset generators.
- Never run:
  - `scripts/generate_synthetic_cv_assets.py`
  - `scripts/download_cv_models.py`
  - `scripts/benchmark_cv.py`
- Never claim identity confirmation, watchlist matching, Aadhaar matching, R4C validation, or real-world accuracy.

---

## Step 1 — Open the application

| Item | Detail |
| --- | --- |
| Route/action | Open `http://127.0.0.1:5173`. |
| Expected result | Dashboard `/` loads with stats, recent cases, dependency/tool health, and append-only recent audit activity. Header service indicator is visible. |
| Presenter explanation | “This is a local evidence organization prototype, not a police identity system. The dashboard reports local state and explicitly shows interpretation limits.” |
| Verification | TEST-VERIFIED for health/session API behavior in `frontend/src/components/AppShell.test.ts`, `frontend/src/lib/sessionApi.test.ts`; FIXTURE-SMOKE VERIFIED for dashboard rendering in TASK-20. |
| Recovery | If unreachable, check the already-running local services; do not restart from this task. Reload the page. If passphrase mode is enabled, unlock via the session indicator. If unset, expect “Open local mode.” |

## Step 2 — Select or create a demonstration case

| Item | Detail |
| --- | --- |
| Route/action | Go to `/cases`. Create a case whose number/title/location/tags include `DEMO`, `SAMPLE`, `SYNTHETIC`, or `TEST DATA`. |
| Expected result | Case appears in the list with a visible demo label. Selecting it writes `?case=<case_id>` and loads transactions, videos, notes, timeline, and links. |
| Presenter explanation | “Demo markers are deliberately visible so synthetic evidence is never confused with real case material.” |
| Verification | TEST-VERIFIED for demo-marker logic in `frontend/src/lib/demo.test.ts`; case CRUD API covered by backend tests. |
| Recovery | If the case list is empty, create a new demo case. If a case appears without a demo marker, edit metadata/tags or create a fresh demo case. Do not alter existing protected data. |

## Step 3 — Add/select a transaction and timestamp

| Item | Detail |
| --- | --- |
| Route/action | In `/cases?case=<case_id>`, add a transaction with a demo reference/ATM ID. Enter local transaction time and CCTV time so the derived window lies inside the chosen clip duration. |
| Expected result | Transaction appears in the transaction list. Local input is converted to UTC before `POST /api/cases/{id}/transactions`. UTC/CCTV context is labelled. |
| Presenter explanation | “Transaction time converts a long video review problem into a short, evidence-focused window. The CCTV clock may differ from the transaction clock, so both times are recorded.” |
| Verification | TEST-VERIFIED in `backend/tests/test_timestamps.py:12-89`; UI validation in `frontend/src/pages/Investigation.test.ts`. |
| Recovery | If Add transaction is disabled, ensure reference and both timestamps are present/parseable. If the window will be outside the clip, adjust CCTV time or choose a different synthetic clip. Do not edit protected annotations. |

## Step 4 — Upload/select a sample video

| Item | Detail |
| --- | --- |
| Route/action | Go to `/investigation?case=<case_id>`. Select the case/transaction, then upload `data/demo/synthetic_atm.mp4` or one of the `data/datasets/synthetic/cv/*.mp4` clips. Use a copy in a temporary demo data directory if repository data must remain untouched. |
| Expected result | Upload succeeds for MP4/AVI/MOV/MKV only, with filename, size, container metadata, and SHA-256 displayed. Invalid extensions or files above 500 MB are rejected with clear messages and the input resets. |
| Presenter explanation | “The original file is preserved by hash. We validate container basics before processing; unsupported DVR formats require an H.264 MP4 export from the source system.” |
| Verification | TEST-VERIFIED in `backend/tests/test_security.py`, `backend/tests/test_video.py`, `frontend/src/pages/Investigation.test.ts`. |
| Recovery | If upload fails, confirm extension/size and that the file is a real synthetic sample. Use `synthetic_atm.mp4` for the general workflow; use `subject_a_front.mp4` for the most reliable local CV path. |

## Step 5 — Show timestamp alignment

| Item | Detail |
| --- | --- |
| Route/action | In `/investigation`, complete metadata and clock-offset steps, set before/after seconds and max frames, then click `Verify alignment`. |
| Expected result | `POST /api/alignment/preview` reports derived/applied offset, transaction video seconds, analysis window, and warnings. Example TASK-19 fixture result: `transaction_video_seconds=3.0`, window `2.0s–4.0s`. |
| Presenter explanation | “Alignment is arithmetic plus provenance. It narrows review to the transaction window; it does not independently verify the CCTV clock.” |
| Verification | TEST-VERIFIED in `backend/tests/test_cv_alignment.py:172-404`, `backend/tests/test_timestamps.py`; TASK-19 workflow result. |
| Recovery | If warnings appear, inspect the clock offset and CCTV reference point. Leave manual offset blank to derive it when appropriate. Ensure the video duration covers the window. |

## Step 6 — Run the existing CV workflow if supported locally

| Item | Detail |
| --- | --- |
| Route/action | From `/investigation`, click `Start processing` to create a video job, or go to `/cv?case=<case_id>` and create a CV run using full-video or transaction-aligned mode. For real local inference, confirm pinned model hashes in `data/models/SHA256SUMS.json` are present. |
| Expected result | Video job polls to completion and offers workspace/evidence/CV links. CV `POST /api/cv/runs` returns a run with observations and associations. If models or hashes are unavailable, the CV status/run response reports unavailable/blocked state rather than silently producing results. |
| Presenter explanation | “There are two workflows: frame-extraction jobs with progress, and CV runs that execute synchronously with strict frame/cost budgets. Real CV here uses pinned CPU ONNX models on synthetic footage only.” |
| Verification | TEST-VERIFIED by TASK-19 API workflow and P0-6 real local inference. P0-6 verified YuNet, SFace and YOLOX hashes and real detections; production default threshold `0.45` may produce zero person detections on some synthetic clips. |
| Recovery | If no persons are detected, explain that person detection is `experimental_unvalidated` and zero detections are not proof of absence. Use `subject_a_front.mp4` and a verified local model setup for the most reliable real-inference path. If busy, wait and retry after `Retry-After: 5`. Do not change production thresholds for the demo. |

## Step 7 — Inspect persons, faces, and associations

| Item | Detail |
| --- | --- |
| Route/action | Open `/cv?case=<case_id>&run=<cv_run_id>`. Review observations and the `Person associations` section, including zone, dwell, timing, continuity, and review state. |
| Expected result | Face and person observations show frame/time, crop availability, quality signals, and `candidate_only` status. Associations show heuristic score, evidence strength, zone overlap, and review controls only when evidence is eligible. Ineligible records show explicit insufficient-evidence reasons. |
| Presenter explanation | “Track IDs are local to one run, not identities. Association is a reviewable hypothesis built from ATM-zone overlap, timing, continuity, and detector evidence—not proof that a person transacted.” |
| Verification | TEST-VERIFIED by `backend/tests/test_atm_association.py`, P0-1A real-inference verification, P0-1B hardening tests, and `frontend/src/pages/CvRunsView.test.ts`. |
| Recovery | If no association appears, show the insufficient-evidence card and explain the hard gates. Use the P0-1A-style window/zone setup in a fresh demo case if a positive example is required. Do not weaken thresholds. |

## Step 8 — Inspect best-face results and quality indicators

| Item | Detail |
| --- | --- |
| Route/action | In an association card, click `Inspect ranking` to open the best-face modal. Review selected, ranked, rejected, and other-person frames plus reliability indicators. |
| Expected result | Modal shows deterministic score, reason codes, quality components, same-frame person/face bbox containment, and explicit note that mask/helmet/cap are `not_assessed`. P0-2 real-model example: frame 5, score `0.9741`, quality `98.3`. |
| Presenter explanation | “Best-face means best frame for human review under an uncalibrated quality heuristic. It does not mean most identifiable or same person.” |
| Verification | TEST-VERIFIED by `backend/tests/test_best_face.py`, `backend/tests/test_best_face_real_cv.py`, `backend/tests/test_face_reliability.py`, P0-2/P0-3 reports. |
| Recovery | If no best face is selected, show the no-selection reason (unretrievable crop, low confidence, exposure/sharpness/pose/occlusion, or missing quality components). Do not reinterpret weak evidence as usable. |

## Step 9 — Compare original and enhanced crops

| Item | Detail |
| --- | --- |
| Route/action | In a retrievable observation card, expand the enhancement panel, choose `general_enhancement` or `low_light_correction`, and click `Enhance`. |
| Expected result | Original and derived-enhanced images are shown side by side with method version, dimensions, processing milliseconds, both SHA-256 values, and warnings. Label: `"AI-enhanced derived image - not original evidence"`. |
| Presenter explanation | “This is conservative OpenCV signal processing for visual review. Original evidence is unchanged, enhanced output is never used for embeddings/matching, and AI super-resolution models are not available locally.” |
| Verification | TEST-VERIFIED by `backend/tests/test_image_enhancement.py`, `frontend/src/components/CvCropEnhancementPanel.test.ts`; TASK-15 measurements. FIXTURE-SMOKE VERIFIED for UI rendering in TASK-20. |
| Recovery | If an image fails to load, use the labeled placeholder and explain crop retrieval state. If presets do not load, wait/reload; the button remains disabled until presets are available. Do not enable or substitute an unverified model. |

## Step 10 — Demonstrate cross-clip search and human review

| Item | Detail |
| --- | --- |
| Route/action | In `/cv?case=<case_id>&run=<cv_run_id>`, select a query observation, scope to eligible case videos or selected videos, set `topK`, and click search. Then use `relevant`, `irrelevant`, or `needs_review` on observations/candidates; use `confirmed`/`rejected` on associations. |
| Expected result | `POST /api/cv/candidates/search` returns ranked candidates with cosine similarity, model provenance, scan diagnostics, and review controls. Query source video is excluded. Reviews persist and are listed in run detail. |
| Presenter explanation | “Similarity ranks visual candidates for a human. It is not identity confidence. Reviews are local case-review outcomes and are not actor-attributed RBAC decisions.” |
| Verification | TEST-VERIFIED by `backend/tests/test_cv_candidate_search.py`, `backend/tests/test_cv_review.py`, `frontend/src/pages/CvRunsView.test.ts`, TASK-18 exploratory benchmark, TASK-19 workflow. |
| Recovery | If search returns 503, wait for `Retry-After: 5` and retry. If no eligible embedding/index exists, explain V4 provenance requirements. Cross-case searches must fail; do not bypass scope checks. |

## Step 11 — Capture/review evidence

| Item | Detail |
| --- | --- |
| Route/action | Open `/workspace?case=<case_id>&video=<video_id>&job=<job_id>` to view timeline markers and manually capture a frame. Then go to `/evidence?case=<case_id>` to filter, sort, select, annotate, and optionally compare up to four frames. |
| Expected result | Manual capture calls `POST /api/frames/manual`. Evidence gallery shows quality metrics, warnings, SHA-256, selection notes, original view, and compare modal. Compare does not run face detection or similarity. |
| Presenter explanation | “The evidence layer preserves frame provenance and supports human selection. Quality score means image usability, not identity or truthfulness.” |
| Verification | TEST-VERIFIED by backend frame/export tests and frontend `TrustCopy.test.ts`; FIXTURE-SMOKE VERIFIED for evidence rendering in TASK-20. |
| Recovery | If thumbnails are missing, reload the evidence page. If compare is disabled, select fewer than or equal to four frames. Use `/compare?case=<case_id>` for two-frame static comparison and human-authored clip links. |

## Step 12 — Generate PDF and JSON manifest export

| Item | Detail |
| --- | --- |
| Route/action | Go to `/export?case=<case_id>`. Ensure at least one frame is selected; optionally stage CV references from `/cv` and review the opt-in list. Click `Generate report`, then download PDF and JSON manifest; optionally download ZIP and contact sheet. |
| Expected result | `POST /api/exports` returns report data with `report_hash` and `pdf_sha256`. Manifest includes case/transactions/videos/jobs/frames/notes/links/audit events and selected CV references. ZIP uses the exact frame IDs in the generated report. |
| Presenter explanation | “Export packages reviewable evidence with hashes and provenance. CV references are opt-in and marked review context only. It is not a court-certified chain of custody.” |
| Verification | TEST-VERIFIED by `backend/tests/test_pipeline.py`, `backend/tests/test_cv_review.py:770-937`, `frontend/src/pages/Export.test.ts`, TASK-19 hash assertions. |
| Recovery | If Generate is disabled, select at least one frame. If case changes, stale report details clear automatically. If a CV item is rejected, re-stage a valid opaque ID/model SHA/selection context; do not hand-edit export payloads. |

## Demo discipline checklist

- Use synthetic/sample media only.
- Keep demo markers visible.
- Do not modify protected data, evidence, exports, datasets, models, or human annotations.
- Do not run prohibited scripts or change thresholds/models/schemas.
- Do not restart/stop services as part of this documentation task.
- State plainly that real CCTV/R4C validation, identity confirmation, RBAC, and certified chain of custody are not demonstrated.
