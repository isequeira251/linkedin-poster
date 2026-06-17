"""Append a call-to-action to a finished LinkedIn post.

Keeps the CTA link in exactly one place, mirroring how hashtags.py owns the
hashtag block. The CTA is added to the post BODY only — after the copy, before
the hashtag block (see daily_runner.py) — so it never lands on the card image,
which renders from the clean post text.

    from cta import append_cta
    body = append_cta(post_text)     # body + "\n\n📊 ... <scorecard link>"
"""

from __future__ import annotations

# Ian's inbound CRM Health Check scorecard. It carries his Google Calendar
# booking link internally, so the post points here (a single funnel entry)
# rather than at a raw calendar link.
SCORECARD_URL = "https://isequeira251.github.io/crm-health-check/"

CTA = f"📊 How healthy is your CRM, really? Free 1-minute check — get your score and the top fixes (no signup): {SCORECARD_URL}"


def append_cta(text: str) -> str:
    """Return the post body with the scorecard CTA appended as a trailing block.

    Idempotent: if the scorecard link is already in the text (e.g. an approved
    or pre-written post that wrote it inline), the text is returned unchanged so
    we never double up the link."""
    if SCORECARD_URL in text:
        return text
    return f"{text.rstrip()}\n\n{CTA}"
