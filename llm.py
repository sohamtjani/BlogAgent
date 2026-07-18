"""
Thin wrapper around a locally-run Ollama model. Zero cost: no API key, no
per-token billing, everything runs on the founder's own machine.

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


def build_post_prompt(notes: str, style_guide_text: str, corpus_examples: list,
                      research_sources: list = None) -> str:
    examples_block = ""
    if corpus_examples:
        joined = "\n\n---\n\n".join(corpus_examples[:5])
        examples_block = f"\n\nHere are real past posts of his, for tone/rhythm reference only " \
                          f"(do not reuse their content or claims):\n---\n{joined}\n---\n"

    research_block = ""
    if research_sources:
        packets = "\n\n".join(
            f"SOURCE [{source['id']}]\nTitle: {source['title']}\nURL: {source['url']}\n"
            f"Research text ({source.get('retrieval', 'page')}):\n{source['excerpt']}"
            for source in research_sources
        )
        research_block = f"""

Research supporting or qualifying the founder's take:
---
{packets}
---
Use this only for factual and technical additions. Every external factual claim
you add must end with the relevant source ID, such as [1] or [1][2]. Never cite
an ID absent from these source packets. End the post with `## Sources`, followed
only by Markdown links for sources actually used in the exact form
`[1] [Source title](https://source-url)`."""

    return f"""You are ghostwriting a thought-leadership blog post for a nuclear-tooling
industry founder. This is NOT marketing or company promotion — it is
independent professional commentary. Do not mention the founder's company,
its products, or include any call-to-action, sales language, or promotional
framing anywhere in the post. If the notes below don't mention a company,
don't invent one.

The founder's raw take (this is the actual opinion/content — do not replace
or dilute it, only structure and expand it with the founder's own reasoning):
---
{notes}
---

Voice and style guide to match as closely as possible:
---
{style_guide_text}
---
{examples_block}
{research_block}
Requirements:
- Output valid JSON only. Use keys "title", "meta_description", and "body_markdown".
- When research packets are supplied, also include "used_source_ids" as a list of the
  source IDs actually cited in the post.
- "title": specific, opinionated, not generic clickbait.
- "meta_description": under 155 characters, plainly describes the post's actual argument.
- "body_markdown": 500-800 words, uses ## subheadings, states the founder's
  position clearly and early, and closes with implications/what-this-means —
  NOT a call-to-action, NOT a company plug.

Return ONLY the JSON object, no commentary, no markdown code fences."""


def generate_post(ollama_url: str, model: str, notes: str, style_guide_text: str,
                   corpus_examples: list, research_sources: list = None,
                   dry_run: bool = False) -> dict:
    if dry_run:
        body = (
            f"## The Position\n\n> {notes}\n\n"
            f"## Why It Matters\n\n- Reasoning point one\n- Reasoning point two\n\n"
            f"## Implications\n\nWhat this means for the field, stated plainly — "
            f"no company plug, no call-to-action."
        )
        if research_sources:
            source = research_sources[0]
            body += f"\n\n[1] [DRY RUN: evidence-backed technical context.]\n\n## Sources\n\n[1] [{source['title']}]({source['url']})"
        return {
            "title": "[DRY RUN] A Founder's Take, Structured Into a Post",
            "meta_description": "Placeholder summary standing in for the model's real output.",
            "body_markdown": body,
            "used_source_ids": [source["id"] for source in research_sources] if research_sources else [],
        }
    prompt = build_post_prompt(notes, style_guide_text, corpus_examples, research_sources)
    raw = _call_ollama(ollama_url, model, prompt)
    post = _parse_json_response(raw)
    for key in ("title", "meta_description", "body_markdown"):
        if key not in post:
            raise RuntimeError(f"Model output missing required key '{key}': {post}")
    if research_sources:
        valid_ids = {source["id"] for source in research_sources}
        used_ids = post.get("used_source_ids", [])
        if not isinstance(used_ids, list) or not used_ids or not set(used_ids).issubset(valid_ids):
            raise RuntimeError("Model did not identify valid research sources used in the draft.")
        if "## Sources" not in post["body_markdown"]:
            raise RuntimeError("Research-backed draft did not include the required Sources section.")
    return post


def build_initial_research_queries(ollama_url: str, model: str, notes: str,
                                   dry_run: bool = False) -> list:
    """Create evidence-seeking queries before drafting a new founder post."""
    if dry_run:
        return ["[DRY RUN] technical evidence supporting the founder's raw take"]
    prompt = f"""Create 3 to 5 precise web-search queries that find credible technical
evidence supporting or qualifying this founder's raw take. Prefer primary sources,
regulators, standards bodies, original research, and data. Do not write the blog post
and do not replace the founder's position.

Founder notes:
---
{notes}
---

Return ONLY valid JSON: {{"queries": ["query one", "query two"]}}."""
    raw = _call_ollama(ollama_url, model, prompt)
    queries = _parse_json_response(raw).get("queries", [])
    if not isinstance(queries, list):
        raise RuntimeError("Model returned initial research queries in an invalid format.")
    cleaned = [str(query).strip() for query in queries if str(query).strip()]
    if not cleaned:
        raise RuntimeError("Model did not produce any initial research queries.")
    return cleaned[:5]


def revise(ollama_url: str, model: str, body_markdown: str, verb: str,
           style_guide_text: str, dry_run: bool = False) -> str:
    if verb not in REVISION_VERBS:
        raise ValueError(f"Unknown revision verb: {verb}. Options: {list(REVISION_VERBS)}")

    if dry_run:
        return body_markdown + f"\n\n[DRY RUN: would have applied '{verb}' here]"

    instruction = REVISION_VERBS[verb]
    prompt = f"""Apply exactly this instruction to the blog post body below, and nothing else:
"{instruction}"

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


def build_research_queries(ollama_url: str, model: str, draft: dict,
                           dry_run: bool = False) -> list:
    """Create focused, evidence-seeking queries from the founder's actual stance."""
    if dry_run:
        return ["[DRY RUN] technical evidence for the current draft's central claim"]
    prompt = f"""Create 3 to 5 precise web-search queries that would find credible technical
evidence needed to develop the founder's existing position below. Seek primary sources,
standards, regulators, original research, and data—not general commentary. Do not try to
change the position or write the post.

Original founder notes:
---
{draft['notes']}
---

Current draft:
---
{draft['body_markdown']}
---

Return ONLY valid JSON: {{"queries": ["query one", "query two"]}}."""
    raw = _call_ollama(ollama_url, model, prompt)
    queries = _parse_json_response(raw).get("queries", [])
    if not isinstance(queries, list):
        raise RuntimeError("Model returned research queries in an invalid format.")
    cleaned = [str(query).strip() for query in queries if str(query).strip()]
    if not cleaned:
        raise RuntimeError("Model did not produce any research queries.")
    return cleaned[:5]


def revise_with_research(ollama_url: str, model: str, draft: dict, style_guide_text: str,
                         sources: list, dry_run: bool = False) -> dict:
    """Deepen a draft using only supplied web research, with traceable citations."""
    if dry_run:
        body = draft["body_markdown"].split("\n## Sources", 1)[0].rstrip()
        body += "\n\n[1] [DRY RUN: technical claim supported by source.]\n\n## Sources\n\n[1] [Dry-run example technical source](https://example.org/technical-source)"
        return {"body_markdown": body, "used_source_ids": [1]}

    source_block = "\n\n".join(
        f"SOURCE [{source['id']}]\nTitle: {source['title']}\nURL: {source['url']}\n"
        f"Extracted text:\n{source['excerpt']}" for source in sources
    )
    prompt = f"""Revise this founder-written blog post to make its EXISTING position more
technically rigorous, using only the supplied web-source packets for factual additions.
Preserve the founder's thesis and voice; do not turn it into neutral reporting or invent a
new opinion.

Rules:
- Every external factual or technical claim you add must end with one or more source IDs,
  such as [1] or [1][3]. Never cite an ID absent from the source packets.
- Do not invent figures, dates, quotes, regulations, studies, mechanisms, or citations.
- If the sources qualify or disagree with the founder's claim, state that nuance plainly.
- Keep the post's original argument intact and do not add promotional language or a CTA.
- Replace any existing `## Sources` section with one complete `## Sources` section at the
  end, containing only Markdown links for sources actually used in the exact form
  `[1] [Source title](https://source-url)`.

Style guide:
---
{style_guide_text}
---

Original founder notes:
---
{draft['notes']}
---

Current blog post:
---
{draft['body_markdown']}
---

Research packets:
---
{source_block}
---

Return ONLY valid JSON: {{"body_markdown": "<revised markdown>", "used_source_ids": [1, 2]}}."""
    raw = _call_ollama(ollama_url, model, prompt)
    result = _parse_json_response(raw)
    valid_ids = {source["id"] for source in sources}
    used_ids = result.get("used_source_ids", [])
    if not isinstance(result.get("body_markdown"), str) or not isinstance(used_ids, list):
        raise RuntimeError("Model returned an invalid research revision.")
    if not used_ids or not set(used_ids).issubset(valid_ids):
        raise RuntimeError("Model cited a missing source or did not identify sources it used.")
    if "## Sources" not in result["body_markdown"]:
        raise RuntimeError("Model revision did not include the required Sources section.")
    return {"body_markdown": result["body_markdown"], "used_source_ids": used_ids}


def distill_style(ollama_url: str, model: str, corpus_examples: list,
                   current_auto_observed: str, dry_run: bool = False) -> str:
    """Propose a rewritten Auto-Observed Patterns section from the pinned corpus.
    Caller is responsible for showing this as a diff and only applying it on
    explicit founder approval — this function never writes anything itself."""
    if dry_run:
        return (current_auto_observed + "\n- [DRY RUN] would propose an updated "
                "observation here based on the pinned corpus")

    if not corpus_examples:
        return current_auto_observed

    joined = "\n\n---\n\n".join(corpus_examples)
    prompt = f"""Read these approved, founder-pinned blog posts (his real voice):
---
{joined}
---

Current notes on his style:
---
{current_auto_observed}
---

Write an updated, concise set of observations about his writing voice — sentence
rhythm, vocabulary, how directly he states opinions, technical depth, recurring
framing habits. Merge with the current notes above rather than discarding them,
correcting anything the new examples contradict. Keep it under 200 words,
written as plain bullet-style notes (use "- " prefixes), no headers.

Return ONLY valid JSON: {{"auto_observed": "<the updated notes>"}}. No commentary."""
    raw = _call_ollama(ollama_url, model, prompt)
    result = _parse_json_response(raw)
    return result["auto_observed"]
