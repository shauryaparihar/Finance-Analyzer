// Response shapes of the FinSight API. They mirror the backend schemas; the backend owns every rule.

export type UploadStatus = "queued" | "processing" | "completed" | "partial" | "failed";
export type ModuleName = "categorization" | "forecast" | "anomaly" | "summary";
export type RunStatus = "pending" | "running" | "completed" | "failed" | "skipped";
export type AmountConvention = "auto" | "expenses_positive" | "expenses_negative";

export type Role = "user" | "admin" | "demo";

export interface User {
  id: string;
  email: string;
  created_at: string;
  role: Role;
}

export interface AdminOverview {
  users_total: number;
  users_active: number;
  users_by_role: Record<string, number>;
  uploads_total: number;
  uploads_by_status: Record<string, number>;
  uploads_last_7_days: number;
  note: string;
}

export interface AdminUser {
  id: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  upload_count: number;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface ModuleStatus {
  module: ModuleName;
  status: RunStatus;
  duration_ms: number | null;
  model_version: string | null;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface UploadStatusResponse {
  upload_id: string;
  status: UploadStatus;
  error_summary: string | null;
  modules: ModuleStatus[];
}

export interface UploadItem {
  id: string;
  filename: string;
  row_count: number;
  status: UploadStatus;
  error_summary: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface UploadAccepted {
  upload_id: string;
  filename: string;
  status: UploadStatus;
  reused: boolean;
  rows_received: number;
  rows_dropped: number;
  amount_convention: string;
  message: string;
}

export interface Wrapped<T> {
  result_type: string;
  data: T;
}

// --- summary ---
export interface CategorySpend {
  category: string;
  amount: number;
  count: number;
}
export interface MonthlySpend {
  month: string;
  amount: number;
}
export interface RecentTransaction {
  id: number;
  date: string;
  description: string | null;
  amount: number;
  category: string;
}
export interface Summary {
  total_transactions: number;
  total_spending: number;
  total_income: number;
  avg_transaction: number;
  avg_monthly_spending?: number;
  review_queue_size: number;
  category_spending?: CategorySpend[];
  monthly_spending?: MonthlySpend[];
  recent_transactions?: RecentTransaction[];
}

// --- forecast ---
export interface ErrorScores {
  mae: number;
  rmse: number;
  window_total_error_pct: number;
}
export interface ForecastSkipped {
  status: "skipped";
  reason: string;
  history_days: number;
  min_history_days: number;
  disclaimer: string;
}
export interface ForecastCompleted {
  status: "completed";
  reason: null;
  first_date: string;
  last_date: string;
  history_days: number;
  min_history_days: number;
  method: "seasonal_naive" | "lag_random_forest";
  method_label: string;
  model_beat_baseline: boolean;
  backtest: {
    horizon_days: number;
    folds: number;
    forecast_days_scored: number;
    baseline: ErrorScores;
    model: ErrorScores;
    selected: ErrorScores;
    model_vs_baseline_mae_improvement_pct: number;
  };
  forecast: { days: number; total: number; daily: { date: string; predicted_spending: number }[] };
  recent_actual: { date: string; spending: number }[];
  interval: null; // no prediction interval is estimated
  disclaimer: string;
}
export type Forecast = ForecastCompleted | ForecastSkipped;

// --- unusual transactions ---
export type ReviewStatus = "unreviewed" | "confirmed" | "dismissed";
export interface UnusualItem {
  transaction_id: number;
  rank: number;
  date: string | null;
  description: string | null;
  amount: number;
  category: string;
  score: number | null;
  reason: string | null;
  review_status: ReviewStatus;
}
export interface Anomalies {
  status: "completed" | "skipped" | "not_available";
  reason: string | null;
  method: string | null;
  review_capacity: number | null;
  expenses_scanned: number | null;
  reviewed: number;
  confirmed: number;
  dismissed: number;
  decisions_outside_queue: number;
  items: UnusualItem[];
  disclaimer: string;
}

// --- budgets ---
export interface Budget {
  category: string;
  monthly_limit: number;
  created_at: string;
  updated_at: string;
}
export type RiskStatus = "on_track" | "near_limit" | "projected_over" | "over_budget";
export interface BudgetRiskRow {
  category: string;
  monthly_limit: number;
  spent_so_far: number;
  projected_month_end: number;
  variance_current: number;
  variance_projected: number;
  percent_of_limit_spent: number;
  status: RiskStatus;
}
export interface BudgetRisk {
  disclaimer: string;
  as_of: string | null;
  month: string | null;
  remaining_days: number | null;
  projection_method: string;
  assumptions?: string;
  categories: BudgetRiskRow[];
  totals: {
    monthly_limit: number;
    spent_so_far: number;
    projected_month_end: number;
    categories_at_risk: number;
  } | null;
}

// --- transactions ---
export interface TransactionRow {
  id: number;
  date: string | null;
  amount: number;
  category: string;
  description: string | null;
  source_category: string | null;
  predicted_category: string | null;
  prediction_confidence: number | null;
  confirmed_category: string | null;
  review_required: boolean;
  anomaly_score: number | null;
  anomaly_rank: number | null;
  anomaly_reason: string | null;
  anomaly_review_status: ReviewStatus;
}
export interface TransactionsPage {
  upload_id: string;
  count: number;
  limit: number;
  offset: number;
  transactions: TransactionRow[];
}
export interface CategoryList {
  categories: string[];
  model_version: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id?: string;
    details?: { problems?: { field: string; message: string }[] } & Record<string, unknown>;
  };
}
