# Voice Agent

A terminal tool that turns a real person's raw takes into blog posts in their
voice, and publishes them to WordPress — at zero recurring cost.
No paid API, no SaaS subscription: it runs on a local open-source model via
Ollama and publishes through WordPress's own free REST API.

It is sample-driven, not niche-driven. You can use it for a founder, investor,
engineer, coach, critic, creator, operator, or any other personality, as long
as you give it a few real writing samples plus a style guide when needed. It is
designed to structure and expand what the person already thinks, in their own
voice.

## Install (start here)

Don't read this section as documentation — run it instead. The real guide is
an interactive script that checks each step live:

```bash
pip install -r requirements.txt --break-system-packages   # one-time, free
python3 setup.py
```

`setup.py` will walk you through, in order:
1. Confirming Ollama is installed and running (with exact install steps if not)
2. Picking and downloading a local model (e.g. `llama3`) — free, one time
3. Optionally connecting WordPress via a free Application Password
4. Creating your local data folders, starter voice-samples file, and starter style guide

It tells you exactly what to type at each step. If you skip WordPress for now,
you can still draft and review posts — just re-run `python3 setup.py` whenever
you're ready to connect publishing.

Before drafting, add a few real writing samples with `/samples` or
`/sample-paste`. The model studies those examples for tone, structure, length,
sentence rhythm, vocabulary, and recurring stylistic habits.

## Day to day use

```bash
python3 main.py
```

Then just type a raw take, e.g.:

```
writer> Small modular reactors get overhyped on cost timelines; the real
bottleneck is licensing throughput, not reactor design.
```

That drafts a post. From there:

- `/review` — see the current draft again
- `/tighten`, `/expand`, `/redo-opening`, `/more-technical`, `/less-hedging` — targeted revisions
- `/samples` — open the voice-samples file and paste prior writing into it
- `/sample-paste` — paste a writing sample directly into the terminal
- `/style` — open your voice guide in a text editor; edit it by hand any time
- `/pin` — mark this draft to feed your style corpus once published
- `/distill` — propose an update to your style guide from pinned posts (shows you the diff, asks before applying)
- `/publish` — shows a preview + WordPress preview link, asks y/n, only then goes live
- `/history` — list past drafts
- `/help` — full command list

Everything that changes state (publishing, updating the style guide) requires
an explicit yes from you. Nothing runs silently in the background.

## Why there's no database

Every piece of state here — the voice samples, style guide, drafts, the
pinned-post corpus, session logs — is a plain local file (markdown or JSON)
under `data/`. That's deliberate: this is a single user running one process at
a time with a small, slow-growing amount of data, so a linear file scan is
instant and a database engine would add complexity for no benefit. It also
means the voice samples and style guide are things you can open and hand-edit in any
text editor, not something locked behind a UI.

## Testing without Ollama or WordPress set up

```bash
python3 main.py --dry-run
```

Runs the full command flow with mocked responses, so you can see how it
behaves before wiring up real services.

## Future improvements (not in this version)

- Topic-similarity retrieval for style examples (embeddings) once the pinned
  corpus grows past ~30-50 posts — v1 just uses the most recent pins.
- Optional research pass pulling live sources into a post's context.
- Voice-memo-to-draft, skipping typed notes entirely.
