# ATM Sentinel — Project Status

## Completed milestones

### M0 — Foundation: complete
- Inspected current directory (`/Users/yps/dev/web/atm`, empty) and target (`/Users/yps/Dev/projects/atm-sentinel`, empty).
- Verified Python 3.12.16 in the project `.venv`, Node 26.12.1, and npm 11.20.0.
- FFmpeg/ffprobe were missing; installed via Homebrew after explanation.
- Created isolated project, local Git repo (no remote, no commits), plan, status, and README.
- Installed dependencies into project-local `.venv` and `frontend/node_modules`.

### M1 — Backend P0: complete
- FastAPI service on `127.0.0.1:8000`; optional local passphrase session.
- SQLite schema with controlled initialization and audit events.
- Safe uploads: allowlisted extensions, magic bytes, size limit, safe internal names.
- ffprobe metadata, full-decode integrity check, local FFmpeg normalization endpoint.
- Timestamp alignment with offsets, video-start/reference anchoring, timezone handling, warnings, and explicit preview.
- Incremental frame extraction with coarse/fine sampling, cancellation, real progress, and manual capture.
- Explainable quality metrics with warning breakdown and documented limitations.
- Evidence selection, notes, manual clip links, PDF export, JSON manifest, report/PDF hashes, and selected-frames ZIP.

### M2 — Frontend P0: complete
- React + Vite + TypeScript + Tailwind CSS v4 with shadcn-style UI primitives and Lucide icons.
- Dark forensic design system, desktop-first responsive layout.
- All seven screens: Command Center, Cases, New Investigation, Video Workspace, Evidence Gallery, Case Comparison, Evidence Export.
- All API-backed actions are live; no placeholder buttons.

### M3 — Tests and verification: complete
- Pytest: the latest acceptance run executed 215 passed tests with the prohibited synthetic-asset generator test deselected, covering validation, uploads, container formats, metadata, timestamps, windows, quality metrics, hashing, extraction, manual capture, export, audit, CV runs, candidate search, human review, provenance, and CV export.
- Vitest: the latest acceptance run executed 65 passed tests across 9 files.
- TypeScript typecheck and production build pass.
- See `reports/acceptance/acceptance.md` and `reports/acceptance/acceptance.json` for exact commands, statuses, limits, scope, and remaining gaps.

### M4 — Demo hardening: partial
- Synthetic demo video generator implemented (`scripts/generate_demo_video.py`).
- Contact-sheet PDF export implemented for selected frames.
- Tags on cases/videos and global metadata/tag search implemented.
- Face detection was added in later CV stages using the approved local YuNet/YOLOX models; it never performs identity recognition.

## Current milestone

Stage 12 local audit, explicit CV-reference export, association-limitation copy, local container-format acceptance, and isolated synthetic acceptance are complete. Real-device, R4C, RBAC, tamper-proof-audit, and real-world accuracy work remains out of scope for this status.

## Stage 12 PS04CCTV acceptance audit

No literal PS04CCTV checklist exists in this repository. The audit mapped the 11 supplied requirement areas to implementation, tests, and user-facing limitation copy.

| Requirement area | Classification | Evidence |
| --- | --- | --- |
| Local case and evidence workflow | Verified locally | Guided workflow, jobs, frames, evidence selection, and full backend/frontend suites |
| Transaction/clock alignment | Verified locally | `backend/app/services/timestamp.py`, alignment preview, `test_timestamps.py`, `test_cv_alignment.py` |
| Frame extraction and manual capture | Verified locally | `backend/app/services/extraction.py`, workspace UI, `test_pipeline.py` |
| Explainable image-quality scoring | Verified locally | `backend/app/services/quality.py`, CV quality module, quality UI, `test_quality.py` |
| Transaction metadata | Verified locally | Case transaction schema/API/UI and pipeline tests |
| PDF/manifest/ZIP/contact-sheet export | Verified locally | Export service/router and export/CV-export tests |
| SHA-256 integrity and audit history | Verified locally | Upload/frame/report hashing, full-decode check, append-only SQLite audit events |
| Local-only demo safety | Verified locally | Loopback binding, optional passphrase, synthetic demo badges, no cloud/GPU/telemetry |
| Video format compatibility | Partial | MP4/AVI/MOV/MKV local acceptance; real DVR/NVR exports and vendor formats unverified |
| CV candidate search and human review | Implemented but not fully verified | Case-scoped candidate API, persistent runs/reviews, tests, and isolated 12-clip synthetic scenario with stubbed CV inference |
| CV/transaction/operator association limitation | Verified locally | Explicit API/UI/export copy and regression tests rejecting identity or ATM-operator association claims |

Classification summary for this 11-area mapping: **Verified locally: 9**; implemented but not fully verified: 1; partial: 1; not implemented: 0. A separate 15-area PS04CCTV mapping records RBAC and tamper-proof/WORM audit as not implemented.

Caveats: `Verified locally` means implementation plus focused local synthetic tests, not real CCTV/R4C validation. The app has one global local session and no per-user/per-case RBAC; audit events are append-only in SQLite, not tamper-proof/WORM storage or a certified chain of custody; browser-level smoke automation was not executed; no real-world benchmark or identity-accuracy claims were introduced.

## Remaining tasks

1. Validate real DVR/NVR exports and vendor-specific formats with approved samples.
2. Run R4C and real-world detection, face-robustness, and identity-accuracy validation under an approved protocol.
3. Add per-user/per-case RBAC and tamper-proof/WORM audit storage if those requirements apply.
4. Optional future work: richer timeline visualization and browser-level smoke automation with Playwright.

## Known bugs

- No functional bugs known.
- Pytest emits one upstream `StarletteDeprecationWarning` about `httpx`/`starlette.testclient`; tests pass.

## Test results

Latest acceptance run: `reports/acceptance/acceptance.md` and `reports/acceptance/acceptance.json`.

Historical baseline before the acceptance runner:

```text
.venv/bin/python -m pytest backend/tests -q
216 passed, 1 warning in 31.16s

npm run typecheck
passed

npm test -- --run
Test Files 9 passed (9)
Tests 62 passed (62)

npm run build
✓ built in 1.09s
```

Historical end-to-end manual verification with the synthetic clip:
- Upload: 382,305-byte MP4, 640x480, 10 fps, 12 s, integrity verified.
- Alignment: +2.0 min offset, transaction at video 6.0 s, window 3.0–9.0 s.
- Processing job: completed, 11 frames extracted (coarse + fine).
- Evidence: one frame selected with note/reason.
- Export: PDF (starts `%PDF`), JSON manifest, matching report/PDF hashes, ZIP archive, contact-sheet PDF.
- Tags: demo case tagged `atm-01,demo`; demo video tagged `camera-01,synthetic`; `/api/search` returns both for tag queries.
- CV export: selected observations/candidates are validated against case/run/review/model provenance, recorded in the JSON manifest and PDF section, and labelled as review context rather than identity or ATM-operator association.

## Next steps

Run `./scripts/dev.sh`, open `http://127.0.0.1:5173`, and follow the guided investigation workflow using the synthetic demo values in `README.md`.
