# TASK 08 — Face Detector Evaluation: Bounding-Box Ground Truth Readiness

Generated: 2026-11-23 (local, uncommitted).  
Workspace: `/Users/yps/Dev/web/atm`

## 1. Safety / scope

- Read-only inventory of existing benchmark assets, labels, code, and reports. No production CV pipeline changes.
- No model/dataset downloads, no dependency installs, no prohibited scripts, no service restarts.
- No protected runtime data/DB/uploads/evidence/existing synthetic videos modified. No new synthetic videos generated.
- No automatic labels treated as ground truth. No manual frame annotation performed in this task.
- **Explicit confirmation: NO Git write/add/commit/push/pull/fetch/sync/branch/tag/reset/rebase/cherry-pick or remote/GitHub operation was performed. GitHub remains untouched.**

## 2. Inventory of existing authorized benchmark assets

### Synthetic clips (authorized, existing)
Source: `data/datasets/synthetic/cv/manifest.json`, `README.txt` ("procedurally generated fictional assets; no real people").

| clip_id | file | frames | fps | WxH | manifest label type | condition intent |
|---|---|---:|---:|---:|---|---|
| subject_a_front | subject_a_front.mp4 | 40 | 10 | 640x480 | frame-presence `SYN-A` | clear frontal single subject |
| subject_a_side | subject_a_side.mp4 | 30 | 10 | 640x480 | frame-presence `SYN-A` | side/turned pose |
| subject_b_front | subject_b_front.mp4 | 40 | 10 | 640x480 | frame-presence `SYN-B` | different frontal subject |
| multi_subject | multi_subject.mp4 | 35 | 10 | 640x480 | frame-presence `SYN-A,SYN-B` | two subjects same frame |
| challenges | challenges.mp4 | 55 | 10 | 640x480 | frame-presence `SYN-C`/`none` | blur/dark/small/occlusion + tail no-face |
| no_face | no_face.mp4 | 20 | 10 | 640x480 | empty labels `{}` | no-face negatives |

Total: 220 frames. `no_face` has empty labels; `challenges` has explicit `none` tail (40-54). Adjacent frames are visually correlated; **not independent subjects/samples**.

### Existing annotation files
- **Frame-presence labels only** in `manifest.json`. No bbox annotations, no person bbox, no occlusion/pose/size tags, no annotation IDs/confidence/ignore fields.
- No `*annotation*`, `*ground_truth*`, or bbox label files found in repo outside code names.

### Existing detector benchmark outputs (reports/ps04cctv-audit)
- `CV-BASELINE-BENCHMARK-20261123T114054Z.*` (Task 02)
- `YUNET-RECALL-EXPERIMENT-20261123T115642Z.*` (Task 03)
- `YUNET-FALLBACK-EXPERIMENT-20261123T120401Z.*` (Task 04)
- `YUNET-PERSON-GATE-EXPERIMENT-20261123T121706Z.*` (Task 05)
- `YOLOX-THRESHOLD-EXPERIMENT-20261123T122437Z.*` (Task 06)
- Task 07 feasibility/readiness/matrix/license reports.

### Existing evaluation utilities
- `backend/app/cv/baseline_benchmark.py`: frame-presence matching via `_label_set/_is_positive_label`, ranking metrics, NOT_ASSESSABLE handling, provenance capture.
- `backend/app/cv/face_detection_experiments.py`: scale/dedupe helpers, `bbox` as `xywh` in original coords, IoU dedupe.
- `backend/app/cv/face_detector_interface.py` (Task 07): isolated normalized detection adapter contract.
- No existing bbox GT loader/scorer/IoU TP-FP-FN evaluator for ground-truth files.

## 3. Can existing clips support bbox-level GT annotation?

**Yes, with constraints.** They are authorized local synthetic assets, already used for CV experiments, with stable frame counts and known conditions. They can support *proposed* bbox annotation, but:
- **No bbox GT exists today.** Any bbox evaluation is currently **NOT_ASSESSABLE**.
- Synthetic/procedural faces may not represent real CCTV distribution; bbox GT here would validate detector mechanics on this synthetic set only.
- Adjacent frames are redundant/correlated; annotation should be sampled, not every frame by default.
- `multi_subject` and `challenges` need careful per-face identity/ignore rules; occluded/no-face boundaries must be explicit.
- Creating bbox GT requires human annotation effort and QA; **not started**.

## 4. Ground-truth annotation schema proposal

Proposed file: `reports/ps04cctv-audit/annotations/face_bbox_ground_truth.v1.json` (not created; proposal only). Coordinate format: **`xywh_pixels_top_left`** in original frame pixel space.

### Top-level
```json
{
  "schema_version": "1.0-draft",
  "annotation_type": "face_bbox_ground_truth",
  "dataset_id": "synthetic-cv",
  "created_at": "ISO-8601",
  "annotator": "id-or-name",
  "annotation_tool": "name/version",
  "source_manifest": "data/datasets/synthetic/cv/manifest.json",
  "notes": "synthetic only; no real people",
  "clips": [ ... ]
}
```

### Clip / frame / face object
- Clip: `clip_id`, `file`, `frame_count`, `width`, `height`, `fps`, `frames[]`.
- Frame: `frame_number` (0-based), `timestamp_ms` (optional), `image_sha256` (optional), `faces[]`.
- Face annotation:
  - `annotation_id` (unique globally)
  - `subject_label` (`SYN-A|SYN-B|SYN-C|unknown|none`; `none` only for explicit no-face frame records if used)
  - `bbox`: `[x,y,w,h]` float/int pixels, top-left origin
  - `visibility`: `visible|partial|occluded|unknown`
  - `pose`: `frontal|angled|profile|back|unknown`
  - `face_size`: `small|medium|large|unknown` (rule-based by bbox area or shortest side; document rule)
  - `difficulty`: `easy|medium|hard|ignore`
  - `ignore`: bool (for ambiguous/unannotatable/difficult regions excluded from FP/FN)
  - `annotator_confidence`: 0..1
  - `person_bbox` (optional): `[x,y,w,h]` or null; only if annotated
  - `notes`: optional

### Validation rules
- clip/frame must exist in manifest; frame_number within range; unique annotation IDs; no duplicate face entries for same physical face unless explicitly justified.
- bbox inside frame bounds; w/h > 0.
- `ignore=true` or `difficulty=ignore` excluded from FN and matching predictions excluded from FP (standard difficult-ignore handling), reported separately.
- No-face clips/frames must be representable as empty `faces[]`.
- Any auto-proposed box must be marked `proposal_only=true` and **never** used as GT until human-confirmed.

## 5. Bbox evaluation metrics & methodology

| Metric | Status now | Method when GT exists |
|---|---|---|
| TP/FP/FN at IoU threshold | NOT_ASSESSABLE | Greedy IoU matching per frame; default 0.5, also report 0.3/0.75 sensitivity |
| Precision/Recall/F1 | NOT_ASSESSABLE | From TP/FP/FN; per-clip and aggregate with frame counts reported |
| IoU distribution (matched) | NOT_ASSESSABLE | mean/median/p5/p95 of matched IoUs |
| Small/medium/large performance | NOT_ASSESSABLE | stratify by face area/size label |
| Pose/occlusion stratified | NOT_ASSESSABLE | stratify by pose/visibility/difficulty |
| False positives on no-face clips | Partially ready now by frame-presence; bbox-level NOT_ASSESSABLE | count preds on frames/clips with zero GT faces |
| Latency per frame | Ready (existing runners) | mean/p50/p95; include model load separately |
| Detection/confidence distribution | Ready | histogram/summary by GT-matched vs FP |
| mAP/AP | NOT_ASSESSABLE until GT | optional later; not required first pass |

Methodology constraints: same GT file and scorer for all detectors; fixed frame sampling; report detector version/model hash/config; adjacent frames not independent; synthetic-only caveat.

## 6. Annotation effort assessment (proposed, NOT completed)

### Minimum useful subset (recommended first pass)
Prioritize coverage over redundancy: sample every 5th frame, plus all condition transitions and all no-face/challenge boundary frames.

| clip | total | proposed sample | rationale |
|---|---:|---:|---|
| subject_a_front | 40 | 8 | frontal baseline |
| subject_a_side | 30 | 6 | side pose |
| subject_b_front | 40 | 8 | second identity frontal |
| multi_subject | 35 | 7 | multi-face |
| challenges | 55 | 15 | blur/dark/small/occlusion/no-face tail; include all condition boundaries |
| no_face | 20 | 4 | explicit negatives |
| **Total** | **220** | **~48 frames** | minimum viable stratified coverage |

Estimated effort: ~2-4 min/frame for single-face simple frames, ~5-8 min/frame for multi-face/occluded/challenge frames; ~3-5 hours for 48-frame pass including QA. **Estimate only; no annotation completed.**

### Full-set option (later)
All 220 frames only if first-pass shows ambiguity or if publication-grade bbox metrics needed. Higher redundancy/cost.

## 7. Isolated validator/spec created (justified, no GT fabrication)

Created local-only artifacts:
- `backend/app/cv/bbox_ground_truth.py` — schema constants, document/bbox validator, IoU, greedy matcher, summary evaluator. Handles ignore/difficult faces; does not generate GT.
- `backend/tests/test_bbox_ground_truth.py` — unit tests for valid doc, invalid bbox/frame bounds, duplicate annotation IDs, IoU/matching/ignore behavior.

Not created: annotation UI (not necessary; JSON schema + validator sufficient). No modifications to original videos/assets.

## 8. Benchmark comparison requirements

For YuNet vs future SCRFD/any detector:
- **Same GT file**, same schema version, same clip/frame subset, same coordinate convention (`xywh_pixels_top_left`).
- **Same scorer**: identical IoU thresholds, matching rule, ignore handling, stratification rules.
- **Same provenance**: model name/variant/version/source/SHA256, runtime/backend, device, input size, thresholds/config, timestamp, code revision.
- **Same reporting**: per-clip, per-condition, aggregate; FP on no-face; latency mean/p50/p95; confidence distributions; unsupported metrics `NOT_ASSESSABLE`.
- **No production default changes** during benchmarking; isolated adapters/runners only.

## 9. Tests run

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest backend/tests/test_bbox_ground_truth.py backend/tests/test_face_detector_interface.py -q --tb=short` → **8 passed**.

## 10. Limitations

- No bbox ground truth exists; bbox metrics remain NOT_ASSESSABLE until human annotation + QA.
- Synthetic-only dataset; cannot support real CCTV/R4C claims.
- Frame-presence labels in manifest are coarse; `challenges` has mixed conditions without per-frame condition tags.
- Small sample, correlated adjacent frames; not independent subjects.
- Person bbox GT absent; person/track metrics remain NOT_ASSESSABLE.

## 11. Exact next step requiring approval

**Approve creation of a human-annotated bbox GT pilot for the ~48-frame minimum subset only** (no auto-labels as GT, no video modification). This requires: (a) explicit approval to create a new annotation JSON file under `reports/ps04cctv-audit/annotations/` or agreed path, (b) decision on annotation workflow/tool (manual JSON, CVAT/Label Studio export converted offline, or minimal local helper) — no dependency/install/download without approval, (c) QA/review pass before any detector comparison uses it.
