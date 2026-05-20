"""Daily runner: ghostwrites today's post from the notes pool, falling back to
a pre-written post when the pool can't produce one.

Priority each run (for `today`, and only if nothing was posted yet today):
  1. DEFAULT — the next unused note in notes.json: ghostwrite it, and if the
     draft clears MIN_AVG_SCORE, publish it and append the result to posts.json.
  2. FALLBACK — if there's no unused note, or the draft scored below the gate,
     publish today's unposted pre-written `text` entry in posts.json instead.
  3. Otherwise, do nothing.

posts.json entries are {date, posted, ...}. Pre-written entries carry "text";
generated entries also carry "generated": true, "note", "hook_options", and
"self_score". "bubble" (optional) forces/suppresses the card thought bubble.

Reads credentials from env vars (LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN)
or token.json, and ANTHROPIC_API_KEY for generation. Built for GitHub Actions
or local cron.
"""

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from generate_card import generate_card
from ghostwriter import generate_post
from linkedin_post import load_credentials, post_to_linkedin

POSTS_FILE = Path(__file__).parent / "posts.json"
NOTES_FILE = Path(__file__).parent / "notes.json"
TOKEN_FILE = Path(__file__).parent / "token.json"

DEFAULT_MIN_AVG_SCORE = 6.0


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


def _next_unused_note() -> tuple[list, dict | None]:
    """Return (all_notes, first_unused_note) from notes.json, or ([], None)."""
    if not NOTES_FILE.exists():
        return [], None
    notes = json.loads(NOTES_FILE.read_text())
    nxt = next((n for n in notes if not n.get("used")), None)
    return notes, nxt


def _avg_score(self_score: dict) -> float:
    vals = [v for v in self_score.values() if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else 0.0


def _ghostwrite(raw_input: str) -> dict | None:
    """Generate a draft. Return it if it clears MIN_AVG_SCORE; return None (so
    the caller falls back to a pre-written post) if it scores below the gate.
    On a fallback the note is left unused, so it's retried on the next run."""
    print(f"Ghostwriting from note: {raw_input[:70]!r}...")
    draft = generate_post(raw_input)
    score = _avg_score(draft["self_score"])
    min_score = float(os.environ.get("MIN_AVG_SCORE", DEFAULT_MIN_AVG_SCORE))
    print(f"Self-score avg {score:.1f}  detail={draft['self_score']}  (gate={min_score})")
    if min_score and score < min_score:
        print("WARN: draft below gate; falling back to a pre-written post.", file=sys.stderr)
        return None
    return draft


def main() -> int:
    today = os.environ.get("OVERRIDE_DATE") or date.today().isoformat()

    if not POSTS_FILE.exists():
        print(f"ERROR: {POSTS_FILE} not found", file=sys.stderr)
        return 1
    posts = json.loads(POSTS_FILE.read_text())

    # Idempotency: never post twice for the same day.
    if any(p["date"] == today and p.get("posted") for p in posts):
        print(f"Already posted for {today}; nothing to do.")
        warn_if_token_expiring()
        return 0
    warn_if_token_expiring()

    target = None       # the posts.json entry we'll publish
    bubble = None
    consume_note = None  # (notes_list, note) to mark used on success

    # 1) Default: ghostwrite the next unused note.
    notes, note = _next_unused_note()
    if note is not None:
        draft = _ghostwrite(note["note"])
        if draft is not None:
            target = {
                "date": today,
                "note": note["note"],
                "text": draft["post"],
                "generated": True,
                "hook_options": draft["hook_options"],
                "self_score": draft["self_score"],
            }
            posts.append(target)
            consume_note = (notes, note)

    # 2) Fallback: today's unposted pre-written entry.
    if target is None:
        prewritten = [
            p for p in posts
            if p["date"] == today and not p.get("posted")
            and p.get("text") and not p.get("generated")
        ]
        if not prewritten:
            print(f"No usable note and no pre-written post for {today}; nothing to do.")
            return 0
        target = prewritten[0]
        bubble = target.get("bubble")
        print(f"Publishing pre-written fallback for {today}.")

    text = target["text"]
    access_token, person_urn = load_credentials()

    print(f"Generating card for {today}...")
    card_bytes = generate_card(text, bubble=bubble)
    print(f"Posting for {today} (with image, {len(card_bytes)} bytes)...")
    post_id = post_to_linkedin(text, access_token, person_urn, image_bytes=card_bytes)
    print(f"Posted: {post_id}")

    target["posted"] = True
    target["posted_at"] = datetime.now(timezone.utc).isoformat()
    target["post_id"] = post_id
    POSTS_FILE.write_text(json.dumps(posts, indent=2) + "\n")
    print(f"Updated {POSTS_FILE}")

    if consume_note is not None:
        notes, note = consume_note
        note["used"] = True
        note["used_at"] = today
        NOTES_FILE.write_text(json.dumps(notes, indent=2) + "\n")
        print(f"Marked note used in {NOTES_FILE}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
