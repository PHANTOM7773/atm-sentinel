# ATM Sentinel CV Baseline Benchmark (Task 02)

Generated: `2026-11-23T11:40:06.182988+00:00`

> Synthetic/sample-only baseline. Candidate-only outputs. No identity confirmation. No real CCTV/R4C validation.

## Methodology

- Dataset: `/Users/yps/Dev/web/atm/data/datasets/synthetic/cv` (manifest `/Users/yps/Dev/web/atm/data/datasets/synthetic/cv/manifest.json`)
- Runs: warmup=0, measurement=1, stride=1, top_k=5
- Pipeline: existing `CVPipeline` with current YOLOX/YuNet/SimpleTracker/SFace/quality/best-face behavior; no model/config threshold changes.
- No prohibited scripts run. No source assets, DB, evidence, exports, or embedding generations modified.

## Environment

- Platform: macOS-26.6.2-arm64-arm-64bit / arm64
- Python: 3.12.16 (CPython)
- OpenCV: 5.1.0 | NumPy: 2.5.5
- Peak RSS (best effort): 52838400 bytes (macOS ru_maxrss bytes; Linux ru_maxrss KiB*1024; best-effort process peak, includes test/runtime overhead.)

## Model Provenance

| Model | File | SHA256 | Expected | Verification | License |
|---|---|---|---|---|---|
| yunet | `face_detection_yunet_2026may.onnx` | `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0` | `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0` | verified | MIT weights; OpenCV Zoo Apache-2.0 repository |
| sface | `face_recognition_sface_2021dec.onnx` | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` | verified | Apache-2.0 |
| yolox | `object_detection_yolox_2022nov.onnx` | `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` | `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` | verified | Apache-2.0 |

## Measured / Heuristic / Not Assessable

### Detection (frame presence)

| Clip | Face P | Face R | Face F1 | Person P (heuristic proxy) | Person R (heuristic proxy) |
|---|---:|---:|---:|---:|---:|
| subject_a_front | 1.0 | 0.35 | 0.5185 | None | 0.0 |
| subject_a_side | 1.0 | 0.1333 | 0.2353 | None | 0.0 |
| subject_b_front | 1.0 | 0.2 | 0.3333 | None | 0.0 |
| multi_subject | 1.0 | 0.1714 | 0.2927 | None | 0.0 |
| challenges | 1.0 | 0.3 | 0.4615 | 1.0 | 0.2 |
| no_face | None | None | None | None | None |

> Box-level detection mAP/IoU: **NOT_ASSESSABLE** (manifest has no bounding-box GT). Person proxy uses face-presence labels only; heuristic.

### Tracking

- ID switches/fragmentation vs GT: **NOT_ASSESSABLE** — No valid ground-truth track annotations in manifest; cannot compute ID switches/fragmentation.
- Track stability counts measured per clip; see JSON for details.

### Recognition / Ranking

- Status: **MEASURED**
- Rank@1: 4/4 (1.0)
- Rank@5: 4/4 (1.0)
- False-match top1: 0/4 (0.0)
- Same-subject pairs: 20, different-subject pairs: 0
- Same-score mean±std: 0.952019 ± 0.006701
- Diff-score mean±std: None ± None

### Quality / Best-face

- Status: **HEURISTIC** — No ground-truth best-face annotations; reports existing quality/best-face selection outcomes only.
- All face quality: {'count': 44, 'mean': 92.845, 'std': 10.923, 'min': 66.3, 'p50': 97.75, 'max': 99.7}
- Selected best-face quality: {'count': 5, 'mean': 98.48, 'std': 0.859, 'min': 97.2, 'p50': 98.3, 'max': 99.7}

## Historical / Published

- Historical artifact: **HISTORICAL** `/Users/yps/Dev/web/atm/data/cv/benchmark.json` Historical artifact from previous benchmark script run; not regenerated in this task.
- Published upstream claims: **PUBLISHED_UPSTREAM** — Not measured locally in this run. See docs/CV_MODEL_SELECTION.md and model cards/papers for upstream claims; treat as non-local evidence.

## Limitations

- Synthetic-only dataset; no real CCTV, no R4C validation.
- Box-level GT unavailable; detection precision/recall reported as frame-presence where labels exist.
- Person frame-presence uses face-label proxy; heuristic only.
- No GT track IDs in manifest; ID switches/fragmentation NOT_ASSESSABLE.
- Recognition/ranking uses synthetic labels and should not be interpreted as identity accuracy.
- Peak RSS is best-effort process peak.

