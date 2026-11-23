# TASK 20 — UI/Performance Audit and Verification

## Scope
- Audited and polished the ATM Sentinel frontend without changing CV algorithms, detector/tracker thresholds, schemas, protected data, installed packages, or running services.
- Main investigator path exercised: `/investigation` → alignment preview → `/cv` → `/evidence` → `/export`.
- Browser verification used the already-installed Google Chrome `157.0.8103.79` through CDP. No browser-automation libraries were installed.
- Performance used a synthetic 60-frame `320x240` MP4 against an isolated temporary data directory. Protected case data was not read or written by the benchmark.

## UI findings and fixes
| Severity | Finding | Fix |
| --- | --- | --- |
| High | Investigation auto-filled transaction video time from `tx.cctv_ts`, forcing `00:00.00` and leaking stale values across case/tx switches. | Removed the auto-fill and added explicit local video-time input with UTC/CCTV context. |
| High | Alignment/job results remained visible and wizard steps remained clickable after case, transaction, or video changes. | Added state clearing and `maxReachableStep` gating in Investigation. |
| Medium | Upload pickers accepted `video/*` and did not reset the file input, preventing retry with the same file. | Restricted accepted extensions, added size validation, and reset inputs on error/start. |
| Medium | Export could show one case's report while another case was selected; ZIP used current-frame selection instead of generated report frames. | Cleared stale export state on case switch and derived ZIP contents from the generated report. |
| Medium | Enhancement panel could reuse stale presets/results and had broken image states. | Added preset loading state, stale-result clearing, error placeholders, and disabled Enhance until presets load. |
| Medium | Candidate results could remain visible after scope/source/topK changes. | Cleared candidate results on relevant filter changes in CV runs. |
| Low | Null transaction video timestamp rendered as `00:00.00`; best-face ranking detail was unreachable; association list stopped at 25 rows. | Rendered `—`, added best-face inspection modal, and added association pagination. |
| Low | Transaction timestamps lacked timezone clarity and invalid values could be submitted. | Added UTC hint, local-input/stored-UTC labels, and validation before enabling Add transaction. |
| Accessibility | Shared modal lacked dialog semantics; some icon-only controls were unlabelled; Compare results were dead ends. | Added `role="dialog"`, `aria-modal`, labelled title, Escape handling/focus, button labels, and case links from Compare clips. |

## Browser smoke
- Result: **PASS**.
- Browser: Google Chrome `157.0.8103.79` headless via CDP.
- API mode: all `/api` requests fulfilled by CDP fixtures; backend data untouched.
- Checks passed: Investigation rendered, case/transaction/video selected, wizard reached analysis window, alignment preview completed, and `/cv`, `/evidence`, `/export` rendered.
- Console errors: none. Network failures: none. HTTP errors: none. Error banner: absent.

## Performance
- Full metrics: `reports/ps04cctv-audit/TASK-20-PERFORMANCE-RESULTS.json`.
- Slowest measured API steps: normalize `71.8 ms`, video upload `66.2 ms`, cold system status `59.0 ms`, verify `34.9 ms`, export `31.6 ms`.
- Warm read medians: frames `2.35 ms`, exports `1.85 ms`, videos `1.99 ms`.
- Frontend production bundle: JS `455.34 kB` raw / `131.57 kB` gzip; CSS `33.83 kB` raw / `6.66 kB` gzip; three assets total `490.00 kB` raw / `138.22 kB` gzip.
- No CV run inference timing was collected because real model inference is out of scope and models are not installed.

## Verification
- Backend guarded regression: `331 passed, 1 deselected, 1 warning` (`StarletteDeprecationWarning`, pre-existing).
- Frontend: `14` test files, `87` tests passed; `npm run typecheck` passed; `npm run build` passed.
- Protected paths at report time: `19 files; sha256 d301d83f06b58c8884d72ab55ca6861b7f531676ccaa28878e1ba9b86ecd20f5` (sorted path + content-digest method). All protected file mtimes remain `<= 2026-11-23 16:53`, before this TASK 20 run; no protected-path additions, edits, or deletions were made.

## Limitations / deferred
- Benchmark is local TestClient-only, not production traffic or a real-user workload.
- Browser smoke verifies UI behavior with fixtures, not backend persistence.
- Browser performance trace metrics and Core Web Vitals are unavailable in this environment and were not estimated.
- No CV model, threshold, schema, detector, tracker, or protected-data behavior was changed.
- Existing broader limitations remain from TASK13/TASK17/TASK18: detector comparison blocked on approved local weights/runtime, face-bbox GT visual QA incomplete, and AI restoration/quality models unavailable locally.

## Files changed
- `frontend/src/lib/types.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/api.test.ts`
- `frontend/src/components/ui.tsx`
- `frontend/src/components/ui.test.ts`
- `frontend/src/components/CvCropEnhancementPanel.tsx`
- `frontend/src/components/CvCropEnhancementPanel.test.ts`
- `frontend/src/pages/Investigation.tsx`
- `frontend/src/pages/Investigation.test.ts`
- `frontend/src/pages/CvRuns.tsx`
- `frontend/src/pages/CvRunsView.test.ts`
- `frontend/src/pages/Export.tsx`
- `frontend/src/pages/Export.test.ts`
- `frontend/src/pages/Cases.tsx`
- `frontend/src/pages/Evidence.tsx`
- `frontend/src/pages/Compare.tsx`
- `reports/ps04cctv-audit/TASK-20-PERFORMANCE-RESULTS.json`
- `reports/ps04cctv-audit/TASK-20-UI-PERFORMANCE-AUDIT.md`
