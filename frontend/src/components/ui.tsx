import type * as React from "react";
import { type ButtonHTMLAttributes, type ReactNode, useEffect, useId, useRef } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { LoaderCircle, ShieldCheck } from "lucide-react";
import { cn } from "../lib/cn";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md border text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
  {
    variants: {
      variant: {
        primary: "border-accent/60 bg-accent/15 text-accent hover:bg-accent/25",
        solid: "border-accent bg-accent text-ink-950 hover:bg-muted",
        secondary: "border-line bg-ink-800 text-slate-200 hover:border-accent/50 hover:text-white",
        ghost: "border-transparent bg-transparent text-muted hover:bg-white/5 hover:text-white",
        danger: "border-bad/40 bg-bad/10 text-bad hover:bg-bad/20",
      },
      size: {
        sm: "h-8 px-2.5 text-xs",
        md: "h-9 px-3.5",
        lg: "h-11 px-5",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  loading?: boolean;
}

export function Button({ className, variant, size, loading, children, disabled, ...props }: ButtonProps) {
  return (
    <button className={cn(buttonVariants({ variant, size }), className)} disabled={disabled || loading} {...props}>
      {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cn("rounded-lg border border-line bg-ink-850/80 shadow-[0_1px_0_rgba(255,255,255,0.03)_inset]", className)}>{children}</section>;
}

export function CardHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
      <div>
        <h2 className="text-sm font-semibold tracking-wide text-slate-100">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-xs text-muted">{subtitle}</p> : null}
      </div>
      {action}
    </header>
  );
}

export function Badge({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("inline-flex items-center rounded border border-line bg-white/5 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted", className)}>{children}</span>;
}

export function DemoBadge({ label = "Demo data" }: { label?: string }) {
  return <Badge className="border-warn/40 bg-warn/10 text-warn">{label}</Badge>;
}

export function Field({ label, hint, children, className }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-muted">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[11px] leading-relaxed text-muted/80">{hint}</span> : null}
    </label>
  );
}

const inputClass =
  "h-9 w-full rounded-md border border-line bg-ink-900 px-3 text-sm text-slate-100 outline-none placeholder:text-muted/60 focus:border-accent/70 focus:ring-1 focus:ring-accent/30";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(inputClass, props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cn(inputClass, "pr-8", props.className)} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(inputClass, "h-auto min-h-[76px] py-2", props.className)} />;
}

export function EmptyState({ title, detail, action }: { title: string; detail: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <div className="rounded-full border border-line bg-ink-900 p-3 text-muted">
        <ShieldCheck className="h-5 w-5" />
      </div>
      <p className="text-sm font-medium text-slate-200">{title}</p>
      <p className="max-w-md text-xs leading-relaxed text-muted">{detail}</p>
      {action}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    panelRef.current?.focus();
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby={titleId} onMouseDown={onClose}>
      <div ref={panelRef} tabIndex={-1} className={cn("max-h-[90vh] w-full overflow-auto rounded-lg border border-line bg-ink-850 shadow-2xl focus:outline-none", wide ? "max-w-5xl" : "max-w-xl")} onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h3 id={titleId} className="text-sm font-semibold text-slate-100">{title}</h3>
          <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-700">
      <div className="h-full rounded-full bg-accent transition-all duration-300" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  );
}

export function KeyValue({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-line/60 py-2 last:border-0">
      <span className="text-[10px] uppercase tracking-wider text-muted">{label}</span>
      <span className={cn("break-all text-xs text-slate-200", mono && "font-mono text-[11px]")}>{value ?? "—"}</span>
    </div>
  );
}

export function Alert({ kind = "info", children }: { kind?: "info" | "warn" | "error"; children: ReactNode }) {
  const tone = kind === "error" ? "border-bad/40 bg-bad/10 text-bad" : kind === "warn" ? "border-warn/40 bg-warn/10 text-warn" : "border-accent/30 bg-accent/10 text-accent";
  return <div className={cn("rounded-md border px-3 py-2 text-xs leading-relaxed", tone)}>{children}</div>;
}

export function DemoDataBanner({ subject = "record" }: { subject?: string }) {
  return <Alert kind="warn">Demo/sample data: this {subject} is marked as demonstration or synthetic content. Do not treat it as genuine investigator material.</Alert>;
}
