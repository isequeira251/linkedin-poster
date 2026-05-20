"""Daily runner: publishes today's post, generating it on the fly when needed.

Each posts.json entry is {date, posted, ...} plus one of:
  - "text": a pre-written, ready-to-publish post (legacy / hand-authored).
  - "note": a raw note the ghostwriter turns into a post at run time.
  - "bubble" (optional): true forces the card's thought bubble, false suppresses
    it. Omit to let generate_card decide from hook length.

Order of operations for `today`:
  1. A scheduled entry with "text" -> publish it as-is.
  2. A scheduled entry with "note" (no "text") -> ghostwrite it, then publish.
  3. Nothing scheduled -> pull the next unused note from notes.json, ghostwrite
     it, publish, and append the result to posts.json.

So the hand-written queue keeps flowing until it runs out, after which the
notes pool auto-generates a fresh post every day. Generated posts are quality-
gated: if the model's average self-score is below MIN_AVG_SCORE (default 6.0,
set 0 to disable), nothing is posted and the run fails so it can be retried.

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


def _ghostwrite_or_die(raw_input: str) -> dict:
    """Generate a draft and enforce the optional quality gate. Raises SystemExit
    (without consuming the note) if the draft scores below MIN_AVG_SCORE."""
    print(f"Ghostwriting from note: {raw_input[:70]!r}...")
    draft = generate_post(raw_input)
    score = _avg_score(draft["self_score"])
    print(f"Self-score avg {score:.1f}  detail={draft['self_score']}")
    min_score = float(os.environ.get("MIN_AVG_SCORE", DEFAULT_MIN_AVG_SCORE))
    if min_score and score < min_score:
        raise SystemExit(
            f"ERROR: draft scored {score:.1f} < MIN_AVG_SCORE={min_score}; not "
            f"posting. Rework the note or lower MIN_AVG_SCORE, then re-run."
        )
    return draft


def main() -> int:
    today = os.environ.get("OVERRIDE_DATE") or date.today().isoformat()

    if not POSTS_FILE.exists():
        print(f"ERROR: {POSTS_FILE} not found", file=sys.stderr)
        return 1
    posts = json.loads(POSTS_FILE.read_text())

    todays = [p for p in posts if p["date"] == today and not p.get("posted")]
    if len(todays) > 1:
        print(f"WARN: {len(todays)} posts scheduled for {today}; posting the first only.")
    warn_if_token_expiring()

    # Decide what to publish, generating from a note when there's no ready text.
    target = todays[0] if todays else None
    note_entry: tuple[list, dict] | None = None  # set when pulling from the pool
    bubble = None

    if target is not None and target.get("text"):
        text = target["text"]
        bubble = target.get("bubble")
        print(f"Publishing pre-written entry for {today}.")
    elif target is not None and target.get("note"):
        draft = _ghostwrite_or_die(target["note"])
        text = draft["post"]
        bubble = target.get("bubble")
        target.update(
            text=text,
            generated=True,
            hook_options=draft["hook_options"],
            self_score=draft["self_score"],
        )
    else:
        notes, note = _next_unused_note()
        if note is None:
            print(f"Nothing scheduled for {today} and no unused notes left.")
            return 0
        draft = _ghostwrite_or_die(note["note"])
        text = draft["post"]
        target = {
            "date": today,
            "note": note["note"],
            "text": text,
            "generated": True,
            "hook_options": draft["hook_options"],
            "self_score": draft["self_score"],
        }
        posts.append(target)
        note_entry = (notes, note)

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

    if note_entry is not None:
        notes, note = note_entry
        note["used"] = True
        note["used_at"] = today
        NOTES_FILE.write_text(json.dumps(notes, indent=2) + "\n")
        print(f"Marked note used in {NOTES_FILE}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
