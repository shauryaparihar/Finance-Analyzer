import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { Forecast, ForecastCompleted, ModuleStatus } from "../types";
import { AuthForm } from "./AuthForm";
import { CookieNotice } from "./common";
import { KPICard } from "./KPICard";
import { ModuleProgress } from "./ModuleProgress";
import { ForgotPasswordPage, ResetPasswordPage, VerifyEmailPage } from "./pages/EmailPages";
import { ForecastView } from "./pages/ForecastPage";

const completed = (over: Partial<ForecastCompleted> = {}): ForecastCompleted => ({
  status: "completed", reason: null, first_date: "2025-04-07", last_date: "2026-04-02", history_days: 361, min_history_days: 90,
  method: "lag_random_forest", method_label: "Lag-feature random forest", model_beat_baseline: true,
  backtest: {
    horizon_days: 31, folds: 40, forecast_days_scored: 1240,
    baseline: { mae: 374.1, rmse: 587.9, window_total_error_pct: 36 }, model: { mae: 272.8, rmse: 434, window_total_error_pct: 16.1 },
    selected: { mae: 272.8, rmse: 434, window_total_error_pct: 16.1 }, model_vs_baseline_mae_improvement_pct: 27.1,
  },
  forecast: { days: 31, total: 12950.35, daily: [{ date: "2026-04-03", predicted_spending: 806.4 }] },
  recent_actual: [{ date: "2026-04-02", spending: 100 }], interval: null,
  disclaimer: "An estimate based only on your past spending pattern. It is not financial advice.",
  ...over,
});

const render = (f: Forecast) => renderToStaticMarkup(<MemoryRouter><ForecastView f={f} /></MemoryRouter>);

describe("forecast screen", () => {
  it("shows the method, both scores, the improvement and the history length when the model won", () => {
    const html = render(completed());
    for (const text of ["12,950.35", "ML model", "Lag-feature random forest", "27.1% better", "smaller average daily error", "361 days", "374.10", "272.80", "16.1%", "36.0%", "not financial advice"]) {
      expect(html).toContain(text);
    }
    expect(html).toContain("smaller daily mistakes than the simple baseline");
  });

  it("says plainly when the model did not beat the baseline and shows the degradation", () => {
    const html = render(completed({
      method: "seasonal_naive", method_label: "Seasonal naive baseline (same weekday last week)", model_beat_baseline: false,
      backtest: { ...completed().backtest, model_vs_baseline_mae_improvement_pct: -8.4, selected: completed().backtest.baseline },
    }));
    expect(html).toContain("Baseline");
    expect(html).toContain("8.4% worse");
    expect(html).toContain("larger average daily error");
    expect(html).toContain("did <strong>not</strong> beat the simple baseline");
  });

  it("explains a short history clearly and offers no forecast", () => {
    const html = render({ status: "skipped", reason: "A forecast needs at least 90 days of spending history, but this file covers 14 days.", history_days: 14, min_history_days: 90, disclaimer: "x" });
    expect(html).toContain("Not enough history for a forecast");
    expect(html).toContain("covers 14 days");
    expect(html).toContain("History in this file: 14 days");
    expect(html).not.toContain("Next 31 days");
  });

  it("never claims an uncertainty band that does not exist", () => {
    const html = render(completed()).toLowerCase();
    expect(html).not.toContain("confidence interval");
    expect(html).toContain("no uncertainty range is shown");
    expect(html).toContain("drifts towards your typical daily spending");
  });

  it("notes when the test used a shorter horizon than the forecast", () => {
    const html = render(completed({ backtest: { ...completed().backtest, horizon_days: 14 } }));
    expect(html).toContain("too short to test the full 31 days");
  });
});

describe("per-step progress", () => {
  const step = (module: ModuleStatus["module"], status: ModuleStatus["status"], message: string | null = null): ModuleStatus => ({
    module, status, duration_ms: status === "completed" ? 1250 : null, model_version: null, error_code: null, error_message: message, started_at: null, finished_at: null,
  });
  it("shows every state: waiting, running, done, failed and skipped, with reasons", () => {
    const html = renderToStaticMarkup(
      <ModuleProgress modules={[
        step("categorization", "completed"), step("forecast", "skipped", "Need 90 days."),
        step("anomaly", "failed", "Unusual-transaction ranking failed."), step("summary", "running"),
      ]} />,
    );
    for (const text of ["Categorize transactions", "Done", "1.3 s", "Skipped", "Need 90 days.", "Failed", "Unusual-transaction ranking failed.", "Running"]) {
      expect(html).toContain(text);
    }
    expect(renderToStaticMarkup(<ModuleProgress modules={[step("summary", "pending")]} />)).toContain("Waiting");
  });
});

describe("KPI card", () => {
  it("shows the label, value and hint", () => {
    const html = renderToStaticMarkup(<KPICard label="Total spending" value="1,000.00" hint="12 transactions" />);
    expect(html).toContain("Total spending");
    expect(html).toContain("1,000.00");
    expect(html).toContain("12 transactions");
  });
});

describe("login form", () => {
  const noop = () => undefined;
  const form = (over: Partial<Parameters<typeof AuthForm>[0]> = {}) =>
    renderToStaticMarkup(
      <AuthForm mode="register" email="" password="" errors={{}} busy={false} onEmail={noop} onPassword={noop} onBlurField={noop} onSubmit={noop} {...over} />,
    );

  it("asks a new user to confirm the password, but not someone logging in", () => {
    expect(form()).toContain("Confirm password");
    expect(form({ errors: { confirm: "The two passwords do not match." } })).toContain("The two passwords do not match.");
    expect(form({ mode: "login" })).not.toContain("Confirm password");
  });

  it("offers a show-password button that starts hidden", () => {
    const html = form();
    expect(html).toContain('aria-label="Show password"');
    expect(html).toContain('type="password"');
  });

  it("turns off the browser's own pop-up messages so the app's styled ones are used", () => {
    expect(form()).toContain("novalidate");
  });
  it("shows the password hint on the page, always, so no message can cover it", () => {
    expect(form()).toContain("At least 8 characters.");
    expect(form({ errors: { password: "Use at least 8 characters (you have 3)." } })).toContain("At least 8 characters.");
  });
  it("shows an error under the field, in the destructive colour, linked to the field for screen readers", () => {
    const html = form({ errors: { password: "Use at least 8 characters (you have 3)." } });
    expect(html).toContain('role="alert"');
    expect(html).toContain("Use at least 8 characters (you have 3).");
    expect(html).toContain("text-destructive");
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain('aria-describedby="password-error password-hint"');
  });
  it("marks only the field that has a problem", () => {
    const html = form({ errors: { email: "Enter your email address." } });
    expect(html.match(/aria-invalid="true"/g)).toHaveLength(1);
    expect(html).toContain("Enter your email address.");
  });
  it("has no error markup when everything is fine, and the login version has no length hint", () => {
    expect(form()).not.toContain('role="alert"');
    expect(form({ mode: "login" })).not.toContain("At least 8 characters.");
  });
});

describe("cookie warning", () => {
  it("tells the person plainly what will happen and what to do", () => {
    const html = renderToStaticMarkup(<CookieNotice />);
    expect(html).toContain("did not keep the login cookie");
    expect(html).toContain("logged out when you reload");
    expect(html).toContain("same web address");
  });
});

describe("email pages", () => {
  const page = (element: JSX.Element, url = "/") => renderToStaticMarkup(<MemoryRouter initialEntries={[url]}>{element}</MemoryRouter>);
  it("asks for an email address and never says whether an account exists", () => {
    const html = page(<ForgotPasswordPage />);
    expect(html).toContain("Send reset link");
    expect(html.toLowerCase()).not.toContain("no account");
  });
  it("asks for the new password twice and explains an incomplete link", () => {
    expect(page(<ResetPasswordPage />, "/reset-password?token=abcdefghijklmnop")).toContain("Confirm new password");
    expect(page(<ResetPasswordPage />, "/reset-password")).toContain("incomplete");
  });
  it("shows a clear result page for the confirmation link", () => {
    expect(page(<VerifyEmailPage />, "/verify-email")).toContain("not valid any more");
  });
});
