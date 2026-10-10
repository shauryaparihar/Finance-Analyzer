import { ReactNode } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info, Loader2 } from "lucide-react";
import { Link } from "react-router";
import { friendlyMessage } from "../api";
import { cn } from "./ui/utils";

export type Tone = "good" | "warn" | "bad" | "neutral" | "info";

const TONES: Record<Tone, string> = {
  good: "bg-primary/15 text-primary",
  warn: "bg-[#FFA657]/15 text-[#FFA657]",
  bad: "bg-destructive/15 text-destructive",
  neutral: "bg-muted/60 text-muted-foreground",
  info: "bg-[#58A6FF]/15 text-[#58A6FF]",
};

export function Pill({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded px-2 py-0.5 font-mono text-xs", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("rounded-lg border border-border bg-card p-4 sm:p-6", className)}>{children}</div>;
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h3 className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{children}</h3>
      {action}
    </div>
  );
}

export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-6 sm:mb-8">
      <h2 className="font-sans text-2xl text-foreground sm:text-3xl">{title}</h2>
      {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
    </div>
  );
}

export function Spinner({ label = "Loading..." }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-12" role="status">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
      <p className="font-mono text-sm text-muted-foreground">{label}</p>
    </div>
  );
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <div className="flex-1">
        <p className="text-foreground">{friendlyMessage(error)}</p>
        {onRetry && (
          <button onClick={onRetry} className="mt-2 text-primary underline-offset-4 hover:underline">
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "good"; children: ReactNode }) {
  const styles = {
    info: ["border-[#58A6FF]/40 bg-[#58A6FF]/10", Info, "text-[#58A6FF]"],
    warn: ["border-[#FFA657]/40 bg-[#FFA657]/10", AlertTriangle, "text-[#FFA657]"],
    good: ["border-primary/40 bg-primary/10", CheckCircle2, "text-primary"],
  } as const;
  const [box, Icon, color] = styles[tone];
  return (
    <div role="status" className={cn("flex items-start gap-3 rounded-lg border p-4 text-sm", box)}>
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", color)} />
      <div className="flex-1 text-foreground">{children}</div>
    </div>
  );
}

export function EmptyState({ title, children, linkTo, linkLabel }: { title: string; children?: ReactNode; linkTo?: string; linkLabel?: string }) {
  return (
    <div className="flex items-center justify-center p-6 sm:p-12">
      <div className="max-w-md rounded-lg border border-border bg-card p-8 text-center">
        <h2 className="mb-2 font-sans text-xl text-foreground">{title}</h2>
        {children && <div className="mb-6 text-sm text-muted-foreground">{children}</div>}
        {linkTo && (
          <Link to={linkTo} className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            {linkLabel ?? "Continue"}
          </Link>
        )}
      </div>
    </div>
  );
}

export function Disclaimer({ children }: { children: ReactNode }) {
  return <p className="mt-6 text-xs text-muted-foreground">{children}</p>;
}

/** Shown when the browser did not keep the login cookie: a reload will log the person out. */
export function CookieNotice() {
  return (
    <Notice tone="warn">
      <strong>Your browser did not keep the login cookie</strong>, so you will be logged out when you reload this page or after about 15 minutes.
      If you run this site yourself, serve the website and its API from the same web address (see &quot;Login security&quot; in the README).
    </Notice>
  );
}
