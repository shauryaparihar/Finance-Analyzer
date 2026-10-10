import { FormEvent, useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
import { deleteBudget, getBudgetRisk, listBudgets, saveBudget } from "../api";
import { useResource } from "../hooks/useResource";
import { amount, shortDate } from "../lib/format";
import { RISK_LABELS } from "../lib/status";
import type { RiskStatus } from "../types";
import { Card, Disclaimer, ErrorNotice, Pill, SectionTitle, Tone } from "./common";
import { Button } from "./ui/button";

const RISK_TONE: Record<RiskStatus, Tone> = { on_track: "good", near_limit: "warn", projected_over: "bad", over_budget: "bad" };

/** Monthly budgets per category with how much is spent so far and where the month is projected to end. */
export function BudgetPanel({ uploadId, categoryChoices }: { uploadId: string; categoryChoices: string[] }) {
  const risk = useResource(() => getBudgetRisk(uploadId), [uploadId]);
  const budgets = useResource(listBudgets, []);
  const [category, setCategory] = useState("");
  const [limit, setLimit] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<unknown>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const refresh = () => {
    risk.reload();
    budgets.reload();
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = Number(limit);
    setFormError(null);
    setSaving(true);
    try {
      await saveBudget(category.trim(), value);
      setCategory("");
      setLimit("");
      refresh();
    } catch (e) {
      setFormError(e);
    } finally {
      setSaving(false);
    }
  }

  async function remove(name: string) {
    setFormError(null);
    try {
      await deleteBudget(name);
      setConfirming(null);
      refresh();
    } catch (e) {
      setFormError(e);
    }
  }

  const rows = risk.data?.categories ?? [];
  const known = new Set(rows.map((r) => r.category));
  const limitOnly = (budgets.data ?? []).filter((b) => !known.has(b.category));
  const input = "rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground outline-none focus:border-primary";

  return (
    <Card>
      <SectionTitle>Monthly budgets</SectionTitle>

      <form onSubmit={submit} className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label htmlFor="budget-category" className="mb-1 block text-xs text-muted-foreground">Category</label>
          <input id="budget-category" list="budget-categories" required maxLength={100} value={category} onChange={(e) => setCategory(e.target.value)} placeholder="e.g. Groceries" className={`${input} w-full`} />
          <datalist id="budget-categories">{categoryChoices.map((c) => <option key={c} value={c} />)}</datalist>
        </div>
        <div className="sm:w-44">
          <label htmlFor="budget-limit" className="mb-1 block text-xs text-muted-foreground">Monthly limit</label>
          <input id="budget-limit" type="number" required min="0.01" step="0.01" value={limit} onChange={(e) => setLimit(e.target.value)} className={`${input} w-full`} />
        </div>
        <Button type="submit" disabled={saving}>
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />} Save budget
        </Button>
      </form>
      {formError !== null && <div className="mb-4"><ErrorNotice error={formError} /></div>}
      {risk.error !== null && <div className="mb-4"><ErrorNotice error={risk.error} onRetry={refresh} /></div>}

      {rows.length === 0 && limitOnly.length === 0 && !risk.loading && (
        <p className="text-sm text-muted-foreground">No budgets yet. Add one above to see how this month is going.</p>
      )}

      {(rows.length > 0 || limitOnly.length > 0) && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-border text-left font-mono text-xs uppercase tracking-wider text-muted-foreground">
                <th className="py-2 pr-3">Category</th><th className="py-2 pr-3 text-right">Limit</th><th className="py-2 pr-3 text-right">Spent so far</th>
                <th className="py-2 pr-3 text-right">Projected month end</th><th className="py-2 pr-3">Status</th><th className="py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((r) => (
                <tr key={r.category}>
                  <td className="py-3 pr-3 text-foreground">{r.category}</td>
                  <td className="py-3 pr-3 text-right font-mono">{amount(r.monthly_limit)}</td>
                  <td className="py-3 pr-3 text-right font-mono">{amount(r.spent_so_far)} <span className="text-xs text-muted-foreground">({r.percent_of_limit_spent.toFixed(0)}%)</span></td>
                  <td className="py-3 pr-3 text-right font-mono">{amount(r.projected_month_end)}</td>
                  <td className="py-3 pr-3"><Pill tone={RISK_TONE[r.status]}>{RISK_LABELS[r.status]}</Pill></td>
                  <td className="whitespace-nowrap py-3 text-right">
                    {confirming === r.category ? (
                      <span className="text-xs">Remove? <button className="text-destructive underline" onClick={() => void remove(r.category)}>Yes</button> · <button className="underline" onClick={() => setConfirming(null)}>No</button></span>
                    ) : (
                      <Button variant="ghost" size="sm" aria-label={`Remove budget for ${r.category}`} onClick={() => setConfirming(r.category)}><Trash2 className="h-4 w-4 text-muted-foreground" /></Button>
                    )}
                  </td>
                </tr>
              ))}
              {limitOnly.map((b) => (
                <tr key={b.category}>
                  <td className="py-3 pr-3 text-foreground">{b.category}</td>
                  <td className="py-3 pr-3 text-right font-mono">{amount(b.monthly_limit)}</td>
                  <td className="py-3 pr-3 text-right text-muted-foreground" colSpan={3}>Shown once an analysis is open</td>
                  <td />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {risk.data && risk.data.as_of && (
        <div className="mt-4 space-y-1 text-xs text-muted-foreground">
          <p>Month {risk.data.month}, as of {shortDate(risk.data.as_of)} ({risk.data.remaining_days} days left in the month). {risk.data.assumptions}</p>
          {risk.data.totals && risk.data.totals.categories_at_risk > 0 && (
            <p className="text-[#FFA657]">{risk.data.totals.categories_at_risk} categor{risk.data.totals.categories_at_risk === 1 ? "y is" : "ies are"} already over, or projected to go over, the limit.</p>
          )}
        </div>
      )}
      <Disclaimer>{risk.data?.disclaimer ?? "Estimates from your past spending pattern only. Not financial advice."}</Disclaimer>
    </Card>
  );
}
