# ATM Sentinel CV Model Selection and Licensing

Date: 2026-11-22  
Scope: Phase 1 local computer-vision pipeline for ATM Sentinel.  
Status: selected stack; Phase 1 remediation applied; later local synthetic acceptance executed; real-world and R4C validation not assessed.

## Safety and interpretation rules

- This pipeline never confirms identity. It only produces candidate matches for human review.
- Track IDs are temporary, analysis-local labels. They restart for each run and may be reused across videos; they are not identities.
- Similarity scores are ranking signals only. No threshold in this phase is treated as a positive identification.
- Attribute flags are limited to explainable heuristics. Mask, cap and helmet states are `not_assessed` unless a separately approved, validated classifier is added later.
- All processing is local. No uploads, external APIs or telemetry are used.
- Model weights are stored under `data/models/` and excluded from Git by the existing `data/` rule in `.gitignore`.

## Runtime baseline

- Python: 3.12.16 in `/Users/yps/Dev/web/atm/.venv`.
- OpenCV: `opencv-python-headless==5.1.0.95`, already installed.
- NumPy: `2.5.5`, already installed.
- New Python dependencies for Phase 1: none.
- Hardware target: Apple M1 with 8 GB unified memory; CPU fallback must always work.
- ONNX/CoreML/MPS note: OpenCV DNN runs ONNX models on CPU by default. OpenCV DNN has no direct Apple MPS target. A configurable backend/target setting is implemented so CUDA-capable hosts can opt in, while CPU remains the default. CoreML execution would require a different runtime and additional dependency, so it is not used in Phase 1.
- Runtime reporting is per model: YuNet and SFace use OpenCV facade backend/target arguments where supported; YOLOX uses `setPreferableBackend`/`setPreferableTarget`. `/api/cv/status` reports the configured/effective profile for each model, and each analysis result reports the profile actually used.

## Selected stack

| Function | Selection | Weight source | License | Notes |
| --- | --- | --- | --- | --- |
| Face detection | YuNet `face_detection_yunet_2026may.onnx` | Pinned Hugging Face mirror of OpenCV Zoo export | MIT weights; OpenCV Zoo Apache-2.0 repo | Dynamic input, OpenCV 5.x compatible, 5 landmarks. |
| Face embedding | SFace `face_recognition_sface_2021dec.onnx` | OpenCV Zoo Hugging Face | Apache-2.0 | 128-d normalized descriptors; used only for candidate ranking. |
| Person detection | YOLOX-s `object_detection_yolox_2022nov.onnx` | OpenCV Zoo Hugging Face | Apache-2.0 | COCO `person` class only; 640x640 input. |
| Tracking | In-house IoU/centroid tracker | Local implementation | Project code | Clip-local IDs with miss tolerance and fragmentation handling. |
| Landmarks / pose | YuNet 5 landmarks + geometric proxies | Derived locally | No extra weights | Yaw/pitch/roll proxies are explainable angles, not calibrated 3D pose. |
| Quality / condition flags | In-house heuristics | Local implementation | Project code | Sharpness, size, illumination, contrast, landmark visibility and occlusion proxies. |
| Embedding storage | Generation-based JSON manifest + `.npy` vectors | Generated locally | Project data | Case-scoped only; records include model hash, runtime, run ID and provenance. Checksums and generation manifest are written last. |

OpenCV 5.1 returns YuNet rows as `[x, y, w, h, 5 landmark pairs, score]`. The detector also supports the older layout with score at index 4.

### Download URLs

- YuNet: `https://huggingface.co/pollen-robotics/face_detection_yunet_2026may/resolve/2b8e922362946a0db67e861bae0f77826980effd/face_detection_yunet_2026may.onnx` (unmodified MIT redistribution of the OpenCV Zoo dynamic export; GitHub raw serves a Git LFS pointer for this file)
- SFace: `https://huggingface.co/opencv/face_recognition_sface/resolve/3d7082438a6e4551e840c9b2bb60b71e8da4b524/face_recognition_sface_2021dec.onnx`
- YOLOX: `https://huggingface.co/opencv/object_detection_yolox/resolve/78c368f74ce73ee28fc7a1be418a598c71b58b52/object_detection_yolox_2022nov.onnx`
- License notices and full license texts: `docs/licenses/`
- License reference: `https://raw.githubusercontent.com/opencv/opencv_zoo/main/LICENSE`

Verified SHA256 values pinned in `backend/app/cv/models.py`:

- YuNet `face_detection_yunet_2026may.onnx`: `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0`
- SFace `face_recognition_sface_2021dec.onnx`: `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`
- YOLOX `object_detection_yolox_2022nov.onnx`: `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063`

The YuNet 2023mar SHA256 found during research was `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`; the dynamic 2026may file was selected instead for OpenCV 5.x compatibility.

## Rejected or deferred options

| Option | Reason |
| --- | --- |
| InsightFace ArcFace / buffalo_l embeddings | Pretrained models are non-commercial / research-only unless separate commercial rights are obtained. |
| InsighhtFace RetinaFace detector | Same non-commercial model-weight restriction. |
| Ultralytics YOLO detectors | AGPL code and Enterprise/ToS constraints make them unsuitable for this permissive local prototype. |
| QMagFace / SER-FIQ | Research/non-commercial weights. |
| MediaPipe Face Landmarker / Face Mesh | Code is Apache-2.0 but model-use scope and additional runtime dependency are undesirable for this phase. Defer until explicitly approved. |
| Haar cascades | Poor reliability under CCTV blur, pose and lighting variation; no landmark support. |
| Generic dlib face recognition model | License/model restrictions and absence of a clear permissive pretrained weight set. |
| Cross-video ReID models | ReID weight licenses vary and cross-video identity linkage is out of scope. |
| Cloud vision APIs | Violates local-only handling of case footage. |

## License conclusions

- OpenCV Apache-2.0 code license is confirmed from `opencv/opencv_zoo` LICENSE.
- YuNet model weights are MIT according to the YuNet README.
- SFace model weights are Apache-2.0 according to the SFace README and OpenCV Zoo LICENSE.
- YOLOX OpenCV Zoo weights are Apache-2.0 according to the OpenCV Zoo LICENSE.
- No non-commercial or research-only weight is selected.
- No model with an unresolved commercial use restriction is downloaded in Phase 1.
- Full license texts and model-to-license mapping are stored in `docs/licenses/`.
- SFace attribution is recorded from the upstream README: contributed by Yaoyao Zhong, with ONNX conversion credited to Chengrui Wang.
- YuNet is MIT with Copyright (c) 2020 Shiqi Yu <shiqi.yu@gmail.com>.

## Embedding schema compatibility

- Newly generated embedding records use schema version 4 and record `opencv_version` and `embedding_schema_version` alongside model hash, source URL, runtime and analysis run ID.
- Legacy records remain readable; missing provenance is marked `legacy_unknown` / `unknown` and historical OpenCV and schema versions are never invented.
- Generation checksums and recovery remain authoritative; schema version changes do not invalidate previously verified generations.

## Benchmark evidence and timing

- Benchmark ranking evidence is stored in `data/cv/benchmark_ranking_evidence.json` with synthetic-only scope and no raw face crops or biometric vectors.
- Labels are used only for post-ranking evaluation, never for candidate generation or similarity scoring.
- Frame timings are single-pass synthetic smoke timings from one run, not repeated benchmarks with variance estimates.

## API resource limits

Analysis remains synchronous and bounded. Defaults are configurable through `ATM_SENTINEL_*` environment variables and exposed by `/api/cv/status`:

- `max_analysis_frames`: 300
- `max_frame_stride`: 20
- `max_decoded_frames`: 3000
- `max_clip_duration_seconds`: 300
- `max_crops_per_analysis`: 100
- `max_retained_crop_files`: 2000
- `max_top_k`: 25
- `max_ranked_candidates`: 100
- `max_face_observations_per_frame`: 8
- `max_person_observations_per_frame`: 12
- `max_face_observations_per_analysis`: 120
- `max_person_observations_per_analysis`: 200
- `max_face_detections_per_frame`: 64
- `max_person_detections_per_frame`: 128
- `max_face_detections_per_analysis`: 6000
- `max_person_detections_per_analysis`: 12000
- `max_response_bytes`: 750000
- `concurrent_analyses`: 1

Observation retention is capped after detection, never by lowering detector thresholds. All detector counts are preserved separately in `analysis.summary.face_detections`, `analysis.summary.person_detections`, and per-frame `total_counts`; retained records are counted in `counts` and `retained_*_observations`. Retention keeps the highest face-quality and highest person-confidence candidates first, then drops the remainder with explicit `truncation` indicators. A hard processing budget produces a controlled `CVError`/HTTP 400 instead of silently dropping evidence. If response serialization still exceeds `max_response_bytes`, lowest-priority retained observations and candidates are removed deterministically and reported under `response_truncation`.

Crops are opt-in (`save_crops=false` by default), written atomically, and pruned only when complete and nonempty. Responses are summary-only when `summary_only=true`; summary-only analysis avoids retaining or serializing per-frame details and candidate payloads. Full per-frame embeddings are always removed from API responses. A busy analyzer returns HTTP 503 with `Retry-After`.

## Expected resource use

Historical estimates only; the isolated 12-clip acceptance timings in `reports/acceptance/acceptance.md` are one synthetic run with stubbed CV inference and are not a benchmark:

- Disk: approximately 75 MB of ONNX weights.
- Resident memory: typically under 600 MB when all three models are loaded once.
- CPU: YOLOX-s at 640x640 dominates runtime; expected cost is seconds per frame on constrained CPUs.
- Acceleration: optional via OpenCV DNN backend/target settings; CPU fallback always available.

## Limitations

- YuNet was trained on face detection datasets and does not guarantee detection under heavy blur, occlusion, extreme pose or very small faces.
- SFace embeddings degrade with poor crops, low resolution and non-frontal faces; quality scores are used to suppress weak candidates rather than validate identity.
- YOLOX person detection is generic COCO person detection and is not specially trained for ATM scenes. The application default threshold is `0.45` and remains unvalidated; zero detections means no person was detected by this unvalidated detector, not that no person was present.
- Tracking uses deterministic greedy one-to-one matching, not a globally optimal assignment, and does not solve identity across occlusion, camera cuts or separate videos.
- Geometric pose proxies are explainable but approximate.
- Synthetic benchmark results validate only pipeline mechanics, reproducibility and failure handling. They are not evidence of production accuracy.

## Change control

- Before adding any model, repeat this license check and update this document.
- Before claiming real-world usefulness, run a separate validation with an explicitly approved, properly governed dataset.
