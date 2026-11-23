# TASK 09 Human Annotation Instructions

## Scope
- Annotate only the selected ~48 derived frames in `reports/ps04cctv-audit/annotations/frames/`.
- Human annotation required. **Do not use detector output as ground truth.**
- Original videos/labels are read-only; do not alter them.

## Open the tool (offline)
1. From workspace root run a simple local static server (no install needed; Python already present):
   `cd /Users/yps/Dev/web/atm && .venv/bin/python -m http.server 8765`
2. Open `http://127.0.0.1:8765/reports/ps04cctv-audit/annotations/annotation-tool/`
3. Click **Selection manifest** and load `reports/ps04cctv-audit/annotations/selected-frames-manifest.json`.
4. Draw boxes and set labels. Export JSON often.
5. To resume, load selection manifest first, then **Load annotation JSON**.

> If you prefer not to run a server, some browsers restrict local file loading; the local server is the supported offline path.

## Annotation rules
- BBox format: `[x,y,w,h]` in **original frame pixel coordinates** (xywh, top-left). The tool stores original coords even when image is scaled.
- Draw one box per visible human face. Multiple faces allowed.
- `No visible face`: check box and set status `annotated`; faces must be empty.
- `Ignore/difficult`: use for ambiguous/unannotatable faces; still draw box if face location is identifiable, mark ignore+difficult and explain in notes.
- Status: `not_annotated`, `annotated`, `needs_review`.
- Do not annotate from memory; flag uncertain cases `needs_review` and low confidence.

## Required per-face fields
- Visibility: `visible | partially_occluded | heavily_occluded`
- Pose: `front | slight_profile | profile | unknown`
- Face size: `small | medium | large`
- Blur: `none | mild | severe`
- Illumination: `normal | dark | overexposed`
- Confidence: `high | medium | low`
- Ignore/difficult: bool
- Notes: optional

## QA
- Run validator: `.venv/bin/python scripts/validate_annotation_pilot.py --annotations <exported.json> --selection reports/ps04cctv-audit/annotations/selected-frames-manifest.json --manifest data/datasets/synthetic/cv/manifest.json --out reports/ps04cctv-audit/annotations/qa-report.json`
- Validator pass is **not** benchmark-ready. Human QA required; complete `QA-REPORT-TEMPLATE.md` and mark `QA_PASSED` only after review.

## Safety
- No uploads. No Git operations. Do not move files outside annotations dir. Do not modify original videos.
