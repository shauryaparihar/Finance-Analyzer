import type {
  Anomalies, AmountConvention, ApiErrorBody, Budget, BudgetRisk, CategoryList, Forecast, Summary,
  TokenResponse, TransactionRow, TransactionsPage, UploadAccepted, UploadItem, UploadStatusResponse, User,
  Wrapped, ReviewStatus,
} from "./types";

/**
 * The only place that talks to the backend. It adds the login token, and turns every failure (no network, expired
 * session, validation error, server error) into one ApiError with a message that is safe to show to a person.
 */
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : "/api";
const TOKEN_KEY = "finsight.token";

// The token lives in sessionStorage: it is gone when the tab closes, and is short-lived (30 minutes). Trade-off:
// any script running on the page could read it (XSS). A stronger design is a refresh token in an HttpOnly cookie.
export const tokenStore = {
  get(): string | null {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string): void {
    try {
      sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* storage unavailable: the user simply has to log in again after a refresh */
    }
  },
  clear(): void {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nothing to clear */
    }
  },
};

export type UnauthorizedReason = "expired" | "invalid" | "missing";
let onUnauthorized: ((reason: UnauthorizedReason) => void) | null = null;
export function setUnauthorizedHandler(handler: ((reason: UnauthorizedReason) => void) | null): void {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;
  problems: { field: string; message: string }[];

  constructor(status: number, code: string, message: string, requestId?: string, problems: { field: string; message: string }[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.problems = problems;
  }
}

/** Text to show a person for any error, including ones that are not ApiErrors. */
export function friendlyMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const reference = error.status >= 500 && error.requestId ? ` (reference ${error.requestId})` : "";
    return error.message + reference;
  }
  return "Something unexpected went wrong. Please try again.";
}

function describeFailure(status: number, body: ApiErrorBody | null): ApiError {
  const err = body?.error;
  if (err) {
    const problems = err.details?.problems ?? [];
    let message = err.message;
    if (status === 422 && problems.length > 0) {
      message = problems.map((p) => (p.field ? `${p.field}: ${p.message}` : p.message)).join("; ");
    }
    return new ApiError(status, err.code, message, err.request_id, problems);
  }
  if (status === 403) return new ApiError(status, "FORBIDDEN", "You do not have access to this.");
  if (status >= 500) return new ApiError(status, "SERVER_ERROR", "The server had a problem. Please try again in a moment.");
  return new ApiError(status, "REQUEST_FAILED", "The request could not be completed.");
}

interface RequestOptions {
  method?: string;
  json?: unknown;
  body?: FormData;
  query?: Record<string, string | number | boolean | undefined>;
  auth?: boolean; // false for register/login: a 401 there means "wrong password", not "session expired"
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", json, body, query, auth = true } = options;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) params.set(key, String(value));
  }
  const url = `${API_BASE}${path}${params.toString() ? `?${params}` : ""}`;

  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (json !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(url, { method, headers, body: json !== undefined ? JSON.stringify(json) : body });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the server. Check your connection and try again.");
  }

  if (response.status === 204) return undefined as T;

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const failure = describeFailure(response.status, payload as ApiErrorBody | null);
    if (response.status === 401 && auth) {
      tokenStore.clear();
      onUnauthorized?.(failure.code === "TOKEN_EXPIRED" ? "expired" : token ? "invalid" : "missing");
    }
    throw failure;
  }
  return payload as T;
}

// --- auth ---
export const register = (email: string, password: string) =>
  request<User>("/auth/register", { method: "POST", json: { email, password }, auth: false });
export const login = (email: string, password: string) =>
  request<TokenResponse>("/auth/login", { method: "POST", json: { email, password }, auth: false });
export const getMe = () => request<User>("/auth/me");

// --- uploads ---
export function uploadFile(file: File, amountConvention: AmountConvention = "auto") {
  const form = new FormData();
  form.append("file", file);
  return request<UploadAccepted>("/uploads", { method: "POST", body: form, query: { amount_convention: amountConvention } });
}
export const listUploads = () => request<UploadItem[]>("/uploads", { query: { limit: 50 } });
export const getUploadStatus = (id: string) => request<UploadStatusResponse>(`/uploads/${id}/status`);
export const deleteUpload = (id: string) => request<void>(`/uploads/${id}`, { method: "DELETE" });

// --- results ---
export const getSummary = (id: string) => request<Wrapped<Summary>>(`/uploads/${id}/summary`);
export const getForecast = (id: string) => request<Wrapped<Forecast>>(`/uploads/${id}/forecast`);
export const getAnomalies = (id: string) => request<Anomalies>(`/uploads/${id}/anomalies`);
export const getBudgetRisk = (id: string) => request<BudgetRisk>(`/uploads/${id}/budget-risk`);
export const getTransactions = (id: string, options: { limit: number; offset: number; reviewRequired?: boolean }) =>
  request<TransactionsPage>(`/uploads/${id}/transactions`, {
    query: { limit: options.limit, offset: options.offset, review_required: options.reviewRequired },
  });
export const getCategories = () => request<CategoryList>("/categories");

// --- corrections and reviews ---
export const correctCategory = (transactionId: number, category: string) =>
  request<TransactionRow>(`/transactions/${transactionId}/category`, { method: "PATCH", json: { category } });
export const reviewUnusual = (transactionId: number, status: ReviewStatus) =>
  request<TransactionRow>(`/transactions/${transactionId}/anomaly-review`, { method: "PATCH", json: { status } });

// --- budgets ---
export const listBudgets = () => request<Budget[]>("/budgets");
export const saveBudget = (category: string, monthlyLimit: number) =>
  request<Budget>(`/budgets/${encodeURIComponent(category)}`, { method: "PUT", json: { monthly_limit: monthlyLimit } });
export const deleteBudget = (category: string) =>
  request<void>(`/budgets/${encodeURIComponent(category)}`, { method: "DELETE" });
