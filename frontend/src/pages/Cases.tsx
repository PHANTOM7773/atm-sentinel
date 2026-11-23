import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Archive, ArrowRight, FileVideo, Plus, Save, Search, StickyNote } from "lucide-react";
import { api, qs } from "../lib/api";
import { formatBytes, formatDate, fromLocalInput, toLocalInput } from "../lib/format";
import { isDemoCase, isDemoTransaction, isDemoVideo } from "../lib/demo";
import { CV_ASSOCIATION_LIMITATION } from "../lib/types";
import type { CaseRecord, ClipLink, NoteRecord, TimelineEvent, TransactionRecord, VideoRecord } from "../lib/types";
import { Alert, Badge, Button, Card, CardHeader, DemoBadge, DemoDataBanner, EmptyState, Field, Input, Modal, Select, Textarea } from "../components/ui";

const tagsOf = (value: string) => value.split(",").map((tag) => tag.trim()).filter(Boolean);

export function CasesPage() {
  const [params, setParams] = useSearchParams();
  const caseParam = params.get("case") ?? "";
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [selectedId, setSelectedId] = useState(caseParam);
  const [transactions, setTransactions] = useState<TransactionRecord[]>([]);
  const [videos, setVideos] = useState<VideoRecord[]>([]);
  const [notes, setNotes] = useState<NoteRecord[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [links, setLinks] = useState<ClipLink[]>([]);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<{ cases: CaseRecord[]; videos: VideoRecord[] } | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showCaseForm, setShowCaseForm] = useState(false);
  const [showTxForm, setShowTxForm] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [caseForm, setCaseForm] = useState({ case_number: "", title: "", location: "", tags: "" });
  const [videoTagDrafts, setVideoTagDrafts] = useState<Record<string, string>>({});
  const [txForm, setTxForm] = useState({
    reference: "",
    atm_id: "",
    transaction_ts: "",
    cctv_ts: "",
    transaction_type: "withdrawal",
    amount: "",
    note: "",
  });
  const [noteBody, setNoteBody] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [editLocation, setEditLocation] = useState("");
  const [editTags, setEditTags] = useState("");

  const loadCases = useCallback(() => {
    api.get<CaseRecord[]>("/api/cases?include_archived=true")
      .then((data) => {
        setCases(data);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    setSelectedId(caseParam);
  }, [caseParam]);

  const selectCase = (nextCase: string) => {
    setSelectedId(nextCase);
    setParams(nextCase ? { case: nextCase } : {});
  };

  const loadDetail = useCallback(() => {
    if (!selectedId) return;
    Promise.all([
      api.get<TransactionRecord[]>(`/api/cases/${selectedId}/transactions`),
      api.get<VideoRecord[]>(`/api/videos${qs({ case_id: selectedId })}`),
      api.get<NoteRecord[]>(`/api/cases/${selectedId}/notes`),
      api.get<TimelineEvent[]>(`/api/cases/${selectedId}/timeline`),
      api.get<ClipLink[]>(`/api/cases/${selectedId}/links`),
    ])
      .then(([tx, vid, note, time, link]) => {
        setTransactions(tx);
        setVideos(vid);
        setVideoTagDrafts(Object.fromEntries(vid.map((item) => [item.id, item.tags])));
        setNotes(note);
        setTimeline(time);
        setLinks(link);
      })
      .catch((reason: Error) => setError(reason.message));
  }, [selectedId]);

  useEffect(loadCases, [loadCases]);
  useEffect(loadDetail, [loadDetail]);
  useEffect(() => {
    const current = cases.find((item) => item.id === selectedId);
    if (current) {
      setEditTitle(current.title);
      setEditLocation(current.location);
      setEditTags(current.tags);
    }
  }, [selectedId, cases]);

  useEffect(() => {
    const term = query.trim();
    if (!term) {
      setSearchResults(null);
      return;
    }
    const timer = window.setTimeout(() => {
      api.get<{ cases: CaseRecord[]; videos: VideoRecord[] }>(`/api/search${qs({ q: term })}`)
        .then(setSearchResults)
        .catch((reason: Error) => setError(reason.message));
    }, 200);
    return () => window.clearTimeout(timer);
  }, [query]);

  const filtered = useMemo(() => {
    const term = query.toLowerCase().trim();
    if (!term) return cases;
    return cases.filter((item) => `${item.case_number} ${item.title} ${item.location} ${item.tags}`.toLowerCase().includes(term));
  }, [cases, query]);

  const handleCreateCase = async () => {
    try {
      const created = await api.post<CaseRecord>("/api/cases", caseForm);
      setShowCaseForm(false);
      setCaseForm({ case_number: "", title: "", location: "", tags: "" });
      selectCase(created.id);
      setNotice(`Case ${created.case_number} created`);
      loadCases();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const handleSaveCase = async () => {
    try {
      await api.patch(`/api/cases/${selectedId}`, { title: editTitle, location: editLocation, tags: editTags });
      setNotice("Case metadata updated");
      loadCases();
      loadDetail();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const handleSaveVideoTags = async (video: VideoRecord) => {
    try {
      await api.patch(`/api/videos/${video.id}`, { tags: videoTagDrafts[video.id] ?? video.tags });
      setNotice("Video tags updated");
      loadDetail();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const handleArchive = async () => {
    const current = cases.find((item) => item.id === selectedId);
    if (!current) return;
    try {
      await api.post(`/api/cases/${selectedId}/archive${qs({ archived: current.status === "active" })}`);
      setNotice(current.status === "active" ? "Case archived" : "Case restored");
      loadCases();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const handleTransaction = async () => {
    try {
      await api.post(`/api/cases/${selectedId}/transactions`, {
        ...txForm,
        transaction_ts: fromLocalInput(txForm.transaction_ts),
        cctv_ts: fromLocalInput(txForm.cctv_ts),
      });
      setShowTxForm(false);
      setTxForm({ reference: "", atm_id: "", transaction_ts: "", cctv_ts: "", transaction_type: "withdrawal", amount: "", note: "" });
      setNotice("Transaction added");
      loadDetail();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const handleUpload = async (file: File | undefined) => {
    if (!file || !selectedId) return;
    setUploading(true);
    setError("");
    try {
      const result = await api.upload<VideoRecord>(`/api/videos/upload${qs({ case_id: selectedId })}`, file);
      setNotice(`Uploaded ${result.original_filename} · ${result.width}x${result.height} · integrity ${result.integrity_status}`);
      loadDetail();
      loadCases();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setUploading(false);
    }
  };

  const handleNote = async () => {
    if (!noteBody.trim()) return;
    try {
      await api.post(`/api/cases/${selectedId}/notes`, { body: noteBody });
      setNoteBody("");
      setNotice("Note added");
      loadDetail();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const current = cases.find((item) => item.id === selectedId);
  const currentDemo = current ? isDemoCase(current) : false;

  return (
    <div className="mx-auto max-w-[1500px] space-y-5">
      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert>{notice}</Alert> : null}
      {caseParam && cases.length > 0 && !current ? <Alert kind="warn">The selected case is unavailable. Choose a case from the list.</Alert> : null}
      {currentDemo ? <DemoDataBanner subject="case" /> : null}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader title="Cases" subtitle={`${cases.length} local records`} action={<Button size="sm" variant="primary" onClick={() => setShowCaseForm(true)}><Plus className="h-3.5 w-3.5" /> New</Button>} />
          <div className="border-b border-line p-3">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted" />
              <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search cases" className="pl-8" />
            </div>
          </div>
          <div className="max-h-[620px] divide-y divide-line/60 overflow-y-auto">
            {filtered.map((item) => (
              <button key={item.id} onClick={() => selectCase(item.id)} className={`w-full px-4 py-3 text-left transition-colors ${item.id === selectedId ? "bg-accent/10" : "hover:bg-white/[0.03]"}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 font-mono text-xs text-accent">{item.case_number}{isDemoCase(item) ? <DemoBadge /> : null}</span>
                  <Badge className={item.status === "active" ? "text-ok" : ""}>{item.status}</Badge>
                </div>
                <p className="mt-1 truncate text-sm text-slate-200">{item.title}</p>
                <p className="mt-1 text-[11px] text-muted">{formatDate(item.updated_at)}</p>
                {tagsOf(item.tags).length ? <div className="mt-2 flex flex-wrap gap-1">{tagsOf(item.tags).map((tag) => <Badge key={tag} className="text-[9px]">{tag}</Badge>)}</div> : null}
              </button>
            ))}
            {!filtered.length ? <EmptyState title="No matching cases" detail="Create a case or clear the search filter." /> : null}
          </div>
        </Card>

        {searchResults ? (
          <Card>
            <CardHeader title="Matching clips" subtitle={`${searchResults.videos.length} metadata/tag matches`} />
            <div className="divide-y divide-line/60">
              {searchResults.videos.map((video) => (
                <button key={video.id} onClick={() => selectCase(video.case_id)} className="block w-full px-4 py-2 text-left hover:bg-white/[0.03]">
                  <p className="flex items-center gap-2 truncate text-xs text-slate-200">{video.original_filename}{isDemoVideo(video) ? <DemoBadge label="Demo clip" /> : null}</p>
                  <p className="mt-1 text-[10px] text-muted">{video.container} · {video.codec} · {video.width}x{video.height}</p>
                  {tagsOf(video.tags).length ? <div className="mt-1 flex flex-wrap gap-1">{tagsOf(video.tags).map((tag) => <Badge key={tag} className="text-[9px]">{tag}</Badge>)}</div> : null}
                </button>
              ))}
              {!searchResults.videos.length ? <p className="px-4 py-3 text-xs text-muted">No clips match this search.</p> : null}
            </div>
          </Card>
        ) : null}

        {current ? (
          <div className="space-y-5">
            <Card>
              <CardHeader title={current.case_number} subtitle={`Created ${formatDate(current.created_at)}`} action={<span className="flex items-center gap-2">{currentDemo ? <DemoBadge /> : null}<Badge className={current.status === "active" ? "text-ok" : ""}>{current.status}</Badge></span>} />
              <div className="grid gap-4 p-4 md:grid-cols-2">
                <Field label="Case title"><Input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} /></Field>
                <Field label="Location / description"><Input value={editLocation} onChange={(event) => setEditLocation(event.target.value)} /></Field>
                <Field label="Tags" hint="Comma-separated labels for metadata search"><Input value={editTags} onChange={(event) => setEditTags(event.target.value)} placeholder="atm-01, demo" /></Field>
              </div>
              <div className="flex flex-wrap gap-2 border-t border-line px-4 py-3">
                <Button size="sm" onClick={handleSaveCase}><Save className="h-3.5 w-3.5" /> Save metadata</Button>
                <Button size="sm" variant={current.status === "active" ? "ghost" : "primary"} onClick={handleArchive}><Archive className="h-3.5 w-3.5" /> {current.status === "active" ? "Archive case" : "Restore case"}</Button>
                <Link to={`/investigation${qs({ case: current.id })}`}><Button size="sm" variant="primary">Continue investigation <ArrowRight className="h-3.5 w-3.5" /></Button></Link>
                <Link to={`/cv${qs({ case: current.id })}`}><Button size="sm">CV review <ArrowRight className="h-3.5 w-3.5" /></Button></Link>
              </div>
            </Card>

            <div className="grid gap-5 lg:grid-cols-2">
              <Card>
                <CardHeader title="Transactions" subtitle={`${transactions.length} recorded`} action={<Button size="sm" variant="primary" onClick={() => setShowTxForm(true)}><Plus className="h-3.5 w-3.5" /> Add</Button>} />
                <div className="divide-y divide-line/60">
                  {transactions.map((tx) => (
                    <div key={tx.id} className="px-4 py-3 text-xs">
                      <div className="flex justify-between gap-2"><span className="flex items-center gap-2 font-mono text-accent">{tx.reference}{isDemoTransaction(tx) ? <DemoBadge label="Demo record" /> : null}</span><Badge>{tx.transaction_type}</Badge></div>
                      <p className="mt-1 text-muted">ATM: {tx.atm_id || "—"} · Amount: {tx.amount || "—"}</p>
                      <p className="mt-1 font-mono text-[11px] text-slate-300">TX {tx.transaction_ts}</p>
                      <p className="font-mono text-[11px] text-slate-300">CCTV {tx.cctv_ts || "not set"}</p>
                    </div>
                  ))}
                  {!transactions.length ? <EmptyState title="No transactions" detail="Add an anonymized transaction reference and timestamps." /> : null}
                </div>
                <div className="border-t border-line p-4">
                  <p className="text-[11px] leading-relaxed text-muted">{CV_ASSOCIATION_LIMITATION}</p>
                </div>
              </Card>

              <Card>
                <CardHeader title="Videos" subtitle={`${videos.length} uploaded · originals preserved`} />
                <div className="divide-y divide-line/60">
                  {videos.map((video) => (
                    <div key={video.id} className="px-4 py-3 text-xs">
                      <div className="flex items-center gap-2"><FileVideo className="h-4 w-4 text-accent" /><span className="flex items-center gap-2 truncate font-medium text-slate-200">{video.original_filename}{isDemoVideo(video) ? <DemoBadge label="Demo clip" /> : null}</span></div>
                      <p className="mt-1 text-muted">{video.width}x{video.height} · {video.fps} fps · {video.duration}s · {formatBytes(video.size_bytes)}</p>
                      <p className="mt-1 truncate font-mono text-[10px] text-muted">SHA-256 {video.sha256}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Badge className={video.integrity_status === "verified" ? "text-ok" : video.integrity_status === "failed" ? "text-bad" : ""}>{video.integrity_status}</Badge>
                        {tagsOf(video.tags).map((tag) => <Badge key={tag} className="text-[9px]">{tag}</Badge>)}
                      </div>
                      <div className="mt-2 flex gap-2">
                        <Input value={videoTagDrafts[video.id] ?? video.tags} onChange={(event) => setVideoTagDrafts({ ...videoTagDrafts, [video.id]: event.target.value })} placeholder="Tags, comma separated" />
                        <Button size="sm" onClick={() => handleSaveVideoTags(video)}>Save tags</Button>
                      </div>
                    </div>
                  ))}
                  {!videos.length ? <EmptyState title="No videos uploaded" detail="Upload MP4, AVI, MOV or MKV footage from the guided workflow." /> : null}
                </div>
                <div className="border-t border-line p-4">
                  <Field label="Add video to case" hint="File bytes stay local. Accepted: MP4, AVI, MOV, MKV.">
                    <Input type="file" accept=".mp4,.avi,.mov,.mkv,video/*" disabled={uploading} onChange={(event) => handleUpload(event.target.files?.[0])} />
                    <p className="mt-1 text-[11px] text-muted">DVR/NVR exports: use the vendor export/backup function to produce H.264 MP4. WMV, FLV, MPEG and MPG are not accepted; convert and preserve the original clip for evidence.</p>
                  </Field>
                  {uploading ? <p className="mt-2 text-xs text-accent">Validating and hashing video…</p> : null}
                </div>
              </Card>
            </div>

            <div className="grid gap-5 lg:grid-cols-2">
              <Card>
                <CardHeader title="Notes" subtitle="Investigator annotations" />
                <div className="space-y-3 p-4">
                  <Textarea value={noteBody} onChange={(event) => setNoteBody(event.target.value)} placeholder="Record an observation or rationale…" />
                  <Button size="sm" onClick={handleNote}><StickyNote className="h-3.5 w-3.5" /> Add note</Button>
                  <div className="max-h-56 divide-y divide-line/60 overflow-y-auto">
                    {notes.map((note) => (
                      <div key={note.id} className="py-2 text-xs">
                        <p className="text-slate-200">{note.body}</p>
                        <p className="mt-1 text-[10px] text-muted">{formatDate(note.created_at)}</p>
                      </div>
                    ))}
                    {!notes.length ? <p className="py-2 text-xs text-muted">No notes recorded.</p> : null}
                  </div>
                </div>
              </Card>

              <Card>
                <CardHeader title="Case timeline" subtitle="Derived from local records" />
                <div className="max-h-96 divide-y divide-line/60 overflow-y-auto">
                  {timeline.map((event, index) => (
                    <div key={`${event.at}-${index}`} className="flex gap-3 px-4 py-2.5 text-xs">
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                      <div className="min-w-0 flex-1"><p className="text-slate-200">{event.label}: <span className="text-muted">{event.detail}</span></p><p className="text-[10px] text-muted">{formatDate(event.at)}</p></div>
                    </div>
                  ))}
                  {!timeline.length ? <EmptyState title="Empty timeline" detail="Case activity will appear as records are added." /> : null}
                </div>
              </Card>
            </div>

            {links.length ? (
              <Card>
                <CardHeader title="Documented clip relationships" subtitle="Manually recorded by an investigator" />
                <div className="divide-y divide-line/60">
                  {links.map((link) => <div key={link.id} className="px-4 py-2 text-xs"><span className="font-mono text-accent">{link.video_a.slice(0, 8)} ↔ {link.video_b.slice(0, 8)}</span><p className="mt-1 text-muted">{link.reason}</p></div>)}
                </div>
              </Card>
            ) : null}
          </div>
        ) : (
          <Card><EmptyState title="Select or create a case" detail="Choose a case from the list to manage transactions, videos, notes, and its timeline." /></Card>
        )}
      </div>

      <Modal open={showCaseForm} onClose={() => setShowCaseForm(false)} title="Create case">
        <div className="space-y-4">
          <Field label="Case number" hint="Use an anonymized internal reference — do not enter personal details."><Input value={caseForm.case_number} onChange={(event) => setCaseForm({ ...caseForm, case_number: event.target.value })} placeholder="DEMO-2026-0002" /></Field>
          <Field label="Title"><Input value={caseForm.title} onChange={(event) => setCaseForm({ ...caseForm, title: event.target.value })} placeholder="ATM CCTV review — synthetic demo" /></Field>
                    <Field label="Location / description"><Input value={caseForm.location} onChange={(event) => setCaseForm({ ...caseForm, location: event.target.value })} /></Field>
          <Field label="Tags" hint="Optional comma-separated labels, for example: atm-01, demo"><Input value={caseForm.tags} onChange={(event) => setCaseForm({ ...caseForm, tags: event.target.value })} placeholder="atm-01, demo" /></Field>
          <div className="flex justify-end gap-2">
<Button onClick={() => setShowCaseForm(false)}>Cancel</Button><Button variant="solid" onClick={handleCreateCase}>Create case</Button></div>
        </div>
      </Modal>

      <Modal open={showTxForm} onClose={() => setShowTxForm(false)} title="Add transaction">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Transaction reference"><Input value={txForm.reference} onChange={(event) => setTxForm({ ...txForm, reference: event.target.value })} placeholder="DEMO-TX-002" /></Field>
          <Field label="ATM identifier"><Input value={txForm.atm_id} onChange={(event) => setTxForm({ ...txForm, atm_id: event.target.value })} placeholder="ATM-DEMO-01" /></Field>
          <Field label="Transaction timestamp"><Input type="datetime-local" step="1" value={txForm.transaction_ts} onChange={(event) => setTxForm({ ...txForm, transaction_ts: event.target.value })} /></Field>
          <Field label="CCTV timestamp at same moment"><Input type="datetime-local" step="1" value={txForm.cctv_ts} onChange={(event) => setTxForm({ ...txForm, cctv_ts: event.target.value })} /></Field>
          <Field label="Type"><Select value={txForm.transaction_type} onChange={(event) => setTxForm({ ...txForm, transaction_type: event.target.value })}><option value="withdrawal">Withdrawal</option><option value="deposit">Deposit</option><option value="balance_enquiry">Balance enquiry</option><option value="card_retained">Card retained</option><option value="other">Other</option></Select></Field>
          <Field label="Amount (optional demo value)"><Input value={txForm.amount} onChange={(event) => setTxForm({ ...txForm, amount: event.target.value })} /></Field>
          <Field label="Notes" className="sm:col-span-2"><Textarea value={txForm.note} onChange={(event) => setTxForm({ ...txForm, note: event.target.value })} /></Field>
          <div className="flex justify-end gap-2 sm:col-span-2"><Button onClick={() => setShowTxForm(false)}>Cancel</Button><Button variant="solid" onClick={handleTransaction}>Add transaction</Button></div>
        </div>
      </Modal>
    </div>
  );
}
