# ATM Sentinel — Official PS04CCTV Requirements Compliance Audit

- Generated: `2026-11-23T04:08:57Z`
- Project root: `/Users/yps/Dev/web/atm`
- Audit completion status: **Complete**
- Audit type: requirements compliance only; no implementation work was started
- Evidence policy: current source and executed narrowly scoped tests were treated as authoritative. Previous reports, status documents and feature descriptions were inspected only as context and were not used to grant credit.

## 1. Executive summary

| Measure | Score | Interpretation |
|---|---:|---|
| MUST HAVE completion | **88/100** | Core local mechanics are mostly present. Lowered by missing ATM-operator association, unvalidated best-face selection and unvalidated CV accuracy. |
| GOOD TO HAVE completion | **8/100** | Only static DVR/NVR conversion guidance exists. Skimming/shoulder-surfing and labelled face enhancement are absent. |
| Overall official PS04CCTV compliance | **58/100** | Includes key features, good-to-have items, cross-cutting requirements, four correctly absent out-of-scope controls and R4C validation gap. |
| Local technical verification | **63/100** | Measures which official capabilities were actually verified locally by executed tests, not the test pass rate. |

These are internal engineering assessments, **not official Rajasthan Police certification**. A planned feature, documentation claim, placeholder, static disclaimer or unexecuted test received no verified-completion credit. Partial implementations received only partial credit.

### Mandatory status vocabulary

`VERIFIED LOCALLY`, `IMPLEMENTED BUT NOT FULLY VERIFIED`, `PARTIAL`, `NOT IMPLEMENTED`, `NOT ASSESSED`, `OUT OF SCOPE — CORRECTLY NOT IMPLEMENTED`, `OUT OF SCOPE — UNEXPECTED IMPLEMENTATION FOUND`.

No instance of `OUT OF SCOPE — UNEXPECTED IMPLEMENTATION FOUND` was found.

## 2. Audit and verification commands

No broad acceptance runner was executed. No prohibited scripts were invoked.

### Backend command

```bash
/Users/yps/Dev/web/atm/.venv/bin/python -m pytest backend/tests/test_security.py backend/tests/test_video.py backend/tests/test_timestamps.py backend/tests/test_pipeline.py backend/tests/test_cv_alignment.py backend/tests/test_quality.py backend/tests/test_cv_engine.py backend/tests/test_cv_accuracy_evidence.py backend/tests/test_cv_candidate_search.py backend/tests/test_cv_review.py backend/tests/test_cv_embedding_store_v4.py backend/tests/test_cv_embedding_publication.py backend/tests/test_cv_observation_identity.py backend/tests/test_cv_integration.py -q --tb=short --deselect=backend/tests/test_cv_engine.py::test_synthetic_generator_writes_labelled_clips
```

Workdir: `/Users/yps/Dev/web/atm`

Result: `215 passed, 1 deselected, 1 warning in 30.36s`. The warning is a `StarletteDeprecationWarning` from `fastapi.testclient`, unrelated to PS04CCTV behavior. The deselected node imports prohibited `scripts/generate_synthetic_cv_assets.py`.

### Frontend command

```bash
npm run test -- --run src/components/AppShell.test.ts src/lib/cvContract.test.ts src/lib/cvReviewApi.test.ts src/lib/demo.test.ts src/lib/format.test.ts src/lib/sessionApi.test.ts src/pages/CvRunsView.test.ts src/pages/Export.test.ts src/pages/TrustCopy.test.ts
```

Workdir: `/Users/yps/Dev/web/atm/frontend`

Result: `Test Files 9 passed (9)`, `Tests 65 passed (65)`.

### Isolation and safety evidence

- `backend/tests/conftest.py:14-38` points all app data at a fresh temp directory and cleans it per test.
- Backend HTTP tests use in-process `TestClient`; no service ports were touched.
- Frontend API tests stub `fetch`; no network calls were made.
- Source/config/data snapshot before tests: `215 files; sha256 1b132acc1c781f4a272a9eb5e2a13e1ee664e0024814d1c17fc8883a09e590ee`.
- Source/config/data snapshot after tests: identical.
- Backend PID before/after: `90317`.
- Frontend PID before/after: `90347`.

## 3. Scoring formula

Status weights:

| Status | Credit |
|---|---:|
| VERIFIED LOCALLY | 1.00 |
| IMPLEMENTED BUT NOT FULLY VERIFIED | 0.60 |
| PARTIAL | 0.40 |
| NOT IMPLEMENTED | 0.00 |
| NOT ASSESSED | 0.00 |
| OUT OF SCOPE — CORRECTLY NOT IMPLEMENTED | 1.00 for out-of-scope compliance |
| OUT OF SCOPE — UNEXPECTED IMPLEMENTATION FOUND | 0.00 |

Special narrower partial weights were used where only one sub-feature exists:

- reliability flags: `0.25` because only partial-face heuristic exists; mask/helmet/cap are `not_assessed`;
- adverse-condition robustness: `0.25` because warnings exist but no validated robustness operation;
- proprietary DVR/NVR export handling: `0.25` because conversion guidance exists but no vendor-specific handling.

### MUST HAVE score detail

| Must Have | Earned / possible | Score |
|---|---:|---:|
| MH-1 upload + timestamp + best faces + quality scores | 8.8 / 12 | 73.3 |
| MH-2 at least three common formats | 5 / 5 | 100 |
| MH-3 cross-clip search + evidence sheet | 9.0 / 10 | 90 |
| Must Have average | — | **88/100** |

MH-1 credits verified upload, timestamp input, configurable window, alignment computation, crops, quality scores and evidence preservation. It penalizes missing ATM-operator association, partial face detection, partial best-frame selection, partial robustness and lack of browser E2E verification.

MH-2 credits four synthetic containers (MP4, AVI, MOV, MKV) that were accepted, probed, decoded and normalized. MP4 also completed the full upload/extraction/select/export pipeline.

MH-3 credits verified search mechanics, case scoping, source exclusion, ranking, provenance, review and export. It penalizes lack of browser E2E, lack of real same-person accuracy validation and stubbed synthetic inference in the previous acceptance scenario.

### GOOD TO HAVE score detail

| Good to Have | Status | Credit |
|---|---|---:|
| GH-1 proprietary DVR/NVR export handling | PARTIAL | 0.25 / 1 |
| GH-2 skimming/shoulder-surfing detection | NOT IMPLEMENTED | 0 / 1 |
| GH-3 labelled face enhancement | NOT IMPLEMENTED | 0 / 1 |
| Good to Have total | — | **8/100** |

### Overall compliance score detail

The 25-item overall rubric earned `14.55 / 25 = 58.2`, rounded to **58/100**. It includes the key feature bullets, good-to-have items, cross-cutting reliability/security requirements, four correctly absent out-of-scope controls and the R4C validation gap.

### Local technical verification score detail

The 16-area verification rubric earned `10.1 / 16 = 63.1`, rounded to **63/100**. High-credit areas include formats, alignment, quality formula, tracking mechanics, embeddings, search, review, export and audit. Zero or low-credit areas include ATM association, RBAC, real robustness, browser interaction E2E, R4C and production-limit boundary stress.

## 4. Requirement-by-requirement summary

| Requirement | Category | Status | Evidence | Missing work |
|---|---|---|---|---|
| KF1.1 Accept listed formats and DVR/NVR exports | MUST HAVE / key feature | PARTIAL | `config.py:20`; `security.py:13-18,40-67`; `videos.py:19-103`; tests passed for mp4/avi/mov/mkv | WMV, FLV, MPEG/MPG, real DVR/NVR vendor exports |
| KF1.2 Codec, resolution, duration | MUST HAVE / key feature | VERIFIED LOCALLY | `video.py:50-109`; `test_video.py` passed | Nothing for local containers |
| KF1.3 Validate and normalize with FFmpeg | MUST HAVE / key feature | VERIFIED LOCALLY | `video.py:112-147`; `videos.py:148-218`; AVI/MOV/MKV normalized derivatives passed | Automatic unsupported-format transcode |
| KF1.4 Unsupported format guidance | MUST HAVE / key feature | VERIFIED LOCALLY | `security.py:40-56`; `test_security.py` passed | Vendor-specific handling |
| KF2.1 Detect and track people | MUST HAVE / key feature | PARTIAL | `detection.py:73-207`; `tracking.py:41-138`; tracker tests passed | Validated ATM-scene person detection |
| KF2.2 Person at keypad/cash slot | MUST HAVE / key feature | NOT IMPLEMENTED | `schemas.py:187-191` explicitly denies association | Region detection and person-transaction linking |
| KF3.1 Transaction time and configurable window | MUST HAVE / key feature | VERIFIED LOCALLY | `timestamp.py`; `cases.py:94-131`; `Investigation.tsx`; timestamp and payload tests passed | Statement/journal import |
| KF3.2 Timestamp alignment | MUST HAVE / key feature | VERIFIED LOCALLY | `timestamp.py:48-146`; `cv_integration.py:157-299`; 18 alignment tests passed | Independent CCTV clock verification/OCR |
| KF4.1 Quality scores | MUST HAVE / key feature | PARTIAL | `cv/quality.py:13-105`; `landmarks.py:28-91`; tests passed | Validated pose/illumination/occlusion accuracy |
| KF4.2 Best frames | MUST HAVE / key feature | PARTIAL | `pipeline.py:410-418,571-638`; cap and dedupe tests passed | Best identifiable face per linked person |
| KF5.1 Reliability flags | MUST HAVE / key feature | PARTIAL | `cv/quality.py:63-81`; `cv_integration.py:58,430-432`; tests passed | Mask/helmet/cap classifiers and validated partial-face detector |
| KF6.1 Cross-clip embedding search | MUST HAVE / key feature | IMPLEMENTED BUT NOT FULLY VERIFIED | `embeddings.py`; `cv_integration.py:1403-1783`; search tests passed | Real-world/R4C same-person accuracy |
| KF6.2 Role-based access | MUST HAVE / key feature | NOT IMPLEMENTED | `main.py:34-63`; one global passphrase only | Users, roles, grants, guards, actor attribution |
| KF6.3 Audit log | MUST HAVE / key feature | PARTIAL | `db.py:131-137,297-301`; selected audit tests passed | Actor, WORM, dedicated audit API/page, full event coverage |
| KF6.4 Downloadable evidence sheet | MUST HAVE / key feature | VERIFIED LOCALLY | `export.py:312-610`; `exports.py`; export tests passed | Certified custody/signing; distinct tabular sheet if required |
| MH-1 Complete upload-to-best-face workflow | MUST HAVE | PARTIAL | Component tests passed; UI workflow inspected | ATM association, validated best-face selection, E2E |
| MH-2 At least three formats | MUST HAVE | VERIFIED LOCALLY | MP4/AVI/MOV/MKV probed, decoded, normalized | Nothing for the Must Have threshold |
| MH-3 Search and export workflow | MUST HAVE | IMPLEMENTED BUT NOT FULLY VERIFIED | Search/review/export mechanics tests passed | Browser E2E and real clip evidence |
| GH-1 DVR/NVR export handling | GOOD TO HAVE | PARTIAL | Conversion guidance errors and UI copy tested | Vendor-specific parsers/wrappers |
| GH-2 Skimming/shoulder-surfing | GOOD TO HAVE | NOT IMPLEMENTED | No source/endpoint/test found | Entire feature |
| GH-3 Labelled enhancement | GOOD TO HAVE | NOT IMPLEMENTED | `crop.py:21-57` saves raw crops | Optional enhancement and enhanced/original labelling |
| OOS-1 Criminal database matching | OUT OF SCOPE | OUT OF SCOPE — CORRECTLY NOT IMPLEMENTED | No implementation found; candidate-only tests passed | None |
| OOS-2 Aadhaar matching | OUT OF SCOPE | OUT OF SCOPE — CORRECTLY NOT IMPLEMENTED | No implementation found | None |
| OOS-3 Automatic identity assertion | OUT OF SCOPE | OUT OF SCOPE — CORRECTLY NOT IMPLEMENTED | `schemas.py:185-190,483,539`; `cv/quality.py:80`; tests passed | None |
| OOS-4 Live bank CCTV connection | OUT OF SCOPE | OUT OF SCOPE — CORRECTLY NOT IMPLEMENTED | File-upload intake only; no RTSP/ONVIF code | None |
| Robustness to lighting/angles/occlusion/low-res | CROSS-CUTTING | PARTIAL | Warning and flag tests passed; no accuracy validation | Validated robustness operations |
| Human verification | CROSS-CUTTING | VERIFIED LOCALLY | Review CRUD, validation, audit and UI copy tests passed | Authenticated reviewer identity |
| Evidence provenance/export integrity | CROSS-CUTTING | VERIFIED LOCALLY | Hash, provenance, stale/cross-case rejection tests passed | WORM/signature/certified custody |
| Sample data only / synthetic allowed | SAMPLE DATA RULE | VERIFIED LOCALLY | Synthetic fixtures, temp DB, demo labels; tests passed | None |
| R4C validation | VALIDATION | NOT ASSESSED | No R4C dataset/protocol used | Approved real-data protocol and results |

## 5. Must Have compliance

### MH-1: Upload + transaction timestamp + best face frames + quality scores

**Works end to end at the local mechanics level:** upload a synthetic MP4, create a transaction with `transaction_ts` and `cctv_ts`, preview alignment, choose a configurable window, launch extraction/CV, obtain face observations with crops and explainable quality scores, select evidence and export a report. The relevant backend and frontend contract tests executed successfully.

**Partial:** actual face detection is real OpenCV wiring but unvalidated for ATM footage; quality scores are explainable heuristics; frame selection is quality-priority retention and near-duplicate suppression rather than a dedicated best-identifiable-face feature; frontend workflow has static/contract tests but no interaction E2E.

**Missing:** no logic associates the best face with the person at the ATM keypad or cash slot. Transaction time only aligns video time.

**Verdict:** `PARTIAL`. The complete user workflow is operationally present as a local prototype, but the official objective “extracts the best identifiable facial image of the person linked to a specific ATM transaction” is not fully implemented or verified.

### MH-2: At least three common video formats

| Format | Accepted by validation | Probed | Fully decoded | Normalized to MP4 | Full upload/extract/select/export |
|---|---|---|---|---|---|
| MP4 | Yes | Yes | Yes | Not needed | Yes |
| AVI | Yes | Yes | Yes | Yes | Not separately executed |
| MOV | Yes | Yes | Yes | Yes | Not separately executed |
| MKV | Yes | Yes | Yes | Yes | Not separately executed |
| WMV/FLV/MPEG/MPG | No | No | No | No | No |
| Real DVR/NVR exports | No | No | No | No | No |

**Verdict:** `VERIFIED LOCALLY`. Four common synthetic formats exceed the “at least three” Must Have threshold. This does not extend to the broader key-feature format list or real DVR/NVR exports.

### MH-3: Search selected face + evidence sheet

**Verified locally:** case-scoped candidate search, query observation lookup, embedding provenance, v4-only eligibility, source-video exclusion, top-K bounds, scan diagnostics, human review, crop retrieval validation, explicit CV export selection, generated PDF, JSON manifest, ZIP and contact sheet.

**Partial:** embedding accuracy is not validated; previous 12-clip acceptance used stubbed CV inference; frontend was verified with static/pure-function/API-client tests rather than browser interaction E2E.

**Verdict:** `IMPLEMENTED BUT NOT FULLY VERIFIED`. The full mechanics are operational as a local prototype; real same-person search reliability and browser E2E remain unverified.

## 6. Good to Have compliance

- **GH-1 DVR/NVR export handling — PARTIAL:** users receive clear guidance to export H.264 MP4 from vendor tools. No vendor-specific parser, wrapper, metadata handler or proprietary container support exists.
- **GH-2 Skimming/shoulder-surfing — NOT IMPLEMENTED:** no device/overlay detector, second-person proximity/gaze behavior logic, suspicious action model, endpoint, schema or test was found. Generic person detection was not counted.
- **GH-3 Clearly labelled face enhancement — NOT IMPLEMENTED:** no enhancement, super-resolution, deblurring or relighting operation exists. Raw crops are saved as derived evidence; resizing, cropping and contrast metrics are not enhancement.

## 7. Out-of-scope audit

| Out-of-scope item | Finding | Status |
|---|---|---|
| Criminal database matching | No criminal/watchlist code, endpoint or UI found. SFace is constrained to candidate ranking. | OUT OF SCOPE — CORRECTLY NOT IMPLEMENTED |
| Aadhaar database matching | No Aadhaar references or matching code found in `backend/app`. | OUT OF SCOPE — CORRECTLY NOT IMPLEMENTED |
| Automatic identity assertion | Hard-coded `candidate_only`, `identity_confirmed: False`, `requires_human_verification: True` and disclaimers. | OUT OF SCOPE — CORRECTLY NOT IMPLEMENTED |
| Live bank CCTV connection | File upload only; no RTSP/ONVIF/network CCTV client found. | OUT OF SCOPE — CORRECTLY NOT IMPLEMENTED |

Other unnecessary scope expansion found: none requiring immediate review. Persistent CV runs, review state and similarity search are directly related to the official problem statement. Several disclaimers and provenance safeguards are defensive rather than scope expansion.

## 8. Cross-cutting limitations

- **Face detection robustness:** real YuNet/YOLOX wiring with pinned SHA-256 gates exists, but person detection is explicitly `experimental_unvalidated`; no R4C or real CCTV accuracy proof exists.
- **Poor lighting/side angles/occlusion/low resolution:** warnings and heuristic flags exist. No illumination normalization, pose normalization, deblurring or super-resolution exists. Stub scenario names such as `low_illumination` and `side_facing` prove pipeline completion only, not robustness.
- **Mask/helmet/cap/partial face:** partial occlusion is an uncalibrated landmark-visibility review flag; mask, helmet and cap are carried as `not_assessed`.
- **ATM operator association:** explicitly absent and disclaimed; transaction time selects/aligns video windows only.
- **Transaction time correctness:** ISO-8601 parsing, offset derivation, manual offsets, clamping and window boundaries are verified. No bank-statement/ATM-journal import and no automatic CCTV clock extraction.
- **Human verification:** review decisions are stored and required for CV export, but reviewers are not authenticated or attributed.
- **Role-based access:** only one optional global local passphrase; open mode when unset; no roles, users or per-case grants.
- **Audit logging:** append-only SQLite events for selected actions; no actor column, no dedicated audit endpoint/page, incomplete coverage and no tamper-evidence.
- **Evidence provenance/export integrity:** SHA-256, canonical manifest, PDF hash, model/video/source provenance and stale/cross-case rejection are verified. No WORM, digital signature, certified chain of custody or export verification endpoint.

## 9. Gap analysis and completion plan

See `reports/ps04cctv-audit/IMPLEMENTATION_GAP_PLAN.md`. No gap was implemented during this audit.

## 10. Exact source files inspected

Backend application:

- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/db.py`
- `backend/app/schemas.py`
- `backend/app/services/security.py`
- `backend/app/services/video.py`
- `backend/app/services/timestamp.py`
- `backend/app/services/extraction.py`
- `backend/app/services/quality.py`
- `backend/app/services/export.py`
- `backend/app/services/cv_integration.py`
- `backend/app/routers/cases.py`
- `backend/app/routers/videos.py`
- `backend/app/routers/frames.py`
- `backend/app/routers/jobs.py`
- `backend/app/routers/exports.py`
- `backend/app/routers/cv.py`
- `backend/app/routers/system.py`
- `backend/app/cv/pipeline.py`
- `backend/app/cv/detection.py`
- `backend/app/cv/tracking.py`
- `backend/app/cv/quality.py`
- `backend/app/cv/landmarks.py`
- `backend/app/cv/crop.py`
- `backend/app/cv/embeddings.py`
- `backend/app/cv/models.py`
- `backend/app/cv/runtime.py`
- `backend/app/cv/types.py`
- `backend/app/cv/errors.py`

Frontend application:

- `frontend/src/App.tsx`
- `frontend/src/main.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/types.ts`
- `frontend/src/lib/demo.ts`
- `frontend/src/lib/format.ts`
- `frontend/src/lib/cn.ts`
- `frontend/src/components/AppShell.tsx`
- `frontend/src/components/ui.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Cases.tsx`
- `frontend/src/pages/Investigation.tsx`
- `frontend/src/pages/Workspace.tsx`
- `frontend/src/pages/Evidence.tsx`
- `frontend/src/pages/Compare.tsx`
- `frontend/src/pages/CvRuns.tsx`
- `frontend/src/pages/Export.tsx`

Tests inspected:

- `backend/tests/conftest.py`
- `backend/tests/test_security.py`
- `backend/tests/test_video.py`
- `backend/tests/test_timestamps.py`
- `backend/tests/test_pipeline.py`
- `backend/tests/test_quality.py`
- `backend/tests/test_cv_alignment.py`
- `backend/tests/test_cv_engine.py`
- `backend/tests/test_cv_accuracy_evidence.py`
- `backend/tests/test_cv_candidate_search.py`
- `backend/tests/test_cv_review.py`
- `backend/tests/test_cv_embedding_store_v4.py`
- `backend/tests/test_cv_embedding_publication.py`
- `backend/tests/test_cv_observation_identity.py`
- `backend/tests/test_cv_integration.py`
- `frontend/src/components/AppShell.test.ts`
- `frontend/src/lib/cvContract.test.ts`
- `frontend/src/lib/cvReviewApi.test.ts`
- `frontend/src/lib/demo.test.ts`
- `frontend/src/lib/format.test.ts`
- `frontend/src/lib/sessionApi.test.ts`
- `frontend/src/pages/CvRunsView.test.ts`
- `frontend/src/pages/Export.test.ts`
- `frontend/src/pages/TrustCopy.test.ts`

## 11. Confirmations

- No application source, frontend source, database, configuration, upload limits, CV algorithm, dependency, model or real personal data was modified.
- No service was stopped, restarted or reconfigured. Backend PID `90317` and frontend PID `90347` were preserved.
- No external network access, Git operation, dependency installation, model download or prohibited script execution occurred.
- The only new files are the three audit reports in `reports/ps04cctv-audit/`.
