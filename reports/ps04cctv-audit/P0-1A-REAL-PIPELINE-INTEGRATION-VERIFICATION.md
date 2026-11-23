# P0-1A Real CV-to-ATM Association Integration Verification

Final status: **VERIFIED**

The primary video-to-detection-to-tracking-to-zone-to-transaction-association path succeeded using real YOLOX inference through the actual `/api/cv/runs` service entry point, with no mocked detections or manually fabricated tracks. Negative/boundary controls were run separately and are labelled where mocked.

## 1. Execution path from detector to association

Inspected implementation path:

1. `POST /api/cv/runs` is handled by `backend/app/routers/cv.py:247-259` and calls `cv_integration.create_and_execute_run()`.
2. `backend/app/services/cv_integration.py:1094-1106` validates the request, resolves the uploaded video, creates the run record with zone JSON, then executes the run.
3. Because `atm_zone` requires `transaction_aligned`, execution goes through `_run_window_analysis()` at `backend/app/services/cv_integration.py:729-892`; it constructs `CVPipeline()` and calls `pipeline.analyze_frame(...)` for frames in the transaction window.
4. `backend/app/cv/pipeline.py:295-306` calls `YOLOXPersonDetector.detect(frame)` and then `SimpleTracker.update(...)`; real detections are serialized with `track_id`, `bbox`, and `confidence` at `backend/app/cv/pipeline.py:345-354`.
5. `backend/app/services/atm_association.py:114-165` consumes the serialized tracked person observations from `analysis["frames"][...]["persons"]`, computes zone overlap, and persists `cv_person_observations`.
6. `backend/app/services/atm_association.py:249-453` groups the real tracked observations by run-local `track_id`, computes dwell, window overlap, continuity, quality proxy, and the heuristic score, then creates association records.
7. `backend/app/services/atm_association.py:456-529` inserts person observations and associations; schema/tables are in `backend/app/db.py:229-281`.
8. `backend/app/routers/cv.py:339-356` serves `GET /api/cv/runs/{cv_run_id}/person-associations`; `backend/app/routers/cv.py:359-374` serves `POST /api/cv/person-associations/{association_id}/review`.

Association service data source:

- The production association service consumes serialized real `CVPipeline` output, which is derived from actual `YOLOXPersonDetector` detections and actual `SimpleTracker` track IDs.
- `backend/app/services/atm_association.py` does not itself import detector or tracker classes; it operates on `VideoAnalysis.to_dict()` person records.
- The P0-1 unit tests in `backend/tests/test_atm_association.py:136-179` deliberately monkeypatch `CVPipeline` and `cv2.VideoCapture` with fake pipeline/capture classes and inject a hard-coded `track_id=7`. Those tests were treated as mocked semantic controls, not as end-to-end evidence.

## 2. Asset and model verification

Verified with `shasum -a 256`:

- YOLOX model: `data/models/object_detection_yolox_2022nov.onnx`
- SHA-256: `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063`
- Pinned value in `backend/app/cv/models.py`: matched.

Selected synthetic video:

- Path: `data/datasets/synthetic/cv/subject_a_front.mp4`
- SHA-256: `cdda2c7344346be6df6147b568327a1427d442e899de69722a6c17e0cd0741a2`
- Reason: documented in P0-6 as producing positive real YOLOX person detections with test-local `score_threshold=0.1`.
- No asset was generated, downloaded, replaced, or modified for the primary run.

Detector threshold:

- `ATM_SENTINEL_CV_PERSON_SCORE=0.1` was used, matching the P0-6 synthetic smoke-test methodology.
- Production default `0.45` remains unvalidated for these procedural assets; no real-world accuracy claim is made.

## 3. Primary real end-to-end result

Isolated environment:

- Temporary data dir: `reports/ps04cctv-audit/.verification-tmp/data`
- Temporary DB: `reports/ps04cctv-audit/.verification-tmp/data/sentinel.db`
- Temporary uploads and model copies were created only under `.verification-tmp`.

Run identifiers:

- Case: `1d1333aa82e443ad906710153c28d5f3`
- Transaction: `6a8b848947634a6d915b4390cc829f8d`
- Uploaded video: `43eb8b51b3744355809e35a38ce0f020`
- CV run: `de61ef14bcb94493bb702872dbd4e40d`
- Run status: `completed_with_warnings`
- Warning: `near_duplicate_faces_suppressed`, unrelated to person association.

Configuration:

- Transaction timestamp: `2026-01-15T09:00:00.550000+00:00`
- CCTV timestamp: `2026-01-15T09:00:00.550000+00:00`
- Video start timestamp: `2026-01-15T09:00:00+00:00`
- Transaction video time: `0.55s`
- Window: before `0.55s`, after `0.65s`, analyzed window `0.0s–1.2s`
- Normalized zone: `{"name":"atm_keypad_real","x":0.28,"y":0.15,"width":0.46,"height":0.75}`
- Pixel zone: `x=179.2`, `y=72.0`, `width=294.4`, `height=360.0`, `right=473.6`, `bottom=432.0`

Real detector and tracker results:

- Real YOLOX detector calls: `13`
- Actual detector output: `7` person detections
- Actual tracked person observations persisted: `7`
- Track IDs: `1` only
- Track frame range: `0–11`
- Track time range: `0.0s–1.1s`
- Frames observed: `0, 1, 2, 3, 4, 5, 11`
- Detector confidences: `0.1259, 0.1138, 0.1703, 0.2413, 0.2118, 0.1672, 0.1302`

Zone observation results:

- All `7` tracked observations were in zone.
- Zone frame count: `7`
- Average bbox-overlap ratio: `0.9442`
- Maximum bbox-overlap ratio: `0.954`
- Average IoU: `0.8408`
- Per-frame overlap ratios: `0.954, 0.9414, 0.9477, 0.9403, 0.9447, 0.937, 0.944`
- Maximum track gap: `0.6s`
- Discontinuity gap count: `0`

Association result:

- Generated associations: `1`
- Person track: `1`
- Review state: `proposed`
- Evidence strength: `strong`
- Heuristic score: `0.9207` — a heuristic evidence score, not a calibrated probability.
- Dwell: `1.2s`
- Transaction-window overlap: `1.2s`
- First/last in-zone timestamps: `0.0s` / `1.1s`
- Score components: zone overlap `1.0`, dwell `1.0`, transaction timing `1.0`, track continuity `1.0`, observation quality `0.2072`
- Reason: `sufficient_observed_evidence`

Instrumentation note:

- `YOLOXPersonDetector.detect` was wrapped in-process only to count outputs. The original method was called unchanged; no detections or tracks were substituted.

## 4. Persistence and API retrieval

Persistence:

- The temporary DB contained `7` rows in `cv_person_observations` for the primary run and `1` row in `transaction_person_associations`.
- The association persisted with evidence JSON, review state, heuristic score, dwell, zone frame count, and timing fields.

API retrieval:

- `GET /api/cv/runs/de61ef14bcb94493bb702872dbd4e40d/person-associations?case_id=1d1333aa82e443ad906710153c28d5f3&limit=25&offset=0`
- Result: HTTP `200`, `total=1`, one `proposed` association with evidence fields preserved.
- Returned identity-safety metadata included `verification_status="candidate_only"`, `requires_human_verification=true`, the association limitation disclaimer, and `score_meaning` explicitly stating the score is not calibrated probability or identity likelihood.
- No raw embedding vector fields, face identity fields, person identity fields, account-holder fields, criminal/suspect fields, or `identity_confirmed` fields were found. `embedding_schema_version` is provenance metadata only and is not a raw embedding.

API review:

- `POST /api/cv/person-associations/4d8aba0f369a4003a3d3bbfdc87cbe8b/review?case_id=1d1333aa82e443ad906710153c28d5f3`
- Body decision: `confirmed`, with reviewer note marked as case-review only.
- Result: HTTP `200`; `review_state` changed from `proposed` to `confirmed`.
- Re-fetch confirmed the review state and that the evidence object was unchanged.

## 5. Negative and boundary verification

Real-inference controls:

1. Outside-zone control (real inference):
   - Run: `c6d86a00094e45f0a7e4e690bda45575`
   - Zone: `{"x":0.0,"y":0.0,"width":0.12,"height":0.12}`
   - Detector output: `7`; tracked observations: `7`; in-zone observations: `0`.
   - Result: one `insufficient_evidence` association, strength `insufficient`, score `0.1207`, dwell `0.0`, zone frames `0`, window overlap `0.0`.
   - Conclusion: a detected person with no positive zone overlap did not receive positive zone evidence.

2. Outside-transaction-window control (real inference):
   - Run: `829ea41ad038409cb8233f558f518706`
   - Transaction video time: `3.0s`; window `2.5s–3.5s`; primary zone reused.
   - Detector output: `1`; tracked observation: frame `35` at `3.5s`, in zone.
   - Result: one `insufficient_evidence` association, strength `insufficient`, score `0.4383`, zone frames `1`, transaction-window overlap `0.0`.
   - Conclusion: the boundary observation did not produce a positive transaction association.

3. Invalid zone control (API validation):
   - Zone: `{"x":0.95,"y":0.15,"width":0.2,"height":0.2}`
   - `POST /api/cv/runs` returned HTTP `422`; `runs_created=0`.

Mocked controls (explicitly labelled; no real inference):

1. Multiple tracks: direct `build_associations()` control produced two distinguishable records, tracks `11` and `12`, both `proposed`, strength `moderate`, score `0.6`.
2. Single-frame evidence: direct builder control produced `insufficient_evidence`, strength `insufficient`, zone frames `1`.
3. Discontinuous evidence: direct builder control with two observations separated by `2.0s` produced a `proposed` record, strength `moderate`, score `0.5317`, zone frames `2`. This is an observed limitation of the current builder: discontinuity reduces the score but does not by itself force `insufficient_evidence`. No fix was attempted.

No suitable existing synthetic asset with multiple real YOLOX person detections was available, so multiple-candidate and discontinuous controls were mocked and are not primary evidence.

## 6. API and frontend integration inspection

Backend endpoints inspected and exercised in the isolated environment:

- `GET /api/cv/runs/{cv_run_id}/person-associations`: retrieved records, evidence fields, review states, limitations, and candidate-only status.
- `POST /api/cv/person-associations/{association_id}/review`: accepted `confirmed`, preserved evidence, and updated review state.

Frontend source inspection:

- `frontend/src/lib/api.ts:131-143`: `listPersonAssociations()` calls the association GET endpoint with `case_id`, optional `transaction_id`, `limit`, and `offset`.
- `frontend/src/lib/api.ts:144-152`: `reviewPersonAssociation()` calls the association review POST endpoint with `case_id` as a query parameter.
- `frontend/src/pages/CvRuns.tsx:474-562`: `CvAssociationCard` displays association ID, track ID, zone ID, badges, limitation text, score meaning, heuristic score, dwell, zone frames, window overlap, and timestamps; confirm/reject controls are at lines `534-553`.
- `frontend/src/pages/CvRuns.tsx:1210-1232`: run detail renders “Transaction-person associations” and maps API items into `CvAssociationCard`.
- `frontend/src/pages/CvRuns.tsx:1373-1397`: page load fetches associations with `cvApi.listPersonAssociations`.
- `frontend/src/pages/CvRuns.tsx:1461-1487`: review handler posts `confirmed`/`rejected` and updates local state with the saved record.

No browser interaction was performed against the running production frontend; no service was restarted or reconfigured. Frontend verification was source inspection plus focused tests.

## 7. Exact commands executed

Model/asset hashes and pre-check:

```bash
shasum -a 256 data/models/object_detection_yolox_2022nov.onnx data/datasets/synthetic/cv/subject_a_front.mp4 data/datasets/synthetic/cv/challenges.mp4
mkdir -p reports/ps04cctv-audit/.verification-tmp
```

Results included the pinned YOLOX hash `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` and `subject_a_front.mp4` hash `cdda2c7344346be6df6147b568327a1427d442e899de69722a6c17e0cd0741a2`.

Temporary model copy:

```bash
mkdir -p reports/ps04cctv-audit/.verification-tmp/data/models && /Users/yps/Dev/web/atm/.venv/bin/python - <<'PY'
from pathlib import Path
import shutil
root = Path('/Users/yps/Dev/web/atm')
src = root / 'data/models'
dst = root / 'reports/ps04cctv-audit/.verification-tmp/data/models'
for name in ['object_detection_yolox_2022nov.onnx', 'face_detection_yunet_2026may.onnx', 'face_recognition_sface_2021dec.onnx']:
    shutil.copy2(src / name, dst / name)
print('copied', len(list(dst.glob('*.onnx'))), 'models into temp data dir')
PY
```

Result: `copied 3 models into temp data dir`.

Real detector/tracker probe used to choose the zone:

```bash
ATM_SENTINEL_DATA_DIR=/Users/yps/Dev/web/atm/reports/ps04cctv-audit/.verification-tmp/data ATM_SENTINEL_CV_PERSON_SCORE=0.1 PYTHONDONTWRITEBYTECODE=1 /Users/yps/Dev/web/atm/.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, '/Users/yps/Dev/web/atm/backend')
import cv2
from app.cv.detection import YOLOXPersonDetector
from app.cv.tracking import SimpleTracker
video = '/Users/yps/Dev/web/atm/data/datasets/synthetic/cv/subject_a_front.mp4'
detector = YOLOXPersonDetector()
tracker = SimpleTracker()
cap = cv2.VideoCapture(video)
frame_no = 0
total_detections = 0
rows = []
while frame_no < 20:
    ok, image = cap.read()
    if not ok:
        break
    detections = detector.detect(image)
    total_detections += len(detections)
    stamps = [float(frame_no) / 10.0 for _ in detections]
    tracks = tracker.update(detections, frame_no, stamps)
    for det in tracks:
        rows.append((frame_no, det.track_id, tuple(round(v, 2) for v in det.bbox), round(det.confidence, 4)))
    frame_no += 1
cap.release()
print('frames', frame_no)
print('detections', total_detections)
print('tracked observations', len(rows))
for row in rows:
    print(row)
PY
```

Result: `frames 20`, `detections 7`, `tracked observations 7`, all on track `1`.

Primary and control harness:

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/yps/Dev/web/atm/.venv/bin/python reports/ps04cctv-audit/.verification-tmp/real_pipeline_verification.py
```

It was rerun once with a clean temp data directory:

```bash
/Users/yps/Dev/web/atm/.venv/bin/python - <<'PY'
from pathlib import Path
import shutil
path = Path('/Users/yps/Dev/web/atm/reports/ps04cctv-audit/.verification-tmp/data')
if path.exists():
    shutil.rmtree(path)
PY
PYTHONDONTWRITEBYTECODE=1 /Users/yps/Dev/web/atm/.venv/bin/python reports/ps04cctv-audit/.verification-tmp/real_pipeline_verification.py
```

Final harness result:

```text
primary_run_id de61ef14bcb94493bb702872dbd4e40d
primary_detections 7
primary_person_observations 7
primary_associations 1
primary_review_state proposed
primary_evidence_strength strong
primary_heuristic_score 0.9207
review_state_after confirmed
outside_zone_associations 1
outside_window_associations 1
invalid_zone_status 422
```

Focused backend tests:

```bash
mkdir -p reports/ps04cctv-audit/.verification-tmp/pytest-tmp
TMPDIR=/Users/yps/Dev/web/atm/reports/ps04cctv-audit/.verification-tmp/pytest-tmp PYTHONDONTWRITEBYTECODE=1 /Users/yps/Dev/web/atm/.venv/bin/python -m pytest backend/tests/test_cv_real_inference_verification.py backend/tests/test_atm_association.py -q --tb=short
```

Result: `11 passed, 1 warning in 8.24s`.

Focused frontend checks:

```bash
npm run typecheck && npm test -- --run src/lib/cvContract.test.ts src/lib/cvReviewApi.test.ts src/pages/CvRunsView.test.ts
```

Result: typecheck passed; `3` test files, `43 tests passed`.

Protected-state and service checks were run before and after verification:

```bash
/Users/yps/Dev/web/atm/.venv/bin/python - <<'PY'
from pathlib import Path
import hashlib
root = Path('/Users/yps/Dev/web/atm')
paths = ['data/uploads', 'data/evidence', 'data/exports', 'data/datasets', 'data/models']
items = []
for rel in paths:
    base = root / rel
    if base.exists():
        items.extend(sorted(p for p in base.rglob('*') if p.is_file()))
digest = hashlib.sha256()
for path in items:
    digest.update(str(path.relative_to(root)).encode())
    digest.update(hashlib.sha256(path.read_bytes()).digest())
print(f'{len(items)} files; sha256 {digest.hexdigest()}')
PY
ps -p 90317,90347 -o pid=,command=
```

Result before and after: `16 files; sha256 64c13a65182d6d1c8a1e18c4b73d056fd15f1e21b46a623ad5054e149b2e52a2`; PIDs unchanged.

## 8. Files created or modified

Created under `reports/ps04cctv-audit/.verification-tmp/`:

- `real_pipeline_verification.py`
- `real_pipeline_evidence.json`
- `data/models/object_detection_yolox_2022nov.onnx` (temporary copy)
- `data/models/face_detection_yunet_2026may.onnx` (temporary copy)
- `data/models/face_recognition_sface_2021dec.onnx` (temporary copy)
- `data/sentinel.db` (temporary DB)
- `data/uploads/051b510b87aa4bf891ee4f718409094f.mp4`
- `data/uploads/43eb8b51b3744355809e35a38ce0f020.mp4`
- `data/uploads/86a715d70b594cf6b1493d9e864458d7.mp4`
- `pytest-tmp/...` temporary pytest data, including fixture-written `synthetic_test.mp4` files used only by the mocked association unit tests.

Created report:

- `reports/ps04cctv-audit/P0-1A-REAL-PIPELINE-INTEGRATION-VERIFICATION.md`

No production source, frontend source, schema, migration, CV algorithm, API contract, dependency, dataset, upload, evidence, export, or model file was modified.

## 9. Known limitations and unresolved blockers

- Positive person detection required the test-local threshold `0.1`; production default `0.45` was not validated on these procedural assets.
- Synthetic assets are fictional/procedural and validate pipeline mechanics only, not real-world ATM CCTV accuracy.
- Only one real track was available for the positive primary association; multiple-candidate verification used a mocked builder control.
- The discontinuous-track mocked control produced a `proposed` record with reduced score; no fix was attempted because this task is read-only.
- No browser interaction with the running frontend was performed because services must not be restarted or reconfigured; frontend verification was source inspection plus focused tests.
- Focused `test_atm_association.py` uses its own pytest fixture that writes tiny temporary MP4 files under `.verification-tmp/pytest-tmp`; these are not repository assets and were not used in the primary real-inference run.
- Prohibited scripts were not executed, including `scripts/generate_synthetic_cv_assets.py`, `scripts/download_cv_models.py`, and `scripts/benchmark_cv.py`.

## 10. Production state and running services

- All application imports and API calls in the primary harness used `ATM_SENTINEL_DATA_DIR` pointing to `reports/ps04cctv-audit/.verification-tmp/data`; the production DB and storage paths were not used.
- Protected-path snapshot before and after verification was identical.
- Service PIDs before and after verification were unchanged: backend `90317`, frontend `90347`.
- No network access, download, Git operation, service stop/restart, or destructive UI operation was performed.
- P0-2 was not started.
