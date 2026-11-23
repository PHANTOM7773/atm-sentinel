# YuNet Face Detection Recall Investigation / Shadow Experiments

- Generated: 2026-11-23T11:55:53.716562+00:00
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
| challenges | baseline_original | 1.0 | 0.75 | 0.8571 | 0.0 | 0.0 | 6.004 | 1.0 | 0 |
| challenges | yunet_upscale_1_5x | 1.0 | 0.75 | 0.8571 | 0.0 | 0.0 | 18.96 | 3.1579 | 30 |
| challenges | yunet_upscale_2x | 1.0 | 0.75 | 0.8571 | 0.0 | 0.0 | 28.266 | 4.7079 | 10 |
| no_face | baseline_original | None | None | None | None | None | 5.661 | 1.0 | 0 |
| no_face | yunet_upscale_1_5x | None | None | None | None | None | 18.451 | 3.2593 | 0 |
| no_face | yunet_upscale_2x | None | None | None | None | None | 28.81 | 5.0892 | 0 |

## Evidence-based root causes
- `challenges.mp4` misses are concentrated in frames 30-39 (occluded block) in this synthetic set: baseline detected 0/10. Other challenge blocks (normal/blur/dark) were detected 10/10 in this controlled run.
- Manifest labels are frame-presence only; no bbox GT exists, so localization/IoU cannot be measured.
- Upscaling experiments are diagnostic; any gain on synthetic occlusion-like artifacts must not be interpreted as real-world improvement.

## Protected data / Git
- No DB, uploads, videos, evidence, exports, crops, or embedding generations modified.
- No Git write/add/commit/push/pull/fetch operations performed.
