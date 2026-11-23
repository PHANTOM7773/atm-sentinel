# YuNet Selective Upscaling Fallback - Shadow Evaluation

- Generated: 2026-11-23T12:04:01.114018+00:00
- Dataset: `/Users/yps/Dev/web/atm/data/datasets/synthetic/cv` (synthetic_only=True, real_people=False)
- Dedupe IoU: 0.5
- Production behavior: **unchanged** (experimental evaluation only).

## Task 03 evidence / trigger rationale
- All TASK 03 recovered GT frames on subject_a_side came from baseline-zero-detection frames (12/12).
- Confidence-based fallback below 0.75 would also trigger on 7 low-confidence baseline GT hits (frames 1-7), adding latency with no additional GT recovery in this dataset.
- Zero-detection fallback is the minimal evidence-supported trigger; confidence fallback evaluated as sensitivity analysis only.

## Comparison

| clip | strategy | P | R | F1 | dR vs base | lat ms | lat x base | fallback % | dR vs full 1.5x | lat x full 1.5x |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| challenges | baseline_only | 1.0 | 0.75 | 0.8571 | 0.0 | 6.611 | 1.0 | 0.0 | 0.0 | 0.3704 |
| challenges | full_1_5x | 1.0 | 0.75 | 0.8571 | 0.0 | 17.848 | 2.6997 | 1.0 | 0.0 | 1.0 |
| challenges | zero_detection_fallback_1_5x | 1.0 | 0.75 | 0.8571 | 0.0 | 11.453 | 1.7324 | 0.4545 | 0.0 | 0.6417 |
| challenges | confidence_fallback_lt_0_7 | 1.0 | 0.75 | 0.8571 | 0.0 | 13.461 | 2.0362 | 0.4545 | 0.0 | 0.7542 |
| challenges | confidence_fallback_lt_0_75 | 1.0 | 0.75 | 0.8571 | 0.0 | 18.984 | 2.8716 | 0.4545 | 0.0 | 1.0636 |
| challenges | confidence_fallback_lt_0_8 | 1.0 | 0.75 | 0.8571 | 0.0 | 12.908 | 1.9525 | 0.4545 | 0.0 | 0.7232 |
| multi_subject | baseline_only | 1.0 | 1.0 | 1.0 | 0.0 | 6.323 | 1.0 | 0.0 | 0.0 | 0.3593 |
| multi_subject | full_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 17.598 | 2.7832 | 1.0 | 0.0 | 1.0 |
| multi_subject | zero_detection_fallback_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 5.679 | 0.8981 | 0.0 | 0.0 | 0.3227 |
| multi_subject | confidence_fallback_lt_0_7 | 1.0 | 1.0 | 1.0 | 0.0 | 5.926 | 0.9372 | 0.0 | 0.0 | 0.3367 |
| multi_subject | confidence_fallback_lt_0_75 | 1.0 | 1.0 | 1.0 | 0.0 | 5.85 | 0.9252 | 0.0 | 0.0 | 0.3324 |
| multi_subject | confidence_fallback_lt_0_8 | 1.0 | 1.0 | 1.0 | 0.0 | 10.716 | 1.6948 | 0.0 | 0.0 | 0.6089 |
| no_face | baseline_only | None | None | None | None | 6.582 | 1.0 | 0.0 | None | 0.3732 |
| no_face | full_1_5x | None | None | None | None | 17.636 | 2.6794 | 1.0 | None | 1.0 |
| no_face | zero_detection_fallback_1_5x | None | None | None | None | 17.596 | 2.6734 | 1.0 | None | 0.9977 |
| no_face | confidence_fallback_lt_0_7 | None | None | None | None | 23.068 | 3.5047 | 1.0 | None | 1.308 |
| no_face | confidence_fallback_lt_0_75 | None | None | None | None | 28.966 | 4.4008 | 1.0 | None | 1.6424 |
| no_face | confidence_fallback_lt_0_8 | None | None | None | None | 20.407 | 3.1004 | 1.0 | None | 1.1571 |
| subject_a_front | baseline_only | 1.0 | 1.0 | 1.0 | 0.0 | 6.608 | 1.0 | 0.0 | 0.0 | 0.309 |
| subject_a_front | full_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 21.387 | 3.2365 | 1.0 | 0.0 | 1.0 |
| subject_a_front | zero_detection_fallback_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 6.027 | 0.9121 | 0.0 | 0.0 | 0.2818 |
| subject_a_front | confidence_fallback_lt_0_7 | 1.0 | 1.0 | 1.0 | 0.0 | 5.897 | 0.8924 | 0.0 | 0.0 | 0.2757 |
| subject_a_front | confidence_fallback_lt_0_75 | 1.0 | 1.0 | 1.0 | 0.0 | 6.653 | 1.0068 | 0.0 | 0.0 | 0.3111 |
| subject_a_front | confidence_fallback_lt_0_8 | 1.0 | 1.0 | 1.0 | 0.0 | 6.526 | 0.9876 | 0.0 | 0.0 | 0.3051 |
| subject_a_side | baseline_only | 1.0 | 0.5667 | 0.7234 | 0.0 | 7.057 | 1.0 | 0.0 | -0.4 | 0.3703 |
| subject_a_side | full_1_5x | 1.0 | 0.9667 | 0.9831 | 0.4 | 19.059 | 2.7007 | 1.0 | 0.0 | 1.0 |
| subject_a_side | zero_detection_fallback_1_5x | 1.0 | 0.9667 | 0.9831 | 0.4 | 11.197 | 1.5867 | 0.4333 | 0.0 | 0.5875 |
| subject_a_side | confidence_fallback_lt_0_7 | 1.0 | 0.9667 | 0.9831 | 0.4 | 12.082 | 1.7121 | 0.5333 | 0.0 | 0.6339 |
| subject_a_side | confidence_fallback_lt_0_75 | 1.0 | 0.9667 | 0.9831 | 0.4 | 14.831 | 2.1016 | 0.6667 | 0.0 | 0.7782 |
| subject_a_side | confidence_fallback_lt_0_8 | 1.0 | 0.9667 | 0.9831 | 0.4 | 20.104 | 2.8488 | 0.8333 | 0.0 | 1.0548 |
| subject_b_front | baseline_only | 1.0 | 1.0 | 1.0 | 0.0 | 6.752 | 1.0 | 0.0 | 0.0 | 0.3757 |
| subject_b_front | full_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 17.973 | 2.6619 | 1.0 | 0.0 | 1.0 |
| subject_b_front | zero_detection_fallback_1_5x | 1.0 | 1.0 | 1.0 | 0.0 | 5.671 | 0.8399 | 0.0 | 0.0 | 0.3155 |
| subject_b_front | confidence_fallback_lt_0_7 | 1.0 | 1.0 | 1.0 | 0.0 | 5.762 | 0.8534 | 0.0 | 0.0 | 0.3206 |
| subject_b_front | confidence_fallback_lt_0_75 | 1.0 | 1.0 | 1.0 | 0.0 | 5.889 | 0.8722 | 0.0 | 0.0 | 0.3277 |
| subject_b_front | confidence_fallback_lt_0_8 | 1.0 | 1.0 | 1.0 | 0.0 | 8.526 | 1.2627 | 0.0 | 0.0 | 0.4744 |

## Limitations
- Frame-presence labels only; no bounding-box GT. Localization/IoU accuracy is NOT_ASSESSABLE.
- Adjacent video frames are not independent subjects/samples; synthetic diagnostic only.
- Multi-face frames counted as present if any face detected.
- Confidence thresholds were chosen from observed TASK 03 per-frame evidence, not tuned on a real validation set.
- No production behavior/config/threshold/model changed.

## Safety
- No production detection/pipeline/config/threshold/model changes.
- No DB/schema/migrations/source media/datasets/evidence/exports/crops/embeddings modified.
- No Git write/synchronization operations performed.
