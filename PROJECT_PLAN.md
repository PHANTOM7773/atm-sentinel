# ATM Sentinel — Project Plan

## Scope

ATM Sentinel is a local-only prototype for transaction-driven ATM CCTV evidence organization. It helps an authorized investigator:

1. create a case and record transaction details,
2. upload a video and verify its integrity,
3. align transaction time with CCTV clock time,
4. extract frames from the configured window,
5. score frame image quality with explainable metrics,
6. select evidence and export a PDF report with SHA-256 hashes.

The application does **not** identify people, perform facial recognition, or make claims about identity. Local CV features only locate regions, rank review candidates, and record human decisions; quality scores describe image usability only.

## Milestones

### M0 — Foundation (complete)
- [x] Inspect environment and target directory
- [x] Verify Python, Node, npm, Git, FFmpeg
- [x] Create isolated project and local Git repository
- [x] Write plan, status, and README
- [x] Install local Python virtualenv and frontend dependencies
- [x] Start application and run baseline tests

### M1 — Backend P0 (complete)
- FastAPI service bound to `127.0.0.1`
- SQLite schema with controlled initialization
- Safe upload handling: extension allowlist, magic-byte check, size limit, safe internal names
- ffprobe metadata extraction and integrity check
- Timestamp alignment calculation with offsets, explicit verification endpoint
- Incremental frame extraction around the analysis window with progress/cancel
- Laplacian variance sharpness, brightness, contrast, normalized explainable quality score
- Case/transaction/video/frame/evidence/note/audit endpoints
- PDF export with report hash and JSON manifest

### M2 — Frontend P0 (complete)
- Dark forensic dashboard shell
- Command Center with real counts and system dependency status
- Case Management (create, open, edit, notes, transactions, videos, timeline, archive)
- New Investigation guided workflow with alignment preview
- Video Workspace with player, markers, metadata, extracted frames
- Evidence Gallery with sorting, filtering, selection, compare, notes
- Case Comparison (manual links only)
- Evidence Export screen

### M3 — Tests and verification (complete)
- Pytest for validation, timestamps, windows, metadata, extraction, quality, hashing, export, DB, unsafe filenames, invalid files, missing FFmpeg, empty uploads
- Vitest for frontend utilities
- TypeScript typecheck and production build
- Synthetic test video generation
- End-to-end manual verification and documentation update

### M4 — Demo hardening (partial)
- [x] Synthetic sample dataset generator
- [x] Face-region detection as an optional, clearly labelled feature (no recognition)
- [x] Contact sheet export
- [ ] Advanced timeline visualization
- [x] Additional export options (selected-frames ZIP)
- [x] Tags metadata and tag-based search

## Architecture

```
atm-sentinel/
  backend/
    app/
      main.py             FastAPI app, CORS restricted to localhost
      config.py           paths and limits
      db.py               SQLite connection and schema
      schemas.py          Pydantic request/response models
      services/
        security.py       filenames, hashes, path safety
        video.py          ffprobe, validation, normalization
        timestamp.py      alignment and window math
        quality.py        explainable frame metrics
        extraction.py     incremental frame sampling
        export.py         PDF + JSON manifest
      routers/            case, video, job, frame, system APIs
    tests/                synthetic fixtures and unit/integration tests
  frontend/
    src/
      pages/              dashboard, cases, investigation, workspace, evidence, compare, export
      components/         shared UI primitives
      lib/                API client, formatting, types
  data/                   local SQLite, uploads, frames, exports (gitignored)
  scripts/                dev launcher and demo helpers
```

## Constraints and decisions

- Target: MacBook Air M1, 8 GB RAM, CPU-only. No cloud AI or remote services.
- Frame extraction uses OpenCV sequential reads plus FFmpeg seek for manual single-frame capture; never loads a full video into RAM.
- FFmpeg/ffprobe are called with argument arrays via `subprocess`; no shell interpolation.
- Uploaded videos are renamed to random internal IDs. Original names are stored as metadata only.
- Source videos are never modified or deleted by processing.
- SQLite stores paths relative to `data/`, never video blobs.
- No official police branding, no endorsement claim.
- The product displays: "Prototype evidence organization and integrity tracking."

## Out of scope

- Facial recognition, embeddings, identity matching, watchlists, Aadhaar/criminal DB checks
- Legally certified/court-certified claims
- Real CCTV footage in Git
- Automatic conclusions about suspicious behavior or identity
