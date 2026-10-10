import { useMemo, useState } from "react";
import { Link } from "react-router";
import { ArrowUpDown } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ApiError, getCategories, getSummary } from "../../api";
import { useAppContext } from "../../context/AppContext";
import { useResource } from "../../hooks/useResource";
import { amount, shortDate } from "../../lib/format";
import { categoryOptions } from "../../lib/review";
import { whyNoResult } from "../../lib/status";
import type { ModuleStatus, RecentTransaction } from "../../types";
import { BudgetPanel } from "../BudgetPanel";
import { Card, ErrorNotice, Notice, PageHeader, SectionTitle, Spinner } from "../common";
import { KPICard } from "../KPICard";
import { UploadGate } from "../UploadGate";

const COLORS = ["#00D4C8", "#58A6FF", "#A371F7", "#FFA657", "#F85149"];

type SortKey = "date" | "description" | "amount" | "category";
type Sort = { key: SortKey; direction: "asc" | "desc" } | null;

export function OverviewPage() {
  return <UploadGate>{(status) => <OverviewContent modules={status.modules} />}</UploadGate>;
}

function OverviewContent({ modules }: { modules: ModuleStatus[] }) {
  const { uploadId } = useAppContext();
  const id = uploadId as string;
  const summary = useResource(() => getSummary(id), [id]);
  const modelCategories = useResource(() => getCategories().then((c) => c.categories).catch(() => [] as string[]), []);
  const [sort, setSort] = useState<Sort>(null);

  const recent = summary.data?.data.recent_transactions;
  const rows = useMemo<RecentTransaction[]>(() => {
    const list = [...(recent ?? [])];
    if (!sort) return list;
    return list.sort((a, b) => {
      const x = a[sort.key] ?? "";
      const y = b[sort.key] ?? "";
      if (x < y) return sort.direction === "asc" ? -1 : 1;
      if (x > y) return sort.direction === "asc" ? 1 : -1;
      return 0;
    });
  }, [recent, sort]);

  if (summary.loading && !summary.data) return <Spinner label="Loading summary..." />;
  if (summary.error !== null) {
    const missing = summary.error instanceof ApiError && summary.error.status === 404;
    return (
      <div className="p-4 sm:p-8">
        {missing ? <Notice tone="warn">{whyNoResult(modules, "summary")}</Notice> : <ErrorNotice error={summary.error} onRetry={summary.reload} />}
      </div>
    );
  }
  const s = summary.data!.data;
  const categories = s.category_spending ?? [];
  const monthly = s.monthly_spending ?? [];
  const chartCategories = categories.slice(0, 10);
  const categoryNames = categoryOptions(modelCategories.data ?? [], categories.map((c) => c.category));

  const toggleSort = (key: SortKey) =>
    setSort((current) => {
      if (!current || current.key !== key) return { key, direction: "asc" };
      return current.direction === "asc" ? { key, direction: "desc" } : null;
    });

  return (
    <div className="space-y-6 p-4 sm:space-y-8 sm:p-8">
      <PageHeader title="Overview & budgets" subtitle="Spending so far, where it goes, and how this month is tracking against your budgets." />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KPICard label="Total spending" value={amount(s.total_spending)} hint={`${s.total_transactions} transactions`} />
        <KPICard label="Money in" value={amount(s.total_income)} hint="income and refunds" />
        <KPICard label="Avg monthly spending" value={amount(s.avg_monthly_spending ?? 0)} />
        <KPICard
          label="Unusual to review" value={String(s.review_queue_size)}
          hint={s.review_queue_size > 0 ? "see Unusual Transactions" : "nothing stood out"}
          variant={s.review_queue_size > 0 ? "warning" : "default"}
        />
      </div>

      <BudgetPanel uploadId={id} categoryChoices={categoryNames} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <SectionTitle>Spending by category</SectionTitle>
          {chartCategories.length === 0 ? <p className="text-sm text-muted-foreground">No spending to show.</p> : (
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartCategories} layout="vertical" margin={{ left: 10, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363D" horizontal={false} />
                  <XAxis type="number" stroke="#ADBAC7" tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="category" stroke="#ADBAC7" tick={{ fontSize: 11 }} width={110} />
                  <Tooltip formatter={(value) => amount(Number(value))} contentStyle={{ background: "#161B22", border: "1px solid #30363D" }} />
                  <Bar dataKey="amount" radius={[0, 4, 4, 0]}>
                    {chartCategories.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card>
          <SectionTitle>Spending by month</SectionTitle>
          {monthly.length === 0 ? <p className="text-sm text-muted-foreground">No monthly data.</p> : (
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={monthly}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#30363D" />
                  <XAxis dataKey="month" stroke="#ADBAC7" tick={{ fontSize: 11 }} />
                  <YAxis stroke="#ADBAC7" tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(value) => amount(Number(value))} contentStyle={{ background: "#161B22", border: "1px solid #30363D" }} />
                  <Bar dataKey="amount" fill="#00D4C8" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      <Card>
        <SectionTitle action={<Link to="/categories" className="text-xs text-primary underline-offset-4 hover:underline">Review categories</Link>}>Latest transactions</SectionTitle>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-border text-left font-mono text-xs uppercase tracking-wider text-muted-foreground">
                {([["date", "Date"], ["description", "Description"], ["category", "Category"], ["amount", "Amount"]] as [SortKey, string][]).map(([key, label]) => (
                  <th key={key} className={`py-2 pr-3 ${key === "amount" ? "text-right" : ""}`}>
                    <button onClick={() => toggleSort(key)} className="inline-flex items-center gap-1 hover:text-foreground">{label}<ArrowUpDown className="h-3 w-3" /></button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((t) => (
                <tr key={t.id}>
                  <td className="whitespace-nowrap py-3 pr-3 text-muted-foreground">{shortDate(t.date)}</td>
                  <td className="max-w-[16rem] truncate py-3 pr-3 text-foreground" title={t.description ?? ""}>{t.description ?? "(no description)"}</td>
                  <td className="py-3 pr-3 text-muted-foreground">{t.category}</td>
                  <td className="py-3 text-right font-mono">{amount(t.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
