#!/usr/bin/env python3
"""Manual smoke test: text in (POST_TEXT env) -> private Short on the channel.

No LinkedIn calls, no posts.json writes. Fails loudly (unlike make_short.py)
so problems surface in the workflow run.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SHORTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SHORTS))

from generate_script import generate  # noqa: E402
from upload_youtube import upload  # noqa: E402


def run(cmd):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


def main():
    text = os.environ["POST_TEXT"]
    script = generate(text)
    if script is None:
        print("quality gate skipped this text — try a more concrete post")
        return

    slug = f"smoke-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
    vdir = SHORTS / "videos" / slug
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "script.json").write_text(json.dumps(script, indent=2))

    run([sys.executable, str(SHORTS / "pipeline" / "tts.py"), slug])
    run(["node", str(SHORTS / "pipeline" / "render.js"), slug])
    run([sys.executable, str(SHORTS / "pipeline" / "assemble.py"), slug])

    mp4 = SHORTS / "out" / slug / f"{slug}.mp4"
    video_id = upload(mp4, f"[SMOKE] {script['meta']['youtubeTitle']}",
                      script["meta"]["description"], script["meta"]["tags"],
                      privacy="private")
    print(f"SMOKE OK: https://youtube.com/shorts/{video_id} (private — delete after review)")


if __name__ == "__main__":
    main()
