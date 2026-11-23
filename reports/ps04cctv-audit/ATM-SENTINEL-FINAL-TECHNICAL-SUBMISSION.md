# ATM Sentinel — Final Technical Submission

**Hackathon:** Rajasthan Police PS04CCTV  
**Workspace:** `/Users/yps/Dev/web/atm`  
**Document status:** Final technical reference for presentation scripting, demo narration, architecture explanation, judge Q&A, and submission documentation.  
**Document type:** Technical report only; no slides, no visual deck, no presentation graphics.

---

## 1. Executive summary

ATM Sentinel is a local, synthetic-data hackathon prototype for transaction-driven CCTV evidence organization. It narrows long CCTV review to a transaction-centered analysis window, extracts and selects frames, runs CPU-based person/face CV with pinned local models, presents results as reviewable candidates, and exports evidence with hashes and provenance.

### Final readiness verdict

**Conditional demo-ready; not production-ready.**

The system is ready for a controlled hackathon demonstration using authorized synthetic assets, with explicit caveats. It is **not** ready for real CCTV/R4C validation, production deployment, automatic identity decisions, court-certified evidence handling, or law-enforcement operational use.

### What is implemented and locally verified

- Case and transaction management; video upload, metadata, hashing, verification and normalized derivatives.
- Transaction-to-CCTV alignment with bounded windows and provenance.
- Frame extraction jobs, manual capture, evidence gallery and comparison.
- CPU CV pipeline using YuNet face detection, YOLOX person detection, SimpleTracker, SFace embeddings and face-quality heuristics.
- ATM-zone transaction-person association with hard eligibility gates and human review.
- Deterministic best-face ranking with reliability indicators.
- Cross-case-scoped candidate search and face/association human review.
- Derived-only OpenCV enhancement preview with original/enhanced separation.
- PDF, JSON manifest, ZIP and contact-sheet export with SHA-256 hashes and audit events.
- Frontend trust copy, demo labels, accessibility and stale-state fixes.

### Current verification results

| Verification | Exact result |
| --- | --- |
| Guarded backend regression | `331 passed, 1 deselected, 1 warning in 49.49s` |
| Frontend tests | `14` files, `87` tests passed |
| Frontend typecheck | passed |
| Frontend production build | passed |
| TASK-20 Chrome/CDP browser smoke | `PASS`; no console/network/HTTP errors; API fixtures only |
| TASK-19 API workflow | `PASSED`; `MEASURED_API_WORKFLOW`; no integration bugs found |

### Critical boundaries and caveats

- No automatic identity verification. No criminal/Aadhaar/watchlist matching. No live bank CCTV connection.
- Person detection is explicitly `experimental_unvalidated`; zero detections do not prove absence.
- Similarity scores are visual candidate ranks, not identity confidence.
- TASK-17 annotations remain `NOT_REVIEWED`; TASK-18 retrieval is synthetic-only.
- Real CCTV/R4C validation was not performed.
- RBAC, actor attribution, logout/revocation, WORM/tamper-proof audit and certified chain of custody are not implemented.
- TASK-10, TASK-11 and TASK-13 artifacts were not found; TASK-13 alternative-detector feasibility remains unverified.
- AI restoration/quality models (GFPGAN, Real-ESRGAN, CodeFormer, CR-FIQA, MagFace) are unavailable locally.

### Supporting documents

| Document | Path |
| --- | --- |
| Requirement mapping | `reports/ps04cctv-audit/TASK-21-REQUIREMENT-MAPPING.md` |
| Architecture diagram | `reports/ps04cctv-audit/TASK-21-ARCHITECTURE.mmd` |
| Demo runbook | `reports/ps04cctv-audit/TASK-21-DEMO-RUNBOOK.md` |
| Judge Q&A | `reports/ps04cctv-audit/TASK-21-JUDGE-QA.md` |
| Final readiness | `reports/ps04cctv-audit/TASK-21-FINAL-READINESS.md` |
| Performance evidence | `reports/ps04cctv-audit/TASK-20-PERFORMANCE-RESULTS.json` |
| TASK-20 audit | `reports/ps04cctv-audit/TASK-20-UI-PERFORMANCE-AUDIT.md` |

---

## 2. Problem statement

### 2.1 Original brief availability

No literal original Rajasthan Police PS04CCTV brief, problem statement file, checklist or specification file exists in this repository. `PROJECT_STATUS.md:46` states: “No literal PS04CCTV checklist exists in this repository.”

The authoritative in-repo source is the internal reconstruction in:

- `reports/ps04cctv-audit/REQUIREMENTS_MATRIX.json` — 30 requirement entries, generated `2026-11-23T04:08:57Z`, marked `audit_only: true`.
- `reports/ps04cctv-audit/REQUIREMENTS_COMPLIANCE_REPORT.md`
- `reports/ps04cctv-audit/IMPLEMENTATION_GAP_PLAN.md`
- `PROJECT_STATUS.md`
- `reports/acceptance/acceptance.json` and `reports/acceptance/acceptance.md`

The requirement strings are canonical local reconstruction/supplied text, not verified verbatim copies of an external government document. Compliance scores are internal engineering assessments, not official Rajasthan Police certification.

### 2.2 Problem addressed

ATM/CCTV review is time-consuming because relevant evidence occupies a small portion of long recordings. Investigators need to:

1. Anchor review to a transaction time and ATM journal/bank statement time.
2. Handle clock differences between transaction records and CCTV.
3. Detect and track people near the ATM keypad/cash slot.
4. Detect faces, assess frame usability and select reviewable best frames.
5. Search a selected face across other sample clips.
6. Preserve provenance and produce an exportable evidence sheet.
7. Perform human verification and avoid automatic identity claims.
8. Respect explicit out-of-scope controls: no real criminal/Aadhaar matching, no automatic identification without human verification, no live bank CCTV connection.

---

## 3. Proposed solution

ATM Sentinel implements a transaction-driven, human-in-the-loop workflow:

1. Create a case and transaction with CCTV/transaction timestamps.
2. Upload or select a sample video.
3. Compute alignment and a bounded analysis window.
4. Run a frame-extraction job or CV run.
5. Detect persons with YOLOX and track them with run-local IDs.
6. Detect faces with YuNet, compute quality signals, and generate crops.
7. Embed eligible faces with SFace for candidate retrieval.
8. Associate tracked persons with a normalized ATM zone using heuristic timing/continuity evidence.
9. Select deterministic best-face frames for review.
10. Let investigators review faces, candidates and associations.
11. Export selected evidence with PDF/JSON manifests, hashes, provenance and audit events.

The design deliberately labels CV output as `candidate_only`, requires human verification, excludes query source videos from candidate searches, separates derived images from originals, and rejects stale/cross-case export selections.

---

## 4. Product capabilities

| Capability | What exists | Primary routes / files | Product meaning |
| --- | --- | --- | --- |
| Case management | Create/edit/archive cases, transactions, notes, links, timeline, metadata search | `/cases`; `backend/app/routers/cases.py`; `GET/POST /api/cases`, `GET/POST /api/cases/{id}/transactions`, `GET /api/search` | Organizes an investigation and preserves case context. |
| Video ingestion | MP4/AVI/MOV/MKV upload, size/extension/magic checks, SHA-256, ffprobe metadata, normalized MP4 derivative | `backend/app/services/security.py`, `video.py`; `POST /api/videos/upload`, `POST /api/videos/{id}/verify`, `POST /api/videos/{id}/normalize` | Preserves original and prepares a reviewable derivative. |
| Alignment | Configurable transaction/CCTV times, offsets, before/after window, warnings | `backend/app/services/timestamp.py`; `/investigation`; `POST /api/alignment/preview` | Narrows review to a bounded, documented window. |
| Frame jobs | Extraction, progress, cancel, manual capture, thumbnails, quality | `backend/app/routers/jobs.py`, `frames.py`; `POST /api/jobs`, `GET /api/jobs/{id}`, `POST /api/frames/manual` | Converts video to selectable frame evidence. |
| Person CV | YOLOX COCO person class, `SimpleTracker` run-local IDs | `backend/app/cv/detection.py`, `tracking.py`, `pipeline.py`; `POST /api/cv/runs` | Experimental person candidate detection/tracking. |
| Face CV | YuNet boxes/landmarks, quality heuristics, SFace 128-d embeddings | `backend/app/cv/models.py`, `pipeline.py`, `quality.py`, `embeddings.py` | Face candidates and visual similarity ranking. |
| ATM association | Zone overlap, dwell, transaction timing, continuity, quality heuristics; eligibility gates | `backend/app/services/atm_association.py`; `GET /api/cv/runs/{id}/person-associations`; `POST /api/cv/person-associations/{id}/review` | Reviewable person-at-ATM hypothesis, not identity. |
| Best-face | Deterministic weighted rank, reason codes, reliability indicators | `backend/app/services/best_face.py`, `face_reliability.py`; `GET /api/cv/runs/{id}/person-associations/{assoc}/best-face` | Best frame for human review. |
| Candidate search | Case-scoped SFace candidate retrieval with provenance checks and source exclusion | `backend/app/services/cv_integration.py`; `POST /api/cv/candidates/search` | Finds visually similar candidates in other sample clips. |
| Human review | `relevant`, `irrelevant`, `needs_review`; association `confirmed`/`rejected` | `POST /api/cv/runs/{id}/observations/{obs}/review`; `POST /api/cv/person-associations/{id}/review` | Records local case-review outcomes. |
| Enhancement | Classical OpenCV derived preview, hashes, side-by-side original | `backend/app/routers/cv_enhancement.py`; `GET /api/cv/enhancement/presets`, `POST /api/cv/enhancement/face-crop`, `GET /api/cv/enhancement/face-crop/image` | Visual aid only; never used for matching or export evidence. |
| Export | PDF, JSON manifest, ZIP, contact sheet, hashes, audit events | `backend/app/services/export.py`; `POST /api/exports`, `GET /api/exports/{id}/pdf`, `GET /api/exports/{id}/manifest` | Evidence package with provenance; not certified custody. |
| Safety copy | Candidate-only disclaimers, demo labels, trust copy | `frontend/src/lib/types.ts`, `TrustCopy.test.ts`, all pages | Prevents overclaiming. |

---

## 5. Investigator workflow

| Step | Route / action | Output | Meaning / limitation |
| --- | --- | --- | --- |
| 1 | Open `/` | Dashboard counts, dependency/tool status, recent audit activity | Local prototype state; not certification. |
| 2 | `/cases` create demo case | Case with visible demo marker | Synthetic evidence remains clearly labelled. |
| 3 | `/cases` add transaction | Transaction/CCTV timestamps, reference, ATM ID | Manual entry only; no statement OCR. |
| 4 | `/investigation` upload/select video | Metadata, SHA-256, integrity | Original preserved; MP4/AVI/MOV/MKV only. |
| 5 | `/investigation` verify alignment | Offset, transaction video seconds, window, warnings | Arithmetic alignment; no independent clock verification. |
| 6 | `/investigation` start job or `/cv` create run | Frames/CV observations/associations | CV budget-bounded and synchronous; models must be available. |
| 7 | `/cv?case=&run=` | Observations, person associations, review states | Track IDs are run-local; association is heuristic. |
| 8 | Best-face inspector | Ranked/rejected/other-frame detail and reliability | “Best to review,” not “most identifiable.” |
| 9 | Enhancement panel | Original vs derived preview with hashes | Derived-only; not original evidence or matching input. |
| 10 | Candidate search and review | Ranked candidates, review decisions | Similarity is not identity confidence. |
| 11 | `/workspace` and `/evidence` | Manual capture, frame selection, notes, compare | Quality score is image usability only. |
| 12 | `/export` | PDF/JSON/ZIP/contact sheet with report/PDF hashes | Hash-backed package; no certified chain of custody. |

Full exact actions, expected results, presenter explanations, verification labels and recovery steps are in `TASK-21-DEMO-RUNBOOK.md`.

---

## 6. System architecture

### 6.1 Frontend structure

React 19 + Vite 6 SPA; `BrowserRouter`; Tailwind CSS v4; Vitest/jsdom tests.

| Route | Component | File | Purpose |
| --- | --- | --- | --- |
| `/` | `DashboardPage` | `frontend/src/pages/Dashboard.tsx` | Overview, status, recent cases/audit, limits |
| `/cases` | `CasesPage` | `frontend/src/pages/Cases.tsx` | Cases, transactions, uploads, notes, timeline, links, search |
| `/investigation` | `InvestigationPage` | `frontend/src/pages/Investigation.tsx` | 7-step guided workflow, alignment, job start/monitor |
| `/workspace` | `WorkspacePage` | `frontend/src/pages/Workspace.tsx` | Playback, timeline markers, manual capture, normalization |
| `/evidence` | `EvidencePage` | `frontend/src/pages/Evidence.tsx` | Frame gallery, filters, selection, notes, compare |
| `/compare` | `ComparePage` | `frontend/src/pages/Compare.tsx` | Manual clip links, metadata search, two-frame compare |
| `/cv` | `CvRunsPage` | `frontend/src/pages/CvRuns.tsx` | CV runs, observations, associations, best-face, search, review |
| `/export` | `ExportPage` | `frontend/src/pages/Export.tsx` | PDF/manifest/ZIP/contact-sheet generation and history |

Case context is preserved with `?case=<id>`. CV detail uses `?case=&run=`. Workspace uses `?case=&video=&job=`. API base defaults to `http://127.0.0.1:8000` with `credentials: include` in `frontend/src/lib/api.ts`.

### 6.2 Backend structure

FastAPI application in `backend/app/main.py`, version `0.1.0`, schema version `5`. Lifespan calls `init_db()`. CORS defaults to local Vite ports. Optional passphrase mode uses `ATM_SENTINEL_PASSPHRASE` and cookie `sentinel_session`.

Routers:

- `system`, `cases`, `videos`, `jobs`, `frames`, `exports`, `cv`, `cv_enhancement`.
- Total API surface: 59 routes including root and session.

Grouped API routes:

| Group | Routes |
| --- | --- |
| Session/system | `GET /`; `POST /api/session`; `GET /api/system/status` |
| Cases/search | `GET /api/cases`; `POST /api/cases`; `GET/PATCH /api/cases/{case_id}`; `POST /api/cases/{case_id}/archive`; `GET/POST /api/cases/{case_id}/transactions`; `GET/POST /api/cases/{case_id}/notes`; `GET/POST /api/cases/{case_id}/links`; `GET /api/cases/{case_id}/timeline`; `GET /api/search` |
| Videos | `POST /api/videos/upload`; `GET /api/videos`; `GET/PATCH /api/videos/{video_id}`; `GET /api/videos/{video_id}/file`; `POST /api/videos/{video_id}/verify`; `POST /api/videos/{video_id}/normalize` |
| Alignment/jobs | `POST /api/alignment/preview`; `POST /api/jobs`; `GET /api/jobs`; `GET /api/jobs/{job_id}`; `POST /api/jobs/{job_id}/cancel` |
| Frames | `GET /api/frames`; `POST /api/frames/manual`; `GET /api/frames/compare`; `GET /api/frames/{frame_id}/image`; `GET /api/frames/{frame_id}/thumb`; `PATCH /api/frames/{frame_id}` |
| Exports | `POST /api/exports`; `GET /api/exports/frames/archive`; `GET /api/exports/contact_sheet`; `GET /api/exports`; `GET /api/exports/{export_id}/pdf`; `GET /api/exports/{export_id}/manifest` |
| CV core | `GET /api/cv/status`; `GET /api/cv/embeddings`; `POST /api/cv/analyze`; `POST /api/cv/runs`; `GET /api/cv/runs`; `GET /api/cv/runs/{cv_run_id}`; `GET /api/cv/runs/{cv_run_id}/observations`; `POST/GET /api/cv/runs/{cv_run_id}/observations/{observation_id}/review`; `GET /api/cv/runs/{cv_run_id}/reviews`; `GET /api/cv/runs/{cv_run_id}/person-associations`; `GET /api/cv/runs/{cv_run_id}/person-associations/{association_id}/best-face`; `POST /api/cv/person-associations/{association_id}/review`; `GET /api/cv/runs/{cv_run_id}/observations/{observation_id}/crop`; `POST /api/cv/candidates/search` |
| Enhancement | `GET /api/cv/enhancement/presets`; `POST /api/cv/enhancement/face-crop`; `GET /api/cv/enhancement/face-crop/meta`; `GET /api/cv/enhancement/face-crop/image` |

### 6.3 Service boundaries and storage

`backend/app/db.py` initializes SQLite with WAL mode, foreign keys and 30-second busy timeout. Tables:

`schema_meta`, `cases`, `transactions`, `videos`, `processing_jobs`, `frames`, `evidence_items`, `notes`, `clip_links`, `audit_events`, `exports`, `cv_runs`, `cv_observations`, `cv_review_decisions`, `cv_person_observations`, `transaction_person_associations`.

Key data paths:

| Path | Purpose |
| --- | --- |
| `data/sentinel.db` | SQLite state and audit events |
| `data/uploads` | Original uploaded files |
| `data/videos` | Normalized derivatives |
| `data/frames` | Extracted frames and thumbnails |
| `data/cv`, `data/cv/crops` | CV runs, observations, crops |
| `data/exports` | PDF/JSON/ZIP/contact-sheet exports |
| `data/models` | Pinned ONNX models and `SHA256SUMS.json` |
| `data/datasets/synthetic/cv` | Authorized synthetic benchmark clips |
| `reports/ps04cctv-audit/task15-enhancements` | Derived enhancement previews |

Architecture diagram: `reports/ps04cctv-audit/TASK-21-ARCHITECTURE.mmd`. It distinguishes production components, isolated experiments, and unavailable/planned components.

---

## 7. Technology stack and model details

### 7.1 Stack

| Layer | Technology |
| --- | --- |
| Frontend | React 19, ReactDOM 19, react-router-dom v7, Tailwind CSS v4, lucide-react, Vite 6, Vitest 2, jsdom |
| Backend | Python 3.12, FastAPI, SQLite, Uvicorn, Pydantic schemas |
| Video | ffmpeg/ffprobe discovered via `shutil.which`; OpenCV video handling |
| CV | OpenCV 5.1.0 CPU ONNX inference |
| Reporting | ReportLab PDF generation, canonical JSON manifest |
| Testing | pytest (`PYTHONDONTWRITEBYTECODE=1`), Vitest, TestClient |

### 7.2 Pinned models

| Model | File | SHA-256 | Purpose |
| --- | --- | --- | --- |
| YuNet | `data/models/face_detection_yunet_2026may.onnx` | `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0` | Face detection + 5 landmarks |
| SFace | `data/models/face_recognition_sface_2021dec.onnx` | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c82983484087c34e79` | 128-d embeddings for candidate ranking |
| YOLOX | `data/models/object_detection_yolox_2022nov.onnx` | `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` | COCO person class 0 detection |

`require_model()` verifies file existence and SHA-256 before load. No downloads or installs are performed.

### 7.3 Important production limits

From `backend/app/config.py`:

- `CV_BACKEND = "cpu"`, `CV_TARGET = "cpu"`
- `CV_FACE_SCORE_THRESHOLD = 0.6`
- `CV_PERSON_SCORE_THRESHOLD = 0.45`
- `CV_MIN_EMBED_QUALITY = 20`
- `CV_MAX_FRAMES = 300`, `CV_ANALYZE_MAX_FRAMES = 300`
- `CV_MAX_FRAME_STRIDE = 20`, `CV_MAX_DECODED_FRAMES = 3000`
- `CV_MAX_CLIP_DURATION_SECONDS = 300`
- `CV_MAX_CROPS_PER_ANALYSIS = 100`, `CV_MAX_CROP_FILES = 2000`
- `CV_MAX_TOP_K = 25`
- `CV_MAX_FACE_OBSERVATIONS_PER_FRAME = 8`, `CV_MAX_PERSON_OBSERVATIONS_PER_FRAME = 12`
- `CV_MAX_FACE_OBSERVATIONS_PER_ANALYSIS = 120`, `CV_MAX_PERSON_OBSERVATIONS_PER_ANALYSIS = 200`
- `CV_MAX_RANKED_CANDIDATES = 100`, `CV_MAX_RESPONSE_BYTES = 750000`

---

## 8. CV pipeline

### 8.1 Run lifecycle

`backend/app/services/cv_integration.py` enforces:

- `queued → running | failed`
- `running → completed | completed_with_warnings | failed`
- Terminal statuses: `completed`, `completed_with_warnings`, `failed`.

It validates case/video/transaction scope, resolves safe video paths, records source and normalized-video provenance, plans windows, runs analysis, persists observations, publishes eligible embeddings, applies truncation/warnings, and sanitizes public DTOs.

### 8.2 Window planning

- `full_video`: start `0`, end source duration.
- `transaction_aligned`: requires transaction ID, transaction timestamp, CCTV timestamp, before/after seconds; clamps to source duration and rejects windows over max clip duration.
- `_run_window_analysis()` seeks to exact start frame and rejects seek mismatch.

### 8.3 Detection, tracking and crops

`CVPipeline` loads YuNet, YOLOX, SFace, two `SimpleTracker` instances and `EmbeddingStore`.

- `analyze_frame()` detects faces/persons, applies trackers, builds face records, enforces per-frame caps and optionally saves crops.
- `_build_face_record()` crops face, runs `analyze_face_quality()`, generates deterministic IDs, computes L2-normalized SFace embedding only when quality `>= CV_MIN_EMBED_QUALITY`, and sets `verification_status="candidate_only"`.
- `_apply_analysis_caps()` enforces analysis-wide caps and suppresses near-duplicate faces using Hamming distance `<=5` within a 15-frame gap.
- Embeddings are staged during analysis and published only after provenance checks against persisted observations.

### 8.4 ATM-zone association

`backend/app/services/atm_association.py`:

- Zone is frame-relative normalized geometry with `x+width<=1`, `y+height<=1`.
- `MIN_ZONE_OVERLAP_RATIO = 0.25`
- `MIN_ZONE_FRAMES = 2`
- `MIN_DWELL_SECONDS = 0.1`
- `MAX_TRACK_GAP_SECONDS = 1.0`
- Score weights: zone overlap `0.30`, dwell `0.25`, transaction timing `0.25`, track continuity `0.10`, observation quality `0.10`.
- P0-1B hard eligibility rejects excessive track gaps, insufficient zone observations/dwell, outside-window evidence, and missing timing/quality evidence. Ineligible records get `heuristic_score=0.0` and `insufficient_evidence`.
- Reviews allow `confirmed`/`rejected`; insufficient-evidence records cannot be reviewed.

### 8.5 Best-face selection

`backend/app/services/best_face.py`:

- Link method: `same_frame_face_bbox_contained_in_person_bbox`
- `MIN_FACE_BBOX_CONTAINMENT = 0.6`
- Weights: sharpness `0.30`, usable resolution `0.15`, frontalness `0.15`, illumination `0.15`, contrast `0.10`, landmark visibility `0.10`, detector confidence `0.05`.
- Occlusion review factor `0.75`.
- Hard rejections include low sharpness, exposure problems, small face, pose away, suspected occlusion, missing quality components, unretrievable crop, and low detector confidence.
- Tie-break: earlier frame, then observation ID.
- `face_reliability.py` reports `usable/limited/poor/not_assessed`; mask/helmet/cap are always `not_assessed`.

### 8.6 Candidate search and review

`POST /api/cv/candidates/search` validates case, query run/video/observation, selected source videos, and V4 eligibility:

- `record_format == V4_RECORD_FORMAT`
- `v4_eligible is True`
- `embedding_schema_version == EMBEDDING_SCHEMA_VERSION`
- `model_key == "sface"`
- `provenance_status == "known"`
- `verification_status == "candidate_only"`
- valid 64-hex `model_sha256`

It excludes query observation and source video, audits `cv_candidate_search`, and returns score meaning, disclaimer, index provenance, limits, and scan diagnostics. Busy analysis slots return `503` with `Retry-After: 5`.

Human review routes store `relevant`, `irrelevant`, `needs_review` for face observations/candidates and `confirmed`/`rejected` for associations.

### 8.7 Original vs derived image separation

- Original uploads: `data/uploads`, hashed and never overwritten.
- Normalized video: separate derivative.
- Crops: `data/cv/crops`, retrievability-gated.
- Enhanced crops: derived directory, sidecar metadata, label `"AI-enhanced derived image - not original evidence"`, notice `"Derived artifact. Original evidence unchanged. Never use for face matching/embeddings."`, method version `task15-opencv-v1`.
- Enhanced images are not used by CV embeddings, candidate search, export, or DB evidence items.

---

## 9. Feature-by-feature implementation status

### 9.1 Requirement status summary

| Current status | Count | Requirements |
| --- | ---: | --- |
| Implemented and verified | 12 | KF1.2, KF1.3, KF1.4, KF2.2, KF3.1, KF3.2, KF4.2, KF6.4, MH-2, CC-HUMAN, CC-PROV, SD-1 |
| Implemented partially verified | 4 | KF6.1, MH-1, MH-3, GH-3 |
| Partially implemented | 7 | KF1.1, KF2.1, KF4.1, KF5.1, KF6.3, GH-1, CC-ROBUST |
| Not implemented | 3 | KF6.2, GH-2, R4C |
| Out of scope | 4 | OOS-1, OOS-2, OOS-3, OOS-4 |

Full row-by-row matrix: `TASK-21-REQUIREMENT-MAPPING.md`.

### 9.2 Investigator perspective

| Feature | What it does | Why it matters | How investigator uses it | Output meaning | What it cannot establish |
| --- | --- | --- | --- | --- | --- |
| Case/transaction setup | Stores case metadata and transaction/CCTV times | Anchors review | `/cases` create case/transaction | Case-scoped timeline | No statement/OCR import; no clock authenticity |
| Upload/verify | Validates and hashes video | Preserves original | `/investigation` upload | Metadata + SHA-256 | Real DVR containers unsupported |
| Alignment | Computes offset/window | Reduces review scope | Verify alignment | Transaction video seconds/window | No independent CCTV clock verification |
| Frame extraction | Produces frames/jobs | Makes evidence selectable | Start job, open `/workspace` | Frame IDs, quality, timestamps | Quality is usability, not truth |
| Person detection/tracking | Detects persons and assigns run-local tracks | Narrows candidate review | `/cv` run detail | Tracks/observations | Not identity; unvalidated detector |
| ATM association | Scores zone/timing/continuity | Finds possible ATM actor | Association card + review | Heuristic hypothesis | Not proof of transaction/identity |
| Face detection/crops | Detects faces, saves crops | Enables review | Observation cards | Face candidates | Misses possible; no bbox mAP in production |
| Quality/reliability | Shows usability signals | Warns about weak frames | Observation/best-face modal | Heuristic statuses | No identity measure; concealment not assessed |
| Best-face | Selects one ranked face per association | Prioritizes review | Inspect ranking | Review-priority frame | Not “most identifiable” |
| Enhancement | Classical derived preview | Helps visual inspection | Enhancement panel | Derived image + hashes | Not original, not matching input, not SR |
| Candidate search | Finds similar faces across case clips | Supports investigative leads | Query observation → search | Cosine similarity rank | Not identity confidence |
| Human review | Records decisions | Keeps human in loop | Review forms | Case-review state | Reviewer identity/RBAC absent |
| Evidence/export | Packages selected evidence | Provenance and sharing | `/export` | PDF/JSON/ZIP + hashes | Not certified custody |

---

## 10. Original hackathon requirement mapping

### 10.1 Must Have / key features

| ID | Requirement | Status | Evidence | Gaps |
| --- | --- | --- | --- | --- |
| KF1.1 | Accept MP4, AVI, MOV, MKV, WMV, FLV, MPEG/MPG and compatible CCTV/DVR/NVR exports | Partially implemented | `config.py:20`, `security.py`, `videos.py`, `POST /api/videos/upload`, video/security tests | Only MP4/AVI/MOV/MKV supported |
| KF1.2 | Detect codec, resolution, duration | Implemented and verified | `video.py:50-109`, `POST /api/videos/{id}/verify`, `test_video.py` | Depends on ffprobe |
| KF1.3 | Validate and normalize with FFmpeg | Implemented and verified | `security.py`, `video.py:112-147`, `POST /api/videos/{id}/normalize` | Video-only; drops audio |
| KF1.4 | Clear unsupported-format guidance | Implemented and verified | `security.py:40-56`, `video.py:20-33`, `Cases.tsx`, `test_security.py` | Static guidance only |
| KF2.1 | Detect and track people | Partially implemented | YOLOX/SimpleTracker, `POST /api/cv/runs`, P0-6 | `experimental_unvalidated`; no real-CCTV accuracy |
| KF2.2 | Focus on person at ATM keypad/cash slot | Implemented and verified | `atm_association.py`, P0-1A/1B, `test_atm_association.py` | Synthetic only; heuristic |
| KF3.1 | Transaction time with configurable window | Implemented and verified | `timestamp.py`, `cases.py`, `test_timestamps.py` | No statement import/OCR |
| KF3.2 | Align transaction time to CCTV | Implemented and verified | `timestamp.py`, `cv_integration.py`, `test_cv_alignment.py` | No independent clock verification |
| KF4.1 | Score sharpness, pose, illumination, occlusion | Partially implemented | `quality.py`, `landmarks.py`, `test_quality.py`, TASK-16 | Heuristics; TASK-16 isolated/noise flaw |
| KF4.2 | Select best frames | Implemented and verified | `best_face.py`, P0-2, `test_best_face_real_cv.py` | Synthetic real-CV only; uncalibrated |
| KF5.1 | Flag masks/helmets/caps/partial faces | Partially implemented | `face_reliability.py`, P0-3, `cvContract.test.ts` | Concealment `not_assessed` |
| KF6.1 | Cross-clip embedding search | Implemented partially verified | `embeddings.py`, `POST /api/cv/candidates/search`, TASK-18 | Synthetic only; no real identity proof |
| KF6.2 | Role-based access | Not implemented | P0-4A audit | Global passphrase only; no RBAC |
| KF6.3 | Audit log | Partially implemented | `db.py`, `GET /api/system/status`, exports, P0-4A | No actor/WORM/signature |
| KF6.4 | Downloadable evidence sheet | Implemented and verified | `export.py`, `POST /api/exports`, `Export.tsx`, export tests | Not certified; no digital signing |

### 10.2 Top-level Must Have, Good to Have, Out of Scope

| ID | Requirement | Status | Key evidence/limitation |
| --- | --- | --- | --- |
| MH-1 | Upload + transaction time + best face frames + quality scores | Implemented partially verified | Full local chain; no browser E2E/real CCTV |
| MH-2 | At least three common formats | Implemented and verified | MP4/AVI/MOV/MKV tested |
| MH-3 | Cross-clip face search + evidence sheet | Implemented partially verified | API workflow passed; synthetic only |
| GH-1 | Proprietary DVR/NVR handling | Partially implemented | Static export guidance only |
| GH-2 | Skimming/shoulder-surfing detection | Not implemented | Entirely absent |
| GH-3 | Clearly labelled face enhancement | Implemented partially verified | Classical OpenCV preview; not exported/matched |
| OOS-1 | No criminal photo DB matching | Out of scope | Verified absent |
| OOS-2 | No Aadhaar matching | Out of scope | Verified absent |
| OOS-3 | No automatic identity without human verification | Out of scope | Candidate-only + human review |
| OOS-4 | No live bank CCTV connection | Out of scope | File upload only |
| CC-ROBUST | Illumination/angle/occlusion/low-resolution robustness | Partially implemented | Experiments only; annotations not reviewed |
| CC-HUMAN | Human verification | Implemented and verified | Review endpoints/UI/tests |
| CC-PROV | Provenance/export integrity | Implemented and verified | Hashes/manifest/source/model checks |
| SD-1 | Synthetic/sample data only | Implemented and verified | Synthetic fixtures and demo labels |
| R4C | Real footage validation | Not implemented | `NOT_ASSESSED` |

### 10.3 Historical scores

From `REQUIREMENTS_COMPLIANCE_REPORT.md`: Must Have `88/100`, Good to Have `8/100`, overall internal PS04CCTV `58/100`, local technical verification `63/100`. These are audit-time scores and predate later P0/TASK implementations; no recomputed official-style score exists.

---

## 11. Experiments and benchmark results

### 11.1 Common synthetic dataset

TASK 02–08 and related detector experiments used `data/datasets/synthetic/cv`:

| Clip | Frames | FPS | Resolution | Intent |
| --- | ---: | ---: | --- | --- |
| `subject_a_front` | 40 | 10 | 640×480 | clear frontal frame-presence |
| `subject_a_side` | 30 | 10 | 640×480 | turned pose |
| `subject_b_front` | 40 | 10 | 640×480 | second subject |
| `multi_subject` | 35 | 10 | 640×480 | two subjects |
| `challenges` | 55 | 10 | 640×480 | blur/dark/small/occlusion/no-face tail |
| `no_face` | 20 | 10 | 640×480 | empty labels |

Total: 220 frames. Adjacent frames are correlated, not independent subjects. No person/track/box ground truth was available initially.

### 11.2 TASK 02 — baseline benchmark

- Objective: measure existing production pipeline with `MEASURED`, `HEURISTIC`, `NOT_ASSESSABLE` separation.
- Method: `warmup=0`, `measurement=1`, `frame_stride=1`, `top_k=5`; no model/config changes.
- Canonical artifact: `CV-BASELINE-BENCHMARK-20261123T114054Z.{md,json}`.
- Results: duration `48,544.563 ms`; best-effort peak RSS `52,838,400 bytes`.
- Face frame-presence P `1.0` on labeled clips; recall: front `0.35`, side `0.1333`, subject_b `0.2`, multi `0.1714`, challenges `0.3`.
- Recognition: queries `4`; Rank@1/Rank@5 `4/4`; false top-1 `0/4`; same-subject pairs `20`; different-subject pairs `0`; same-score mean±std `0.952019 ± 0.006701`.
- Quality: mean `92.845`, std `10.923`, min `66.3`, p50 `97.75`, max `99.7`; best-face quality mean `98.48`.
- Interpretation: frame presence was precise but recall poor on side/multi clips; ranking looked perfect only in tiny synthetic setup with no different-subject pairs.
- Production integrated: benchmark only; no changes.

### 11.3 TASK 03–06 — detector/fallback/threshold experiments

| Task | Objective | Exact metrics | Interpretation / limitation | Production |
| --- | --- | --- | --- | --- |
| 03 YuNet recall | Shadow-test upscaling | 1.5× side recall `0.5667 → 0.9667`, latency `5.625 → 17.858 ms` (`3.1748×`); 2× no gain, `26.901 ms` (`4.7824×`) | Only side pose benefited; occluded frames 30–39 remained `0/10`; frame-presence only | Isolated |
| 04 fallback | Reduce upscaling cost | Zero-detection fallback side recall `0.9667`, `11.197 ms` vs full `19.059 ms`; 12/12 recovered frames were baseline-zero | Good synthetic result; always fires on no-face frames; no occlusion recovery | Isolated |
| 05 person gate | Avoid unnecessary upscaling | Strict gate side recall `0.5667`, `51.068 ms`; safety run recall `0.9667`, `58.616 ms` vs fallback `11.218 ms` | YOLOX person proxy `0.0` on side clip; no person GT | Isolated |
| 06 YOLOX threshold | Threshold sensitivity | Challenges proxy coverage `0.425 @0.1`, `0.2 @0.45`; side/subject_b/multi `0.0` at all thresholds | Face labels are not person GT; no threshold selected | Isolated |

### 11.4 TASK 07 — alternative detector feasibility

- Status: `partially_ready_isolated_experimental_only`.
- Ready: frame-presence P/R/F1, no-face FPs, confidence analysis, latency.
- Partial: memory measurement.
- NOT_ASSESSABLE: bbox IoU/mAP, person accuracy, track switches/fragmentation, real-world generalization.
- Local models pinned: YuNet `229738` bytes, SFace `38,696,353` bytes, YOLOX-s `35,858,002` bytes.
- Runtimes `onnxruntime`, `insightface`, `torch`, `onnx` not installed.
- SCRFD/RetinaFace packs not approved due unclear/restricted weight licenses; YOLOv8-face avoided due AGPL/unclear provenance; YuNet retained.
- No alternative detector performance measurements; isolated adapter only.

### 11.5 TASK 08–12 — ground truth and annotation

- TASK 08: no bbox/person/track GT; bbox P/R/F1/IoU/mAP NOT_ASSESSABLE; minimum useful subset ~48/220 frames; focused tests `8 passed`.
- TASK 09: deterministic 48-frame pilot created with offline annotation tool; validator template returned `REVIEW_REQUIRED` with 48 missing; tests `9 passed`.
- TASK 12: programmatic QA found 48 unique frames represented, 46 boxes, 9 no-face frames, 48/48 readable PNGs, 0 out-of-bounds, 0 errors/warnings; QA status `NOT_REVIEWED`, `benchmark_ready=false`, visual criteria NOT_ASSESSABLE.
- Production integrated: no; QA reports only.

### 11.6 TASK 13 — missing artifacts

No TASK-13 report or artifact was found. Only an indirect reference in `TASK-20-UI-PERFORMANCE-AUDIT.md` says detector comparison was blocked on approved local weights/runtime. No objective, dataset, metrics or conclusion can be claimed.

### 11.7 TASK 14 — ByteTrack-inspired tracker

- Objective: isolated two-stage tracker experiment.
- Sample: 4 deterministic sequences (12/12/12/11 frames) plus 3 synthetic 30-frame clips.
- Results: parity on deterministic proxies; JSON crossing had `unique_track_ids=2`, `id_switches_proxy=2`; clip runtimes Simple/ByteTrack `0.332/0.222`, `0.326/0.224`, `0.323/0.222 ms`; all synthetic clips had zero YOLOX detections, so runtime only.
- IDF1/MOTA/HOTA NOT_ASSESSABLE; MD/JSON disagree on some crossing/runtime values.
- Production status: not integrated; `SimpleTracker` remains default.

### 11.8 TASK 15 — enhancement

- Objective: derive-only face-crop enhancement with provenance.
- Sample: 12 runs, 3 source crops, 4 presets; classical CLAHE/gamma/brightness/contrast/denoise/unsharp/upscale.
- Dark preset durations `162.527/140.708/143.330/136.261 ms`; blurred `136.154/143.788/138.526/135.470 ms`; normal `138.332/145.605/140.825/138.174 ms`.
- Tests: focused `6 passed`; guarded `315 passed, 1 deselected, 1 warning`.
- AI restoration adapters all unavailable; no weights/packages.
- Production status: routes/UI preview integrated; not in export, DB evidence, embeddings or matching.

### 11.9 TASK 16 — face quality experiment

- Objective: explainable multi-dimension quality scoring.
- Sample: 6 base samples × 6 variants; `inconsistencies: []`.
- Old→new overall examples: dark `52.4→72.99`, blur `22.7→36.92`, downscale `27.2→42.30`, low-light `19.5→35.56`, low-contrast `38.3→56.32`, noise `53.8→62.82`.
- Overall score rose under noise in `5/6` samples due proxy inflation.
- Guarded regression `323 passed, 1 deselected, 1 warning`.
- Production status: isolated; no CV wiring.

### 11.10 TASK 17 — face-box ground-truth benchmark

- Dataset: 48 frames, 46 boxes, 9 no-face frames; QA `NOT_REVIEWED`.
- Baseline: P `1.0`, R `0.869565`, F1 `0.930233`, AP50 `0.869565`, mean matched IoU `0.660550`, `5.725725 ms`.
- Full 1.5×: R `0.913043`, F1 `0.954545`, AP50 `0.913043`, IoU `0.678481`, `17.469964 ms`.
- Zero-detection fallback: same R/F1/AP50, IoU `0.660799`, `9.276854 ms`, fallback `0.3125`.
- Confidence<0.7 fallback: same scores, `9.331609 ms`.
- Interpretation: fallback recovers `+0.043` recall at ~1.62× latency; exploratory only.

### 11.11 TASK 18 — SFace retrieval

- Dataset: 127 usable samples, 3 synthetic subjects, 4 clips; 8,001 all pairs (2,811 genuine / 5,190 impostor); 5,870 cross-clip pairs (680 genuine / 5,190 impostor).
- Genuine all mean `0.940315 ± 0.038746`; impostor `0.837298 ± 0.042882`; cross-clip genuine `0.929612 ± 0.019023`.
- Retrieval Rank@1/Rank@5/MRR `1.0` including and excluding source clip.
- AUC all `0.954847`; cross-clip `0.989106`.
- EER proxy all thr `0.889643`, TAR `0.899324`, FAR `0.100771`; cross-clip thr `0.896400`, TAR `0.942647`, FAR `0.057996`.
- Offline balanced threshold `0.90`: TAR `0.868374`, FAR `0.044123`, TP `2441`, FP `229`, TN `4961`, FN `370`.
- Robustness proxy rank-1 original `0.175`; blur `0.2125`; downscale `0.2125`; low-light `0.2125`; low-contrast `0.2125`; noise `0.200`. Pose NOT_ASSESSABLE.
- MD/JSON disagree on some cross-clip TAR@FAR values; report both sources if asked.
- Production status: exploratory; no production threshold/model/matching changes.

### 11.12 TASK 19 — API workflow

- Objective: verify API-level ATM workflow from case creation to export.
- Method: isolated TestClient + Vitest API-contract/static tests; deterministic synthetic fixtures.
- Result: `MEASURED_API_WORKFLOW`, `PASSED`, `integration_bugs_found=[]`, `production_changes=[]`.
- Alignment `transaction_video_seconds=3.0`, window `2.0–4.0`; person track `7`; association confirmed; export CV counts `2/1/1`; report hash matched manifest; PDF header present; enhanced SHA differed and original unchanged.
- Boundaries verified: cross-case run 404, wrong crop 404, cross-case search 404, cross-case export 422, stale review export 422, busy slot 503 with `Retry-After: 5`.
- Tests: workflow `1 passed`; frontend API `3 passed`; guarded backend `331 passed`; frontend `77 passed` at that time.
- Limitation: API/TestClient only; no browser E2E, real CCTV or accuracy validation.

### 11.13 TASK 20 — UI/browser/performance

- Objective: audit/polish UI and measure local performance.
- Method: Chrome `157.0.8103.79` headless CDP smoke with all `/api` requests fulfilled by fixtures; FastAPI TestClient isolated temp data; one synthetic 60-frame 320×240 MP4 (`35,644` bytes).
- Browser smoke PASS: Investigation rendered; case/transaction/video selected; wizard reached analysis window; alignment preview completed; `/cv`, `/evidence`, `/export` rendered; 0 console/network/HTTP errors; no error banner.
- API timings: normalize `71.826 ms`, upload `66.225 ms`, cold status `58.995 ms`, verify `34.916 ms`, export `31.602 ms`, jobs `3.435 ms`, frames `4.906 ms`, PDF `4.556 ms`, ZIP `3.512 ms`, CV status `6.196 ms`, CV runs `2.082 ms`.
- Warm medians: frames `2.348 ms`, exports `1.849 ms`, videos `1.991 ms`.
- Bundle: 3 assets, `490,002` raw / `138,220` gzip bytes; JS `455,339/131,161`, CSS `33,833/6,614`, HTML `830/445`.
- Final guarded backend `331 passed`; frontend `87 passed` across 14 files; typecheck/build passed.
- Limitation: fixtures do not verify backend persistence; no real traffic, CV inference timing, Core Web Vitals, or browser trace.

### 11.14 P0 hardening and real-CV evidence

| Work | Key evidence | Production status |
| --- | --- | --- |
| P0-1A real association | Real YOLOX threshold `0.1`, 7 detections, track 1, 7 in-zone, overlap `0.9442`, association score `0.9207`, review `proposed→confirmed`; mocked controls separated | Verification only |
| P0-1B hardening | Gap ≤`1.0s` proposed; gap `1.01s` insufficient; guard suite `233 passed` | Production-integrated in `atm_association.py` |
| P0-2 best face | 12 detections, 8 retained, frame 5 score `0.9741`, quality `98.3`; guarded `247 passed` | Production-integrated |
| P0-3 reliability | Usable/limited/poor/not_assessed indicators; mask/helmet/cap not assessed; guarded `258 passed` | Production-integrated |
| P0-4A access audit | 48 endpoint rows, 12 gaps; global passphrase, no RBAC/actor/WORM | Read-only audit |
| P0-6 real CV | Hashes verified; YuNet 12 detections; SFace dim 128; YOLOX threshold `0.1` → 7/front and 15/challenges; default `0.45` → 0/multi; side query top cosine `0.947086`; `3 passed` | Verification only |

---

## 12. Security, privacy and evidence integrity

### 12.1 Verified safeguards

| Safeguard | Implementation evidence |
| --- | --- |
| Original preservation | Originals stored under `data/uploads` with SHA-256; normalization/crops/enhancement/exports are separate derivatives. |
| Upload validation | Allowed extensions MP4/AVI/MOV/MKV, 500 MB cap, staged `.part`, magic-byte checks, safe filename checks, streamed SHA-256. |
| Path containment | `absolute_from_data()` rejects paths escaping `DATA_DIR`; crop/enhanced image paths constrained to derived roots. |
| Session guard | Optional `ATM_SENTINEL_PASSPHRASE`; HMAC-derived `sentinel_session` cookie; `hmac.compare_digest`; public paths `/api/session`, `/api/system/status`, `/api/alignment/preview`. |
| Case-scoped CV | CV runs, candidate search, observations, associations and exports validate case relationships; query source excluded; cross-case tests return 404/422. |
| Provenance | Runs record video/source/normalized hashes, timestamps, model details, budgets, warnings; exports include canonical payload and hashes. |
| Export validation | Rejects ineligible run status, wrong hashes, non-`candidate_only` observations, stale reviews, mismatched model provenance. |
| Human review | Candidate-only outputs; review states; disclaimers that results are not identity. |
| Derived labeling | Enhanced images labelled derived, not original evidence; never used for embeddings/matching. |
| Response hygiene | Public DTOs strip path/embedding/identity keys; crop responses set `nosniff`, `default-src 'none'`, `private, no-store`. |
| Audit events | DB-backed append-only events for selected actions; included in exports and system status. |

### 12.2 Unverified assumptions / absent controls

- No per-user accounts, roles, per-case grants, actor identity, logout, expiry, revocation or rate limiting.
- Cookie lacks `Secure` and explicit max-age; CORS allows credentialed wildcard methods/headers.
- `/docs` and `/openapi.json` are outside the `/api` guard.
- Some object-ID endpoints have IDOR-shaped gaps per P0-4A.
- Audit events are local SQLite; no WORM, signature, tamper evidence, or certified custody.
- No export verification endpoint.
- No independent scan of all pre-existing data for real personal data was performed.
- Not court-admissible or official compliance certification.

---

## 13. Testing and verification evidence

### 13.1 Current final verification

| Command | Result |
| --- | --- |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --tb=no -k 'not test_synthetic_generator_writes_labelled_clips'` | `331 passed, 1 deselected, 1 warning in 49.49s` |
| `cd frontend && npm test -- --run` | `14` files, `87` tests passed |
| `npm run typecheck` | passed |
| `npm run build` | passed; 1610 modules transformed; JS/CSS/HTML sizes as above |

Warning: `StarletteDeprecationWarning` from `fastapi.testclient`.

### 13.2 Historical verification progression

| Report | Backend | Frontend |
| --- | --- | --- |
| Acceptance / compliance audit | `215 passed, 1 deselected, 1 warning in 30.36s` | `65 passed` / 9 files |
| P0-1 association | `226 passed, 1 deselected` | `72 passed` / 9 files |
| P0-1B hardening | `233 passed, 1 deselected` | — |
| P0-2 best-face | `247 passed, 1 deselected` | `74 passed` / 9 files |
| P0-3 reliability | `258 passed, 1 deselected` | `39 passed` |
| TASK-15 enhancement | `315 passed, 1 deselected` | — |
| TASK-16 quality | `323 passed, 1 deselected` | — |
| TASK-19 workflow | `331 passed, 1 deselected` | `77 passed`, typecheck/build |
| TASK-20 / current | `331 passed, 1 deselected` | `87 passed` / 14 files, typecheck/build |

### 13.3 Frontend test inventory

14 files, 87 tests: `CvRunsView.test.ts` 29, `cvReviewApi.test.ts` 14, `AppShell.test.ts` 8, `Export.test.ts` 7, `cvContract.test.ts` 6, `sessionApi.test.ts` 5, `format.test.ts` 4, `task19WorkflowApi.test.ts` 3, `TrustCopy.test.ts` 3, `demo.test.ts` 3, `Investigation.test.ts` 2, `CvCropEnhancementPanel.test.ts` 1, `ui.test.ts` 1, `api.test.ts` 1.

### 13.4 Browser and real-CV evidence

- TASK-20 browser smoke PASS via Chrome CDP with fixtures, no console/network/HTTP errors.
- P0-6 real local inference verified pinned hashes and real YuNet/SFace/YOLOX behavior on synthetic clips.
- P0-1A verified real YOLOX → tracking → zone → persisted association path.
- P0-2 and P0-3 verified real-model best-face/reliability outputs.
- No real CCTV/R4C data was used.

---

## 14. Demo runbook

See `TASK-21-DEMO-RUNBOOK.md` for full detail. Summary:

| # | Route/action | Expected result | Verification label | Recovery |
| ---: | --- | --- | --- | --- |
| 1 | Open `/` | Dashboard/status/audit | TEST-VERIFIED + fixture smoke | Reload; check already-running services; session unlock if needed |
| 2 | `/cases` create demo case | Visible `[demo data]` marker | TEST-VERIFIED | Create fresh marked case |
| 3 | Add transaction | Transaction/CCTV timestamps | TEST-VERIFIED | Ensure parseable times; adjust window |
| 4 | `/investigation` upload sample | Metadata + SHA-256 | TEST-VERIFIED | Check extension/size; use `synthetic_atm.mp4` |
| 5 | Verify alignment | Offset/window/warnings | TEST-VERIFIED | Correct clock/reference inputs |
| 6 | Start job / CV run | Frames/CV observations | TEST-VERIFIED real-CV + live required | Use verified models; zero detections are valid unvalidated result; retry 503 |
| 7 | Inspect `/cv` associations | Heuristic association/review | TEST-VERIFIED | Show insufficient-evidence reasons; do not weaken thresholds |
| 8 | Best-face inspector | Ranked frames/reliability | TEST-VERIFIED | Show no-selection reason |
| 9 | Enhancement panel | Original vs derived + hashes | TEST-VERIFIED + fixture smoke | Use placeholders; reload presets; no unverified model |
| 10 | Candidate search/review | Similarity ranks + review states | TEST-VERIFIED + exploratory | Wait for 503; explain provenance requirements |
| 11 | `/workspace`, `/evidence` | Manual capture/selection/compare | TEST-VERIFIED + fixture smoke | Reload; select ≤4 frames for compare |
| 12 | `/export` | PDF/JSON/ZIP hashes | TEST-VERIFIED | Select frames; re-stage valid CV items; stale state clears on case switch |

---

## 15. Judge Q&A

Full 40 Q&A: `TASK-21-JUDGE-QA.md`. Key answers:

| Question | Short accurate answer |
| --- | --- |
| What problem is solved? | Faster transaction-anchored evidence triage, not identity confirmation. |
| Why transaction time matters? | It provides an objective anchor and narrows long CCTV to a short window. |
| Does the system verify CCTV clocks? | No. Alignment is arithmetic and records provenance; no OCR/independent clock check. |
| How are persons tracked? | YOLOX + `SimpleTracker`; track IDs are run-local, not identities. |
| Are detections reliable? | Person detection is `experimental_unvalidated`; zero detections are not proof of absence. |
| How are faces detected? | YuNet boxes/landmarks; SFace 128-d embeddings for ranking. |
| What is best-face? | Deterministic best frame for human review under quality heuristics. |
| Is quality an identity score? | No. It is image usability only. |
| Does it identify suspects? | No. It never asserts identity. |
| What does similarity mean? | Visual candidate rank, not identity confidence. |
| Can it prevent false positives? | It reduces them with provenance/eligibility gates and human review, but cannot eliminate them. |
| How is evidence integrity handled? | SHA-256, canonical manifests, PDF hashes, source/model provenance and audit events. |
| Are originals modified? | No. Normalized videos, crops and enhancements are separate derivatives. |
| Is enhancement AI super-resolution? | No. Classical OpenCV only; AI models unavailable. |
| Is there RBAC? | No. Global optional passphrase only; P0-4A documents gaps. |
| Is there criminal/Aadhaar matching? | No; explicitly out of scope and verified absent. |
| Is R4C validated? | No. R4C status is `NOT_ASSESSED`. |
| Is this court-admissible? | No certified chain of custody or legal validation. |
| What performance was measured? | Local TestClient timings and bundle sizes; no production latency or Core Web Vitals. |
| Final readiness? | Synthetic demo-ready with caveats; not production-ready. |

---

## 16. Limitations and risks

### 16.1 Explicit disclosures

- TASK-17 human annotation QA remains `NOT_REVIEWED`; benchmark is exploratory on 48 synthetic frames/46 boxes.
- TASK-18 retrieval benchmark uses 127 synthetic samples, 3 subjects and 4 clips; it does not prove real-world identification accuracy.
- TASK-19 used isolated API/TestClient fixtures; real CCTV validation was not performed.
- TASK-20 browser smoke used CDP fixtures, not backend persistence.
- Real CCTV performance and production inference latency are not established.
- TASK-13 artifacts are unavailable; alternative detector feasibility remains unverified/blocked.
- AI restoration models are not available locally.
- TASK-14 ByteTrack-inspired tracker, TASK-16 quality evaluator, TASK-17/18 benchmarks and YuNet/YOLOX experiments are not production-integrated.
- No live CCTV, OCR clock extraction, skimming/shoulder-surfing detection, statement import, RBAC, actor attribution, WORM, digital signing or certified custody.
- Only MP4/AVI/MOV/MKV are supported; WMV/FLV/MPEG/MPG and proprietary DVR/NVR exports are unsupported.
- Face reliability cannot classify masks/helmets/caps; these are `not_assessed`.
- CV runs are synchronous and budget-bounded; no progress/cancel/refresh for CV runs.
- Candidate reviews are stored against observation IDs, with no authenticated reviewer identity.
- Frontend behavioral tests are absent for Cases, Workspace, Evidence and Compare; browser smoke is fixture-based.
- Current README/PROJECT_STATUS caveats are partly stale for association/enhancement; current source and P0/TASK reports are authoritative.

### 16.2 Risk register

| Risk | Severity | Impact | Mitigation / status |
| --- | --- | --- | --- |
| Misinterpretation as identity system | High | Wrongful accusation | Anti-identity disclaimers, candidate-only DTOs, human review; must be repeated in presentation |
| Real-CCTV failure | High | Demo/operational failure | Use synthetic assets only; state R4C NOT_ASSESSED |
| RBAC absence | High | Unauthorized access in real deployment | Global passphrase only; implement RBAC before any real use |
| Chain-of-custody weakness | High | Evidence challenge | Hashes/manifest only; no WORM/signature/certification |
| Person detector misses | Medium/High | Lost leads | Experimental status; multiple frames; human review; calibrated experiments not production |
| Quality heuristic miscalibration | Medium | Bad frame ranking | TASK-16 isolated; do not use as accuracy claim |
| Format gaps | Medium | Cannot ingest real exports | H.264 MP4 export guidance; broad format support future work |
| Annotation QA incomplete | Medium | Invalid detector metrics | Keep benchmark exploratory; complete visual QA before claims |
| Performance unknown | Medium | Production slowness | Local timings only; async CV and real-load benchmarking future work |

---

## 17. Future roadmap

### Immediate engineering gaps

1. Add authenticated users, RBAC, per-case grants, actor attribution, logout, expiry/revocation and protected-route E2E tests.
2. Add WORM/tamper-evident audit storage, signed manifests and export verification.
3. Implement asynchronous CV runs with progress, cancellation and refresh.
4. Broaden video format support or provide robust conversion tooling for DVR/NVR exports.
5. Recalibrate quality/best-face heuristics and fix TASK-16 noise inflation.
6. Complete human visual QA of annotations and acquire person/track ground truth before detector/tracker accuracy claims.
7. Add behavioral frontend tests for Cases, Workspace, Evidence, Compare and download URLs.
8. Establish real benchmark protocol with approved data and documented hardware.

### Longer-term research opportunities

- Real CCTV/R4C robustness across illumination, compression, occlusion, pose and camera angle.
- Approved alternative detectors/trackers with proper licenses, provenance and annotated ground truth.
- Validated face-quality, concealment and degradation models.
- Calibrated retrieval thresholds on lawful, approved, diverse datasets.
- Governed AI restoration with artifact detection and forensic separation.
- Timeline visualization and better multi-clip comparison tooling.
- Privacy-preserving search and audit controls.

---

## 18. Final readiness assessment

### What can be claimed

- A complete local prototype exists with real source code, 59 API routes, 8 UI routes, SQLite provenance, pinned CPU ONNX models, human review and hash-backed exports.
- Current code passes `331` guarded backend tests and `87` frontend tests, plus typecheck and build.
- Real local CV inference was verified on synthetic assets with pinned model hashes.
- API workflow, cross-case boundaries, stale-review rejection, export hashes and derived-image separation were verified.
- Browser UI smoke passed with fixtures after TASK-20 fixes.

### What cannot be claimed

- No real-world identity recognition accuracy.
- No R4C validation or real CCTV performance.
- No automatic identification or watchlist/Aadhaar/criminal database matching.
- No role-based access control or certified custody.
- No production deployment readiness.
- No court admissibility or official Rajasthan Police certification.

### Final verdict

**Conditional demo-ready; not production-ready.** Present ATM Sentinel as a local, synthetic-data, human-review evidence organization prototype with bounded CV assistance, transparent provenance and explicit limitations. Use the synthetic runbook, show the disclaimers, and answer any accuracy/readiness question with the caveats in this document.

### TASK 21 changed files

- `reports/ps04cctv-audit/ATM-SENTINEL-FINAL-TECHNICAL-SUBMISSION.md`
- `reports/ps04cctv-audit/TASK-21-REQUIREMENT-MAPPING.md`
- `reports/ps04cctv-audit/TASK-21-DEMO-RUNBOOK.md`
- `reports/ps04cctv-audit/TASK-21-JUDGE-QA.md`
- `reports/ps04cctv-audit/TASK-21-FINAL-READINESS.md`
- `reports/ps04cctv-audit/TASK-21-ARCHITECTURE.mmd`

No product source, CV algorithm, detector, tracker, threshold, embedding, schema, package, service, protected data, annotation or benchmark source was changed by TASK 21. `git status --short` was read-only; the worktree contains pre-existing modified/untracked implementation, test, script, artifact and report files from prior tasks plus these six TASK 21 report files. No Git write or synchronization operation was performed.
