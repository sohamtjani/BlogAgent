#!/usr/bin/env python3
"""
Voice Agent — a terminal-based, zero-cost writing tool.

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

import config as cfg
import llm
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
  /more-technical       Raise technical precision
  /less-hedging         Remove unnecessary qualifiers
  /samples              Open the voice samples file in your editor
  /sample-paste         Paste a writing sample directly into the terminal
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
    voice_samples = storage.load_voice_samples()
    style_text = storage.load_style_guide()
    corpus_examples = storage.get_recent_corpus_texts()
    print("Drafting..." if not DRY_RUN else "Drafting (dry run)...")
    try:
        post = llm.generate_post(cfg.load_config()["ollama_url"], cfg.load_config()["ollama_model"],
                                  notes, voice_samples, style_text, corpus_examples,
                                  dry_run=DRY_RUN)
    except llm.OllamaUnavailable as e:
        print(f"Error: {e}")
        return
    draft = storage.new_draft(notes)
    draft.update(post)
    storage.save_draft(draft)
    storage.log_session("user", f"/post {notes}")
    storage.log_session("agent", f"drafted {draft['id']}")
    print_draft(draft)


def cmd_revise(verb: str):
    draft = storage.get_current_draft()
    if not draft:
        print("No draft open. Use /post <notes> first.")
        return
    voice_samples = storage.load_voice_samples()
    style_text = storage.load_style_guide()
    print(f"Applying '{verb}'..." if not DRY_RUN else f"Applying '{verb}' (dry run)...")
    try:
        new_body = llm.revise(cfg.load_config()["ollama_url"], cfg.load_config()["ollama_model"],
                               draft["body_markdown"], verb, voice_samples, style_text,
                               dry_run=DRY_RUN)
    except llm.OllamaUnavailable as e:
        print(f"Error: {e}")
        return
    draft["body_markdown"] = new_body
    draft["revisions"].append({"verb": verb})
    storage.save_draft(draft)
    storage.log_session("user", f"/{verb}")
    print_draft(draft)


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


def cmd_samples():
    editor = os.environ.get("EDITOR", "nano")
    path = storage.VOICE_SAMPLES_PATH
    storage.ensure_dirs()
    print(f"Opening {path} in {editor}...")
    try:
        subprocess.call([editor, path])
    except FileNotFoundError:
        print(f"Couldn't launch '{editor}'. Open this file manually:\n{path}")


def cmd_sample_paste():
    print("Paste a real writing sample. End input with a line containing only /done.")
    lines = []
    while True:
        try:
            line = input("")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return
        if line.strip() == "/done":
            break
        lines.append(line)
    sample_text = "\n".join(lines).strip()
    if not sample_text:
        print("No sample captured.")
        return
    storage.append_voice_sample(sample_text)
    print("Saved to voice samples.")


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
    storage.log_session("user", "/publish -> yes")
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
        elif command in llm.REVISION_VERBS:
            cmd_revise(command)
        elif command == "review":
            cmd_review()
        elif command == "style":
            cmd_style()
        elif command == "samples":
            cmd_samples()
        elif command == "sample-paste":
            cmd_sample_paste()
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
    storage.log_session("user", line)
    if storage.get_current_draft() is None:
        cmd_post(line)
    else:
        print("A draft is already open. Use a slash command to act on it "
              "(/tighten, /expand, /publish, ...), or /post <notes> to start a new one.")
    return True


def main():
    if not cfg.config_exists():
        print("No config found yet.")
        run_setup = input("Run the guided setup now? [Y/n] ").strip().lower()
        if run_setup in ("", "y", "yes"):
            import setup as setup_module
            setup_module.run()
        else:
            print("You can run `python3 setup.py` any time before publishing.")

    storage.ensure_dirs()
    print("Voice Agent. Type a raw take to start a draft, or /help for commands.")
    if DRY_RUN:
        print("(running in --dry-run mode: no calls to Ollama or WordPress)")

    while True:
        try:
            line = input("\nwriter> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not dispatch(line):
            break


if __name__ == "__main__":
    main()
