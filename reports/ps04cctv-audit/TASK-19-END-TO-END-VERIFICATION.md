# TASK 19 — End-to-End Workflow Verification

## Scope / boundaries
- Isolated `pytest`/FastAPI `TestClient` workflow plus frontend API-contract/static tests.
- Existing synthetic pytest video fixtures only; prohibited generator scripts were not run.
- No service restart/stop/reconfiguration, package/model download/install, DB/production data mutation, annotation edit, export/evidence mutation, CV algorithm/threshold/model/DB redesign, or Git write/sync operation.
- Browser-level automation and real-CCTV validation were **NOT_ASSESSED**; no browser automation dependency was installed and no real CCTV/authorized labeled dataset was introduced.

## Result
**PASSED for the API-level end-to-end workflow.** No production integration bug was verified; no production code was changed.

The isolated test `backend/tests/test_task19_workflow.py` exercised:
1. Case and transaction creation.
2. Video upload, verification and normalization with source-vs-normalized provenance retained.
3. Transaction-aligned CV run with ATM interaction zone: transaction video time `3.0s`, analysis window `2.0s–4.0s`.
4. Person observation and transaction-person association persistence; association review confirmed.
5. Face observation persistence, crop identifier scoping and crop retrieval state transition in isolated storage.
6. Best-face selection linked to the confirmed person track; selection remained a heuristic quality ranking and review aid, not identity evidence.
7. TASK 15 derived enhancement preview: presets, enhancement POST, derived metadata GET and enhanced JPEG GET; original crop bytes unchanged.
8. Cross-video SFace candidate search via a local isolated embedding store; candidate marked `candidate_only` with bounded similarity.
9. Face-observation and candidate human review.
10. Manual evidence-frame capture, PDF report/JSON manifest export with two explicit CV references, and audit-event verification.

## Data consistency and safety assertions
- CV run preserved source and normalized video ids/hashes; export report hash matched JSON manifest; PDF header was present.
- Export contained `cv_selection_count=2`, `cv_observation_count=1`, `cv_candidate_count=1`.
- Candidate export required a `relevant` human review decision and marked client-supplied rank/similarity as `unverified_client_selection_context`.
- Unsupported attributes remained `not_assessed`; best-face copy and association copy explicitly deny identity claims.
- Original crop bytes were unchanged by enhancement; enhanced SHA-256 differed from original SHA-256.
- No embedding vectors or raw crop paths were exposed in observation/export payloads; existing regression tests also assert no embedding/path columns in `cv_observations`.

## Failure and boundary checks
| Check | Result |
|---|---:|
| Cross-case CV run lookup | 404 |
| Wrong crop id | 404 |
| Cross-case candidate search | 404 |
| Cross-case export with foreign CV observation | 422 |
| Stale review export expectation | 422 |
| Busy CV slot (existing regression) | 503 with `Retry-After: 5` |

## Test evidence
| Command | Result |
|---|---:|
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest backend/tests/test_task19_workflow.py -q --tb=short` | 1 passed, 1 warning |
| `cd frontend && npm test -- --run src/lib/task19WorkflowApi.test.ts` | 3 passed |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --tb=no -k 'not test_synthetic_generator_writes_labelled_clips'` | 331 passed, 1 deselected, 1 warning |
| `cd frontend && npm test -- --run && npm run typecheck && npm run build` | 77 passed, typecheck passed, build passed |

The warning is the pre-existing `StarletteDeprecationWarning` for `httpx`/`starlette.testclient`.

## Files added
- `backend/tests/test_task19_workflow.py`
- `frontend/src/lib/task19WorkflowApi.test.ts`
- `reports/ps04cctv-audit/TASK-19-END-TO-END-RESULTS.json`
- `reports/ps04cctv-audit/TASK-19-END-TO-END-VERIFICATION.md`

## Limitations
- This is synthetic, deterministic API/TestClient verification. It is not browser interaction E2E, not a real-model accuracy benchmark, and not validation on real ATM/CCTV footage.
- Browser console errors were not assessed because browser automation was unavailable; frontend API request/response/error behavior was verified with Vitest fetch stubs.
- No production best-face score, SFace similarity threshold, detector threshold, model, schema or enhancement behavior was changed.
- Protected data snapshot at report time: 19 files, SHA-256 `d0056e39f65ddaefa9bedceb20cbfbd86eb043e891fff73fd9c62701d742d110`. The three extra `data/uploads` files have local mtimes `16:02`, `16:52` and `16:53` on 2026-11-23, before this TASK 19 run; TASK 19 made no protected-data additions, edits or deletions.
- Git operations were read-only status only.
