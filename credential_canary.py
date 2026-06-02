#!/usr/bin/env python3
"""Credential canary — warn BEFORE an expiring secret silently breaks automation.

Three of Ian's automations die quietly when a credential lapses:
  - LinkedIn access token (hard ~60-day expiry) → linkedin-poster stops posting.
  - Gmail app password (breaks on any Google password change) → every SMTP
    sender 535s: both portal digests, the email-assistant bridge, this canary.
  - GitHub fine-grained PAT (~90-day expiry) → the workflow-health monitor 401s.

This script tests each credential it can see and emails Ian ONLY when something
is already failing or within WARN_DAYS of expiry. Silence means healthy.

Layering: it emails via Gmail SMTP, so if the Gmail password itself is dead it
can't send the warning — in that case it exits non-zero so the existing
workflow-health monitor flags this run as ❌ and Ian still hears about it.

Credentials whose env vars are absent are skipped (graceful), so the same script
runs anywhere; richer checks just light up when more secrets are provided.

pip install: requests   (smtp/email/json are stdlib)

Env:
  LINKEDIN_ACCESS_TOKEN              required for the LinkedIn check
  LINKEDIN_CLIENT_ID / _SECRET       optional — enables proactive expiry (introspection)
  GMAIL_ADDRESS / GMAIL_APP_PASSWORD required for the Gmail check + to send alerts
  GH_MONITOR_TOKEN                   optional — enables the GitHub PAT expiry check
  MONITOR_RECIPIENT                  where to mail alerts (default: +canary alias of sender)
  WARN_DAYS                          days-to-expiry that trips a warning (default 7)
  DRY_RUN=1                          print instead of sending
"""

import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage

import requests

LINKEDIN_TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN")
LINKEDIN_CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID")
LINKEDIN_CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET")
GH_TOKEN = os.environ.get("GH_MONITOR_TOKEN")
SENDER = os.environ.get("GMAIL_ADDRESS", "sequeiri@gmail.com")
PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
# To != From so Gmail delivers it unread (a self-addressed mail lands in Sent).
RECIPIENT = os.environ.get("MONITOR_RECIPIENT") or SENDER.replace("@", "+canary@", 1)
WARN_DAYS = float(os.environ.get("WARN_DAYS", "7"))
DRY_RUN = os.environ.get("DRY_RUN") == "1"

NOW = datetime.now(timezone.utc)


def log(msg):
    print(msg, file=sys.stderr)


def days_until(dt):
    return (dt - NOW).total_seconds() / 86400


def fmt_days(d):
    if d < 1:
        return f"{d * 24:.0f}h"
    return f"{d:.0f}d"


# Each check returns (emoji, alert?, headline, detail). alert=True means it goes
# in the email and counts as a problem. Gmail is special-cased in main().


def check_linkedin():
    """Validity always; proactive expiry when client creds are available."""
    if not LINKEDIN_TOKEN:
        return ("⚪", False, "LinkedIn token", "skipped — LINKEDIN_ACCESS_TOKEN not set")

    # Proactive: introspection returns the token's real expires_at.
    if LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET:
        try:
            r = requests.post(
                "https://www.linkedin.com/oauth/v2/introspectToken",
                data={
                    "token": LINKEDIN_TOKEN,
                    "client_id": LINKEDIN_CLIENT_ID,
                    "client_secret": LINKEDIN_CLIENT_SECRET,
                },
                timeout=30,
            )
            r.raise_for_status()
            info = r.json()
            if info.get("active") is False or info.get("status") == "expired":
                return ("❌", True, "LinkedIn token", "EXPIRED/revoked — re-run linkedin_auth.py")
            exp = info.get("expires_at")
            if exp:
                left = days_until(datetime.fromtimestamp(int(exp), timezone.utc))
                if left <= WARN_DAYS:
                    return ("⏰", True, "LinkedIn token",
                            f"expires in {fmt_days(left)} — re-auth soon (linkedin_auth.py)")
                return ("✅", False, "LinkedIn token", f"valid, {fmt_days(left)} left")
            return ("✅", False, "LinkedIn token", "active (no expiry returned)")
        except Exception as e:  # introspection failed → fall through to validity ping
            log(f"  LinkedIn introspection failed, falling back to validity: {e}")

    # Reactive: a plain authenticated call. 401 == dead token.
    try:
        r = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {LINKEDIN_TOKEN}"},
            timeout=30,
        )
        if r.status_code == 401:
            return ("❌", True, "LinkedIn token", "401 — EXPIRED/invalid, re-run linkedin_auth.py")
        r.raise_for_status()
        return ("✅", False, "LinkedIn token",
                "valid (no expiry visible — add LINKEDIN_CLIENT_ID/SECRET for countdown)")
    except Exception as e:
        return ("❌", True, "LinkedIn token", f"check failed: {e}")


def check_github():
    """GitHub fine-grained PATs expose expiry via a response header."""
    if not GH_TOKEN:
        return ("⚪", False, "GitHub PAT", "skipped — GH_MONITOR_TOKEN not set in this repo")
    try:
        r = requests.get(
            "https://api.github.com/rate_limit",
            headers={"Authorization": f"Bearer {GH_TOKEN}",
                     "X-GitHub-Api-Version": "2022-11-28"},
            timeout=30,
        )
        if r.status_code == 401:
            return ("❌", True, "GitHub PAT", "401 — EXPIRED/revoked, regenerate the fine-grained PAT")
        r.raise_for_status()
        exp = r.headers.get("github-authentication-token-expiration")
        if exp:
            # Header looks like "2026-08-19 12:00:00 UTC" or ISO; handle both.
            raw = exp.replace(" UTC", "+00:00").replace(" ", "T", 1)
            try:
                left = days_until(datetime.fromisoformat(raw))
                if left <= WARN_DAYS:
                    return ("⏰", True, "GitHub PAT", f"expires in {fmt_days(left)} — regenerate soon")
                return ("✅", False, "GitHub PAT", f"valid, {fmt_days(left)} left")
            except ValueError:
                return ("✅", False, "GitHub PAT", f"valid (expires {exp})")
        return ("✅", False, "GitHub PAT", "valid (classic/no-expiry token)")
    except Exception as e:
        return ("❌", True, "GitHub PAT", f"check failed: {e}")


def check_gmail():
    """SMTP login only — no message sent. Returns ok flag separately so main()
    can fall back to a non-zero exit when Gmail (our own send path) is down."""
    if not PASSWORD:
        return ("⚪", False, "Gmail app pw", "skipped — GMAIL_APP_PASSWORD not set", False)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(SENDER, PASSWORD)
        return ("✅", False, "Gmail app pw", "SMTP login ok", True)
    except smtplib.SMTPAuthenticationError:
        return ("❌", True, "Gmail app pw",
                "535 auth failed — rotate GMAIL_APP_PASSWORD (breaks digests + bridges)", False)
    except Exception as e:
        return ("❌", True, "Gmail app pw", f"SMTP check failed: {e}", False)


def render_html(rows):
    items = "".join(
        f"<tr><td style='padding:4px 10px;font-size:18px'>{e}</td>"
        f"<td style='padding:4px 10px;font-weight:600'>{h}</td>"
        f"<td style='padding:4px 10px;color:#444'>{d}</td></tr>"
        for e, _, h, d in rows
    )
    return (
        "<div style='font-family:system-ui,Arial,sans-serif'>"
        "<h2 style='margin:0 0 4px'>🐤 Credential canary</h2>"
        f"<p style='color:#666;margin:0 0 12px'>Checked {NOW:%Y-%m-%d %H:%M UTC} · "
        f"warns within {WARN_DAYS:.0f} days of expiry</p>"
        f"<table style='border-collapse:collapse'>{items}</table></div>"
    )


def send(subject, html):
    if DRY_RUN or not PASSWORD:
        if not PASSWORD and not DRY_RUN:
            log("GMAIL_APP_PASSWORD not set — cannot send; printing.")
        print(f"Subject: {subject}\n")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SENDER
    msg["To"] = RECIPIENT
    msg.set_content("This email is HTML. View it in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")
    log(f"Sending to {RECIPIENT} (from {SENDER})…")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(SENDER, PASSWORD)
        s.send_message(msg)
    log("Sent.")


def main():
    li = check_linkedin()
    gh = check_github()
    em, alert, head, detail, gmail_ok = check_gmail()
    gmail = (em, alert, head, detail)

    rows = [li, gh, gmail]
    for e, _, h, d in rows:
        log(f"  {e} {h} — {d}")

    alerts = [r for r in rows if r[1]]

    # If Gmail itself is down we can't email — exit non-zero so the
    # workflow-health monitor catches this run as ❌ failed.
    if not gmail_ok and PASSWORD is not None:
        log("Gmail send path is down — exiting non-zero so the monitor flags it.")
        sys.exit(1)

    if not alerts:
        log("All credentials healthy — no email sent.")
        return

    heads = ", ".join(r[2] for r in alerts)
    subject = f"🐤 Credential canary: {len(alerts)} need attention — {heads}"
    send(subject, render_html(rows))


if __name__ == "__main__":
    main()
