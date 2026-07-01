"""
The whole "database" for this tool is plain local files:
  - style_guide.md          human-readable, hand-editable voice doc
  - style_guide_backups/    timestamped snapshot before every approved change
  - corpus/                 pinned "sounds like me" posts, used as few-shot examples
  - drafts/                 one JSON record per post, its whole lifecycle
  - sessions/               append-only JSONL conversation log, one file per day
  - .current_draft          tiny pointer file: which draft is "open" right now

No database engine because there's exactly one user, one process, and a data
volume (a few posts a week) where a linear file scan is instant. See the
install guide for the full reasoning if you're wondering why.
"""
import json
import os
import re
import shutil
from datetime import datetime, timezone

from config import DATA_DIR

STYLE_GUIDE_PATH = os.path.join(DATA_DIR, "style_guide.md")
STYLE_GUIDE_BACKUP_DIR = os.path.join(DATA_DIR, "style_guide_backups")
CORPUS_DIR = os.path.join(DATA_DIR, "corpus")
DRAFTS_DIR = os.path.join(DATA_DIR, "drafts")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
CURRENT_DRAFT_POINTER = os.path.join(DATA_DIR, ".current_draft")

FOUNDER_OVERRIDES_HEADER = "## Founder Overrides"
AUTO_OBSERVED_HEADER = "## Auto-Observed Patterns"

DEFAULT_STYLE_GUIDE = f"""# Voice & Style Guide

This file drives how every post is written. It is never overwritten silently —
the "Auto-Observed Patterns" section only changes when you approve an update
via `/distill`. The "Founder Overrides" section is yours; the agent never
touches it.

{FOUNDER_OVERRIDES_HEADER}
(Nothing here yet. Add your own rules any time, e.g. "never use the word
'leverage'" or "always open with the contrarian claim, not the setup." These
always win over anything in Auto-Observed Patterns below.)

{AUTO_OBSERVED_HEADER}
(No real samples yet, so the agent is using this placeholder default: direct,
technical, opinionated, first-person, comfortable with jargon a nuclear-industry
practitioner would know, short paragraphs, states a contrarian view plainly
rather than hedging it. Replace this by pinning a few real posts and running
`/distill` once you have some published under your voice.)
"""


def ensure_dirs():
    for d in (DATA_DIR, STYLE_GUIDE_BACKUP_DIR, CORPUS_DIR, DRAFTS_DIR, SESSIONS_DIR):
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(STYLE_GUIDE_PATH):
        with open(STYLE_GUIDE_PATH, "w", encoding="utf-8") as f:
            f.write(DEFAULT_STYLE_GUIDE)


# ---------------------------------------------------------------- style guide

def load_style_guide() -> str:
    ensure_dirs()
    with open(STYLE_GUIDE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def split_style_guide(text: str) -> dict:
    """Split into founder-overrides vs auto-observed sections (best-effort)."""
    overrides, auto = "", ""
    if FOUNDER_OVERRIDES_HEADER in text:
        after_overrides = text.split(FOUNDER_OVERRIDES_HEADER, 1)[1]
        if AUTO_OBSERVED_HEADER in after_overrides:
            overrides, auto_part = after_overrides.split(AUTO_OBSERVED_HEADER, 1)
            auto = auto_part
        else:
            overrides = after_overrides
    return {"overrides": overrides.strip(), "auto_observed": auto.strip()}


def backup_style_guide():
    ensure_dirs()
    if not os.path.exists(STYLE_GUIDE_PATH):
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    dest = os.path.join(STYLE_GUIDE_BACKUP_DIR, f"style_guide_{stamp}.md")
    shutil.copy(STYLE_GUIDE_PATH, dest)


def apply_auto_observed_update(new_auto_observed_text: str):
    """Only called after the founder explicitly approves a /distill proposal."""
    backup_style_guide()
    current = load_style_guide()
    parts = split_style_guide(current)
    new_content = (
        "# Voice & Style Guide\n\n"
        "This file drives how every post is written. It is never overwritten silently —\n"
        "the \"Auto-Observed Patterns\" section only changes when you approve an update\n"
        "via `/distill`. The \"Founder Overrides\" section is yours; the agent never\n"
        "touches it.\n\n"
        f"{FOUNDER_OVERRIDES_HEADER}\n{parts['overrides']}\n\n"
        f"{AUTO_OBSERVED_HEADER}\n{new_auto_observed_text.strip()}\n"
    )
    with open(STYLE_GUIDE_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)


def append_founder_override(note: str):
    """/pin-style manual rule add — takes effect immediately, no approval needed
    since the founder is directly authoring it himself."""
    ensure_dirs()
    current = load_style_guide()
    parts = split_style_guide(current)
    new_overrides = (parts["overrides"] + f"\n- {note}").strip()
    new_content = (
        "# Voice & Style Guide\n\n"
        "This file drives how every post is written. It is never overwritten silently —\n"
        "the \"Auto-Observed Patterns\" section only changes when you approve an update\n"
        "via `/distill`. The \"Founder Overrides\" section is yours; the agent never\n"
        "touches it.\n\n"
        f"{FOUNDER_OVERRIDES_HEADER}\n{new_overrides}\n\n"
        f"{AUTO_OBSERVED_HEADER}\n{parts['auto_observed']}\n"
    )
    backup_style_guide()
    with open(STYLE_GUIDE_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)


# ---------------------------------------------------------------------- corpus

def slugify(text: str, max_words: int = 6) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())[:max_words]
    return "-".join(words) if words else "post"


def add_to_corpus(draft: dict):
    ensure_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = slugify(draft.get("title", draft.get("notes", "post")))
    path = os.path.join(CORPUS_DIR, f"{stamp}_{slug}.md")
    frontmatter = (
        "---\n"
        f"title: {draft.get('title', '')}\n"
        f"date: {stamp}\n"
        f"source_draft_id: {draft.get('id', '')}\n"
        "---\n\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(frontmatter + draft.get("body_markdown", ""))
    return path


def list_corpus() -> list:
    ensure_dirs()
    return sorted(
        os.path.join(CORPUS_DIR, f) for f in os.listdir(CORPUS_DIR) if f.endswith(".md")
    )


def get_recent_corpus_texts(n: int = 5) -> list:
    """v1 retrieval strategy: most recent N pinned posts. Good enough at this
    scale; swap for embedding-based topic similarity once the corpus grows
    past ~30-50 entries (see README 'Future Improvements')."""
    files = list_corpus()[-n:]
    texts = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            texts.append(f.read())
    return texts


# --------------------------------------------------------------------- drafts

def new_draft(notes: str, sources: list = None) -> dict:
    ensure_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    slug = slugify(notes)
    draft_id = f"{stamp}_{slug}"
    draft = {
        "id": draft_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "sources": sources or [],
        "title": "",
        "meta_description": "",
        "body_markdown": "",
        "revisions": [],
        "wp_post_id": None,
        "wp_status": "none",
        "pin_requested": False,
    }
    save_draft(draft)
    set_current_draft_id(draft_id)
    return draft


def draft_path(draft_id: str) -> str:
    return os.path.join(DRAFTS_DIR, f"{draft_id}.json")


def save_draft(draft: dict):
    ensure_dirs()
    with open(draft_path(draft["id"]), "w", encoding="utf-8") as f:
        json.dump(draft, f, indent=2)


def load_draft(draft_id: str) -> dict:
    with open(draft_path(draft_id), "r", encoding="utf-8") as f:
        return json.load(f)


def list_drafts() -> list:
    ensure_dirs()
    return sorted(f[:-5] for f in os.listdir(DRAFTS_DIR) if f.endswith(".json"))


def set_current_draft_id(draft_id: str):
    ensure_dirs()
    with open(CURRENT_DRAFT_POINTER, "w", encoding="utf-8") as f:
        f.write(draft_id)


def get_current_draft_id():
    if not os.path.exists(CURRENT_DRAFT_POINTER):
        return None
    with open(CURRENT_DRAFT_POINTER, "r", encoding="utf-8") as f:
        val = f.read().strip()
    return val or None


def get_current_draft():
    draft_id = get_current_draft_id()
    if not draft_id:
        return None
    try:
        return load_draft(draft_id)
    except FileNotFoundError:
        return None


# -------------------------------------------------------------------- session

def log_session(role: str, text: str):
    ensure_dirs()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(SESSIONS_DIR, f"{day}.jsonl")
    entry = {"time": datetime.now(timezone.utc).isoformat(), "role": role, "text": text}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
