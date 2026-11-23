# TASK 15 — ATM Sentinel AI Image Enhancement

## Scope
- Local, isolated implementation for TASK 15. No production CV pipeline integration, no service restarts, no protected data modification, no model/package downloads/installs, no Git write/sync operations.
- Original evidence unchanged; enhanced outputs are derived artifacts only.

## 1) Existing workflow inspection (key points)
- Face crop generation/storage: `backend/app/cv/crop.py` (`crop_face`, `save_crop`, `prune_crops`), `backend/app/cv/pipeline.py` saves crops under `data/cv/crops/<case>/<video>/frame_XXXXXX/<sample>.jpg` when `save_crops=True`; path stored as data-relative.
- Quality scoring: `backend/app/cv/quality.py` `analyze_face_quality` (sharpness/brightness/contrast/face size/pose/occlusion heuristics; usability only, not identity).
- Evidence/export: `backend/app/services/export.py` builds PDF/manifest with CV selections; no crop-image embedding in CV section; `backend/app/db.py` has `evidence_items/exports/audit_events`.
- Frontend review: `frontend/src/pages/CvRuns.tsx` (`CvObservationCard`, `CvCandidateCard`), `frontend/src/lib/api.ts` `cvApi.cropUrl`, `frontend/src/lib/types.ts` `CvCropSummary`.
- Crop serving: `backend/app/routers/cv.py` GET `/api/cv/runs/{cv_run_id}/observations/{observation_id}/crop`; `backend/app/services/cv_integration.py` `resolve_observation_crop` enforces scope/opaque ID/retrievable JPEG.
- Dependencies: `backend/requirements.txt` has `opencv-python-headless>=4.9`; no torch/gfpgan/realesrgan/codeformer/basicsr/facexlib installed.

## 2) OpenCV enhancement (implemented)
- Module: `backend/app/cv/image_enhancement.py`
  - Operations: CLAHE (LAB-L), gamma correction, brightness/contrast (`convertScaleAbs`), denoise (`fastNlMeansDenoisingColored`), conservative unsharp mask, upscale (OpenCV interpolation: nearest/linear/cubic/area/lanczos4).
  - Presets: `general_enhancement`, `low_light_correction`, `low_contrast_correction`, `noise_reduction`.
  - Never overwrites originals; derived outputs written separately.
  - Records SHA256 for original/enhanced, method/version, params, dims, processing ms, warnings, metadata JSON.
  - Invalid/unreadable images raise `CVError`; router/service map to controlled errors.
- Default derived output root: `reports/ps04cctv-audit/task15-enhancements/` (isolated audit artifact path).

## 3) AI restoration model evaluation (no installs/downloads)
- Adapters/status: `backend/app/cv/ai_restoration_adapters.py`
- Checked local packages: `gfpgan/realesrgan/codeformer/basicsr/facexlib/torch/torchvision` = all missing.
- Readiness: `any_ready=false`; no real AI sample run possible.

| Model | Code package | Code license (verify upstream/tag) | Weight license/provenance | Installed | Weights available | Ready | Blockers |
|---|---|---|---|---:|---:|---:|---|
| GFPGAN | gfpgan | Apache-2.0 (verify; third-party components may vary) | Must be verified separately; do not assume code license covers weights | No | No | No | missing package/weights |
| Real-ESRGAN | realesrgan | BSD-3-Clause (verify) | Must be verified separately; some weights may have restrictions | No | No | No | missing package/weights |
| CodeFormer | codeformer | S-Lab License 1.0/upstream terms (verify; non-commercial restrictions may apply) | Must be verified separately | No | No | No | missing package/weights |

Exact install requirements (approval required before any install/download):
- GFPGAN: `pip install gfpgan basicsr facexlib torch torchvision`; provide approved local weights (e.g. `GFPGANv1.4.pth`); verify weight license/provenance.
- Real-ESRGAN: `pip install realesrgan basicsr facexlib torch torchvision`; provide approved local weights; verify license/provenance.
- CodeFormer: install approved CodeFormer runtime/deps (torch/basicsr/facexlib etc.); provide approved local `codeformer.pth` + required facelib weights; verify code/weight licenses.

## 4) Frontend preview (implemented)
- Component: `frontend/src/components/CvCropEnhancementPanel.tsx`
- Integrated into `frontend/src/pages/CvRuns.tsx` observation crop card.
- Features: original crop, enhanced crop, before/after side-by-side, preset selector, Enhance action, processing status/errors, preset/params summary, dims, processing ms, original/enhanced SHA256, method/version, warnings.
- Clear label: “AI-enhanced derived image - not original evidence”. Also states original unchanged and not used for matching/embeddings.
- Uses actual generated output via API; no placeholder images.

## 5) Backend API/service (isolated, no production CV integration)
- Service: `backend/app/services/image_enhancement.py` - resolves original crop via existing scoped `resolve_observation_crop`; writes derived image+metadata; deterministic per case/run/observation/crop/preset.
- Router: `backend/app/routers/cv_enhancement.py`
  - `GET /api/cv/enhancement/presets`
  - `POST /api/cv/enhancement/face-crop`
  - `GET /api/cv/enhancement/face-crop/meta`
  - `GET /api/cv/enhancement/face-crop/image`
- Wired in `backend/app/main.py` via `app.include_router(cv_enhancement.router)` (isolated endpoint; no change to CV analysis pipeline/embedding/matching behavior).

## 6) Forensic integrity controls
- Originals never overwritten; derived files stored separately.
- SHA256 recorded for original and enhanced images in metadata/response.
- Provenance recorded: case/run/observation/crop IDs, sample/frame/timestamp/bbox/confidence/quality snapshot, method/version, preset/params, warnings.
- UI/API labels enhanced output as derived; not original evidence.
- No silent use in face matching: SFace embeddings and CV pipeline unchanged; enhancement endpoints do not write embeddings or alter observations.
- No claim that AI/enhancement restores genuine evidence.

## 7) Tests
- `backend/tests/test_image_enhancement.py` — 5 passed (presets, dark enhancement effect, derived output+metadata+original hash unchanged, invalid image graceful failure, unknown preset rejected).
- `backend/tests/test_ai_restoration_adapters.py` — 1 passed (all AI adapters blocked/unready, requirements reported).
- Focused: `6 passed`.
- Guarded regression: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --tb=no -k 'not test_synthetic_generator_writes_labelled_clips'` → `315 passed, 1 deselected, 1 warning`.

## 8) Actual demo runs on existing authorized synthetic face crops
Source crops from existing `data/cv/crops/...` (synthetic-derived local crops; originals untouched).

| Sample | Input | Preset | Output | Orig dims | Enh dims | ms | Orig SHA256 | Enh SHA256 |
|---|---|---|---|---:|---:|---:|---|---|
| dark | `data/cv/crops/0053076b6d0e4b9b83f7c5558223b2a5/1e43e347ee90427188319dd1b4b09811/frame_000004/1e43e347ee90427188319dd1b4b09811-f000004-t001.jpg` | general_enhancement | `reports/ps04cctv-audit/task15-enhancements/demo/dark/general_enhancement/1e43e347ee90427188319dd1b4b09811-f000004-t001_general_enhancement_enhanced.jpg` | 249x329 | 374x494 | 162.527 | see `demo-summary.json` | see `demo-summary.json` |
| dark | same | low_light_correction | `reports/ps04cctv-audit/task15-enhancements/demo/dark/low_light_correction/..._enhanced.jpg` | 249x329 | 374x494 | 140.708 | same original | derived |
| dark | same | low_contrast_correction | `reports/ps04cctv-audit/task15-enhancements/demo/dark/low_contrast_correction/..._enhanced.jpg` | 249x329 | 374x494 | 143.330 | same original | derived |
| dark | same | noise_reduction | `reports/ps04cctv-audit/task15-enhancements/demo/dark/noise_reduction/..._enhanced.jpg` | 249x329 | 249x329 | 136.261 | same original | derived |
| blurred | same as dark-selected crop by heuristic | general_enhancement | `reports/ps04cctv-audit/task15-enhancements/demo/blurred/general_enhancement/..._enhanced.jpg` | 249x329 | 374x494 | 136.154 | see summary | derived |
| blurred | same | low_light_correction | `reports/ps04cctv-audit/task15-enhancements/demo/blurred/low_light_correction/..._enhanced.jpg` | 249x329 | 374x494 | 143.788 | same original | derived |
| blurred | same | low_contrast_correction | `reports/ps04cctv-audit/task15-enhancements/demo/blurred/low_contrast_correction/..._enhanced.jpg` | 249x329 | 374x494 | 138.526 | same original | derived |
| blurred | same | noise_reduction | `reports/ps04cctv-audit/task15-enhancements/demo/blurred/noise_reduction/..._enhanced.jpg` | 249x329 | 249x329 | 135.470 | same original | derived |
| normal | `.../frame_000007/1e43e347ee90427188319dd1b4b09811-f000007-t001.jpg` | general_enhancement | `reports/ps04cctv-audit/task15-enhancements/demo/normal/general_enhancement/..._enhanced.jpg` | 248x339 | 372x508 | 138.332 | see summary | derived |
| normal | same | low_light_correction | `reports/ps04cctv-audit/task15-enhancements/demo/normal/low_light_correction/..._enhanced.jpg` | 248x339 | 372x508 | 145.605 | same original | derived |
| normal | same | low_contrast_correction | `reports/ps04cctv-audit/task15-enhancements/demo/normal/low_contrast_correction/..._enhanced.jpg` | 248x339 | 372x508 | 140.825 | same original | derived |
| normal | same | noise_reduction | `reports/ps04cctv-audit/task15-enhancements/demo/normal/noise_reduction/..._enhanced.jpg` | 248x339 | 248x339 | 138.174 | same original | derived |

Machine-readable demo details: `reports/ps04cctv-audit/task15-enhancements/demo-summary.json`.

## 9) Failures / limitations
- AI models (GFPGAN/Real-ESRGAN/CodeFormer) **not runnable** locally: missing packages/weights; no downloads/installs performed.
- OpenCV enhancement is classical signal processing only; it cannot recover true missing identity detail and may introduce artifacts.
- Demo crop selection used simple brightness/sharpness heuristics on existing synthetic-derived crops; “dark/blurred/normal” labels are heuristic, not ground-truth quality classes.
- Frontend UI was wired but not visually browser-tested in this run (no service restart/UI automation performed). Component/type integration added; backend endpoints smoke-tested.
- Enhancement endpoint is isolated and not integrated into export/evidence packaging or DB schema; provenance is stored as sidecar JSON in audit artifact dir.
- No real CCTV validation; no identity/biometric claims.

## 10) Files added/changed (local, uncommitted)
- Added: `backend/app/cv/image_enhancement.py`, `backend/app/cv/ai_restoration_adapters.py`, `backend/app/services/image_enhancement.py`, `backend/app/routers/cv_enhancement.py`, `backend/tests/test_image_enhancement.py`, `backend/tests/test_ai_restoration_adapters.py`, `frontend/src/components/CvCropEnhancementPanel.tsx`, demo outputs under `reports/ps04cctv-audit/task15-enhancements/`.
- Changed: `backend/app/main.py` (router include), `frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`, `frontend/src/pages/CvRuns.tsx`.
- No Git write/sync operations performed.
