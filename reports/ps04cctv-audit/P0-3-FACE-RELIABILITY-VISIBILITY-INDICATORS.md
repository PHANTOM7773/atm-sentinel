# P0-3 Face Reliability & Visibility Indicators

Status: **COMPLETE**

Scope: conservative, transparent face-reliability/visibility indicators for existing best-face evidence. No new models, no detector/tracker redesign, no ATM association changes, no best-face ranking redesign, no DB migration.

## Objective

Expose defensible reliability and visibility limitations for selected/linked face frames so investigators can interpret best-face evidence without treating it as identity, biometric, concealment-classification, or certainty evidence.

## Phase 1 Audit Findings

### Existing signals

- **Quality scoring**: `backend/app/cv/quality.py` computes sharpness, brightness, contrast, crop/face size, landmark visibility, frontal proxy, occlusion proxy, quality score, warnings, and raw flags including `mask/helmet/cap="unknown"`.
- **Pose/occlusion**: `backend/app/cv/landmarks.py` derives YuNet five-landmark visibility, uncalibrated geometric pose proxies, and landmark-boundary occlusion status `not_suspected/review/suspected`; explicitly not a face-covering classifier.
- **Detection models**: `backend/app/cv/models.py` has only YuNet (face), SFace (embedding), YOLOX (person class 0 only). No mask/helmet/cap/head-covering classifier exists.
- **Best-face selection**: `backend/app/services/best_face.py` ranks existing face observations by quality components and bbox linkage; it does not classify concealment and does not change association semantics.
- **Crop/evidence**: crop retrievability is already persisted and checked (`cv_integration._crop_retrieval_state`); observations and evidence remain source records.
- **Frontend**: `CvRuns.tsx` already labels heuristic flags as signals only and renders mask/helmet/cap as `not assessed`. Best-face summary was read-only.
- **Requirements**: PS04CCTV asks for visibility/reliability limitations (masked/helmeted/capped/partially visible/unsuitable). Current implementation cannot truthfully classify those concealment types.

### Indicator inventory

| Indicator | Status before P0-3 | Source | P0-3 handling |
|---|---|---|---|
| Sharpness/blur | Implemented | `quality.sharpness`, `review_flags.low_sharpness` | Consolidated into `image_quality` indicator with evidence/limitation. |
| Brightness/exposure | Implemented | `quality.brightness`, `underexposed/overexposed` | Consolidated into `image_quality`. |
| Face resolution/size | Implemented | `quality.face_size_px/crop_size_px`, `small_face` | Consolidated into `image_quality`. |
| Detector confidence | Implemented | `observation.detector_confidence` | Remains in observation/best-face score inputs; not relabeled as identity confidence. |
| Pose/frontalness | Implemented heuristic | `pose.*`, `frontal_component`, `pose_away` | Exposed as `pose` indicator with uncalibrated-proxy limitation. |
| Partial occlusion | Implemented heuristic | `occlusion_status`, `partial_occlusion_suspected`, `occlusion_review`, landmark visibility | Exposed as `face_visibility` and `occlusion` indicators. |
| Crop retrievability | Implemented | `crop.retrieval_state` | Used as measured evidence; unretrievable crop makes image quality poor. |
| Mask/helmet/cap concealment class | Not supported | no model/classifier; schema constant `not_assessed` | Explicitly `not_assessed`; never inferred as present/absent. |
| Generic obstruction type | Not supported | no classifier | Only conservative `possible_obstruction` when occlusion heuristics already indicate review/suspected. |
| Calibrated 3D pose/gaze | Not supported | geometric proxy only | Reported as heuristic/limitation, not calibrated. |
| Enhancement/restoration | Not supported | no enhancement model | Not claimed. |

## Implementation

### Backend

- Added `backend/app/services/face_reliability.py`:
  - per-observation assessment `assess_face_reliability(observation)`.
  - overall statuses: `usable`, `limited`, `poor`, `not_assessed`.
  - indicators: `face_visibility`, `occlusion`, `pose`, `image_quality`, `potential_concealment`.
  - indicator assessment types: `measured`, `heuristic`, `not_assessed`.
  - concealment is `not_assessed` by default; may become `possible_obstruction` only from existing occlusion/visibility heuristics, never mask/helmet/cap classification.
  - explicit limitation: not identity, biometric match, criminality, account ownership, or suspect identification.

- Updated `backend/app/services/best_face.py`:
  - attaches `reliability` to each ranked/rejected/other frame.
  - adds selected reliability status/summary to best-face summary.
  - no ranking weights, thresholds, tie-breaks, or selection logic changed.

- Updated `backend/app/schemas.py`:
  - added `CvFaceReliabilityIndicator`, `CvFaceReliabilityAssessment`.
  - extended `CvBestFaceRankedFrame.reliability`.
  - extended `CvBestFaceSelectionSummary.selected_reliability_status/summary`.
  - no DB migration.

### Frontend

- Updated `frontend/src/lib/types.ts` for reliability DTOs.
- Updated `frontend/src/pages/CvRuns.tsx` best-face summary card to show:
  - reliability badge/status,
  - summary text,
  - explicit limitation: reliability is not identity/biometric/suspect evidence and mask/helmet/cap are not assessed.
- No frontend detection/classification logic added.

## Assessment Semantics

- `usable`: available measured/heuristic evidence indicates the face frame is suitable for human visual review; still requires human verification.
- `limited`: frame is reviewable but has meaningful limitations (pose, partial visibility, limited quality, possible obstruction, or partial unknowns).
- `poor`: quality/visibility/pose limitations make reliable visual review unlikely from this frame.
- `not_assessed`: insufficient evidence to assess reliability.

Indicator statuses are conservative:
- Visibility: `fully_visible`, `mostly_visible`, `partially_visible`, `insufficient_visibility`, `unknown`.
- Occlusion: `not_suspected`, `review_needed`, `suspected`, `unknown`.
- Pose: `frontal_or_near_frontal`, `turned_or_profile`, `poor_pose`, `unknown`.
- Image quality: `good`, `limited`, `poor`, `unknown`.
- Potential concealment: `not_assessed`, `possible_obstruction` only.

`possible_obstruction` does **not** mean mask/helmet/cap. It only means occlusion heuristics suggest obstruction; type is unclassified.

## Tests

### Added

- `backend/tests/test_face_reliability.py`
  - high-quality unobstructed face -> usable where supported
  - low sharpness -> poor image quality
  - poor illumination -> poor image quality
  - small face -> poor image quality
  - pose limitation -> turned/poor pose reported
  - occlusion suspected -> partial visibility/review-needed/suspected + conservative possible obstruction
  - missing metrics -> unknown/not_assessed, no fabricated positive/negative
  - mask/helmet/cap unsupported -> explicitly not assessed
  - selected best-face reliability matches underlying observation
  - reliability does not alter selection ordering/scores
  - best-face endpoint includes reliability payload

### Updated

- `backend/tests/test_best_face_real_cv.py` asserts selected real-CV frame includes reliability and concealment remains not assessed.
- `frontend/src/pages/CvRunsView.test.ts` asserts reliability summary renders conservatively.

## Verification

Commands run from `/Users/yps/Dev/web/atm`.

Focused backend:

```text
24 passed, 1 warning in 0.61s
```

Backend regression set:

```text
133 passed, 1 warning in 31.77s
```

Guarded backend suite:

```text
258 passed, 1 deselected, 1 warning in 40.78s
```

Deselected:

```text
backend/tests/test_cv_engine.py::test_synthetic_generator_writes_labelled_clips
```

Frontend:

```text
src/pages/CvRunsView.test.ts + src/lib/cvReviewApi.test.ts: 39 passed
npm run typecheck: passed
npm run build: passed
```

Warnings: existing Starlette/httpx deprecation warning from `fastapi.testclient`.

## Real CV Validation

Existing local asset only: `data/datasets/synthetic/cv/subject_a_front.mp4` (sha256 unchanged). Pinned local models in `data/models` copied into temp test/CV model dirs as needed by existing fixtures; no downloads.

Observed real-CV selected frame:

```text
selected True
reliability status: usable
face_visibility: fully_visible (heuristic)
occlusion: not_suspected (heuristic)
pose: frontal_or_near_frontal (heuristic)
image_quality: good (measured)
potential_concealment: not_assessed (not_assessed)
measured: mask/helmet/cap/not_assessed, occlusion_status=not_suspected
```

This confirms reliability is computed from real existing CV observations and does not claim mask/helmet/cap detection.

## Limitations

- No mask/helmet/cap/obstruction-type classifier exists; concealment type remains not assessed.
- `possible_obstruction` is a conservative heuristic from existing occlusion signals, not object detection.
- Pose is uncalibrated geometric proxy, not calibrated 3D pose/gaze.
- Quality metrics are usability proxies, not identity/correctness probabilities.
- Real validation used existing local synthetic CV asset and pinned local models; not real CCTV adverse-condition benchmarking.
- No DB migration; reliability is computed on demand from existing observation fields.

## Protected Data / Service / Git Confirmation

Protected paths snapshot before and after: unchanged.

```text
16 files; sha256 e87d1c2a306f3414c64d93761cca80937cf37a6a7af630c36ba1fd5cae6e61c8
```

No files in `data/uploads`, `data/evidence`, `data/exports`, `data/datasets`, `data/models` were modified.

Services unchanged and not restarted:

```text
90317 uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
90347 vite --host 127.0.0.1 --host 127.0.0.1 --port 5173 --strictPort
```

No Git operations performed. Worktree was not a git repo (`git status` returned fatal not a git repository).

## P0-4

Not started.
