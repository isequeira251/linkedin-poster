"""Append relevant HubSpot/RevOps hashtags to a finished LinkedIn post.

The ghostwriter (and any approved/pre-written copy) leaves the body hashtag-free;
this module owns hashtags so they live in exactly one place. Selection is
content-aware and deterministic: #HubSpot always anchors the set, then tags are
added by keyword-matching the post text, capped at MAX_HASHTAGS (LinkedIn's
sweet spot is 3-5). Anything already hashtagged in the body is respected and
never duplicated.

Library:
    from hashtags import append_hashtags, select_hashtags
    body = append_hashtags(post_text)     # body + "\n\n#HubSpot #RevOps ..."
    tags = select_hashtags(post_text)     # just the NEW tags it would add

CLI (preview what a note would get tagged with):
    python hashtags.py "We backfilled lead scoring after a dedup pass."
"""

from __future__ import annotations

import re
import sys

MAX_HASHTAGS = 5          # total tags on the post (existing in body + appended)
MIN_HASHTAGS = 3          # top up to this many with fillers when matches are thin

# Always present — the through-line for everything Ian posts.
BASE = ["#HubSpot"]

# Ordered by priority. Each tag is added when ANY of its keywords appears in the
# post (whole-word, case-insensitive). Keep keywords specific to avoid false hits.
RULES: list[tuple[str, list[str]]] = [
    ("#RevOps", ["revops", "revenue operations", "rev ops"]),
    ("#DataQuality", ["dedup", "duplicate", "duplicates", "data quality",
                      "hygiene", "dirty data", "merge", "merging", "clean data"]),
    ("#LeadScoring", ["lead scoring", "lead score", "scoring model", "lead scores"]),
    ("#MarketingAutomation", ["automation", "automate", "automated", "workflow",
                              "workflows", "sequence", "sequences"]),
    ("#SalesOps", ["pipeline", "deal stage", "deals", "forecast", "quota",
                   "sales team", "reps"]),
    ("#CRM", ["crm", "contact record", "records", "properties", "lifecycle",
              "lifecycle stage", "mql", "sql"]),
    ("#MarketingOps", ["campaign", "campaigns", "segment", "segmentation",
                       "marketing ops", "marketing team"]),
    ("#Analytics", ["report", "reports", "reporting", "dashboard", "dashboards",
                    "attribution", "metric", "metrics", "analytics"]),
    ("#Integrations", ["integration", "integrate", "sync", "syncing", "api",
                       "klaviyo", "kustomer", "acumatica", "salesforce"]),
    ("#AI", ["ai", "artificial intelligence", "llm", "machine learning",
             "ai agent", "prompt"]),
]

# Used to top the set up to MIN_HASHTAGS when keyword matches are sparse.
FILLERS = ["#RevOps", "#CRM", "#MarketingOps"]


def _existing(text: str) -> set[str]:
    """Lowercased set of hashtags already written into the body."""
    return {m.group(0).lower() for m in re.finditer(r"#\w+", text)}


def _matches(text: str, keyword: str) -> bool:
    """Whole-word, case-insensitive keyword match, so 'ai' hits the token "AI"
    but not 'email', and 'merge' doesn't fire inside 'emerge'."""
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text, re.IGNORECASE) is not None


def select_hashtags(text: str) -> list[str]:
    """Return the NEW hashtags to append (excludes any already in the body)."""
    have = _existing(text)
    chosen: list[str] = []

    def add(tag: str) -> None:
        if tag.lower() in have or tag in chosen:
            return
        if len(have) + len(chosen) >= MAX_HASHTAGS:
            return
        chosen.append(tag)

    for tag in BASE:
        add(tag)
    for tag, keywords in RULES:
        if len(have) + len(chosen) >= MAX_HASHTAGS:
            break
        if any(_matches(text, k) for k in keywords):
            add(tag)
    for tag in FILLERS:
        if len(have) + len(chosen) >= MIN_HASHTAGS:
            break
        add(tag)
    return chosen


def append_hashtags(text: str) -> str:
    """Return the post body with relevant hashtags appended as a trailing block.
    Idempotent-ish: tags already present in the body are never duplicated."""
    tags = select_hashtags(text)
    if not tags:
        return text
    return f"{text.rstrip()}\n\n{' '.join(tags)}"


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python hashtags.py "post text"', file=sys.stderr)
        return 1
    print(append_hashtags(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
