import { NavLink, useLocation } from "react-router-dom";
import {
  Archive,
  Camera,
  ClipboardList,
  Files,
  GitCompareArrows,
  KeyRound,
  LayoutDashboard,
  RefreshCw,
  ScanFace,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { qs, sessionApi, systemApi } from "../lib/api";
import { cn } from "../lib/cn";
import type { ServiceHealthState, SessionState, SystemStatus } from "../lib/types";
import { Alert, Button, Field, Input, Modal } from "./ui";

export type ThemeMode = "light" | "dark";

export const THEME_STORAGE_KEY = "atm-theme";

export function resolveTheme(stored: string | null, prefersDark: boolean): ThemeMode {
  if (stored === "light" || stored === "dark") return stored;
  return prefersDark ? "dark" : "light";
}

function initialTheme(): ThemeMode {
  if (typeof window === "undefined") return "light";
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    return "light";
  }
  let prefersDark = false;
  try {
    prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return resolveTheme(stored, false);
  }
  return resolveTheme(stored, prefersDark);
}

const NAV = [
  { to: "/", label: "Command Center", icon: LayoutDashboard, hint: "Overview" },
  { to: "/cases", label: "Cases", icon: Archive, hint: "Case management" },
  { to: "/investigation", label: "New Investigation", icon: ClipboardList, hint: "Guided workflow" },
  { to: "/workspace", label: "Video Workspace", icon: Camera, hint: "Frames & timeline" },
  { to: "/evidence", label: "Evidence Gallery", icon: Files, hint: "Quality & selection" },
  { to: "/compare", label: "Case Comparison", icon: GitCompareArrows, hint: "Manual review" },
  { to: "/cv", label: "CV Review", icon: ScanFace, hint: "Candidate review" },
  { to: "/export", label: "Evidence Export", icon: ScanFace, hint: "PDF & manifest" },
];

export function deriveServiceHealth(status: SystemStatus | null, error: string | null, loading: boolean): ServiceHealthState {
  if (loading) return "loading";
  if (error || !status) return "error";
  const dependencies = Object.values(status.dependencies ?? {});
  if (!dependencies.length || dependencies.some((available) => !available)) return "degraded";
  return "healthy";
}

export function serviceHealthDetail(state: ServiceHealthState, status: SystemStatus | null): string {
  if (state === "loading") return "Checking the local status endpoint";
  if (state === "error") return "Status endpoint did not respond successfully";
  if (!status) return "Status response unavailable";
  if (state === "degraded") {
    const missing = Object.entries(status.dependencies ?? {}).filter(([, available]) => !available).map(([name]) => name);
    return `Status endpoint reachable; missing dependencies: ${missing.length ? missing.join(", ") : "unknown"}`;
  }
  return `Status endpoint reachable; ${status.app} ${status.version}; local dependencies available`;
}

export function ServiceHealthIndicator({
  state,
  detail,
  refreshing,
  onRefresh,
}: {
  state: ServiceHealthState;
  detail: string;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const label = state === "healthy" ? "Service available" : state === "degraded" ? "Service degraded" : state === "error" ? "Service unavailable" : "Checking status";
  const dotTone = state === "healthy" ? "bg-ok" : state === "degraded" ? "bg-warn" : state === "error" ? "bg-bad" : "bg-muted";
  const textTone = state === "healthy" ? "text-ok" : state === "degraded" ? "text-warn" : state === "error" ? "text-bad" : "text-muted";
  return (
    <button
      type="button"
      onClick={onRefresh}
      title={`${detail}. Select to refresh.`}
      aria-label="Refresh service status"
      className="flex items-center gap-2 rounded-md border border-line bg-ink-900 px-3 py-2 text-[11px] text-muted transition-colors hover:border-accent/40 hover:text-slate-200"
    >
      <span className={cn("h-2 w-2 rounded-full", dotTone)} />
      <span className={textTone}>{label}</span>
      <RefreshCw className={cn("h-3 w-3", refreshing ? "animate-spin" : "opacity-60")} />
      <span className="sr-only">{detail}</span>
    </button>
  );
}

export function SessionIndicator({
  session,
  error,
  onOpen,
}: {
  session: SessionState | null;
  error: string | null;
  onOpen: () => void;
}) {
  const label = error
    ? "Session check failed"
    : !session
      ? "Session unknown"
      : session.mode === "secured"
        ? session.protectedAccess
          ? "Protected access confirmed"
          : "Passphrase required"
        : "Open local mode";
  const tone = error || (session?.mode === "secured" && !session.protectedAccess) ? "text-warn" : session?.protectedAccess ? "text-ok" : "text-muted";
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn("flex items-center gap-2 rounded-md border border-line bg-ink-900 px-3 py-2 text-[11px] text-muted transition-colors hover:border-accent/40 hover:text-slate-200", tone)}
    >
      <KeyRound className="h-3 w-3" />
      {label}
    </button>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const current = NAV.find((item) => item.to === location.pathname) ?? NAV[0];
  const caseId = new URLSearchParams(location.search).get("case") ?? "";
  const navHref = (to: string) => `${to}${caseId ? qs({ case: caseId }) : ""}`;

  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [healthError, setHealthError] = useState("");
  const [healthLoading, setHealthLoading] = useState(true);
  const [refreshingHealth, setRefreshingHealth] = useState(false);
  const [session, setSession] = useState<SessionState | null>(null);
  const [sessionError, setSessionError] = useState("");
  const [sessionLoading, setSessionLoading] = useState(true);
  const [showSession, setShowSession] = useState(false);
  const [passphrase, setPassphrase] = useState("");
  const [theme, setTheme] = useState<ThemeMode>(initialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      void 0;
    }
  }, [theme]);

  const loadHealth = useCallback(async () => {
    setHealthLoading(true);
    setRefreshingHealth(true);
    try {
      const status = await systemApi.status();
      setSystemStatus(status);
      setHealthError("");
    } catch (reason) {
      setSystemStatus(null);
      setHealthError((reason as Error).message);
    } finally {
      setHealthLoading(false);
      setRefreshingHealth(false);
    }
  }, []);

  const loadSession = useCallback(async () => {
    setSessionLoading(true);
    setSessionError("");
    try {
      setSession(await sessionApi.probe());
    } catch (reason) {
      setSession(null);
      setSessionError((reason as Error).message);
    } finally {
      setSessionLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHealth();
    void loadSession();
  }, [loadHealth, loadSession]);

  const submitPassphrase = async () => {
    const submitted = passphrase;
    setPassphrase("");
    if (!submitted) {
      setSessionError("Enter the local passphrase.");
      return;
    }
    setSessionLoading(true);
    setSessionError("");
    try {
      const response = await sessionApi.login(submitted);
      setSession({ mode: response.mode === "secured" ? "secured" : "open", protectedAccess: true });
      setShowSession(false);
    } catch (reason) {
      setSessionError((reason as Error).message);
    } finally {
      setSessionLoading(false);
    }
  };

  const health = deriveServiceHealth(systemStatus, healthError, healthLoading);

  return (
    <div className="flex min-h-screen bg-ink-950">
      <aside className="fixed inset-y-0 left-0 z-30 flex w-[248px] flex-col border-r border-line bg-ink-900">
        <div className="flex items-center gap-3 border-b border-line px-5 py-5">
          <div className="grid h-9 w-9 place-items-center rounded-md border border-accent/40 bg-accent/10 text-accent">
            <ShieldAlert className="h-5 w-5" />
          </div>
          <div>
            <p className="text-sm font-bold tracking-wide text-white">ATM SENTINEL</p>
            <p className="text-[10px] uppercase tracking-[0.14em] text-muted">Evidence organization</p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto p-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={navHref(item.to)}
              className={({ isActive }) =>
                cn(
                  "group flex items-center gap-3 rounded-md border px-3 py-2.5 text-sm transition-colors",
                  isActive
                    ? "border-accent/30 bg-accent/10 text-accent"
                    : "border-transparent text-muted hover:border-line hover:bg-white/[0.03] hover:text-slate-100",
                )
              }
            >
              <item.icon className="h-4 w-4 shrink-0" />
              <span className="flex-1">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-line p-4">
          <p className="text-[10px] leading-relaxed text-muted">
            Prototype evidence organization, integrity tracking, and local CV candidate review.
          </p>
          <p className="mt-2 text-[10px] text-muted/70">Local-only · Detection and similarity produce candidates for human review, never identity conclusions</p>
        </div>
      </aside>

      <div className="ml-[248px] flex min-h-screen w-[calc(100%-248px)] flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-line bg-ink-950/95 px-6 py-4 backdrop-blur">
          <div>
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted">Transaction-driven CCTV evidence review</p>
            <h1 className="mt-0.5 text-lg font-semibold text-white">{current.label}</h1>
            <p className="mt-0.5 text-[11px] text-muted">{current.hint}</p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              aria-pressed={theme === "dark"}
              onClick={() => setTheme((currentTheme) => currentTheme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? "Light" : "Dark"}
            </Button>
            <ServiceHealthIndicator
              state={health}
              detail={serviceHealthDetail(health, systemStatus)}
              refreshing={refreshingHealth}
              onRefresh={() => void loadHealth()}
            />
            <SessionIndicator session={session} error={sessionError || null} onOpen={() => setShowSession(true)} />
          </div>
        </header>
        <main className="grid-bg flex-1 p-6">{children}</main>
      </div>

      <Modal open={showSession} onClose={() => { setShowSession(false); setPassphrase(""); }} title="Local session">
        <div className="space-y-4">
          <Alert>
            Backend mode: {session?.mode ?? "unknown"} · Protected access: {session ? (session.protectedAccess ? "confirmed" : "not confirmed") : "unknown"}.
            {session?.mode === "open" ? " No passphrase is required in open mode." : null}
          </Alert>
          {sessionError ? <Alert kind="error">{sessionError}</Alert> : null}
          <Field label="Local passphrase" hint="Submitted directly to the local backend. It is not stored in browser state after submission.">
            <Input type="password" value={passphrase} autoComplete="off" onChange={(event) => setPassphrase(event.target.value)} />
          </Field>
          <p className="text-[11px] leading-relaxed text-muted">
            Expiry: not reported by the backend. The current contract uses a browser-session cookie and has no logout endpoint; protected access is only shown after a protected endpoint accepts the session.
          </p>
          <div className="flex justify-end gap-2">
            <Button onClick={() => { setShowSession(false); setPassphrase(""); }}>Cancel</Button>
            <Button variant="solid" loading={sessionLoading} onClick={() => void submitPassphrase()}><ShieldCheck className="h-4 w-4" /> Unlock</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
