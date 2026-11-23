# TASK 21 — Judge Questions and Answers

These answers are the technically accurate source for judge responses and presenter scripting. They intentionally avoid claims of automatic identity verification, real-world accuracy, R4C certification, or database matching.

## Problem and solution

### 1. What problem does ATM Sentinel solve?
It reduces manual CCTV review by using a bank transaction timestamp to select a short analysis window, organize relevant frames, detect/track persons and faces, rank reviewable candidates, support human decisions, and export evidence with hashes and provenance. It is a local prototype for evidence organization, not an identity system.

### 2. Why not just play the CCTV footage manually?
Manual review of long recordings is slow and error-prone. The system converts a transaction time and CCTV clock offset into a bounded window, then surfaces frame-level evidence, quality signals, review states, and exportable provenance. It accelerates triage; it does not replace human review.

### 3. What is the core proposed solution?
A FastAPI + React application with SQLite provenance, FFmpeg-based video validation/normalization, YuNet face detection, YOLOX person detection, SFace embeddings for candidate ranking, heuristic ATM-zone association, deterministic best-frame selection, human review, and PDF/JSON export.

### 4. Is this a production police system?
No. It is a hackathon prototype validated locally with synthetic/sample data. Real CCTV/R4C validation, RBAC, certified chain of custody, and court admissibility are not established.

## Transaction time and alignment

### 5. Why do transaction timestamps matter?
They provide an objective anchor for selecting a short video window around the ATM interaction, reducing unrelated footage and preserving the relationship between a financial event and candidate visual evidence.

### 6. How is CCTV time aligned to transaction time?
The investigator supplies transaction time, CCTV time at a reference point, and/or a manual clock offset. `backend/app/services/timestamp.py`, `POST /api/alignment/preview`, `POST /api/jobs` and `POST /api/cv/runs` compute the transaction position in source-video seconds and a bounded before/after window with warnings and provenance.

### 7. Does the system read the CCTV clock automatically?
No. There is no OCR or automatic DVR clock extraction. Naive timestamps are treated as UTC with warnings. Alignment is mathematical and records provenance; it does not independently verify camera clock accuracy.

### 8. What happens if the transaction time is wrong?
The window will be wrong. The UI shows derived/applied offsets, transaction video time, warnings, and a visible window so the investigator can correct the inputs before processing.

## Person detection and tracking

### 9. How are persons detected and tracked?
YOLOX ONNX detects COCO class 0 persons on CPU; `SimpleTracker` assigns clip-local IDs using detection association logic. Production config uses `CV_PERSON_SCORE_THRESHOLD = 0.45`; budgets cap frames, detections, and observations.

### 10. Are person detections reliable?
The API explicitly reports person detection as `experimental_unvalidated`. Zero detections mean “no person detected by this detector,” not “no person present.” P0-6 verified real inference on synthetic clips; a test-local threshold of `0.1` was used for a positive person case, while production default `0.45` produced zero detections on one synthetic multi-subject clip.

### 11. Does a track ID identify a person?
No. Track IDs are local to one analysis run and may be reused or fragmented. They are not biometric identities, database keys, or persistent person identifiers.

### 12. Was an alternative tracker adopted?
No. The ByteTrack-inspired tracker in `backend/app/cv/bytetrack_tracker.py` is isolated and not wired into production. TASK-14 found parity on proxy tests and no demonstrated gain; IDF1/MOTA/HOTA were `NOT_ASSESSABLE` without person/track ground truth.

## Face detection, quality, and best-face

### 13. Which face detector and embedding model are used?
YuNet (`face_detection_yunet_2026may.onnx`) provides face boxes and five landmarks. SFace (`face_recognition_sface_2021dec.onnx`) provides 128-dimensional embeddings. Both are pinned with SHA-256 hashes in `data/models/SHA256SUMS.json` and verified at load time.

### 14. What does face quality measure?
It measures image-usability signals such as sharpness, resolution, exposure, contrast, pose proxy, and occlusion proxy. These are heuristics for human review, not identity accuracy or biometric validity.

### 15. What does “best face” mean?
It means one existing observation in a linked person association is selected by a deterministic weighted heuristic using sharpness, usable resolution, frontalness, illumination, contrast, landmark visibility, detector confidence, and an occlusion factor. Tie-breaks are earlier frame then observation ID. It means “best frame to review,” not “most identifiable person.”

### 16. How is a face linked to a person at the ATM?
`backend/app/services/best_face.py` uses same-frame face bbox containment inside a person bbox (`MIN_FACE_BBOX_CONTAINMENT = 0.6`). This is geometric linkage, not identity linkage.

### 17. Does the system detect masks, helmets or caps?
No. Potential obstruction is a conservative heuristic only. Mask, helmet, cap and concealment type remain `not_assessed`.

## Embeddings and similarity search

### 18. How does cross-clip search work?
SFace embeddings from eligible, provenance-valid observations are indexed. `POST /api/cv/candidates/search` ranks candidates by cosine similarity within a case-scoped set, excludes the query observation and source video, validates model/schema provenance, and returns scan diagnostics and review controls.

### 19. What does a similarity score mean?
It is visual similarity within a synthetic/sample dataset for candidate retrieval. It is not identity confidence, probability of same person, or evidence of criminal involvement.

### 20. Did TASK-18 prove real-world face recognition accuracy?
No. TASK-18 used 127 usable samples, 3 synthetic subjects, 4 clips, 8,001 all pairs and 5,870 cross-clip pairs. AUC all was `0.9548`, AUC cross-clip `0.9891`, but cross-clip genuine pairs were only SYN-A. It is exploratory and not real-world validation.

### 21. Are there false positives and missed detections?
Yes. Frame-presence precision was often `1.0` in TASK-02 while recall was low on side/multi-subject clips. TASK-17 baseline had precision `1.0`, recall `0.8696`, F1 `0.9302` against 48 unreviewed annotated frames. Misses and heuristic false candidates remain possible; human review is required.

## Evidence integrity

### 22. How is original evidence preserved?
Uploaded originals are stored under `data/uploads` with SHA-256, metadata and audit events. Normalized MP4s, crops, thumbnails, enhanced previews, PDFs and manifests are separate derived artifacts. Originals are not overwritten.

### 23. What does export contain?
`POST /api/exports` generates a canonical JSON payload, PDF, manifest with `report_hash` and `pdf_sha256`, optional ZIP of selected frames and contact sheet. It includes case/transactions/videos/jobs/frames/notes/links/audit events and opt-in CV references. TASK-19 verified report hash matched manifest and PDF header was present.

### 24. Can stale or cross-case evidence be exported?
Export validation rejects cross-case runs, wrong source/normalized hashes, ineligible run status, non-`candidate_only` observations, stale review timestamps, and mismatched model provenance. TASK-19 verified cross-case export `422` and stale review export `422`.

### 25. Is the audit log tamper-proof?
No. Append-only SQLite audit events are recorded and included in exports, but there is no WORM storage, signature, actor attribution, or certified chain of custody.

## Enhancement, privacy, and responsible use

### 26. What enhancement is available?
TASK-15 added classical OpenCV enhancement presets as a derived preview: CLAHE, gamma, brightness/contrast, denoise, unsharp, and upscale. Outputs are labelled `"AI-enhanced derived image - not original evidence"` and are never used for embeddings or matching.

### 27. Are AI restoration models used?
No. GFPGAN, Real-ESRGAN, CodeFormer, CR-FIQA and MagFace are not available locally. `backend/app/cv/ai_restoration_adapters.py` only checks availability; it does not download or install models.

### 28. How does the system protect privacy?
It uses synthetic/sample data only for the hackathon, case-scoped CV data, source-video exclusion in candidate search, restricted crop headers, optional local passphrase mode, sanitized public DTOs, anti-identity disclaimers, and human review requirements. It does not connect to real CCTV, Aadhaar, criminal databases, or watchlists.

### 29. Is there role-based access control?
No. P0-4A found an optional global passphrase, open mode when unset, a deterministic shared session cookie, no users/roles, no per-case grants, no actor identity, no logout, expiry, or revocation. This is an open engineering gap.

### 30. Can ATM Sentinel identify a suspect automatically?
No. It never asserts identity. Outputs are candidate frames, similarity ranks, track IDs, heuristic associations, and human-review decisions. Any identity judgment remains with an authorized human investigator using lawful processes outside this prototype.

## Performance and hardware

### 31. What performance was measured?
TASK-20 used local FastAPI TestClient and one synthetic 60-frame, 320×240 MP4. Slowest API steps were normalize `71.826 ms`, upload `66.225 ms`, cold status `58.995 ms`, verify `34.916 ms`, export `31.602 ms`. Warm medians: frames `2.348 ms`, exports `1.849 ms`, videos `1.991 ms`. Bundle: `455.34 kB` JS raw / `131.57 kB` gzip and `33.83 kB` CSS raw / `6.66 kB` gzip.

### 32. Does that prove production latency?
No. It is local TestClient measurement, not production traffic, real CCTV resolution, network latency, or core CV inference. No Core Web Vitals/browser trace metrics were available; TASK-20 browser smoke used CDP fixtures.

### 33. Why is CV synchronous?
The current implementation executes `POST /api/cv/runs` synchronously with strict frame/decode/candidate/response budgets. Long clips are bounded by `CV_MAX_FRAMES = 300`, `CV_MAX_DECODED_FRAMES = 3000`, and `CV_MAX_CLIP_DURATION_SECONDS = 300`. Busy candidate search returns `503` with `Retry-After: 5`.

## Model selection and experiments

### 34. Why YuNet, YOLOX and SFace?
They were locally available, CPU-capable, pinned by hash, and had acceptable license provenance in TASK-07. Alternative SCRFD/RetinaFace packs were not approved locally; YOLOv8-face/Ultralytics-derived options were avoided due license/provenance risk. No alternative detector was benchmarked against real CCTV.

### 35. What did detector experiments show?
TASK-03 found 1.5× YuNet upscaling raised side-pose frame recall from `0.5667` to `0.9667` at `3.1748×` latency. TASK-04 zero-detection fallback reproduced the gain at `11.197 ms` vs `19.059 ms` full upscaling. TASK-17 against 48 unreviewed frames found fallback recall `0.9130` vs baseline `0.8696`, latency `9.28 ms` vs `5.73 ms`. None were production-integrated.

### 36. What did baseline CV benchmark show?
TASK-02 canonical run: 220 synthetic frames, total duration `48,544.563 ms`, peak RSS best effort `52,838,400 bytes`. Face frame-presence precision was `1.0` on labeled clips but recall varied (side `0.1333`, multi-subject `0.1714`). Rank@1/Rank@5 were `4/4` with no different-subject pairs, so ranking was not identity accuracy.

## Dataset limitations and readiness

### 37. What data was used?
Synthetic procedural clips under `data/datasets/synthetic/cv`: 6 clips, 220 frames, 10 fps, 640×480, labels for frame presence only. No real people or real CCTV footage were used.

### 38. What is the human annotation status?
TASK-09 created a 48-frame annotation pilot. TASK-12 programmatically verified 48 frames represented, 46 boxes, 9 no-face frames, valid bounds, 0 validator errors/warnings. However QA status remains `NOT_REVIEWED`, `benchmark_ready=false`, and visual criteria were `NOT_ASSESSABLE` because image input was unavailable to the auditor.

### 39. Was R4C data used?
No. R4C status is `NOT_ASSESSED`. No real ATM-angle footage, real formats/qualities/timestamps, or same/different-person clips were supplied or validated.

### 40. What is the final readiness verdict?
Ready for a controlled synthetic hackathon demonstration with strict caveats. Not ready for real-world deployment, identity decisions, R4C validation, or production police use. Core local mechanics, provenance, human review, and export are implemented and verified; accuracy, RBAC, certified custody, format breadth and real-CCTV robustness remain open.
