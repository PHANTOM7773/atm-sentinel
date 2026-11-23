# PS04CCTV Implementation Gap Plan

- Generated during audit: `2026-11-23T04:08:57Z`
- Status: **planning only**. No gap was implemented during this audit.
- Priority definitions:
  - P0: missing or broken Must Have functionality central to the official problem statement.
  - P1: Must Have verification, reliability and security gaps.
  - P2: Good to Have features.
  - P3: optional improvements not required for the hackathon.

## Recommended implementation order

1. P0-1 ATM keypad/cash-slot person association.
2. P0-2 Best identifiable face selection for the linked person.
3. P0-4 Role-based access for authorised investigators.
4. P0-3 Adverse-condition reliability flags and validation.
5. P0-5 Additional official container formats and real DVR/NVR sample handling.
6. P1-1 Browser-level end-to-end workflow verification.
7. P1-2 R4C/real-data validation under an approved protocol.
8. P1-3 through P1-6 security, audit, provenance and boundary verification.
9. P2 items only after Must Have completion is credible.
10. P3 optional refinements last.

## P0 — Missing or broken Must Have functionality

| ID | Exact missing functionality | Why it matters | Relevant existing code | Proposed implementation | Tests required | Dependencies | Risks | Complexity |
|---|---|---|---|---|---|---|---|---|
| P0-1 | Detect the ATM keypad/cash-slot region and associate one tracked person with the transaction window. | The official objective is the face of the person who performed the withdrawal; current transaction time only selects a window. | `backend/app/cv/pipeline.py`; `backend/app/cv/tracking.py`; `backend/app/schemas.py:187-191` association limitation; `backend/app/services/cv_integration.py:157-299` alignment. | Add an ATM interaction zone model/rule, score candidates by zone dwell time and transaction timing, and expose an explicit linked-person result with confidence and review state. Never auto-assert identity. | Synthetic ATM-angle clip tests with one person, multiple people, occlusion and no interaction; API contract tests; export tests proving association copy is accurate. | Approved ATM-angle sample geometry or annotated synthetic scenes; investigator-reviewed zone definitions. | Wrong association could mislead investigations; camera placement varies; false confidence risk. | L |
| P0-2 | Select the single best identifiable face frame for the linked ATM person. | Must Have says “obtain best face frames”; current code only retains quality-priority observations and deduplicates. | `backend/app/cv/pipeline.py:410-418,571-638`; `backend/app/cv/quality.py`; `backend/app/cv/crop.py:60-66`. | Add a ranked best-frame endpoint/field combining person association, quality components, sharpness, pose and review state; retain original frame reference and crop hash. | Unit tests for ranking inputs/tie-breaks; synthetic clip tests; API tests; UI rendering tests; export tests. | P0-1 linked-person result; validated quality thresholds. | Ranking heuristic may appear authoritative; must remain candidate-only and human-reviewed. | M |
| P0-3 | Validate and expose reliability for poor lighting, side angles, partial occlusion and low resolution; implement mask/helmet/cap classification or keep explicit not-assessed state. | Official problem statement requires robustness and reliability flags. Current behavior is warning/flag only and mask/helmet/cap are `not_assessed`. | `backend/app/cv/quality.py:52-81`; `backend/app/cv/landmarks.py:28-91`; `backend/app/services/cv_integration.py:58,430-432`; `frontend/src/pages/CvRuns.tsx:496-533`. | Define measurable thresholds, calibrate on approved synthetic/real samples, add classifiers where justified, and render each attribute as validated/heuristic/not_assessed. | Calibration tests; labeled synthetic clips; API contract tests; frontend tests for honest status rendering. | Labeled adverse-condition data; model approval; documented thresholds. | Classifiers may be unreliable; training data risk; overclaiming reliability. | L |
| P0-4 | Implement role-based access for authorised investigators. | Official requirement explicitly says authorised investigators; one global passphrase is not role-based. | `backend/app/main.py:34-63`; `backend/app/services/security.py:93-100`; `frontend/src/App.tsx:16-25`; `frontend/src/components/AppShell.tsx:47-56,107-136`. | Add users, roles, per-case grants, authenticated dependencies on all APIs, actor IDs in audit events, route guards and UI permission filtering. | Auth unit tests; endpoint authorization matrix tests; audit actor tests; frontend guard tests; cross-user denial tests. | Identity provider decision; password/session policy; DB migration. | Migration risk; service disruption if misconfigured; must not expose secrets. | L |
| P0-5 | Support WMV, FLV and MPEG/MPG and genuine DVR/NVR export handling. | Key feature 1 explicitly lists these formats and compatible DVR/NVR exports. Current app supports four local containers plus guidance. | `backend/app/config.py:20`; `backend/app/services/security.py:13-18,40-67`; `backend/app/services/video.py`; `backend/app/routers/videos.py:19-103`. | Add validated magic/probe support for additional containers and vendor-export adapters that convert to MP4 while preserving originals and provenance. | Synthetic files per format; probe/decode/normalize tests; unsupported-format rejection tests; vendor sample regression tests. | Sample files and vendor export specifications. | Codec variability; proprietary formats; security risk from new parsers. | L |
| P0-6 | Replace stubbed inference evidence with real CV verification for the official workflow. | Previous 12-clip scenario used stubbed CV inference; real model detection/embedding behavior is only thinly verified. | `backend/app/cv/pipeline.py`; `backend/tests/test_cv_engine.py:252-272`; `backend/tests/test_cv_accuracy_evidence.py`. | Run narrowly scoped real-model synthetic scenarios with pinned model hashes and record exact detection/search outputs without claiming R4C accuracy. | Real-model smoke tests with skip guards; provenance tests; no prohibited generator scripts. | Existing pinned models; synthetic clips. | Real-model timing; model-file availability; synthetic results can still be overinterpreted. | M |

## P1 — Must Have verification and reliability gaps

| ID | Exact missing functionality | Why it matters | Relevant existing code | Proposed implementation | Tests required | Dependencies | Risks | Complexity |
|---|---|---|---|---|---|---|---|---|
| P1-1 | Browser interaction E2E for upload, timestamp entry, alignment preview, CV run, candidate search, review and export. | Current frontend evidence is static/pure-function/API-client only; full user workflow is not browser-verified. | `frontend/src/pages/Investigation.tsx`; `frontend/src/pages/CvRuns.tsx`; `frontend/src/pages/Export.tsx`; existing `*.test.ts` files. | Add a browser automation suite using local synthetic fixtures and isolated data. | Playwright/Vitest browser tests for the full workflow and failure states. | Test browser; isolated backend instance or TestClient harness; explicit test data. | Test flakiness; service interference if not isolated. | M |
| P1-2 | R4C/real-data validation under approved protocol. | No official real ATM-angle footage, format variation or timestamps were assessed. | No current R4C code; CV limitation copy in schemas/export. | Define protocol, metrics and acceptance thresholds; run only with approved samples and human oversight. | Protocol-driven evaluation report; per-condition metrics; review panel evidence. | R4C data approval; labeled same/different person clips; privacy controls. | Real personal data risk; metric misuse; identity overclaiming. | L |
| P1-3 | Complete actor-attributed audit events and dedicated audit review/export. | Audit is partial; no actor, no full coverage, no dedicated UI/API. | `backend/app/db.py:131-137,297-301`; `backend/app/routers/system.py:13-33`; `frontend/src/pages/Dashboard.tsx:107-123`. | Add actor_id, more event types, case-scoped audit endpoint, filters and audit export. | Audit coverage matrix tests; actor attribution tests; export tests; UI tests. | P0-4 users/roles; DB migration. | Schema migration; audit volume; privacy of reviewer notes. | M |
| P1-4 | Tamper-evident/WORM or certified chain-of-custody controls if required. | Current local SQLite append-only logs and SHA-256 hashes are not tamper-proof. | `backend/app/db.py`; `backend/app/services/export.py:312-610`. | Decide whether hashing/signing/manifest verification is sufficient; otherwise add tamper-evident storage and signed manifests. | Hash verification tests; signature verification tests; negative tamper tests. | Security policy; key management. | Key custody complexity; may exceed hackathon scope. | L |
| P1-5 | Unify provenance version strings and add explicit stale/incompatible-record policy. | `cv-phase1-remediated` and `cv-phase2-persistent-runs` coexist; records remain validated but versioning is confusing. | `backend/app/cv/pipeline.py:463`; `backend/app/services/cv_integration.py:327`; schema v4 constants. | Define one pipeline version field with component versions and migration policy. | Provenance tests; stale-record rejection tests; export tests. | None beyond code change approval. | Must invalidate or migrate old records carefully. | S |
| P1-6 | Production-limit boundary stress for configured upload, duration, decoded-frame, crop and top-K limits. | Limits exist and unit tests check some validation, but full configured boundaries were not exercised in this audit. | `backend/app/config.py:19,33-44,68`; `backend/app/routers/cv.py:69-199`; tests for controlled errors. | Run isolated boundary tests with synthetic files only; do not alter production limits or data. | Boundary tests per limit; resource cleanup assertions; controlled-error tests. | Local synthetic large/dense video generation; disk/time budget. | Slow tests; resource exhaustion; must not touch user data. | M |

## P2 — Good to Have features

| ID | Exact missing functionality | Why it matters | Relevant existing code | Proposed implementation | Tests required | Dependencies | Risks | Complexity |
|---|---|---|---|---|---|---|---|---|
| P2-1 | Vendor-specific DVR/NVR export parsers and conversion workflows. | Would improve compatibility beyond static guidance. | `backend/app/services/security.py`; `backend/app/services/video.py`; `frontend/src/pages/Cases.tsx:312-315`. | Add adapters per vendor/export family with original-file preservation and conversion provenance. | Vendor sample tests; conversion/normalization tests; provenance tests. | Vendor samples and licenses. | Proprietary behavior changes; parser security. | L |
| P2-2 | Skimming-device or shoulder-surfing detection. | Explicit Good to Have item; currently absent. | No implementation; generic person detection in `backend/app/cv/detection.py` must not be counted. | Add ATM overlay/device detector and second-person proximity/gaze behavior logic with human-review output only. | Labeled synthetic tests; false-positive checks; API/UI/export tests. | Labeled scenario data; model approval. | High false positives; action recognition difficulty; sensitive claims. | L |
| P2-3 | Clearly labelled optional face enhancement. | Explicit Good to Have item; current crops are raw derived artifacts. | `backend/app/cv/crop.py:21-57`; export provenance. | Add optional enhancement operation that creates a separate enhanced artifact with original hash, algorithm/version and UI/export label. | Enhancement output tests; original-vs-enhanced distinction tests; provenance tests. | Approved enhancement algorithm; quality validation. | Could mislead investigators; must not overwrite originals. | M |

## P3 — Optional improvements not required for the hackathon

| ID | Exact missing functionality | Why it matters | Relevant existing code | Proposed implementation | Tests required | Dependencies | Risks | Complexity |
|---|---|---|---|---|---|---|---|---|
| P3-1 | Dedicated tabular evidence sheet screen. | Current output is PDF, JSON manifest, ZIP and contact sheet; “evidence sheet” may be interpreted as a distinct tabular UI. | `frontend/src/pages/Export.tsx`; `backend/app/services/export.py`. | Add a reviewable table of selected frames/CV references before generation. | UI tests; export parity tests. | None. | Scope creep if not required. | S |
| P3-2 | Richer timeline visualization. | Helps manual review but is not an official requirement. | `backend/app/routers/cases.py:179-197`; `frontend/src/pages/Workspace.tsx`. | Add interactive timeline overlays for transaction, window, tracks and selections. | UI tests; performance tests. | None. | Distraction from Must Haves. | M |
| P3-3 | Search/ranking quality dashboards and calibration reports. | Useful transparency, not required. | `backend/app/cv/embeddings.py`; `backend/tests/test_cv_candidate_search.py`. | Add local-only diagnostics for score distributions and provenance coverage. | Unit and UI tests. | Aggregated non-personal metrics only. | Could be mistaken for accuracy metrics. | M |
| P3-4 | Export verification endpoint for manifests/PDFs. | Improves local integrity checks, not required. | `backend/app/services/export.py`; `backend/app/routers/exports.py`. | Add an endpoint that verifies a supplied manifest against stored hashes. | Positive and tamper-negative tests. | None. | Must avoid exposing sensitive file paths. | S |

## Explicit non-action during this audit

- No source, configuration, database, model, dependency or CV algorithm was changed.
- No gap above was implemented.
- No prohibited script was executed.
- No application service was stopped, restarted or reconfigured.

Stop after this report generation; wait for explicit approval before implementation.
