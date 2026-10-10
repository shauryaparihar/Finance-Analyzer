import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError, correctCategory, deleteBudget, friendlyMessage, getTransactions, login, saveBudget, setUnauthorizedHandler,
  tokenStore, uploadFile,
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

beforeEach(() => {
  vi.stubGlobal("sessionStorage", memoryStorage());
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  unauthorized = vi.fn();
  setUnauthorizedHandler(unauthorized);
});

afterEach(() => {
  setUnauthorizedHandler(null);
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

describe("failures", () => {
  it("clears the session and says it expired on a 401 TOKEN_EXPIRED", async () => {
    tokenStore.set("old");
    fetchMock.mockResolvedValue(reply(401, errorBody("TOKEN_EXPIRED", "Your session has expired. Please log in again.")));
    await expect(getTransactions("u1", { limit: 1, offset: 0 })).rejects.toMatchObject({ status: 401, code: "TOKEN_EXPIRED" });
    expect(tokenStore.get()).toBeNull();
    expect(unauthorized).toHaveBeenCalledWith("expired");
  });

  it("treats other 401s on protected calls as an invalid session", async () => {
    tokenStore.set("tampered");
    fetchMock.mockResolvedValue(reply(401, errorBody("TOKEN_INVALID", "Your session is not valid.")));
    await expect(getTransactions("u1", { limit: 1, offset: 0 })).rejects.toBeInstanceOf(ApiError);
    expect(unauthorized).toHaveBeenCalledWith("invalid");
  });

  it("does not log the user out when the login itself is rejected", async () => {
    tokenStore.set("still-valid");
    fetchMock.mockResolvedValue(reply(401, errorBody("INVALID_CREDENTIALS", "Incorrect email or password.")));
    await expect(login("a@b.co", "wrong")).rejects.toMatchObject({ code: "INVALID_CREDENTIALS" });
    expect(unauthorized).not.toHaveBeenCalled();
    expect(tokenStore.get()).toBe("still-valid");
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

describe("the token store", () => {
  it("survives storage being unavailable", () => {
    vi.stubGlobal("sessionStorage", {
      getItem: () => { throw new Error("blocked"); },
      setItem: () => { throw new Error("blocked"); },
      removeItem: () => { throw new Error("blocked"); },
    });
    expect(tokenStore.get()).toBeNull();
    expect(() => tokenStore.set("x")).not.toThrow();
    expect(() => tokenStore.clear()).not.toThrow();
  });
});
