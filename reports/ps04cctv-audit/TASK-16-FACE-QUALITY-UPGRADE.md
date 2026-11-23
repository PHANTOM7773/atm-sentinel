# TASK 16 — Face Quality Scoring Upgrade

## Scope
- Isolated local experiment only. No production best-face ranking/SFace embedding changes, no service restarts, no protected data/annotation/original crop changes, no dependency/model downloads/installs, no Git write/sync.

## 1) Existing implementation inspection
- `backend/app/cv/quality.py` `analyze_face_quality`: Laplacian sharpness, mean brightness, std contrast, face/crop size, landmark visibility, geometric pose proxies, occlusion proxy; 0-100 score; warnings/flags; disclaimers (not identity/biometric).
- `backend/app/cv/landmarks.py`: `estimate_pose`, `landmark_visibility`, `occlusion_proxy` (5-point YuNet landmarks; heuristic, uncalibrated).
- `backend/app/services/best_face.py`: deterministic best-face ranking over existing observations; weights sharpness/usable_resolution/frontalness/illumination/contrast/landmark_visibility/detector_confidence; hard rejection flags; occlusion review factor; tie-break by earlier frame then observation_id. Uses existing quality components; does not use noise dimension.
- `backend/app/services/face_reliability.py`: conservative review reliability/visibility indicators; separate from identity.

Weaknesses identified: no explicit noise metric; no configurable weight interface in quality evaluator; missing-metric handling coarse; no dimension-level reason codes/scores in a single isolated evaluator; overall score not explicitly renormalized over available dimensions.

## 2) Isolated evaluator
- Added `backend/app/cv/face_quality_experiment.py` with `evaluate_face_quality(...)`.
- Dimensions (0-100 each, explainable): sharpness/blur (Laplacian var), resolution/usable pixel area (face min px + area), exposure/brightness (distance from mid-gray), contrast (stddev), noise (Laplacian MAD + HF residual std), pose/frontalness (existing landmark pose proxy), occlusion/visibility (existing landmark visibility/occlusion proxy).
- Output: `overall_score` 0-100, per-dimension score/available/weight/contribution/reason_codes/warnings/metrics, missing/unavailable indicators, configurable weights (normalized over active/available dims), clear reason codes/warnings.
- Explicit disclaimer: **not probability of identity or recognition accuracy**.
- Missing landmarks: pose/occlusion marked unavailable with reason codes; overall renormalized over available dimensions.

## 3) Benchmark (actual local crops)
- Script: `scripts/benchmark_face_quality.py`
- JSON: `reports/ps04cctv-audit/TASK-16-FACE-QUALITY-BENCHMARK.json`
- Data: existing synthetic-derived crops from `data/cv/crops` + TASK 15 demo inputs; controlled in-memory degraded variants: blur, downscale, low light, low contrast, noise. No original crops/annotations modified.

| Sample | Orig old/new | Blur old/new | Downscale old/new | Low-light old/new | Low-contrast old/new | Noise old/new |
|---|---:|---:|---:|---:|---:|---:|
| dark_sample | 52.4 / 72.99 | 22.7 / 36.92 | 27.2 / 42.30 | 19.5 / 35.56 | 38.3 / 56.32 | 53.8 / 62.82 |
| blurred_sample | 59.9 / 81.82 | 43.2 / 61.09 | 44.2 / 62.32 | 24.3 / 41.66 | 41.1 / 59.70 | 71.6 / 84.34 |
| normal_sample | 61.4 / 83.68 | 43.2 / 61.02 | 44.6 / 62.77 | 25.1 / 42.55 | 41.8 / 60.50 | 71.9 / 84.56 |
| task15_dark | 59.9 / 81.82 | 43.2 / 61.09 | 44.2 / 62.32 | 24.3 / 41.66 | 41.1 / 59.70 | 71.6 / 84.34 |
| task15_blurred | 59.9 / 81.82 | 43.2 / 61.09 | 44.2 / 62.32 | 24.3 / 41.66 | 41.1 / 59.70 | 71.6 / 84.34 |
| task15_normal | 60.8 / 82.99 | 43.3 / 61.18 | 44.2 / 62.29 | 24.4 / 41.77 | 41.6 / 60.21 | 71.8 / 84.46 |

Direction checks: blur/downscale/low-light/low-contrast reduced relevant dimension scores as expected (0 inconsistencies by script). Noise dimension dropped sharply in all samples (e.g. 100 -> ~0.95-2.87).
Inconsistency observed: overall score increased for noise variants in 5/6 samples because added random noise increased Laplacian variance/contrast-like signals used by sharpness/legacy components, outweighing noise penalty at current weights. This is reported as a heuristic limitation; noise metric itself behaved as expected.

## 4) AI quality model feasibility (CR-FIQA / MagFace)
- Local package check: `insightface/onnxruntime/torch/cr_fiqa/magface` all missing.
- Local weights: only existing YuNet/SFace/YOLOX ONNX present in `data/models`; no CR-FIQA/MagFace weights.
- Code/weight licenses: **not verified as usable locally** because runtime/weights unavailable; any future use requires separate code-license and pretrained-weight/provenance review.
- Blocker: missing packages + missing approved local weights. No downloads/installs performed.

## 5) Tests
- Added `backend/tests/test_face_quality_experiment.py` (8 tests): bounds/reason codes/disclaimer, determinism, blur degradation, dark/low-contrast degradation, noisy degradation, tiny-face resolution flag, missing landmarks unavailable handling, invalid input failure.
- Focused: `9 passed` with `backend/tests/test_ai_restoration_adapters.py`.
- Guarded regression: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --tb=no -k 'not test_synthetic_generator_writes_labelled_clips'` → `323 passed, 1 deselected, 1 warning`.

## Limitations / recommendation
- Isolated evaluator only; **not wired into production**. Do not use for SFace matching/identity decisions.
- Heuristic, not calibrated; overall score can increase under synthetic noise because noise can inflate sharpness/contrast proxies. Before production, recalibrate weights, cap sharpness gain when noise high, and validate on annotated real CCTV/crop sets.
- Pose/occlusion require landmarks; unavailable when landmarks missing.
- CR-FIQA/MagFace unavailable locally; cannot be benchmarked.

**Recommendation:** **Not justified for production integration yet.** Keep isolated. Next step: add noise-aware sharpness penalty/weight recalibration, validate against human-reviewed/bbox-ground-truth crops, then consider replacing/augmenting `best_face.py` scoring behind a feature flag with regression tests.
