interface KPICardProps {
  label: string;
  value: string;
  hint?: string;
  variant?: "default" | "warning";
}

export function KPICard({ label, value, hint, variant = "default" }: KPICardProps) {
  const isWarning = variant === "warning";
  return (
    <div
      className={`rounded-lg border bg-card p-4 transition-all duration-300 sm:p-6 ${
        isWarning ? "border-destructive/50 shadow-[0_0_20px_rgba(248,81,73,0.15)]" : "border-border shadow-[0_0_15px_rgba(0,212,200,0.08)]"
      }`}
    >
      <div className="mb-3 font-mono text-[11px] uppercase tracking-[0.1em] text-muted-foreground">{label}</div>
      <div className={`mb-2 font-mono text-2xl leading-none sm:text-[32px] ${isWarning ? "text-destructive" : "text-foreground"}`}>{value}</div>
      {hint && <div className="font-mono text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}
