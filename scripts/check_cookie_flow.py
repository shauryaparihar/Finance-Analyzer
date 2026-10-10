"""
Check that the login cookie works end to end at a given web address.

    python scripts/check_cookie_flow.py https://your-site.example.com
    python scripts/check_cookie_flow.py http://localhost:5173 --allow-insecure     # local development only

Run it against the address people actually open (the FRONTEND address: for the deployed app, the Vercel URL, not the
Render URL), so it tests the rewrite/proxy in front of the API too. It creates a throwaway account
(cookie-check-...@example.com), logs in, and verifies:

  1. the API answers through this address
  2. the refresh cookie is sent back to the browser (the proxy did not drop Set-Cookie) with the right flags
  3. the cookie rotates and gives a working access token
  4. a request claiming to come from an unknown website is refused
  5. (--check-replay) replaying an old cookie revokes the session
  6. logging out revokes the session and clears the cookie

Exit code 0 means every check passed. Needs only the `httpx` package.
"""
import argparse
import secrets
import sys
import time

import httpx

COOKIE = "finsight_refresh"
CSRF = {"X-FinSight-Request": "1"}
failures: list[str] = []


def check(name: str, ok: bool, hint: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        failures.append(name)
        if hint:
            print(f"        -> {hint}")
    return ok


def cookie_headers(response: httpx.Response) -> list[str]:
    return [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie" and v.startswith(f"{COOKIE}=")]


def code(response: httpx.Response) -> str:
    try:
        return response.json()["error"]["code"]
    except Exception:
        return f"HTTP {response.status_code}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base_url")
    parser.add_argument("--allow-insecure", action="store_true", help="accept a non-Secure cookie (local http only)")
    parser.add_argument("--check-replay", action="store_true", help="also test replay detection (waits about 11 seconds)")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    origin = base
    email = f"cookie-check-{int(time.time())}-{secrets.token_hex(3)}@example.com"
    password = secrets.token_urlsafe(18)

    print(f"Checking the login cookie flow at {base}\n")
    with httpx.Client(base_url=base, timeout=30, follow_redirects=False) as client:
        # 1. the API is reachable through this address
        try:
            probe = client.get("/api/auth/me")
        except httpx.HTTPError as exc:
            check("the API answers through this address", False, f"could not connect: {exc}")
            return 1
        shaped = probe.status_code == 401 and code(probe) == "NOT_AUTHENTICATED"
        if not check("the API answers through this address", shaped, f"expected a 401 JSON error from /api/auth/me, got {probe.status_code}. Is /api proxied to the backend?"):
            return 1

        # 2. login: the cookie must reach the browser
        client.post("/api/auth/register", json={"email": email, "password": password})
        login = client.post("/api/auth/login", json={"email": email, "password": password})
        if not check("login succeeds", login.status_code == 200, f"got {login.status_code} {code(login)}"):
            return 1
        check("the login response body does not contain the refresh secret", "refresh" not in login.text.lower())
        headers = cookie_headers(login)
        if not check(
            "the refresh cookie (Set-Cookie) reaches the browser through this address", bool(headers),
            "the proxy/rewrite in front of the API is dropping Set-Cookie, so people would be logged out on every reload. "
            "Serve the website and API from one address with a proxy that forwards response cookies.",
        ):
            return 1
        header = headers[0].lower()
        check("cookie is HttpOnly", "httponly" in header, "page scripts could read the cookie")
        check("cookie is SameSite=Strict", "samesite=strict" in header)
        check("cookie is limited to /api/auth", "path=/api/auth" in header)
        check("cookie has no Domain attribute (host-only)", "domain=" not in header)
        secure = "; secure" in header
        if secure:
            check("cookie is Secure", True)
        elif args.allow_insecure:
            print("  SKIP  cookie is Secure (not Secure: allowed because --allow-insecure was given; never use that flag on the deployed site)")
        else:
            check("cookie is Secure", False, "use https; the backend sets Secure when ENVIRONMENT=production")

        # 3. refresh rotates the cookie and issues a working access token
        first = client.cookies.get(COOKIE, path="/api/auth")
        refreshed = client.post("/api/auth/refresh", headers={**CSRF, "Origin": origin})
        if check("refresh works with the cookie", refreshed.status_code == 200, f"got {code(refreshed)}. If this is CSRF_REJECTED, add {origin} to FRONTEND_URL or EXTRA_FRONTEND_ORIGINS on the backend; if REFRESH_INVALID, the cookie was not sent back."):
            token = refreshed.json()["access_token"]
            check("the new access token works", client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200)
            second = client.cookies.get(COOKIE, path="/api/auth")
            check("the cookie was rotated", bool(second) and second != first)

        # 4. a request from an unknown website is refused
        evil = client.post("/api/auth/refresh", headers={**CSRF, "Origin": "https://evil.example"})
        check("a request from an unknown website is refused", evil.status_code == 403 and code(evil) == "CSRF_REJECTED", f"got {code(evil)}")
        check("a request without the custom header is refused", client.post("/api/auth/refresh", headers={"Origin": origin}).status_code == 403)

        # 5. replay detection
        if args.check_replay:
            old = client.cookies.get(COOKIE, path="/api/auth")
            client.post("/api/auth/refresh", headers={**CSRF, "Origin": origin})
            print("        (waiting 11 seconds for the replay window to close...)")
            time.sleep(11)
            with httpx.Client(base_url=base, timeout=30) as thief:
                thief.cookies.set(COOKIE, old, path="/api/auth")
                replay = thief.post("/api/auth/refresh", headers={**CSRF, "Origin": origin})
            check("replaying an old cookie is detected", code(replay) == "REFRESH_REUSED", f"got {code(replay)}")
            check("... and the real session is revoked as well", client.post("/api/auth/refresh", headers={**CSRF, "Origin": origin}).status_code == 401)
            client.post("/api/auth/login", json={"email": email, "password": password})

        # 6. logout
        out = client.post("/api/auth/logout", headers={**CSRF, "Origin": origin})
        cleared = [h for h in cookie_headers(out) if "max-age=0" in h.lower()]
        check("logout succeeds and clears the cookie", out.status_code == 204 and bool(cleared), f"got {out.status_code}")
        check("the session is dead after logout", client.post("/api/auth/refresh", headers={**CSRF, "Origin": origin}).status_code == 401)

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED: " + "; ".join(failures))
        return 1
    print("All checks passed. (The throwaway account remains; it is harmless.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
