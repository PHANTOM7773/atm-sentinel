import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Download, FileArchive, FileJson, FileText, Fingerprint, LayoutGrid } from "lucide-react";
import { api, cvApi, qs } from "../lib/api";
import { formatDate, formatSeconds } from "../lib/format";
import { demoOptionLabel, isDemoCase } from "../lib/demo";
import {
  CV_ASSOCIATION_LIMITATION,
  CV_CANDIDATE_DISCLAIMER,
  CV_EXPORT_ITEM_KINDS,
  CV_EXPORT_MAX_ITEMS,
  CV_EXPORT_SELECTION_KEY,
} from "../lib/types";
import type {
  CaseRecord,
  CvCandidateSummary,
  CvExportItem,
  CvFaceObservationSummary,
  CvRunSummary,
  ExportRecord,
  ExportRequestPayload,
  FrameRecord,
} from "../lib/types";
import { Alert, Badge, Button, Card, CardHeader, DemoDataBanner, EmptyState, Field, Select } from "../components/ui";

function opaqueId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 120 && !/[\/\\:\0]/.test(value) && !value.includes("..");
}

function finiteInRange(value: unknown, min: number, max: number): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
}

function integerInRange(value: unknown, min: number, max: number): value is number {
  return finiteInRange(value, min, max) && Number.isInteger(value);
}

function dedupeCvItems(items: CvExportItem[]): CvExportItem[] {
  const seen = new Set<string>();
  const result: CvExportItem[] = [];
  for (const item of items) {
    const key = `${item.kind}:${item.cv_run_id}:${item.observation_id}`;
    if (!seen.has(key) && result.length < CV_EXPORT_MAX_ITEMS) {
      seen.add(key);
      result.push(item);
    }
  }
  return result;
}

export function normalizeCvExportItem(value: unknown): CvExportItem | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  if (!CV_EXPORT_ITEM_KINDS.includes(raw.kind as CvExportItem["kind"])) return null;
  if (!opaqueId(raw.cv_run_id) || !opaqueId(raw.observation_id)) return null;
  const kind = raw.kind as CvExportItem["kind"];
  const item: CvExportItem = { kind, cv_run_id: raw.cv_run_id, observation_id: raw.observation_id };
  if (typeof raw.expected_review_updated_at === "string" && Number.isFinite(Date.parse(raw.expected_review_updated_at))) {
    item.expected_review_updated_at = raw.expected_review_updated_at;
  }
  if (typeof raw.expected_model_sha256 === "string" && /^[0-9a-f]{64}$/.test(raw.expected_model_sha256)) {
    item.expected_model_sha256 = raw.expected_model_sha256;
  }
  if (kind === "candidate") {
    if (!opaqueId(raw.query_cv_run_id) || !opaqueId(raw.query_observation_id)) return null;
    if (!raw.selection_context || typeof raw.selection_context !== "object") return null;
    const context = raw.selection_context as Record<string, unknown>;
    if (!integerInRange(context.rank, 1, CV_EXPORT_MAX_ITEMS)) return null;
    if (!finiteInRange(context.similarity_score, -1, 1)) return null;
    item.query_cv_run_id = raw.query_cv_run_id;
    item.query_observation_id = raw.query_observation_id;
    if (opaqueId(raw.candidate_id)) item.candidate_id = raw.candidate_id;
    item.selection_context = {
      rank: context.rank,
      similarity_score: context.similarity_score,
      score_meaning: typeof context.score_meaning === "string" ? context.score_meaning.slice(0, 400) : undefined,
      candidate_disclaimer: typeof context.candidate_disclaimer === "string" ? context.candidate_disclaimer.slice(0, 400) : undefined,
    };
  }
  return item;
}

export function parseDraftCvItems(raw: string | null): CvExportItem[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return dedupeCvItems(parsed.map(normalizeCvExportItem).filter((item): item is CvExportItem => Boolean(item)));
  } catch {
    return [];
  }
}

export function observationToCvExportItem(observation: CvFaceObservationSummary): CvExportItem | null {
  return normalizeCvExportItem({
    kind: "observation",
    cv_run_id: observation.cv_run_id,
    observation_id: observation.observation_id,
  });
}

export function candidateToCvExportItem(candidate: CvCandidateSummary): CvExportItem | null {
  return normalizeCvExportItem({
    kind: "candidate",
    cv_run_id: candidate.candidate_cv_run_id,
    observation_id: candidate.candidate_observation_id,
    query_cv_run_id: candidate.query_cv_run_id,
    query_observation_id: candidate.query_observation_id,
    candidate_id: candidate.candidate_id,
    selection_context: {
      rank: candidate.rank,
      similarity_score: candidate.similarity_score,
      score_meaning: candidate.score_meaning,
      candidate_disclaimer: candidate.candidate_disclaimer || CV_CANDIDATE_DISCLAIMER,
    },
  });
}

export function buildExportPayload(caseId: string, frameIds: string[], cvItems: CvExportItem[] = []): ExportRequestPayload {
  const payload: ExportRequestPayload = { case_id: caseId, frame_ids: [...frameIds] };
  const normalized = dedupeCvItems(cvItems.map(normalizeCvExportItem).filter((item): item is CvExportItem => Boolean(item)));
  if (normalized.length) payload.cv_items = normalized;
  return payload;
}

export function cvExportDraftKey(caseId: string): string {
  return `${CV_EXPORT_SELECTION_KEY}:${caseId}`;
}

export function ExportPage() {
  const [params, setParams] = useSearchParams();
  const caseParam = params.get("case") ?? "";
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [caseId, setCaseId] = useState(caseParam);
  const [frames, setFrames] = useState<FrameRecord[]>([]);
  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [latest, setLatest] = useState<ExportRecord | null>(null);
  const [generatedFrameIds, setGeneratedFrameIds] = useState<string[]>([]);
  const [cvRuns, setCvRuns] = useState<CvRunSummary[]>([]);
  const [cvRunId, setCvRunId] = useState("");
  const [cvObservations, setCvObservations] = useState<CvFaceObservationSummary[]>([]);
  const [draftCvItems, setDraftCvItems] = useState<CvExportItem[]>([]);
  const [selectedObservationIds, setSelectedObservationIds] = useState<string[]>([]);
  const [cvLoading, setCvLoading] = useState(false);
  const [cvError, setCvError] = useState("");

  useEffect(() => {
    api.get<CaseRecord[]>("/api/cases").then((data) => {
      setCases(data);
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    setCaseId(caseParam);
    setFrames([]);
    setExports([]);
    setLatest(null);
    setGeneratedFrameIds([]);
    setNotice("");
    setError("");
    setCvRuns([]);
    setCvRunId("");
    setCvObservations([]);
    setDraftCvItems([]);
    setSelectedObservationIds([]);
    setCvError("");
  }, [caseParam]);

  const selectCase = (nextCase: string) => {
    setCaseId(nextCase);
    setLatest(null);
    setGeneratedFrameIds([]);
    setNotice("");
    setError("");
    setParams(nextCase ? { case: nextCase } : {});
  };

  const load = () => {
    if (!caseId) return;
    Promise.all([
      api.get<FrameRecord[]>(`/api/frames${qs({ case_id: caseId })}`),
      api.get<ExportRecord[]>(`/api/exports${qs({ case_id: caseId })}`),
    ]).then(([frame, exported]) => {
      setFrames(frame);
      setExports(exported);
    }).catch((reason: Error) => setError(reason.message));
  };

  useEffect(load, [caseId]);

  useEffect(() => {
    setCvError("");
    setCvRunId("");
    setCvObservations([]);
    setSelectedObservationIds([]);
    if (!caseId) {
      setCvRuns([]);
      setDraftCvItems([]);
      return;
    }
    const raw = typeof window === "undefined" ? null : window.sessionStorage.getItem(cvExportDraftKey(caseId));
    setDraftCvItems(parseDraftCvItems(raw));
    setCvLoading(true);
    cvApi.listRuns(caseId, { limit: CV_EXPORT_MAX_ITEMS, offset: 0 })
      .then((page) => setCvRuns(page.items))
      .catch((reason: Error) => setCvError(reason.message))
      .finally(() => setCvLoading(false));
  }, [caseId]);

  useEffect(() => {
    setCvObservations([]);
    setSelectedObservationIds([]);
    if (!caseId || !cvRunId) return;
    setCvLoading(true);
    cvApi.getObservations(caseId, cvRunId, { limit: CV_EXPORT_MAX_ITEMS, offset: 0 })
      .then((page) => setCvObservations(page.items))
      .catch((reason: Error) => setCvError(reason.message))
      .finally(() => setCvLoading(false));
  }, [caseId, cvRunId]);

  const selected = frames.filter((frame) => frame.selected);
  const inFormCvItems = cvObservations
    .filter((observation) => selectedObservationIds.includes(observation.observation_id))
    .map(observationToCvExportItem)
    .filter((item): item is CvExportItem => Boolean(item));
  const cvItems = dedupeCvItems([...draftCvItems, ...inFormCvItems]);
  const caseKnown = cases.some((item) => item.id === caseId);
  const selectedCase = cases.find((item) => item.id === caseId);

  const generate = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.post<ExportRecord>(
        "/api/exports",
        buildExportPayload(caseId, selected.map((frame) => frame.id), cvItems),
      );
      setLatest(result);
      setGeneratedFrameIds(selected.map((frame) => frame.id));
      setNotice(cvItems.length ? `PDF report and JSON manifest generated with ${cvItems.length} CV reference(s)` : "PDF report and JSON manifest generated");
      if (typeof window !== "undefined") window.sessionStorage.removeItem(cvExportDraftKey(caseId));
      setDraftCvItems([]);
      setSelectedObservationIds([]);
      load();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1320px] space-y-5">
      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert>{notice}</Alert> : null}
      {caseParam && cases.length > 0 && !caseKnown ? <Alert kind="warn">The selected case is unavailable. Choose a case before generating a report.</Alert> : null}
      {selectedCase && isDemoCase(selectedCase) ? <DemoDataBanner subject="case" /> : null}
      <Card>
        <CardHeader title="Generate forensic evidence report" subtitle="Report includes case, transaction, video metadata, alignment, frames, quality metrics, notes, hashes, audit history and explicitly selected CV references" />
        <div className="space-y-4 p-5">
          <Field label="Case" className="max-w-xl"><Select value={caseId} onChange={(event) => selectCase(event.target.value)}><option value="">Select case…</option>{cases.map((item) => <option key={item.id} value={item.id}>{demoOptionLabel(`${item.case_number} — ${item.title}`, isDemoCase(item))}</option>)}</Select></Field>
          <p className="text-[11px] leading-relaxed text-muted">No CV candidate results are included unless you explicitly select them. Included CV references are reviewer context only, are not identity evidence, and do not identify the ATM operator or transaction participant. Candidate similarity must not be represented as identity confirmation.</p>
          {cvError ? <Alert kind="warn">CV references could not be loaded: {cvError}</Alert> : null}
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Optional CV references ({cvItems.length})</p>
            <p className="mb-3 text-[11px] leading-relaxed text-muted">{CV_ASSOCIATION_LIMITATION}</p>
            {draftCvItems.length ? (
              <div className="mb-3 flex flex-wrap gap-2">
                {draftCvItems.map((item) => (
                  <div key={`${item.kind}:${item.cv_run_id}:${item.observation_id}`} className="flex items-center gap-2 rounded border border-line bg-ink-900 p-2">
                    <Badge>{item.kind}</Badge>
                    <span className="font-mono text-[10px] text-accent">{item.observation_id}</span>
                    <button
                      type="button"
                      className="text-[10px] text-muted underline hover:text-slate-200"
                      onClick={() => setDraftCvItems((previous) => previous.filter((candidate) => candidate.observation_id !== item.observation_id || candidate.cv_run_id !== item.cv_run_id))}
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            ) : null}
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
              <Field label="CV run (optional)" className="max-w-xl">
                <Select value={cvRunId} onChange={(event) => setCvRunId(event.target.value)}>
                  <option value="">No CV run selected</option>
                  {cvRuns.map((run) => <option key={run.cv_run_id} value={run.cv_run_id}>{run.cv_run_id} · {run.status}</option>)}
                </Select>
              </Field>
              <div>
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Observations in selected run</p>
                {cvLoading ? <p className="text-[11px] text-muted">Loading CV references…</p> : null}
                {!cvRunId ? <p className="text-[11px] text-muted">Select a CV run to include individual face observations.</p> : null}
                {cvRunId && !cvObservations.length && !cvLoading ? <p className="text-[11px] text-muted">No observations in this run.</p> : null}
                <div className="grid gap-2 sm:grid-cols-2">
                  {cvObservations.map((observation) => (
                    <label key={observation.observation_id} className="flex items-center gap-2 rounded border border-line bg-ink-900 p-2 text-[11px] text-muted">
                      <input
                        type="checkbox"
                        checked={selectedObservationIds.includes(observation.observation_id)}
                        onChange={() => setSelectedObservationIds((previous) => previous.includes(observation.observation_id)
                          ? previous.filter((id) => id !== observation.observation_id)
                          : [...previous, observation.observation_id])}
                      />
                      <span className="font-mono text-accent">{observation.observation_id}</span>
                      <span>frame {observation.original_frame_number}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>
          <div>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Selected evidence frames ({selected.length})</p>
            {selected.length ? (
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                {selected.map((frame) => (
                  <div key={frame.id} className="flex items-center gap-2 rounded border border-line bg-ink-900 p-2">
                    <img src={api.url(`/api/frames/${frame.id}/thumb`)} alt="Selected evidence" className="h-12 w-20 rounded object-cover" />
                    <div className="min-w-0"><p className="font-mono text-[11px] text-accent">{formatSeconds(frame.timestamp)}</p><p className="truncate font-mono text-[9px] text-muted">{frame.id}</p></div>
                  </div>
                ))}
              </div>
            ) : <Alert kind="warn">Select evidence frames in the Evidence Gallery before exporting.</Alert>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="solid" onClick={generate} loading={busy} disabled={!caseId || !selected.length}><FileText className="h-3.5 w-3.5" /> Generate PDF report</Button>
            <Button onClick={() => api.download(`/api/exports/contact_sheet${qs({ case_id: caseId, frame_ids: selected.map((frame) => frame.id).join(",") })}`)} disabled={!caseId || !selected.length}><LayoutGrid className="h-3.5 w-3.5" /> Contact sheet PDF</Button>
            <span className="text-[11px] text-muted">Original videos are never overwritten.</span>
          </div>
          {latest ? (
            <div className="grid gap-3 rounded-md border border-accent/30 bg-accent/5 p-4 md:grid-cols-2">
              <div><p className="text-[10px] uppercase tracking-wider text-muted">Report data SHA-256</p><p className="break-all font-mono text-[11px] text-accent">{latest.report_hash}</p></div>
              <div><p className="text-[10px] uppercase tracking-wider text-muted">PDF SHA-256</p><p className="break-all font-mono text-[11px] text-accent">{latest.pdf_sha256}</p></div>
              <div className="flex flex-wrap gap-2 md:col-span-2">
                <Button size="sm" onClick={() => api.download(`/api/exports/${latest.id}/pdf`)}><Download className="h-3.5 w-3.5" /> Download PDF</Button>
                <Button size="sm" onClick={() => api.download(`/api/exports/${latest.id}/manifest`)}><FileJson className="h-3.5 w-3.5" /> Download manifest</Button>
                <Button size="sm" onClick={() => api.download(`/api/exports/frames/archive${qs({ case_id: caseId, frame_ids: generatedFrameIds.join(",") })}`)}><FileArchive className="h-3.5 w-3.5" /> Download frames ZIP</Button>
                <p className="w-full text-[10px] text-muted">The frames ZIP uses the {generatedFrameIds.length} frame(s) included in the generated report, even if the Evidence Gallery selection changes afterwards.</p>
              </div>
            </div>
          ) : null}
        </div>
      </Card>

      <Card>
        <CardHeader title="Export history" subtitle="Local report records with hashes" />
        {exports.length ? (
          <div className="divide-y divide-line/60">
            {exports.map((item) => (
              <div key={item.id} className="grid gap-2 px-4 py-3 text-xs md:grid-cols-[1fr_auto]">
                <div>
                  <div className="flex items-center gap-2"><Fingerprint className="h-4 w-4 text-accent" /><span className="font-mono text-slate-200">{item.id}</span><Badge>{item.frame_count} frames</Badge></div>
                  <p className="mt-1 text-muted">{formatDate(item.created_at)}</p>
                  <p className="mt-1 truncate font-mono text-[10px] text-muted">{item.pdf_sha256}</p>
                </div>
                <div className="flex items-start gap-2">
                  <Button size="sm" onClick={() => api.download(`/api/exports/${item.id}/pdf`)}><Download className="h-3.5 w-3.5" /> PDF</Button>
                  <Button size="sm" onClick={() => api.download(`/api/exports/${item.id}/manifest`)}><FileJson className="h-3.5 w-3.5" /> JSON</Button>
                </div>
              </div>
            ))}
          </div>
        ) : <EmptyState title="No reports generated" detail="Generated PDFs and manifests are recorded here with their SHA-256 hashes." />}
      </Card>
    </div>
  );
}
