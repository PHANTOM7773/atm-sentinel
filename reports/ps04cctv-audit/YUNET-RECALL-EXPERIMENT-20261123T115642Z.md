# YuNet Face Detection Recall Investigation / Shadow Experiments

- Generated: 2026-11-23T11:56:42.133979+00:00
- Dataset: `/Users/yps/Dev/web/atm/data/datasets/synthetic/cv` (synthetic_only=True, real_people=False)
- Dedupe IoU: 0.5
- Production behavior: **unchanged** (isolated experimental path only; no detector/config/threshold/model replacement).

## Limitations
- Frame-presence labels only; no bounding-box GT, so IoU/localization accuracy is NOT_ASSESSABLE.
- Adjacent video frames are not independent subjects/samples; results are clip/frame-presence diagnostics on synthetic assets.
- Multi-face frames counted as present if any face detected; this can overstate recall in multi-face conditions.
- No production thresholds/config/models were changed; experiments are isolated.

## Comparison

| clip | variant | precision | recall | f1 | delta recall | delta precision | mean ms | latency x | dup removed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| challenges | baseline_original | 1.0 | 0.75 | 0.8571 | 0.0 | 0.0 | 5.498 | 1.0 | 0 |
| challenges | yunet_upscale_1_5x | 1.0 | 0.75 | 0.8571 | 0.0 | 0.0 | 17.91 | 3.2575 | 30 |
| challenges | yunet_upscale_2x | 1.0 | 0.75 | 0.8571 | 0.0 | 0.0 | 27.168 | 4.9414 | 10 |
| multi_subject | baseline_original | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 5.607 | 1.0 | 0 |
| multi_subject | yunet_upscale_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 17.931 | 3.198 | 70 |
| multi_subject | yunet_upscale_2x | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 26.805 | 4.7806 | 0 |
| no_face | baseline_original | None | None | None | None | None | 5.499 | 1.0 | 0 |
| no_face | yunet_upscale_1_5x | None | None | None | None | None | 17.97 | 3.2679 | 0 |
| no_face | yunet_upscale_2x | None | None | None | None | None | 28.024 | 5.0962 | 0 |
| subject_a_front | baseline_original | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 5.768 | 1.0 | 0 |
| subject_a_front | yunet_upscale_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 18.251 | 3.1642 | 40 |
| subject_a_front | yunet_upscale_2x | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 26.969 | 4.6756 | 22 |
| subject_a_side | baseline_original | 1.0 | 0.5667 | 0.7234 | 0.0 | 0.0 | 5.625 | 1.0 | 0 |
| subject_a_side | yunet_upscale_1_5x | 1.0 | 0.9667 | 0.9831 | 0.4 | 0.0 | 17.858 | 3.1748 | 17 |
| subject_a_side | yunet_upscale_2x | 1.0 | 0.5667 | 0.7234 | 0.0 | 0.0 | 26.901 | 4.7824 | 1 |
| subject_b_front | baseline_original | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 5.51 | 1.0 | 0 |
| subject_b_front | yunet_upscale_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 18.759 | 3.4045 | 40 |
| subject_b_front | yunet_upscale_2x | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 26.813 | 4.8662 | 11 |

## Evidence-based root causes
- `challenges.mp4` misses are concentrated in frames 30-39 (occluded block) in this synthetic set: baseline detected 0/10. Other challenge blocks (normal/blur/dark) were detected 10/10 in this controlled run.
- Manifest labels are frame-presence only; no bbox GT exists, so localization/IoU cannot be measured.
- Upscaling experiments are diagnostic; any gain on synthetic occlusion-like artifacts must not be interpreted as real-world improvement.

## Protected data / Git
- No DB, uploads, videos, evidence, exports, crops, or embedding generations modified.
- No Git write/add/commit/push/pull/fetch operations performed.
