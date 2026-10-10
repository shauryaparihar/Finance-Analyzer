"""
Runs scripts/check_cookie_flow.py against a real backend process placed behind a local proxy, once behaving
like a good rewrite and once like a broken one. The same script is what gets run against the deployed site.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from backend.tests.conftest import TEST_DATABASE_URL
from backend.tests.support.proxy import start_proxy

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def stack(test_engine):
    """A backend process plus helpers to put a proxy in front of it."""
    backend_port, proxy_port = _free_port(), _free_port()
    started = {"process": None, "proxy": None}

    def launch(allow_proxy_origin: bool, strip_set_cookie: bool = False) -> str:
        env = {
            **os.environ, "PYTHONPATH": str(ROOT), "ENVIRONMENT": "development", "DATABASE_URL": TEST_DATABASE_URL,
            "EXTRA_FRONTEND_ORIGINS": f"http://127.0.0.1:{proxy_port}" if allow_proxy_origin else "",
        }
        started["process"] = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(backend_port),
             "--log-config", "backend/logging_config.json", "--no-access-log"],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(80):
            try:
                if httpx.get(f"http://127.0.0.1:{backend_port}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            pytest.fail("the backend did not start")
        started["proxy"] = start_proxy(proxy_port, f"http://127.0.0.1:{backend_port}", strip_set_cookie)
        return f"http://127.0.0.1:{proxy_port}"

    yield launch
    if started["proxy"]:
        started["proxy"].shutdown()
    if started["process"] and started["process"].poll() is None:
        started["process"].terminate()
        started["process"].wait(timeout=20)


def _run_check(url: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/check_cookie_flow.py", url, "--allow-insecure", *extra],
        cwd=ROOT, capture_output=True, text=True, timeout=90,
    )


def test_a_proxy_that_forwards_cookies_passes_every_check_including_replay_detection(stack):
    url = stack(allow_proxy_origin=True)
    result = _run_check(url, "--check-replay")
    assert result.returncode == 0, result.stdout[-1500:]
    for expected in (
        "the refresh cookie (Set-Cookie) reaches the browser through this address", "cookie is HttpOnly", "cookie is SameSite=Strict",
        "the cookie was rotated", "a request from an unknown website is refused", "replaying an old cookie is detected",
        "logout succeeds and clears the cookie", "All checks passed",
    ):
        assert f"PASS  {expected}" in result.stdout or expected in result.stdout, expected
    assert "FAIL" not in result.stdout


def test_a_proxy_that_drops_set_cookie_is_caught_with_an_explanation(stack):
    url = stack(allow_proxy_origin=True, strip_set_cookie=True)
    result = _run_check(url)
    assert result.returncode == 1
    assert "FAIL  the refresh cookie (Set-Cookie) reaches the browser through this address" in result.stdout
    assert "dropping Set-Cookie" in result.stdout and "logged out on every reload" in result.stdout


def test_a_backend_that_does_not_know_the_websites_address_is_caught_with_the_fix(stack):
    url = stack(allow_proxy_origin=False)  # FRONTEND_URL / EXTRA_FRONTEND_ORIGINS do not include the proxy's address
    result = _run_check(url)
    assert result.returncode == 1
    assert "FAIL  refresh works with the cookie" in result.stdout
    assert "EXTRA_FRONTEND_ORIGINS" in result.stdout and "CSRF_REJECTED" in result.stdout


def test_an_address_with_nothing_behind_it_fails_clearly():
    result = _run_check(f"http://127.0.0.1:{_free_port()}")
    assert result.returncode == 1 and "could not connect" in result.stdout
