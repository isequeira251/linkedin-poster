#!/usr/bin/env python3
"""Post-publish step: turn today's LinkedIn post into a YouTube Short and
drop the link as the post's first comment.

Runs in daily-post.yml AFTER daily_runner.py and BEFORE the commit step.
Writes short_video_id / short_url into today's posts.json entry (picked up
by the existing `git add posts.json` commit).

Design rule: this script NEVER exits non-zero. A Shorts failure must not
fail the daily-post job (the LinkedIn post already went out and posts.json
must still be committed for idempotency). Errors are emailed instead.
"""
import json
import os
import smtplib
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHORTS = REPO / "shorts"
MIN_S, MAX_S = 20, 59  # final mp4 duration bounds (Shorts must be <60s)


def email(subject: str, body: str) -> None:
    addr = os.environ.get("GMAIL_ADDRESS")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not (addr and pw):
        print(f"[email skipped] {subject}\n{body}")
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = addr
    msg["To"] = addr
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(addr, pw)
        s.send_message(msg)


def run(cmd: list[str]) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=REPO)


def probe_duration(p: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def todays_entry(posts: list[dict]) -> dict | None:
    today = datetime.now(timezone.utc).date().isoformat()
    for p in posts:
        if p.get("posted") and str(p.get("posted_at", ""))[:10] == today:
            return p
    return None


def _slug_today() -> str:
    return f"short-{datetime.now(timezone.utc).date().isoformat()}"


def plan_pre_post(post_text: str) -> bool:
    """Pre-post hook for daily_runner: run the gate + script generation BEFORE
    the LinkedIn post goes out, so the post body can carry a "video in the
    comments" teaser only on days a video is actually coming.

    Saves script.json (or a SKIP marker) for main() to reuse — same workflow
    job, same workspace. Returns True when a video is coming.
    """
    sys.path.insert(0, str(SHORTS))
    from generate_script import generate
    vdir = SHORTS / "videos" / _slug_today()
    vdir.mkdir(parents=True, exist_ok=True)
    script = generate(post_text)
    if script is None:
        (vdir / "SKIP").write_text("quality gate")
        return False
    (vdir / "script.json").write_text(json.dumps(script, indent=2))
    return True


def main() -> None:
    if not os.environ.get("YT_REFRESH_TOKEN"):
        print("YT_REFRESH_TOKEN not set — Shorts step disabled, skipping.")
        return

    posts_path = REPO / "posts.json"
    posts = json.loads(posts_path.read_text())
    entry = todays_entry(posts)
    if entry is None:
        print("no post published today — nothing to do.")
        return
    if entry.get("short_video_id"):
        print(f"Short already exists for today: {entry['short_video_id']}")
        return

    post_text = entry.get("posted_text") or entry.get("text") or ""
    post_urn = entry.get("post_id", "")
    if not post_text or not post_urn:
        print("today's entry missing posted_text/post_id — skipping.")
        return

    slug = _slug_today()
    vdir = SHORTS / "videos" / slug
    spath = vdir / "script.json"
    if (vdir / "SKIP").exists():
        # pre-post gate already said no — don't second-guess it (the post
        # carries no teaser, so a surprise video would be inconsistent)
        print("pre-post gate skipped this post.")
        entry["short_skipped"] = "quality gate"
        posts_path.write_text(json.dumps(posts, indent=2))
        return
    if spath.exists():
        script = json.loads(spath.read_text())
        print("reusing pre-post script.json")
    else:
        from generate_script import generate  # noqa: E402 (sys.path set in __main__)
        script = generate(post_text)
        if script is None:
            entry["short_skipped"] = "quality gate"
            posts_path.write_text(json.dumps(posts, indent=2))
            return
        vdir.mkdir(parents=True, exist_ok=True)
        spath.write_text(json.dumps(script, indent=2))

    run([sys.executable, str(SHORTS / "pipeline" / "tts.py"), slug])
    run(["node", str(SHORTS / "pipeline" / "render.js"), slug])
    run([sys.executable, str(SHORTS / "pipeline" / "assemble.py"), slug])

    mp4 = SHORTS / "out" / slug / f"{slug}.mp4"
    dur = probe_duration(mp4)
    if not MIN_S <= dur <= MAX_S:
        raise RuntimeError(f"final duration {dur:.1f}s outside {MIN_S}-{MAX_S}s — not uploading")

    from upload_youtube import upload  # noqa: E402
    video_id = upload(mp4, script["meta"]["youtubeTitle"],
                      script["meta"]["description"], script["meta"]["tags"])
    short_url = f"https://youtube.com/shorts/{video_id}"

    from comment_link import post_comment  # noqa: E402
    post_comment(post_urn, f"🎥 The 60-second video version: {short_url}")

    entry["short_video_id"] = video_id
    entry["short_url"] = short_url
    posts_path.write_text(json.dumps(posts, indent=2))

    email(f"Short published: {script['meta']['youtubeTitle']}",
          f"{short_url}\n\nDuration: {dur:.0f}s\nLinked as first comment on {post_urn}\n\n"
          f"From this morning's post:\n{post_text[:500]}")
    print(f"done: {short_url} ({dur:.1f}s)")


if __name__ == "__main__":
    sys.path.insert(0, str(SHORTS))
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        try:
            email("Shorts pipeline FAILED (LinkedIn post is fine)", tb)
        except Exception as mail_err:  # truly nothing left to do
            print(f"error email also failed: {mail_err}", file=sys.stderr)
        # never fail the daily-post job — see module docstring
        sys.exit(0)
