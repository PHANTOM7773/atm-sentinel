import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Camera, Crosshair, Pause, Play, Radio, RefreshCw } from "lucide-react";
import { api, qs } from "../lib/api";
import { formatSeconds, qualityTone, statusTone } from "../lib/format";
import { demoOptionLabel, isDemoCase, isDemoVideo } from "../lib/demo";
import { CV_ASSOCIATION_LIMITATION } from "../lib/types";
import type { AlignmentResult, CaseRecord, FrameRecord, JobRecord, VideoRecord } from "../lib/types";
import { Alert, Badge, Button, Card, CardHeader, DemoDataBanner, EmptyState, Field, KeyValue, ProgressBar, Select } from "../components/ui";

export function WorkspacePage() {
  const [params, setParams] = useSearchParams();
  const caseParam = params.get("case") ?? "";
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [videos, setVideos] = useState<VideoRecord[]>([]);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [frames, setFrames] = useState<FrameRecord[]>([]);
  const [caseId, setCaseId] = useState(caseParam);
  const [videoId, setVideoId] = useState(params.get("video") || "");
  const [jobId, setJobId] = useState(params.get("job") || "");
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    api.get<CaseRecord[]>("/api/cases").then((data) => {
      setCases(data);
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    setCaseId(caseParam);
    if (!caseParam) {
      setVideoId("");
      setJobId("");
    }
  }, [caseParam]);

  const selectCase = (nextCase: string) => {
    setCaseId(nextCase);
    setVideoId("");
    setJobId("");
    setParams(nextCase ? { case: nextCase } : {});
  };

  useEffect(() => {
    if (!caseId) return;
    Promise.all([
      api.get<VideoRecord[]>(`/api/videos${qs({ case_id: caseId })}`),
      api.get<JobRecord[]>(`/api/jobs${qs({ case_id: caseId })}`),
      api.get<FrameRecord[]>(`/api/frames${qs({ case_id: caseId })}`),
    ]).then(([vid, job, frame]) => {
      setVideos(vid);
      setJobs(job);
      setFrames(frame);
      if (!videoId && vid.length) setVideoId(vid[0].id);
      if (!jobId && job.length) setJobId(job[0].id);
    }).catch((reason: Error) => setError(reason.message));
  }, [caseId, videoId, jobId]);

  useEffect(() => {
    if (!jobId || !jobs.length) return;
    const job = jobs.find((item) => item.id === jobId);
    if (!job || ["completed", "failed", "cancelled"].includes(job.status)) return;
    const timer = window.setInterval(() => {
      api.get<JobRecord>(`/api/jobs/${jobId}`).then((updated) => setJobs((previous) => previous.map((item) => item.id === updated.id ? updated : item))).catch(() => undefined);
    }, 800);
    return () => window.clearInterval(timer);
  }, [jobId, jobs]);

  const video = videos.find((item) => item.id === videoId);
  const job = jobs.find((item) => item.id === jobId);
  const caseKnown = cases.some((item) => item.id === caseId);
  const selectedCase = cases.find((item) => item.id === caseId);
  const alignment: AlignmentResult | undefined = job?.alignment;
  const visibleFrames = useMemo(() => frames.filter((frame) => !videoId || frame.video_id === videoId), [frames, videoId]);
  const seek = (time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = Math.max(0, Math.min(time, duration || video?.duration || 0));
      setCurrent(videoRef.current.currentTime);
    }
  };
  const toggle = () => {
    const element = videoRef.current;
    if (!element) return;
    if (element.paused) void element.play();
    else element.pause();
  };
  const normalizeCopy = async () => {
    if (!video || !caseId) return;
    try {
      await api.post(`/api/videos/${video.id}/normalize${qs({ case_id: caseId })}`);
      const updated = await api.get<VideoRecord[]>(`/api/videos${qs({ case_id: caseId })}`);
      setVideos(updated);
      setNotice("Created a normalized MP4 copy locally. The original file was not modified.");
    } catch (reason) {
      setError((reason as Error).message);
    }
  };
  const manualCapture = async () => {
    if (!caseId || !videoId) return;
    try {
      await api.post("/api/frames/manual", { case_id: caseId, video_id: videoId, timestamp: current, note: "Manually captured from video workspace" });
      const updated = await api.get<FrameRecord[]>(`/api/frames${qs({ case_id: caseId, video_id: videoId })}`);
      setFrames(updated);
      setNotice(`Captured frame at ${formatSeconds(current)}`);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };
  const timelineDuration = duration || video?.duration || 1;
  const marker = (value: number | undefined, color: string, label: string) => value !== undefined ? (
    <div className="absolute -top-6 -translate-x-1/2" style={{ left: `${Math.min(100, Math.max(0, (value / timelineDuration) * 100))}%` }} title={`${label}: ${formatSeconds(value)}`}>
      <div className="h-4 w-0.5" style={{ backgroundColor: color }} />
      <span className="absolute left-1/2 top-4 -translate-x-1/2 whitespace-nowrap text-[9px]" style={{ color }}>{label}</span>
    </div>
  ) : null;

  return (
    <div className="mx-auto max-w-[1500px] space-y-5">
      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert>{notice}</Alert> : null}
      {caseParam && cases.length > 0 && !caseKnown ? <Alert kind="warn">The selected case is unavailable. Choose a case before continuing.</Alert> : null}
      {selectedCase && isDemoCase(selectedCase) ? <DemoDataBanner subject="case" /> : null}
      <div className="grid gap-4 md:grid-cols-3">
        <Field label="Case"><Select value={caseId} onChange={(event) => selectCase(event.target.value)}><option value="">Select case…</option>{cases.map((item) => <option key={item.id} value={item.id}>{demoOptionLabel(`${item.case_number} — ${item.title}`, isDemoCase(item))}</option>)}</Select></Field>
        <Field label="Video"><Select value={videoId} onChange={(event) => setVideoId(event.target.value)}><option value="">Select video…</option>{videos.map((item) => <option key={item.id} value={item.id}>{demoOptionLabel(item.original_filename, isDemoVideo(item))}</option>)}</Select></Field>
        <Field label="Processing job"><Select value={jobId} onChange={(event) => setJobId(event.target.value)}><option value="">Select job…</option>{jobs.map((item) => <option key={item.id} value={item.id}>{item.stage} · {item.status} · {item.id.slice(0, 8)}</option>)}</Select></Field>
      </div>

      {video ? (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_330px]">
          <div className="space-y-5">
            <Card>
              <div className="bg-black">
                <video ref={videoRef} src={api.url(`/api/videos/${video.id}/file`)} controls className="max-h-[58vh] min-h-[300px] w-full" onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)} onTimeUpdate={(event) => setCurrent(event.currentTarget.currentTime)} />
              </div>
              <div className="space-y-5 p-4">
                <div className="flex items-center gap-3">
                  <Button size="sm" onClick={toggle}>{current && videoRef.current && !videoRef.current.paused ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />} {videoRef.current?.paused ? "Play" : "Pause"}</Button>
                  <span className="font-mono text-sm tabular-nums text-accent">{formatSeconds(current)}</span>
                  <span className="font-mono text-xs text-muted">/ {formatSeconds(duration || video.duration)}</span>
                  <span className="ml-auto font-mono text-xs text-muted">{video.fps} fps · {video.width}×{video.height}</span>
                </div>
                <div>
                  <div className="relative pt-6">
                    {marker(alignment?.window_start_seconds, "var(--color-accent)", "Window start")}
                    {marker(alignment?.transaction_video_seconds, "var(--color-ok)", "Transaction")}
                    {marker(alignment?.window_end_seconds, "var(--color-accent)", "Window end")}
                    <input type="range" min={0} max={timelineDuration} step={0.01} value={Math.min(current, timelineDuration)} onChange={(event) => seek(Number(event.target.value))} className="w-full accent-accent" />
                  </div>
                  <div className="mt-1 flex justify-between font-mono text-[10px] text-muted"><span>0:00</span><span>{formatSeconds(timelineDuration)}</span></div>
                </div>
                <div className="flex items-center gap-2">
                  <Button size="sm" onClick={manualCapture} disabled={!caseId}><Camera className="h-3.5 w-3.5" /> Capture frame at {formatSeconds(current)}</Button>
                  <span className="text-[11px] text-muted">Manual captures are stored with their own SHA-256 and quality metrics.</span>
                </div>
              </div>
            </Card>

            <Card>
              <CardHeader title="Extracted frames" subtitle={`${visibleFrames.length} frames on this video · click to seek`} />
              {visibleFrames.length ? (
                <div className="grid grid-cols-3 gap-2 overflow-y-auto p-3 sm:grid-cols-4 lg:grid-cols-6">
                  {visibleFrames.map((frame) => (
                    <button key={frame.id} onClick={() => seek(frame.timestamp)} className="group overflow-hidden rounded border border-line bg-ink-900 text-left transition-colors hover:border-accent/60">
                      <img src={api.url(`/api/frames/${frame.id}/thumb`)} alt={`Frame at ${frame.timestamp}s`} className="aspect-video w-full object-cover" />
                      <div className="flex items-center justify-between px-1.5 py-1 font-mono text-[9px]"><span className="text-accent">{formatSeconds(frame.timestamp)}</span><span className={qualityTone(frame.quality_score)}>{frame.quality_score}</span></div>
                    </button>
                  ))}
                </div>
              ) : <EmptyState title="No frames extracted" detail="Start a processing job from the New Investigation workflow." />}
            </Card>
          </div>

          <div className="space-y-5">
            <Card>
              <CardHeader title="Processing status" subtitle="Live job state" />
              {job ? (
                <div className="space-y-3 p-4">
                  <div className="flex items-center justify-between"><span className="text-xs text-slate-200">{job.stage}</span><Badge className={statusTone(job.status)}>{job.status}</Badge></div>
                  <ProgressBar value={job.progress} />
                  <p className="text-xs text-muted">{job.message}</p>
                  <div className="grid grid-cols-2 gap-2 text-[10px] text-muted"><span>Frames on video</span><span className="text-right text-slate-200">{visibleFrames.length}</span><span>Job created</span><span className="text-right text-slate-200">{job.created_at.slice(0, 19)}</span></div>
                </div>
              ) : <EmptyState title="No job selected" detail="Select a job to view its status." />}
            </Card>

            <Card>
              <CardHeader title="Video metadata" subtitle="Read with ffprobe; source unchanged" />
              <div className="px-4 py-2">
                <KeyValue label="Filename" value={video.original_filename} />
                <KeyValue label="Container" value={video.container} />
                <KeyValue label="Codec" value={video.codec} />
                <KeyValue label="Resolution" value={`${video.width} × ${video.height}`} />
                <KeyValue label="FPS" value={video.fps} />
                <KeyValue label="Duration" value={formatSeconds(video.duration)} />
                <KeyValue label="Size" value={`${(video.size_bytes / 1048576).toFixed(2)} MB`} />
                <KeyValue label="SHA-256" value={video.sha256} mono />
                <KeyValue label="Integrity" value={video.integrity_status} />
                <div className="pt-2"><Button size="sm" onClick={normalizeCopy}><RefreshCw className="h-3.5 w-3.5" /> Create normalized MP4 copy</Button></div>
                <p className="pt-2 text-[10px] text-muted">Normalization uses FFmpeg with safe argument arrays and leaves the original untouched.</p>
              </div>
            </Card>

            <Card>
              <CardHeader title="Timestamp alignment" subtitle="User-verified mapping" />
              {alignment ? (
                <div className="px-4 py-2">
                  <KeyValue label="Offset" value={`${alignment.offset_minutes} min`} />
                  <KeyValue label="Transaction in video" value={formatSeconds(alignment.transaction_video_seconds)} />
                  <KeyValue label="Analysis window" value={`${formatSeconds(alignment.window_start_seconds)} – ${formatSeconds(alignment.window_end_seconds)}`} />
                  <KeyValue label="Warnings" value={alignment.warnings.length ? alignment.warnings.join(" ") : "none"} />
                </div>
              ) : <EmptyState title="No alignment data" detail="Alignment is stored with each processing job." />}
            </Card>

            <Card className="p-4">
              <p className="flex items-start gap-2 text-[11px] leading-relaxed text-muted"><Radio className="mt-0.5 h-4 w-4 shrink-0 text-accent" />Original video files are never overwritten. Frame extraction reads the video incrementally and stores derived JPEGs in the case directory.</p>
            </Card>
          </div>
        </div>
      ) : (
        <Card><EmptyState title="No video selected" detail="Choose a case and video above, or upload a video in the guided workflow." /></Card>
      )}
      <p className="flex items-center gap-2 text-center text-[11px] text-muted"><Crosshair className="h-3.5 w-3.5" /> Manual frame capture does not perform face detection or CV similarity ranking; identity is never established automatically. {CV_ASSOCIATION_LIMITATION}</p>
    </div>
  );
}
