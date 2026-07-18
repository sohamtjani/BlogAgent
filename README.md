# FounderVoice - A Blog-gen Solution for Thought Leaders

A terminal tool that turns the founder's own raw takes into thought-leadership
posts in his voice, and publishes them to WordPress — at zero recurring cost.
No paid API, no SaaS subscription: it runs on a local open-source model via
Ollama and publishes through WordPress's own free REST API.

This is not a marketing tool. It never invents an opinion, never mentions
the company, and never adds promotional language — it structures and expands
what the founder already thinks, in his own words.

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
4. Connecting a local SearXNG instance for research-backed technical revisions
5. Creating your local data folders and a starter style guide

It tells you exactly what to type at each step. If you skip WordPress for now,
you can still draft and review posts — just re-run `python3 setup.py` whenever
you're ready to connect publishing.

## Day to day use

```bash
python3 main.py
```

Then just type a raw take, e.g.:

```
founder> Small modular reactors get overhyped on cost timelines; the real
bottleneck is licensing throughput, not reactor design.
```

That first finds technical sources supporting or qualifying the take, shows them
for approval, then drafts a cited post in the founder's voice. If research is
unavailable, it offers an explicit choice to draft without web evidence. From there:

- `/review` — see the current draft again
- `/tighten`, `/expand`, `/redo-opening`, `/less-hedging` — targeted revisions
- `/more-technical` — finds live technical sources through SearXNG, shows them for approval, then deepens the current argument with traceable citations
- `/style` — open your voice guide in a text editor; edit it by hand any time
- `/pin` — mark this draft to feed your style corpus once published
- `/distill` — propose an update to your style guide from pinned posts (shows you the diff, asks before applying)
- `/publish` — shows a preview + WordPress preview link, asks y/n, only then goes live
- `/history` — list past drafts
- `/help` — full command list

Everything that changes state (publishing, updating the style guide) requires
an explicit yes from you. Nothing runs silently in the background.

## Research-backed technical revisions

`/more-technical` is deliberately different from an ordinary rewrite. It
creates focused search queries from your current draft, searches the web through
your own [SearXNG](https://github.com/searxng/searxng) instance, retrieves a
small set of readable source pages, and shows the selected sources before it
changes anything. The revised post keeps your original position, adds only
source-supported factual material, and includes a numbered `## Sources` section.

### One-time SearXNG installation (macOS, no Docker)

SearXNG is a separate local search-server package. You install it once; then
Founder Voice starts it automatically whenever the app launches. No Docker,
API key, login, or paid account is needed.

Open the **Terminal** app and run these commands one at a time.

**1. Install Homebrew, only if `brew --version` says command not found.**

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

When the installer finishes, it may print one or two commands under “Next
steps”. Copy and run those exact commands before continuing. This makes `brew`
available in future Terminal windows.

**2. Install the build tools SearXNG needs.**

```bash
brew install git make mise
```

**3. Download and install the local SearXNG package.** From the BlogAgent
folder, run:

```bash
mkdir -p vendor
git clone https://github.com/searxng/searxng.git vendor/searxng
cd vendor/searxng
mise trust
mise exec python@3.11 -- make install
cd ../..
```

`mise trust` may ask you to approve the SearXNG project configuration; type
`y` and press Return. The `mise exec ... make install` command can take several minutes on its first run.
It creates SearXNG’s own isolated Python environment, then installs the actual
SearXNG server package and every dependency it needs. Do **not** use
`pip install searxng`: that similarly named PyPI package is not the SearXNG web
server this app requires.

**4. Connect BlogAgent to it.**

```bash
python3 setup.py
```

At the SearXNG prompts, press Return to accept both defaults:

```text
SearXNG URL:       http://localhost:8888
SearXNG source:    the displayed path ending in /vendor/searxng
```

Setup creates a private local configuration automatically. It enables the JSON
search API BlogAgent needs, binds the service to your own computer only, and
creates a random local secret. It then starts SearXNG and confirms the search
connection.

### What happens after installation

Start BlogAgent normally:

```bash
python3 main.py
```

At launch, BlogAgent checks `http://localhost:8888`. If SearXNG is already
running, it reuses it. If not, it starts SearXNG through its local Python 3.11
toolchain from `vendor/searxng` and
waits until the local JSON search API is ready. Then `/more-technical` can
research and cite web sources.

### If setup reports an error

Run these checks in the BlogAgent folder:

```bash
test -d vendor/searxng && echo "SearXNG folder found" || echo "Run step 3 above"
cd vendor/searxng && mise exec python@3.11 -- make run
```

Leave that Terminal window open. In a second Terminal window, run:

```bash
curl "http://localhost:8888/search?q=nuclear+licensing&format=json"
```

Success looks like JSON beginning with `{` and containing a `results` list. If
the address is already in use, stop the process using port 8080 with:

```bash
lsof -ti :8888 | xargs kill
```

Then repeat `cd vendor/searxng && mise exec python@3.11 -- make run`. Once the curl command works, stop
the manual server with Control-C and launch `python3 main.py`; BlogAgent will
start it automatically thereafter.

## Why there's no database

Every piece of state here — the style guide, drafts, the pinned-post corpus,
session logs — is a plain local file (markdown or JSON) under `data/`. That's
deliberate: this is a single user running one process at a time with a small,
slow-growing amount of data, so a linear file scan is instant and a database
engine would add complexity for no benefit. It also means the style guide is
something you can open and hand-edit in any text editor, not something locked
behind a UI.

## Testing without Ollama or WordPress set up

```bash
python3 main.py --dry-run
```

Runs the full command flow with simulated Ollama, SearXNG, and WordPress
responses. It needs no configuration, downloads nothing, makes no network
requests, and never publishes. Use `/post` followed by `/more-technical` to
test the complete research-backed revision flow with predictable placeholder
sources and citations.

## Future improvements (not in this version)

- Topic-similarity retrieval for style examples (embeddings) once the pinned
  corpus grows past ~30-50 posts — v1 just uses the most recent pins.
- Optional research pass pulling live sources into a post's context.
- Voice-memo-to-draft, skipping typed notes entirely.
