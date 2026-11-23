import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { api, ApiError, cvApi, qs } from "../lib/api";
import { formatDate, formatSeconds, fromLocalInput, qualityTone, statusTone } from "../lib/format";
import { demoOptionLabel, isDemoCase, isDemoVideo } from "../lib/demo";
import {
  CV_ASSOCIATION_EVIDENCE_MEANING,
  CV_ASSOCIATION_LIMITATION,
  CV_ASSOCIATION_REVIEW_STATES,
  CV_ATM_ZONE_COORDINATE_CONVENTION,
  CV_CANDIDATE_DISCLAIMER,
  CV_CANDIDATE_SEARCH_SCOPES,
  CV_CANDIDATE_VERIFICATION_STATUS,
  CV_EXPORT_MAX_ITEMS,
  CV_MAX_FRAMES,
  CV_REVIEW_DECISIONS,
  CV_UNSUPPORTED_ATTRIBUTE_STATUS,
  CV_WINDOW_MODES,
} from "../lib/types";
import type {
  AtmInteractionZone,
  CaseRecord,
  CvCandidateSearchResponse,
  CvCandidateSearchScope,
  CvCandidateSummary,
  CvAssociationReviewState,
  CvBestFaceSelectionResponse,
  CvCropSummary,
  CvExportItem,
  CvFaceObservationSummary,
  CvHumanReviewDecision,
  CvPage,
  CvPersonAssociationPage,
  CvReviewDecision,
  CvRunCreateRequest,
  CvRunSummary,
  CvWindowMode,
  TransactionRecord,
  TransactionPersonAssociationRecord,
  VideoRecord,
} from "../lib/types";
import { Alert, Badge, Button, Card, CardHeader, DemoDataBanner, EmptyState, Field, Input, KeyValue, Modal, Select, Textarea } from "../components/ui";
import { CvCropEnhancementPanel } from "../components/CvCropEnhancementPanel";
import { candidateToCvExportItem, cvExportDraftKey, observationToCvExportItem, parseDraftCvItems } from "./Export";

const HISTORY_LIMIT = 25;
const OBSERVATION_LIMIT = 25;
const ASSOCIATION_LIMIT = 25;
const REVIEW_LIMIT = 200;
const CANDIDATE_TOP_K_DEFAULT = 5;
const CANDIDATE_TOP_K_MAX = 25;

function cvHref(caseId: string, runId?: string): string {
  return `/cv${qs({ case: caseId || undefined, run: runId })}`;
}

function isDecision(value: string | null | undefined): value is CvReviewDecision {
  return Boolean(value && (CV_REVIEW_DECISIONS as readonly string[]).includes(value));
}

function isAssociationDecision(value: string | null | undefined): value is Extract<CvAssociationReviewState, "confirmed" | "rejected"> {
  return value === "confirmed" || value === "rejected";
}

function buildAtmZone(form: CvRunFormValues): AtmInteractionZone | null {
  if (!form.atmZoneEnabled) return null;
  return {
    name: form.atmZoneName.trim() || "atm_interaction",
    x: Number(form.atmZoneX),
    y: Number(form.atmZoneY),
    width: Number(form.atmZoneWidth),
    height: Number(form.atmZoneHeight),
  };
}

function atmZoneFieldsValid(form: CvRunFormValues): boolean {
  if (!form.atmZoneEnabled) return true;
  const zone = buildAtmZone(form);
  return Boolean(
    zone
      && [zone.x, zone.y, zone.width, zone.height].every((value) => Number.isFinite(value))
      && zone.x >= 0
      && zone.y >= 0
      && zone.width > 0
      && zone.height > 0
      && zone.x + zone.width <= 1
      && zone.y + zone.height <= 1,
  );
}

export function cvRunFieldsValid(form: CvRunFormValues): boolean {
  const maxFrames = Number(form.maxFrames);
  const frameStride = Number(form.frameStride);
  if (!Number.isInteger(maxFrames) || maxFrames < 1 || maxFrames > CV_MAX_FRAMES) return false;
  if (!Number.isInteger(frameStride) || frameStride < 1 || frameStride > 20) return false;
  if (form.windowMode !== "transaction_aligned") return true;
  const reference = Number(form.cctvReferenceVideoTime);
  const before = Number(form.beforeSeconds);
  const after = Number(form.afterSeconds);
  return Number.isFinite(reference) && reference >= 0
    && Number.isFinite(before) && before >= 0
    && Number.isFinite(after) && after >= 0;
}

export function reviewErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return "This CV run or observation no longer exists. Return to the run history and reload.";
    if (error.status === 409) return "This review was changed elsewhere. Reload the observation and try again.";
    if (error.status === 422) return "The review could not be saved because it was invalid. Check the decision and note.";
    if (error.status === 503) {
      return error.retryAfterSeconds === null
        ? "CV review is temporarily unavailable. Retry shortly."
        : `CV review is temporarily unavailable. Retry in ${error.retryAfterSeconds} seconds.`;
    }
    return error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

export function cvActionErrorMessage(error: unknown, action: string): string {
  if (error instanceof ApiError) {
    if (error.message === "Query embedding unavailable") {
      return "This observation has no usable embedding for candidate search. Choose another observation or create a new indexed CV run.";
    }
    if (error.message === "Query embedding is malformed") {
      return "The selected observation has a malformed embedding. Choose another observation.";
    }
    if (error.message === "Candidate index unavailable" || error.message === "Candidate index is unavailable") {
      return "The candidate index is unavailable. Retry after the local CV service is ready.";
    }
    if (error.status === 503) {
      return error.retryAfterSeconds === null
        ? `${action} is temporarily unavailable. Retry shortly.`
        : `${action} is temporarily unavailable. Retry in ${error.retryAfterSeconds} seconds.`;
    }
    if (error.status === 404) return `${action} could not find the selected case, run, video, or observation. Reload and try again.`;
    if (error.status === 422) return `${action} was rejected. ${error.message}`;
    return error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

export function candidateSearchErrorMessage(error: unknown): string {
  return cvActionErrorMessage(error, "Candidate search");
}

function scopeLabel(scope: CvCandidateSearchScope): string {
  return scope === "case_all_eligible_videos" ? "All eligible case videos" : "Selected case videos";
}

function retrievableCrop(crop: CvCropSummary | null | undefined): string | null {
  if (!crop?.available || crop.status !== "available" || crop.retrieval_state !== "retrievable" || !crop.crop_id) return null;
  return crop.crop_id;
}

export function storeCvExportSelection(caseId: string, item: CvExportItem): void {
  if (typeof window === "undefined" || !caseId) return;
  const key = cvExportDraftKey(caseId);
  const existing = parseDraftCvItems(window.sessionStorage.getItem(key)).filter(
    (current) => current.kind !== item.kind || current.cv_run_id !== item.cv_run_id || current.observation_id !== item.observation_id,
  );
  window.sessionStorage.setItem(key, JSON.stringify([...existing, item].slice(-CV_EXPORT_MAX_ITEMS)));
}

export interface CvRunFormValues {
  videoId: string;
  transactionId: string;
  windowMode: CvWindowMode;
  videoStartTs: string;
  cctvReferenceVideoTime: string;
  beforeSeconds: string;
  afterSeconds: string;
  maxFrames: string;
  frameStride: string;
  saveCrops: boolean;
  addToIndex: boolean;
  atmZoneEnabled: boolean;
  atmZoneName: string;
  atmZoneX: string;
  atmZoneY: string;
  atmZoneWidth: string;
  atmZoneHeight: string;
}

export const initialCvRunFormValues: CvRunFormValues = {
  videoId: "",
  transactionId: "",
  windowMode: "full_video",
  videoStartTs: "",
  cctvReferenceVideoTime: "0",
  beforeSeconds: "20",
  afterSeconds: "20",
  maxFrames: "240",
  frameStride: "1",
  saveCrops: true,
  addToIndex: true,
  atmZoneEnabled: false,
  atmZoneName: "atm_interaction",
  atmZoneX: "0.35",
  atmZoneY: "0.35",
  atmZoneWidth: "0.3",
  atmZoneHeight: "0.3",
};

export function buildCvRunPayload(
  caseId: string,
  form: CvRunFormValues,
  transactions: TransactionRecord[],
): CvRunCreateRequest {
  const payload: CvRunCreateRequest = {
    case_id: caseId,
    video_id: form.videoId,
    max_frames: form.maxFrames === "" ? null : Number(form.maxFrames),
    frame_stride: Number(form.frameStride),
    save_crops: form.saveCrops,
    add_to_index: form.addToIndex,
    rank: false,
    summary_only: false,
    window_mode: form.windowMode,
  };
  if (form.windowMode === "transaction_aligned") {
    const transaction = transactions.find((item) => item.id === form.transactionId);
    payload.transaction_id = form.transactionId || null;
    payload.transaction_ts = transaction?.transaction_ts ?? null;
    payload.cctv_ts = transaction?.cctv_ts ?? null;
    payload.before_seconds = Number(form.beforeSeconds);
    payload.after_seconds = Number(form.afterSeconds);
    payload.video_start_ts = form.videoStartTs ? fromLocalInput(form.videoStartTs) : null;
    payload.cctv_reference_video_time = Number(form.cctvReferenceVideoTime);
    payload.atm_zone = buildAtmZone(form);
  }
  return payload;
}

export interface CvRunHistoryViewProps {
  cases: CaseRecord[];
  caseId: string;
  onCaseChange: (caseId: string) => void;
  runs: CvRunSummary[];
  total: number;
  offset: number;
  limit?: number;
  loading?: boolean;
  error?: string | null;
  onPrevious?: () => void;
  onNext?: () => void;
}

export function CvRunHistoryView({
  cases,
  caseId,
  onCaseChange,
  runs,
  total,
  offset,
  limit = HISTORY_LIMIT,
  loading = false,
  error = null,
  onPrevious,
  onNext,
}: CvRunHistoryViewProps) {
  const first = runs.length ? offset + 1 : 0;
  const last = offset + runs.length;
  return (
    <Card>
      <CardHeader title="CV run history" subtitle="Candidate-only analysis runs, scoped to the selected case" />
      <div className="space-y-4 p-4">
        <Field label="Case" hint="Select a case to list its CV runs.">
          <Select value={caseId} onChange={(event) => onCaseChange(event.target.value)}>
            <option value="">Select case…</option>
            {cases.map((item) => <option key={item.id} value={item.id}>{item.case_number} — {item.title}</option>)}
          </Select>
        </Field>
        {error ? <Alert kind="error">{error}</Alert> : null}
        {loading ? <p className="px-1 py-6 text-center text-xs text-muted">Loading CV runs…</p> : null}
        {!loading && !error && !runs.length ? (
          <EmptyState title="No CV runs yet" detail="Analysis runs for this case will appear here once they have been created." />
        ) : null}
        <div className="divide-y divide-line/60">
          {runs.map((run) => (
            <div key={run.cv_run_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-accent">{run.cv_run_id}</span>
                  <Badge className={statusTone(run.status)}>{run.status}</Badge>
                  <Badge>{run.window_mode}</Badge>
                </div>
                <p className="text-xs text-slate-300">
                  Video {run.video_provenance.source_video_id} · created {formatDate(run.created_at)}
                </p>
                <p className="text-[11px] text-muted">Observations: {run.observation_count ?? "—"}</p>
                {run.status === "failed" ? (
                  <div className="max-w-2xl"><Alert kind="error">Run failed: {run.message || "No detail provided"}</Alert></div>
                ) : run.message ? (
                  <p className="text-[11px] text-muted">{run.message}</p>
                ) : null}
              </div>
              <Link to={cvHref(caseId, run.cv_run_id)}>
                <Button size="sm" variant="primary">Open review <ArrowRight className="h-3.5 w-3.5" /></Button>
              </Link>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
          <span className="text-[11px] text-muted">Showing {first}–{last} of {total} runs (page size {limit})</span>
          <div className="flex gap-2">
            <Button size="sm" onClick={onPrevious} disabled={!offset}>Previous</Button>
            <Button size="sm" onClick={onNext} disabled={last >= total}>Next</Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

export interface CvRunCreateFormProps {
  cases: CaseRecord[];
  caseId: string;
  videos: VideoRecord[];
  transactions: TransactionRecord[];
  form: CvRunFormValues;
  busy?: boolean;
  error?: string | null;
  notice?: string | null;
  onCaseChange: (caseId: string) => void;
  onFormChange: (patch: Partial<CvRunFormValues>) => void;
  onCreate: () => void | Promise<void>;
}

export function CvRunCreateForm({
  cases,
  caseId,
  videos,
  transactions,
  form,
  busy = false,
  error = null,
  notice = null,
  onCaseChange,
  onFormChange,
  onCreate,
}: CvRunCreateFormProps) {
  const caseKnown = cases.some((item) => item.id === caseId);
  const selectedCase = cases.find((item) => item.id === caseId);
  const selectedVideo = videos.find((item) => item.id === form.videoId);
  const videoSelected = Boolean(selectedVideo);
  const transactionSelected = transactions.some((item) => item.id === form.transactionId);
  const canCreate = caseKnown && videoSelected && (form.windowMode === "full_video" || transactionSelected) && atmZoneFieldsValid(form) && cvRunFieldsValid(form) && !busy;
  return (
    <Card>
      <CardHeader title="Start CV candidate analysis" subtitle="Bounded local detection and similarity ranking — results are candidates, never identity confirmation" />
      <div className="space-y-4 p-4">
        {selectedCase && isDemoCase(selectedCase) ? <DemoDataBanner subject="case" /> : null}
        {selectedVideo && isDemoVideo(selectedVideo) ? <DemoDataBanner subject="video" /> : null}
        <Alert>Face detection locates face regions; embedding similarity ranks candidate excerpts only. Reviewers decide relevance; identity is never inferred.</Alert>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Case" hint="Runs are scoped to one case.">
            <Select value={caseId} onChange={(event) => onCaseChange(event.target.value)}>
              <option value="">Select case…</option>
              {cases.map((item) => <option key={item.id} value={item.id}>{demoOptionLabel(`${item.case_number} — ${item.title}`, isDemoCase(item))}</option>)}
            </Select>
          </Field>
          <Field label="Source video" hint="Original video bytes are preserved; analysis is bounded by frame and duration limits.">
            <Select value={form.videoId} onChange={(event) => onFormChange({ videoId: event.target.value })}>
              <option value="">Select video…</option>
              {videos.map((item) => <option key={item.id} value={item.id}>{demoOptionLabel(`${item.original_filename} · ${formatSeconds(item.duration)}`, isDemoVideo(item))}</option>)}
            </Select>
          </Field>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Analysis window">
            <Select value={form.windowMode} onChange={(event) => onFormChange({ windowMode: event.target.value as CvWindowMode })}>
              {CV_WINDOW_MODES.map((mode) => <option key={mode} value={mode}>{mode.replace("_", " ")}</option>)}
            </Select>
          </Field>
          <Field label="Maximum frames" hint={`Local analysis cap: ${CV_MAX_FRAMES} frames.`}><Input type="number" min="1" max={CV_MAX_FRAMES} value={form.maxFrames} onChange={(event) => onFormChange({ maxFrames: event.target.value })} /></Field>
          <Field label="Frame stride"><Input type="number" min="1" max="20" value={form.frameStride} onChange={(event) => onFormChange({ frameStride: event.target.value })} /></Field>
        </div>
        {form.windowMode === "transaction_aligned" ? (
          <div className="grid gap-4 rounded-md border border-line bg-ink-900 p-4 md:grid-cols-2 lg:grid-cols-5">
            <Field label="Transaction">
              <Select value={form.transactionId} onChange={(event) => onFormChange({ transactionId: event.target.value })}>
                <option value="">Select transaction…</option>
                {transactions.map((item) => <option key={item.id} value={item.id}>{item.reference} · {item.transaction_ts}</option>)}
              </Select>
            </Field>
            <Field label="CCTV time at video start" hint="Optional; leave blank to derive from the transaction.">
              <Input type="datetime-local" step="1" value={form.videoStartTs} onChange={(event) => onFormChange({ videoStartTs: event.target.value })} />
            </Field>
            <Field label="CCTV reference point in video (s)" hint="Video time of the CCTV timestamp above.">
              <Input type="number" min="0" step="0.1" value={form.cctvReferenceVideoTime} onChange={(event) => onFormChange({ cctvReferenceVideoTime: event.target.value })} />
            </Field>
            <Field label="Seconds before transaction"><Input type="number" min="0" step="0.5" value={form.beforeSeconds} onChange={(event) => onFormChange({ beforeSeconds: event.target.value })} /></Field>
            <Field label="Seconds after transaction"><Input type="number" min="0" step="0.5" value={form.afterSeconds} onChange={(event) => onFormChange({ afterSeconds: event.target.value })} /></Field>
          </div>
        ) : null}
        {form.windowMode === "transaction_aligned" ? (
          <div className="space-y-3 rounded-md border border-line bg-ink-900 p-4">
            <label className="flex items-center gap-2 text-xs text-slate-200">
              <input type="checkbox" checked={form.atmZoneEnabled} onChange={(event) => onFormChange({ atmZoneEnabled: event.target.checked })} />
              Associate detected people with an ATM interaction zone
            </label>
            <p className="text-[11px] text-muted">{CV_ATM_ZONE_COORDINATE_CONVENTION}</p>
            {form.atmZoneEnabled ? (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
                <Field label="Zone name"><Input value={form.atmZoneName} onChange={(event) => onFormChange({ atmZoneName: event.target.value })} /></Field>
                <Field label="X (0–1)"><Input type="number" min="0" max="1" step="0.01" value={form.atmZoneX} onChange={(event) => onFormChange({ atmZoneX: event.target.value })} /></Field>
                <Field label="Y (0–1)"><Input type="number" min="0" max="1" step="0.01" value={form.atmZoneY} onChange={(event) => onFormChange({ atmZoneY: event.target.value })} /></Field>
                <Field label="Width (0–1)"><Input type="number" min="0" max="1" step="0.01" value={form.atmZoneWidth} onChange={(event) => onFormChange({ atmZoneWidth: event.target.value })} /></Field>
                <Field label="Height (0–1)"><Input type="number" min="0" max="1" step="0.01" value={form.atmZoneHeight} onChange={(event) => onFormChange({ atmZoneHeight: event.target.value })} /></Field>
              </div>
            ) : null}
            <p className="text-[11px] text-muted">Zone, dwell and timing produce a reviewable link hypothesis only. No face, person, account holder or transaction actor is inferred.</p>
          </div>
        ) : (
          <Alert>Full-video mode analyzes the whole clip within the configured frame budget.</Alert>
        )}
        <div className="flex flex-wrap gap-5">
          <label className="flex items-center gap-2 text-xs text-slate-200">
            <input type="checkbox" checked={form.saveCrops} onChange={(event) => onFormChange({ saveCrops: event.target.checked })} />
            Save opaque crop references
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-200">
            <input type="checkbox" checked={form.addToIndex} onChange={(event) => onFormChange({ addToIndex: event.target.checked })} />
            Add eligible observations to the local candidate index
          </label>
        </div>
        {error ? <Alert kind="error">{error}</Alert> : null}
        {notice ? <Alert>{notice}</Alert> : null}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <p className="text-[11px] text-muted">Similarity candidates require human verification. Ranking is not identity confidence or probability, and no identity inference is produced.</p>
          <Button variant="solid" loading={busy} disabled={!canCreate} onClick={() => void onCreate()}>Start candidate analysis</Button>
        </div>
      </div>
    </Card>
  );
}

export interface CvReviewFormProps {
  decision?: CvReviewDecision | null;
  reviewerNote?: string | null;
  savedAt?: string | null;
  saving?: boolean;
  error?: string | null;
  onSave?: (decision: CvReviewDecision, note: string) => void | Promise<void>;
}

export function CvReviewForm({
  decision = null,
  reviewerNote = null,
  savedAt = null,
  saving = false,
  error = null,
  onSave,
}: CvReviewFormProps) {
  const [selected, setSelected] = useState<CvReviewDecision | "">(isDecision(decision) ? decision : "");
  const [note, setNote] = useState(reviewerNote ?? "");
  const isSaved = isDecision(decision);

  return (
    <div className="mt-4 space-y-3 border-t border-line pt-4">
      <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)]">
        <Field label="Review decision" hint="Record your own assessment of this candidate observation.">
          <Select value={selected} onChange={(event) => setSelected(event.target.value as CvReviewDecision | "")}>
            <option value="">Select decision…</option>
            {CV_REVIEW_DECISIONS.map((value) => <option key={value} value={value}>{value}</option>)}
          </Select>
        </Field>
        <Field label="Reviewer note" hint="Optional rationale. Do not record identity claims.">
          <Textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional note about this candidate…" />
        </Field>
      </div>
      {error ? <Alert kind="error">{error}</Alert> : null}
      {isSaved ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-ink-900 px-3 py-2 text-xs">
          <span className="font-semibold uppercase tracking-wider text-muted">Saved review</span>
          <Badge className="text-accent">{decision}</Badge>
          <span className="text-slate-300">{reviewerNote || "No note recorded"}</span>
          {savedAt ? <span className="text-[10px] text-muted">{formatDate(savedAt)}</span> : null}
        </div>
      ) : null}
      <Button
        size="sm"
        variant="primary"
        loading={saving}
        disabled={!selected}
        onClick={() => { if (selected && onSave) void onSave(selected, note); }}
      >
        {isSaved ? "Update review" : "Save review"}
      </Button>
    </div>
  );
}

export function CvBestFaceInspector({ caseId, runId, associationId }: { caseId: string; runId: string; associationId: string }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<CvBestFaceSelectionResponse | null>(null);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError("");
    cvApi.getBestFace(caseId, runId, associationId)
      .then((response) => { if (active) setDetail(response); })
      .catch((reason: Error) => { if (active) setError(cvActionErrorMessage(reason, "Best-face ranking")); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, caseId, runId, associationId]);

  const renderFrame = (frame: CvBestFaceSelectionResponse["ranked_frames"][number], key: string) => (
    <div key={key} className="rounded-md border border-line bg-ink-900 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[11px] text-accent">{frame.observation.observation_id}</p>
        <div className="flex flex-wrap gap-2">
          {frame.rank !== null ? <Badge>rank {frame.rank}</Badge> : null}
          <Badge>{frame.eligible ? "eligible" : "not eligible"}</Badge>
          <Badge>{frame.selection_score.toFixed(4)}</Badge>
          {frame.reliability ? <Badge>reliability: {frame.reliability.status.replaceAll("_", " ")}</Badge> : null}
        </div>
      </div>
      <p className="mt-2 text-[11px] text-slate-300">Frame {frame.observation.original_frame_number} · video time {formatSeconds(frame.observation.original_video_timestamp_seconds)}</p>
      {frame.rationale.length ? <p className="mt-1 text-[11px] text-muted">{frame.rationale.join(" · ")}</p> : null}
      {frame.reason_codes.length ? <p className="mt-1 font-mono text-[10px] text-muted">{frame.reason_codes.join(", ")}</p> : null}
      {frame.reliability ? <p className="mt-1 text-[11px] text-slate-300">{frame.reliability.summary} {frame.reliability.limitation}</p> : null}
      {frame.link ? <p className="mt-1 text-[11px] text-muted">Link: person track {frame.link.person_track_id}, containment {frame.link.bbox_containment_ratio.toFixed(2)} · {frame.link.limitations.join(" · ")}</p> : null}
      {Object.keys(frame.quality_indicators).length ? (
        <p className="mt-1 font-mono text-[10px] text-muted">
          {Object.entries(frame.quality_indicators).map(([name, value]) => `${name}: ${typeof value === "number" ? value.toFixed(2) : value}`).join(" · ")}
        </p>
      ) : null}
    </div>
  );

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>Inspect ranking</Button>
      <Modal open={open} onClose={() => setOpen(false)} title="Best-face ranking detail" wide>
        <div className="space-y-4">
          <p className="text-[11px] leading-relaxed text-muted">{detail?.score_meaning ?? "Quality ranking only. This is not identity evidence."}</p>
          {error ? <Alert kind="error">{error}</Alert> : null}
          {loading ? <p className="text-xs text-muted">Loading ranking detail…</p> : null}
          {detail ? (
            <>
              <Alert>{detail.limitation}</Alert>
              {detail.selected ? (
                <div>
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Selected</p>
                  {renderFrame(detail.selected, "selected")}
                </div>
              ) : <Alert kind="warn">{detail.no_selection_reason ?? "No usable face frame was selected."}</Alert>}
              <div>
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Ranked frames ({detail.ranked_frames.length})</p>
                <div className="space-y-2">{detail.ranked_frames.map((frame, index) => renderFrame(frame, `ranked-${index}`))}</div>
              </div>
              {detail.rejected_frames.length ? (
                <div>
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Rejected frames ({detail.rejected_frames.length})</p>
                  <div className="space-y-2">{detail.rejected_frames.map((frame, index) => renderFrame(frame, `rejected-${index}`))}</div>
                </div>
              ) : null}
              {detail.other_person_frames.length ? (
                <div>
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Other-person frames ({detail.other_person_frames.length})</p>
                  <div className="space-y-2">{detail.other_person_frames.map((frame, index) => renderFrame(frame, `other-${index}`))}</div>
                </div>
              ) : null}
              <p className="text-[11px] text-muted">Reliability is a human-review aid, not identity, biometric match, or suspect-identification evidence.</p>
            </>
          ) : null}
        </div>
      </Modal>
    </>
  );
}

export interface CvAssociationCardProps {
  caseId: string;
  runId: string;
  association: TransactionPersonAssociationRecord;
  saving?: boolean;
  reviewError?: string | null;
  onReview?: (associationId: string, decision: Extract<CvAssociationReviewState, "confirmed" | "rejected">, note: string) => void | Promise<void>;
}

export function CvAssociationCard({
  caseId,
  runId,
  association,
  saving = false,
  reviewError = null,
  onReview,
}: CvAssociationCardProps) {
  const [selected, setSelected] = useState<Extract<CvAssociationReviewState, "confirmed" | "rejected"> | "">(
    isAssociationDecision(association.review_state) ? association.review_state : "",
  );
  const [note, setNote] = useState(association.reviewer_note ?? "");
  const canReview = ["proposed", "confirmed", "rejected"].includes(association.review_state);

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-xs text-accent">{association.association_id}</p>
          <p className="mt-1 text-xs text-slate-300">
            Track {association.person_track_id ?? "none"} · zone {association.zone_id}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge className="border-warn/30 bg-warn/10 text-warn">{association.verification_status}</Badge>
          <Badge>{association.review_state}</Badge>
          <Badge>{association.evidence_strength}</Badge>
        </div>
      </div>

      <div className="mt-3 space-y-2">
        <Alert>{association.association_disclaimer}</Alert>
        <p className="text-[11px] text-muted">{CV_ASSOCIATION_EVIDENCE_MEANING}</p>
      </div>

      {association.best_face ? (
        <div className="mt-3 rounded-md border border-line p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium text-slate-100">Best face frame (quality ranking only)</p>
            <div className="flex flex-wrap items-center gap-2">
              <Badge>{association.best_face.status}</Badge>
              {association.best_face.selected_reliability_status ? (
                <Badge>reliability: {association.best_face.selected_reliability_status.replaceAll("_", " ")}</Badge>
              ) : null}
              <CvBestFaceInspector caseId={caseId} runId={runId} associationId={association.association_id} />
            </div>
          </div>
          {association.best_face.selected_observation_id ? (
            <div className="mt-2 grid gap-x-6 sm:grid-cols-2 lg:grid-cols-4">
              <KeyValue label="Observation" value={association.best_face.selected_observation_id} mono />
              <KeyValue label="Frame" value={association.best_face.selected_frame_number ?? "—"} />
              <KeyValue label="Video time" value={association.best_face.selected_timestamp_seconds === null || association.best_face.selected_timestamp_seconds === undefined ? "—" : formatSeconds(association.best_face.selected_timestamp_seconds)} />
              <KeyValue label="Rank score" value={association.best_face.selected_selection_score === null || association.best_face.selected_selection_score === undefined ? "—" : association.best_face.selected_selection_score.toFixed(4)} />
            </div>
          ) : (
            <div className="mt-2">
              <Alert kind="warn">No usable face frame was selected for this linked person track. This is not an identity conclusion.</Alert>
              <p className="mt-1 font-mono text-[10px] text-muted">{association.best_face.no_selection_reason ?? "no_selection"}</p>
            </div>
          )}
          {association.best_face.selected_reliability_summary ? (
            <p className="mt-2 text-[11px] text-slate-300">
              Reliability (human visual review): {association.best_face.selected_reliability_summary}
            </p>
          ) : null}
          <p className="mt-2 text-[11px] text-slate-300">
            Ranked {association.best_face.ranked_frame_count} · rejected {association.best_face.rejected_frame_count} · other people {association.best_face.other_person_frame_count}
          </p>
          <p className="mt-1 text-[11px] text-muted">{association.best_face.score_meaning}</p>
          <p className="mt-1 text-[11px] text-muted">{association.best_face.limitation}</p>
          <p className="mt-1 text-[11px] text-muted">Reliability is not identity, biometric match, or suspect-identification evidence; mask/helmet/cap are not assessed.</p>
        </div>
      ) : null}

      <div className="mt-4 grid gap-x-6 sm:grid-cols-2 lg:grid-cols-3">
        <KeyValue label="Heuristic score" value={association.heuristic_score.toFixed(4)} />
        <KeyValue label="Dwell" value={formatSeconds(association.dwell_seconds)} />
        <KeyValue label="Zone frames" value={association.zone_frame_count} />
        <KeyValue label="Window overlap" value={formatSeconds(association.transaction_window_overlap_seconds)} />
        <KeyValue label="First in zone" value={association.first_video_timestamp_seconds === null ? "—" : formatSeconds(association.first_video_timestamp_seconds)} />
        <KeyValue label="Last in zone" value={association.last_video_timestamp_seconds === null ? "—" : formatSeconds(association.last_video_timestamp_seconds)} />
        <KeyValue label="Transaction video time" value={association.transaction_video_seconds === null ? "—" : formatSeconds(association.transaction_video_seconds)} />
        <KeyValue label="Analysis window" value={`${formatSeconds(association.window_start_seconds)} – ${formatSeconds(association.window_end_seconds)}`} />
        <KeyValue label="Source video" value={association.video_provenance.source_video_id} mono />
      </div>

      {association.reviewer_note ? (
        <p className="mt-3 text-[11px] text-slate-300">Reviewer note: {association.reviewer_note}</p>
      ) : null}

      {canReview ? (
        <div className="mt-4 space-y-3 border-t border-line pt-4">
          <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)]">
            <Field label="Association review" hint="Record a case-review outcome, never an identity conclusion.">
              <Select value={selected} onChange={(event) => setSelected(event.target.value as Extract<CvAssociationReviewState, "confirmed" | "rejected"> | "")}>
                <option value="">Select decision…</option>
                {CV_ASSOCIATION_REVIEW_STATES.filter((value) => value === "confirmed" || value === "rejected").map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </Select>
            </Field>
            <Field label="Reviewer note" hint="Optional rationale. Do not record identity claims.">
              <Textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Optional note about the observed zone and timing…" />
            </Field>
          </div>
          {reviewError ? <Alert kind="error">{reviewError}</Alert> : null}
          <Button size="sm" variant="primary" loading={saving} disabled={!selected} onClick={() => {
            if (selected && onReview) void onReview(association.association_id, selected, note);
          }}>Save association review</Button>
        </div>
      ) : (
        <div className="mt-4 border-t border-line pt-4">
          <Alert kind="warn">No person track crossed the zone with enough evidence for review. This is not a conclusion that no person was present.</Alert>
        </div>
      )}
      <p className="mt-3 font-mono text-[10px] text-muted">Run {runId} · case {caseId}</p>
    </Card>
  );
}

export interface CvObservationCardProps {
  caseId: string;
  runId: string;
  observation: CvFaceObservationSummary;
  review?: CvHumanReviewDecision | null;
  saving?: boolean;
  reviewError?: string | null;
  onSaveReview?: (observationId: string, decision: CvReviewDecision, note: string) => void | Promise<void>;
  querySelectable?: boolean;
  selectedAsQuery?: boolean;
  onSelectQuery?: (observation: CvFaceObservationSummary) => void;
}

export function CvObservationCard({
  caseId,
  runId,
  observation,
  review = null,
  saving = false,
  reviewError = null,
  onSaveReview,
  querySelectable = false,
  selectedAsQuery = false,
  onSelectQuery,
}: CvObservationCardProps) {
  const [cropFailed, setCropFailed] = useState(false);
  const crop = observation.crop;
  const cropId = retrievableCrop(crop);
  const showCrop = Boolean(cropId);
  const flags = observation.review_flags;
  const heuristics = [
    { label: "Low sharpness", active: flags.low_sharpness },
    { label: "Underexposed", active: flags.underexposed },
    { label: "Overexposed", active: flags.overexposed },
    { label: "Small face", active: flags.small_face },
    { label: "Pose away", active: flags.pose_away },
    { label: "Possible partial occlusion", active: flags.partial_occlusion_suspected },
    { label: "Occlusion review", active: flags.occlusion_review },
  ];

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-xs text-accent">Frame {observation.original_frame_number}</p>
          <p className="mt-1 text-xs text-muted">Original video time {formatSeconds(observation.original_video_timestamp_seconds)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {onSelectQuery ? (
            <label className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs ${selectedAsQuery ? "border-accent/50 bg-accent/10 text-accent" : "border-line text-muted"}`}>
              <input
                type="radio"
                name={`cv-query-${runId}`}
                checked={selectedAsQuery}
                disabled={!querySelectable}
                onChange={() => onSelectQuery(observation)}
              />
              Use as similarity query
            </label>
          ) : null}
          <Button size="sm" variant="ghost" onClick={() => {
            const item = observationToCvExportItem(observation);
            if (item) storeCvExportSelection(caseId, item);
          }}>Select for export</Button>
          <Badge className="border-warn/30 bg-warn/10 text-warn">{CV_CANDIDATE_VERIFICATION_STATUS}</Badge>
          <Badge>face observation</Badge>
        </div>
      </div>

      <div className="mt-3 space-y-2">
        <Alert>{CV_CANDIDATE_DISCLAIMER}</Alert>
        <Alert>{CV_ASSOCIATION_LIMITATION}</Alert>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
        <div>
          {showCrop && !cropFailed ? (
            <img
              src={cvApi.cropUrl(caseId, runId, observation.observation_id, cropId as string)}
              alt={`Crop for frame ${observation.original_frame_number}`}
              className="w-full rounded border border-line bg-black"
              onError={() => setCropFailed(true)}
            />
          ) : (
            <div className="grid min-h-[160px] place-items-center rounded border border-dashed border-line bg-ink-900 px-3 text-center text-xs text-muted">
              Crop unavailable
            </div>
          )}
          <p className="mt-1.5 text-[10px] text-muted">Opaque crop reference only — no file path is shown.</p>
          {showCrop && cropId ? (
            <CvCropEnhancementPanel
              caseId={caseId}
              runId={runId}
              observationId={observation.observation_id}
              cropId={cropId}
            />
          ) : null}
        </div>
        <div className="grid gap-x-6 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Quality metrics</p>
            <KeyValue label="Quality score" value={<span className={qualityTone(observation.quality.quality_score)}>{observation.quality.quality_score}</span>} />
            <KeyValue label="Sharpness" value={observation.quality.sharpness} />
            <KeyValue label="Brightness" value={observation.quality.brightness} />
            <KeyValue label="Contrast" value={observation.quality.contrast} />
            <KeyValue label="Detected face (px)" value={observation.quality.face_size_px} />
            <KeyValue label="Crop size (px)" value={observation.quality.crop_size_px ?? "—"} />
            <KeyValue label="Crop status" value={observation.crop.status} />
          </div>
          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Pose proxies</p>
            <KeyValue label="Roll proxy (deg)" value={observation.pose.roll_proxy_deg ?? "—"} />
            <KeyValue label="Yaw proxy" value={observation.pose.yaw_proxy ?? "—"} />
            <KeyValue label="Pitch proxy" value={observation.pose.pitch_proxy ?? "—"} />
            <KeyValue label="Frontal score" value={observation.pose.frontal_score} />
          </div>
        </div>
      </div>

      <div className="mt-4 space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Heuristic review flags — signals only, not conclusions</p>
        <div className="flex flex-wrap gap-2">
          {heuristics.filter((item) => item.active).map((item) => (
            <Badge key={item.label} className="border-warn/30 bg-warn/10 text-warn">{item.label}</Badge>
          ))}
          {!heuristics.some((item) => item.active) ? <span className="text-xs text-muted">No heuristic flags raised</span> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {(["mask", "helmet", "cap"] as const).map((attribute) => (
            <Badge key={attribute}>{attribute}: {CV_UNSUPPORTED_ATTRIBUTE_STATUS.replace("_", " ")}</Badge>
          ))}
        </div>
        {observation.quality.warnings.length ? (
          <p className="text-[11px] text-muted">Quality warnings: {observation.quality.warnings.join(" · ")}</p>
        ) : null}
        {observation.pose.warnings.length ? (
          <p className="text-[11px] text-muted">Pose warnings: {observation.pose.warnings.join(" · ")}</p>
        ) : null}
      </div>

      <CvReviewForm
        key={`${observation.observation_id}-${review?.decision_id ?? "none"}-${review?.updated_at ?? review?.created_at ?? "none"}`}
        decision={review?.decision ?? null}
        reviewerNote={review?.reviewer_note ?? null}
        savedAt={review?.updated_at ?? review?.created_at ?? null}
        saving={saving}
        error={reviewError}
        onSave={(decision, note) => onSaveReview ? onSaveReview(observation.observation_id, decision, note) : undefined}
      />
    </Card>
  );
}

export interface CvCandidateCardProps {
  caseId: string;
  candidate: CvCandidateSummary;
  reviewerNote?: string | null;
  saving?: boolean;
  reviewError?: string | null;
  onReview?: (candidate: CvCandidateSummary, decision: CvReviewDecision, note: string) => void | Promise<void>;
}

export function CvCandidateCard({
  caseId,
  candidate,
  reviewerNote = null,
  saving = false,
  reviewError = null,
  onReview,
}: CvCandidateCardProps) {
  const [cropFailed, setCropFailed] = useState(false);
  const cropId = retrievableCrop(candidate.candidate_crop);
  const flags = candidate.candidate_review_flags;
  const heuristics = flags ? [
    { label: "Low sharpness", active: flags.low_sharpness },
    { label: "Underexposed", active: flags.underexposed },
    { label: "Overexposed", active: flags.overexposed },
    { label: "Small face", active: flags.small_face },
    { label: "Pose away", active: flags.pose_away },
    { label: "Possible partial occlusion", active: flags.partial_occlusion_suspected },
    { label: "Occlusion review", active: flags.occlusion_review },
  ] : [];

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-xs text-accent">Rank {candidate.rank} · similarity score {candidate.similarity_score.toFixed(4)} · not identity confidence</p>
          <p className="mt-1 text-xs text-slate-300">
            Video {candidate.candidate_video_provenance.source_video_id} · frame {candidate.candidate_original_frame_number} · {formatSeconds(candidate.candidate_original_video_timestamp_seconds)}
          </p>
          <p className="mt-1 font-mono text-[10px] text-muted">{candidate.candidate_observation_id}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="ghost" onClick={() => {
            const item = candidateToCvExportItem(candidate);
            if (item) storeCvExportSelection(caseId, item);
          }}>Select for export</Button>
          <Badge className="border-warn/30 bg-warn/10 text-warn">{candidate.verification_status}</Badge>
          {candidate.human_review_status ? <Badge className="text-accent">review: {candidate.human_review_status}</Badge> : null}
        </div>
      </div>

      <div className="mt-3 space-y-2">
        <Alert>{candidate.candidate_disclaimer}</Alert>
        <Alert>{CV_ASSOCIATION_LIMITATION}</Alert>
        <p className="text-[11px] text-muted">Score meaning: {candidate.score_meaning}</p>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
        <div>
          {cropId && !cropFailed ? (
            <img
              src={cvApi.cropUrl(caseId, candidate.candidate_cv_run_id, candidate.candidate_observation_id, cropId)}
              alt={`Candidate crop for frame ${candidate.candidate_original_frame_number}`}
              className="w-full rounded border border-line bg-black"
              onError={() => setCropFailed(true)}
            />
          ) : (
            <div className="grid min-h-[160px] place-items-center rounded border border-dashed border-line bg-ink-900 px-3 text-center text-xs text-muted">
              Crop unavailable
            </div>
          )}
          <p className="mt-1.5 text-[10px] text-muted">
            Crop state: {candidate.candidate_crop?.retrieval_state ?? "not_supported"}
          </p>
        </div>
        <div className="space-y-3">
          {candidate.candidate_quality ? (
            <div className="grid gap-x-6 sm:grid-cols-2">
              <div>
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Candidate quality</p>
                <KeyValue label="Quality score" value={<span className={qualityTone(candidate.candidate_quality.quality_score)}>{candidate.candidate_quality.quality_score}</span>} />
                <KeyValue label="Sharpness" value={candidate.candidate_quality.sharpness} />
                <KeyValue label="Brightness" value={candidate.candidate_quality.brightness} />
                <KeyValue label="Detected face (px)" value={candidate.candidate_quality.face_size_px} />
                <KeyValue label="Crop size (px)" value={candidate.candidate_quality.crop_size_px ?? "—"} />
              </div>
              <div>
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Candidate flags</p>
                {heuristics.filter((item) => item.active).length ? (
                  <div className="flex flex-wrap gap-2">
                    {heuristics.filter((item) => item.active).map((item) => (
                      <Badge key={item.label} className="border-warn/30 bg-warn/10 text-warn">{item.label}</Badge>
                    ))}
                  </div>
                ) : <p className="text-xs text-muted">No heuristic flags raised</p>}
                {(["mask", "helmet", "cap"] as const).map((attribute) => (
                  <Badge key={attribute} className="mr-1 mt-2">{attribute}: {CV_UNSUPPORTED_ATTRIBUTE_STATUS.replace("_", " ")}</Badge>
                ))}
              </div>
            </div>
          ) : (
            <Alert kind="warn">Candidate quality and review-flag summaries are unavailable for this record.</Alert>
          )}
          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Model provenance</p>
            <div className="flex flex-wrap gap-2">
              {candidate.model_provenance.map((model) => (
                <Badge key={`${model.model_key}-${model.model_sha256}`} className="normal-case tracking-normal">
                  {model.model_key} · schema {model.embedding_schema_version} · {model.runtime_state} · {model.model_sha256.slice(0, 12)}
                </Badge>
              ))}
            </div>
          </div>
        </div>
      </div>

      <CvReviewForm
        key={`candidate-${candidate.candidate_observation_id}-${candidate.human_review_status ?? "none"}-${saving ? "saving" : "idle"}`}
        decision={candidate.human_review_status ?? null}
        reviewerNote={reviewerNote}
        saving={saving}
        error={reviewError}
        onSave={(decision, note) => onReview ? onReview(candidate, decision, note) : undefined}
      />
    </Card>
  );
}

export interface CvCandidateSearchPanelProps {
  caseId: string;
  runId: string;
  videos: VideoRecord[];
  queryObservation: CvFaceObservationSummary | null;
  querySourceVideoId: string;
  scope: CvCandidateSearchScope;
  sourceVideoIds: string[];
  topK: string;
  result: CvCandidateSearchResponse | null;
  loading?: boolean;
  error?: string | null;
  notice?: string | null;
  savingId?: string | null;
  reviewNotes?: Record<string, string>;
  reviewError?: string | null;
  onScopeChange: (scope: CvCandidateSearchScope) => void;
  onSourceVideoToggle: (videoId: string) => void;
  onTopKChange: (value: string) => void;
  onSearch: () => void | Promise<void>;
  onReview?: (candidate: CvCandidateSummary, decision: CvReviewDecision, note: string) => void | Promise<void>;
}

export function CvCandidateSearchPanel({
  caseId,
  runId,
  videos,
  queryObservation,
  querySourceVideoId,
  scope,
  sourceVideoIds,
  topK,
  result,
  loading = false,
  error = null,
  notice = null,
  savingId = null,
  reviewNotes = {},
  reviewError = null,
  onScopeChange,
  onSourceVideoToggle,
  onTopKChange,
  onSearch,
  onReview,
}: CvCandidateSearchPanelProps) {
  const maxTopK = result?.limits.max_top_k ?? CANDIDATE_TOP_K_MAX;
  const availableVideos = videos.filter((video) => video.id !== querySourceVideoId);
  const canSearch = Boolean(queryObservation) && (scope !== "case_selected_videos" || sourceVideoIds.length > 0) && !loading;
  const scan = result?.limits.candidate_scan;

  return (
    <Card>
      <CardHeader title="Candidate search" subtitle="Similarity candidates only; reviewers make every assessment" />
      <div className="space-y-4 p-4">
        {!queryObservation ? (
          <EmptyState title="Select a query observation" detail="Choose a face observation above, then search for candidate-only similarity results." />
        ) : (
          <>
            <Alert>{CV_CANDIDATE_DISCLAIMER}</Alert>
            <div className="grid gap-4 md:grid-cols-3">
              <Field label="Query observation">
                <Input value={queryObservation.observation_id} readOnly />
              </Field>
              <Field label="Scope">
                <Select value={scope} onChange={(event) => onScopeChange(event.target.value as CvCandidateSearchScope)}>
                  {CV_CANDIDATE_SEARCH_SCOPES.map((value) => <option key={value} value={value}>{scopeLabel(value)}</option>)}
                </Select>
              </Field>
              <Field label="Maximum candidates" hint={`Case limit: ${maxTopK}`}>
                <Input type="number" min="1" max={maxTopK} value={topK} onChange={(event) => onTopKChange(event.target.value)} />
              </Field>
            </div>
            {scope === "case_selected_videos" ? (
              <div className="space-y-2 rounded-md border border-line bg-ink-900 p-3">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Candidate source videos</p>
                {availableVideos.length ? (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {availableVideos.map((video) => (
                      <label key={video.id} className="flex items-center gap-2 text-xs text-slate-200">
                        <input
                          type="checkbox"
                          checked={sourceVideoIds.includes(video.id)}
                          onChange={() => onSourceVideoToggle(video.id)}
                        />
                        <span className="truncate">{video.original_filename} <span className="font-mono text-[10px] text-muted">{video.id}</span></span>
                      </label>
                    ))}
                  </div>
                ) : <p className="text-xs text-muted">No other videos are available in this case.</p>}
                <p className="text-[11px] text-muted">The query source video is excluded automatically.</p>
              </div>
            ) : (
              <Alert>All eligible videos in this case are searched. The query source video is excluded automatically.</Alert>
            )}
            {error ? <Alert kind="error">{error}</Alert> : null}
            {notice ? <Alert>{notice}</Alert> : null}
            <div className="flex justify-end"><Button variant="solid" loading={loading} disabled={!canSearch} onClick={() => void onSearch()}>Search candidates</Button></div>
          </>
        )}

        {result ? (
          <div className="space-y-4">
            <Card className="p-4">
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted">Scan diagnostics</p>
              <div className="grid gap-x-6 sm:grid-cols-2 lg:grid-cols-3">
                <KeyValue label="Candidates returned" value={`${result.count} of requested ${result.limit}`} />
                <KeyValue label="Scope" value={scopeLabel(result.scope)} />
                <KeyValue label="Source videos" value={result.source_video_ids.length ? result.source_video_ids.join(", ") : "all eligible case videos"} />
                <KeyValue label="Scan limit" value={scan?.limit ?? "—"} />
                <KeyValue label="Scanned" value={scan?.scanned ?? "—"} />
                <KeyValue label="Truncated" value={scan ? (scan.truncated ? "yes" : "no") : "—"} />
                <KeyValue label="Stop reason" value={scan?.reason ?? "—"} />
                <KeyValue label="Index generation" value={result.index.generation} />
                <KeyValue label="Index schema" value={result.index.schema_version} />
                <KeyValue label="Index records" value={result.index.record_count} />
                <KeyValue label="Known provenance" value={result.index.provenance.known} />
                <KeyValue label="Legacy unknown" value={result.index.provenance.legacy_unknown} />
              </div>
              <div className="mt-3 space-y-2">
                <Alert>{result.disclaimer}</Alert>
                <p className="text-[11px] text-muted">{result.score_meaning} Similarity scores are not identity confidence or probability.</p>
              </div>
            </Card>

            {result.items.length ? (
              <div className="space-y-4">
                {result.items.map((candidate) => (
                  <CvCandidateCard
                    key={candidate.candidate_id}
                    caseId={caseId}
                    candidate={candidate}
                    reviewerNote={reviewNotes[candidate.candidate_observation_id] ?? null}
                    saving={savingId === candidate.candidate_observation_id}
                    reviewError={savingId === candidate.candidate_observation_id ? reviewError : null}
                    onReview={onReview}
                  />
                ))}
              </div>
            ) : (
              <EmptyState title="No similarity candidates" detail="No eligible, indexed candidates crossed the search filters. This is not an identity conclusion." />
            )}
          </div>
        ) : null}

        {result ? <p className="text-[10px] text-muted">Run {runId} · query case {caseId}</p> : null}
      </div>
    </Card>
  );
}

export interface CvRunDetailViewProps {
  caseId: string;
  runId: string;
  run: CvRunSummary | null;
  observations: CvFaceObservationSummary[];
  reviews: CvHumanReviewDecision[];
  associations?: CvPersonAssociationPage | null;
  associationOffset?: number;
  totalObservations: number;
  offset: number;
  limit?: number;
  loading?: boolean;
  error?: string | null;
  onPrevious?: () => void;
  onNext?: () => void;
  savingId?: string | null;
  reviewError?: string | null;
  reviewNotice?: string | null;
  associationSavingId?: string | null;
  associationReviewError?: string | null;
  associationReviewNotice?: string | null;
  onAssociationPrevious?: () => void;
  onAssociationNext?: () => void;
  onSaveReview?: (observationId: string, decision: CvReviewDecision, note: string) => void | Promise<void>;
  onReviewAssociation?: (associationId: string, decision: Extract<CvAssociationReviewState, "confirmed" | "rejected">, note: string) => void | Promise<void>;
  queryObservation?: CvFaceObservationSummary | null;
  onSelectQuery?: (observation: CvFaceObservationSummary) => void;
  videos?: VideoRecord[];
  candidateScope?: CvCandidateSearchScope;
  candidateSourceVideoIds?: string[];
  candidateTopK?: string;
  candidateResult?: CvCandidateSearchResponse | null;
  candidateLoading?: boolean;
  candidateError?: string | null;
  candidateNotice?: string | null;
  candidateSavingId?: string | null;
  candidateReviewNotes?: Record<string, string>;
  candidateReviewError?: string | null;
  onCandidateScopeChange?: (scope: CvCandidateSearchScope) => void;
  onCandidateSourceVideoToggle?: (videoId: string) => void;
  onCandidateTopKChange?: (value: string) => void;
  onSearchCandidates?: () => void | Promise<void>;
  onReviewCandidate?: (candidate: CvCandidateSummary, decision: CvReviewDecision, note: string) => void | Promise<void>;
}

export function CvRunDetailView({
  caseId,
  runId,
  run,
  observations,
  reviews,
  associations = null,
  associationOffset = 0,
  totalObservations,
  offset,
  limit = OBSERVATION_LIMIT,
  loading = false,
  error = null,
  onPrevious,
  onNext,
  savingId = null,
  reviewError = null,
  reviewNotice = null,
  associationSavingId = null,
  associationReviewError = null,
  associationReviewNotice = null,
  onAssociationPrevious,
  onAssociationNext,
  onSaveReview,
  onReviewAssociation,
  queryObservation = null,
  onSelectQuery,
  videos = [],
  candidateScope = "case_all_eligible_videos",
  candidateSourceVideoIds = [],
  candidateTopK = String(CANDIDATE_TOP_K_DEFAULT),
  candidateResult = null,
  candidateLoading = false,
  candidateError = null,
  candidateNotice = null,
  candidateSavingId = null,
  candidateReviewNotes = {},
  candidateReviewError = null,
  onCandidateScopeChange = () => undefined,
  onCandidateSourceVideoToggle = () => undefined,
  onCandidateTopKChange = () => undefined,
  onSearchCandidates = () => undefined,
  onReviewCandidate = () => undefined,
}: CvRunDetailViewProps) {
  const byTarget = new Map<string, CvHumanReviewDecision>();
  for (const review of reviews) {
    if (!byTarget.has(review.target_id)) byTarget.set(review.target_id, review);
  }
  const first = observations.length ? offset + 1 : 0;
  const last = offset + observations.length;
  const associationFirst = associations?.items.length ? associationOffset + 1 : 0;
  const associationLast = associationOffset + (associations?.items.length ?? 0);
  const querySelectable = run?.status === "completed" || run?.status === "completed_with_warnings";
  const querySourceVideoId = run?.video_provenance.source_video_id ?? queryObservation?.video_provenance.source_video_id ?? "";

  return (
    <div className="space-y-5">
      <div><Link to={cvHref(caseId)}><Button size="sm" variant="ghost"><ArrowLeft className="h-3.5 w-3.5" /> Back to CV runs</Button></Link></div>
      {error ? <Alert kind="error">{error}</Alert> : null}
      {reviewError ? <Alert kind="error">{reviewError}</Alert> : null}
      {reviewNotice ? <Alert>{reviewNotice}</Alert> : null}
      {associationReviewError ? <Alert kind="error">{associationReviewError}</Alert> : null}
      {associationReviewNotice ? <Alert>{associationReviewNotice}</Alert> : null}

      {run ? (
        <>
          <Card>
            <CardHeader title="CV run" subtitle={`Analysis ${run.analysis_run_id}`} action={<Badge className={statusTone(run.status)}>{run.status}</Badge>} />
            <div className="grid gap-x-6 p-4 sm:grid-cols-2 lg:grid-cols-3">
              <KeyValue label="Run" value={run.cv_run_id} mono />
              <KeyValue label="Window mode" value={run.window_mode} />
              <KeyValue label="Video" value={run.video_provenance.source_video_id} mono />
              <KeyValue label="Transaction" value={run.transaction_id ?? "—"} mono />
              <KeyValue label="Created" value={formatDate(run.created_at)} />
              <KeyValue label="Started" value={formatDate(run.started_at)} />
              <KeyValue label="Finished" value={formatDate(run.finished_at)} />
              <KeyValue label="Frames analyzed" value={run.budget.analyzed_frames} />
              <KeyValue label="Message" value={run.message || "—"} />
            </div>
            <div className="border-t border-line px-4 py-3">
              <p className="text-[11px] leading-relaxed text-muted">
                The transaction ID is alignment metadata only. It does not identify or associate any detected face, person or track with the ATM operator or transaction actor.
              </p>
            </div>
            <div className="space-y-2 border-t border-line px-4 py-3">
              {run.warnings.length ? <Alert kind="warn">Warnings: {run.warnings.join(" · ")}</Alert> : null}
              {run.truncation.truncated ? (
                <Alert kind="warn">
                  Analysis output truncated: {run.truncation.face_observations_omitted} face observations, {run.truncation.person_observations_omitted} person observations, {run.truncation.ranking_candidates_omitted} candidates and {run.truncation.frames_omitted} frames omitted.
                  {run.truncation.reasons.length ? ` ${run.truncation.reasons.join(" · ")}` : ""}
                </Alert>
              ) : (
                <p className="text-[11px] text-muted">Analysis output complete — no truncation reported.</p>
              )}
            </div>
          </Card>

          {run.window && run.window_mode === "transaction_aligned" ? (
            <Card>
              <CardHeader title="Transaction-aligned window" subtitle="Derived analysis window in source-video time" />
              <div className="grid gap-x-6 p-4 sm:grid-cols-2 lg:grid-cols-3">
                <KeyValue label="Mode" value={run.window.mode} />
                <KeyValue label="Start" value={formatSeconds(run.window.start_seconds)} />
                <KeyValue label="End" value={formatSeconds(run.window.end_seconds)} />
                <KeyValue label="Duration" value={formatSeconds(run.window.duration_seconds)} />
                <KeyValue label="Source duration" value={formatSeconds(run.window.source_video_duration_seconds)} />
                <KeyValue label="Before / after" value={`${run.window.before_seconds ?? "—"} / ${run.window.after_seconds ?? "—"}`} />
                <KeyValue label="Clamped" value={run.window.clamped ? "yes" : "no"} />
                <KeyValue label="Full video" value={run.window.is_full_video ? "yes" : "no"} />
              </div>
              {run.window.warnings.length ? (
                <div className="border-t border-line px-4 py-3"><Alert kind="warn">Window warnings: {run.window.warnings.join(" · ")}</Alert></div>
              ) : null}
            </Card>
          ) : null}

          {run.timestamp_provenance ? (
            <Card>
              <CardHeader title="Timestamp provenance" subtitle="All times resolved to source-video seconds" />
              <div className="grid gap-x-6 p-4 sm:grid-cols-2 lg:grid-cols-3">
                <KeyValue label="Timebase" value={run.timestamp_provenance.timebase} />
                <KeyValue label="Transaction UTC" value={run.timestamp_provenance.transaction_utc ?? "—"} />
                <KeyValue label="CCTV clock UTC" value={run.timestamp_provenance.cctv_clock_utc ?? "—"} />
                <KeyValue label="Offset (s)" value={run.timestamp_provenance.applied_alignment_offset_seconds ?? "—"} />
                <KeyValue label="Alignment source" value={run.timestamp_provenance.alignment_source ?? "—"} />
                <KeyValue label="Transaction video time" value={run.timestamp_provenance.transaction_video_seconds === null || run.timestamp_provenance.transaction_video_seconds === undefined ? "—" : formatSeconds(run.timestamp_provenance.transaction_video_seconds)} />
                <KeyValue label="Window start" value={formatSeconds(run.timestamp_provenance.window_start_seconds)} />
                <KeyValue label="Window end" value={formatSeconds(run.timestamp_provenance.window_end_seconds)} />
              </div>
              {run.timestamp_provenance.warnings.length ? (
                <div className="border-t border-line px-4 py-3"><Alert kind="warn">Timestamp warnings: {run.timestamp_provenance.warnings.join(" · ")}</Alert></div>
              ) : null}
            </Card>
          ) : null}

          {run.model_provenance?.length ? (
            <Card>
              <CardHeader title="Model provenance" subtitle="Runtime and checksum evidence recorded for this run" />
              <div className="space-y-3 p-4">
                {run.model_provenance.map((model) => (
                  <div key={`${model.model_key}-${model.model_sha256}`} className="rounded border border-line p-3">
                    <p className="font-mono text-xs text-accent">{model.model_key} · {model.runtime_state}</p>
                    <p className="mt-1 text-[11px] text-muted">{model.model_filename}</p>
                    <p className="mt-1 break-all font-mono text-[10px] text-muted">{model.model_sha256}</p>
                    <p className="mt-1 text-[10px] text-muted">{model.backend} / {model.target} · OpenCV {model.opencv_version}</p>
                  </div>
                ))}
              </div>
            </Card>
          ) : null}
        </>
      ) : null}

      <Card>
        <CardHeader title="Face observations" subtitle="Candidate-only records requiring human verification" />
        <div className="space-y-4 p-4">
          {loading ? <p className="py-6 text-center text-xs text-muted">Loading observations…</p> : null}
          {!loading && !observations.length ? (
            <EmptyState title="No face observations" detail="This page has no face observations to review." />
          ) : null}
          <div className="space-y-4">
            {observations.map((observation) => (
              <CvObservationCard
                key={observation.observation_id}
                caseId={caseId}
                runId={runId}
                observation={observation}
                review={byTarget.get(observation.observation_id) ?? null}
                saving={savingId === observation.observation_id}
                reviewError={savingId === observation.observation_id ? reviewError : null}
                onSaveReview={onSaveReview}
                querySelectable={querySelectable}
                selectedAsQuery={queryObservation?.observation_id === observation.observation_id}
                onSelectQuery={onSelectQuery}
              />
            ))}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
            <span className="text-[11px] text-muted">Showing {first}–{last} of {totalObservations} observations (page size {limit})</span>
            <div className="flex gap-2">
              <Button size="sm" onClick={onPrevious} disabled={!offset}>Previous</Button>
              <Button size="sm" onClick={onNext} disabled={last >= totalObservations}>Next</Button>
            </div>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title="Transaction-person associations" subtitle="Reviewable link hypotheses from zone, dwell and timing evidence" />
        <div className="space-y-4 p-4">
          <Alert>{CV_ASSOCIATION_LIMITATION}</Alert>
          {loading ? <p className="py-6 text-center text-xs text-muted">Loading associations…</p> : null}
          {!loading && !associations?.items.length ? (
            <EmptyState title="No transaction-person associations" detail="This run produced no association records to review. This is not a conclusion that no person was present." />
          ) : null}
          <div className="space-y-4">
            {associations?.items.map((association) => (
              <CvAssociationCard
                key={`${association.association_id}:${association.review_state}:${association.reviewed_at ?? ""}`}
                caseId={caseId}
                runId={runId}
                association={association}
                saving={associationSavingId === association.association_id}
                reviewError={associationSavingId === association.association_id ? associationReviewError : null}
                onReview={onReviewAssociation}
              />
            ))}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
            <span className="text-[11px] text-muted">Showing {associationFirst}–{associationLast} of {associations?.total ?? 0} associations</span>
            <div className="flex gap-2">
              <Button size="sm" onClick={onAssociationPrevious} disabled={!associationOffset}>Previous</Button>
              <Button size="sm" onClick={onAssociationNext} disabled={associationLast >= (associations?.total ?? 0)}>Next</Button>
            </div>
          </div>
        </div>
      </Card>

      <CvCandidateSearchPanel
        caseId={caseId}
        runId={runId}
        videos={videos}
        queryObservation={queryObservation}
        querySourceVideoId={querySourceVideoId}
        scope={candidateScope}
        sourceVideoIds={candidateSourceVideoIds}
        topK={candidateTopK}
        result={candidateResult}
        loading={candidateLoading}
        error={candidateError}
        notice={candidateNotice}
        savingId={candidateSavingId}
        reviewNotes={candidateReviewNotes}
        reviewError={candidateReviewError}
        onScopeChange={onCandidateScopeChange}
        onSourceVideoToggle={onCandidateSourceVideoToggle}
        onTopKChange={onCandidateTopKChange}
        onSearch={onSearchCandidates}
        onReview={onReviewCandidate}
      />
    </div>
  );
}

export function CvRunsPage() {
  const [params, setParams] = useSearchParams();
  const caseId = params.get("case") ?? "";
  const runId = params.get("run") ?? "";
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [videos, setVideos] = useState<VideoRecord[]>([]);
  const [transactions, setTransactions] = useState<TransactionRecord[]>([]);
  const [createForm, setCreateForm] = useState<CvRunFormValues>(initialCvRunFormValues);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");
  const [createNotice, setCreateNotice] = useState("");
  const [history, setHistory] = useState<CvPage<CvRunSummary>>({ items: [], total: 0, limit: HISTORY_LIMIT, offset: 0 });
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [run, setRun] = useState<CvRunSummary | null>(null);
  const [observations, setObservations] = useState<CvPage<CvFaceObservationSummary>>({ items: [], total: 0, limit: OBSERVATION_LIMIT, offset: 0 });
  const [observationOffset, setObservationOffset] = useState(0);
  const [reviews, setReviews] = useState<CvHumanReviewDecision[]>([]);
  const [associations, setAssociations] = useState<CvPersonAssociationPage>({ items: [], total: 0, limit: ASSOCIATION_LIMIT, offset: 0, status: "insufficient_evidence", disclaimer: CV_ASSOCIATION_LIMITATION });
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [reviewError, setReviewError] = useState("");
  const [reviewNotice, setReviewNotice] = useState("");
  const [associationOffset, setAssociationOffset] = useState(0);
  const [associationSavingId, setAssociationSavingId] = useState<string | null>(null);
  const [associationReviewError, setAssociationReviewError] = useState("");
  const [associationReviewNotice, setAssociationReviewNotice] = useState("");
  const [queryObservation, setQueryObservation] = useState<CvFaceObservationSummary | null>(null);
  const [candidateScope, setCandidateScope] = useState<CvCandidateSearchScope>("case_all_eligible_videos");
  const [candidateSourceVideoIds, setCandidateSourceVideoIds] = useState<string[]>([]);
  const [candidateTopK, setCandidateTopK] = useState(String(CANDIDATE_TOP_K_DEFAULT));
  const [candidateResult, setCandidateResult] = useState<CvCandidateSearchResponse | null>(null);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [candidateError, setCandidateError] = useState("");
  const [candidateNotice, setCandidateNotice] = useState("");
  const [candidateSavingId, setCandidateSavingId] = useState<string | null>(null);
  const [candidateReviewNotes, setCandidateReviewNotes] = useState<Record<string, string>>({});
  const [candidateReviewError, setCandidateReviewError] = useState("");

  useEffect(() => {
    let active = true;
    api.get<CaseRecord[]>("/api/cases")
      .then((data) => { if (active) setCases(data); })
      .catch((reason: Error) => { if (active) setHistoryError(reason.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    setCreateForm(initialCvRunFormValues);
    setCandidateResult(null);
    setQueryObservation(null);
    if (!caseId) {
      setVideos([]);
      setTransactions([]);
      return;
    }
    Promise.all([
      api.get<VideoRecord[]>(`/api/videos${qs({ case_id: caseId })}`),
      api.get<TransactionRecord[]>(`/api/cases/${caseId}/transactions`),
    ]).then(([videoList, transactionList]) => {
      if (!active) return;
      setVideos(videoList);
      setTransactions(transactionList);
    }).catch((reason: Error) => { if (active) setCreateError(reason.message); });
    return () => { active = false; };
  }, [caseId]);

  useEffect(() => {
    if (!videos.length) return;
    setCreateForm((current) => current.videoId ? current : { ...current, videoId: videos[0].id });
  }, [videos]);

  useEffect(() => { setHistoryOffset(0); }, [caseId]);
  useEffect(() => { setObservationOffset(0); setAssociationOffset(0); }, [caseId, runId]);

  useEffect(() => {
    if (runId || !caseId) {
      setHistory({ items: [], total: 0, limit: HISTORY_LIMIT, offset: 0 });
      return;
    }
    let active = true;
    setHistoryLoading(true);
    setHistoryError("");
    cvApi.listRuns(caseId, { limit: HISTORY_LIMIT, offset: historyOffset })
      .then((page) => {
        if (active) setHistory({
          items: page.items ?? [],
          total: page.total ?? 0,
          limit: page.limit ?? HISTORY_LIMIT,
          offset: page.offset ?? historyOffset,
        });
      })
      .catch((reason: Error) => { if (active) setHistoryError(reason.message); })
      .finally(() => { if (active) setHistoryLoading(false); });
    return () => { active = false; };
  }, [caseId, runId, historyOffset]);

  useEffect(() => {
    if (!runId || !caseId) {
      setRun(null);
      setObservations({ items: [], total: 0, limit: OBSERVATION_LIMIT, offset: 0 });
      setReviews([]);
      setAssociations({ items: [], total: 0, limit: ASSOCIATION_LIMIT, offset: 0, status: "insufficient_evidence", disclaimer: CV_ASSOCIATION_LIMITATION });
      setQueryObservation(null);
      setCandidateResult(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setDetailError("");
    setReviewNotice("");
    Promise.all([
      cvApi.getRun(caseId, runId),
      cvApi.getObservations(caseId, runId, { limit: OBSERVATION_LIMIT, offset: observationOffset }),
      cvApi.listReviews(caseId, runId, { limit: REVIEW_LIMIT, offset: 0 }),
      cvApi.listPersonAssociations(caseId, runId, { limit: ASSOCIATION_LIMIT, offset: associationOffset }),
    ])
      .then(([detail, observationPage, reviewPage, associationPage]) => {
        if (!active) return;
        setRun(detail);
        setObservations({
          items: observationPage.items ?? [],
          total: observationPage.total ?? 0,
          limit: observationPage.limit ?? OBSERVATION_LIMIT,
          offset: observationPage.offset ?? observationOffset,
        });
        setReviews(reviewPage.items ?? []);
        setAssociations({
          items: associationPage.items ?? [],
          total: associationPage.total ?? 0,
          limit: associationPage.limit ?? ASSOCIATION_LIMIT,
          offset: associationPage.offset ?? associationOffset,
          status: associationPage.status ?? "insufficient_evidence",
          disclaimer: associationPage.disclaimer ?? CV_ASSOCIATION_LIMITATION,
        });
      })
      .catch((reason: Error) => { if (active) setDetailError(reason.message); })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [caseId, runId, observationOffset, associationOffset]);

  const changeCase = (nextCase: string) => {
    setHistoryError("");
    setCreateError("");
    setCreateNotice("");
    setCandidateError("");
    setCandidateNotice("");
    setParams(nextCase ? { case: nextCase } : {});
  };

  const createRun = async () => {
    if (!caseId || !createForm.videoId) return;
    setCreateBusy(true);
    setCreateError("");
    setCreateNotice("");
    try {
      const created = await cvApi.createRun(buildCvRunPayload(caseId, createForm, transactions));
      setRun(created.run);
      setObservations({
        items: created.observations.items ?? [],
        total: created.observations.total ?? 0,
        limit: created.observations.limit ?? OBSERVATION_LIMIT,
        offset: 0,
      });
      setAssociations(created.associations ?? { items: [], total: 0, limit: ASSOCIATION_LIMIT, offset: 0, status: "insufficient_evidence", disclaimer: CV_ASSOCIATION_LIMITATION });
      setReviews([]);
      setQueryObservation(null);
      setCandidateResult(null);
      setCreateNotice(`CV run ${created.run.cv_run_id} finished with status ${created.run.status}.`);
      setParams({ case: caseId, run: created.run.cv_run_id });
    } catch (reason) {
      setCreateError(cvActionErrorMessage(reason, "CV analysis"));
    } finally {
      setCreateBusy(false);
    }
  };

  const saveReview = async (observationId: string, decision: CvReviewDecision, note: string) => {
    if (!caseId || !runId) return;
    setSavingId(observationId);
    setReviewError("");
    setReviewNotice("");
    try {
      const saved = await cvApi.upsertReview(caseId, runId, observationId, {
        case_id: caseId,
        cv_run_id: runId,
        target_type: "face_observation",
        decision,
        reviewer_note: note.trim() ? note : null,
      });
      setReviews((previous) => [saved, ...previous.filter((item) => item.target_id !== observationId)]);
      setReviewNotice("Review saved. The updated decision is shown on this observation.");
    } catch (reason) {
      setReviewError(reviewErrorMessage(reason));
    } finally {
      setSavingId(null);
    }
  };

  const reviewAssociation = async (
    associationId: string,
    decision: Extract<CvAssociationReviewState, "confirmed" | "rejected">,
    note: string,
  ) => {
    if (!caseId || !runId) return;
    setAssociationSavingId(associationId);
    setAssociationReviewError("");
    setAssociationReviewNotice("");
    try {
      const saved = await cvApi.reviewPersonAssociation(caseId, associationId, {
        case_id: caseId,
        cv_run_id: runId,
        decision,
        reviewer_note: note.trim() ? note : null,
      });
      setAssociations((previous) => ({
        ...previous,
        items: previous.items.map((item) => item.association_id === associationId ? saved : item),
      }));
      setAssociationReviewNotice("Association review saved. This is a case-review outcome, not an identity conclusion.");
    } catch (reason) {
      setAssociationReviewError(reviewErrorMessage(reason));
    } finally {
      setAssociationSavingId(null);
    }
  };

  const selectQuery = (observation: CvFaceObservationSummary) => {
    setQueryObservation(observation);
    setCandidateResult(null);
    setCandidateError("");
    setCandidateNotice("");
  };

  const invalidateCandidateResults = () => {
    setCandidateResult(null);
    setCandidateError("");
    setCandidateNotice("");
  };

  const changeCandidateScope = (scope: CvCandidateSearchScope) => {
    setCandidateScope(scope);
    invalidateCandidateResults();
  };

  const toggleSourceVideo = (videoId: string) => {
    setCandidateSourceVideoIds((previous) => previous.includes(videoId)
      ? previous.filter((item) => item !== videoId)
      : [...previous, videoId]);
    invalidateCandidateResults();
  };

  const changeCandidateTopK = (value: string) => {
    setCandidateTopK(value);
    invalidateCandidateResults();
  };

  const searchCandidates = async () => {
    if (!caseId || !runId || !queryObservation) return;
    const max = candidateResult?.limits.max_top_k ?? CANDIDATE_TOP_K_MAX;
    const topK = Math.min(max, Math.max(1, Number(candidateTopK) || CANDIDATE_TOP_K_DEFAULT));
    setCandidateTopK(String(topK));
    setCandidateLoading(true);
    setCandidateError("");
    setCandidateNotice("");
    setCandidateReviewError("");
    try {
      const result = await cvApi.searchCandidates({
        case_id: caseId,
        query_cv_run_id: runId,
        query_observation_id: queryObservation.observation_id,
        top_k: topK,
        scope: candidateScope,
        source_video_ids: candidateScope === "case_selected_videos" ? candidateSourceVideoIds : [],
      });
      setCandidateResult(result);
      setCandidateNotice(`Scanned ${result.limits.candidate_scan.scanned} indexed records for ${result.count} similarity candidates.`);
    } catch (reason) {
      setCandidateResult(null);
      setCandidateError(candidateSearchErrorMessage(reason));
    } finally {
      setCandidateLoading(false);
    }
  };

  const reviewCandidate = async (
    candidate: CvCandidateSummary,
    decision: CvReviewDecision,
    note: string,
  ) => {
    setCandidateSavingId(candidate.candidate_observation_id);
    setCandidateReviewError("");
    setCandidateNotice("");
    try {
      const saved = await cvApi.upsertReview(
        caseId,
        candidate.candidate_cv_run_id,
        candidate.candidate_observation_id,
        {
          case_id: caseId,
          cv_run_id: candidate.candidate_cv_run_id,
          target_type: "face_observation",
          decision,
          reviewer_note: note.trim() ? note : null,
        },
      );
      setCandidateResult((previous) => previous ? {
        ...previous,
        items: previous.items.map((item) => item.candidate_observation_id === candidate.candidate_observation_id
          ? { ...item, human_review_status: saved.decision }
          : item),
      } : previous);
      setCandidateReviewNotes((previous) => ({ ...previous, [candidate.candidate_observation_id]: note }));
      setCandidateNotice("Candidate review saved. This does not establish identity or an ATM-operator association.");
    } catch (reason) {
      setCandidateReviewError(reviewErrorMessage(reason));
    } finally {
      setCandidateSavingId(null);
    }
  };

  const caseKnown = cases.some((item) => item.id === caseId);
  const historyErrorText = caseId && cases.length > 0 && !caseKnown
    ? "The selected case is unavailable. Choose a case before starting or reviewing CV runs."
    : historyError;

  return (
    <div className="mx-auto max-w-[1500px] space-y-5">
      <Alert>{CV_CANDIDATE_DISCLAIMER}</Alert>
      <Alert>{CV_ASSOCIATION_LIMITATION}</Alert>
      {!runId && !caseId && cases.length > 0 ? <Alert kind="warn">Select a case to start or review CV runs. No case is selected automatically.</Alert> : null}
      {!runId && caseId && cases.length > 0 && !caseKnown ? <Alert kind="warn">{historyErrorText}</Alert> : null}
      {runId ? (
        <CvRunDetailView
          caseId={caseId}
          runId={runId}
          run={run}
          observations={observations.items}
          reviews={reviews}
          totalObservations={observations.total}
          offset={observations.offset}
          limit={observations.limit}
          loading={detailLoading}
          error={detailError}
          onPrevious={() => setObservationOffset(Math.max(0, observationOffset - observations.limit))}
          onNext={() => setObservationOffset(observationOffset + observations.limit)}
          savingId={savingId}
          reviewError={reviewError}
          reviewNotice={reviewNotice}
          associations={associations}
          associationOffset={associationOffset}
          associationSavingId={associationSavingId}
          associationReviewError={associationReviewError}
          associationReviewNotice={associationReviewNotice}
          onAssociationPrevious={() => setAssociationOffset(Math.max(0, associationOffset - ASSOCIATION_LIMIT))}
          onAssociationNext={() => setAssociationOffset(associationOffset + ASSOCIATION_LIMIT)}
          onSaveReview={saveReview}
          onReviewAssociation={reviewAssociation}
          queryObservation={queryObservation}
          onSelectQuery={selectQuery}
          videos={videos}
          candidateScope={candidateScope}
          candidateSourceVideoIds={candidateSourceVideoIds}
          candidateTopK={candidateTopK}
          candidateResult={candidateResult}
          candidateLoading={candidateLoading}
          candidateError={candidateError}
          candidateNotice={candidateNotice}
          candidateSavingId={candidateSavingId}
          candidateReviewNotes={candidateReviewNotes}
          candidateReviewError={candidateReviewError}
          onCandidateScopeChange={changeCandidateScope}
          onCandidateSourceVideoToggle={toggleSourceVideo}
          onCandidateTopKChange={changeCandidateTopK}
          onSearchCandidates={searchCandidates}
          onReviewCandidate={reviewCandidate}
        />
      ) : (
        <>
          <CvRunCreateForm
            cases={cases}
            caseId={caseId}
            videos={videos}
            transactions={transactions}
            form={createForm}
            busy={createBusy}
            error={createError}
            notice={createNotice}
            onCaseChange={changeCase}
            onFormChange={(patch) => setCreateForm((current) => ({ ...current, ...patch }))}
            onCreate={createRun}
          />
          <CvRunHistoryView
            cases={cases}
            caseId={caseId}
            onCaseChange={changeCase}
            runs={history.items}
            total={history.total}
            offset={history.offset}
            limit={history.limit}
            loading={historyLoading}
            error={historyErrorText}
            onPrevious={() => setHistoryOffset(Math.max(0, historyOffset - history.limit))}
            onNext={() => setHistoryOffset(historyOffset + history.limit)}
          />
        </>
      )}
    </div>
  );
}
