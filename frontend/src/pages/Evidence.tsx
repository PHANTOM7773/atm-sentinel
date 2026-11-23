import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowDownWideNarrow, Check, Columns2, Eye, FileWarning, MessageSquarePlus, Search } from "lucide-react";
import { api, qs } from "../lib/api";
import { formatSeconds, qualityTone } from "../lib/format";
import { demoOptionLabel, isDemoCase } from "../lib/demo";
import type { CaseRecord, FrameRecord } from "../lib/types";
import { Alert, Badge, Button, Card, CardHeader, DemoDataBanner, EmptyState, Field, Input, Modal, Select, Textarea } from "../components/ui";

export function EvidencePage() {
  const [params, setParams] = useSearchParams();
  const caseParam = params.get("case") ?? "";
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [caseId, setCaseId] = useState(caseParam);
  const [frames, setFrames] = useState<FrameRecord[]>([]);
  const [sort, setSort] = useState("timestamp");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [viewFrame, setViewFrame] = useState<FrameRecord | null>(null);
  const [noteFrame, setNoteFrame] = useState<FrameRecord | null>(null);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [compareFrames, setCompareFrames] = useState<FrameRecord[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<CaseRecord[]>("/api/cases").then((data) => {
      setCases(data);
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    setCaseId(caseParam);
    if (!caseParam) setFrames([]);
  }, [caseParam]);

  const selectCase = (nextCase: string) => {
    setCaseId(nextCase);
    setParams(nextCase ? { case: nextCase } : {});
  };

  const load = () => {
    if (!caseId) return;
    api.get<FrameRecord[]>(`/api/frames${qs({ case_id: caseId })}`).then(setFrames).catch((reason: Error) => setError(reason.message));
  };

  useEffect(load, [caseId]);

  const visible = useMemo(() => {
    let result = [...frames];
    if (filter === "warnings") result = result.filter((frame) => frame.warnings.length > 0);
    if (filter === "selected") result = result.filter((frame) => frame.selected);
    if (filter === "fine") result = result.filter((frame) => frame.source === "fine");
    if (filter === "manual") result = result.filter((frame) => frame.source === "manual");
    if (query.trim()) {
      const term = query.toLowerCase();
      result = result.filter((frame) => `${frame.id} ${frame.timestamp} ${frame.frame_number}`.toLowerCase().includes(term));
    }
    result.sort((a, b) => sort === "quality" ? b.quality_score - a.quality_score : a.timestamp - b.timestamp);
    return result;
  }, [frames, filter, sort, query]);

  const selected = frames.filter((frame) => frame.selected);
  const caseKnown = cases.some((item) => item.id === caseId);
  const selectedCase = cases.find((item) => item.id === caseId);

  const toggle = async (frame: FrameRecord) => {
    try {
      const updated = await api.patch<FrameRecord>(`/api/frames/${frame.id}`, { selected: !frame.selected });
      setFrames((previous) => previous.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const saveNote = async () => {
    if (!noteFrame) return;
    try {
      const updated = await api.patch<FrameRecord>(`/api/frames/${noteFrame.id}`, { note, reason, selected: true });
      setFrames((previous) => previous.map((item) => item.id === updated.id ? updated : item));
      setNoteFrame(null);
      setNote("");
      setReason("");
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const openCompare = async () => {
    if (selected.length < 2) return;
    try {
      const result = await api.get<FrameRecord[]>(`/api/frames/compare${qs({ ids: selected.slice(0, 4).map((frame) => frame.id).join(",") })}`);
      setCompareFrames(result);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  return (
    <div className="mx-auto max-w-[1500px] space-y-5">
      {error ? <Alert kind="error">{error}</Alert> : null}
      {caseParam && cases.length > 0 && !caseKnown ? <Alert kind="warn">The selected case is unavailable. Choose a case before continuing.</Alert> : null}
      {selectedCase && isDemoCase(selectedCase) ? <DemoDataBanner subject="case" /> : null}
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Case" className="min-w-[280px] flex-1"><Select value={caseId} onChange={(event) => selectCase(event.target.value)}><option value="">Select case…</option>{cases.map((item) => <option key={item.id} value={item.id}>{demoOptionLabel(`${item.case_number} — ${item.title}`, isDemoCase(item))}</option>)}</Select></Field>
        <Field label="Sort"><Select value={sort} onChange={(event) => setSort(event.target.value)}><option value="timestamp">Timestamp</option><option value="quality">Quality score</option></Select></Field>
        <Field label="Filter"><Select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All frames</option><option value="warnings">With warnings</option><option value="selected">Selected only</option><option value="fine">Fine samples</option><option value="manual">Manual captures</option></Select></Field>
        <Field label="Search" className="min-w-[180px]"><div className="relative"><Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted" /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Frame ID / time" className="pl-8" /></div></Field>
        <Button onClick={openCompare} disabled={selected.length < 2}><Columns2 className="h-3.5 w-3.5" /> Compare {selected.length ? Math.min(selected.length, 4) : ""}</Button>
        <Link to={`/export${qs({ case: caseId })}`}><Button variant="primary">Export report</Button></Link>
      </div>

      <div className="flex flex-wrap items-center gap-4 rounded-md border border-line bg-ink-900 px-4 py-2.5 text-xs text-muted">
        <span><span className="text-slate-200">{frames.length}</span> extracted</span>
        <span><span className="text-slate-200">{selected.length}</span> selected</span>
        <span><span className="text-slate-200">{frames.filter((frame) => frame.warnings.length).length}</span> with warnings</span>
        <span className="ml-auto flex items-center gap-1"><ArrowDownWideNarrow className="h-3.5 w-3.5" /> Quality score = image usability only; CV candidate search is separate</span>
      </div>

      {visible.length ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {visible.map((frame) => (
            <Card key={frame.id} className={`overflow-hidden ${frame.selected ? "border-accent/60" : ""}`}>
              <div className="relative bg-black">
                <img src={api.url(`/api/frames/${frame.id}/image`)} alt={`Evidence frame at ${frame.timestamp} seconds`} className="aspect-video w-full object-contain" />
                <div className="absolute right-2 top-2 flex gap-1">
                  <button onClick={() => setViewFrame(frame)} className="rounded border border-line bg-ink-950/80 p-1.5 text-slate-200 hover:text-accent" title="View original" aria-label={`View original frame ${frame.id}`}><Eye className="h-3.5 w-3.5" /></button>
                  <button onClick={() => { setNoteFrame(frame); setNote(frame.selection_note || frame.frame_notes[0]?.body || ""); setReason(frame.selection_reason || ""); }} className="rounded border border-line bg-ink-950/80 p-1.5 text-slate-200 hover:text-accent" title="Add note" aria-label={`Add note for frame ${frame.id}`}><MessageSquarePlus className="h-3.5 w-3.5" /></button>
                </div>
                {frame.selected ? <div className="absolute left-2 top-2 rounded bg-accent px-1.5 py-0.5 text-[10px] font-bold text-ink-950">SELECTED</div> : null}
              </div>
              <div className="space-y-2 p-3">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-accent">T+{formatSeconds(frame.timestamp)}</span>
                  <Badge>{frame.source}</Badge>
                </div>
                <div className="grid grid-cols-4 gap-1 text-center text-[10px]">
                  <div><p className="text-muted">Quality</p><p className={`font-mono text-xs font-semibold ${qualityTone(frame.quality_score)}`}>{frame.quality_score}</p></div>
                  <div><p className="text-muted">Sharp</p><p className="font-mono text-xs text-slate-200">{frame.sharpness.toFixed(0)}</p></div>
                  <div><p className="text-muted">Bright</p><p className="font-mono text-xs text-slate-200">{frame.brightness.toFixed(0)}</p></div>
                  <div><p className="text-muted">Contrast</p><p className="font-mono text-xs text-slate-200">{frame.contrast.toFixed(0)}</p></div>
                </div>
                <div className="flex flex-wrap gap-1">
                  {frame.warnings.length ? frame.warnings.map((warning) => <Badge key={warning} className="border-warn/40 bg-warn/10 text-warn">{warning}</Badge>) : <Badge className="border-ok/30 bg-ok/10 text-ok">No quality warnings</Badge>}
                </div>
                <p className="truncate font-mono text-[10px] text-muted">{frame.sha256}</p>
                {frame.selection_note ? <p className="line-clamp-2 text-[11px] text-slate-300">{frame.selection_note}</p> : null}
                <Button size="sm" variant={frame.selected ? "danger" : "primary"} className="w-full" onClick={() => toggle(frame)}>{frame.selected ? "Remove from evidence" : <><Check className="h-3.5 w-3.5" /> Select as evidence</>}</Button>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Card><EmptyState title="No frames to display" detail="Process a video first, or adjust the filter. Extracted frames appear here with explainable quality metrics." /></Card>
      )}

      <Modal open={!!viewFrame} onClose={() => setViewFrame(null)} title={`Original frame · ${viewFrame ? formatSeconds(viewFrame.timestamp) : ""}`} wide>
        {viewFrame ? <div className="space-y-3"><img src={api.url(`/api/frames/${viewFrame.id}/image`)} alt="Original extracted frame" className="mx-auto max-h-[65vh] rounded border border-line" /><p className="font-mono text-xs text-muted">SHA-256 {viewFrame.sha256} · source frame {viewFrame.frame_number}</p></div> : null}
      </Modal>

      <Modal open={!!noteFrame} onClose={() => setNoteFrame(null)} title="Evidence selection notes">
        <div className="space-y-4">
          <Field label="Why this frame is relevant"><Textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Manual investigator assessment…" /></Field>
          <Field label="Investigator note"><Textarea value={note} onChange={(event) => setNote(event.target.value)} /></Field>
          <div className="flex justify-end gap-2"><Button onClick={() => setNoteFrame(null)}>Cancel</Button><Button variant="solid" onClick={saveNote}>Save & select</Button></div>
        </div>
      </Modal>

      <Modal open={compareFrames.length > 0} onClose={() => setCompareFrames([])} title="Side-by-side manual comparison" wide>
        <div className="grid gap-3 sm:grid-cols-2">
          {compareFrames.map((frame) => (
            <div key={frame.id} className="rounded border border-line bg-ink-900 p-2">
              <img src={api.url(`/api/frames/${frame.id}/image`)} alt={`Comparison frame ${frame.id}`} className="w-full rounded" />
              <div className="mt-2 flex justify-between text-[11px]"><span className="font-mono text-accent">{formatSeconds(frame.timestamp)}</span><span className="text-muted">Quality {frame.quality_score}</span></div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[11px] text-muted">Reviewer must make and document their own assessment. This manual comparison does not run face detection or calculate similarity; CV candidates are reviewed separately and never establish identity.</p>
      </Modal>
    </div>
  );
}
