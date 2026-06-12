#!/usr/bin/env python3
"""Turn a published LinkedIn post into a YouTube Short script via Claude.

Called by make_short.py. Returns a dict (the script.json content) or None
when the post doesn't carry a concrete, visual concept worth a video —
forcing weak posts into Shorts hurts the channel more than skipping a day.

Description is assembled programmatically (not by the model) so the booking
link is always present and no AI/meta language can leak in.
"""
import json
import os
import re

import anthropic

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
BOOKING_LINE = "📅 Book a HubSpot consulting call: https://calendar.app.google/Hnb4hjABXYCWmx8N7"
HASHTAG_LINE = "#HubSpot #RevOps #CRM #Shorts"
ALLOWED_TEMPLATES = {"title", "outro", "bullets", "code", "diagram", "ui"}

PROMPT = """You write scripts for "Portal Ops", a faceless YouTube Shorts channel by a HubSpot consultant. Today's LinkedIn post (already published, written in his voice) is below. Decide whether it carries ONE concrete, easy-to-visualize concept, and if so, retell it as a vertical Short script.

SKIP CRITERIA — respond {{"skip": true, "reason": "<one line>"}} if the post is: abstract philosophy with no concrete scenario, a listicle of more than 3 unrelated tips, pure self-promotion, or otherwise lacks a single visual "aha". Be honest; a skipped day is fine.

LINKEDIN POST:
---
{post_text}
---

If it qualifies, respond with ONLY this JSON (no markdown fences):
{{
  "skip": false,
  "youtubeTitle": "<≤95 chars, curiosity hook, no hashtags>",
  "descriptionHook": "<2 punchy sentences about the takeaway>",
  "scenes": [ ... 2-3 scenes ... ]
}}

HARD CONSTRAINTS:
- TOTAL narration across all scenes: 110-145 words (≈45-52s spoken). Count carefully.
- First narration sentence is the hook — no warmup, no greetings.
- First person, dry confident practitioner voice matching the post. No hype words.
- Final scene narration ends with a short follow nudge (one clause, e.g. "Follow for more HubSpot fixes.").

SCENE TEMPLATES (vertical 1080x1920 layout):
- {{"template":"title","kicker":"...","title":"...","subtitle":"...","narration":"..."}} — big centered text
- {{"template":"bullets","title":"...","bullets":["...<strong>bold</strong> ok..."],"narration":"..."}} — max 3 short bullets
- {{"template":"diagram","title":"...","boxes":[{{"title":"...","detail":"...","accent":true}}],"narration":"..."}} — max 3 boxes, stacked vertically
- {{"template":"ui","title":"...","subtitle":"...","columns":[...],"rows":[["cell","<span class='pill warn'>text</span>"]],"actions":[{{"at":0.3,"type":"highlight","sel":"#row-0"}},{{"at":0.7,"type":"modal","title":"...","body":["..."],"primary":"..."}}],"narration":"..."}} — fake CRM table; max 3 columns / 4 rows; pills: ok/warn/info; action types: cursor/highlight/click/modal/closeModal with "at" as 0-1 fraction
- {{"template":"code","title":"...","file":"...","code":"...","narration":"..."}} — typed text box, ≤12 lines, ≤40 chars/line

Use simulated example data only (fake names/companies), never anything that looks like real client data."""


def _validate(data: dict) -> str | None:
    """Return an error string, or None if the script is usable."""
    if not isinstance(data.get("scenes"), list) or not 1 <= len(data["scenes"]) <= 4:
        return "scenes must be a list of 1-4 entries"
    words = 0
    for i, sc in enumerate(data["scenes"]):
        if sc.get("template") not in ALLOWED_TEMPLATES:
            return f"scene {i}: unknown template {sc.get('template')!r}"
        if not isinstance(sc.get("narration"), str) or not sc["narration"].strip():
            return f"scene {i}: missing narration"
        words += len(sc["narration"].split())
    if not 90 <= words <= 160:
        return f"total narration {words} words, need 110-145"
    title = data.get("youtubeTitle", "")
    if not title or len(title) > 100 or "#" in title:
        return "youtubeTitle missing, >100 chars, or contains a hashtag"
    if not data.get("descriptionHook"):
        return "descriptionHook missing"
    return None


def generate(post_text: str) -> dict | None:
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": PROMPT.format(post_text=post_text)}]
    for attempt in range(2):
        resp = client.messages.create(model=MODEL, max_tokens=3000, messages=messages)
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            err = f"invalid JSON: {e}"
            data = None
        if data is not None:
            if data.get("skip"):
                print(f"script gate: SKIP — {data.get('reason', 'no reason given')}")
                return None
            err = _validate(data)
            if err is None:
                break
        print(f"script attempt {attempt + 1} rejected: {err}")
        if attempt == 1:
            raise ValueError(f"script generation failed twice: {err}")
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"Fix this and resend the full JSON only: {err}"}]

    # description assembled here — booking link guaranteed, no model freelancing
    hook = data["descriptionHook"].strip()
    description = f"{hook}\n\n{BOOKING_LINE}\n\n{HASHTAG_LINE}"
    return {
        "title": data["youtubeTitle"],
        "format": "short",
        "rate": "+10%",
        "voice": "en-US-AndrewNeural",
        "meta": {
            "youtubeTitle": data["youtubeTitle"],
            "description": description,
            "tags": ["hubspot", "hubspot admin", "revops", "crm", "hubspot tutorial",
                     "sales operations", "hubspot tips", "shorts"],
        },
        "scenes": data["scenes"],
    }
