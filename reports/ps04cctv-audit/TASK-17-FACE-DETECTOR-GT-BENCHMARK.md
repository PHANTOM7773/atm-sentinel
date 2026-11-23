# TASK 17 — Face Detector Ground-Truth Benchmark

## Status / QA gate
- **Exploratory only.** Human annotations: `reports/ps04cctv-audit/annotations/human-annotations.status-fixed.json` remain **NOT_REVIEWED**. No benchmark finding is production/real-CCTV evidence until visual QA is completed.
- Annotations not modified. Synthetic authorized dataset only; no real-CCTV accuracy claim.

## 1) Ground truth verification
- Schema/path/dimensions/box bounds checked by `validate_annotations`: **ok**.
- Frames: **48**. Total face boxes: **46**. No-face frames: **9**. Clips: 6 (`subject_a_front`, `subject_a_side`, `subject_b_front`, `multi_subject`, `no_face`, `challenges`).
- Image mapping: derived PNG and source video paths exist for all frames. Bbox format `xywh_pixels_top_left`, original frame pixel space.

## 2) Strategies evaluated (existing code reused)
Reused `backend/app/cv/detection.py` YuNet + scaling/merge logic patterns from `face_detection_experiments.py`.
- `yunet_baseline`: original YuNet.
- `yunet_full_1_5x`: always baseline + 1.5x upscale, deduped.
- `yunet_zero_detection_fallback_1_5x`: 1.5x only when baseline has zero detections.
- `yunet_conf_fallback_lt_0_7`: 1.5x when baseline max confidence < 0.7.

## 3) Metrics (box-level, one-to-one IoU matching)
Configurable thresholds: IoU=0.5, conf in {0.0,0.5,0.7}; primary reported conf=0.5, IoU=0.5. AP@0.5 computed VOC-style all-point over annotated boxes. Frame-level no-face FP rate reported separately.

| Strategy | P | R | F1 | AP@0.5 | Mean matched IoU | No-face FP frames/boxes | Mean latency ms | Fallback rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| yunet_baseline | 1.000 | 0.870 | 0.930 | 0.870 | 0.661 | 0/0 (0.0) | 5.73 | 0.00 |
| yunet_full_1_5x | 1.000 | 0.913 | 0.955 | 0.913 | 0.678 | 0/0 (0.0) | 17.47 | 1.00 |
| yunet_zero_detection_fallback_1_5x | 1.000 | 0.913 | 0.955 | 0.913 | 0.661 | 0/0 (0.0) | 9.28 | 0.3125 |
| yunet_conf_fallback_lt_0_7 | 1.000 | 0.913 | 0.955 | 0.913 | 0.661 | 0/0 (0.0) | 9.33 | 0.3125 |

## 4) Per-clip misses (conf=0.5, IoU=0.5)
All strategies: perfect on `subject_a_front`, `subject_b_front`, `multi_subject`, `no_face`.
Misses remain:
- `subject_a_side`: baseline R 0.50 (FN 3/6); upscale/fallback strategies R 0.833 (FN 1/6) — improvement.
- `challenges`: all strategies R 0.70 (FN 3/10) — no improvement from 1.5x/fallback.

## 5) Analysis
- **Miss causes:** side/challenge frames remain hardest; 1.5x recovers 2 side misses but not challenge misses. No bbox GT for localization beyond IoU mean on matched boxes.
- **Multi-scale/fallback value:** improves recall/F1/AP@0.5 by +0.043 recall vs baseline on this small synthetic exploratory set; no added false positives on 9 no-face frames.
- **Latency:** full 1.5x is ~3.05x baseline latency (17.47ms vs 5.73ms). Zero/conf fallback gives same recall gain as full 1.5x at ~1.62x latency and 31.25% fallback rate.
- **False positives:** none observed on annotated no-face frames at conf=0.5/IoU=0.5; this is limited by small no-face sample and NOT_REVIEWED GT.

## 6) Recommendation
- **Further testing candidate:** `yunet_zero_detection_fallback_1_5x` (or conf fallback) — same recall gain as full 1.5x, much lower latency, no observed no-face FPs in this exploratory set.
- **Not production-ready:** GT is NOT_REVIEWED, synthetic-only, 48 frames/46 boxes; no real-CCTV claim. Before any production change: complete visual QA, expand GT (real CCTV/varied conditions), add localization/error analysis, and run regression/latency budgets.

## 7) Artifacts
- Code: `backend/app/cv/face_detector_gt_benchmark.py`
- Tests: `backend/tests/test_face_detector_gt_benchmark.py`
- Script: `scripts/run_face_detector_gt_benchmark.py`
- JSON: `reports/ps04cctv-audit/TASK-17-FACE-DETECTOR-GT-BENCHMARK.json`
- Report: this file
