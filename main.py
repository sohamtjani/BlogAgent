#!/usr/bin/env python3
"""
Founder Voice Agent — a terminal-based, zero-cost thought-leadership tool.

Talk to it like a chat, or use slash commands for anything that changes state.
Nothing publishes, and nothing rewrites your style guide, without you
explicitly confirming it.

Run `python3 setup.py` first if you haven't configured Ollama/WordPress yet
(main.py will offer to do this for you on first run too).
"""
import os
import shlex
import subprocess
import sys

from runtime import ensure_project_runtime

ensure_project_runtime(__file__)

import config as cfg
import llm
import research
import storage
import wordpress

DRY_RUN = "--dry-run" in sys.argv

HELP_TEXT = """
Commands:
  /post <notes>        Start a new draft from a raw take (or just type plainly)
  /review               Show the current draft
  /tighten              Cut length, remove hedging/filler
  /expand               Add another layer of reasoning/example
  /redo-opening         Rewrite just the opening so the position leads
  /more-technical       Research the current stance, then deepen it with cited web sources
  /less-hedging         Remove unnecessary qualifiers
  /style                Open the style guide in your editor
  /pin                  Mark this draft to be added to the style corpus on publish
  /distill              Propose an update to the style guide from pinned posts (needs your approval)
  /publish              Preview + confirm, then push live to WordPress
  /history              List past drafts
  /help                 Show this again
  /quit                 Exit
"""


def print_draft(draft: dict):
    print(f"\n--- Draft: {draft['id']} ---")
    print(f"Title: {draft['title']}")
    print(f"Meta:  {draft['meta_description']}")
    print(f"\n{draft['body_markdown']}\n")
    print(f"WordPress status: {draft['wp_status']}"
          + (f" (post id {draft['wp_post_id']})" if draft["wp_post_id"] else ""))
    if draft.get("pin_requested"):
        print("Pinned: will be added to the style corpus when published.")


def cmd_post(notes: str):
    if not notes.strip():
        print("Usage: /post <your raw take on a topic>")
        return
    c = cfg.load_config()
    style_text = storage.load_style_guide()
    corpus_examples = storage.get_recent_corpus_texts()
    queries, sources = [], []
    print("Researching the founder's take..." if not DRY_RUN else "Researching the founder's take (dry run)...")
    try:
        queries = llm.build_initial_research_queries(c["ollama_url"], c["ollama_model"], notes, dry_run=DRY_RUN)
        sources = research.gather_research(
            queries, c["searxng_url"], max_sources=int(c.get("research_max_sources", 5)),
            timeout=int(c.get("research_timeout_seconds", 15)), dry_run=DRY_RUN,
        )
    except (llm.OllamaUnavailable, research.ResearchUnavailable, RuntimeError) as e:
        print(f"Research unavailable: {e}")
    if not sources:
        if DRY_RUN:
            print("No simulated sources were returned. No draft was created.")
            return
        answer = input("Draft without web research instead? [y/N] ").strip().lower()
        if answer != "y":
            print("No draft was created.")
            return
    else:
        print("\n--- Supporting sources ---")
        for source in sources:
            print(f"[{source['id']}] {source['title']}\n    {source['url']}")
        if not DRY_RUN:
            answer = input("Use these sources to draft the post? [y/N] ").strip().lower()
            if answer != "y":
                print("No draft was created.")
                return
    print("Drafting with cited research..." if sources and not DRY_RUN else "Drafting...")
    try:
        post = llm.generate_post(c["ollama_url"], c["ollama_model"], notes, style_text,
                                  corpus_examples, sources, dry_run=DRY_RUN)
    except (llm.OllamaUnavailable, RuntimeError) as e:
        print(f"Error: {e}")
        return
    draft = storage.new_draft(notes)
    draft.update(post)
    if sources:
        storage.add_research_run(draft, queries, sources, post["used_source_ids"], command="post")
    storage.save_draft(draft)
    storage.log_session("founder", f"/post {notes}")
    storage.log_session("agent", f"drafted {draft['id']}")
    print_draft(draft)


def cmd_revise(verb: str):
    draft = storage.get_current_draft()
    if not draft:
        print("No draft open. Use /post <notes> first.")
        return
    style_text = storage.load_style_guide()
    print(f"Applying '{verb}'..." if not DRY_RUN else f"Applying '{verb}' (dry run)...")
    try:
        new_body = llm.revise(cfg.load_config()["ollama_url"], cfg.load_config()["ollama_model"],
                               draft["body_markdown"], verb, style_text, dry_run=DRY_RUN)
    except llm.OllamaUnavailable as e:
        print(f"Error: {e}")
        return
    draft["body_markdown"] = new_body
    draft["revisions"].append({"verb": verb})
    storage.save_draft(draft)
    storage.log_session("founder", f"/{verb}")
    print_draft(draft)


def cmd_more_technical():
    """Run a source-backed technical revision while keeping the founder's stance."""
    draft = storage.get_current_draft()
    if not draft:
        print("No draft open. Use /post <notes> first.")
        return
    c = cfg.load_config()
    searxng_url = c.get("searxng_url", "").strip()
    if not searxng_url:
        print("Web research isn't configured. Run `python3 setup.py` to add SearXNG.")
        return

    print("Creating focused research queries..." if not DRY_RUN else "Creating research queries (dry run)...")
    try:
        queries = llm.build_research_queries(c["ollama_url"], c["ollama_model"], draft, dry_run=DRY_RUN)
        sources = research.gather_research(
            queries, searxng_url,
            max_sources=int(c.get("research_max_sources", 5)),
            timeout=int(c.get("research_timeout_seconds", 15)), dry_run=DRY_RUN,
        )
    except (llm.OllamaUnavailable, research.ResearchUnavailable, RuntimeError) as exc:
        print(f"Error: {exc}")
        return
    if not sources:
        print("No usable research sources were retrieved. Your draft was not changed.")
        return

    print("\n--- Research sources ---")
    for source in sources:
        print(f"[{source['id']}] {source['title']}\n    {source['url']}")
    if not DRY_RUN:
        answer = input("Use these sources to revise the draft? [y/N] ").strip().lower()
        if answer != "y":
            print("Not revised. Your draft was left unchanged.")
            return

    print("Deepening the technical argument with cited sources..." if not DRY_RUN else "Revising with research (dry run)...")
    try:
        revision = llm.revise_with_research(
            c["ollama_url"], c["ollama_model"], draft, storage.load_style_guide(), sources,
            dry_run=DRY_RUN,
        )
    except (llm.OllamaUnavailable, RuntimeError) as exc:
        print(f"Error: {exc}")
        return
    draft["body_markdown"] = revision["body_markdown"]
    storage.add_research_run(draft, queries, sources, revision["used_source_ids"])
    draft["revisions"].append({"verb": "more-technical", "source_ids": revision["used_source_ids"]})
    storage.save_draft(draft)
    storage.log_session("founder", "/more-technical")
    print_draft(draft)


def start_research_service():
    """Best-effort launch for the optional local research service."""
    if DRY_RUN:
        return
    c = cfg.load_config()
    if not c.get("searxng_autostart", True):
        return
    url = c.get("searxng_url", "").strip()
    if not url:
        return
    if c.get("searxng_start_mode", "bare_metal") == "docker":
        ok, message = research.ensure_local_instance(
            url, c.get("searxng_container_name", "founder-voice-searxng"),
        )
    else:
        ok, message = research.ensure_bare_metal_instance(
            url, c.get("searxng_source_dir", ""),
            c.get("searxng_launch_command", "local/py3/bin/granian --interface wsgi --host 127.0.0.1 --port 8888 searx.webapp:app"),
            c.get("searxng_settings_dir", ""),
        )
    if ok:
        print(f"Research service: {message}")
    else:
        print(f"Research service unavailable: {message}")


def cmd_review():
    draft = storage.get_current_draft()
    if not draft:
        print("No draft open. Use /post <notes> first.")
        return
    print_draft(draft)


def cmd_style():
    editor = os.environ.get("EDITOR", "nano")
    path = storage.STYLE_GUIDE_PATH
    storage.ensure_dirs()
    print(f"Opening {path} in {editor}...")
    try:
        subprocess.call([editor, path])
    except FileNotFoundError:
        print(f"Couldn't launch '{editor}'. Open this file manually:\n{path}")


def cmd_pin():
    draft = storage.get_current_draft()
    if not draft:
        print("No draft open. Use /post <notes> first.")
        return
    draft["pin_requested"] = True
    storage.save_draft(draft)
    print("Marked. This draft will be added to your style corpus once you /publish it.")


def cmd_publish():
    draft = storage.get_current_draft()
    if not draft:
        print("No draft open. Use /post <notes> first.")
        return
    c = cfg.load_config()
    if not DRY_RUN and not (c["wp_url"] and c["wp_user"] and c["wp_app_password"]):
        print("WordPress isn't configured yet. Run `python3 setup.py` to add it.")
        return

    print("\n--- Preview ---")
    print(f"Title: {draft['title']}")
    print(f"Meta:  {draft['meta_description']}")
    print(f"\n{draft['body_markdown'][:600]}{'...' if len(draft['body_markdown']) > 600 else ''}\n")

    try:
        if draft["wp_post_id"]:
            result = wordpress.update_existing_draft(
                c["wp_url"], c["wp_user"], c["wp_app_password"], draft["wp_post_id"],
                draft["title"], draft["body_markdown"], draft["meta_description"], dry_run=DRY_RUN)
        else:
            result = wordpress.create_draft_post(
                c["wp_url"], c["wp_user"], c["wp_app_password"],
                draft["title"], draft["body_markdown"], draft["meta_description"], dry_run=DRY_RUN)
    except wordpress.WordPressError as e:
        print(f"Error: {e}")
        return

    draft["wp_post_id"] = result["id"]
    draft["wp_status"] = "draft"
    storage.save_draft(draft)

    print(f"Preview link (open while logged into WordPress admin): {result['link']}")
    answer = input("Publish this live now? [y/N] ").strip().lower()
    if answer != "y":
        print("Not published. It remains a WordPress draft; run /publish again when ready.")
        return

    try:
        pub_result = wordpress.publish_post(c["wp_url"], c["wp_user"], c["wp_app_password"],
                                             draft["wp_post_id"], dry_run=DRY_RUN)
    except wordpress.WordPressError as e:
        print(f"Error: {e}")
        return

    draft["wp_status"] = "published"
    storage.save_draft(draft)
    storage.log_session("founder", "/publish -> yes")
    print(f"Published: {pub_result['link']}")

    if draft.get("pin_requested"):
        storage.add_to_corpus(draft)
        print("Added to your style corpus.")


def cmd_distill():
    corpus_examples = storage.get_recent_corpus_texts(n=20)
    if not corpus_examples:
        print("No pinned posts yet — nothing to learn from. Use /pin before /publish on a few "
              "posts that really sound like you, then try /distill again.")
        return
    current = storage.split_style_guide(storage.load_style_guide())
    c = cfg.load_config()
    print("Analyzing pinned posts..." if not DRY_RUN else "Analyzing pinned posts (dry run)...")
    try:
        proposed = llm.distill_style(c["ollama_url"], c["ollama_model"], corpus_examples,
                                      current["auto_observed"], dry_run=DRY_RUN)
    except llm.OllamaUnavailable as e:
        print(f"Error: {e}")
        return

    print("\n--- Current Auto-Observed Patterns ---")
    print(current["auto_observed"] or "(empty)")
    print("\n--- Proposed Auto-Observed Patterns ---")
    print(proposed)
    answer = input("\nApply this update to your style guide? [y/N] ").strip().lower()
    if answer != "y":
        print("Not applied.")
        return
    storage.apply_auto_observed_update(proposed)
    print("Style guide updated. (Previous version backed up automatically.)")


def cmd_history():
    ids = storage.list_drafts()
    if not ids:
        print("No drafts yet.")
        return
    current = storage.get_current_draft_id()
    for draft_id in ids:
        marker = " *" if draft_id == current else ""
        try:
            d = storage.load_draft(draft_id)
            print(f"{draft_id}{marker}  [{d['wp_status']}]  {d['title'] or '(untitled)'}")
        except Exception:
            print(f"{draft_id}{marker}  (unreadable)")


def dispatch(line: str):
    line = line.strip()
    if not line:
        return True
    if line in ("/quit", "/exit"):
        return False
    if line in ("/help", "/?"):
        print(HELP_TEXT)
        return True

    if line.startswith("/"):
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split(" ", 1)
        command = parts[0][1:]
        rest = line[len(parts[0]):].strip()

        if command == "post":
            cmd_post(rest)
        elif command == "more-technical":
            cmd_more_technical()
        elif command in llm.REVISION_VERBS:
            cmd_revise(command)
        elif command == "review":
            cmd_review()
        elif command == "style":
            cmd_style()
        elif command == "pin":
            cmd_pin()
        elif command == "publish":
            cmd_publish()
        elif command == "distill":
            cmd_distill()
        elif command == "history":
            cmd_history()
        else:
            print(f"Unknown command: /{command}. Type /help for the list.")
        return True

    # Plain text, no leading slash.
    storage.log_session("founder", line)
    if storage.get_current_draft() is None:
        cmd_post(line)
    else:
        print("A draft is already open. Use a slash command to act on it "
              "(/tighten, /expand, /publish, ...), or /post <notes> to start a new one.")
    return True


def main():
    if not cfg.config_exists():
        if DRY_RUN:
            print("No config found; using built-in simulated services for this dry run.")
        else:
            print("No config found yet.")
            run_setup = input("Run the guided setup now? [Y/n] ").strip().lower()
            if run_setup in ("", "y", "yes"):
                import setup as setup_module
                setup_module.run()
            else:
                print("You can run `python3 setup.py` any time before publishing.")

    storage.ensure_dirs()
    start_research_service()
    print("Founder Voice Agent. Type a raw take to start a draft, or /help for commands.")
    if DRY_RUN:
        print("(running in --dry-run mode: no calls to Ollama or WordPress)")

    while True:
        try:
            line = input("\nfounder> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not dispatch(line):
            break


if __name__ == "__main__":
    main()
