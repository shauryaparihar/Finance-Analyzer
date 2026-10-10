import { describe, expect, it } from "vitest";
import { serverFieldErrors, validateCredentials } from "./validation";

describe("checking the login form before sending it", () => {
  it("accepts a good registration", () => {
    expect(validateCredentials("register", "name@example.com", "long-enough-1")).toEqual({});
  });
  it("asks for an email, and for a sensible one", () => {
    expect(validateCredentials("login", "", "x").email).toBe("Enter your email address.");
    expect(validateCredentials("login", "   ", "x").email).toBe("Enter your email address.");
    for (const bad of ["plain", "a@b", "a b@c.de", "@c.de", "a@.de"]) {
      expect(validateCredentials("login", bad, "x").email).toBe("Enter a valid email address, like name@example.com.");
    }
    expect(validateCredentials("login", "  name@example.com  ", "x").email).toBeUndefined(); // surrounding spaces are fine
  });
  it("tells a new user how many characters they have against the 8 needed", () => {
    expect(validateCredentials("register", "a@b.co", "abc").password).toBe("Use at least 8 characters (you have 3).");
    expect(validateCredentials("register", "a@b.co", "1234567").password).toBe("Use at least 8 characters (you have 7).");
    expect(validateCredentials("register", "a@b.co", "12345678").password).toBeUndefined();
  });
  it("does not apply the length rule when logging in, because an existing password is whatever it is", () => {
    expect(validateCredentials("login", "a@b.co", "abc").password).toBeUndefined();
    expect(validateCredentials("login", "a@b.co", "").password).toBe("Enter your password.");
  });
  it("reports every problem at once", () => {
    expect(Object.keys(validateCredentials("register", "nope", "abc"))).toEqual(["email", "password"]);
  });
});

describe("confirming the password when registering", () => {
  it("catches a typo before the account is created", () => {
    expect(validateCredentials("register", "a@b.co", "correct-horse", "correct-horze").confirm).toBe("The two passwords do not match.");
    expect(validateCredentials("register", "a@b.co", "correct-horse", "").confirm).toBe("Type the password again to confirm it.");
  });
  it("accepts matching passwords, and never asks when logging in", () => {
    expect(validateCredentials("register", "a@b.co", "correct-horse", "correct-horse")).toEqual({});
    expect(validateCredentials("login", "a@b.co", "whatever", "different").confirm).toBeUndefined();
  });
  it("does not pile a mismatch message on top of a too-short password", () => {
    expect(validateCredentials("register", "a@b.co", "abc", "xyz").confirm).toBeUndefined();
  });
});

describe("showing the server's own field messages under the right field", () => {
  it("maps known fields and ignores others", () => {
    expect(serverFieldErrors([
      { field: "password", message: "String should have at least 8 characters" },
      { field: "email", message: "value is not a valid email address" },
      { field: "other", message: "ignored" },
    ])).toEqual({ password: "String should have at least 8 characters", email: "value is not a valid email address" });
    expect(serverFieldErrors([])).toEqual({});
  });
});
