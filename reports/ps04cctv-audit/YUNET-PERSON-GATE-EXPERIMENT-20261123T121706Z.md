# YuNet Person-Gated Fallback - Shadow Evaluation

- Generated: 2026-11-23T12:17:06.836105+00:00
- Dataset: `/Users/yps/Dev/web/atm/data/datasets/synthetic/cv` (synthetic_only=True, real_people=False)
- Production behavior: **unchanged** (experimental only).

## YOLOX evidence (observational; no person bbox GT in manifest)
| clip | gt face+ frames | person on gt-face frames | person recall proxy | miss person on gt-face | fp person on gt-face-neg |
|---|---:|---:|---:|---:|---:|
| subject_a_front | 40 | 0 | 0.0 | 40 | 0 |
| subject_a_side | 30 | 0 | 0.0 | 30 | 0 |
| subject_b_front | 40 | 0 | 0.0 | 40 | 0 |
| multi_subject | 35 | 0 | 0.0 | 35 | 0 |
| challenges | 40 | 8 | 0.2 | 32 | 0 |
| no_face | 0 | 0 | None | 0 | 0 |

## Comparison
| clip | strategy | P | R | F1 | dR base | lat ms | lat x base | fb% | yolox | yunet | dR vs zero-fb | lat x zero-fb |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| challenges | baseline_yunet | 1.0 | 0.75 | 0.8571 | 0.0 | 5.739 | 1.0 | 0.0 | 0 | 55 | 0.0 | 0.507 |
| challenges | zero_detection_fallback_1_5x | 1.0 | 0.75 | 0.8571 | 0.0 | 11.32 | 1.9725 | 0.4545 | 0 | 80 | 0.0 | 1.0 |
| challenges | person_gated_zero_fallback_skip | 1.0 | 0.75 | 0.8571 | 0.0 | 54.184 | 9.4414 | 0.0 | 25 | 55 | 0.0 | 4.7866 |
| challenges | person_gated_zero_fallback_safety_run | 1.0 | 0.75 | 0.8571 | 0.0 | 61.72 | 10.7545 | 0.4545 | 25 | 80 | 0.0 | 5.4523 |
| challenges | person_region_1_5x_experimental | 1.0 | 0.75 | 0.8571 | 0.0 | 58.701 | 10.2284 | 0.0 | 25 | 55 | 0.0 | 5.1856 |
| multi_subject | baseline_yunet | 1.0 | 1.0 | 1.0 | 0.0 | 5.733 | 1.0 | 0.0 | 0 | 35 | 0.0 | 0.974 |
| multi_subject | zero_detection_fallback_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 5.886 | 1.0267 | 0.0 | 0 | 35 | 0.0 | 1.0 |
| multi_subject | person_gated_zero_fallback_skip | 1.0 | 1.0 | 1.0 | 0.0 | 5.894 | 1.0281 | 0.0 | 0 | 35 | 0.0 | 1.0014 |
| multi_subject | person_gated_zero_fallback_safety_run | 1.0 | 1.0 | 1.0 | 0.0 | 6.012 | 1.0487 | 0.0 | 0 | 35 | 0.0 | 1.0214 |
| multi_subject | person_region_1_5x_experimental | 1.0 | 1.0 | 1.0 | 0.0 | 6.091 | 1.0624 | 0.0 | 0 | 35 | 0.0 | 1.0348 |
| no_face | baseline_yunet | None | None | None | None | 5.771 | 1.0 | 0.0 | 0 | 20 | None | 0.3201 |
| no_face | zero_detection_fallback_1_5x | None | None | None | None | 18.027 | 3.1237 | 1.0 | 0 | 40 | None | 1.0 |
| no_face | person_gated_zero_fallback_skip | None | None | None | None | 112.577 | 19.5074 | 0.0 | 20 | 20 | None | 6.2449 |
| no_face | person_gated_zero_fallback_safety_run | None | None | None | None | 128.165 | 22.2085 | 1.0 | 20 | 40 | None | 7.1096 |
| no_face | person_region_1_5x_experimental | None | None | None | None | 133.139 | 23.0704 | 0.0 | 20 | 20 | None | 7.3855 |
| subject_a_front | baseline_yunet | 1.0 | 1.0 | 1.0 | 0.0 | 5.992 | 1.0 | 0.0 | 0 | 40 | 0.0 | 1.0054 |
| subject_a_front | zero_detection_fallback_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 5.96 | 0.9947 | 0.0 | 0 | 40 | 0.0 | 1.0 |
| subject_a_front | person_gated_zero_fallback_skip | 1.0 | 1.0 | 1.0 | 0.0 | 5.819 | 0.9711 | 0.0 | 0 | 40 | 0.0 | 0.9763 |
| subject_a_front | person_gated_zero_fallback_safety_run | 1.0 | 1.0 | 1.0 | 0.0 | 6.145 | 1.0255 | 0.0 | 0 | 40 | 0.0 | 1.031 |
| subject_a_front | person_region_1_5x_experimental | 1.0 | 1.0 | 1.0 | 0.0 | 6.602 | 1.1018 | 0.0 | 0 | 40 | 0.0 | 1.1077 |
| subject_a_side | baseline_yunet | 1.0 | 0.5667 | 0.7234 | 0.0 | 5.765 | 1.0 | 0.0 | 0 | 30 | -0.4 | 0.5139 |
| subject_a_side | zero_detection_fallback_1_5x | 1.0 | 0.9667 | 0.9831 | 0.4 | 11.218 | 1.9459 | 0.4333 | 0 | 43 | 0.0 | 1.0 |
| subject_a_side | person_gated_zero_fallback_skip | 1.0 | 0.5667 | 0.7234 | 0.0 | 51.068 | 8.8583 | 0.0 | 13 | 30 | -0.4 | 4.5523 |
| subject_a_side | person_gated_zero_fallback_safety_run | 1.0 | 0.9667 | 0.9831 | 0.4 | 58.616 | 10.1676 | 0.4333 | 13 | 43 | 0.0 | 5.2252 |
| subject_a_side | person_region_1_5x_experimental | 1.0 | 0.5667 | 0.7234 | 0.0 | 59.981 | 10.4043 | 0.0 | 13 | 30 | -0.4 | 5.3469 |
| subject_b_front | baseline_yunet | 1.0 | 1.0 | 1.0 | 0.0 | 5.688 | 1.0 | 0.0 | 0 | 40 | 0.0 | 1.0026 |
| subject_b_front | zero_detection_fallback_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 5.673 | 0.9974 | 0.0 | 0 | 40 | 0.0 | 1.0 |
| subject_b_front | person_gated_zero_fallback_skip | 1.0 | 1.0 | 1.0 | 0.0 | 5.787 | 1.0174 | 0.0 | 0 | 40 | 0.0 | 1.0201 |
| subject_b_front | person_gated_zero_fallback_safety_run | 1.0 | 1.0 | 1.0 | 0.0 | 6.149 | 1.081 | 0.0 | 0 | 40 | 0.0 | 1.0839 |
| subject_b_front | person_region_1_5x_experimental | 1.0 | 1.0 | 1.0 | 0.0 | 6.656 | 1.1702 | 0.0 | 0 | 40 | 0.0 | 1.1733 |

## Limitations
- Frame-presence labels only; bbox GT absent so localization/IoU NOT_ASSESSABLE.
- Synthetic diagnostic only; adjacent frames are not independent subjects/samples.
- YOLOX person labels are not present in manifest; person-gate evidence is observational on this synthetic set.
- No production behavior/config/model/threshold changes.

## Safety
- No production code/config/model/threshold changes. No DB/media/evidence/crops/embeddings changed.
- No Git write/synchronization operations performed.
