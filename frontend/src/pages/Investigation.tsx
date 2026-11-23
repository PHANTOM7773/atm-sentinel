import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, CircleDot, FileVideo, Play, ShieldCheck } from "lucide-react";
import { api, qs } from "../lib/api";
import { formatBytes, formatSeconds, fromLocalInput, toLocalInput } from "../lib/format";
import { demoOptionLabel, isDemoCase, isDemoTransaction, isDemoVideo } from "../lib/demo";
import { CV_ASSOCIATION_LIMITATION } from "../lib/types";
import type { AlignmentResult, CaseRecord, JobRecord, TransactionRecord, VideoRecord } from "../lib/types";
import { Alert, Badge, Button, Card, CardHeader, DemoDataBanner, Field, Input, KeyValue, ProgressBar, Select, Textarea } from "../components/ui";

const STEPS = ["Case", "Transaction", "Upload video", "Metadata", "Clock offset", "Analysis window", "Process"];

export function InvestigationPage() {
  const [params, setParams] = useSearchParams();
  const caseParam = params.get("case") ?? "";
  const [step, setStep] = useState(0);
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [transactions, setTransactions] = useState<TransactionRecord[]>([]);
  const [videos, setVideos] = useState<VideoRecord[]>([]);
  const [caseId, setCaseId] = useState(caseParam);
  const [txId, setTxId] = useState("");
  const [videoId, setVideoId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [alignment, setAlignment] = useState<AlignmentResult | null>(null);
  const [form, setForm] = useState({
    video_start_ts: "",
    cctv_reference_video_time: "0",
    clock_offset_minutes: "",
    window_before_seconds: "20",
    window_after_seconds: "20",
    coarse_interval_seconds: "1",
    fine_interval_seconds: "0.25",
    fine_radius_seconds: "5",
    max_frames: "240",
  });

  const loadCases = useCallback(() => {
    api.get<CaseRecord[]>("/api/cases").then((data) => {
      setCases(data);
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(loadCases, [loadCases]);

  useEffect(() => {
    setCaseId(caseParam);
    if (!caseParam) {
      setTxId("");
      setVideoId("");
    }
  }, [caseParam]);

  const selectCase = (nextCase: string) => {
    setCaseId(nextCase);
    setTxId("");
    setVideoId("");
    setParams(nextCase ? { case: nextCase } : {});
  };

  useEffect(() => {
    if (!caseId) return;
    Promise.all([
      api.get<TransactionRecord[]>(`/api/cases/${caseId}/transactions`),
      api.get<VideoRecord[]>(`/api/videos${qs({ case_id: caseId })}`),
    ]).then(([tx, vid]) => {
      setTransactions(tx);
      setVideos(vid);
      if (!txId && tx.length) setTxId(tx[0].id);
      if (!videoId && vid.length) setVideoId(vid[0].id);
    }).catch((reason: Error) => setError(reason.message));
  }, [caseId, txId, videoId]);

  useEffect(() => {
    if (!job || ["completed", "failed", "cancelled"].includes(job.status)) return;
    const timer = window.setInterval(() => {
      api.get<JobRecord>(`/api/jobs/${job.id}`).then(setJob).catch(() => undefined);
    }, 700);
    return () => window.clearInterval(timer);
  }, [job]);

  const tx = transactions.find((item) => item.id === txId);
  const video = videos.find((item) => item.id === videoId);
  const caseKnown = cases.some((item) => item.id === caseId);
  const selectedCase = cases.find((item) => item.id === caseId);

  useEffect(() => {
    if (tx?.cctv_ts) setForm((current) => current.video_start_ts ? current : { ...current, video_start_ts: toLocalInput(tx.cctv_ts) });
  }, [tx]);

  const verify = async () => {
    if (!tx || !video) {
      setError("Select a transaction and a video first");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.post<AlignmentResult>("/api/alignment/preview", {
        transaction_ts: tx.transaction_ts,
        cctv_ts: tx.cctv_ts || tx.transaction_ts,
        video_duration: video.duration,
        video_start_ts: form.video_start_ts ? fromLocalInput(form.video_start_ts) : null,
        cctv_reference_video_time: Number(form.cctv_reference_video_time),
        clock_offset_minutes: form.clock_offset_minutes === "" ? null : Number(form.clock_offset_minutes),
        before_seconds: Number(form.window_before_seconds),
        after_seconds: Number(form.window_after_seconds),
      });
      setAlignment(result);
      setStep(6);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!alignment) {
      await verify();
      return;
    }
    setBusy(true);
    setError("");
    try {
      const created = await api.post<JobRecord>("/api/jobs", {
        video_id: videoId,
        transaction_id: txId,
        config: {
          video_start_ts: form.video_start_ts ? fromLocalInput(form.video_start_ts) : undefined,
          cctv_reference_video_time: Number(form.cctv_reference_video_time),
          clock_offset_minutes: form.clock_offset_minutes === "" ? undefined : Number(form.clock_offset_minutes),
          window_before_seconds: Number(form.window_before_seconds),
          window_after_seconds: Number(form.window_after_seconds),
          coarse_interval_seconds: Number(form.coarse_interval_seconds),
          fine_interval_seconds: Number(form.fine_interval_seconds),
          fine_radius_seconds: Number(form.fine_radius_seconds),
          max_frames: Number(form.max_frames),
        },
      });
      setJob(created);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleUpload = async (file: File | undefined) => {
    if (!file || !caseId) return;
    setBusy(true);
    try {
      const created = await api.upload<VideoRecord>(`/api/videos/upload${qs({ case_id: caseId })}`, file);
      setVideoId(created.id);
      const updated = await api.get<VideoRecord[]>(`/api/videos${qs({ case_id: caseId })}`);
      setVideos(updated);
      setStep(3);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1320px] space-y-5">
      {error ? <Alert kind="error">{error}</Alert> : null}
      {caseParam && cases.length > 0 && !caseKnown ? <Alert kind="warn">The selected case is unavailable. Choose a case before continuing.</Alert> : null}
      {selectedCase && isDemoCase(selectedCase) ? <DemoDataBanner subject="case" /> : null}
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          {STEPS.map((label, index) => (
            <button key={label} onClick={() => setStep(index)} className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] ${index === step ? "border-accent/50 bg-accent/10 text-accent" : index < step ? "border-ok/30 bg-ok/5 text-ok" : "border-line text-muted"}`}>
              {index < step ? <Check className="h-3 w-3" /> : <CircleDot className="h-3 w-3" />}
              <span>{index + 1}. {label}</span>
            </button>
          ))}
        </div>

        <div className="p-5">
          {step === 0 ? (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-100">1. Create or select a case</h3>
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Case"><Select value={caseId} onChange={(event) => selectCase(event.target.value)}><option value="">Select a case…</option>{cases.map((item) => <option key={item.id} value={item.id}>{demoOptionLabel(`${item.case_number} — ${item.title}`, isDemoCase(item))}</option>)}</Select></Field>
                <div className="flex items-end"><Link to={`/cases${qs({ case: caseId })}`}><Button variant="primary">Create / manage cases <ArrowRight className="h-3.5 w-3.5" /></Button></Link></div>
              </div>
              {cases.length ? <Alert>Selected: <span className="font-mono">{cases.find((item) => item.id === caseId)?.case_number}</span>. All case data is local.</Alert> : <Alert kind="warn">No cases exist yet. Create one before starting an investigation.</Alert>}
            </div>
          ) : null}

          {step === 1 ? (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-100">2. Enter transaction information</h3>
              {transactions.length ? (
                <div className="grid gap-3 md:grid-cols-2">
                  {transactions.map((item) => (
                    <button key={item.id} onClick={() => setTxId(item.id)} className={`rounded-md border p-3 text-left text-xs ${item.id === txId ? "border-accent/50 bg-accent/10" : "border-line bg-ink-900"}`}>
                      <p className="font-mono text-accent">{demoOptionLabel(item.reference, isDemoTransaction(item))}</p>
                      <p className="mt-1 text-slate-300">{item.atm_id || "No ATM ID"} · {item.transaction_type}</p>
                      <p className="mt-1 font-mono text-[11px] text-muted">{item.transaction_ts}</p>
                      {item.note ? <p className="mt-1 text-muted">{item.note}</p> : null}
                    </button>
                  ))}
                </div>
              ) : <Alert kind="warn">No transactions in this case. <Link to={`/cases${qs({ case: caseId })}`} className="underline">Add one in Case Management.</Link></Alert>}
            </div>
          ) : null}

          {step === 2 ? (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-100">3. Upload video</h3>
              <Field label="Video file" hint="MP4, AVI, MOV, MKV. The original file is copied into the local data directory and never modified.">
                <Input type="file" accept=".mp4,.avi,.mov,.mkv,video/*" onChange={(event) => handleUpload(event.target.files?.[0])} />
                <p className="mt-1 text-[11px] text-muted">For DVR/NVR clips, export H.264 MP4 from the vendor software. WMV, FLV, MPEG and MPG are unsupported; convert a copy and retain the original export.</p>
              </Field>
              {videos.length ? <div className="space-y-2">{videos.map((item) => <button key={item.id} onClick={() => setVideoId(item.id)} className={`flex w-full items-center gap-3 rounded-md border p-3 text-left text-xs ${item.id === videoId ? "border-accent/50 bg-accent/10" : "border-line bg-ink-900"}`}><FileVideo className="h-4 w-4 text-accent" /><span className="flex-1 truncate">{demoOptionLabel(item.original_filename, isDemoVideo(item))}</span>
<Badge>{item.integrity_status}</Badge></button>)}</div> : null}
              {busy ? <p className="text-xs text-accent">Validating, hashing and probing metadata…</p> : null}
            </div>
          ) : null}

          {step === 3 ? (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-100">4. Analyze metadata</h3>
              {video ? (
                <div className="grid gap-x-8 md:grid-cols-2">
                  <KeyValue label="Original filename" value={video.original_filename} />
                  <KeyValue label="Container" value={video.container} />
                  <KeyValue label="Codec" value={video.codec} />
                  <KeyValue label="Resolution" value={`${video.width} × ${video.height}`} />
                  <KeyValue label="Frame rate" value={`${video.fps} fps`} />
                  <KeyValue label="Duration" value={formatSeconds(video.duration)} />
                  <KeyValue label="Size" value={formatBytes(video.size_bytes)} />
                  <KeyValue label="Integrity" value={video.integrity_status} />
                  <KeyValue label="SHA-256" value={video.sha256} mono />
                  <KeyValue label="Streams" value={video.stream_count} />
                </div>
              ) : <Alert kind="warn">Upload or select a video first.</Alert>}
            </div>
          ) : null}

          {step === 4 ? (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-100">5. Configure CCTV timestamp offset</h3>
              <p className="text-xs leading-relaxed text-muted">Enter the CCTV wall-clock time shown at the start of this video file. If unknown, use a reference point inside the clip and its video time. The application derives the clock offset from the transaction and CCTV timestamps unless you override it.</p>
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="CCTV time at video start" hint="Leave blank to use the CCTV reference point below."><Input type="datetime-local" step="1" value={form.video_start_ts} onChange={(event) => setForm({ ...form, video_start_ts: event.target.value })} /></Field>
                <Field label="CCTV reference point in video (seconds)"><Input type="number" min="0" step="0.1" value={form.cctv_reference_video_time} onChange={(event) => setForm({ ...form, cctv_reference_video_time: event.target.value })} /></Field>
                <Field label="Manual clock offset (minutes)" hint="Blank = derive from transaction and CCTV timestamps. Positive means CCTV is ahead."><Input type="number" step="0.1" value={form.clock_offset_minutes} onChange={(event) => setForm({ ...form, clock_offset_minutes: event.target.value })} placeholder="derived" /></Field>
              </div>
              {tx ? <Alert><span className="font-mono">TX {tx.transaction_ts}</span> · <span className="font-mono">CCTV {tx.cctv_ts || "not recorded"}</span></Alert> : <Alert kind="warn">Select a transaction in step 2.</Alert>}
            </div>
          ) : null}

          {step === 5 ? (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-100">6. Configure analysis window and sampling</h3>
              <div className="grid gap-4 md:grid-cols-3">
                <Field label="Seconds before transaction"><Input type="number" min="0" step="0.5" value={form.window_before_seconds} onChange={(event) => setForm({ ...form, window_before_seconds: event.target.value })} /></Field>
                <Field label="Seconds after transaction"><Input type="number" min="0" step="0.5" value={form.window_after_seconds} onChange={(event) => setForm({ ...form, window_after_seconds: event.target.value })} /></Field>
                <Field label="Maximum frames"><Input type="number" min="1" max="2000" value={form.max_frames} onChange={(event) => setForm({ ...form, max_frames: event.target.value })} /></Field>
                <Field label="Coarse interval (s)"><Input type="number" min="0.1" step="0.1" value={form.coarse_interval_seconds} onChange={(event) => setForm({ ...form, coarse_interval_seconds: event.target.value })} /></Field>
                <Field label="Fine interval (s)"><Input type="number" min="0.05" step="0.05" value={form.fine_interval_seconds} onChange={(event) => setForm({ ...form, fine_interval_seconds: event.target.value })} /></Field>
                <Field label="Fine radius around transaction (s)"><Input type="number" min="0" step="0.5" value={form.fine_radius_seconds} onChange={(event) => setForm({ ...form, fine_radius_seconds: event.target.value })} /></Field>
              </div>
              <p className="text-xs text-muted">Sampling is incremental and bounded. Near the transaction, the fine interval is used; elsewhere the coarse interval applies.</p>
            </div>
          ) : null}

          {step === 6 ? (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-100">7. Verify alignment and start processing</h3>
              {alignment ? (
                <Card className="p-4">
                  <div className="grid gap-x-8 md:grid-cols-2">
                    <KeyValue label="Transaction (UTC)" value={alignment.transaction_utc} />
                    <KeyValue label="CCTV clock (UTC)" value={alignment.cctv_utc} />
                    <KeyValue label="Derived offset" value={`${alignment.derived_offset_seconds}s`} />
                    <KeyValue label="Applied offset" value={`${alignment.offset_minutes} min · ${alignment.offset_source}`} />
                    <KeyValue label="Transaction CCTV time" value={alignment.transaction_cctv_utc} />
                    <KeyValue label="Transaction at video time" value={`${formatSeconds(alignment.transaction_video_seconds)}`} />
                    <KeyValue label="Analysis window" value={`${formatSeconds(alignment.window_start_seconds)} → ${formatSeconds(alignment.window_end_seconds)} (${alignment.analysis_span_seconds}s)`} />
                    <KeyValue label="Video duration" value={formatSeconds(alignment.video_duration)} />
                  </div>
                  {alignment.warnings.length ? <div className="mt-3"><Alert kind="warn">{alignment.warnings.join(" ")}</Alert></div> : <div className="mt-3"><Alert>Alignment is internally consistent. Confirm the clock settings reflect the actual CCTV recorder.</Alert></div>}
                </Card>
              ) : <Alert kind="warn">Run the alignment preview to see the calculation.</Alert>}

              {job ? (
                <Card className="p-4">
                  <div className="flex items-center justify-between text-xs"><span className="font-mono text-accent">{job.id}</span><Badge>{job.status}</Badge></div>
                  <p className="mt-2 text-xs text-muted">{job.stage} — {job.message}</p>
                  <div className="mt-3"><ProgressBar value={job.progress} /></div>
                  {job.status === "completed" ? <div className="mt-3 flex flex-wrap gap-2"><Link to={`/workspace${qs({ case: job.case_id, video: job.video_id, job: job.id })}`}><Button variant="primary">Open video workspace <ArrowRight className="h-3.5 w-3.5" /></Button></Link><Link to={`/evidence${qs({ case: job.case_id })}`}><Button>Review evidence</Button></Link><Link to={`/cv${qs({ case: job.case_id })}`}><Button>Review CV candidates</Button></Link></div> : null}
                  {!["completed", "failed", "cancelled"].includes(job.status) ? <div className="mt-3"><Button variant="danger" size="sm" onClick={() => api.post(`/api/jobs/${job.id}/cancel`).then(() => api.get<JobRecord>(`/api/jobs/${job.id}`)).then(setJob)}>Cancel processing</Button></div> : null}
                </Card>
              ) : null}
            </div>
          ) : null}

          <div className="mt-7 flex items-center justify-between border-t border-line pt-4">
            <Button onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}><ArrowLeft className="h-3.5 w-3.5" /> Back</Button>
            <div className="flex gap-2">
              {step < 6 ? <Button variant="primary" onClick={() => setStep(step + 1)} disabled={(step === 0 && !caseId) || (step === 1 && !txId) || (step === 2 && !videoId)}>Next <ArrowRight className="h-3.5 w-3.5" /></Button> : null}
              {step >= 4 ? <Button onClick={verify} loading={busy}>Verify alignment <ShieldCheck className="h-3.5 w-3.5" /></Button> : null}
              {step === 6 ? <Button variant="solid" onClick={start} loading={busy} disabled={!alignment}><Play className="h-3.5 w-3.5" /> Start processing</Button> : null}
            </div>
          </div>
        </div>
      </Card>
      <p className="text-center text-[11px] text-muted">Face detection locates face regions; CV embedding similarity ranks candidates only. Reviewers decide relevance, and no identity confirmation is performed. {CV_ASSOCIATION_LIMITATION}</p>
    </div>
  );
}
