"""Turn a raw note into a finished LinkedIn post in Ian's voice.

Calls the Claude API (Anthropic SDK) with a ghostwriter system prompt and
returns the structured draft: candidate hooks, the finished post, and a
self-score the model rewrites against.

Library:
    from ghostwriter import generate_post
    draft = generate_post("raw note text")
    draft["post"]          # the finished post text to publish
    draft["hook_options"]  # list of candidate first lines it considered
    draft["self_score"]    # {"hook": n, "specificity": n, "human": n, "comment_bait": n}

CLI (draft/preview a single note without posting):
    python ghostwriter.py "Spent an hour untangling a lead-scoring model nobody trusted."

Requires ANTHROPIC_API_KEY in the environment. Model defaults to Opus 4.7
(best at matching voice; ~a fraction of a cent per post). Override with the
ANTHROPIC_MODEL env var, e.g. claude-sonnet-4-6.
"""

import json
import os
import sys

import anthropic
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "claude-opus-4-7"

# --- Voice profile -----------------------------------------------------------
# Edit these to retune who the ghostwriter writes as. Everything here flows
# into the system prompt below; keep it concrete and opinionated, not generic.
GHOSTWRITER_NAME = "Ian Sequeira"
GHOSTWRITER_ROLE = "HubSpot / CRM & marketing-ops consultant"

VOICE = """\
- Point of view — opinions Ian actually holds:
    * Most "CRM problems" are definition problems, not tool problems.
    * Good automation is invisible. If it feels automated, it's bad.
    * RevOps is plumbing, not strategy theater — the unglamorous work is the work.
    * AI on a dirty CRM doesn't fix the mess, it scales it. A model is only ever
      as good as the records under it.
    * The fix for a CRM problem is rarely another tool. It's usually a
      definition, an owner, or a deletion.
- Tone: direct, dry, no fluff, lightly contrarian. Sounds like someone who has
  cleaned up the mess, not someone selling the dream.
- Writes like a practitioner, not a marketer. Uses lifecycle stages, workflows,
  properties, lead scoring, dedup, attribution, and permissions naturally and
  correctly — never as buzzwords.
- Never sounds like: a motivational coach, a press release, or a "thought leader\"."""

SYSTEM_PROMPT = f"""\
You are a LinkedIn ghostwriter for {GHOSTWRITER_NAME}, a {GHOSTWRITER_ROLE}. You
turn raw notes into posts that sound like them and earn genuine engagement.

<voice>
{VOICE}
</voice>

<rules>
- One idea per post. If the input has several, pick the sharpest, drop the rest.
- The first line is everything — it must hook as a standalone before the
  "...more" cutoff. Specific or contrarian, never a throat-clear.
- Open with a concrete scene, number, or claim. No "In today's world."
- Short lines, white space between thoughts, scannable on a phone.
- Teach one usable thing OR stake one real opinion — something the reader can
  act on or argue with.
- Length 600-1,300 characters. No links in the body. Do NOT add hashtags —
  relevant HubSpot hashtags are appended automatically after generation.
- Close in two beats. First, ONE engagement driver: a genuine question or an
  invitation to disagree (never "Agree?" or "Thoughts?"). Then a final,
  deliberately understated one-line sign-off that invites a DM, in the spirit
  of "DM me if you want a hand with a project or have a question," reworded
  every time to fit the post. Keep it low-key and human: never a salesy CTA,
  never the same phrasing twice, never a templated footer.
</rules>

<avoid>
AI tells — never produce: em-dash overuse, "it's not just X, it's Y," "let's
dive in," "the truth is," rhetorical-question stacking, listicle cadence, hollow
inspirational closers, buzzwords with no concrete referent.
</avoid>

<process>
1. Find the single sharpest idea in the input.
2. Draft 4 hook options. Pick the most specific/contrarian.
3. Write the post.
4. Confirm it ends with the engagement driver followed by the subtle DM
   sign-off; if either is missing, revise before scoring.
5. Score 1-10 on: hook strength, specificity, sounds-human, reason-to-comment.
   Rewrite anything below 8.
</process>

Return the four hook options you considered, the finished post, and your
self-scores."""

# Structured-output schema: guarantees parseable JSON back from the model.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "hook_options": {"type": "array", "items": {"type": "string"}},
        "post": {"type": "string"},
        "self_score": {
            "type": "object",
            "properties": {
                "hook": {"type": "integer"},
                "specificity": {"type": "integer"},
                "human": {"type": "integer"},
                "comment_bait": {"type": "integer"},
            },
            "required": ["hook", "specificity", "human", "comment_bait"],
            "additionalProperties": False,
        },
    },
    "required": ["hook_options", "post", "self_score"],
    "additionalProperties": False,
}


def _model_extras(model: str) -> dict:
    """Adaptive thinking and the effort parameter are only valid on newer
    models. Gate them so switching ANTHROPIC_MODEL to Haiku/older doesn't 400."""
    extras: dict = {}
    if any(m in model for m in ("opus-4-5", "opus-4-6", "opus-4-7", "sonnet-4-6")):
        extras["effort"] = "high"
    if any(m in model for m in ("opus-4-6", "opus-4-7", "sonnet-4-6")):
        extras["thinking"] = {"type": "adaptive"}
    return extras


def generate_post(raw_input: str, *, model: str | None = None) -> dict:
    """Generate a LinkedIn post draft from a raw note. Returns a dict with
    keys: hook_options (list[str]), post (str), self_score (dict)."""
    # `or`-chain (not get's default) so an empty ANTHROPIC_MODEL — what an unset
    # GitHub Actions variable expands to — still falls back to DEFAULT_MODEL.
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    extras = _model_extras(model)
    output_config: dict = {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
    if "effort" in extras:
        output_config["effort"] = extras["effort"]

    kwargs: dict = {
        "model": model,
        "max_tokens": 8000,
        # Frozen prefix — marked cacheable so back-to-back generations (e.g.
        # batch-filling notes) reuse it; harmless when it can't (daily cadence).
        "system": [{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        "output_config": output_config,
        "messages": [{
            "role": "user",
            "content": (
                f"Raw material from {GHOSTWRITER_NAME} — a note, a story, an "
                f"observation:\n\n{raw_input.strip()}"
            ),
        }],
    }
    if "thinking" in extras:
        kwargs["thinking"] = extras["thinking"]

    response = client.messages.create(**kwargs)

    if response.stop_reason == "refusal":
        raise RuntimeError("Model refused to generate this post.")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError(f"No text block in response (stop_reason={response.stop_reason}).")
    return json.loads(text)


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python ghostwriter.py "raw note text"', file=sys.stderr)
        return 1
    draft = generate_post(sys.argv[1])
    print(json.dumps(draft, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
