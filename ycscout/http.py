"""Shared HTTP client with retries and per-host politeness."""
from __future__ import annotations

import random
import ssl
import threading
import time
from urllib.parse import urlparse

import httpx

from . import config

_client: httpx.Client | None = None
_client_lock = threading.Lock()
_host_last: dict[str, float] = {}
_host_lock = threading.Lock()

# Minimum gap between two requests to the same host (seconds).
HOST_GAP = {"www.ycombinator.com": 0.35}
DEFAULT_GAP = 0.15


def client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            # Use the OS trust store (Windows cert store / macOS keychain) so the
            # app works behind antivirus or corporate TLS inspection, like a browser.
            ctx = ssl.create_default_context()
            _client = httpx.Client(
                verify=ctx,
                headers={
                    "User-Agent": config.USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
            )
        return _client


def _throttle(url: str) -> None:
    host = urlparse(url).netloc
    gap = HOST_GAP.get(host, DEFAULT_GAP)
    with _host_lock:
        now = time.monotonic()
        wait = _host_last.get(host, 0) + gap - now
        _host_last[host] = max(now, _host_last.get(host, 0) + gap)
    if wait > 0:
        time.sleep(wait)


def get(url: str, *, retries: int = 3, timeout: float | None = None) -> httpx.Response:
    """GET with exponential backoff on 429/5xx and transient network errors."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        _throttle(url)
        try:
            kwargs = {"timeout": timeout} if timeout else {}
            resp = client().get(url, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt + random.random()
                if attempt < retries:
                    time.sleep(min(delay, 30))
                    continue
            return resp
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2 ** attempt + random.random())
                continue
    if last_exc:
        raise last_exc
    raise RuntimeError(f"GET failed: {url}")


def get_json(url: str):
    resp = get(url)
    resp.raise_for_status()
    return resp.json()
