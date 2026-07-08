"""
Thin wrapper around a locally-run Ollama model. Zero cost: no API key, no
per-token billing, everything runs on the user's own machine.

Three jobs only, kept deliberately narrow because small local models are far
more reliable on narrow, templated tasks than on open-ended instruction
following:
  1. generate_post   - the only open-ended writing step
  2. revise          - a fixed menu of templated edit verbs, not freeform edits
  3. distill_style   - proposes an Auto-Observed Patterns rewrite from the
                        pinned corpus (never applied without approval)
"""
import json
import re

import requests

REVISION_VERBS = {
    "tighten": "Cut this by roughly a third. Remove hedging, filler, and repeated points. Keep every distinct claim.",
    "expand": "Expand this with one more layer of reasoning or a concrete example per section. Keep the same voice.",
    "redo-opening": "Rewrite only the opening 2-3 sentences so the position/claim is stated immediately, no throat-clearing. Leave everything after that unchanged.",
    "more-technical": "Raise the technical precision and vocabulary to match a practitioner audience. Don't add hedging or caveats, just precision.",
    "less-hedging": "Remove qualifiers like 'might', 'could', 'it seems', 'arguably' wherever the underlying claim is actually one the writer holds confidently. State positions plainly.",
}


class OllamaUnavailable(RuntimeError):
    pass


def _call_ollama(ollama_url: str, model: str, prompt: str, timeout: int = 240) -> str:
    try:
        resp = requests.post(
            f"{ollama_url.rstrip('/')}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise OllamaUnavailable(
            f"Could not reach Ollama at {ollama_url}. Is it running? "
            f"Start it with `ollama serve` (or it may already be running as a background "
            f"service). Original error: {e}"
        )
    return resp.json().get("response", "").strip()


def _parse_json_response(raw_text: str) -> dict:
    cleaned = re.sub(r"^```(json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
    return json.loads(cleaned)


def build_post_prompt(notes: str, voice_samples: list, style_guide_text: str,
                      corpus_examples: list) -> str:
    sample_block = ""
    if voice_samples:
        joined = "\n\n---\n\n".join(voice_samples[:5])
        sample_block = f"""

Study these real past writing samples first. Infer tone, style, form, preferred
length, sentence rhythm, vocabulary, how directly the person states opinions,
and recurring rhetorical tendencies. Use them as voice reference only. Do not
copy their wording, anecdotes, or claims.
---
{joined}
---
"""

    corpus_block = ""
    if corpus_examples:
        joined = "\n\n---\n\n".join(corpus_examples[:5])
        corpus_block = f"""

Here are real past posts already produced under this voice, for additional
rhythm and structure reference only:
---
{joined}
---
"""

    return f"""You are ghostwriting a blog post in the voice of a real person.
Do not invent affiliations, products, achievements, or opinions that are not
supported by the notes, the voice samples, or the style guide.
{sample_block}{corpus_block}

The person's raw take (this is the actual opinion/content — do not replace
or dilute it, only structure and expand it with that person's reasoning):
---
{notes}
---

Voice and style guide to match as closely as possible:
---
{style_guide_text}
---
Requirements:
- Output valid JSON only, with keys: "title", "meta_description", "body_markdown".
- "title": specific, opinionated, not generic clickbait.
- "meta_description": under 155 characters, plainly describes the post's actual argument.
- "body_markdown": 500-800 words, uses ## subheadings, states the person's
  position clearly and early, and closes with implications/what-this-means.
- Respect any promotional or non-promotional boundaries defined in the style
  guide. If no such boundary is stated, stay focused on the
  actual argument rather than adding generic calls to action.

Return ONLY the JSON object, no commentary, no markdown code fences."""


def generate_post(ollama_url: str, model: str, notes: str, voice_samples: list,
                   style_guide_text: str, corpus_examples: list,
                   dry_run: bool = False) -> dict:
    if dry_run:
        return {
            "title": "[DRY RUN] A Real Person's Take, Structured Into a Post",
            "meta_description": "Placeholder summary standing in for the model's real output.",
            "body_markdown": (
                f"## The Position\n\n> {notes}\n\n"
                f"## Why It Matters\n\n- Reasoning point one\n- Reasoning point two\n\n"
                f"## Implications\n\nWhat this means for the field, stated plainly — "
                f"no company plug, no call-to-action."
            ),
        }
    prompt = build_post_prompt(notes, voice_samples, style_guide_text, corpus_examples)
    raw = _call_ollama(ollama_url, model, prompt)
    post = _parse_json_response(raw)
    for key in ("title", "meta_description", "body_markdown"):
        if key not in post:
            raise RuntimeError(f"Model output missing required key '{key}': {post}")
    return post


def revise(ollama_url: str, model: str, body_markdown: str, verb: str,
           voice_samples: list, style_guide_text: str,
           dry_run: bool = False) -> str:
    if verb not in REVISION_VERBS:
        raise ValueError(f"Unknown revision verb: {verb}. Options: {list(REVISION_VERBS)}")

    if dry_run:
        return body_markdown + f"\n\n[DRY RUN: would have applied '{verb}' here]"

    instruction = REVISION_VERBS[verb]
    sample_block = ""
    if voice_samples:
        joined = "\n\n---\n\n".join(voice_samples[:5])
        sample_block = f"""

Maintain the voice inferred from these real writing samples:
---
{joined}
---
"""

    prompt = f"""Apply exactly this instruction to the blog post body below, and nothing else:
"{instruction}"
{sample_block}

Maintain this voice/style:
---
{style_guide_text}
---

Blog post body (markdown):
---
{body_markdown}
---

Return ONLY valid JSON: {{"body_markdown": "<the revised body>"}}. No commentary."""
    raw = _call_ollama(ollama_url, model, prompt)
    result = _parse_json_response(raw)
    return result["body_markdown"]


def distill_style(ollama_url: str, model: str, corpus_examples: list,
                   current_auto_observed: str, dry_run: bool = False) -> str:
    """Propose a rewritten Auto-Observed Patterns section from the pinned corpus.
    Caller is responsible for showing this as a diff and only applying it on
    explicit user approval — this function never writes anything itself."""
    if dry_run:
        return (current_auto_observed + "\n- [DRY RUN] would propose an updated "
                "observation here based on the pinned corpus")

    if not corpus_examples:
        return current_auto_observed

    joined = "\n\n---\n\n".join(corpus_examples)
    prompt = f"""Read these approved, user-pinned blog posts (this person's real voice):
---
{joined}
---

Current notes on this person's style:
---
{current_auto_observed}
---

Write an updated, concise set of observations about this writing voice — sentence
rhythm, vocabulary, how directly the person states opinions, technical depth, recurring
framing habits. Merge with the current notes above rather than discarding them,
correcting anything the new examples contradict. Keep it under 200 words,
written as plain bullet-style notes (use "- " prefixes), no headers.

Return ONLY valid JSON: {{"auto_observed": "<the updated notes>"}}. No commentary."""
    raw = _call_ollama(ollama_url, model, prompt)
    result = _parse_json_response(raw)
    return result["auto_observed"]
