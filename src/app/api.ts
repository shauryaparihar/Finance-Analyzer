import type {
  AdminOverview, AdminUser, Anomalies, AmountConvention, ApiErrorBody, Budget, BudgetRisk, CategoryList, Forecast, Summary,
  TokenResponse, TransactionRow, TransactionsPage, UploadAccepted, UploadItem, UploadStatusResponse, User,
  Wrapped, ReviewStatus,
} from "./types";

/**
 * The only place that talks to the backend. It adds the login token, and turns every failure (no network, expired
 * session, validation error, server error) into one ApiError with a message that is safe to show to a person.
 */
const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : "/api";
const CSRF_HEADER = "X-FinSight-Request";
export const RACE_RETRY_MS = 300;

// The short-lived access token is kept in memory only. It is never written to sessionStorage or localStorage, so a
// script injected into the page cannot copy it out of storage and reuse it later. The long-lived credential is the
// refresh token: an HttpOnly cookie that page scripts cannot read at all. After a page reload the access token is
// simply fetched again from that cookie (see refreshSession). The API must be reached on the same origin (the dev
// server proxy, or the Vercel rewrite in production) so the browser sends the cookie.
let accessToken: string | null = null;
export const tokenStore = {
  get: (): string | null => accessToken,
  set: (token: string): void => {
    accessToken = token;
  },
  clear: (): void => {
    accessToken = null;
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
  csrf?: boolean; // the cookie-authenticated endpoints need the custom header
}

const SESSION_ERRORS = new Set(["TOKEN_EXPIRED", "TOKEN_INVALID", "NOT_AUTHENTICATED"]);

export type RefreshOutcome = "ok" | "denied" | "unreachable";
let refreshing: Promise<RefreshOutcome> | null = null;

/**
 * Ask the server for a new access token using the refresh cookie. Several callers at once share one request, so
 * the single-use refresh token is not spent twice. "denied" means there is no valid session; "unreachable" means
 * the server could not be contacted (the session may still be fine).
 */
export function refreshSession(): Promise<RefreshOutcome> {
  if (!refreshing) refreshing = attemptRefresh(0).finally(() => { refreshing = null; });
  return refreshing;
}

async function attemptRefresh(attempt: number, clearOnDenied = true): Promise<RefreshOutcome> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/auth/refresh`, { method: "POST", headers: { [CSRF_HEADER]: "1" }, credentials: "same-origin" });
  } catch {
    return "unreachable";
  }
  if (response.ok) {
    const body = (await response.json()) as TokenResponse;
    tokenStore.set(body.access_token);
    return "ok";
  }
  if (response.status === 401 && attempt === 0) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null;
    if (body?.error.code === "REFRESH_RACE") {
      // another tab renewed the session a moment ago and its new cookie is already in the browser: just try again
      await new Promise((resolve) => setTimeout(resolve, RACE_RETRY_MS));
      return attemptRefresh(1, clearOnDenied);
    }
  }
  if (clearOnDenied) tokenStore.clear();
  return "denied";
}

/**
 * Right after logging in, check that the browser really keeps and returns the refresh cookie. If the site is set up
 * so that the cookie never comes back (for example the website and its API are on different addresses), the person
 * would be logged out on every reload; this lets the app say so instead of failing mysteriously.
 * Returns false only when the server answered but did not recognise the cookie. Never ends the current session.
 */
export async function verifySessionCookie(): Promise<boolean> {
  // A read-only question: refreshing here would rotate the token while the person might reload, losing the new cookie.
  try {
    const response = await fetch(`${API_BASE}/auth/session-check`, { method: "POST", headers: { [CSRF_HEADER]: "1" }, credentials: "same-origin" });
    return response.status !== 401;
  } catch {
    return true; // could not reach the server: not evidence that the cookie is missing
  }
}

async function request<T>(path: string, options: RequestOptions = {}, alreadyRetried = false): Promise<T> {
  const { method = "GET", json, body, query, auth = true, csrf = false } = options;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) params.set(key, String(value));
  }
  const url = `${API_BASE}${path}${params.toString() ? `?${params}` : ""}`;

  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (json !== undefined) headers["Content-Type"] = "application/json";
  if (csrf) headers[CSRF_HEADER] = "1";

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
      // The access token is short-lived. Before giving up, try once to renew it from the refresh cookie.
      if (!alreadyRetried && SESSION_ERRORS.has(failure.code)) {
        const outcome = await refreshSession();
        if (outcome === "ok") return request<T>(path, options, true);
        if (outcome === "unreachable") throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the server. Check your connection and try again.");
      }
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
export interface Providers { google: boolean; demo: boolean; email: boolean }
/** Which extra ways to sign in this site offers. */
export const getProviders = () => request<Providers>("/auth/providers", { auth: false });
export const forgotPassword = (email: string) =>
  request<{ message: string }>("/auth/forgot-password", { method: "POST", json: { email }, auth: false, csrf: true });
export const resetPassword = (token: string, password: string) =>
  request<void>("/auth/reset-password", { method: "POST", json: { token, password }, auth: false, csrf: true });
export const verifyEmail = (token: string) => request<void>("/auth/verify-email", { method: "POST", json: { token }, auth: false, csrf: true });
export const sendVerification = () => request<{ message: string }>("/auth/send-verification", { method: "POST" });
/** Where "Continue with Google" sends the browser (a full page visit, not a fetch). */
export const GOOGLE_LOGIN_URL = `${API_BASE}/auth/google/login`;
/** One-click read-only guest session (only when the deployment turns it on). */
export type TokenResponseShape = TokenResponse;
export const demoLogin = () => request<TokenResponse>("/auth/demo", { method: "POST", auth: false, csrf: true });
export const getMe = () => request<User>("/auth/me");

// --- admin (administrator accounts only; counts and account details, never anyone's transactions) ---
export const getAdminOverview = () => request<AdminOverview>("/admin/overview");
export const listAdminUsers = () => request<AdminUser[]>("/admin/users");
export const setUserActive = (id: string, isActive: boolean) =>
  request<AdminUser>(`/admin/users/${id}`, { method: "PATCH", json: { is_active: isActive } });
/** End the login session on the server (revokes the refresh cookie's session). */
export const logout = () => request<void>("/auth/logout", { method: "POST", auth: false, csrf: true });

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
