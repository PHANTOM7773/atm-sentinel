import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, ArrowUpRight, Database, Film, FolderOpen, Images, Plus, ScanLine, ShieldCheck } from "lucide-react";
import { api } from "../lib/api";
import { formatDate } from "../lib/format";
import { isDemoCase } from "../lib/demo";
import { CV_ASSOCIATION_LIMITATION } from "../lib/types";
import type { CaseRecord, SystemStatus } from "../lib/types";
import { Alert, Badge, Button, Card, CardHeader, DemoBadge, DemoDataBanner, EmptyState } from "../components/ui";

const STATS = [
  { key: "cases", label: "Cases", icon: FolderOpen, to: "/cases" },
  { key: "videos", label: "Uploaded videos", icon: Film, to: "/workspace" },
  { key: "jobs", label: "Processing jobs", icon: Activity, to: "/workspace" },
  { key: "frames", label: "Evidence items", icon: Images, to: "/evidence" },
];

export function DashboardPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.get<SystemStatus>("/api/system/status"), api.get<CaseRecord[]>("/api/cases")])
      .then(([system, caseList]) => {
        setStatus(system);
        setCases(caseList);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const hasDemoCases = cases.some(isDemoCase);

  return (
    <div className="mx-auto max-w-[1500px] space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.18em] text-accent">ATM Sentinel</p>
          <h2 className="mt-1 text-2xl font-semibold text-white">Investigation overview</h2>
          <p className="mt-1 text-sm text-muted">Counts reflect local records, including demo/sample records when present. They are not operational statistics.</p>
        </div>
        <Link to="/investigation">
          <Button variant="solid"><Plus className="h-4 w-4" /> New investigation</Button>
        </Link>
      </div>

      {error ? <Alert kind="error">{error}</Alert> : null}
      {hasDemoCases ? <DemoDataBanner subject="dashboard data" /> : null}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {STATS.map((stat) => (
          <Link key={stat.key} to={stat.to} className="group">
            <Card className="h-full p-4 transition-colors hover:border-accent/40">
              <div className="flex items-start justify-between">
                <div className="rounded-md border border-line bg-ink-900 p-2 text-accent"><stat.icon className="h-4 w-4" /></div>
                <ArrowUpRight className="h-4 w-4 text-muted opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
              <p className="mt-4 text-3xl font-semibold tabular-nums text-white">{status?.counts[stat.key] ?? "—"}</p>
              <p className="mt-1 text-xs text-muted">{stat.label}</p>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="Recent cases" subtitle="Locally stored case records" action={<Link to="/cases" className="text-xs text-accent hover:underline">Manage cases</Link>} />
          {cases.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[10px] uppercase tracking-wider text-muted">
                  <tr className="border-b border-line"><th className="px-4 py-2.5">Case no.</th><th className="px-4 py-2.5">Title</th><th className="px-4 py-2.5">Status</th><th className="px-4 py-2.5">Updated</th></tr>
                </thead>
                <tbody>
                  {cases.slice(0, 8).map((item) => (
                    <tr key={item.id} className="border-b border-line/50 last:border-0 hover:bg-white/[0.02]">
                      <td className="px-4 py-2.5"><span className="flex items-center gap-2 font-mono text-accent">{item.case_number}{isDemoCase(item) ? <DemoBadge /> : null}</span></td>
                      <td className="px-4 py-2.5 text-slate-200">{item.title}</td>
                      <td className="px-4 py-2.5"><Badge className={item.status === "active" ? "text-ok" : ""}>{item.status}</Badge></td>
                      <td className="px-4 py-2.5 text-muted">{formatDate(item.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No cases yet" detail="Create a case to begin a transaction-driven review." action={<Link to="/investigation"><Button variant="primary">Start guided workflow</Button></Link>} />
          )}
        </Card>

        <Card>
          <CardHeader title="System dependencies" subtitle="Checked at request time" />
          <div className="space-y-2 p-4">
            {Object.entries(status?.dependencies ?? {}).map(([name, available]) => (
              <div key={name} className="flex items-center justify-between rounded border border-line/70 bg-ink-900 px-3 py-2">
                <span className="font-mono text-xs text-slate-200">{name}</span>
                <Badge className={available ? "text-ok border-ok/30 bg-ok/10" : "text-bad border-bad/30 bg-bad/10"}>{available ? "available" : "missing"}</Badge>
              </div>
            ))}
            {Object.entries(status?.tool_versions ?? {}).map(([name, version]) => (
              <p key={name} className="truncate text-[10px] text-muted" title={version}>{name}: {version}</p>
            ))}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="Recent activity" subtitle="Append-only local audit events" />
          {status?.recent_activity.length ? (
            <div className="divide-y divide-line/60">
              {status.recent_activity.map((event) => (
                <div key={event.id} className="flex items-center gap-3 px-4 py-2.5 text-xs">
                  <Activity className="h-3.5 w-3.5 shrink-0 text-accent" />
                  <span className="flex-1 font-mono text-slate-200">{event.action}</span>
                  <span className="text-muted">{formatDate(event.created_at)}</span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="No activity recorded" detail="Case, upload, processing, and export actions will appear here." />
          )}
        </Card>

        <Card>
          <CardHeader title="Interpretation limits" subtitle="Read before reviewing frames" />
          <div className="space-y-3 p-4 text-xs leading-relaxed text-muted">
            <p className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" />{status?.disclaimer ?? "Prototype evidence organization and integrity tracking."}</p>
            <p className="flex gap-2"><ScanLine className="mt-0.5 h-4 w-4 shrink-0 text-accent" />{status?.quality_score_limitations ?? "Quality scores describe image usability only."}</p>
            <p className="flex gap-2"><Database className="mt-0.5 h-4 w-4 shrink-0 text-accent" />All uploads, frames, and reports remain inside this project's local data directory.</p>
            <p className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" />Face detection locates face regions; CV similarity ranks candidates only. Reviewers decide relevance; identity conclusions are not produced.</p>
            <p className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" />{CV_ASSOCIATION_LIMITATION}</p>
          </div>
        </Card>
      </div>
    </div>
  );
}
