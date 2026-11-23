# TASK 21 — Final Readiness Assessment

## Verdict

**Ready for a controlled synthetic hackathon demonstration with explicit caveats. Not ready for real-world deployment, identity decisions, R4C validation, or production police use.**

Rationale:

- Core local mechanics are implemented: case/transaction/video workflow, alignment, frame extraction, CV runs, association, best-face, review, candidate search, enhancement preview, and PDF/JSON/ZIP export.
- Current guarded verification passed: backend `331 passed, 1 deselected, 1 warning`; frontend `14` files / `87` tests; typecheck and build passed.
- Evidence integrity and provenance are implemented and locally verified: SHA-256, canonical manifest, PDF hash, source/model provenance, cross-case and stale-review rejection.
- Critical gaps remain: no RBAC/actor attribution/logout, no WORM/certified chain of custody, no real CCTV/R4C validation, no automatic identity capability (correctly absent), limited video formats, uncalibrated quality/heuristics, and synthetic-only benchmarks.

## Scope completed in TASK 21

- Inspected actual backend source, frontend source, tests, acceptance reports, requirement matrix, and TASK 02–20 reports.
- Confirmed no literal original Rajasthan Police brief file exists; `reports/ps04cctv-audit/REQUIREMENTS_MATRIX.json` is the authoritative in-repo reconstruction.
- Produced one primary self-contained report and five supporting documents.
- Ran required final verification commands and read-only `git status --short`.
- Made no product/CV/schema/threshold/model/package/service changes and no protected-data changes.

## Requirement coverage summary

| Current status | Count | Requirements |
| --- | ---: | --- |
| Implemented and verified | 12 | KF1.2, KF1.3, KF1.4, KF2.2, KF3.1, KF3.2, KF4.2, KF6.4, MH-2, CC-HUMAN, CC-PROV, SD-1 |
| Implemented partially verified | 4 | KF6.1, MH-1, MH-3, GH-3 |
| Partially implemented | 7 | KF1.1, KF2.1, KF4.1, KF5.1, KF6.3, GH-1, CC-ROBUST |
| Not implemented | 3 | KF6.2, GH-2, R4C |
| Out of scope | 4 | OOS-1, OOS-2, OOS-3, OOS-4 |

Historical audit scores were Must Have `88/100`, Good to Have `8/100`, overall internal PS04CCTV `58/100`, local technical verification `63/100`. These are audit-time scores before later P0/TASK implementations and are not official certification.

## Verified features

- Case creation/edit/archive, transactions, notes, timeline, clip links, metadata search.
- Upload validation, ffprobe metadata, SHA-256, verification, normalized MP4 derivative.
- Transaction-to-CCTV alignment preview with offsets, warnings, and provenance.
- Frame extraction jobs with progress/cancel and manual frame capture.
- YuNet face detection, YOLOX person detection, `SimpleTracker` clip-local tracks, SFace embeddings.
- ATM-zone person association with hard continuity/eligibility gates and human review.
- Deterministic best-face ranking with reliability indicators and explicit `not_assessed` concealment status.
- Derived-only OpenCV enhancement preview with original/enhanced separation and hashes.
- Case-scoped cross-clip candidate search with query source exclusion and model-provenance validation.
- Face/candidate/association human review states.
- Evidence gallery, compare, PDF/JSON/ZIP/contact sheet export with hashes and audit events.
- Frontend anti-identity trust copy, demo-data labels, modal accessibility fixes, stale-state fixes.
- Optional global passphrase/session cookie in local mode.

## Exact final verification

| Command | Exact result |
| --- | --- |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q --tb=no -k 'not test_synthetic_generator_writes_labelled_clips'` | `331 passed, 1 deselected, 1 warning in 49.49s` |
| `cd frontend && npm test -- --run` | `Test Files 14 passed (14)`, `Tests 87 passed (87)` |
| `npm run typecheck` | passed |
| `npm run build` | passed; `dist/index.html 0.83 kB`, CSS `33.83 kB / 6.66 kB gzip`, JS `455.34 kB / 131.57 kB gzip` |
| `git status --short` | read-only; see changed-files section |

Warning: `StarletteDeprecationWarning` from `fastapi.testclient`; pre-existing and unrelated.

## Exact benchmark metrics with limitations

| Work | Key exact metrics | Limitations / production status |
| --- | --- | --- |
| TASK 02 baseline | 220 synthetic frames; duration `48,544.563 ms`; peak RSS best effort `52,838,400 bytes`; face frame-presence P `1.0`, R side `0.1333` / multi `0.1714`; Rank@1/Rank@5 `4/4`; quality mean `92.845`; best-face quality mean `98.48` | Synthetic only; no bbox mAP/IoU, track GT, real CCTV; benchmark of existing pipeline, no production change. |
| TASK 03 YuNet recall | 1.5× upscaling raised side recall `0.5667 → 0.9667` at `~3.17×` latency; 2× no gain at `~4.7–5.1×` latency | Frame-presence labels only; isolated. |
| TASK 04 fallback | Zero-detection fallback side recall `0.9667`, `11.197 ms` vs full `19.059 ms`; all recovered frames came from baseline-zero detections `12/12` | Synthetic; confidence thresholds selected from observed evidence; isolated. |
| TASK 05 person gate | Strict person-gate side recall fell to `0.5667`; safety run retained `0.9667` but `58.616 ms` vs `11.218 ms` fallback | YOLOX person proxy `0.0` on side clip; no person GT; isolated. |
| TASK 06 YOLOX threshold | Proxy coverage on challenges `0.425 @0.1`, `0.2 @0.45`; side/second-subject/multi stayed `0.0` at every threshold | Face labels are not person GT; no threshold selected/changed. |
| TASK 07 feasibility | Status `partially_ready_isolated_experimental_only`; SCRFD/RetinaFace weight license unclear/restricted risk; YOLOv8-face avoided (AGPL/unclear weights); YuNet retained | No approved alternative weights/runtime; no alternative performance measurements. |
| TASK 08 bbox readiness | Bbox TP/FP/FN, IoU, mAP NOT_ASSESSABLE; minimum useful subset ~48/220 frames; focused tests `8 passed` | No bbox GT before annotation; isolated validator. |
| TASK 09 annotation pilot | 48 frames selected; derived PNGs; empty-template validator `REVIEW_REQUIRED`, 48 missing; focused tests `9 passed` | Tool/workspace only; no completed human annotation created by TASK 09. |
| TASK 12 annotation QA | 48 frames represented, 46 boxes, 9 no-face, 0 missing/extra/duplicates, 48/48 images readable, 0 validator errors/warnings; QA `NOT_REVIEWED`, `benchmark_ready=false` | Visual criteria `NOT_ASSESSABLE`; labels appear default-like; not benchmark-ready. |
| TASK 13 | No artifact found | Cannot state objective/metrics/results; alternative detector feasibility remains blocked/unverified. |
| TASK 14 tracker | Proxy parity on 4 deterministic sequences; JSON crossing `unique_track_ids=2`, `id_switches_proxy=2`; clip runtimes Simple/ByteTrack `0.332/0.222`, `0.326/0.224`, `0.323/0.222 ms`; MD/JSON disagree on some values | IDF1/MOTA/HOTA NOT_ASSESSABLE; zero YOLOX detections in clip benchmark; not integrated. |
| TASK 15 enhancement | 12 runs over 3 crops × 4 presets; dark durations `162.527/140.708/143.330/136.261 ms`; classical presets only; focused `6 passed`, guarded `315 passed` | AI models unavailable; derived preview only; not in export/DB/matching. |
| TASK 16 quality | Old→new overall examples dark `52.4→72.99`, blur `22.7→36.92`, noise `53.8→62.82`; overall rose under noise in `5/6` samples; guarded `323 passed` | Uncalibrated; noise flaw; isolated, not production. |
| TASK 17 face-box GT | 48 frames/46 boxes; baseline P `1.0`, R `0.869565`, F1 `0.930233`, AP50 `0.869565`, IoU `0.660550`, `5.725725 ms`; fallback R `0.913043`, `9.276854 ms` | GT `NOT_REVIEWED`, synthetic only; exploratory. |
| TASK 18 SFace retrieval | 127 samples/3 subjects/4 clips; 8,001 pairs; AUC all `0.954847`, cross-clip `0.989106`; Rank@1/Rank@5/MRR `1.0`; EER proxy all thr `0.889643`, TAR `0.899324`, FAR `0.100771`; cross-clip thr `0.896400`, TAR `0.942647`, FAR `0.057996` | Synthetic only; genuine cross-clip only SYN-A; offline thresholds; no production change; MD/JSON cross-clip TAR@FAR values differ. |
| TASK 19 workflow | API workflow PASSED; alignment video seconds `3.0`, window `2.0–4.0`; association confirmed; export CV counts `2/1/1`; hashes matched; cross-case/stale boundaries returned 404/422; busy 503 with `Retry-After: 5` | API/TestClient fixtures; not browser E2E, real CCTV, or accuracy validation. |
| TASK 20 UI/perf | Browser CDP smoke PASS, 0 console/network/HTTP errors; normalize `71.826 ms`, upload `66.225 ms`, cold status `58.995 ms`, export `31.602 ms`; warm medians `2.348/1.849/1.991 ms`; bundle `490,002` raw / `138,220` gzip bytes | Fixtures for all `/api`; no backend persistence, real traffic, CV inference timing, or Core Web Vitals. |
| P0-1A/1B/2/3/6 | Real YOLOX test-local threshold `0.1` produced 7 detections; P0-1B gap gate ≤`1.0s`; P0-2 selected frame 5 score `0.9741`; P0-3 reliability statuses; P0-6 hashes verified and side-query top cosine `0.947086` | Synthetic assets; mocked controls clearly separated; no real CCTV. |

## Demo prerequisites and workflow

Prerequisites: existing local services; synthetic assets under `data/demo` and `data/datasets/synthetic/cv`; pinned models under `data/models`; no prohibited scripts; no service restart/stop; no protected-data modification.

Workflow: open `/` → create demo case at `/cases` → add transaction timestamp → upload/select synthetic video at `/investigation` → verify alignment → start processing/CV run if local models are verified → inspect `/cv` observations, associations and best-face → compare original/enhanced crop → cross-clip candidate search and review → review/capture evidence in `/workspace` and `/evidence` → generate PDF/JSON/ZIP at `/export`. See `TASK-21-DEMO-RUNBOOK.md` for exact actions, expected results, presenter explanations, verification labels, and recovery steps.

## Outstanding risks

### Immediate engineering gaps
- Implement per-user authentication, RBAC, per-case grants, actor attribution, logout/expiry/revocation, and protected-route browser verification.
- Add WORM/tamper-evident audit storage, signatures, and export verification if required for custody claims.
- Broaden supported video formats or provide robust conversion guidance/tooling for real DVR/NVR exports.
- Make CV runs asynchronous or clearly constrained for longer clips; add progress/cancel/refresh.
- Recalibrate quality/best-face heuristics and fix TASK-16 noise-score inflation before production use.
- Complete human visual QA of annotations and acquire person/track ground truth before detector/tracker accuracy claims.
- Add behavioral tests for Cases, Workspace, Evidence, Compare, download URLs, and full browser E2E against a real backend.

### Longer-term research opportunities
- Real CCTV/R4C validation across cameras, lighting, compression, occlusion, and clock drift.
- Approved alternative detectors and trackers with proper license/provenance and annotated ground truth.
- Validated face-quality, concealment, pose, and degradation robustness models.
- Calibrated retrieval thresholds with real identities and lawful, approved datasets only.
- Carefully governed AI restoration models with forensic separation and artifact detection.

## Changed files produced by TASK 21

- `reports/ps04cctv-audit/ATM-SENTINEL-FINAL-TECHNICAL-SUBMISSION.md`
- `reports/ps04cctv-audit/TASK-21-REQUIREMENT-MAPPING.md`
- `reports/ps04cctv-audit/TASK-21-DEMO-RUNBOOK.md`
- `reports/ps04cctv-audit/TASK-21-JUDGE-QA.md`
- `reports/ps04cctv-audit/TASK-21-FINAL-READINESS.md`
- `reports/ps04cctv-audit/TASK-21-ARCHITECTURE.mmd`

No product source, CV algorithm, detector, tracker, threshold, embedding, schema, package, service, protected data, annotation, or benchmark source was changed by TASK 21.

## Git status

`git status --short` was read-only. The worktree contains pre-existing modified/untracked implementation, test, script, artifact and report files from prior tasks, plus the six TASK 21 report files listed above. No Git write/sync operation was performed.

## Final readiness verdict

**Conditional demo-ready; not production-ready.** Present the system as a local, synthetic-data, human-review evidence organization prototype with measurable provenance and carefully bounded CV assistance. Do not present it as automatic identity verification, real-world-validated face recognition, R4C-certified, or court-admissible.
