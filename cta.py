"""Append a scheduling call-to-action to a finished LinkedIn post.

Keeps the booking link in exactly one place, mirroring how hashtags.py owns the
hashtag block. The CTA is added to the post BODY only — after the copy, before
the hashtag block (see daily_runner.py) — so it never lands on the card image,
which renders from the clean post text.

    from cta import append_cta
    body = append_cta(post_text)     # body + "\n\n📅 ... <booking link>"
"""

from __future__ import annotations

# Ian's free Google Calendar appointment-schedule booking page.
BOOKING_URL = "https://calendar.app.google/uk9YhnkaMWUc2QjY6"

CTA = f"📅 Want a second set of eyes on your HubSpot setup? Grab a time with me: {BOOKING_URL}"


def append_cta(text: str) -> str:
    """Return the post body with the scheduling CTA appended as a trailing block.

    Idempotent: if the booking link is already in the text (e.g. an approved or
    pre-written post that wrote it inline), the text is returned unchanged so we
    never double up the link."""
    if BOOKING_URL in text:
        return text
    return f"{text.rstrip()}\n\n{CTA}"
