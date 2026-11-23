import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { GitCompareArrows, Link2, Search } from "lucide-react";
import { api, qs } from "../lib/api";
import { formatDate, formatSeconds } from "../lib/format";
import { demoOptionLabel, isDemoCase, isDemoVideo } from "../lib/demo";
import type { CaseRecord, ClipLink, FrameRecord, VideoRecord } from "../lib/types";
import { Alert, Badge, Button, Card, CardHeader, DemoDataBanner, EmptyState, Field, Input, Select, Textarea } from "../components/ui";

export function ComparePage() {
  const [params, setParams] = useSearchParams();
  const caseParam = params.get("case") ?? "";
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [caseId, setCaseId] = useState(caseParam);
  const [videos, setVideos] = useState<VideoRecord[]>([]);
  const [frames, setFrames] = useState<FrameRecord[]>([]);
  const [links, setLinks] = useState<ClipLink[]>([]);
  const [videoA, setVideoA] = useState("");
  const [videoB, setVideoB] = useState("");
  const [reason, setReason] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ cases: CaseRecord[]; videos: VideoRecord[] } | null>(null);
  const [compareA, setCompareA] = useState("");
  const [compareB, setCompareB] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    api.get<CaseRecord[]>("/api/cases").then((data) => {
      setCases(data);
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    setCaseId(caseParam);
    if (!caseParam) {
      setVideos([]);
      setFrames([]);
      setLinks([]);
      setVideoA("");
      setVideoB("");
      setCompareA("");
      setCompareB("");
    }
  }, [caseParam]);

  const selectCase = (nextCase: string) => {
    setCaseId(nextCase);
    setVideoA("");
    setVideoB("");
    setCompareA("");
    setCompareB("");
    setParams(nextCase ? { case: nextCase } : {});
  };

  useEffect(() => {
    if (!caseId) return;
    Promise.all([
      api.get<VideoRecord[]>(`/api/videos${qs({ case_id: caseId })}`),
      api.get<FrameRecord[]>(`/api/frames${qs({ case_id: caseId })}`),
      api.get<ClipLink[]>(`/api/cases/${caseId}/links`),
    ]).then(([vid, frame, link]) => {
      setVideos(vid);
      setFrames(frame);
      setLinks(link);
      setVideoA(vid[0]?.id || "");
      setVideoB(vid[1]?.id || "");
      setCompareA(frame[0]?.id || "");
      setCompareB(frame[1]?.id || "");
    }).catch((reason: Error) => setError(reason.message));
  }, [caseId]);

  const addLink = async () => {
    try {
      await api.post(`/api/cases/${caseId}/links`, { video_a: videoA, video_b: videoB, reason });
      setNotice("Manual relationship documented");
      setReason("");
      const updated = await api.get<ClipLink[]>(`/api/cases/${caseId}/links`);
      setLinks(updated);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const search = async () => {
    try {
      setResults(await api.get<{ cases: CaseRecord[]; videos: VideoRecord[] }>(`/api/search${qs({ q: query })}`));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const frameA = frames.find((frame) => frame.id === compareA);
  const frameB = frames.find((frame) => frame.id === compareB);
  const caseKnown = cases.some((item) => item.id === caseId);
  const selectedCase = cases.find((item) => item.id === caseId);

  return (
    <div className="mx-auto max-w-[1500px] space-y-5">
      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert>{notice}</Alert> : null}
      {caseParam && cases.length > 0 && !caseKnown ? <Alert kind="warn">The selected case is unavailable. Choose a case before continuing.</Alert> : null}
      {selectedCase && isDemoCase(selectedCase) ? <DemoDataBanner subject="case" /> : null}
      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="Manual clip relationship" subtitle="Human-controlled visual review — no automated identity matching" />
          <div className="space-y-4 p-4">
            <Field label="Case"><Select value={caseId} onChange={(event) => selectCase(event.target.value)}><option value="">Select case…</option>{cases.map((item) => <option key={item.id} value={item.id}>{demoOptionLabel(`${item.case_number} — ${item.title}`, isDemoCase(item))}</option>)}</Select></Field>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Clip A"><Select value={videoA} onChange={(event) => setVideoA(event.target.value)}><option value="">Select…</option>{videos.map((item) => <option key={item.id} value={item.id}>{demoOptionLabel(`${item.original_filename} (${item.id.slice(0, 8)})`, isDemoVideo(item))}</option>)}</Select></Field>
              <Field label="Clip B"><Select value={videoB} onChange={(event) => setVideoB(event.target.value)}><option value="">Select…</option>{videos.map((item) => <option key={item.id} value={item.id}>{demoOptionLabel(`${item.original_filename} (${item.id.slice(0, 8)})`, isDemoVideo(item))}</option>)}</Select></Field>
            </div>
            <Field label="Why do you consider these clips potentially related?" hint="Record your own rationale. This text is stored in the audit trail and PDF report."><Textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="e.g. Same camera area and similar clothing observed in both clips — manual visual assessment only" /></Field>
            <Button onClick={addLink} disabled={!videoA || !videoB || !reason.trim()}><Link2 className="h-3.5 w-3.5" /> Document relationship</Button>
          </div>
        </Card>

        <Card>
          <CardHeader title="Search cases & clips" subtitle="Metadata and recorded rationale" />
          <div className="space-y-3 p-4">
            <div className="relative"><Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted" /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Case number, ATM, filename…" className="pl-8" /></div>
            <Button size="sm" onClick={search}>Search</Button>
            {results ? (
              <div className="max-h-72 space-y-2 overflow-y-auto text-xs">
                <p className="text-muted">Cases ({results.cases.length})</p>
                {results.cases.map((item) => <Link key={item.id} to={`/cases${qs({ case: item.id })}`} className="block rounded border border-line p-2 hover:border-accent/50"><span className="font-mono text-accent">{demoOptionLabel(item.case_number, isDemoCase(item))}</span><p className="text-slate-300">{item.title}</p></Link>)}
                <p className="pt-2 text-muted">Clips ({results.videos.length})</p>
                {results.videos.map((item) => <Link key={item.id} to={`/cases${qs({ case: item.case_id })}`} className="block rounded border border-line p-2 hover:border-accent/50"><span className="text-slate-300">{demoOptionLabel(item.original_filename, isDemoVideo(item))}</span> <Badge>{item.codec}</Badge><span className="block font-mono text-[10px] text-muted">Case {item.case_id}</span></Link>)}
              </div>
            ) : null}
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title="Frame comparison" subtitle="Select two extracted frames for visual review" />
        <div className="grid gap-4 p-4 lg:grid-cols-2">
          <Field label="Frame A"><Select value={compareA} onChange={(event) => setCompareA(event.target.value)}><option value="">Select…</option>{frames.map((frame) => <option key={frame.id} value={frame.id}>{formatSeconds(frame.timestamp)} · {frame.id.slice(0, 10)}</option>)}</Select></Field>
          <Field label="Frame B"><Select value={compareB} onChange={(event) => setCompareB(event.target.value)}><option value="">Select…</option>{frames.map((frame) => <option key={frame.id} value={frame.id}>{formatSeconds(frame.timestamp)} · {frame.id.slice(0, 10)}</option>)}</Select></Field>
        </div>
        <div className="grid gap-4 border-t border-line p-4 md:grid-cols-2">
          {[frameA, frameB].map((frame, index) => frame ? (
            <div key={`${index}-${frame.id}`} className="rounded border border-line bg-black p-2">
              <img src={api.url(`/api/frames/${frame.id}/image`)} alt={`Comparison ${index + 1}`} className="w-full rounded" />
              <p className="mt-2 text-[11px] text-muted"><span className="font-mono text-accent">{formatSeconds(frame.timestamp)}</span> · quality {frame.quality_score} · warnings {frame.warnings.length}</p>
            </div>
          ) : <div key={index} className="grid min-h-[180px] place-items-center rounded border border-dashed border-line text-xs text-muted">No frame selected</div>)}
        </div>
        <p className="border-t border-line px-4 py-3 text-[11px] text-muted">The investigator makes and documents their own assessment. This manual comparison does not run face detection or compute similarity; CV candidate search is separate and never establishes identity.</p>
      </Card>

      <Card>
        <CardHeader title="Recorded relationships" subtitle={`${links.length} manual links in this case`} />
        {links.length ? (
          <div className="divide-y divide-line/60">
            {links.map((link) => (
              <div key={link.id} className="flex gap-3 px-4 py-3 text-xs">
                <GitCompareArrows className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                <div className="flex-1"><p className="font-mono text-slate-200">{link.video_a.slice(0, 8)} ↔ {link.video_b.slice(0, 8)}</p><p className="mt-1 text-muted">{link.reason}</p><p className="mt-1 text-[10px] text-muted">{formatDate(link.created_at)}</p></div>
              </div>
            ))}
          </div>
        ) : <EmptyState title="No relationships recorded" detail="Compare clips manually and document your rationale to create a local relationship record." />}
      </Card>
    </div>
  );
}
