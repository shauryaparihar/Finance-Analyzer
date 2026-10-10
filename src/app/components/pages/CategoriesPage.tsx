import { useState } from "react";
import { Loader2 } from "lucide-react";
import { correctCategory, friendlyMessage, getCategories, getTransactions } from "../../api";
import { useAppContext } from "../../context/AppContext";
import { useResource } from "../../hooks/useResource";
import { amount, shortDate } from "../../lib/format";
import { categoryOptions, checkReason, confidenceLabel, usesModelGuess } from "../../lib/review";
import type { TransactionRow } from "../../types";
import { Card, ErrorNotice, Notice, PageHeader, Pill, Spinner } from "../common";
import { Button } from "../ui/button";
import { UploadGate } from "../UploadGate";

const PAGE_SIZE = 50;
const CUSTOM = "__custom__";

export function CategoriesPage() {
  return <UploadGate>{() => <CategoriesContent />}</UploadGate>;
}

function CategoriesContent() {
  const { uploadId } = useAppContext();
  const id = uploadId as string;
  const [filter, setFilter] = useState<"review" | "all">("review");
  const [offset, setOffset] = useState(0);
  const [saved, setSaved] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [pendingId, setPendingId] = useState<number | null>(null);

  const page = useResource(
    () => getTransactions(id, { limit: PAGE_SIZE, offset, reviewRequired: filter === "review" ? true : undefined }),
    [id, filter, offset],
  );
  const modelCategories = useResource(() => getCategories().then((c) => c.categories).catch(() => [] as string[]), []);

  const rows = page.data?.transactions ?? [];
  const options = categoryOptions(modelCategories.data ?? [], rows.map((r) => r.category));

  async function change(row: TransactionRow, category: string) {
    setPendingId(row.id);
    setActionError(null);
    setSaved(null);
    try {
      const updated = await correctCategory(row.id, category);
      page.setData((current) => ({ ...current, transactions: current.transactions.map((t) => (t.id === updated.id ? updated : t)) }));
      setSaved(`Saved "${category}". Totals, budgets and the unusual-transaction list are recalculated from your correction.`);
    } catch (e) {
      setActionError(e);
    } finally {
      setPendingId(null);
    }
  }

  const switchFilter = (next: "review" | "all") => {
    setFilter(next);
    setOffset(0);
    setSaved(null);
  };

  return (
    <div className="space-y-6 p-4 sm:p-8">
      <PageHeader title="Category review" subtitle="Check the categories and fix any that are wrong. Your choice always wins over the model's guess." />

      <Notice tone="info">
        <strong>Model confidence</strong> shows how sure the model is about its guess. It is a hint for where to look, not a probability that the guess is right.
        Rows are marked <strong>Check this</strong> when they have no category or the model is unsure (below 70%).
      </Notice>

      <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="Which transactions to show">
        {([["review", "Needs review"], ["all", "All transactions"]] as const).map(([key, label]) => (
          <button
            key={key} role="tab" aria-selected={filter === key} onClick={() => switchFilter(key)}
            className={`rounded-md px-3 py-1.5 text-sm ${filter === key ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/40"}`}
          >
            {label}
          </button>
        ))}
        <Button variant="ghost" size="sm" onClick={page.reload} className="ml-auto">Refresh list</Button>
      </div>

      {saved && <Notice tone="good">{saved}</Notice>}
      {actionError !== null && <ErrorNotice error={actionError} />}
      {page.error !== null && <ErrorNotice error={page.error} onRetry={page.reload} />}
      {page.loading && !page.data && <Spinner label="Loading transactions..." />}

      {page.data && rows.length === 0 && (
        <Card><p className="text-sm text-muted-foreground">{filter === "review" ? "Nothing needs review. Every transaction has a category." : "No transactions on this page."}</p></Card>
      )}

      {rows.length > 0 && (
        <Card className="p-0 sm:p-0">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-border text-left font-mono text-xs uppercase tracking-wider text-muted-foreground">
                  <th className="px-4 py-3">Date</th><th className="px-4 py-3">Description</th><th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3">Category</th><th className="px-4 py-3">Model confidence</th><th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((row) => {
                  const reason = checkReason(row);
                  return (
                    <tr key={row.id} className={pendingId === row.id ? "opacity-60" : ""}>
                      <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">{shortDate(row.date)}</td>
                      <td className="max-w-[14rem] truncate px-4 py-3 text-foreground" title={row.description ?? ""}>{row.description ?? "(no description)"}</td>
                      <td className="px-4 py-3 text-right font-mono">{amount(row.amount)}</td>
                      <td className="px-4 py-3"><CategoryCell row={row} options={options} busy={pendingId === row.id} onChange={(c) => void change(row, c)} /></td>
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-muted-foreground">{usesModelGuess(row) ? confidenceLabel(row.prediction_confidence) : "-"}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        {reason ? <Pill tone="warn">Check this: {reason}</Pill>
                          : row.confirmed_category ? <Pill tone="good">Your choice</Pill>
                          : usesModelGuess(row) ? <Pill tone="neutral">Model guess</Pill>
                          : <Pill tone="neutral">From your file</Pill>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {page.data && (offset > 0 || rows.length === PAGE_SIZE) && (
        <div className="flex items-center justify-between text-sm">
          <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</Button>
          <span className="text-muted-foreground">Rows {offset + 1} to {offset + rows.length}</span>
          <Button variant="outline" size="sm" disabled={rows.length < PAGE_SIZE} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</Button>
        </div>
      )}
    </div>
  );
}

/** One click to fix a category: pick from the list and it is saved straight away. */
function CategoryCell({ row, options, busy, onChange }: { row: TransactionRow; options: string[]; busy: boolean; onChange: (category: string) => void }) {
  const [custom, setCustom] = useState(false);
  const [text, setText] = useState("");
  const field = "rounded-md border border-border bg-input px-2 py-1.5 text-sm text-foreground outline-none focus:border-primary";

  if (custom) {
    return (
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { onChange(text.trim()); setCustom(false); setText(""); } }}>
        <input autoFocus aria-label="Your own category" maxLength={100} value={text} onChange={(e) => setText(e.target.value)} placeholder="Category name" className={`${field} w-36`} />
        <Button type="submit" size="sm" disabled={!text.trim() || busy}>Save</Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setCustom(false)}>Cancel</Button>
      </form>
    );
  }

  const needsChoice = row.category === "Uncategorized";
  const list = options.includes(row.category) || needsChoice ? options : [row.category, ...options];
  return (
    <span className="inline-flex items-center gap-2">
      <select
        aria-label={`Category for ${row.description ?? "transaction"}`} disabled={busy} value={needsChoice ? "" : row.category} className={field}
        onChange={(e) => { if (e.target.value === CUSTOM) setCustom(true); else if (e.target.value) onChange(e.target.value); }}
      >
        {needsChoice && <option value="">Choose a category...</option>}
        {list.map((c) => <option key={c} value={c}>{c}</option>)}
        <option value={CUSTOM}>Other (type your own)...</option>
      </select>
      {busy && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
    </span>
  );
}
