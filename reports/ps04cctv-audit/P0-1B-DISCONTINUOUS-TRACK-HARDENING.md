# P0-1B Discontinuous Track Association Hardening

Status: **COMPLETE**

Scope: backend ATM person-association eligibility/scoring logic and directly related backend tests only.

## Objective

Harden ATM transaction/person association evidence selection so weak, insufficient, discontinuous, or transaction-window-irrelevant tracks cannot be proposed as meaningful review candidates.

P0-1A showed that a mocked two-observation track with a `2.0s` discontinuity still produced `review_state=proposed`, `evidence_strength=moderate`, and `heuristic_score=0.5317`. This was misleading because the association list is ranked by `heuristic_score`, allowing an insufficient discontinuous candidate to outrank valid continuous evidence.

## Root Cause

The previous implementation computed a numeric heuristic score first and only used continuity as a small weighted score penalty. `discontinuity_count` was calculated from actual observation gaps greater than `MAX_TRACK_GAP_SECONDS`, but it did not block eligibility. The old `sufficient` check only covered zone observation count, dwell, transaction-window overlap, temporal score, and confidence proxy.

As a result:

- A `2.0s` gap reduced continuity score but still produced a positive rankable heuristic score.
- Insufficient candidates retained positive scores.
- Evidence did not clearly explain why a candidate was rejected or downgraded.
- `get_associations` ordering by descending `heuristic_score` could place insufficient discontinuous evidence above valid continuous evidence.

## Design Decision

No new arbitrary threshold was introduced. The existing `MAX_TRACK_GAP_SECONDS = 1.0` constant was already used for discontinuity counting and interval merging, so it is now also used as the hard continuity eligibility boundary.

Continuity rule:

- Gap `<= 1.0s`: allowed.
- Gap `> 1.0s`: rejected as insufficient evidence.
- Multiple gaps `> 1.0s`: rejected with an explicit multiple-discontinuity reason.

This is conservative and preserves the existing boundary behavior where a gap exactly equal to `1.0s` remains valid.

## Implementation

Changed files:

- `backend/app/services/atm_association.py`
- `backend/tests/test_atm_association.py`

Backend changes:

- Added `_eligibility_failures()` at `backend/app/services/atm_association.py:195` to centralize eligibility checks and return granular failure reasons:
  - `insufficient_zone_observation_count`
  - `insufficient_dwell_time`
  - `outside_transaction_window`
  - `no_transaction_window_timing_evidence`
  - `no_observation_quality_evidence`
  - `single_excessive_track_gap`
  - `multiple_excessive_track_gaps`
- Kept the original weighted calculation as `computed_score`, then set the stored/rankable `heuristic_score` to `0.0` whenever eligibility fails.
- Added structured `evidence.eligibility` with:
  - `eligible`
  - `reasons`
  - `zone_observation_count`
  - `max_allowed_gap_seconds`
  - `max_observed_gap_seconds`
  - `discontinuity_gap_count`
  - `transaction_window_overlap_seconds`
- Added methodology text at `backend/app/services/atm_association.py:323` documenting that gaps greater than `max_track_gap_seconds` are insufficient evidence.
- Added the same structured eligibility evidence to the no-track path at `backend/app/services/atm_association.py:353`.
- Preserved all existing observations, overlap samples, track summaries, component scores, and transaction-window fields in evidence; rejected candidates are explained rather than silently discarded.
- Preserved existing `review_state`, `evidence_strength`, `human_review_required`, and non-identity semantics.

No schema, model, migration, database, router, dependency, detector, tracker, face-selection, embedding, or frontend files were changed.

Schema/migration assessment: **not required**. Eligibility details are stored in the existing free-form `evidence` JSON together with the existing `heuristic_score`, `review_state`, and `evidence_strength` fields.

## Tests Added

Added focused mocked track tests in `backend/tests/test_atm_association.py`:

- `test_continuous_track_remains_proposed_with_explanatory_eligibility` — valid continuous evidence remains proposed with explanatory eligibility evidence.
- `test_single_zone_observation_is_insufficient_with_zero_rankable_score` — single observation is insufficient and score is `0`.
- `test_excessive_observation_gap_is_insufficient` — the P0-1A `2.0s` gap case becomes insufficient with `single_excessive_track_gap`.
- `test_multiple_discontinuities_are_insufficient` — three excessive gaps are insufficient with `multiple_excessive_track_gaps`.
- `test_observations_outside_transaction_window_are_insufficient` — no window overlap is rejected and explained.
- `test_continuity_boundary_uses_existing_gap_limit` — gap exactly `1.0s` remains proposed; gap `1.01s` becomes insufficient.
- `test_discontinuous_candidate_does_not_outrank_continuous_candidate` — discontinuous candidate gets `0` score and a valid lower-scoring continuous candidate ranks first.

Existing tests still cover real API creation, persistence, case-scoped association listing, and manual review behavior.

## Verification

Commands executed from `/Users/yps/Dev/web/atm` with test isolation under `reports/ps04cctv-audit/.verification-tmp/p01b-pytest` and `PYTHONDONTWRITEBYTECODE=1`.

Baseline before changes:

```bash
.venv/bin/python -m pytest backend/tests/test_atm_association.py -q --tb=short
```

Result:

```text
8 passed, 1 warning in 0.86s
```

Focused after changes:

```bash
.venv/bin/python -m pytest backend/tests/test_atm_association.py -q --tb=short
```

Result:

```text
15 passed, 1 warning in 0.83s
```

Relevant CV/review regression set:

```bash
.venv/bin/python -m pytest \
  backend/tests/test_atm_association.py \
  backend/tests/test_cv_review.py \
  backend/tests/test_cv_integration.py \
  backend/tests/test_cv_observation_identity.py \
  backend/tests/test_cv_real_inference_verification.py \
  -q --tb=short
```

Result:

```text
54 passed, 1 warning in 11.96s
```

Guarded backend suite:

```bash
.venv/bin/python -m pytest backend/tests -q --tb=short \
  --deselect backend/tests/test_cv_engine.py::test_synthetic_generator_writes_labelled_clips
```

Result:

```text
233 passed, 1 deselected, 1 warning in 37.01s
```

Only warning is the existing Starlette/httpx deprecation warning from `fastapi.testclient`.

The prohibited synthetic generator test was deselected. No prohibited scripts were run and no model downloads were performed.

## Protection Checks

Protected data snapshot before changes:

```text
16 files; sha256 64c13a65182d6d1c8a1e18c4b73d056fd15f1e21b46a623ad5054e149b2e52a2
```

Protected data snapshot after verification:

```text
16 files; sha256 64c13a65182d6d1c8a1e18c4b73d056fd15f1e21b46a623ad5054e149b2e52a2
```

Paths covered:

- `data/uploads`
- `data/evidence`
- `data/exports`
- `data/datasets`
- `data/models`

PIDs unchanged:

```text
90317 uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
90347 vite --host 127.0.0.1 --host 127.0.0.1 --port 5173 --strictPort
```

No service was restarted or stopped. No Git operations were performed. No frontend tests, typecheck, or build were run because this task explicitly excluded frontend/UI work and the README defines typecheck/build under the frontend scope.

## Requirement Confirmation

- Sufficient, discontinuous, and transaction-window-irrelevant observations are handled in one explicit eligibility path.
- Excessive track gaps are no longer merely score penalties; they block proposal.
- Observation count, transaction-window overlap, dwell, confidence proxy, and continuity all participate in eligibility.
- Ineligible candidates receive `heuristic_score=0.0`, so they cannot outrank valid continuous candidates under existing descending-score ordering.
- Evidence explains rejection/downgrade reasons and retains useful observation details.
- Existing valid continuous association and manual-review behavior remains covered and passing.
- Human review remains mandatory; scores remain heuristic; no identity/account-holder/criminal claims are made.
- No schema or DB migration was needed.
- No P0-2 work was performed.

## Limitations

- Continuity tests use mocked person tracks only; they are deterministic unit tests and are not real CV validation.
- No live HTTP/CV run was performed for P0-1B. Real-pipeline evidence remains in the P0-1A report.
- The selected threshold is the existing project constant `MAX_TRACK_GAP_SECONDS = 1.0`; this report does not claim a new empirically calibrated threshold.
