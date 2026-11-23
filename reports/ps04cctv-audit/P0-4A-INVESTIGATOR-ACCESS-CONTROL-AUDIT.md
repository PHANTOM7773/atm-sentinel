# P0-4A — Investigator Review & Access-Control Security Audit

**Project:** `/Users/yps/Dev/web/atm`  
**Date:** 2026-11-23  
**Type:** Read-only audit (no implementation)  
**Scope:** Authentication, authorization/RBAC, investigator workflows, case/run isolation, audit logging, security boundaries. No source/schema/frontend/dependency/data/service/Git changes.

## 1. Current Authentication Architecture

| Area | Finding | Evidence |
|---|---|---|
| Mechanism | Single optional global passphrase; one HTTP middleware guard. No FastAPI per-route auth dependencies (`Depends`/`Security`/OAuth2/API key) found in routers. | `backend/app/main.py:34-47`, `backend/app/main.py:50-63` |
| Passphrase source | `ATM_SENTINEL_PASSPHRASE` env var; empty/unset = open mode. No DB/file credential store. | `backend/app/services/security.py:99-100`, `backend/app/main.py:39,52-54` |
| Verification | Login compares submitted passphrase with `hmac.compare_digest` against env passphrase. No password hashing (no bcrypt/argon2/passlib/JWT deps). | `backend/app/main.py:55-60`, `backend/app/requirements.txt:1-9` |
| Session token | Deterministic HMAC-SHA256 of fixed literal `"atm-sentinel-session"` keyed by passphrase; same token for all sessions for a given passphrase. | `backend/app/services/security.py:93-96`, `backend/app/main.py:43,62` |
| Cookie | `sentinel_session`; `httponly=True`, `samesite="lax"`; no `secure`, no `max_age`/`expires`, no explicit path/domain; browser-session cookie only. | `backend/app/main.py:16,62`, read at `:44` |
| Server-side session | None. No session/token DB table; no expiry, revocation, rotation, logout endpoint. | `backend/app/db.py:15-251` (no session/user tables), `frontend/src/components/AppShell.tsx:302-304` |
| Default behavior | No passphrase configured: middleware bypasses all `/api`; `/api/session` returns `{"mode":"open",...}`; all API endpoints open. | `backend/app/main.py:41,53-54` |
| Public paths | Exact `PUBLIC_PATHS`: `/api/session`, `/api/system/status`, `/api/alignment/preview`. Paths outside `/api` (`/`, `/docs`, `/openapi.json`) are not guarded by middleware. | `backend/app/main.py:34,41,66-73` |
| Frontend auth state | Session state in `AppShell`; probe/login via `sessionApi`; passphrase held transiently in React state and cleared after submit. No route guards; all nav/routes render unconditionally. | `frontend/src/components/AppShell.tsx:107-136,148-217,292-310`, `frontend/src/App.tsx:16-30`, `frontend/src/lib/api.ts:84-111`, `frontend/src/lib/types.ts:185-192` |
| CORS/config | CORS allows configured origins, credentials, `*` methods/headers; defaults localhost 5173/5174; overridable by `ATM_SENTINEL_CORS_ORIGINS`. Loopback dev binding in scripts/config. | `backend/app/main.py:26-32`, `backend/app/config.py:71-86`, `scripts/dev.sh:7`, `frontend/vite.config.ts:8`, `frontend/package.json:7,9` |
| Secret handling | Passphrase read from env only; no secret exposed by audit. No `.env` committed; `.gitignore` excludes env/data/db. Upload limits/magic/filename hardening present. | `backend/app/services/security.py:11-67,99-100`, `backend/app/config.py:19-20`, `.gitignore:13-28` |

**Conclusion:** The global passphrase provides **application-wide shared access only** when enabled, not investigator-level access control. There is no user identity, no roles, no per-case authorization, no session lifecycle management, and no actor attribution.

## 2. Current Authorization Architecture

| Area | Finding | Evidence |
|---|---|---|
| RBAC | Not implemented. No users/roles/permissions/grants/case-assignment tables. | `backend/app/db.py:15-251` |
| Endpoint authorization | No per-endpoint permission checks. All protected `/api` endpoints share same middleware gate. | `backend/app/main.py:37-47`; no auth deps in routers |
| Identity/actor | No authenticated principal. `audit_events` has no actor/user/session/IP column. | `backend/app/db.py:131-137,360-364` |
| Case authorization | Case scoping is data filtering in selected handlers, not authorization. Some endpoints require/validate `case_id`; many ID-based endpoints do not. | see §4/§5 |
| Permission distinctions | No distinction for view/upload/run/review/confirm/reject/search/export/manage settings. Any caller with the shared session (or open mode) can perform all exposed actions. | router/service inspection; `cv.py:299-312,372-387,412-429,432-515`, `exports.py:17-116` |
| Frontend authorization | No route guards, role-aware UI, or action gating by identity. UI only reflects session mode. | `frontend/src/App.tsx:16-30`, `frontend/src/components/AppShell.tsx:107-136,234-252` |

## 3. Investigator Workflow Permission Matrix

Legend: **Auth** = `GS` global session guard, `PUB` public path exempt, `OUT` outside `/api`. **AuthZ** = role/case authorization beyond data filtering. **Case/Run scope** = handler validates object belongs to supplied/derived case/run. **Audit** = explicit `audit()` write.

| Workflow | Endpoint(s) | Auth | AuthZ | Case/Run scope | Audit | Notes / Risk |
|---|---|---:|---:|---:|---:|---|
| Video upload | `POST /api/videos/upload?case_id=` (`videos.py:19-103`) | GS | None | Case checked after file persisted/moved (`:66-74`) | `video_uploaded` | Invalid case can leave moved file without DB row; no actor |
| Video list/detail/file/verify/tags | `GET/GET{id}/PATCH{id}/GET{id}/file/POST{id}/verify` (`videos.py:106-171`) | GS | None | ID-only lookups; list unfiltered when `case_id` omitted | tags/verify only | IDOR/read exposure by video ID; file download unaudited |
| Video normalize | `POST /api/videos/{id}/normalize?case_id=` (`videos.py:174-218`) | GS | None | Validates `video.case_id==case_id` | `video_normalized` | Good case check |
| CV run create/execute | `POST /api/cv/runs` (`cv.py:248-260`, `cv_integration.py:546-569,948-1106`) | GS | None | Strong: case/video/tx/normalized video/hash validated | **No** | State-changing run creation unaudited |
| CV run list/detail/observations | `GET /api/cv/runs...` (`cv.py:263-296`, `cv_integration.py:1154-1172,1246-1255`) | GS | None | Requires case and validates run belongs to case | No | Read-only; scoped |
| CV crop image | `GET /api/cv/runs/{run}/observations/{obs}/crop` (`cv.py:390-409`, `cv_integration.py:1291-1304,1850-1887`) | GS | None | Strong: case/run/obs/crop ID/path containment | No | Read/download unaudited |
| Ad-hoc CV analyze | `POST /api/cv/analyze` (`cv.py:432-515`) | GS | None | Video ID lookup only; case derived from video; no caller case param | **No** | IDOR-style cross-case analysis by known video ID; unaudited |
| Association list | `GET /api/cv/runs/{run}/person-associations` (`cv.py:340-357`, `atm_association.py:636-665`) | GS | None | Run/case validated; `transaction_id` only SQL filter, not validated against case/run | No | Minor filter-scope weakness |
| Best-face selection | `GET /api/cv/runs/{run}/person-associations/{assoc}/best-face` (`cv.py:360-369`, `best_face.py:379-443`) | GS | None | Strong: run/case/association/video/source hash scoped | No | Read-only |
| Face reliability | Computed inside best-face (`face_reliability.py:57-342`, `best_face.py:275,289-307`) | GS | None | Inherits best-face scoping | No | No concealment classification; conservative |
| Association review confirm/reject | `POST /api/cv/person-associations/{id}/review` (`cv.py:372-387`, `atm_association.py:686-724`) | GS | None | Run/case/association triple checked; insufficient evidence blocked. **Body `case_id` not compared to query `case_id`**. | `transaction_person_association_reviewed` | Audit lacks actor; request-scope inconsistency |
| Candidate search | `POST /api/cv/candidates/search` (`cv.py:412-429`, `cv_integration.py:1425-1813`) | GS | None | Strong: case/run/observation/video/source scope, hit revalidation, response budget | `cv_candidate_search` | Good scoping; detail includes IDs/counts |
| Observation/candidate review | `POST/GET review`, `GET reviews` (`cv.py:299-337`, `cv_integration.py:1282-1422`) | GS | None | Strong: body/query/run/obs/case/target validated | create/update audited; reads not | No actor attribution |
| Evidence export create | `POST /api/exports` (`exports.py:17-51`, `export.py:137-358`) | GS | None | Strong: case/frame/CV selection/run/video/hash/review/staleness checks | `report_exported` | Export permission not role-gated |
| Export downloads/lists | `GET /api/exports/frames/archive`, `contact_sheet`, list, pdf, manifest (`exports.py:54-116`) | GS | None | Archive/contact-sheet case-scoped; **PDF/manifest by export_id ID-only**; list unfiltered when no case | archive/contact-sheet audited; pdf/manifest/list not | IDOR/download exposure for export artifacts |
| Case data | cases/tx/notes/links/timeline (`cases.py:19-195`) | GS | None | Mostly case-scoped; `list_links` no `_case_or_404`; note `video_id/frame_id` not validated to case | create/update/archive/tx/note/link audited | Minor integrity/scoping gaps |
| Jobs/frames | jobs/frames endpoints (`jobs.py:32-113`, `frames.py:32-124`) | GS | None | Create paths check case; many read/download/cancel ID-only; lists unfiltered without case | job queued, manual frame, frame updated | IDOR/read/cancel exposure by ID |
| Global search | `GET /api/search?q=` (`cases.py:198-220`) | GS | None | Cross-case by design in current impl | No | Cross-case data discovery |
| System status | `GET /api/system/status` (`system.py:13-34`) | **PUB** | None | None; returns counts + recent audit events across all cases | No | Public sensitive metadata/audit detail exposure |
| Alignment preview | `POST /api/alignment/preview` (`jobs.py:16-29`) | **PUB** | None | Pure computation, no DB | No | Low risk |
| Session | `POST /api/session` (`main.py:50-63`) | **PUB** | n/a | n/a | No | No login/logout/failure audit |

## 4. Endpoint-by-Endpoint Security Findings

| Endpoint | Method | Auth | AuthZ | Scope/IDOR | Audit | Finding |
|---|---|---:|---:|---|---:|---|
| `/` | GET | OUT | None | n/a | No | Public app metadata; acceptable if local-only. |
| `/docs`, `/openapi.json` | GET | OUT | None | n/a | No | **Public when outside `/api`**; exposes full API surface even in secured mode. |
| `/api/session` | POST | PUB | n/a | n/a | No | No rate limit/lockout/audit; deterministic shared token; no logout. |
| `/api/system/status` | GET | PUB | None | Cross-case | No | **Public exposure** of case counts and recent audit events/detail across cases. |
| `/api/alignment/preview` | POST | PUB | None | No DB | No | Low-risk pure computation. |
| `/api/cases` | GET/POST | GS | None | List cross-case | create only | No actor; no per-case authorization. |
| `/api/cases/{case_id}` | GET/PATCH | GS | None | `_case_or_404` | update only | Read unaudited. |
| `/api/cases/{case_id}/archive` | POST | GS | None | `_case_or_404` | Yes | No actor/role check. |
| `/api/cases/{case_id}/transactions` | GET/POST | GS | None | Case checked | add audited | Read unaudited. |
| `/api/cases/{case_id}/notes` | GET/POST | GS | None | Case checked; note `video_id/frame_id` not validated against case | add audited | Potential cross-case note attachment reference. |
| `/api/cases/{case_id}/links` | GET/POST | GS | None | GET has no case existence check; POST validates both videos in case | add audited | Minor inconsistency. |
| `/api/cases/{case_id}/timeline` | GET | GS | None | Case-scoped queries | No | Read unaudited. |
| `/api/search` | GET | GS | None | **Cross-case search** | No | Data discovery across cases. |
| `/api/videos/upload` | POST | GS | None | Case validated after file write | Yes | Orphan file possible on invalid case. |
| `/api/videos` | GET | GS | None | Optional filter; unfiltered cross-case | No | Inventory exposure. |
| `/api/videos/{video_id}` | GET/PATCH | GS | None | **ID-only** | patch only | IDOR/read exposure. |
| `/api/videos/{video_id}/file` | GET | GS | None | **ID-only** + path containment | No | Sensitive evidence download unaudited/IDOR by ID. |
| `/api/videos/{video_id}/verify` | POST | GS | None | **ID-only** | Yes | State/read action by ID. |
| `/api/videos/{video_id}/normalize` | POST | GS | None | Video-case checked | Yes | Better scoped. |
| `/api/jobs` | POST/GET | GS | None | POST validates same-case video+tx; GET unfiltered optional | queued only | List cross-case. |
| `/api/jobs/{job_id}` | GET | GS | None | **ID-only** | No | IDOR/read exposure. |
| `/api/jobs/{job_id}/cancel` | POST | GS | None | **ID-only existence/status** | **No** | Unauthorized/cross-case cancel by ID; unaudited. |
| `/api/alignment/preview` | POST | PUB | None | none | No | Low risk. |
| `/api/frames` | GET | GS | None | Optional filters; unfiltered cross-case | No | Inventory exposure. |
| `/api/frames/manual` | POST | GS | None | Video must belong to case | Yes | Scoped. |
| `/api/frames/compare` | GET | GS | None | **ID-only**, missing IDs skipped | No | IDOR/read exposure. |
| `/api/frames/{frame_id}/image` | GET | GS | None | **ID-only** + containment | No | Evidence image download unaudited. |
| `/api/frames/{frame_id}/thumb` | GET | GS | None | **ID-only** + containment | No | Unaudited. |
| `/api/frames/{frame_id}` | PATCH | GS | None | **ID-only**; audit uses frame.case_id | Yes | Cross-case mutation by ID possible if ID known. |
| `/api/exports` | POST/GET | GS | None | POST strongly case-scoped; GET unfiltered optional | POST audited | List cross-case. |
| `/api/exports/frames/archive` | GET | GS | None | Case+frame IDs validated | Yes | Good scoping. |
| `/api/exports/contact_sheet` | GET | GS | None | Payload builder case-scoped | Yes | Good scoping. |
| `/api/exports/{export_id}/pdf` | GET | GS | None | **ID-only** + containment | No | Export artifact IDOR/download unaudited. |
| `/api/exports/{export_id}/manifest` | GET | GS | None | **ID-only** + containment | No | Manifest contains case/audit/CV provenance; sensitive. |
| `/api/cv/status` | GET | GS | None | No case data | No | Used as auth probe; benign. |
| `/api/cv/embeddings` | GET | GS | None | No case data | No | Benign metadata. |
| `/api/cv/runs` | POST | GS | None | Strong case/video/tx/normalized hash checks | **No** | State-changing; unaudited. |
| `/api/cv/runs` | GET | GS | None | Case required/validated | No | Scoped. |
| `/api/cv/runs/{cv_run_id}` | GET | GS | None | Run-case validated | No | Scoped. |
| `/api/cv/runs/{cv_run_id}/observations` | GET | GS | None | Run-case validated | No | Scoped. |
| `/api/cv/runs/{cv_run_id}/observations/{observation_id}/review` | POST/GET | GS | None | Strong scope; body/query agreement checked on POST | POST audited | No actor; reads unaudited. |
| `/api/cv/runs/{cv_run_id}/reviews` | GET | GS | None | Run-case validated | No | Scoped. |
| `/api/cv/runs/{cv_run_id}/person-associations` | GET | GS | None | Run-case validated; tx filter not case-validated | No | Minor. |
| `/api/cv/runs/{cv_run_id}/person-associations/{association_id}/best-face` | GET | GS | None | Strong run/case/assoc/video/hash scope | No | Scoped. |
| `/api/cv/person-associations/{association_id}/review` | POST | GS | None | Run/case/assoc checked; **body case_id ignored/uncompared** | Yes | Request-scope inconsistency; no actor. |
| `/api/cv/runs/{cv_run_id}/observations/{observation_id}/crop` | GET | GS | None | Strong scope + crop ID/path checks | No | Scoped download unaudited. |
| `/api/cv/candidates/search` | POST | GS | None | Strong case/run/obs/video/hit revalidation | Yes | Good scoping. |
| `/api/cv/analyze` | POST | GS | None | **Video ID only; case derived** | **No** | Cross-case trigger by known video ID; unaudited. |

## 5. Case/Run Isolation Findings

**Strong isolation (data-level):** CV run creation/reads, observation/review scope validation, candidate search/hit revalidation, crop retrieval, association list/review, best-face selection, export CV selection/frame selection, video normalization, job creation same-case check, manual frame capture, clip link same-case check. (`cv_integration.py:546-569,1154-1172,1246-1255,1282-1464,1606-1639,1726-1765,1850-1887`; `atm_association.py:636-700`; `best_face.py:379-416`; `export.py:137-249,325-333`; `videos.py:177-179`; `jobs.py:35-38`; `extraction.py:234`; `cases.py:168-170`)

**Weak/object-ID-only or cross-case patterns:**
- `GET/PATCH /api/videos/{id}`, file, verify (`videos.py:114-171`) - no caller case scope.
- `GET /api/frames`, compare, image, thumb, patch (`frames.py:32-44,59-124`) - ID-only or optional filters.
- `GET /api/jobs`, get, cancel (`jobs.py:88-113`) - ID-only/cross-case list.
- `GET /api/exports`, pdf, manifest (`exports.py:91-116`) - export ID-only downloads/lists.
- `GET /api/search` (`cases.py:198-220`) - cross-case search.
- `POST /api/cv/analyze` (`cv.py:432-437`) - video ID only, derives case.
- `POST /api/cv/person-associations/{id}/review` accepts body `case_id` but handler does not compare it to query case (`schemas.py:724`, `cv.py:376-385`, `atm_association.py:686-724`); face-observation review does compare (`cv_integration.py:1315-1316`).
- `GET /api/cv/runs/{run}/person-associations?transaction_id=` validates run/case but not that `transaction_id` belongs to that case/run (`atm_association.py:642-644`).
- `POST /api/cases/{case_id}/notes` does not validate `video_id/frame_id` belong to case (`cases.py:141-152`).
- `/api/system/status` is public and returns cross-case recent audit events (`main.py:34`, `system.py:16-24,32`).

**IDOR risk note:** Many IDs are UUID4 hex (`security.py:25-26`), reducing guessability but not replacing authorization. Security should be default-deny by authenticated principal + case grant, not ID obscurity.

## 6. Audit-Log Findings

| Area | Finding | Evidence |
|---|---|---|
| Schema | `audit_events(id, case_id nullable/no FK, action, detail_json default {}, created_at)`; no actor/session/IP/outcome/hash/signature. | `backend/app/db.py:131-137` |
| Write helper | Plain insert; `created_at` caller-overridable; no append-only trigger/WORM/hash chain. | `backend/app/db.py:360-364,367-370` |
| Coverage present | case create/update/archive, tx/note/link add, video upload/tags/integrity/normalize, manual frame, frame update, job queued, export/report/archive/contact-sheet, CV review create/update, CV candidate search, association review. | `cases.py:52,73,83,130,151,175`; `videos.py:102,132,161,170,217`; `frames.py:55,123`; `jobs.py:82`; `exports.py:39-50,73,87`; `cv_integration.py:1366-1372,1801-1813`; `atm_association.py:713-724` |
| Coverage gaps | session login/failure/logout (none), CV run create/execute, `/api/cv/analyze`, job cancel, video/frame/crop/export file downloads, export PDF/manifest downloads, most reads/lists, search, timeline, system status reads. | `main.py:50-63`; `cv.py:248-260,432-515`; `jobs.py:109-113`; `exports.py:91-116`; `frames.py:71-88`; `videos.py:136-145`; `cv.py:390-409` |
| Actor attribution | **Missing**. Review decisions store note but no reviewer identity; audit details contain IDs/state only. | `cv_integration.py:1317-1372`; `atm_association.py:713-724`; `test_cv_review.py:333,347-353` |
| Tamper evidence | **Missing**. No hash chain/signature/WORM/DB trigger. Export manifest hashes report payload/PDF but protects only exported snapshot. | `db.py:131-137,360-364`; `export.py:312-358,363,588-610` |
| API/UI exposure | No dedicated audit API/page. `/api/system/status` is **public** and returns recent cross-case audit rows including `detail_json`. Dashboard shows only recent action/time. Exports embed full case audit rows in manifest. | `main.py:34`; `system.py:16-24,32`; `Dashboard.tsx:107-123`; `export.py:324,351`; `exports.py:109-116` |
| Sensitive detail risk | Audit details can include case number, case title/location/status/tags, tx ref, original filename, video tags, search counts/IDs, association tx IDs. No note body/reviewer note observed in audit detail. | `cases.py:52,66-73,130`; `videos.py:102,132`; `cv_integration.py:1805-1811`; `atm_association.py:717-722` |

## 7. Exact Security Gaps and Risks

| ID | Severity | Gap | Impact | Evidence |
|---|---|---|---|---|
| G1 | Critical | No RBAC/users/roles/case grants; shared global passphrase only. | Cannot enforce investigator/reviewer/admin separation or per-case authorization; all actions equivalent. | `main.py:34-63`, `db.py:15-251`, no auth deps |
| G2 | Critical | Default open mode when passphrase unset. | All APIs/data/actions accessible without authentication on local deployment misconfiguration. | `main.py:41,53-54` |
| G3 | High | Object-ID endpoints lack case/principal authorization (videos, frames, jobs, export pdf/manifest, some reads/cancel/patch). | IDOR/cross-case data access or mutation by known/guessed IDs. | `videos.py:114-171`, `frames.py:59-124`, `jobs.py:96-113`, `exports.py:91-116` |
| G4 | High | `/api/system/status` public returns cross-case recent audit events with `detail_json`. | Unauthenticated metadata/case activity leakage. | `main.py:34`, `system.py:16-24,32` |
| G5 | High | `/docs`, `/openapi.json` outside `/api` guard. | API surface disclosure in secured mode. | `main.py:37-47,66-73` |
| G6 | High | Session model weak: deterministic token, no expiry/revocation/logout, no `secure` flag, no CSRF token for cookie-auth state changes. | Stolen/reused cookie persists until passphrase rotation; browser-based CSRF risk if hostile origin can reach local app with cookies in compatible context. | `security.py:93-96`, `main.py:16,62`, no logout |
| G7 | High | Audit log lacks actor attribution, tamper evidence, and full coverage. | Cannot prove who performed review/export/search; incomplete forensic trail. | `db.py:131-137,360-364`, audit write inventory |
| G8 | Medium | State-changing endpoints unaudited: CV run create, `/api/cv/analyze`, job cancel, file downloads. | Accountability gaps for sensitive actions. | `cv.py:248-260,432-515`, `jobs.py:109-113`, download handlers |
| G9 | Medium | Request-scope inconsistencies: association review ignores body `case_id`; tx filter not case-validated; note video/frame refs not case-validated. | Confusing/weak validation; potential cross-case reference integrity issues. | `cv.py:376-385`, `atm_association.py:642-644`, `cases.py:141-152` |
| G10 | Medium | No rate limiting/lockout on session or sensitive endpoints. | Brute-force/local abuse resistance limited. | `main.py:50-63` |
| G11 | Low | File-response security headers inconsistent (crop has nosniff/CSP/no-store; video/frame/export file responses do not). | Minor content-type/cache hardening gap. | `cv.py:401-408` vs `videos.py:145`, `frames.py:78,88`, `exports.py:74,88,106,116` |
| G12 | Low | CORS allows credentials with wildcard methods/headers; defaults localhost only. | Safe by default locally, but risky if origins/env misconfigured. | `main.py:26-32`, `config.py:71-86` |

## 8. Recommended Minimal RBAC Architecture (Proposal Only — Not Implemented)

**Goal:** smallest local-safe model satisfying investigator access control without cloud IdP.

1. **Identity model (local):** Add `users` (id, username, display_name, password_hash argon2/bcrypt, role, active, created_at, last_login_at), `sessions` (id, user_id, token_hash, created_at, expires_at, revoked_at, ip/user_agent optional), optional `case_grants` for case-level assignment. Keep DB local SQLite initially.
2. **Roles (minimum):** `admin` (user/case/settings management), `investigator` (upload/run/search/review/export within assigned cases), `reviewer_supervisor` (review/confirm/reject/export/read within assigned cases; no settings/user mgmt), `auditor_readonly` (read-only case/evidence/audit; no export unless explicitly granted).
3. **AuthN:** Replace shared passphrase with per-user login; server-side random session tokens; `HttpOnly+Secure?+SameSite=Lax`; explicit expiry/idle timeout; logout; password rotation; disable open mode in secured deployments (or make explicit "demo mode" flag).
4. **AuthZ:** FastAPI dependencies for `current_user`, `require_role`, `require_case_access(case_id)`. Default-deny. Every object-ID endpoint must resolve object -> case and check grant/role. Remove/lock down cross-case list/search for non-admins or scope to granted cases.
5. **Review/export controls:** Confirm/reject/candidate review require investigator/reviewer role; export requires explicit permission; downloads audited with actor/case/object.
6. **Audit trail:** Add `actor_user_id`, `actor_role`, `request_id`, `source_ip` (if available), `outcome`, `object_type/id`, immutable append discipline; hash chain or signed checkpoints for tamper evidence; dedicated case-scoped audit API/UI with filters; never expose public cross-case audit feed.
7. **Hardening:** Protect `/docs/openapi` in secured mode or disable in production profile; CSRF token/double-submit or SameSite+origin checks for cookie-auth state changes; rate limit login; uniform security headers on file downloads; redact sensitive audit detail fields.
8. **Migration path:** Keep optional demo mode only for isolated local dev; provide one-time admin bootstrap script/CLI; migrate existing audit rows with `actor_user_id=NULL, actor_type='legacy'`.

## 9. Implementation Priority

| Priority | Item | Rationale |
|---|---|---|
| P0 | Disable/guard open mode for secured deployments; protect `/api/system/status`, `/docs`, `/openapi.json`; add logout/session expiry/server-side sessions | Closes immediate exposure and weak session lifecycle |
| P0 | Introduce authenticated user identity + minimal roles (`admin`, `investigator`, `readonly`) | Prerequisite for all authorization/audit attribution |
| P0 | Add default-deny case authorization dependency on all case/object endpoints; fix ID-only downloads/cancel/patch/search | Closes IDOR/cross-case access |
| P1 | Add actor-attributed audit events for auth, reviews, exports/downloads, CV runs, analyze, cancel, sensitive reads as policy requires | Accountability and forensic trail |
| P1 | Case-scoped audit API/UI; remove public cross-case audit feed; redact sensitive detail | Prevent audit leakage; improve investigator usability |
| P1 | Add CSRF protection, login rate limiting, consistent file response headers | Hardening |
| P2 | Case grants / reviewer-supervisor role / export permission granularity | Finer least-privilege model |
| P2 | Tamper-evident audit hash chain/signatures and retention policy | Stronger evidentiary integrity |

## 10. Exact Verification Results

| Command | Workdir | Result |
|---|---|---|
| `git status --short` | `/Users/yps/Dev/web/atm` | `fatal: not a git repository` (no Git state modified; repo not present) |
| Protected data snapshot (pre-audit check) | `/Users/yps/Dev/web/atm` | `16 files; sha256 e87d1c2a306f3414c64d93761cca80937cf37a6a7af630c36ba1fd5cae6e61c8` |
| `ps -p 90317,90347 -o pid=,command=` | n/a | `90317 uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000`; `90347 vite --host 127.0.0.1 --host 127.0.0.1 --port 5173 --strictPort` |
| `npm run test -- --run src/lib/sessionApi.test.ts src/components/AppShell.test.ts` | `/Users/yps/Dev/web/atm/frontend` | **2 files passed, 13 tests passed** (949ms) |
| `TMPDIR=/Users/yps/Dev/web/atm/reports/ps04cctv-audit/.verification-tmp/p02-pytest PYTHONDONTWRITEBYTECODE=1 /Users/yps/Dev/web/atm/.venv/bin/python -m pytest backend/tests/test_security.py -q --tb=short` | `/Users/yps/Dev/web/atm` | **19 passed in 0.32s** |
| `TMPDIR=.../p02-pytest PYTHONDONTWRITEBYTECODE=1 /Users/yps/Dev/web/atm/.venv/bin/python -m pytest backend/tests/test_cv_review.py backend/tests/test_cv_candidate_search.py backend/tests/test_pipeline.py -k "audit or session or auth" -q --tb=no` | `/Users/yps/Dev/web/atm` | **2 passed, 63 deselected, 1 warning in 0.85s** (StarletteDeprecationWarning) |

**Not run (by scope/safety):** destructive/security exploit tests, DB mutations, user/passphrase changes, service restarts, dependency installs, broad acceptance runner.

## 11. Confirmation of No Modifications

- No source code, schema, frontend, dependency, or config files modified.
- No files created/modified in `data/uploads`, `data/evidence`, `data/exports`, `data/datasets`, `data/models`.
- No database migrations or evidence changes.
- No services restarted; observed PIDs unchanged (`90317`, `90347`).
- No Git operations performed (directory is not a git repo).
- No external network access used.
- This report was written to `reports/ps04cctv-audit/P0-4A-INVESTIGATOR-ACCESS-CONTROL-AUDIT.md` as the audit deliverable.
