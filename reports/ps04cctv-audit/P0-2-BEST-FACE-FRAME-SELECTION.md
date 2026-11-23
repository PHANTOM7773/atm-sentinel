# P0-2 Best-Face Frame Selection

Status: **COMPLETE**

Scope: deterministic selection of the best-quality existing face observation for a linked transaction/person association, focused backend tests, the minimum read-only frontend summary needed to expose the result, and verification.

## Objective

Provide a deterministic, evidence-preserving way to choose one face-bearing frame from already-extracted CV observations for a linked ATM transaction/person association, and expose the outcome as a review aid without making identity, account-holder, or biometric claims.

## Audit Findings

- No existing best-face selection routine was found in `backend/app` or `frontend/src`.
- Existing functionality already included YuNet face detection, quality metrics components, quality-priority observation retention, near-duplicate suppression, bounded candidate ranking, person/zone association, human review, and export.
- `reports/ps04cctv-audit/REQUIREMENTS_MATRIX.json` marked KF4.2 Best frames as `PARTIAL`; the missing pieces were a per-linked-person best-frame selector and a human-facing summary.
- Frontend `CvAssociationCard` showed association evidence and review controls but had no best-face field.

## Implementation

### Backend

New file:

- `backend/app/services/best_face.py`

Modified files:

- `backend/app/schemas.py`
- `backend/app/services/atm_association.py`
- `backend/app/routers/cv.py`

Added:

- Deterministic selector over existing face/person observations:
  - same-frame person bbox containment link,
  - minimum bbox containment `0.6`,
  - hard rejection for unretrievable crop, low detector confidence, low sharpness, under/overexposure, small face, pose-away, occlusion-suspected, missing quality components, and unusable person link,
  - occlusion-review penalty factor `0.75`,
  - weighted quality heuristic over existing components,
  - deterministic tie-break by earlier original frame number then observation ID.
- Read-only endpoint:
  - `GET /api/cv/runs/{cv_run_id}/person-associations/{association_id}/best-face?case_id=...`
  - case/run/association scoped; returns selected frame, ranked/rejected/other frames, reason codes, methodology, score meaning, and limitation.
- Association list summaries:
  - `TransactionPersonAssociationRecord.best_face` now carries a compact read-only summary.
- DTOs/constants:
  - `CvBestFaceLinkSummary`
  - `CvBestFaceRankedFrame`
  - `CvBestFaceSelectionSummary`
  - `CvBestFaceSelectionResponse`
  - `CV_BEST_FACE_SCORE_MEANING`
  - `CV_BEST_FACE_LIMITATION`

No new threshold was invented: the detector-confidence floor reuses existing `CV_FACE_SCORE_THRESHOLD = 0.6`; all other inputs are existing quality components/flags. No database write, schema migration, model change, dependency, tracker change, or association-logic change was introduced.

### Frontend

Modified files:

- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/pages/CvRuns.tsx`
- `frontend/src/pages/CvRunsView.test.ts`
- `frontend/src/lib/cvReviewApi.test.ts`

Added the minimum display needed to make the backend result reviewable:

- best-face response and summary types,
- `cvApi.getBestFace(...)` client method,
- read-only summary in `CvAssociationCard` showing status, observation ID, frame, video time, rank score, counts, score meaning, and limitation,
- no-selection reason display,
- focused presentational and API-client tests.

The frontend performs no ranking, thresholding, crop retrieval, or selection; it only renders backend-provided evidence.

## Tests Added

- `backend/tests/test_best_face.py`
  - 13 focused mocked tests covering quality ordering, sharpness, resolution, pose/illumination/occlusion, tie-breaking, no usable face, low-quality-only frame, unretrievable crop, different person, ambiguous link, rejected association, no DB writes, endpoint scoping, and association-list summaries.
- `backend/tests/test_best_face_real_cv.py`
  - 1 actual-model test using existing `data/datasets/synthetic/cv/subject_a_front.mp4` and pinned local YuNet/YOLOX/SFace models.
- Frontend tests:
  - best-face summary rendering with and without selection,
  - exact best-face API URL.

## Verification

All commands were run from `/Users/yps/Dev/web/atm` with backend test isolation under `reports/ps04cctv-audit/.verification-tmp/p02-pytest` and `PYTHONDONTWRITEBYTECODE=1`.

Focused backend + relevant regression set:

```text
122 passed, 1 warning in 31.40s
```

Guarded backend suite:

```text
247 passed, 1 deselected, 1 warning in 42.14s
```

Deselected test:

```text
backend/tests/test_cv_engine.py::test_synthetic_generator_writes_labelled_clips
```

Frontend checks:

```text
npm run test -- --run: 74 passed across 9 test files
npm run typecheck: passed
npm run build: passed
```

Only backend warning is the existing Starlette/httpx deprecation warning from `fastapi.testclient`. No prohibited scripts were run, no synthetic videos were generated, and no models were downloaded.

### Actual-model validation

Existing asset:

```text
data/datasets/synthetic/cv/subject_a_front.mp4
sha256 cdda2c7344346be6df6147b568327a1427d442e899de69722a6c17e0cd0741a2
```

Result:

```text
face detections: 12
retained face records: 8
ranked: 8
rejected: 0
other-person frames: 0
selected observation: aafe9d50dc8c5a15b1c79be53c8b9c40
selected frame: 5
selected timestamp: 0.5s
selection score: 0.9741
selected quality_score: 98.3
top rationale: sharpness 0.3000, usable_resolution 0.1500, illumination 0.1419, bbox containment 1.000
```

This confirms the selector consumes real detector output, real quality components, real crop retrievability, and real same-frame bbox linkage rather than only mocked fixtures.

## Protection Checks

Pre-change protected-path snapshot (`data/uploads`, `data/evidence`, `data/exports`, `data/datasets`, `data/models`):

```text
16 files; sha256 64c13a65182d6d1c8a1e18c4b73d056fd15f1e21b46a623ad5054e149b2e52a2
```

After verification, the same 16 protected files were present with unchanged sizes and pre-P0-2 modification times. No protected upload, evidence, export, dataset, or model file was written by this task.

Service PIDs unchanged:

```text
90317 uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
90347 vite --host 127.0.0.1 --host 127.0.0.1 --port 5173 --strictPort
```

No service was restarted or stopped. No Git operations were performed.

## Requirement Confirmation

- Best frame is selected from existing CV observations only.
- Selection is deterministic and explainable via score, reason codes, rationale, and tie-break.
- Only retrievable, detector-accepted, quality-usable, same-frame person-linked faces can be selected.
- Rejected, other-person, no-selection, rejected-association, and no-track states are explicit.
- Human review remains mandatory; original evidence remains preserved.
- Score meaning and limitation explicitly reject identity/biometric interpretation.
- No schema migration was required.
- P0-3 was not started.

## Limitations

- The real-CV check uses the existing local synthetic asset and pinned local models; it is not a live CCTV deployment benchmark.
- Face-to-person linkage is bbox containment in the same frame, not identity matching.
- Quality components are existing heuristic proxies, not calibrated biometric or identity confidence.
- Association list summaries are computed on demand; no persistent materialized best-face table was added.
