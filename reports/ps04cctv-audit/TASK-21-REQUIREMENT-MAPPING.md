# TASK 21 — Requirement Mapping

## Source of requirements

No literal Rajasthan Police PS04CCTV brief, problem-statement file, checklist, or specification file exists in this repository. `PROJECT_STATUS.md:46` explicitly states: “No literal PS04CCTV checklist exists in this repository.”

The authoritative in-repo source is therefore:

- `reports/ps04cctv-audit/REQUIREMENTS_MATRIX.json` — 30 requirement entries, generated `2026-11-23T04:08:57Z`, marked `audit_only: true`.
- `reports/ps04cctv-audit/REQUIREMENTS_COMPLIANCE_REPORT.md`
- `reports/ps04cctv-audit/IMPLEMENTATION_GAP_PLAN.md`
- `PROJECT_STATUS.md`
- `reports/acceptance/acceptance.json` and `reports/acceptance/acceptance.md`

The `official_requirement` strings in `REQUIREMENTS_MATRIX.json` are the canonical local reconstruction of supplied requirement text. They are **not** verified verbatim copies of an external Rajasthan Police document. The compliance report explicitly says its scores are internal engineering assessments, not official certification.

## Status vocabulary

| Status used here | Meaning |
| --- | --- |
| Implemented and verified | Locally implemented and verified by executed tests, real local inference where stated, or report evidence. Not R4C/certified validation. |
| Implemented partially verified | Implemented and locally exercised, but not fully validated end-to-end in a browser or on real CCTV. |
| Partially implemented | Some mechanics exist, but required coverage, formats, validation, or accuracy evidence is incomplete. |
| Not implemented | No implementation or required external validation evidence exists. |
| Out of scope | Requirement explicitly requires absence; verified absent by source and tests. |

## Must Have / key features

| ID | Requirement text or faithful summary | Current status | Actual source / routes | Tests / reports / evidence | Gaps and limitations |
| --- | --- | --- | --- | --- | --- |
| KF1.1 | Accept MP4, AVI, MOV, MKV, WMV, FLV and MPEG/MPG files and compatible CCTV/DVR/NVR exports. | Partially implemented | `backend/app/config.py:20`; `backend/app/services/security.py:13-18,40-67`; `backend/app/routers/videos.py:19-103`; `POST /api/videos/upload` | `backend/tests/test_security.py:22-58`; `backend/tests/test_video.py:43-54`; `backend/tests/test_pipeline.py:189-226` | Only MP4/AVI/MOV/MKV are allowed. WMV, FLV, MPEG/MPG and real DVR/NVR containers are unsupported. |
| KF1.2 | Detect codec, resolution and duration. | Implemented and verified | `backend/app/services/video.py:50-109,150-161`; `POST /api/videos/upload`; `POST /api/videos/{id}/verify`; `GET /api/videos/{id}` | `backend/tests/test_video.py:6-61`; `backend/tests/test_pipeline.py:64-79` | Depends on ffprobe metadata and supplied file. No proprietary DVR metadata interpretation. |
| KF1.3 | Validate files and normalise them with FFmpeg when required. | Implemented and verified | `backend/app/services/security.py:59-67`; `backend/app/services/video.py:112-147`; `backend/app/routers/videos.py:148-218`; `POST /api/videos/{id}/verify`; `POST /api/videos/{id}/normalize` | `backend/tests/test_video.py`; `backend/tests/test_pipeline.py` | Normalization is video-only and drops audio. Unsupported containers are not auto-transcoded. |
| KF1.4 | Report unsupported or proprietary formats with clear conversion/export instructions. | Implemented and verified | `backend/app/services/security.py:40-56`; `backend/app/services/video.py:20-33`; `frontend/src/pages/Cases.tsx:312-315`; `POST /api/videos/upload` | `backend/tests/test_security.py:29-58` | Static conversion guidance only; no vendor-specific conversion decision tree. |
| KF2.1 | Detect and track people across the clip. | Partially implemented | `backend/app/cv/detection.py:73-207`; `backend/app/cv/tracking.py:41-138`; `backend/app/cv/pipeline.py:296-376`; `POST /api/cv/runs`; `POST /api/cv/analyze`; `GET /api/cv/status` | `backend/tests/test_cv_engine.py:124-201`; `backend/tests/test_cv_accuracy_evidence.py:22-153`; `P0-6-REAL-CV-VERIFICATION.md` | `GET /api/cv/status` reports `experimental_unvalidated`. Production tracker is `SimpleTracker`; ByteTrack-inspired tracker is isolated. P0-6 used test-local threshold `0.1`; production default `0.45` produced zero detections on one synthetic multi-subject clip. |
| KF2.2 | Focus on the person at the ATM keypad or cash slot. | Implemented and verified | `backend/app/services/atm_association.py`; `backend/app/db.py`; `backend/app/routers/cv.py`: `GET /api/cv/runs/{id}/person-associations`, `POST /api/cv/person-associations/{id}/review` | `backend/tests/test_atm_association.py`; `backend/tests/test_cv_real_inference_verification.py`; `P0-1*`, `P0-1A`, `P0-1B` reports | Local synthetic verification only. Heuristic score is not probability or identity confidence. Track IDs are run-local. No R4C validation or real-backend browser E2E. |
| KF3.1 | Use transaction time from a bank statement or ATM journal with a configurable time window. | Implemented and verified | `backend/app/schemas.py:26-44`; `backend/app/routers/cases.py:94-131`; `backend/app/services/timestamp.py`; `POST /api/cases/{id}/transactions`; `POST /api/jobs`; `POST /api/cv/runs`; `POST /api/alignment/preview` | `backend/tests/test_timestamps.py:12-89`; `frontend/src/pages/CvRunsView.test.ts:462-499` | Manual ISO-8601 entry only. No bank-statement/ATM-journal import or OCR. TASK-20 removed stale auto-fill and clarified UTC/CCTV context. |
| KF3.2 | Align transaction time to CCTV video time. | Implemented and verified | `backend/app/services/timestamp.py:48-146`; `backend/app/services/cv_integration.py:157-299`; `backend/app/services/extraction.py:105-119`; `POST /api/alignment/preview`; `POST /api/jobs`; `POST /api/cv/runs` | `backend/tests/test_cv_alignment.py:172-404`; `backend/tests/test_timestamps.py`; `backend/tests/test_pipeline.py` | Mathematical alignment and provenance verified. No independent CCTV clock verification or automatic clock extraction. Naive timestamps are treated as UTC with warnings. |
| KF4.1 | Score sharpness, pose angle, illumination and occlusion. | Partially implemented | `backend/app/cv/quality.py:13-105`; `backend/app/cv/landmarks.py:28-91`; `backend/app/schemas.py:430-462`; `GET /api/cv/runs/{id}/observations` | `backend/tests/test_cv_engine.py`; `backend/tests/test_cv_accuracy_evidence.py`; `backend/tests/test_quality.py`; `TASK-16-*` | Heuristic image-usability scores, not identity/correctness. Pose is geometric proxy; occlusion is landmark-boundary heuristic. TASK-16 evaluator is isolated and its report notes noise can inflate overall score. |
| KF4.2 | Select the best frames. | Implemented and verified | `backend/app/services/best_face.py`; `backend/app/schemas.py` `CV_BEST_FACE_*`; `backend/app/routers/cv.py:360-369`; `GET /api/cv/runs/{id}/person-associations/{assoc}/best-face` | `backend/tests/test_best_face.py`; `backend/tests/test_best_face_real_cv.py`; `P0-2-BEST-FACE-FRAME-SELECTION.md` | Local synthetic real-CV verification only: 12 detections, 8 retained, frame 5 selected, score `0.9741`. Quality components uncalibrated. Face↔person link is bbox containment, not identity. |
| KF5.1 | Flag masks, helmets, caps and partial faces so investigators understand frame reliability. | Partially implemented | `backend/app/cv/quality.py:63-81`; `backend/app/cv/landmarks.py:78-91`; `backend/app/services/face_reliability.py`; `GET /api/cv/runs/{id}/observations` | `backend/tests/test_face_reliability.py`; `frontend/src/lib/cvContract.test.ts`; `P0-3-FACE-RELIABILITY-VISIBILITY-INDICATORS.md` | Mask/helmet/cap remain `not_assessed`. `possible_obstruction` is conservative heuristic, not concealment classification. No validated adverse-condition real-CCTV benchmark. |
| KF6.1 | Search for the same person in other ATM clips using face embeddings. | Implemented partially verified | `backend/app/cv/embeddings.py`; `backend/app/services/cv_integration.py:1403-1783`; `POST /api/cv/candidates/search`; `GET /api/cv/embeddings` | `backend/tests/test_cv_candidate_search.py`; `backend/tests/test_cv_embedding_store_v4.py`; `frontend/src/pages/CvRunsView.test.ts`; `P0-6`; `TASK-18` | Synthetic-only TASK-18: 127 samples, 3 subjects, 4 clips; cross-clip genuine pairs only SYN-A. No production acceptance threshold. Scores are visual similarity, not identity confidence. |
| KF6.2 | Provide role-based access for authorised investigators. | Not implemented | `backend/app/main.py:34-63`; `backend/app/services/security.py:93-100`; `frontend/src/App.tsx:16-25`; `frontend/src/components/AppShell.tsx`; `POST /api/session` | `P0-4A-INVESTIGATOR-ACCESS-CONTROL-AUDIT.md` | Single optional global passphrase, open mode when unset, deterministic shared token, no users/roles/case grants/actor identity/expiry/revocation/logout. `case_id` filtering is not authorization. |
| KF6.3 | Provide an audit log. | Partially implemented | `backend/app/db.py:131-137,297-301`; `backend/app/routers/system.py:13-33`; `backend/app/services/cv_integration.py`; `GET /api/system/status` | `backend/tests/test_pipeline.py:102-173`; `backend/tests/test_cv_review.py`; `backend/tests/test_cv_candidate_search.py`; `P0-4A` | Append-only SQLite events for selected actions and inclusion in exports. No actor column, WORM/tamper evidence, signature, dedicated audit API/page, full read/download coverage, or certified chain of custody. |
| KF6.4 | Provide a downloadable evidence sheet. | Implemented and verified | `backend/app/services/export.py:312-610`; `backend/app/routers/exports.py:17-116`; `frontend/src/pages/Export.tsx:130-364`; `POST /api/exports`; `GET /api/exports`; `GET /api/exports/{id}/pdf`; `GET /api/exports/{id}/manifest`; `GET /api/exports/frames/archive`; `GET /api/exports/contact_sheet` | `backend/tests/test_pipeline.py`; `backend/tests/test_cv_review.py:770-937`; `frontend/src/pages/Export.test.ts` | PDF/JSON/ZIP/contact sheet are provided, not a distinct tabular “evidence sheet” screen. No certified custody or digital signing. CV items are opt-in; enhancement artifacts are not exported. |

## Top-level Must Have

| ID | Requirement text or faithful summary | Current status | Evidence | Gaps and limitations |
| --- | --- | --- | --- | --- |
| MH-1 | Upload a clip with transaction time and obtain best face frames with quality scores. | Implemented partially verified | Full local chain across `videos.py`, `cases.py`, `timestamp.py`, `pipeline.py`, `quality.py`, `atm_association.py`, `best_face.py`, `face_reliability.py`, `frontend/src/pages/Investigation.tsx`, `frontend/src/pages/CvRuns.tsx`; reports `P0-1`, `P0-1A`, `P0-1B`, `P0-2`, `P0-3`, `TASK-19` | No browser E2E against real backend, no R4C/real CCTV, heuristic association/quality, no calibrated best-identifiable-face validation. |
| MH-2 | Support at least three common video formats. | Implemented and verified | MP4/AVI/MOV/MKV allowed in `backend/app/config.py:20`; tests `backend/tests/test_video.py:43-54`, `backend/tests/test_pipeline.py:189-226` | Broader KF1.1 formats remain unsupported. All media used in verification were synthetic. |
| MH-3 | Search a selected face across other sample clips and export an evidence sheet. | Implemented partially verified | `cv_integration.py`; `cv/embeddings.py`; `export.py`; `frontend/src/pages/CvRuns.tsx`; `frontend/src/pages/Export.tsx`; APIs `POST /api/cv/candidates/search`, `POST /api/exports`, `GET /api/exports/{id}/pdf`, `GET /api/exports/{id}/manifest`; tests for search/review/embedding/export/API client; `TASK-19` | No browser E2E with real backend. No real same-person accuracy/R4C. The earlier 12-clip scenario stubbed CV inference; P0-6 later added real local inference but still on synthetic assets. |

## Good to Have

| ID | Requirement text or faithful summary | Current status | Evidence | Gaps and limitations |
| --- | --- | --- | --- | --- |
| GH-1 | Proprietary DVR/NVR export handling. | Partially implemented | `backend/app/services/security.py:40-56`; `backend/app/services/video.py:20-33`; `frontend/src/pages/Cases.tsx:312-315`; `POST /api/videos/upload`; `backend/tests/test_security.py:29-58` | Static H.264 MP4 vendor export guidance only; no vendor-specific parsers or real DVR/NVR samples. |
| GH-2 | Detection of skimming devices or shoulder-surfing behaviour. | Not implemented | No source, API, frontend, schema, or test found. | No device/overlay detector, second-person proximity/gaze logic, suspicious action model, endpoint, schema, or test. Generic person detection must not be counted. |
| GH-3 | Clearly labelled face enhancement. | Implemented partially verified | `backend/app/cv/image_enhancement.py`; `backend/app/cv/ai_restoration_adapters.py`; `backend/app/services/image_enhancement.py`; `backend/app/routers/cv_enhancement.py`; `backend/app/main.py`; `GET /api/cv/enhancement/presets`; `POST /api/cv/enhancement/face-crop`; `GET /api/cv/enhancement/face-crop/meta`; `GET /api/cv/enhancement/face-crop/image`; `frontend/src/components/CvCropEnhancementPanel.tsx`; `TASK-15` | Classical OpenCV only: CLAHE, gamma, brightness/contrast, denoise, unsharp, upscale. GFPGAN/Real-ESRGAN/CodeFormer unavailable. Derived output labelled `"AI-enhanced derived image - not original evidence"`. Not integrated into export, DB, embeddings, or matching. |

## Out of scope

| ID | Requirement text or faithful summary | Current status | Evidence | Notes |
| --- | --- | --- | --- | --- |
| OOS-1 | No matching against real criminal photo databases. | Out of scope | `REQUIREMENTS_MATRIX.json:496-510`; `backend/app/cv/models.py:39-53`; `backend/tests/test_cv_candidate_search.py:364-368`; source sweep found no implementation | Correctly absent. SFace is constrained to candidate ranking. |
| OOS-2 | No Aadhaar database matching. | Out of scope | `REQUIREMENTS_MATRIX.json:512-527`; source sweep found no implementation | Correctly absent. |
| OOS-3 | No automatic identification of a person without human verification. | Out of scope | `backend/app/schemas.py:185-190,483,539`; `backend/app/cv/quality.py:80`; `backend/app/services/cv_integration.py`; tests assert `candidate_only`, `identity_confirmed: False`, `requires_human_verification: True` | Correctly absent. Human review is local and not RBAC-bound. |
| OOS-4 | No live connection to bank CCTV systems. | Out of scope | `backend/app/routers/videos.py:19-103`; `backend/app/cv/models.py:99-107`; `POST /api/videos/upload`; source sweep found no RTSP/ONVIF client | File upload only. No live CCTV integration. |

## Cross-cutting, sample-data and validation

| ID | Requirement text or faithful summary | Current status | Evidence | Gaps and limitations |
| --- | --- | --- | --- | --- |
| CC-ROBUST | Robustness to varying illumination, face angles, partial occlusion and low resolution. | Partially implemented | `backend/app/cv/quality.py:52-75`; `backend/app/cv/landmarks.py:28-91`; `backend/app/cv/detection.py:111-119`; `GET /api/cv/runs/{id}/observations`; tests `test_cv_accuracy_evidence.py`, `test_quality.py`; isolated YUNET/YOLOX experiment modules and reports; `TASK-17` | No illumination normalization, deblurring, or production super-resolution. Synthetic-only. Ground truth remains `NOT_REVIEWED`. TASK-17: 48 frames/46 boxes; not production-ready. |
| CC-HUMAN | Human verification of candidates. | Implemented and verified | `backend/app/services/cv_integration.py:1203-1358`; `frontend/src/pages/CvRuns.tsx`; `POST /api/cv/runs/{id}/observations/{obs}/review`; `GET /api/cv/runs/{id}/reviews`; `backend/tests/test_cv_review.py:164-362`; `frontend/src/pages/CvRunsView.test.ts:416-460` | Reviewers are not authenticated or attributed. Candidate reviews stored against observation IDs. No RBAC. |
| CC-PROV | Evidence provenance and export integrity. | Implemented and verified | `backend/app/db.py:44-64,83-102,139-148`; `backend/app/services/export.py:137-610`; `backend/app/services/cv_integration.py:302-349,1403-1442`; `POST /api/exports`; `GET /api/exports/{id}/manifest`; `GET /api/exports/{id}/pdf`; tests for exports/review/embedding publication; `TASK-19` hash assertions | SHA-256, canonical manifest, PDF hash, model/video/source provenance, stale/cross-case rejection verified. Not certified chain of custody; no WORM, digital signature, or export verification endpoint. Pipeline version strings differ between components. |
| SD-1 | Use sample data only for the hackathon; synthetic data is allowed; never use real personal data. | Implemented and verified | `backend/tests/conftest.py:41-97`; `frontend/src/lib/demo.ts:12-31`; tests `backend/tests/test_video.py`, `backend/tests/test_cv_accuracy_evidence.py`, `frontend/src/lib/demo.test.ts` | Audit used synthetic fixtures/temp dirs. No independent scan of all pre-existing project data for real personal data was performed. |
| R4C | R4C may provide real ATM-angle footage, formats, qualities, timestamps and same/different-person clips. | Not implemented | `REQUIREMENTS_MATRIX.json:631-646`; `reports/acceptance/acceptance.json:224-229` `R4C status NOT ASSESSED`; no R4C dataset/protocol/results found | No approved real-data validation. No real-world accuracy, identity, robustness, container, or timestamp claim is supported. |

## Coverage summary

| Current status | Count | Requirements |
| --- | ---: | --- |
| Implemented and verified | 12 | KF1.2, KF1.3, KF1.4, KF2.2, KF3.1, KF3.2, KF4.2, KF6.4, MH-2, CC-HUMAN, CC-PROV, SD-1 |
| Implemented partially verified | 4 | KF6.1, MH-1, MH-3, GH-3 |
| Partially implemented | 7 | KF1.1, KF2.1, KF4.1, KF5.1, KF6.3, GH-1, CC-ROBUST |
| Not implemented | 3 | KF6.2, GH-2, R4C |
| Out of scope | 4 | OOS-1, OOS-2, OOS-3, OOS-4 |

## Historical compliance scores — audit-time only

Source: `REQUIREMENTS_COMPLIANCE_REPORT.md:11-18`, `REQUIREMENTS_MATRIX.json:18-105`.

| Measure | Exact score |
| --- | ---: |
| Must Have completion | 88/100 |
| Good to Have completion | 8/100 |
| Overall official PS04CCTV compliance | 58/100 |
| Local technical verification | 63/100 |

These scores were computed before later P0/TASK implementations and must not be presented as current or as official Rajasthan Police certification. No recomputed official-style score exists.

## Contradictions and claims to avoid

1. No literal original brief file exists; use the in-repo reconstruction and label it internal.
2. Audit statuses are stale for KF2.2, KF4.2, KF5.1 and GH-3; current source and later reports show implementations.
3. `PROJECT_STATUS.md` discusses 11 requirement areas, `REQUIREMENTS_MATRIX.json` has 30 entries, and the compliance report uses a 25-item overall rubric plus a 16-area local rubric. Do not conflate them.
4. RBAC/WORM are unmet requirements, not merely “out of scope” in the final report.
5. Acceptance `PASS` means local synthetic acceptance only; RBAC, certified custody, browser protected-route smoke and R4C were not passed.
6. README/PROJECT_STATUS feature caveats are partly stale for association and enhancement; identity/RBAC caveats remain valid.
7. TASK-19 had no browser E2E; TASK-20 browser smoke used CDP fixtures, not real backend persistence.
8. Real-CV verification used synthetic clips and, in P0-6, a test-local threshold `0.1`; production default is `0.45`.
9. Mask/helmet/cap are never classified; they remain `not_assessed`.
10. TASK-15 is classical OpenCV enhancement, not AI super-resolution.
11. ByteTrack, TASK-16/17/18 and YuNet/YOLOX experiments are isolated, not production upgrades.
12. Current `SCHEMA_VERSION = 5`; acceptance records `4` historically.
13. Use `331 backend passed / 1 deselected` and `87 frontend tests / 14 files` as the current verified test state, not compliance scores.
14. OOS absences are compliant; do not present them as gaps.
