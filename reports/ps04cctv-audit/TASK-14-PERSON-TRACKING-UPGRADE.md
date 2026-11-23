# TASK 14 — Person Tracking Upgrade & Association Benchmark

## Scope
- Isolated, local, reproducible ByteTrack-inspired person tracker experiment.
- No production behavior changes: `backend/app/cv/tracking.py` and `backend/app/cv/pipeline.py` unchanged.
- No Git/GitHub write/sync ops, no service restarts, no protected data modification, no model/package downloads.

## Implementation (isolated)
- `backend/app/cv/bytetrack_tracker.py`: `ByteTrackInspiredTracker`
  - Two-stage association: high-confidence detections matched first; remaining tracks matched with low-confidence detections.
  - Matching: IoU + centroid-distance motion consistency, short-gap velocity prediction.
  - Configurable: `high_conf_threshold`, `low_conf_threshold`, `match_iou_threshold`, `second_match_iou_threshold`, `max_centroid_distance`, `max_misses`, `max_time_gap_seconds`, `min_hits`.
  - Lifecycle: `tentative/active/lost/removed`.
  - Stable clip-local IDs: monotonic, never reused within tracker instance.
  - Duplicate active ID guard in frame output.
  - Invalid/empty bbox/conf handling; original detection coords preserved.
- Not wired into production. `SimpleTracker` remains default.

## Tests
- `backend/tests/test_bytetrack_tracker.py` (8 passed)
  - two-stage high/low association preserves ID
  - max-misses/time-gap lifecycle
  - stable clip-local IDs/no reuse
  - no duplicate active IDs
  - invalid/empty detection handling
  - multi-person crossing deterministic/no ID explosion
  - original coordinates preserved
  - SimpleTracker compatibility shape

## Benchmark
- Script: `scripts/benchmark_person_trackers.py`
- JSON: `reports/ps04cctv-audit/TASK-14-PERSON-TRACKING-BENCHMARK.json`
- Deterministic in-memory sequences (not ground truth): linear, occlusion-low-conf, crossing-two-persons, temporary absence.
- Synthetic clip benchmark (existing local synthetic clips, YOLOX person detector, temp/isolated analysis; no crops/embeddings persisted by benchmark): `subject_a_front`, `subject_a_side`, `subject_b_front`, 30 frames each.

### Deterministic sequence summary
| Sequence | Simple unique IDs / switches / frags | ByteTrack unique IDs / switches / frags | Note |
|---|---:|---:|---|
| linear_single_person | 1 / 0 / 0 | 1 / 0 / 0 | parity |
| occlusion_low_conf | 1 / 0 / 0 | 1 / 0 / 0 | parity; low-conf matched in second stage |
| crossing_two_persons | 4 / 0 / 0 | 4 / 0 / 0 | deterministic, no duplicate IDs; crossing stress proxy can swap identities |
| temporary_absence | 2 / 0 / 1 | 2 / 0 / 1 | parity |

### Synthetic clip summary (proxy metrics)
| Clip | Simple IDs/switches/frags/runtime ms | ByteTrack IDs/switches/frags/runtime ms |
|---|---:|---:|
| subject_a_front | 0 / 0 / 0 / 0.133 | 0 / 0 / 0 / 0.192 |
| subject_a_side | 0 / 0 / 0 / 0.099 | 0 / 0 / 0 / 0.140 |
| subject_b_front | 0 / 0 / 0 / 0.099 | 0 / 0 / 0 / 0.143 |

## ATM Integration Compatibility (code inspection, no production integration)
- `transaction_person_associations` requires `track_id`, timestamps, zone overlap, provenance; tracker output supplies `track_id` and bbox continuity compatible with existing observation shape.
- `cv_person_observations` stores per-frame track observations; ByteTrack IDs remain clip-local/stable and can be consumed by same schema.
- No DB/schema/API changes made. No end-to-end ATM persistence run performed because production integration untouched and no approved integration test harness change was required.

## Limitations / NOT_ASSESSABLE
- IDF1/MOTA/HOTA/annotated ID switches/fragmentations: **NOT_ASSESSABLE** (no person/track ground truth).
- Real CCTV/person crossing/occlusion generalization: **NOT_ASSESSABLE**.
- Synthetic clips had zero YOLOX person detections in selected 30-frame windows; clip benchmark measures tracker overhead/stability under empty detections, not identity quality. This is a measurement limitation, not a production claim.
- ByteTrack crossing sequence shows identity swap under symmetric overlap; deterministic but not ground-truth-correct. Needs annotated multi-person CCTV/person GT before production consideration.

## Recommendation
- **Do not integrate into production yet.** Keep as isolated experiment.
- Next prerequisites before integration: person/track ground truth (bbox+ID), real CCTV crossing/occlusion clips, ATM association regression on annotated sequences, and threshold tuning against measured ID metrics.
