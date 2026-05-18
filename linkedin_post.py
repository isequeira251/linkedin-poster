"""Post a single text message to your personal LinkedIn feed.

Library:  post_to_linkedin(text, access_token, person_urn) -> post URN string
CLI:      python linkedin_post.py "Your text here"
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
TOKEN_FILE = Path(__file__).parent / "token.json"


def post_to_linkedin(text: str, access_token: str, person_urn: str) -> str:
    body = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = requests.post(
        UGC_POSTS_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"LinkedIn post failed ({resp.status_code}): {resp.text}")
    return resp.headers.get("x-restli-id") or resp.json().get("id", "")


def load_credentials() -> tuple[str, str]:
    """Prefer env vars (CI). Fall back to token.json (local)."""
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    urn = os.environ.get("LINKEDIN_PERSON_URN")
    if token and urn:
        return token, urn
    if not TOKEN_FILE.exists():
        raise RuntimeError(
            f"No credentials. Set LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN "
            f"env vars, or run linkedin_auth.py to create {TOKEN_FILE}."
        )
    data = json.loads(TOKEN_FILE.read_text())
    return data["access_token"], data["person_urn"]


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python linkedin_post.py "Your post text"', file=sys.stderr)
        return 1
    text = sys.argv[1]
    access_token, person_urn = load_credentials()
    post_id = post_to_linkedin(text, access_token, person_urn)
    print(f"Posted: {post_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
