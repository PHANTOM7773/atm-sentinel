# TASK 09 — Human Bounding-Box Annotation Pilot (48 Frames)

Generated: 2026-11-23 (local, uncommitted).  
Workspace: `/Users/yps/Dev/web/atm`

## Safety / scope
- Approved limited scope only: ~48-frame human bbox GT pilot workspace, derived frames under `reports/ps04cctv-audit/annotations/`, minimal offline annotation tool, schema/template/validator/tests/instructions.
- **No production CV pipeline changes. No model/dataset downloads. No dependency installs. No prohibited scripts. No DB/runtime/uploads/evidence modifications. No services started/restarted.**
- Original videos/labels untouched. No auto ground-truth generation. No detector benchmarking/download.
- **Explicit confirmation: NO Git write/add/commit/push/pull/fetch/sync/branch/tag/reset/rebase/cherry-pick or remote/GitHub operation was performed. GitHub remains untouched.**

## Phase 1 — Frame selection (48 frames, deterministic)

Selection manifest: `reports/ps04cctv-audit/annotations/selected-frames-manifest.json` (total 48).

| clip_id | selected frame_index | timestamps ms | target conditions |
|---|---|---|---|
| subject_a_front | 0,5,10,15,20,25,30,39 | 0,500,1000,1500,2000,2500,3000,3900 | front-facing/clear |
| subject_a_side | 0,5,10,15,20,29 | 0,500,1000,1500,2000,2900 | side-pose |
| subject_b_front | 0,5,10,15,20,25,30,39 | 0..3900 | front-facing different subject |
| multi_subject | 0,5,10,15,20,25,34 | 0..3400 | multiple subjects |
| challenges | 0,5,10,15,20,25,29,30,35,39,40,45,50,54 | 0..5400 | challenging/blur/dark/small-face candidate/occlusion/boundary/no-face tail |
| no_face | 0,5,10,15,19 | 0..1900 | no-face negatives |

Unavailable/limited conditions (not fabricated): real CCTV compression/noise not represented; extreme back-of-head/profile may be limited (annotate observed pose as `unknown/profile` only if actually present); crowd density >2 subjects not represented.

## Phase 2 — Derived frame extraction

- Script: `scripts/select_annotation_pilot_frames.py` (deterministic; refuses overwrite unless `--force`).
- Output: 48 PNGs in `reports/ps04cctv-audit/annotations/frames/`, named `<clip_id>__frame_<000000>.png`.
- Preserved original resolution 640x480; recorded clip/frame/timestamp/source path/derived SHA256 in selection manifest. No enhancement/crop/resize. Original videos untouched.

## Phase 3 — Offline annotation tool

Path: `reports/ps04cctv-audit/annotations/annotation-tool/` (`index.html`, `styles.css`, `app.js`).

Capabilities: load selection manifest, view frame, mouse drag draw bbox, select/edit/delete box, multiple boxes/frame, mark no-face, ignore/difficult, fields (visibility/pose/face_size/blur/illumination/confidence/notes), next/prev, shows clip/frame/timestamp/source, save/export JSON, load existing annotation JSON, status Not annotated/Annotated/Needs review. No uploads, no detector auto-suggestions. BBoxes saved in original frame pixel coords (`xywh_pixels_top_left`).

## Phase 4 — Annotation contract

- Template: `reports/ps04cctv-audit/annotations/annotation-template.json`
- Human output (separate): annotator exports `human-annotations.json` (not created/filled by this task).
- Schema: `schema_version=1.0-pilot`, `annotation_type=face_bbox_ground_truth_pilot`, `bbox_format=xywh_pixels_top_left`, original image coords. Per-face: stable `annotation_id`, bbox, visibility (`visible|partially_occluded|heavily_occluded`), pose (`front|slight_profile|profile|unknown`), face_size (`small|medium|large`), blur (`none|mild|severe`), illumination (`normal|dark|overexposed`), annotation_confidence (`high|medium|low`), `ignore_difficult`, notes. Frame: clip_id, frame_index, timestamp_ms, status, no_face, frame_notes, faces[].
- Validator/helpers: `backend/app/cv/annotation_pilot.py`, CLI `scripts/validate_annotation_pilot.py`.

## Phase 5 — QA and validation

Validator checks: manifest clip existence, frame bounds, timestamp consistency warning, bbox positive/in-bounds, duplicate annotation IDs/frame entries, invalid labels, no-face with boxes, selection coverage, completeness summary.  
**Validation pass != benchmark-ready.** Human QA required; use `reports/ps04cctv-audit/annotations/QA-REPORT-TEMPLATE.md`. QA status: NOT_REVIEWED/REVIEW_REQUIRED/QA_PASSED.

## Phase 6 — Files created

- `reports/ps04cctv-audit/TASK-09-ANNOTATION-PILOT.md`
- `reports/ps04cctv-audit/annotations/selected-frames-manifest.json`
- `reports/ps04cctv-audit/annotations/frames/*.png` (48 derived frames)
- `reports/ps04cctv-audit/annotations/annotation-tool/index.html`
- `reports/ps04cctv-audit/annotations/annotation-tool/styles.css`
- `reports/ps04cctv-audit/annotations/annotation-tool/app.js`
- `reports/ps04cctv-audit/annotations/annotation-template.json`
- `reports/ps04cctv-audit/annotations/README-ANNOTATION-INSTRUCTIONS.md`
- `reports/ps04cctv-audit/annotations/QA-REPORT-TEMPLATE.md`
- `reports/ps04cctv-audit/annotations/qa-report-template.generated.json` (validator smoke output)
- `backend/app/cv/annotation_pilot.py`
- `backend/tests/test_annotation_pilot.py`
- `scripts/select_annotation_pilot_frames.py`
- `scripts/validate_annotation_pilot.py`

## How to open/use tool
1. `cd /Users/yps/Dev/web/atm && .venv/bin/python -m http.server 8765`
2. Open `http://127.0.0.1:8765/reports/ps04cctv-audit/annotations/annotation-tool/`
3. Load `reports/ps04cctv-audit/annotations/selected-frames-manifest.json`
4. Annotate manually; export `human-annotations.json`; resume by loading manifest + exported JSON.
5. Validate: `.venv/bin/python scripts/validate_annotation_pilot.py --annotations <human-annotations.json> --selection reports/ps04cctv-audit/annotations/selected-frames-manifest.json --manifest data/datasets/synthetic/cv/manifest.json --out reports/ps04cctv-audit/annotations/qa-report.json`

## Tests run
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest backend/tests/test_annotation_pilot.py backend/tests/test_bbox_ground_truth.py -q --tb=short` → **9 passed**.
- Validator smoke on template: exit 0, `REVIEW_REQUIRED`, `benchmark_ready=false`, 48 missing selected frames (expected for empty template).

## Remaining manual work (not done)
- Human annotates 48 frames in tool and exports `human-annotations.json`.
- Human QA reviews all frames/boxes/labels; completes QA report; marks QA_PASSED only when justified.
- After QA approval: benchmark comparison may proceed using same GT/scorer; no detector download/benchmark started now.

## Limitations
- Synthetic-only; not real CCTV/R4C. Adjacent-frame correlation; not independent subjects. Some condition categories may be limited by available clips; annotate observed reality, do not fabricate.
- Tool uses browser canvas UI; no new dependencies, but requires local static server/browser. No auto-detection assistance by design.
