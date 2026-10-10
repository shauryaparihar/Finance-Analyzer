import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ApiError, getForecast } from "../../api";
import { useAppContext } from "../../context/AppContext";
import { useResource } from "../../hooks/useResource";
import { amount, percent, shortDate } from "../../lib/format";
import { whyNoResult } from "../../lib/status";
import type { ErrorScores, Forecast, ForecastCompleted, ModuleStatus } from "../../types";
import { Card, Disclaimer, ErrorNotice, Notice, PageHeader, Pill, SectionTitle, Spinner } from "../common";
import { KPICard } from "../KPICard";
import { UploadGate } from "../UploadGate";

export function ForecastPage() {
  return <UploadGate>{(status) => <ForecastContent modules={status.modules} />}</UploadGate>;
}

function ForecastContent({ modules }: { modules: ModuleStatus[] }) {
  const { uploadId } = useAppContext();
  const id = uploadId as string;
  const forecast = useResource(() => getForecast(id), [id]);

  if (forecast.loading && !forecast.data) return <Spinner label="Loading forecast..." />;
  if (forecast.error !== null) {
    const missing = forecast.error instanceof ApiError && forecast.error.status === 404;
    return (
      <div className="p-4 sm:p-8">
        <PageHeader title="Spending forecast" />
        {missing ? <Notice tone="warn">{whyNoResult(modules, "forecast")}</Notice> : <ErrorNotice error={forecast.error} onRetry={forecast.reload} />}
      </div>
    );
  }

  return <ForecastView f={forecast.data!.data} />;
}

/** The forecast screen for a loaded result (exported so it can be rendered in tests). */
export function ForecastView({ f }: { f: Forecast }) {
  if (f.status === "skipped") {
    return (
      <div className="mx-auto max-w-2xl p-4 sm:p-8">
        <PageHeader title="Spending forecast" />
        <Card>
          <h3 className="mb-2 font-sans text-lg text-foreground">Not enough history for a forecast</h3>
          <p className="text-sm text-muted-foreground">{f.reason}</p>
          <p className="mt-4 font-mono text-xs text-muted-foreground">History in this file: {f.history_days} days · needed: {f.min_history_days} days</p>
        </Card>
        <Disclaimer>{f.disclaimer}</Disclaimer>
      </div>
    );
  }
  return <CompletedForecast f={f} />;
}

function ScoreRow({ label, scores, highlight }: { label: string; scores: ErrorScores; highlight: boolean }) {
  return (
    <tr className={highlight ? "bg-primary/5" : ""}>
      <td className="py-3 pr-3 text-foreground">{label} {highlight && <Pill tone="good" className="ml-2">used</Pill>}</td>
      <td className="py-3 pr-3 text-right font-mono">{amount(scores.mae)}</td>
      <td className="py-3 pr-3 text-right font-mono">{amount(scores.rmse)}</td>
      <td className="py-3 text-right font-mono">{percent(scores.window_total_error_pct)}</td>
    </tr>
  );
}

function CompletedForecast({ f }: { f: ForecastCompleted }) {
  const b = f.backtest;
  const modelUsed = f.method === "lag_random_forest";
  const improvement = b.model_vs_baseline_mae_improvement_pct;
  const chart = [
    ...f.recent_actual.map((p) => ({ date: p.date, actual: p.spending, forecast: undefined as number | undefined })),
    ...f.forecast.daily.map((p) => ({ date: p.date, actual: undefined as number | undefined, forecast: p.predicted_spending })),
  ];

  return (
    <div className="space-y-6 p-4 sm:space-y-8 sm:p-8">
      <PageHeader title="Spending forecast" subtitle={`Estimated spending for the ${f.forecast.days} days after ${shortDate(f.last_date)}.`} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KPICard label={`Next ${f.forecast.days} days`} value={amount(f.forecast.total)} hint="estimated total spending" />
        <KPICard label="Method used" value={modelUsed ? "ML model" : "Baseline"} hint={f.method_label} />
        <KPICard
          label="Model vs baseline" value={`${Math.abs(improvement).toFixed(1)}% ${improvement >= 0 ? "better" : "worse"}`}
          hint={improvement >= 0 ? "smaller average daily error" : "larger average daily error"}
          variant={modelUsed ? "default" : "warning"}
        />
        <KPICard label="History used" value={`${f.history_days} days`} hint={`minimum needed: ${f.min_history_days} days`} />
      </div>

      <Notice tone={modelUsed ? "good" : "warn"}>
        {modelUsed
          ? <>The machine-learning model made smaller daily mistakes than the simple baseline (same weekday last week) in testing, so its forecast is used.</>
          : <>The machine-learning model did <strong>not</strong> beat the simple baseline in testing, so the baseline forecast is shown instead.</>}
      </Notice>

      <Card>
        <SectionTitle>Recent spending and forecast</SectionTitle>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chart}>
              <CartesianGrid strokeDasharray="3 3" stroke="#30363D" />
              <XAxis dataKey="date" stroke="#ADBAC7" tick={{ fontSize: 11 }} minTickGap={32} />
              <YAxis stroke="#ADBAC7" tick={{ fontSize: 11 }} />
              <Tooltip formatter={(value) => amount(Number(value))} contentStyle={{ background: "#161B22", border: "1px solid #30363D" }} />
              <Legend />
              <Line type="monotone" dataKey="actual" name="Actual" stroke="#58A6FF" dot={false} strokeWidth={2} connectNulls={false} />
              <Line type="monotone" dataKey="forecast" name="Forecast" stroke="#00D4C8" dot={false} strokeWidth={2} strokeDasharray="5 4" connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          No uncertainty range is shown because none is estimated. Treat single days as rough: further into the future, the forecast drifts towards your typical daily spending.
        </p>
      </Card>

      <Card>
        <SectionTitle>How the methods compared in testing</SectionTitle>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-sm">
            <thead>
              <tr className="border-b border-border text-left font-mono text-xs uppercase tracking-wider text-muted-foreground">
                <th className="py-2 pr-3">Method</th><th className="py-2 pr-3 text-right">Avg daily error</th><th className="py-2 pr-3 text-right">Typical daily miss (RMSE)</th><th className="py-2 text-right">Error on a {b.horizon_days}-day total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              <ScoreRow label="Baseline: same weekday last week" scores={b.baseline} highlight={!modelUsed} />
              <ScoreRow label="Machine-learning model" scores={b.model} highlight={modelUsed} />
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Tested by pretending to forecast {b.folds} earlier times ({b.forecast_days_scored} forecast days in all), always using only the past to predict the next {b.horizon_days} days. Errors are in the same units as your amounts.
          {b.horizon_days < f.forecast.days && ` This history is too short to test the full ${f.forecast.days} days, so the test used ${b.horizon_days}.`}
        </p>
      </Card>
      <Disclaimer>{f.disclaimer}</Disclaimer>
    </div>
  );
}
