#!/usr/bin/env python3
"""One-time local helper: mint a long-lived YouTube refresh token.

Prereqs (one-time, in Google Cloud console — https://console.cloud.google.com):
  1. Create/select a project → APIs & Services → enable "YouTube Data API v3".
  2. OAuth consent screen → External → fill app name/email → ADD SCOPE
     https://www.googleapis.com/auth/youtube.upload → save.
     IMPORTANT: set Publishing status to "In production" (a Testing app's
     refresh tokens expire after 7 days; production tokens do not).
  3. Credentials → Create credentials → OAuth client ID → Desktop app.
     Copy the client ID + secret.

Then run:  python3 shorts/get_youtube_token.py
Paste the client ID/secret, approve in the browser (you'll see an
"unverified app" warning — Advanced → continue; it's your own app),
and store the three printed values as repo secrets:

  gh secret set YT_CLIENT_ID     -R isequeira251/linkedin-poster
  gh secret set YT_CLIENT_SECRET -R isequeira251/linkedin-poster
  gh secret set YT_REFRESH_TOKEN -R isequeira251/linkedin-poster
"""
import http.server
import json
import threading
import urllib.parse
import webbrowser

import requests

SCOPE = "https://www.googleapis.com/auth/youtube.upload"
PORT = 8765
REDIRECT = f"http://localhost:{PORT}/"

code_holder = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code_holder["code"] = qs.get("code", [""])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Token received - you can close this tab.")

    def log_message(self, *a):
        pass


def main():
    client_id = input("OAuth client ID: ").strip()
    client_secret = input("OAuth client secret: ").strip()

    auth_url = ("https://accounts.google.com/o/oauth2/v2/auth?" +
                urllib.parse.urlencode({
                    "client_id": client_id,
                    "redirect_uri": REDIRECT,
                    "response_type": "code",
                    "scope": SCOPE,
                    "access_type": "offline",
                    "prompt": "consent",
                }))
    server = http.server.HTTPServer(("localhost", PORT), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    print(f"\nOpening browser... if it doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)
    while "code" not in code_holder:
        pass

    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code_holder["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT,
        "grant_type": "authorization_code",
    }, timeout=30)
    resp.raise_for_status()
    tok = resp.json()
    if "refresh_token" not in tok:
        raise SystemExit(f"no refresh_token in response: {json.dumps(tok, indent=2)}")

    print("\n=== store these as repo secrets ===")
    print(f"YT_CLIENT_ID={client_id}")
    print(f"YT_CLIENT_SECRET={client_secret}")
    print(f"YT_REFRESH_TOKEN={tok['refresh_token']}")


if __name__ == "__main__":
    main()
