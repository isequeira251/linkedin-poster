"""Read human-approved LinkedIn posts from Gmail.

The LinkedIn Draft Agent (a scheduled remote agent, separate repo) leaves
candidate posts as Gmail drafts addressed to the +linkedin alias. Ian approves
one by editing it and hitting Send. This module reads those *sent* messages over
IMAP so daily_runner.py can publish an approved post ahead of the auto-generated
notes pool.

"Approved and unposted" = a message you sent to the +linkedin alias whose
Message-ID daily_runner hasn't already recorded in posts.json. We dedupe on
Message-ID (tracked in posts.json) rather than a Gmail flag, so a failed publish
is safely retried and nothing depends on IMAP label state.

Env vars (set as GitHub Actions secrets on this repo):
    GMAIL_ADDRESS        the inbox to read, e.g. sequeiri@gmail.com
    GMAIL_APP_PASSWORD   a Gmail app password (same kind the digests use)
    APPROVAL_ALIAS       optional; defaults to "<local>+linkedin@<domain>"
                         derived from GMAIL_ADDRESS

No external deps — imaplib and email are stdlib.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
from email.utils import parsedate_to_datetime

IMAP_HOST = "imap.gmail.com"
_SIG_MARKERS = ("\n-- \n", "\nSent from ", "\nGet Outlook")


def _approval_alias() -> str:
    explicit = os.environ.get("APPROVAL_ALIAS")
    if explicit:
        return explicit
    local, _, domain = os.environ["GMAIL_ADDRESS"].partition("@")
    return f"{local}+linkedin@{domain}"


def _plaintext(msg: email.message.Message) -> str:
    """Pull the text/plain body out of a (possibly multipart) message."""
    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get("Content-Disposition", ""))
            if part.get_content_type() == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", "replace")


def _clean_body(raw: str) -> str:
    """Trim a trailing signature or quoted reply if one slipped into the send."""
    text = raw.replace("\r\n", "\n").strip()
    cut = len(text)
    for marker in _SIG_MARKERS:
        i = text.find(marker)
        if i != -1:
            cut = min(cut, i)
    quoted = re.search(r"\nOn .+wrote:\n", text)
    if quoted:
        cut = min(cut, quoted.start())
    return text[:cut].strip()


def fetch_oldest_approved(exclude_message_ids: set[str]) -> tuple[str, str] | None:
    """Return (message_id, post_text) for the oldest approved-but-unposted post,
    or None. Approved = you sent it to the +linkedin alias; unposted = its
    Message-ID is not in exclude_message_ids."""
    alias = _approval_alias()
    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        mail.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        mail.select('"[Gmail]/All Mail"', readonly=True)
        # Gmail raw search: sent by me, to the alias, not a draft/spam/trash.
        query = f"from:me to:{alias} -in:drafts -in:spam -in:trash"
        typ, data = mail.uid("SEARCH", None, "X-GM-RAW", f'"{query}"')
        if typ != "OK" or not data or not data[0]:
            return None

        candidates: list[tuple] = []
        for uid in data[0].split():
            typ, mdata = mail.uid("FETCH", uid, "(RFC822)")
            if typ != "OK" or not mdata or not mdata[0]:
                continue
            msg = email.message_from_bytes(mdata[0][1])
            mid = (msg.get("Message-ID") or "").strip()
            if not mid or mid in exclude_message_ids:
                continue
            body = _clean_body(_plaintext(msg))
            if not body:
                continue
            try:
                dt = parsedate_to_datetime(msg.get("Date"))
            except (TypeError, ValueError):
                dt = None
            candidates.append((dt, mid, body))

        if not candidates:
            return None
        # Oldest first; messages with an unparseable date sort last.
        candidates.sort(key=lambda c: (c[0] is None, c[0]))
        _, mid, body = candidates[0]
        return mid, body
    finally:
        try:
            mail.logout()
        except Exception:
            pass
