"""Thin, defensive wrapper around the Gemini API (google-genai).

Everything AI goes through here so model choice, fallbacks, rate limiting and
error messages live in one place:

  research()   Google Search + URL context grounding; returns notes with the real
               source URL appended to every grounded sentence, plus all sources.
  structured() JSON that matches a schema.
  stream()     Streaming turn with thought summaries and function calling (agent).
  ping()       Connection test for Settings.

Models are tried in order (GEMINI_MODEL, then GEMINI_FALLBACK_MODELS) when one is
rate-limited, overloaded or not available to the key.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Iterator

import httpx
from google import genai
from google.genai import errors as gerrors
from google.genai import types as T

from . import config

_client: genai.Client | None = None
_lock = threading.Lock()
_rate_lock = threading.Lock()
_last_calls: list[float] = []


class AIError(RuntimeError):
    """An AI call failed in a way the user should see."""


class AINotConfigured(AIError):
    pass


def client() -> genai.Client:
    global _client
    if not config.ai_enabled():
        raise AINotConfigured("Gemini is not configured. Add GEMINI_API_KEY to .env and restart.")
    with _lock:
        if _client is None:
            _client = genai.Client(api_key=config.GEMINI_API_KEY,
                                   http_options=T.HttpOptions(timeout=180_000))
        return _client


# Models whose daily free quota is used up -> unix time when Google resets it.
# Kept in data/model_quota.json so a restart doesn't waste a request rediscovering it.
_QUOTA_FILE = config.DATA_DIR / "model_quota.json"
try:
    _exhausted: dict[str, float] = {k: float(v) for k, v in json.loads(_QUOTA_FILE.read_text()).items() if float(v) > time.time()}
except Exception:
    _exhausted = {}


def _mark_exhausted(model: str, exc: Exception) -> None:
    _exhausted[model] = time.time() + min(_retry_delay(exc) or 3600, 86400)
    try:
        _QUOTA_FILE.write_text(json.dumps(_exhausted))
    except OSError:
        pass


def models(first: str | None = None) -> list[str]:
    out = []
    for m in [first, config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS]:
        if m and m not in out:
            out.append(m)
    now = time.time()
    ready = [m for m in out if _exhausted.get(m, 0) <= now]
    return ready or out  # if everything is exhausted, still try (quota may have reset)


def active_model() -> str:
    """The model the agent will use right now (skips models out of daily quota)."""
    return models()[0]


def model_label(model: str | None = None) -> str:
    """'gemini-3.5-flash' -> 'Gemini 3.5 Flash'."""
    m = (model or active_model()).replace("models/", "")
    return " ".join(p.capitalize() if not re.match(r"\d", p) else p for p in m.split("-"))


# ---------------------------------------------------------------------------
# Rate limiting, retries and fallbacks
# ---------------------------------------------------------------------------

def _throttle() -> None:
    """Keep the whole app under GEMINI_RPM requests per rolling minute."""
    rpm = max(1, config.GEMINI_RPM)
    while True:
        with _rate_lock:
            now = time.monotonic()
            while _last_calls and now - _last_calls[0] > 60:
                _last_calls.pop(0)
            if len(_last_calls) < rpm:
                _last_calls.append(now)
                return
            wait = 60 - (now - _last_calls[0]) + 0.2
        time.sleep(max(0.2, wait))


def _retry_delay(exc: Exception) -> float | None:
    m = re.search(r"retry(?:Delay| in)['\": ]+([\d.]+)s", str(exc))
    return float(m.group(1)) if m else None


def _friendly(exc: Exception) -> AIError:
    code = getattr(exc, "code", None)
    msg = str(exc)
    if code in (401, 403) or "API_KEY_INVALID" in msg or "PERMISSION_DENIED" in msg:
        return AIError("Gemini rejected the API key. Check GEMINI_API_KEY in .env.")
    if code == 429:
        return AIError("Gemini rate limit or daily quota reached. Wait a minute, or use a paid key for bigger batches.")
    if code in (500, 502, 503, 504):
        return AIError("Gemini is overloaded right now. Try again in a minute.")
    if code == 400:
        return AIError(f"Gemini rejected the request: {getattr(exc, 'message', None) or msg[:200]}")
    if isinstance(exc, (httpx.TransportError, ConnectionError, TimeoutError)):
        return AIError("Could not reach Gemini. Check your internet connection.")
    return AIError(f"Gemini error: {msg[:200]}")


def _no_quota(exc: Exception) -> bool:
    """429 caused by a zero or exhausted daily quota: retrying the same model won't help."""
    msg = str(exc)
    return getattr(exc, "code", None) == 429 and ("limit: 0" in msg or "PerDay" in msg or "per day" in msg.lower())


def _retryable(exc: Exception) -> bool:
    return getattr(exc, "code", None) in (404, 429, 500, 502, 503, 504) or isinstance(
        exc, (httpx.TransportError, TimeoutError))


def generate(contents, cfg: T.GenerateContentConfig, *, attempts_per_model: int = 2,
             first_model: str | None = None) -> T.GenerateContentResponse:
    """generate_content with throttling, short retries and model fallbacks."""
    last: Exception | None = None
    for model in models(first_model):
        for attempt in range(attempts_per_model):
            _throttle()
            try:
                resp = client().models.generate_content(model=model, contents=contents, config=cfg)
                _check_blocked(resp)
                return resp
            except AIError:
                raise
            except (gerrors.APIError, httpx.TransportError, TimeoutError) as exc:
                last = exc
                if not _retryable(exc):
                    raise _friendly(exc) from exc
                if _no_quota(exc):
                    _mark_exhausted(model, exc)
                if getattr(exc, "code", None) == 404 or _no_quota(exc):
                    break  # model (or this tool) not available to this key: next model
                if attempt + 1 < attempts_per_model:
                    time.sleep(min(_retry_delay(exc) or (4 * (attempt + 1)), 30))
    raise _friendly(last) if last else AIError("Gemini returned nothing.")


def _check_blocked(resp) -> None:
    fb = getattr(resp, "prompt_feedback", None)
    if fb and getattr(fb, "block_reason", None):
        raise AIError(f"Gemini blocked this request ({fb.block_reason}).")
    if not resp.candidates:
        raise AIError("Gemini returned no answer.")
    reason = str(getattr(resp.candidates[0], "finish_reason", "") or "")
    if reason.endswith(("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII")):
        raise AIError("Gemini declined this request.")


def text_of(resp) -> str:
    try:
        parts = resp.candidates[0].content.parts or []
    except (AttributeError, IndexError, TypeError):
        return ""
    return "".join(p.text for p in parts if p.text and not p.thought).strip()


# ---------------------------------------------------------------------------
# Research with grounding
# ---------------------------------------------------------------------------

_redirect_cache: dict[str, str] = {}


def _resolve(url: str) -> str:
    """Grounding links are Google redirect URLs; resolve them to the real page."""
    if "grounding-api-redirect" not in url:
        return url
    if url in _redirect_cache:
        return _redirect_cache[url]
    real = url
    try:
        r = httpx.head(url, follow_redirects=False, timeout=10)
        if r.headers.get("location"):
            real = r.headers["location"]
        else:
            r = httpx.get(url, follow_redirects=True, timeout=15)
            real = str(r.url)
    except Exception:
        pass
    _redirect_cache[url] = real
    return real


def research(*, system: str, prompt: str) -> tuple[str, list[str]]:
    """Web-grounded answer. Returns (notes with [source: …] after each grounded
    sentence, list of every source URL used)."""
    cfg = T.GenerateContentConfig(
        system_instruction=system,
        tools=[T.Tool(google_search=T.GoogleSearch()), T.Tool(url_context=T.UrlContext())],
        thinking_config=T.ThinkingConfig(include_thoughts=False),
    )
    resp = generate(prompt, cfg, first_model=config.GEMINI_RESEARCH_MODEL)
    text = text_of(resp)
    cand = resp.candidates[0]
    gm = getattr(cand, "grounding_metadata", None)
    chunk_urls: list[str] = []
    for ch in (getattr(gm, "grounding_chunks", None) or []):
        web = getattr(ch, "web", None)
        chunk_urls.append(_resolve(web.uri) if web and web.uri else "")

    # Insert the source after each grounded segment. Indices are UTF-8 byte offsets.
    supports = list(getattr(gm, "grounding_supports", None) or [])
    if supports and text:
        raw = text.encode("utf-8")
        inserts = []
        for s in supports:
            seg = getattr(s, "segment", None)
            idx = [i for i in (getattr(s, "grounding_chunk_indices", None) or []) if i < len(chunk_urls) and chunk_urls[i]]
            if seg is None or seg.end_index is None or not idx:
                continue
            urls = list(dict.fromkeys(chunk_urls[i] for i in idx))[:2]
            inserts.append((seg.end_index, f" [source: {', '.join(urls)}]"))
        for end, note in sorted(inserts, key=lambda x: -x[0]):
            if 0 <= end <= len(raw):
                raw = raw[:end] + note.encode("utf-8") + raw[end:]
        text = raw.decode("utf-8", errors="ignore")

    sources = [u for u in chunk_urls if u]
    um = getattr(cand, "url_context_metadata", None)
    for meta in (getattr(um, "url_metadata", None) or []):
        status = str(getattr(meta, "url_retrieval_status", "") or "")
        if meta.retrieved_url and "SUCCESS" in status:
            sources.append(meta.retrieved_url)
    return text, list(dict.fromkeys(sources))


# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------

def structured(*, system: str, prompt: str, schema: dict, effort: str = "low", max_tokens: int = 8000) -> dict:
    cfg = T.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_json_schema=schema,
        max_output_tokens=max_tokens,
        thinking_config=T.ThinkingConfig(include_thoughts=False),
    )
    resp = generate(prompt, cfg)
    reason = str(getattr(resp.candidates[0], "finish_reason", "") or "")
    raw = text_of(resp)
    if reason.endswith("MAX_TOKENS") and not raw.rstrip().endswith("}"):
        raise AIError("Gemini's answer was cut off. Try again.")
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AIError("Gemini returned malformed JSON.") from exc


# ---------------------------------------------------------------------------
# Streaming (agent)
# ---------------------------------------------------------------------------

def stream(contents: list, cfg: T.GenerateContentConfig) -> Iterator[tuple[str, T.GenerateContentResponse]]:
    """Yield (model, chunk) pairs. Falls back to the next model only if the
    failure happens before anything was streamed."""
    last: Exception | None = None
    for model in models():
        for attempt in range(2):
            _throttle()
            started = False
            try:
                for chunk in client().models.generate_content_stream(model=model, contents=contents, config=cfg):
                    started = True
                    yield model, chunk
                return
            except (gerrors.APIError, httpx.TransportError, TimeoutError) as exc:
                if started:
                    raise _friendly(exc) from exc
                last = exc
                if not _retryable(exc):
                    raise _friendly(exc) from exc
                if _no_quota(exc):
                    _mark_exhausted(model, exc)
                if getattr(exc, "code", None) == 404 or _no_quota(exc):
                    break
                if attempt == 0:
                    time.sleep(min(_retry_delay(exc) or 3, 20))
    raise _friendly(last) if last else AIError("Gemini returned nothing.")


def ping() -> str:
    resp = generate("Reply with the single word: ready",
                    T.GenerateContentConfig(max_output_tokens=200, thinking_config=T.ThinkingConfig(include_thoughts=False)),
                    attempts_per_model=1)
    return f"{model_label(resp.model_version)} replied: {text_of(resp)[:40]}"
