"""Daily runner: posts whatever's scheduled for today.

- Reads posts.json (an array of {date, posted, text})
- Finds the first entry where date == today and posted == false
- Posts it, then flips posted=true and saves
- Exits 0 if there's nothing to do today or the post succeeded
- Exits 1 on failure

Reads credentials from env vars (LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN)
or from token.json. Designed to be run by GitHub Actions or local cron.
"""

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from generate_card import generate_card
from linkedin_post import load_credentials, post_to_linkedin

POSTS_FILE = Path(__file__).parent / "posts.json"
TOKEN_FILE = Path(__file__).parent / "token.json"


def warn_if_token_expiring() -> None:
    """If we have a local token.json, warn when fewer than 7 days remain."""
    if not TOKEN_FILE.exists():
        return
    try:
        data = json.loads(TOKEN_FILE.read_text())
        expires_at = datetime.fromisoformat(data["expires_at"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return
    remaining = expires_at - datetime.now(timezone.utc)
    days = remaining.total_seconds() / 86400
    if days < 7:
        print(
            f"WARN: access token expires in {days:.1f} day(s). "
            f"Re-run linkedin_auth.py to refresh.",
            file=sys.stderr,
        )


def main() -> int:
    today = os.environ.get("OVERRIDE_DATE") or date.today().isoformat()

    if not POSTS_FILE.exists():
        print(f"ERROR: {POSTS_FILE} not found", file=sys.stderr)
        return 1
    posts = json.loads(POSTS_FILE.read_text())

    todays = [p for p in posts if p["date"] == today and not p.get("posted")]
    if not todays:
        print(f"Nothing scheduled for {today}.")
        warn_if_token_expiring()
        return 0
    if len(todays) > 1:
        print(f"WARN: {len(todays)} posts scheduled for {today}; posting the first only.")
    target = todays[0]

    warn_if_token_expiring()
    access_token, person_urn = load_credentials()

    print(f"Generating card for {today}...")
    card_bytes = generate_card(target["text"])
    print(f"Posting for {today} (with image, {len(card_bytes)} bytes)...")
    post_id = post_to_linkedin(target["text"], access_token, person_urn, image_bytes=card_bytes)
    print(f"Posted: {post_id}")

    target["posted"] = True
    target["posted_at"] = datetime.now(timezone.utc).isoformat()
    target["post_id"] = post_id
    POSTS_FILE.write_text(json.dumps(posts, indent=2) + "\n")
    print(f"Updated {POSTS_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
