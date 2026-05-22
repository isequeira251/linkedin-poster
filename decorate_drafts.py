"""Attach a generated card to each pending LinkedIn draft.

The LinkedIn Draft Agent (a cloud routine) leaves text-only Gmail drafts with
subjects like "LI POST — … [id]". This job — run on GitHub Actions shortly
after — renders the card with generate_card.py and swaps each text-only draft
for one with the card attached, so Ian can review the visual before approving.
The publisher (daily_runner.py) then posts that exact attached card.

IMAP messages are immutable, so "swap" means: APPEND a new multipart draft
(plain-text post + PNG attachment) to [Gmail]/Drafts, then delete the original.
Idempotent: a draft that already carries an image is left alone.

Env (GitHub Actions secrets on this repo):
    GMAIL_ADDRESS, GMAIL_APP_PASSWORD   the same inbox/app password the poster reads
    PEXELS_API_KEY                       optional, used by generate_card.py

No external deps beyond what generate_card.py already needs (Pillow, requests).
"""

from __future__ import annotations

import imaplib
import os
import sys
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from approved_inbox import _approval_alias, _plaintext
from generate_card import generate_card

IMAP_HOST = "imap.gmail.com"
DRAFTS = '"[Gmail]/Drafts"'


def _has_image(msg) -> bool:
    if not msg.is_multipart():
        return False
    return any(p.get_content_type().startswith("image/") for p in msg.walk())


def main() -> int:
    if not os.environ.get("GMAIL_APP_PASSWORD"):
        print("GMAIL_APP_PASSWORD not set — skipping draft decoration.")
        return 0

    import email  # local import keeps the module importable for unit tests

    address = os.environ["GMAIL_ADDRESS"]
    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    decorated = 0
    try:
        mail.login(address, os.environ["GMAIL_APP_PASSWORD"])
        mail.select(DRAFTS, readonly=False)
        # The quotes around the value matter: an unquoted "LI POST" parses as two
        # IMAP tokens and the server rejects the command (BAD).
        typ, data = mail.uid("SEARCH", None, "HEADER", "SUBJECT", '"LI POST"')
        if typ != "OK" or not data or not data[0]:
            print("No LI POST drafts to decorate.")
            return 0

        to_delete: list[bytes] = []
        for uid in data[0].split():
            typ, mdata = mail.uid("FETCH", uid, "(RFC822)")
            if typ != "OK" or not mdata or not mdata[0]:
                continue
            msg = email.message_from_bytes(mdata[0][1])
            subject = (msg.get("Subject") or "").strip()
            if _has_image(msg):
                print(f"skip (already carded): {subject[:60]}")
                continue
            body = _plaintext(msg).strip()
            if not body:
                print(f"skip (no body): {subject[:60]}")
                continue
            to_addr = (msg.get("To") or "").strip() or _approval_alias()

            try:
                card = generate_card(body)
            except Exception as e:  # never let one bad card abort the batch
                print(f"WARN: card generation failed for {subject[:50]!r}: {e}", file=sys.stderr)
                continue

            out = MIMEMultipart()
            out["From"] = address
            out["To"] = to_addr
            out["Subject"] = subject
            out.attach(MIMEText(body, "plain", "utf-8"))
            img = MIMEImage(card, _subtype="png")
            img.add_header("Content-Disposition", "attachment", filename="card.png")
            out.attach(img)

            res, _ = mail.append(DRAFTS, "(\\Draft)", None, out.as_bytes())
            if res != "OK":
                print(f"WARN: append failed for {subject[:50]!r}", file=sys.stderr)
                continue
            to_delete.append(uid)
            decorated += 1
            print(f"carded: {subject[:60]}")

        if to_delete:
            for uid in to_delete:
                mail.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            mail.expunge()
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    print(f"Decorated {decorated} draft(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
