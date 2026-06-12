#!/usr/bin/env python3
"""Mux scene videos with narration audio and concat into the final Short mp4.

Usage: python3 shorts/pipeline/assemble.py <slug>
Reads  shorts/out/<slug>/scenes/scene_NN.webm + shorts/out/<slug>/audio/scene_NN.mp3
Writes shorts/out/<slug>/<slug>.mp4
"""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # shorts/
PAD_S = 0.6  # keep in sync with PAD_MS in render.js


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def main(slug: str) -> None:
    out = ROOT / "out" / slug
    durations = json.loads((out / "audio" / "durations.json").read_text())
    seg_dir = out / "segments"
    seg_dir.mkdir(exist_ok=True)

    segments = []
    for tag in sorted(durations):
        webm = out / "scenes" / f"scene_{tag}.webm"
        mp3 = out / "audio" / f"scene_{tag}.mp3"
        seg = seg_dir / f"seg_{tag}.mp4"
        dur = durations[tag] + PAD_S
        run([
            "ffmpeg", "-y", "-i", str(webm), "-i", str(mp3),
            "-filter_complex", "[1:a]apad[a]",
            "-map", "0:v", "-map", "[a]", "-t", f"{dur:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-r", "30", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
            str(seg),
        ])
        segments.append(seg)
        print(f"seg_{tag}.mp4  {dur:.1f}s")

    concat_list = seg_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{s}'\n" for s in segments))
    final = out / f"{slug}.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(final)])
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(final)], capture_output=True, text=True)
    print(f"final: {final}  ({float(probe.stdout):.1f}s)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: assemble.py <slug>")
    main(sys.argv[1])
