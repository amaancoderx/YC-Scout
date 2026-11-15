"""Login for the hosted dashboard.

Enabled when APP_PASSWORD is set (always on Render). Sign-in issues an HMAC-signed,
HttpOnly session cookie; every page and API call checks it. Wrong passwords are
rate-limited per IP.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import config

COOKIE = "ycs_session"
MAX_AGE = 30 * 24 * 3600
OPEN_PATHS = {"/login", "/api/login", "/api/logout", "/healthz", "/favicon.ico"}
_failures: dict[str, deque] = defaultdict(deque)


def enabled() -> bool:
    return bool(config.APP_PASSWORD)


def _secret() -> bytes:
    base = config.SECRET_KEY or ("ycscout:" + (config.APP_PASSWORD or "") + ":" + (config.APP_EMAIL or ""))
    return hashlib.sha256(base.encode()).digest()


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def make_cookie(email: str) -> str:
    payload = f"{email}|{int(time.time()) + MAX_AGE}"
    return base64.urlsafe_b64encode(f"{payload}|{_sign(payload)}".encode()).decode()


def valid_cookie(value: str | None) -> bool:
    if not value:
        return False
    try:
        email, exp, sig = base64.urlsafe_b64decode(value.encode()).decode().rsplit("|", 2)
    except Exception:
        return False
    return (hmac.compare_digest(sig, _sign(f"{email}|{exp}")) and exp.isdigit() and int(exp) > time.time()
            and email.lower() == (config.APP_EMAIL or "").lower())


def check_password(email: str, password: str) -> bool:
    ok_email = hmac.compare_digest((email or "").strip().lower(), (config.APP_EMAIL or "").lower())
    ok_pass = hmac.compare_digest((password or "").encode(), (config.APP_PASSWORD or "").encode())
    return ok_email and ok_pass


def too_many_attempts(ip: str) -> bool:
    q = _failures[ip]
    while q and time.time() - q[0] > 900:
        q.popleft()
    return len(q) >= 10


def record_failure(ip: str) -> None:
    _failures[ip].append(time.time())


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def is_https(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


async def middleware(request: Request, call_next):
    if not enabled():
        return await call_next(request)
    path = request.url.path
    if path in OPEN_PATHS or valid_cookie(request.cookies.get(COOKIE)):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Not signed in"}, status_code=401)
    if path.startswith("/static/"):
        return JSONResponse({"detail": "Not signed in"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


LOGIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · YC Scout</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23111827'/%3E%3Cpath d='M10 9l6 8 6-8M16 17v7' stroke='%23fb923c' stroke-width='2.6' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script>try{var t=localStorage.getItem('ycscout-theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t;}catch(e){}</script>
<style>
:root { --bg:#f4f4f2; --card:#fff; --text:#18181b; --muted:#71717a; --border:#e2e2e0; --input:#fafaf9; --accent:#ea580c; --focus:rgba(234,88,12,.25); --err:#b91c1c; --errbg:#fef2f2; color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0b0b0d; --card:#131316; --text:#f4f4f5; --muted:#a1a1aa; --border:#26262c; --input:#17171b; --accent:#fb923c; --focus:rgba(251,146,60,.28); --err:#f87171; --errbg:#2a1010; color-scheme: dark; } }
:root[data-theme="dark"] { --bg:#0b0b0d; --card:#131316; --text:#f4f4f5; --muted:#a1a1aa; --border:#26262c; --input:#17171b; --accent:#fb923c; --focus:rgba(251,146,60,.28); --err:#f87171; --errbg:#2a1010; color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; min-height:100vh; display:grid; place-items:center; padding:24px 16px; background: radial-gradient(1200px 500px at 50% -10%, color-mix(in srgb, var(--accent) 12%, transparent), transparent), var(--bg);
  color:var(--text); font-family:Inter, ui-sans-serif, system-ui, "Segoe UI", sans-serif; -webkit-font-smoothing:antialiased; }
.card { width:min(400px,100%); background:var(--card); border:1px solid var(--border); border-radius:16px; padding:30px 28px 26px; box-shadow:0 20px 50px -20px rgba(0,0,0,.25); }
.brand { display:flex; align-items:center; gap:10px; margin-bottom:22px; }
.brand svg { width:34px; height:34px; }
.brand b { font-size:18px; letter-spacing:-.01em; }
h1 { margin:0 0 4px; font-size:21px; letter-spacing:-.015em; }
p.sub { margin:0 0 22px; color:var(--muted); font-size:14px; }
label { display:block; font-size:13px; font-weight:600; margin:0 0 6px; }
.field { margin-bottom:14px; position:relative; }
input[type=email], input[type=password], input[type=text] { width:100%; height:42px; padding:0 12px; border:1px solid var(--border); border-radius:10px; background:var(--input); color:var(--text); font:inherit; font-size:14.5px; outline:none; transition:border-color .12s, box-shadow .12s; }
input:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--focus); }
.pw { padding-right:64px !important; }
.show { position:absolute; right:8px; bottom:8px; height:26px; padding:0 9px; border:0; border-radius:7px; background:transparent; color:var(--muted); font:inherit; font-size:12.5px; cursor:pointer; }
.show:hover { color:var(--text); background:var(--bg); }
.row { display:flex; align-items:center; justify-content:space-between; margin:4px 0 18px; font-size:13px; color:var(--muted); }
.row label { display:flex; align-items:center; gap:7px; font-weight:500; margin:0; cursor:pointer; }
button.go { width:100%; height:44px; border:0; border-radius:10px; background:var(--text); color:var(--card); font:inherit; font-size:14.5px; font-weight:600; cursor:pointer; transition:opacity .12s; }
button.go:hover { opacity:.9; } button.go:disabled { opacity:.55; cursor:default; }
.err { display:none; margin:0 0 14px; padding:9px 12px; border-radius:10px; background:var(--errbg); color:var(--err); font-size:13.5px; }
.foot { margin-top:18px; text-align:center; font-size:12px; color:var(--muted); }
</style>
</head>
<body>
<main class="card">
  <div class="brand"><svg viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="currentColor"/><path d="M10 9l6 8 6-8M16 17v7" stroke="#fb923c" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg><b>YC Scout</b></div>
  <h1>Welcome back</h1>
  <p class="sub">Sign in to your dashboard</p>
  <div class="err" id="err"></div>
  <form id="f" autocomplete="on">
    <div class="field"><label for="email">Email</label><input id="email" name="email" type="email" autocomplete="username" required autofocus></div>
    <div class="field"><label for="password">Password</label><input id="password" name="password" class="pw" type="password" autocomplete="current-password" required><button type="button" class="show" id="show">Show</button></div>
    <div class="row"><label><input type="checkbox" id="remember" checked> Keep me signed in</label></div>
    <button class="go" id="go" type="submit">Sign in</button>
  </form>
  <div class="foot">Private dashboard</div>
</main>
<script>
const $ = (s) => document.querySelector(s);
$("#show").onclick = () => { const p = $("#password"); p.type = p.type === "password" ? "text" : "password"; $("#show").textContent = p.type === "password" ? "Show" : "Hide"; p.focus(); };
$("#f").onsubmit = async (e) => {
  e.preventDefault();
  const btn = $("#go"), err = $("#err");
  btn.disabled = true; btn.textContent = "Signing in…"; err.style.display = "none";
  try {
    const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: $("#email").value, password: $("#password").value, remember: $("#remember").checked }) });
    if (r.ok) { location.href = "/"; return; }
    const d = await r.json().catch(() => ({}));
    err.textContent = d.detail || "Couldn't sign in."; err.style.display = "block";
  } catch { err.textContent = "Can't reach the server. Try again in a moment."; err.style.display = "block"; }
  btn.disabled = false; btn.textContent = "Sign in";
};
</script>
</body>
</html>"""


def login_page(request: Request):
    if not enabled() or valid_cookie(request.cookies.get(COOKIE)):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(LOGIN_HTML, headers={"Cache-Control": "no-store"})


def login(request: Request, payload: dict):
    ip = client_ip(request)
    if too_many_attempts(ip):
        return JSONResponse({"detail": "Too many attempts. Try again in 15 minutes."}, status_code=429)
    if not check_password(str(payload.get("email") or ""), str(payload.get("password") or "")):
        record_failure(ip)
        time.sleep(0.6)
        return JSONResponse({"detail": "Wrong email or password."}, status_code=401)
    _failures.pop(ip, None)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, make_cookie(config.APP_EMAIL), max_age=MAX_AGE if payload.get("remember", True) else None,
                    httponly=True, samesite="lax", secure=is_https(request), path="/")
    return resp


def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp
