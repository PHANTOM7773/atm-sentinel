# YOLOX Person Detection Threshold Sensitivity & Reliability Evaluation

- Generated: 2026-11-23T12:24:37.166407+00:00
- Dataset: `/Users/yps/Dev/web/atm/data/datasets/synthetic/cv` (synthetic_only=True, real_people=False)
- Production behavior: **unchanged**. No threshold selected.

## Threshold sensitivity (face-positive-frame coverage is PROXY only; no person GT)
| thr | clip | gt face+ | person on gt-face+ | coverage proxy | person on gt-face-neg | mean ms |
|---:|---|---:|---:|---:|---:|---:|
| 0.1 | subject_a_front | 40 | 9 | 0.225 | 0 | 111.152 |
| 0.1 | subject_a_side | 30 | 0 | 0.0 | 0 | 105.29 |
| 0.1 | subject_b_front | 40 | 0 | 0.0 | 0 | 116.384 |
| 0.1 | multi_subject | 35 | 0 | 0.0 | 0 | 112.831 |
| 0.1 | challenges | 40 | 17 | 0.425 | 0 | 119.175 |
| 0.1 | no_face | 0 | 0 | None | 0 | 116.274 |
| 0.2 | subject_a_front | 40 | 2 | 0.05 | 0 | 106.724 |
| 0.2 | subject_a_side | 30 | 0 | 0.0 | 0 | 110.97 |
| 0.2 | subject_b_front | 40 | 0 | 0.0 | 0 | 112.176 |
| 0.2 | multi_subject | 35 | 0 | 0.0 | 0 | 112.881 |
| 0.2 | challenges | 40 | 10 | 0.25 | 0 | 119.227 |
| 0.2 | no_face | 0 | 0 | None | 0 | 116.296 |
| 0.3 | subject_a_front | 40 | 0 | 0.0 | 0 | 110.904 |
| 0.3 | subject_a_side | 30 | 0 | 0.0 | 0 | 105.331 |
| 0.3 | subject_b_front | 40 | 0 | 0.0 | 0 | 112.197 |
| 0.3 | multi_subject | 35 | 0 | 0.0 | 0 | 117.699 |
| 0.3 | challenges | 40 | 10 | 0.25 | 0 | 119.234 |
| 0.3 | no_face | 0 | 0 | None | 0 | 116.269 |
| 0.4 | subject_a_front | 40 | 0 | 0.0 | 0 | 106.733 |
| 0.4 | subject_a_side | 30 | 0 | 0.0 | 0 | 110.907 |
| 0.4 | subject_b_front | 40 | 0 | 0.0 | 0 | 112.245 |
| 0.4 | multi_subject | 35 | 0 | 0.0 | 0 | 112.859 |
| 0.4 | challenges | 40 | 8 | 0.2 | 0 | 119.192 |
| 0.4 | no_face | 0 | 0 | None | 0 | 116.293 |
| 0.45 | subject_a_front | 40 | 0 | 0.0 | 0 | 110.922 |
| 0.45 | subject_a_side | 30 | 0 | 0.0 | 0 | 105.32 |
| 0.45 | subject_b_front | 40 | 0 | 0.0 | 0 | 112.209 |
| 0.45 | multi_subject | 35 | 0 | 0.0 | 0 | 117.685 |
| 0.45 | challenges | 40 | 8 | 0.2 | 0 | 116.177 |
| 0.45 | no_face | 0 | 0 | None | 0 | 124.765 |
| 0.5 | subject_a_front | 40 | 0 | 0.0 | 0 | 106.756 |
| 0.5 | subject_a_side | 30 | 0 | 0.0 | 0 | 105.327 |
| 0.5 | subject_b_front | 40 | 0 | 0.0 | 0 | 116.661 |
| 0.5 | multi_subject | 35 | 0 | 0.0 | 0 | 113.103 |
| 0.5 | challenges | 40 | 8 | 0.2 | 0 | 119.324 |
| 0.5 | no_face | 0 | 0 | None | 0 | 116.297 |

## Limitations
- Manifest has face-presence labels, not person bounding-box GT. Face-positive-frame coverage is a PROXY only, not person recall/precision/mAP/localization.
- Adjacent frames are not independent subjects/samples; synthetic diagnostic only.
- No production threshold selected or changed.
- No Git write/synchronization operations performed.
