import { useState } from "react";
import { Check, Undo2, X } from "lucide-react";
import { ApiError, friendlyMessage, getAnomalies, reviewUnusual } from "../../api";
import { useAppContext } from "../../context/AppContext";
import { useResource } from "../../hooks/useResource";
import { amount, shortDate } from "../../lib/format";
import { whyNoResult } from "../../lib/status";
import type { Anomalies, ModuleStatus, ReviewStatus, UnusualItem } from "../../types";
import { Card, Disclaimer, ErrorNotice, Notice, PageHeader, Pill, Spinner } from "../common";
import { Button } from "../ui/button";
import { UploadGate } from "../UploadGate";

export function UnusualPage() {
  return <UploadGate>{(status) => <UnusualContent modules={status.modules} />}</UploadGate>;
}

const STATUS_TONE = { unreviewed: "neutral", confirmed: "warn", dismissed: "good" } as const;
const STATUS_TEXT: Record<ReviewStatus, string> = { unreviewed: "To review", confirmed: "Confirmed", dismissed: "Dismissed" };

function UnusualContent({ modules }: { modules: ModuleStatus[] }) {
  const { uploadId } = useAppContext();
  const id = uploadId as string;
  const data = useResource(() => getAnomalies(id), [id]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pending, setPending] = useState<number | null>(null);

  if (data.loading && !data.data) return <Spinner label="Loading unusual transactions..." />;
  if (data.error !== null) {
    const missing = data.error instanceof ApiError && data.error.status === 404;
    return <div className="p-4 sm:p-8">{missing ? <Notice tone="warn">{whyNoResult(modules, "anomaly")}</Notice> : <ErrorNotice error={data.error} onRetry={data.reload} />}</div>;
  }
  const result = data.data as Anomalies;

  async function decide(item: UnusualItem, status: ReviewStatus) {
    setPending(item.transaction_id);
    setActionError(null);
    try {
      await reviewUnusual(item.transaction_id, status);
      data.reload(); // counts and ordering come from the server
    } catch (e) {
      setActionError(friendlyMessage(e));
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="space-y-6 p-4 sm:p-8">
      <PageHeader
        title="Unusual transactions"
        subtitle="Expenses that stand out from your usual spending for their category, so you can check the few that matter."
      />
      <Notice tone="info">
        <strong>Unusual does not mean fraudulent.</strong> {result.disclaimer.replace(/^Unusual does not mean fraudulent\.\s*/, "")}
      </Notice>

      {result.status === "skipped" && <Notice tone="warn">{result.reason}</Notice>}
      {result.status === "not_available" && <Notice tone="warn">{result.reason ?? whyNoResult(modules, "anomaly")}</Notice>}

      {result.status === "completed" && (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <span>{result.items.length} to look at (up to {result.review_capacity}) from {result.expenses_scanned} expenses</span>
            <Pill tone="neutral">{result.reviewed} of {result.items.length} reviewed</Pill>
            {result.confirmed > 0 && <Pill tone="warn">{result.confirmed} confirmed</Pill>}
            {result.dismissed > 0 && <Pill tone="good">{result.dismissed} dismissed</Pill>}
          </div>
          {result.decisions_outside_queue > 0 && (
            <Notice tone="info">{result.decisions_outside_queue} earlier decision{result.decisions_outside_queue === 1 ? "" : "s"} belong to transactions no longer in this list (for example after you corrected a category). They are kept.</Notice>
          )}
          {actionError && <ErrorNotice error={new Error(actionError)} />}

          {result.items.length === 0 ? (
            <Card><p className="text-sm text-muted-foreground">{result.reason ?? "No expense stood out from your usual spending for its category."}</p></Card>
          ) : (
            <ul className="space-y-3">
              {result.items.map((item) => (
                <li key={item.transaction_id} className="rounded-lg border border-border bg-card p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-muted-foreground">#{item.rank}</span>
                        <span className="font-mono text-lg text-foreground">{amount(item.amount)}</span>
                        <Pill tone="neutral">{item.category}</Pill>
                        <Pill tone={STATUS_TONE[item.review_status]}>{STATUS_TEXT[item.review_status]}</Pill>
                      </div>
                      <p className="truncate text-sm text-foreground" title={item.description ?? ""}>{item.description ?? "(no description)"}</p>
                      <p className="text-xs text-muted-foreground">{shortDate(item.date)}</p>
                      {item.reason && <p className="mt-2 text-sm text-muted-foreground">{item.reason}</p>}
                    </div>
                    <div className="flex shrink-0 gap-2">
                      {item.review_status === "unreviewed" ? (
                        <>
                          <Button size="sm" variant="outline" disabled={pending === item.transaction_id} onClick={() => void decide(item, "confirmed")} title="Worth following up">
                            <Check className="mr-1 h-4 w-4" /> Confirm
                          </Button>
                          <Button size="sm" variant="ghost" disabled={pending === item.transaction_id} onClick={() => void decide(item, "dismissed")} title="This is expected">
                            <X className="mr-1 h-4 w-4" /> Dismiss
                          </Button>
                        </>
                      ) : (
                        <Button size="sm" variant="ghost" disabled={pending === item.transaction_id} onClick={() => void decide(item, "unreviewed")}>
                          <Undo2 className="mr-1 h-4 w-4" /> Undo
                        </Button>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted-foreground">
            <strong>Confirm</strong> = worth following up. <strong>Dismiss</strong> = expected. Each expense is compared with the typical amount for its category, so a wrongly categorized expense can look unusual: fix categories on the Categories page and this list updates.
          </p>
        </>
      )}
      <Disclaimer>Method: {result.method ?? "n/a"}. This is a ranking aid, not a fraud check.</Disclaimer>
    </div>
  );
}
