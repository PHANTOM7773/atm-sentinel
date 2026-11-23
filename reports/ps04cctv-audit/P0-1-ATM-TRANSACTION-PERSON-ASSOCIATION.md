# P0-1 ATM Transaction-Person Association — Completion Report

Status: **COMPLETE**

## Scope delivered

- Added an additive, run-scoped ATM interaction zone to CV runs:
  - Normalized frame-relative geometry: `x`, `y`, `width`, `height` in `0..1`.
  - Validation requires `x + width <= 1` and `y + height <= 1`.
  - Pixel geometry is derived from the source video width/height and persisted with both forms.
  - Zone selection is only available for `transaction_aligned` runs and requires a transaction.
- Persisted zone-local person observations separately from face observations:
  - Run-scoped track IDs only; no person identity, face linkage, embedding, or account-holder inference.
- Added heuristic transaction-person associations:
  - Evidence inputs: zone overlap, dwell duration, transaction-window overlap, track continuity, and observation-quality proxy.
  - Outputs: `review_state`, `evidence_strength`, `heuristic_score`, `score_meaning`, and explicit evidence fields.
  - Scores are review heuristics, not calibrated probabilities and not identity confidence.
- Added dedicated association list/review endpoints:
  - `GET /api/cv/runs/{cv_run_id}/person-associations`
  - `POST /api/cv/person-associations/{association_id}/review`
- Added frontend UI:
  - ATM zone enable/name/coordinate fields in the CV run creation form.
  - Zone coordinate convention and non-identity limitation text.
  - Association cards in run detail with evidence metrics, heuristic label, and confirm/reject review controls.
  - Association API methods and association state wiring in `CvRunsPage`.

## Changed files

Backend:

- `backend/app/config.py`
- `backend/app/db.py`
- `backend/app/schemas.py`
- `backend/app/services/cv_integration.py`
- `backend/app/routers/cv.py`
- `backend/tests/test_atm_association.py` (new)
- `backend/tests/test_cv_review.py`

Frontend:

- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/pages/CvRuns.tsx`
- `frontend/src/lib/cvContract.test.ts`
- `frontend/src/lib/cvReviewApi.test.ts`
- `frontend/src/pages/CvRunsView.test.ts`

Report:

- `reports/ps04cctv-audit/P0-1-ATM-TRANSACTION-PERSON-ASSOCIATION.md` (this file)

## Verification

Backend syntax check:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/yps/Dev/web/atm/.venv/bin/python -m py_compile \
  backend/app/services/atm_association.py \
  backend/app/services/cv_integration.py \
  backend/app/routers/cv.py \
  backend/app/db.py \
  backend/app/schemas.py \
  backend/app/config.py
```

Result: passed, no output.

Focused backend tests:

```bash
mkdir -p reports/ps04cctv-audit/.verification-tmp
TMPDIR=/Users/yps/Dev/web/atm/reports/ps04cctv-audit/.verification-tmp \
PYTHONDONTWRITEBYTECODE=1 \
/Users/yps/Dev/web/atm/.venv/bin/python -m pytest \
  backend/tests/test_atm_association.py \
  backend/tests/test_cv_review.py::test_run_and_review_schema_expose_no_raw_embedding_or_identity \
  -q --tb=short
```

Result:

```text
9 passed, 1 warning in 0.93s
```

The warning is the existing FastAPI/Starlette `httpx` deprecation notice.

Full guarded backend regression:

```bash
TMPDIR=/Users/yps/Dev/web/atm/reports/ps04cctv-audit/.verification-tmp \
PYTHONDONTWRITEBYTECODE=1 \
/Users/yps/Dev/web/atm/.venv/bin/python -m pytest \
  backend/tests -q --tb=short \
  --deselect=backend/tests/test_cv_engine.py::test_synthetic_generator_writes_labelled_clips
```

Result:

```text
226 passed, 1 deselected, 1 warning in 36.87s
```

The deselected test invokes prohibited `scripts/generate_synthetic_cv_assets.py`; it is unrelated to P0-1.

Frontend checks:

```bash
npm run typecheck
npm test -- --run
npm run build
```

Results:

- `npm run typecheck`: passed.
- `npm test -- --run`: `72 passed` across `9` test files.
- `npm run build`: passed with Vite `6.4.6`; `1609` modules transformed, production build completed.

No separate lint script is configured in `frontend/package.json`; `typecheck` and `build` were used as the available static checks.

## Protected state and services

Protected-path snapshot (`data/uploads`, `data/evidence`, `data/exports`, `data/datasets`, `data/models`) before and after test execution:

```text
16 files; sha256 64c13a65182d6d1c8a1e18c4b73d056fd15f1e21b46a623ad5054e149b2e52a2
```

The digest was identical before and after verification.

Service PIDs before and after verification were unchanged:

```text
90317 uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
90347 vite --host 127.0.0.1 --port 5173 --strictPort
```

`reports/ps04cctv-audit/.verification-tmp` was removed after verification.

## Constraints check

- No detection, tracking, face recognition, embedding, or quality-scoring algorithm was modified.
- No model, dependency, dataset, upload, evidence, or export was modified.
- No live CCTV source, external database, or identity assertion was added.
- No prohibited script was executed.
- No network access or download was performed.
- No Git operation was performed.
- No service was stopped, restarted, or reconfigured.
- P0-2 was not started.

## Limitations

- Association scores are local heuristics from zone, dwell, and timing evidence; they are not calibrated probabilities.
- Run-local track IDs do not identify a person.
- Association review is a case-review outcome only and must not be interpreted as identity confirmation.
- Mocked tracking/window backend tests validate persistence, listing, review, and semantics; they are not real-inference evidence.
