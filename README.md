# ATM Sentinel

**Transaction-driven CCTV evidence analysis**

ATM Sentinel is a local-only prototype for organizing ATM CCTV evidence around a transaction timestamp. It validates a video, reads metadata with ffprobe, aligns transaction and CCTV clocks, extracts frames incrementally, scores explainable image quality, tracks SHA-256 hashes, and generates a forensic evidence PDF.

> Prototype evidence organization and integrity tracking. This application does not identify people and is not legally or court certified.

## Implemented features

- Command Center with real local counts, recent cases, audit activity, and dependency status
- Case management: create, edit, archive, transactions, notes, video uploads, timeline
- Guided 7-step investigation workflow with a visible timestamp-alignment calculation
- Video Workspace: native player, custom timeline markers, metadata, live job status, manual frame capture, normalized-copy action
- Evidence Gallery: quality metrics, warnings, sorting, filtering, selection, notes, original-frame view, side-by-side comparison
- Manual cross-clip relationships with investigator rationale; local CV candidate ranking is review-only and never identity confirmation
- CV review: local face/person detection, tracking, explainable quality and pose proxies, case-scoped similarity candidates, and human review decisions
- PDF report with case, transaction, video metadata, alignment, frames, quality metrics, notes, selection history, audit events, hashes, version and timestamp; explicitly selected CV observations/candidates can be added as review context
- JSON manifest, PDF SHA-256, ZIP download of selected original frames, and contact-sheet PDF
- Tags on cases and videos, with global metadata/tag search across cases and clips
- SQLite schema with controlled initialization, versioned migration, audit events, export history, and local CV runs/observations/reviews
- Upload allowlist for MP4, AVI, MOV and MKV with magic-byte checks, full-decode integrity verification, and local H.264 MP4 normalization
- Local-only FastAPI service with optional passphrase session (`ATM_SENTINEL_PASSPHRASE`)
- CPU-only, no cloud services, no GPU, no external uploads

## Requirements

- macOS (developed on MacBook Air M1, 8 GB RAM)
- Python 3.11+ (tested with Python 3.12.16 in `.venv`)
- Node 20+ (tested with Node 26.12.1)
- FFmpeg and ffprobe (`brew install ffmpeg` on macOS; installed version 9.0.2 during development)
- No GPU, cloud account, or paid API

## Installation

```bash
cd ~/Dev/web/atm
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cd frontend && npm install
```

## Startup

One command (backend + frontend in one terminal):

```bash
cd ~/Dev/web/atm
./scripts/dev.sh
```

Or two terminals:

```bash
# terminal 1 — backend
cd ~/Dev/web/atm
source .venv/bin/activate
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# terminal 2 — frontend
cd ~/Dev/web/atm/frontend
npm run dev
```

Open `http://127.0.0.1:5173`. API docs are at `http://127.0.0.1:8000/docs`.

## Quick demo with synthetic video

```bash
cd ~/Dev/web/atm
source .venv/bin/activate
PYTHONPATH=backend python scripts/generate_demo_video.py
```

The generator writes `data/demo/synthetic_atm.mp4`, a clearly labelled synthetic CCTV-style clip. It contains no people or real footage.

Suggested demo values:

- Case number: `DEMO-2026-0001`
- Transaction: `2026-01-15T09:00:06+00:00`
- CCTV clock at same moment: `2026-01-15T09:02:06+00:00`
- CCTV time at video start: `2026-01-15T09:02:00+00:00`
- Window: 3 s before / 3 s after
- Sampling: coarse 1 s, fine 0.5 s within 2 s of the transaction

This produces a 2-minute clock offset, a transaction at video time 6 s, and a 3–9 s analysis window.

## Testing

```bash
cd ~/Dev/web/atm
source .venv/bin/activate
python -m pytest backend/tests -q

cd frontend
npm run typecheck
npm run test -- --run
npm run build
```

Latest executed results are recorded in `reports/acceptance/acceptance.md` and `reports/acceptance/acceptance.json`. The acceptance run uses isolated synthetic data and does not establish real CCTV, DVR/NVR, R4C, or identity accuracy.

## Security and privacy

- Binds to `127.0.0.1`; no external API calls or telemetry.
- Uploads are size-limited, extension-checked, magic-byte checked, and renamed to random internal IDs.
- All FFmpeg/ffprobe calls use argument arrays; no shell commands are built from filenames.
- Paths are constrained to the project `data/` directory.
- Source videos are never modified or deleted.
- SQLite stores relative paths, never video blobs.
- Set `ATM_SENTINEL_PASSPHRASE` to require a simple local session cookie; unset means open local demo mode.
- Do not commit `data/`, real footage, personal details, or secrets. `.gitignore` excludes evidence artifacts.

## Limitations

- No identity recognition, identity matching, watchlists, Aadhaar checks, criminal database matching, or automatic association of a face with a transaction participant.
- Local YuNet/YOLOX detection and SFace embeddings are used only to locate regions and rank similarity candidates for human review; reviewer decisions are not identity findings.
- Detected faces, person detections, track IDs, similarity scores and review decisions do not identify the ATM operator, cardholder, cashier or any transaction participant; transaction and ATM references select or align video time only.
- Image-quality scores reflect sharpness, illumination, contrast, resolution, and a directional-blur heuristic. They are not identity probabilities.
- Clock alignment depends on investigator-entered timestamps and is user-verified.
- Manual clip relationships are records of human assessment, not computed similarity.
- Optional CV-derived crops are supporting artifacts when retrievable; contact sheets and selected-frame ZIP export are implemented.
- CPU-only; intended for short clips in a hackathon demonstration. Advanced timeline visualization remains optional future work.
- Real DVR/NVR device compatibility is not verified; only local MP4/AVI/MOV/MKV acceptance is covered by tests.
- There is one global optional local passphrase session, not per-user or per-case role-based access control.
- Audit events are append-only in SQLite, not tamper-proof/WORM storage or a certified chain of custody.
- R4C validation and real-world detection, face-robustness, and identity accuracy remain not assessed.

## Troubleshooting

- `ffmpeg/ffprobe not found`: install with `brew install ffmpeg`, then restart the backend.
- Unsupported video: accepted uploads are MP4, AVI, MOV and MKV. For DVR/NVR exports, use the vendor export/backup function to produce H.264 MP4; WMV, FLV, MPEG and MPG require conversion of a copy. The app's *Create normalized MP4 copy* action is video-only and drops audio. For an equivalent local video-only copy, use `ffmpeg -i input -map 0:v:0 -c:v libx264 -preset veryfast output.mp4`, preserve the original export, and verify the result before use. Real DVR/NVR export compatibility is not verified.
- Empty upload: rejected with a clear validation message.
- Port in use: change the backend `--port` or Vite port, then set `VITE_API_URL` for the frontend.
- Missing frames: check the job status and message in the Video Workspace; failures are reported rather than simulated.

See `PROJECT_PLAN.md` and `PROJECT_STATUS.md` for milestone details.
