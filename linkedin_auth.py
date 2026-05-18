"""One-time OAuth flow: get an access token + person URN for posting to your personal LinkedIn feed.

Run this once locally. It will:
  1. Open your browser to LinkedIn's authorization page.
  2. Spin up a tiny localhost HTTP server to catch the redirect.
  3. Exchange the auth code for an access token.
  4. Fetch your person URN via /userinfo.
  5. Save token.json with the access token, expiry, and person URN.

After that, daily_runner.py uses token.json (or env vars) to post.
"""

import http.server
import json
import os
import secrets
import socketserver
import sys
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("LINKEDIN_REDIRECT_URI", "http://localhost:8000/callback")
SCOPES = "openid profile email w_member_social"
TOKEN_FILE = Path(__file__).parent / "token.json"

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"


def build_auth_url(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "scope": SCOPES,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    captured = {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        CallbackHandler.captured = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if "error" in CallbackHandler.captured:
            body = f"<h1>Authorization failed</h1><pre>{CallbackHandler.captured}</pre>"
        else:
            body = "<h1>Authorization received.</h1><p>You can close this tab.</p>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        return


def wait_for_callback(port: int) -> dict:
    with socketserver.TCPServer(("localhost", port), CallbackHandler) as httpd:
        httpd.handle_request()
    return CallbackHandler.captured


def exchange_code_for_token(code: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_person_urn(access_token: str) -> str:
    resp = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    resp.raise_for_status()
    sub = resp.json()["sub"]
    return f"urn:li:person:{sub}"


def main() -> int:
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET in .env", file=sys.stderr)
        return 1

    parsed_redirect = urllib.parse.urlparse(REDIRECT_URI)
    if parsed_redirect.hostname != "localhost":
        print(f"ERROR: REDIRECT_URI must point to localhost, got {REDIRECT_URI}", file=sys.stderr)
        return 1
    port = parsed_redirect.port or 80

    state = secrets.token_urlsafe(16)
    url = build_auth_url(state)
    print(f"Opening browser for LinkedIn authorization on port {port}...")
    print(f"If the browser doesn't open, visit:\n{url}\n")
    webbrowser.open(url)

    captured = wait_for_callback(port)
    if "error" in captured:
        print(f"ERROR: {captured}", file=sys.stderr)
        return 1
    if captured.get("state") != state:
        print("ERROR: state mismatch — possible CSRF, aborting.", file=sys.stderr)
        return 1
    code = captured.get("code")
    if not code:
        print(f"ERROR: no code in callback: {captured}", file=sys.stderr)
        return 1

    print("Exchanging code for access token...")
    token_data = exchange_code_for_token(code)
    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", 0)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    print("Fetching person URN from /userinfo...")
    person_urn = fetch_person_urn(access_token)

    payload = {
        "access_token": access_token,
        "expires_at": expires_at.isoformat(),
        "person_urn": person_urn,
        "scope": token_data.get("scope"),
    }
    TOKEN_FILE.write_text(json.dumps(payload, indent=2))
    print(f"\nSaved {TOKEN_FILE}")
    print(f"  person_urn:  {person_urn}")
    print(f"  expires_at:  {expires_at.isoformat()}")
    print(f"  expires_in:  ~{expires_in // 86400} days\n")
    print("For GitHub Actions, set these repo secrets:")
    print(f"  LINKEDIN_ACCESS_TOKEN={access_token}")
    print(f"  LINKEDIN_PERSON_URN={person_urn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
