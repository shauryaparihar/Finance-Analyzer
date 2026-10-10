import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError, RACE_RETRY_MS, correctCategory, deleteBudget, friendlyMessage, getMe, getTransactions, login, logout,
  refreshSession, saveBudget, setUnauthorizedHandler, tokenStore, uploadFile, verifySessionCookie,
} from "./api";

function memoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() { return store.size; },
    clear: () => store.clear(),
    getItem: (key) => store.get(key) ?? null,
    key: (index) => Array.from(store.keys())[index] ?? null,
    removeItem: (key) => void store.delete(key),
    setItem: (key, value) => void store.set(key, value),
  };
}

function reply(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const errorBody = (code: string, message: string, extra: Record<string, unknown> = {}) => ({
  error: { code, message, request_id: "req-abc123456", details: {}, ...extra },
});

let fetchMock: ReturnType<typeof vi.fn>;
let unauthorized: ReturnType<typeof vi.fn>;

let storage: Storage;

beforeEach(() => {
  storage = memoryStorage();
  vi.stubGlobal("sessionStorage", storage);
  vi.stubGlobal("localStorage", memoryStorage());
  tokenStore.clear();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  unauthorized = vi.fn();
  setUnauthorizedHandler(unauthorized);
});

afterEach(() => {
  setUnauthorizedHandler(null);
  tokenStore.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function lastCall() {
  const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
  return { url, init, headers: (init.headers ?? {}) as Record<string, string> };
}

describe("sending requests", () => {
  it("sends the login token as a Bearer header when there is one, and none otherwise", async () => {
    fetchMock.mockResolvedValue(reply(200, []));
    await getTransactions("u1", { limit: 10, offset: 0 });
    expect(lastCall().headers.Authorization).toBeUndefined();
    tokenStore.set("abc.def.ghi");
    await getTransactions("u1", { limit: 10, offset: 0 });
    expect(lastCall().headers.Authorization).toBe("Bearer abc.def.ghi");
  });

  it("builds the query string and leaves out options that were not set", async () => {
    fetchMock.mockResolvedValue(reply(200, {}));
    await getTransactions("u1", { limit: 50, offset: 100 });
    expect(lastCall().url).toBe("/api/uploads/u1/transactions?limit=50&offset=100");
    await getTransactions("u1", { limit: 50, offset: 0, reviewRequired: true });
    expect(lastCall().url).toContain("review_required=true");
  });

  it("uploads a file as multipart form data with the chosen sign convention", async () => {
    fetchMock.mockResolvedValue(reply(202, { upload_id: "u1" }));
    await uploadFile(new File(["a,b"], "data.csv"), "expenses_negative");
    const { url, init, headers } = lastCall();
    expect(url).toBe("/api/uploads?amount_convention=expenses_negative");
    expect(init.body).toBeInstanceOf(FormData);
    expect(headers["Content-Type"]).toBeUndefined(); // the browser sets the multipart boundary itself
  });

  it("sends JSON bodies and encodes path values safely", async () => {
    fetchMock.mockResolvedValue(reply(200, {}));
    await saveBudget("Personal Care/Other", 150.5);
    expect(lastCall().url).toBe("/api/budgets/Personal%20Care%2FOther");
    expect(JSON.parse(lastCall().init.body as string)).toEqual({ monthly_limit: 150.5 });
    await correctCategory(7, "Groceries");
    expect(lastCall().init.method).toBe("PATCH");
    expect(JSON.parse(lastCall().init.body as string)).toEqual({ category: "Groceries" });
  });

  it("returns nothing for a 204 response", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(deleteBudget("Dining")).resolves.toBeUndefined();
  });
});

const expiredBody = errorBody("TOKEN_EXPIRED", "Your session has expired. Please log in again.");
const tokenBody = (token: string) => ({ access_token: token, token_type: "bearer", expires_in: 900 });

describe("an expired access token", () => {
  it("is renewed from the refresh cookie and the request is repeated once, without the user noticing", async () => {
    tokenStore.set("old-token");
    fetchMock
      .mockResolvedValueOnce(reply(401, expiredBody)) // the original request
      .mockResolvedValueOnce(reply(200, tokenBody("new-token"))) // the refresh
      .mockResolvedValueOnce(reply(200, { id: "u1", email: "a@b.co", created_at: "x" })); // the retry
    await expect(getMe()).resolves.toMatchObject({ email: "a@b.co" });
    const calls = fetchMock.mock.calls as [string, RequestInit][];
    expect(calls.map(([url]) => url)).toEqual(["/api/auth/me", "/api/auth/refresh", "/api/auth/me"]);
    expect(calls[1][1].method).toBe("POST");
    expect((calls[1][1].headers as Record<string, string>)["X-FinSight-Request"]).toBe("1");
    expect((calls[2][1].headers as Record<string, string>).Authorization).toBe("Bearer new-token");
    expect(tokenStore.get()).toBe("new-token");
    expect(unauthorized).not.toHaveBeenCalled();
  });

  it("logs the user out, with the original error, when the refresh cookie is no longer valid", async () => {
    tokenStore.set("old-token");
    fetchMock
      .mockResolvedValueOnce(reply(401, expiredBody))
      .mockResolvedValueOnce(reply(401, errorBody("REFRESH_EXPIRED", "Your session expired. Please log in again.")));
    await expect(getMe()).rejects.toMatchObject({ status: 401, code: "TOKEN_EXPIRED" });
    expect(tokenStore.get()).toBeNull();
    expect(unauthorized).toHaveBeenCalledWith("expired");
    expect(fetchMock).toHaveBeenCalledTimes(2); // no retry after a failed refresh
  });

  it("makes only one refresh when several requests expire at the same moment", async () => {
    tokenStore.set("old-token");
    let refreshes = 0;
    fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
      if (url === "/api/auth/refresh") {
        refreshes += 1;
        await new Promise((resolve) => setTimeout(resolve, 10));
        return reply(200, tokenBody("new-token"));
      }
      const bearer = (init.headers as Record<string, string>).Authorization;
      return bearer === "Bearer new-token" ? reply(200, { id: "u1", email: "a@b.co", created_at: "x" }) : reply(401, expiredBody);
    });
    await Promise.all([getMe(), getMe(), getMe()]);
    expect(refreshes).toBe(1); // the single-use refresh token must not be spent three times
  });

  it("gives up after one retry instead of looping", async () => {
    tokenStore.set("old-token");
    fetchMock.mockImplementation(async (url: string) => (url === "/api/auth/refresh" ? reply(200, tokenBody("still-bad")) : reply(401, expiredBody)));
    await expect(getMe()).rejects.toMatchObject({ code: "TOKEN_EXPIRED" });
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/auth/refresh")).toHaveLength(1);
    expect(unauthorized).toHaveBeenCalledTimes(1);
  });

  it("keeps the session and reports a network problem when the refresh itself cannot reach the server", async () => {
    tokenStore.set("old-token");
    fetchMock.mockResolvedValueOnce(reply(401, expiredBody)).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(getMe()).rejects.toMatchObject({ code: "NETWORK_ERROR" });
    expect(unauthorized).not.toHaveBeenCalled();
  });

  it("also tries the refresh cookie when there is no access token yet (for example after a page reload)", async () => {
    fetchMock
      .mockResolvedValueOnce(reply(401, errorBody("NOT_AUTHENTICATED", "Please log in to continue.")))
      .mockResolvedValueOnce(reply(200, tokenBody("fresh")))
      .mockResolvedValueOnce(reply(200, { id: "u1", email: "a@b.co", created_at: "x" }));
    await expect(getMe()).resolves.toMatchObject({ email: "a@b.co" });
  });
});

describe("refreshing the session", () => {
  it("stores the new access token in memory and reports ok", async () => {
    fetchMock.mockResolvedValue(reply(200, tokenBody("fresh")));
    await expect(refreshSession()).resolves.toBe("ok");
    expect(tokenStore.get()).toBe("fresh");
  });

  it("reports denied, and forgets any token, when there is no valid session", async () => {
    tokenStore.set("stale");
    fetchMock.mockResolvedValue(reply(401, errorBody("REFRESH_INVALID", "Please log in again.")));
    await expect(refreshSession()).resolves.toBe("denied");
    expect(tokenStore.get()).toBeNull();
  });

  it("reports unreachable when the server cannot be contacted, without forgetting the token", async () => {
    tokenStore.set("still-here");
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(refreshSession()).resolves.toBe("unreachable");
    expect(tokenStore.get()).toBe("still-here");
  });

  it("waits a moment and retries once when another tab renewed the session at the same time", async () => {
    vi.useFakeTimers();
    fetchMock
      .mockResolvedValueOnce(reply(401, errorBody("REFRESH_RACE", "Another tab just renewed the session. Please retry.")))
      .mockResolvedValueOnce(reply(200, tokenBody("after-race")));
    const outcome = refreshSession();
    await vi.advanceTimersByTimeAsync(RACE_RETRY_MS + 10);
    await expect(outcome).resolves.toBe("ok");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(tokenStore.get()).toBe("after-race");
  });

  it("does not keep retrying a race forever", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValue(reply(401, errorBody("REFRESH_RACE", "retry")));
    const outcome = refreshSession();
    await vi.advanceTimersByTimeAsync(RACE_RETRY_MS * 3);
    await expect(outcome).resolves.toBe("denied");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("checking that the browser keeps the login cookie", () => {
  it("passes when the cookie comes back, and stores the renewed token", async () => {
    fetchMock.mockResolvedValue(reply(200, tokenBody("renewed")));
    await expect(verifySessionCookie()).resolves.toBe(true);
    expect(tokenStore.get()).toBe("renewed");
  });
  it("reports false, but does NOT end the current session, when the server never sees the cookie", async () => {
    tokenStore.set("just-logged-in");
    fetchMock.mockResolvedValue(reply(401, errorBody("REFRESH_INVALID", "Please log in again.")));
    await expect(verifySessionCookie()).resolves.toBe(false);
    expect(tokenStore.get()).toBe("just-logged-in");
    expect(unauthorized).not.toHaveBeenCalled();
  });
  it("does not raise a false alarm when the server simply cannot be reached", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(verifySessionCookie()).resolves.toBe(true);
  });
});

describe("logging out", () => {
  it("tells the server to end the session, with the custom header, and never tries to refresh", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(logout()).resolves.toBeUndefined();
    const { url, init, headers } = lastCall();
    expect(url).toBe("/api/auth/logout");
    expect(init.method).toBe("POST");
    expect(headers["X-FinSight-Request"]).toBe("1");
  });
  it("does not start a refresh if the logout call itself is unauthorized", async () => {
    fetchMock.mockResolvedValue(reply(401, errorBody("REFRESH_INVALID", "x")));
    await expect(logout()).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("keeping the token out of reach of page scripts", () => {
  it("never writes the access token to sessionStorage or localStorage", async () => {
    const sessionWrites = vi.spyOn(storage, "setItem");
    const localWrites = vi.spyOn(localStorage, "setItem");
    fetchMock.mockResolvedValue(reply(200, tokenBody("secret-token-value")));
    await refreshSession();
    fetchMock.mockResolvedValue(reply(200, tokenBody("another-secret")));
    await login("a@b.co", "pw");
    tokenStore.set("manual-token");
    expect(sessionWrites).not.toHaveBeenCalled();
    expect(localWrites).not.toHaveBeenCalled();
    expect(storage.length + localStorage.length).toBe(0);
  });
  it("loses the token on a fresh page load, which then needs the cookie to get a new one", () => {
    tokenStore.set("in-memory-only");
    tokenStore.clear(); // what a reload does to module state
    expect(tokenStore.get()).toBeNull();
  });
});

describe("other failures", () => {
  it("does not log the user out, or try to refresh, when the login itself is rejected", async () => {
    tokenStore.set("still-valid");
    fetchMock.mockResolvedValue(reply(401, errorBody("INVALID_CREDENTIALS", "Incorrect email or password.")));
    await expect(login("a@b.co", "wrong")).rejects.toMatchObject({ code: "INVALID_CREDENTIALS" });
    expect(unauthorized).not.toHaveBeenCalled();
    expect(tokenStore.get()).toBe("still-valid");
    expect(fetchMock).toHaveBeenCalledTimes(1); // no refresh attempt for a wrong password
  });

  it("explains a network failure in plain words", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const error = await getTransactions("u1", { limit: 1, offset: 0 }).catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 0, code: "NETWORK_ERROR" });
    expect(friendlyMessage(error)).toContain("Cannot reach the server");
  });

  it("turns validation errors into a readable message and keeps the per-field problems", async () => {
    fetchMock.mockResolvedValue(
      reply(422, errorBody("VALIDATION_ERROR", "The request is not valid.", {
        details: { problems: [{ field: "password", message: "String should have at least 8 characters" }, { field: "email", message: "not a valid email" }] },
      })),
    );
    const error = (await login("x", "y").catch((e: unknown) => e)) as ApiError;
    expect(error.message).toBe("password: String should have at least 8 characters; email: not a valid email");
    expect(error.problems).toHaveLength(2);
  });

  it("passes through the backend's own message for expected errors such as a running job", async () => {
    fetchMock.mockResolvedValue(reply(409, errorBody("ACTIVE_JOB_EXISTS", "You already have an analysis running. Please wait for it to finish.")));
    const error = (await uploadFile(new File(["x"], "d.csv")).catch((e: unknown) => e)) as ApiError;
    expect(error).toMatchObject({ status: 409, code: "ACTIVE_JOB_EXISTS" });
    expect(friendlyMessage(error)).toBe("You already have an analysis running. Please wait for it to finish.");
  });

  it("shows a support reference for server errors but never raw details", async () => {
    fetchMock.mockResolvedValue(reply(500, errorBody("INTERNAL_ERROR", "Something went wrong. Please try again later.")));
    const error = await getTransactions("u1", { limit: 1, offset: 0 }).catch((e: unknown) => e);
    expect(friendlyMessage(error)).toBe("Something went wrong. Please try again later. (reference req-abc123456)");
  });

  it("copes with a 403, and with an error response that is not JSON", async () => {
    fetchMock.mockResolvedValueOnce(new Response("nope", { status: 403 }));
    expect(await getTransactions("u1", { limit: 1, offset: 0 }).catch((e: unknown) => e)).toMatchObject({ status: 403, code: "FORBIDDEN" });
    fetchMock.mockResolvedValueOnce(new Response("<html>bad gateway</html>", { status: 502 }));
    const error = (await getTransactions("u1", { limit: 1, offset: 0 }).catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("SERVER_ERROR");
    expect(error.message).not.toContain("html");
  });

  it("gives a generic message for things that are not API errors", () => {
    expect(friendlyMessage(new Error("TypeError: x is undefined"))).toBe("Something unexpected went wrong. Please try again.");
  });
});
