"""One-time Gmail API sign-in: get a refresh token that lets YC Scout send email
over HTTPS (needed on hosts that block SMTP ports, like Render Free).

    python scout.py gmail-auth

Needs GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET (a "Desktop app" OAuth client from
Google Cloud) in .env. Opens your browser, you click Allow, and the refresh token
is written to .env as GMAIL_REFRESH_TOKEN.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import re
import secrets
import socketserver
import threading
import urllib.parse
import webbrowser

import httpx

from . import config

SCOPE = "https://www.googleapis.com/auth/gmail.send"


def run() -> str:
    if not (config.GMAIL_CLIENT_ID and config.GMAIL_CLIENT_SECRET):
        raise SystemExit("Add GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET to .env first (see DEPLOY.md, step 4).")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ok = q.get("state", [""])[0] == state and "code" in q
            result["code"] = q.get("code", [None])[0] if ok else None
            result["error"] = q.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Gmail connected. You can close this tab and go back to YC Scout." if ok else "Sign-in failed. Close this tab and try again."
            self.wfile.write(f"<html><body style='font-family:system-ui;padding:40px'><h2>{msg}</h2></body></html>".encode())

        def log_message(self, *args):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as srv:
        port = srv.server_address[1]
        redirect = f"http://127.0.0.1:{port}"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": config.GMAIL_CLIENT_ID, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent", "state": state, "login_hint": config.FROM_EMAIL or "",
            "code_challenge": challenge, "code_challenge_method": "S256"})
        print("Opening your browser to connect Gmail. If it doesn't open, visit:\n" + url)
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        srv.timeout = 300
        srv.handle_request()

    if not result.get("code"):
        raise SystemExit(f"Gmail sign-in was not completed ({result.get('error') or 'no code'}).")
    r = httpx.post("https://oauth2.googleapis.com/token", data={
        "code": result["code"], "client_id": config.GMAIL_CLIENT_ID, "client_secret": config.GMAIL_CLIENT_SECRET,
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier}, timeout=30)
    if r.status_code != 200 or "refresh_token" not in r.json():
        raise SystemExit(f"Token exchange failed: {r.text[:300]}")
    token = r.json()["refresh_token"]

    env = config.ROOT / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    if re.search(r"(?m)^GMAIL_REFRESH_TOKEN=.*$", text):
        text = re.sub(r"(?m)^GMAIL_REFRESH_TOKEN=.*$", f"GMAIL_REFRESH_TOKEN={token}", text)
    else:
        text = text.rstrip("\n") + f"\nGMAIL_REFRESH_TOKEN={token}\n"
    env.write_text(text, encoding="utf-8")
    return token
