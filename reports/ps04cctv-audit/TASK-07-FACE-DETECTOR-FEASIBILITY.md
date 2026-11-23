# TASK 07 — Alternative Face Detector Feasibility & Benchmark Integration

Generated: 2026-11-23 (local, uncommitted).  
Workspace: `/Users/yps/Dev/web/atm`

## 1. Scope and safety

- Evaluated feasibility/readiness only. **No production CV changes, no detector replacement, no threshold/config changes, no DB/schema/media/evidence/export/crop/embedding changes, no package/model downloads, no prohibited scripts, no service restarts.**
- Existing YuNet remains the baseline in production code (`backend/app/cv/detection.py` unchanged).
- All claims below distinguish **observed local facts**, **published/upstream claims** (not locally measured), and **NOT_ASSESSABLE** due missing annotations/models.

## 2. Phase 1 — Local inventory (observed)

### Existing face detection / model integration
- Face detector: `backend/app/cv/detection.py:YuNetFaceDetector` (OpenCV `FaceDetectorYN.create`, dynamic input size, score/NMS/topK, 5 landmarks, CPU fallback via runtime). Default threshold from `backend/app/config.py` `CV_FACE_SCORE_THRESHOLD=0.65` (observed in code path; not changed).
- Person detector: `YOLOXPersonDetector` in same file, ONNX via `cv2.dnn.readNetFromONNX`, 640 letterbox, BGR→RGB, CHW, grid/stride decode, person class 0, NMSBoxesBatched, default 0.45.
- Model registry/checksum verification: `backend/app/cv/models.py` with `MODEL_SPECS`, SHA256 verification, `model_status()`, `require_model()`.
- Local models present and verified (`data/models/SHA256SUMS.json`): YuNet `face_detection_yunet_2026may.onnx` (229,738 B, SHA256 ebafce...), SFace (38,696,353 B), YOLOX-s (35,858,002 B).
- Runtime/backend selection: `backend/app/cv/runtime.py` (not modified).

### Installed/runtime capabilities
- Python env: `.venv`, Python 3.12.16.
- `opencv-python-headless==5.1.0` installed; `onnxruntime` **not installed**; `insightface` **not installed**; `torch` **not installed**; `onnx` package **not installed**.
- OpenCV build observed: modules include `dnn, objdetect, ...`; DNN backends exposed include `DNN_BACKEND_CUDA`, `DNN_BACKEND_OPENCV`, etc. (capability presence in API != validated runtime performance on this machine).
- No prohibited scripts run; no package installs performed.

### Existing benchmark/experiment infrastructure
- Task 02 baseline benchmark: `backend/app/cv/baseline_benchmark.py`, `scripts/run_cv_baseline_benchmark.py`, report `CV-BASELINE-BENCHMARK-20261123T114054Z.*`.
- Task 03 YuNet recall/shadow: `backend/app/cv/yunet_recall_experiment.py`, report `YUNET-RECALL-EXPERIMENT-20261123T115642Z.*`.
- Task 04 selective fallback: `backend/app/cv/yunet_fallback_experiment.py`, report `YUNET-FALLBACK-EXPERIMENT-20261123T120401Z.*`.
- Task 05 person-gated: `backend/app/cv/yunet_person_gate_experiment.py`, report `YUNET-PERSON-GATE-EXPERIMENT-20261123T121706Z.*`.
- Task 06 YOLOX threshold: `backend/app/cv/yolox_threshold_experiment.py`, report `YOLOX-THRESHOLD-EXPERIMENT-20261123T122437Z.*`.

## 3. Phase 2 — Candidate feasibility analysis

**Caveat:** All model capability claims below are **published/upstream** unless marked observed. No weights downloaded, no benchmarks run on new models. License/provenance must be re-verified against the exact weight file/checkpoint/source before any download/use.

| Candidate | Arch/variants | Input/resolution | Small-face/pose/occlusion (published) | CPU complexity | Mac M1 | RTX 4050 | Memory/footprint | Deps | Integration complexity | Code license | Weight/checkpoint license/provenance | Redistribution/commercial risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **YuNet (baseline, existing)** | OpenCV YuNet, 5 landmarks | Dynamic input | Moderate; Task 03 showed 0/10 recovery on occluded challenge block, side-pose recoverable by 1.5x upscale | Low; already local | Good (observed local) | Not needed; OpenCV DNN CPU works | 230KB model | Already present (OpenCV) | None (current) | OpenCV Zoo Apache-2.0 | **MIT weights / OpenCV Zoo Apache-2.0 repo** as recorded in `models.py` (observed metadata; verify exact file) | **Low** if pinned SHA256/source maintained |
| **SCRFD (InsightFace)** | SCRFD_500M/2.5G/10G/34G; keypoints | Usually 640x640 or configurable | Published strong on WIDERFace/small faces; better than YuNet in many benchmarks (upstream claim) | 500M feasible on CPU; 10G heavier | Feasible with ONNXRuntime/CoreML EP; OpenCV DNN possible for ONNX but unverified | Good with ONNXRuntime CUDA EP/TensorRT; needs onnxruntime-gpu | 2MB–100MB+ depending variant | ONNXRuntime preferred; or OpenCV DNN ONNX; InsightFace pkg often used but not required | Medium: bbox+score+5-point landmarks mappable to `FaceDetection`; need NMS/decode adapter | InsightFace repo MIT | **Model weights/checkpoints: frequently non-commercial/research restrictions on InsightFace model packs; varies by exact file** | **High/unclear** for commercial/internal production until exact weight license confirmed; reject for production recommendation without explicit weight-license approval |
| **RetinaFace (InsightFace)** | ResNet50/MobileNet0.25; 5 landmarks | 640+ common | Strong published small-face/pose; heavier than SCRFD-500M | MobileNet possible; ResNet heavy CPU | Possible via ONNXRuntime | Good with GPU EP | ~1.7MB (mnet) to ~104MB (R50) | ONNXRuntime/PyTorch/InsightFace | Medium | InsightFace MIT code | **Same weight-license concern as SCRFD** for official InsightFace packs | **High/unclear** until exact checkpoint license verified |
| **RetinaFace (OpenCV Zoo / alternate licensed)** | OpenCV Zoo packaged models, if available | Varies | Upstream claims vary | Varies | Depends | Depends | Varies | OpenCV DNN | Low-medium if OpenCV Zoo format | OpenCV Zoo Apache-2.0 | Must verify exact checkpoint license/SHA256/source | **Medium** pending exact weight verification |
| **YOLOv8-face / YOLO-face ONNX (Ultralytics-derived)** | YOLOv8n/s face variants, community weights | 640 typical | Good speed/accuracy tradeoff upstream; small-face depends on variant/training | n/s feasible CPU | ONNXRuntime good | Good | 6MB+ | ONNXRuntime or Ultralytics (AGPL concerns) | Medium | Ultralytics code **AGPL-3.0** (major concern) unless alternative implementation | Community weights often unclear provenance/license | **High**: AGPL/code+weight provenance/commercial terms risky; avoid for production recommendation |
| **MTCNN** | PNet/RNet/ONet cascade | Multi-scale | Older; weaker on hard CCTV vs modern detectors | Moderate | OK | OK | small | Various implementations | Medium | Implementation-dependent | Weights/provenance implementation-dependent | **Medium**; not top candidate for hard-face recall |

### Key feasibility constraints
- **No onnxruntime/torch/insightface installed.** Any non-OpenCV-DNN path would require new dependencies (prohibited now). OpenCV 5.1 DNN can load ONNX models, but support varies by operator/model; must be validated per candidate with approved local weight.
- **Mac M1**: CPU viable for small ONNX models; CoreML/Metal acceleration would need onnxruntime-coreml or torch-mps, not currently installed.
- **RTX 4050**: viable for ONNXRuntime CUDA/TensorRT or torch CUDA; neither installed. Current env appears CPU/OpenCV-DNN oriented.
- **Licensing blocker**: many high-performing face detectors (InsightFace SCRFD/RetinaFace packs) have **code MIT but weight/use restrictions**; exact checkpoint license must be verified before any download. This blocks production recommendation by default.

## 4. Phase 3 — Common detector interface (isolated, optional, testable without new models)

Created an isolated experimental adapter contract in `backend/app/cv/face_detector_interface.py` (no production wiring, no pipeline/config changes). It normalizes:
- model identity/version/source metadata
- input size and processing latency
- detections in original-frame coordinates: bbox, confidence, landmarks(optional), timestamp/frame number
- explicit unavailable-model/error status

YuNet adapter wraps existing `YuNetFaceDetector` only when model is available; unavailable models return structured `DetectorUnavailable`/error result, never fake detections. No new model loaded.

## 5. Phase 4 — Benchmark readiness

### Ready now (observed)
- Reusable runners exist for Task 02-06; synthetic manifest with frame-presence labels for 6 clips.
- `baseline_benchmark.py` already separates MEASURED/HEURISTIC/NOT_ASSESSABLE and records provenance/env/model hashes.
- Frame-presence P/R/F1 can be computed where labels exist. No-face FP measurable.

### Gaps / NOT_ASSESSABLE
- **Bounding-box GT**: absent. IoU/mAP/localization precision = **NOT_ASSESSABLE**.
- **Person bbox/track GT**: absent. Person detector accuracy and track ID switches/fragmentation = **NOT_ASSESSABLE**.
- **Occlusion/mask/pose labels**: absent except coarse clip descriptions; per-condition claims limited.
- **Real CCTV/R4C validation**: absent. No real-world claims allowed.
- **Independent subjects**: adjacent frames are not independent samples.
- **Approved alternative detector weights**: none local; cannot benchmark SCRFD/RetinaFace until legally approved weight + SHA256 pinned + local availability.

### Benchmark readiness improvements needed before candidate benchmarking
1. Obtain legally approved model weight(s) with explicit license, source URL, pinned revision, SHA256.
2. Add bbox GT annotation format (only if human-annotated/approved; no fake GT).
3. Add per-frame condition tags (pose/blur/occlusion/illumination/small-face) with annotation provenance.
4. Add detector adapter loading path that is opt-in and does not affect production defaults.
5. Record CPU/GPU device, batch=1 latency, RSS, model hash, and failure modes.

## 6. Phase 5 — Recommendation (evidence-bounded)

1. **Test first (after approvals): SCRFD-500M or 2.5G ONNX**, *only* if an explicitly licensed, redistributable checkpoint is identified (e.g., OpenCV Zoo/community package with clear commercial-permissive weight license and verifiable SHA256). Do **not** use InsightFace official model packs without written/legal confirmation of weight license for intended use.
2. **Why technically suitable**: published small-face/pose performance better than YuNet; ONNX export common; 500M variant likely CPU-feasible on M1; 640 input aligns with existing CV sizing patterns. Still unproven locally.
3. **Legal usability**: **NOT APPROVED/UNKNOWN** for common InsightFace-distributed weights. YuNet remains the only clearly low-risk local baseline with recorded provenance.
4. **Mac M1 / RTX 4050**: M1 can likely run SCRFD-500M via CPU OpenCV DNN or future ONNXRuntime; RTX 4050 can accelerate via ONNXRuntime CUDA EP if later approved/installed. Current env lacks onnxruntime/torch, so GPU path is not install-ready.
5. **Exact variant/source needed before any download**: specify exact filename, version, source URL, commit/revision, SHA256, code license, **weight license text/URL**, and intended-use terms. No download until approved.
6. **Missing validation**: bbox GT, person GT, occlusion/pose/illumination tags, real CCTV/R4C approved data, independent test protocol.
7. **Approvals required before download/install**: explicit user/legal approval for weight license; approval for any dependency install; approval for adding model file; security review of source; SHA256 pinning; no production integration without separate approval.

## 7. Deliverables created

- `reports/ps04cctv-audit/TASK-07-FACE-DETECTOR-FEASIBILITY.md` (this report)
- `reports/ps04cctv-audit/TASK-07-DETECTOR-COMPARISON-MATRIX.json`
- `reports/ps04cctv-audit/TASK-07-LICENSE-PROVENANCE-ASSESSMENT.json`
- `reports/ps04cctv-audit/TASK-07-BENCHMARK-READINESS.json`
- `backend/app/cv/face_detector_interface.py` (isolated experimental adapter/interface; no production wiring)
- `backend/tests/test_face_detector_interface.py` (focused tests)

## 8. Safety confirmations

- No production detector replacement, no config/threshold changes, no DB/schema/media/evidence/export/crop/embedding changes.
- No package installations, no model downloads, no prohibited scripts, no service restarts.
- **Explicit confirmation: NO Git write/add/commit/push/pull/fetch/sync/branch/tag/reset/rebase/cherry-pick operation was performed.** GitHub backup remains untouched.
