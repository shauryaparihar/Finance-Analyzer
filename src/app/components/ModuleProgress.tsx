import type { ReactNode } from "react";
import { Check, Circle, Loader2, MinusCircle, XCircle } from "lucide-react";
import { duration } from "../lib/format";
import { MODULE_LABELS, RUN_STATUS_LABELS } from "../lib/status";
import type { ModuleStatus, RunStatus } from "../types";
import { Pill, Tone } from "./common";

const ICONS: Record<RunStatus, ReactNode> = {
  pending: <Circle className="h-4 w-4 text-muted-foreground" />,
  running: <Loader2 className="h-4 w-4 animate-spin text-primary" />,
  completed: <Check className="h-4 w-4 text-primary" />,
  failed: <XCircle className="h-4 w-4 text-destructive" />,
  skipped: <MinusCircle className="h-4 w-4 text-[#FFA657]" />,
};

const TONE: Record<RunStatus, Tone> = { pending: "neutral", running: "info", completed: "good", failed: "bad", skipped: "warn" };

/** One row per analysis step, so a person can see which finished, which was skipped and which failed. */
export function ModuleProgress({ modules }: { modules: ModuleStatus[] }) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {modules.map((m) => (
        <li key={m.module} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-sm">
          {ICONS[m.status]}
          <span className="flex-1 text-foreground">{MODULE_LABELS[m.module]}</span>
          <span className="font-mono text-xs text-muted-foreground">{m.status === "completed" ? duration(m.duration_ms) : ""}</span>
          <Pill tone={TONE[m.status]}>{RUN_STATUS_LABELS[m.status]}</Pill>
          {(m.status === "failed" || m.status === "skipped") && m.error_message && (
            <p className="basis-full pl-7 text-xs text-muted-foreground">{m.error_message}</p>
          )}
        </li>
      ))}
    </ul>
  );
}
