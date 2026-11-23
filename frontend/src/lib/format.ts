export function formatSeconds(value: number | undefined | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  const total = Math.max(0, value);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const base = `${String(minutes).padStart(2, "0")}:${seconds.toFixed(2).padStart(5, "0")}`;
  return hours ? `${String(hours).padStart(2, "0")}:${base}` : base;
}

export function formatBytes(value: number): string {
  if (!value) return "—";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function qualityTone(score: number): string {
  if (score >= 75) return "text-ok";
  if (score >= 50) return "text-warn";
  return "text-bad";
}

export function statusTone(status: string): string {
  const value = status.toLowerCase();
  if (["completed", "verified", "active", "selected"].includes(value)) return "text-ok border-ok/30 bg-ok/10";
  if (["failed", "cancelled", "archived"].includes(value)) return "text-bad border-bad/30 bg-bad/10";
  if (["running", "validating", "extracting"].includes(value)) return "text-accent border-accent/30 bg-accent/10";
  return "text-muted border-line bg-white/5";
}

export function toLocalInput(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 19);
}

export function fromLocalInput(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toISOString();
}
