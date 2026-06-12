#!/usr/bin/env python3
"""Generate narration audio per scene with edge-tts (Shorts pipeline).

Usage: python3 shorts/pipeline/tts.py <slug>
Reads  shorts/videos/<slug>/script.json
Writes shorts/out/<slug>/audio/scene_NN.mp3 and durations.json

Retries a scene once if the produced audio is implausibly short for its
word count (edge-tts occasionally truncates a stream mid-sentence).
"""
import asyncio, json, subprocess, sys
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parent.parent  # shorts/
DEFAULT_VOICE = "en-US-AndrewNeural"
DEFAULT_RATE = "+10%"
MIN_SECONDS_PER_WORD = 0.18  # ~330 wpm ceiling; below this = truncated stream


def probe_duration(p: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


async def synth(text: str, voice: str, rate: str, mp3: Path) -> float:
    await edge_tts.Communicate(text, voice, rate=rate).save(str(mp3))
    return probe_duration(mp3)


async def main(slug: str) -> None:
    script = json.loads((ROOT / "videos" / slug / "script.json").read_text())
    audio_dir = ROOT / "out" / slug / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    rate = script.get("rate", DEFAULT_RATE)

    durations = {}
    for i, scene in enumerate(script["scenes"]):
        tag = f"{i:02d}"
        mp3 = audio_dir / f"scene_{tag}.mp3"
        voice = scene.get("voice", script.get("voice", DEFAULT_VOICE))
        text = scene["narration"]
        floor = len(text.split()) * MIN_SECONDS_PER_WORD
        dur = await synth(text, voice, rate, mp3)
        if dur < floor:  # truncated — retry once
            print(f"scene_{tag}: {dur:.1f}s < {floor:.1f}s floor, retrying TTS")
            dur = await synth(text, voice, rate, mp3)
            if dur < floor:
                sys.exit(f"scene_{tag}: TTS truncated twice ({dur:.1f}s)")
        durations[tag] = dur
        print(f"scene_{tag}.mp3  {dur:.1f}s")

    (audio_dir / "durations.json").write_text(json.dumps(durations, indent=2))
    print(f"total narration: {sum(durations.values()):.1f}s")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: tts.py <slug>")
    asyncio.run(main(sys.argv[1]))
