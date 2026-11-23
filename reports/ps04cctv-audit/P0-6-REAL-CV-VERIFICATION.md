# P0-6 Real CV Verification Report

Status: COMPLETE

## Objective

Verify that the existing ATM Sentinel CV pipeline performs real offline inference with the locally installed pinned models, and separate that evidence from mocked or stubbed tests.

## Verified environment and scope

- Verification performed only inside `/Users/yps/Dev/web/atm`.
- No external network access, downloads, Git operations, service restarts, or configuration changes.
- Backend service PID remained `90317`; frontend service PID remained `90347`.
- Production uploads, evidence, exports, models, datasets, frontend, source, and schemas were not modified.
- Temporary test data was confined to `reports/ps04cctv-audit/.verification-tmp` and removed after verification.

## Pinned local model verification

Exact local hashes were verified before inference:

```text
ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0  data/models/face_detection_yunet_2026may.onnx
0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79  data/models/face_recognition_sface_2021dec.onnx
c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063  data/models/object_detection_yolox_2022nov.onnx
```

Pinned specs in `backend/app/cv/models.py`:

- YuNet: revision `2b8e922362946a0db67e861bae0f77826980effd`.
- SFace: revision `cd6b9d3b77d21b8f18a7475f7dae6df0a64de06b`.
- YOLOX: revision `78c368f74ce73ee28fc7a1be418a598c71b58b52`.

`model_status()` returned `all_usable=True` and `verification=verified` for all three models. Inference paths load these local ONNX files via `require_model(...)`; no download path was used.

## Real inference operations verified

- Face detection: `CVPipeline.analyze_video` on `data/datasets/synthetic/cv/subject_a_front.mp4` produced real YuNet detections; probe observed `face_detections=12` for 12 frames.
- Face quality: existing real quality assessment produced numeric `quality_score` values in `0..100` with components and the "not an identity" disclaimer.
- Embedding generation: real SFace embeddings were generated with `embedding_state=staged_v4_candidate` and `embedding_dim=128`.
- Person detection: real YOLOX inference with test-local `score_threshold=0.1` produced `7` detections on `subject_a_front.mp4` and `15` on `challenges.mp4` over 20 frames. Production default threshold `0.45` produced `0` detections on `multi_subject.mp4`; no positive claim is made for that default/threshold combination.
- Candidate similarity/search: actual generated vectors were published through `EmbeddingStore`; a side-view query returned 5 gallery candidates from the front-view source with top cosine similarity `0.947086`, excluding the query sample and query source.

All synthetic assets used are documented as procedurally generated fictional clips with no real people or real footage. Results validate pipeline mechanics only, not real-world ATM CCTV accuracy.

## Automated evidence added

Created `backend/tests/test_cv_real_inference_verification.py` with three offline tests:

- `test_real_yolox_person_detection_on_synthetic_asset`.
- `test_real_yunet_sface_and_quality_on_synthetic_asset`.
- `test_real_embedding_candidate_similarity_on_synthetic_assets`.

The tests use real pinned ONNX models, do not mock/stub inference, do not use prohibited scripts, do not download anything, skip explicitly if required models/assets are missing, and fail rather than fall back if model hashes are invalid.

## Commands and results

Pinned model hash check:

```bash
shasum -a 256 \
  data/models/face_detection_yunet_2026may.onnx \
  data/models/face_recognition_sface_2021dec.onnx \
  data/models/object_detection_yolox_2022nov.onnx
```

Result: all three hashes matched pinned values listed above.

Focused real-inference tests:

```bash
TMPDIR=/Users/yps/Dev/web/atm/reports/ps04cctv-audit/.verification-tmp \
PYTHONDONTWRITEBYTECODE=1 \
/Users/yps/Dev/web/atm/.venv/bin/python -m pytest \
  backend/tests/test_cv_real_inference_verification.py -q --tb=short
```

Result:

```text
3 passed in 7.20s
```

Full backend suite, closest safe form:

```bash
TMPDIR=/Users/yps/Dev/web/atm/reports/ps04cctv-audit/.verification-tmp \
PYTHONDONTWRITEBYTECODE=1 \
/Users/yps/Dev/web/atm/.venv/bin/python -m pytest backend/tests -q \
  --deselect=backend/tests/test_cv_engine.py::test_synthetic_generator_writes_labelled_clips
```

Result:

```text
218 passed, 1 deselected, 1 warning in 36.36s
```

The exact unmodified command `.venv/bin/python -m pytest backend/tests -q` was not run because `backend/tests/test_cv_engine.py::test_synthetic_generator_writes_labelled_clips` invokes prohibited `scripts/generate_synthetic_cv_assets.py`. The deselected node is unrelated to real inference verification.

Protected-path snapshot before and after test execution:

```text
207 files; sha256 f2de7fe42e88094ba034dae223c3edb42b616120e45aa48153ae3f5c45a44788
```

The digest was identical before and after both test runs. Service PIDs before and after were unchanged: backend `90317`, frontend `90347`.

## Final constraints check

- No production source, config, schema, model, upload, evidence, export, or existing test asset modifications.
- No mocked inference claimed as real.
- No prohibited scripts executed.
- No network access or downloads.
- No Git operations.
- No service stop/restart/reconfigure.
- All temporary files were created inside the project root.

## Files created or modified

- Created `backend/tests/test_cv_real_inference_verification.py`.
- Created `reports/ps04cctv-audit/P0-6-REAL-CV-VERIFICATION.md`.

## Limitations

- Synthetic assets do not establish real-world accuracy.
- Person detection positive assertion uses test-local threshold `0.1`; production default threshold behavior is not claimed as validated on the tested assets.
- Model provenance relies on pinned local revisions and verified local hashes because no network verification was permitted.
