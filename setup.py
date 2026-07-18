#!/usr/bin/env python3
"""
Guided, interactive setup — this IS the install guide. Run it directly with
`python3 setup.py`, or it'll run automatically the first time you start
main.py. It walks through every step live in the terminal and checks each
one before moving on, instead of handing you a document to interpret.

Everything it sets up is free: Ollama runs the model on your own machine,
and WordPress's built-in Application Passwords feature needs no plugin.
"""
import getpass
import subprocess
import sys
import time

from runtime import ensure_project_runtime

ensure_project_runtime(__file__)

import requests

import config as cfg
import storage
import wordpress
import research


def line():
    print("-" * 60)


def step(n, total, title):
    print()
    line()
    print(f"Step {n} of {total}: {title}")
    line()


def check_ollama_running(ollama_url: str) -> bool:
    try:
        resp = requests.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=5)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def list_installed_models(ollama_url: str) -> list:
    try:
        resp = requests.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        return []


def pull_model(model: str) -> bool:
    print(f"Running `ollama pull {model}` — this downloads the model once, for free, "
          f"and can take a few minutes depending on your connection.")
    try:
        proc = subprocess.Popen(["ollama", "pull", model], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True)
        for out_line in proc.stdout:
            print(f"  {out_line.rstrip()}")
        proc.wait()
        return proc.returncode == 0
    except FileNotFoundError:
        print("Couldn't find the `ollama` command on your PATH.")
        return False


def setup_ollama(current_cfg: dict) -> dict:
    step(1, 4, "Local AI model (Ollama)")
    print("This tool writes drafts using a model that runs entirely on your own")
    print("computer via Ollama — no API key, no per-post cost, nothing sent to a")
    print("third-party AI service.\n")

    ollama_url = current_cfg.get("ollama_url", "http://localhost:11434")

    if check_ollama_running(ollama_url):
        print(f"Found Ollama already running at {ollama_url}.")
    else:
        print("Ollama doesn't seem to be running yet.\n")
        print("  1. Install it (one time, free):  https://ollama.com/download")
        print("  2. Once installed, it usually starts automatically. If not, run:")
        print("       ollama serve")
        input("\nPress Enter once Ollama is installed and running to continue...")
        while not check_ollama_running(ollama_url):
            retry = input("Still can't reach Ollama. Press Enter to check again, "
                          "or type 'skip' to configure this later: ").strip().lower()
            if retry == "skip":
                print("Skipping — you can re-run `python3 setup.py` any time.")
                return current_cfg
        print("Ollama is up.")

    installed = list_installed_models(ollama_url)
    default_model = current_cfg.get("ollama_model", "llama3")
    if installed:
        print(f"\nModels already installed: {', '.join(installed)}")
    model = input(f"\nWhich model should this agent use? [{default_model}] ").strip() or default_model

    if not any(model in m for m in installed):
        do_pull = input(f"'{model}' isn't installed yet. Pull it now (free, one time)? [Y/n] ").strip().lower()
        if do_pull in ("", "y", "yes"):
            ok = pull_model(model)
            if not ok:
                print(f"Pull failed or was interrupted. You can retry later with: ollama pull {model}")

    current_cfg["ollama_url"] = ollama_url
    current_cfg["ollama_model"] = model
    return current_cfg


def setup_wordpress(current_cfg: dict) -> dict:
    step(2, 4, "WordPress publishing (optional right now)")
    print("Posts get created as WordPress drafts and only go live when you")
    print("explicitly confirm with /publish. This uses WordPress's built-in")
    print("Application Passwords feature — free, no plugin required.\n")

    do_now = input("Set up WordPress publishing now? [Y/n] ").strip().lower()
    if do_now not in ("", "y", "yes"):
        print("Skipping — you can re-run `python3 setup.py` any time, or just use "
              "/post and /review without publishing for now.")
        return current_cfg

    print("\nTo generate an Application Password:")
    print("  1. Log into your WordPress site's admin dashboard.")
    print("  2. Go to Users -> Profile (or Users -> your username).")
    print("  3. Scroll to 'Application Passwords', enter a name like 'founder-agent',")
    print("     and click 'Add New Application Password'.")
    print("  4. Copy the generated password (it's only shown once).")

    wp_url = input("\nYour WordPress site URL (e.g. https://yourcompany.com): ").strip()
    wp_user = input("Your WordPress username: ").strip()
    wp_app_password = getpass.getpass("Paste the Application Password (hidden as you type): ").strip()

    if wp_url and wp_user and wp_app_password:
        print("\nTesting connection...")
        try:
            ok = wordpress.test_connection(wp_url, wp_user, wp_app_password)
        except Exception as e:
            ok = False
            print(f"Connection test error: {e}")
        if ok:
            print("Connected successfully.")
            current_cfg["wp_url"] = wp_url
            current_cfg["wp_user"] = wp_user
            current_cfg["wp_app_password"] = wp_app_password
        else:
            print("Couldn't authenticate with those details. Nothing was saved for WordPress;")
            print("re-run `python3 setup.py` once you've double-checked the URL/username/password.")
    else:
        print("Incomplete — skipping WordPress setup for now.")

    return current_cfg


def setup_searxng(current_cfg: dict) -> dict:
    step(3, 4, "Web research for /more-technical")
    print("The /more-technical command can use live web sources through a local")
    print("SearXNG instance. SearXNG is free, open source, and runs directly on")
    print("your machine — Docker is not required. The README has the complete setup.\n")
    default_url = current_cfg.get("searxng_url", "http://localhost:8888")
    url = input(f"SearXNG URL [{default_url}]: ").strip() or default_url
    default_dir = current_cfg.get("searxng_source_dir", "")
    source_dir = input(f"SearXNG source folder [{default_dir}]: ").strip() or default_dir
    settings_dir = current_cfg.get("searxng_settings_dir", "")
    print("Preparing the local SearXNG settings and starting it...")
    command = "mise exec python@3.11 -- make run"
    _, message = research.ensure_bare_metal_instance(url, source_dir, command, settings_dir)
    print(message)
    print("Testing SearXNG search API...")
    if research.check_connection(url):
        print("Connected. Research-backed technical revisions are ready.")
        current_cfg["searxng_url"] = url
    else:
        print("Couldn't reach a JSON-enabled SearXNG API at that address. The rest of")
        print("the app will work normally; re-run setup once SearXNG is running.")
        current_cfg["searxng_url"] = url
    current_cfg["searxng_autostart"] = True
    current_cfg["searxng_start_mode"] = "bare_metal"
    current_cfg["searxng_source_dir"] = source_dir
    current_cfg["searxng_launch_command"] = command
    current_cfg["searxng_settings_dir"] = settings_dir
    print("Founder Voice will start SearXNG from this folder automatically at launch.")
    return current_cfg


def setup_data_dirs():
    step(4, 4, "Local data folders")
    storage.ensure_dirs()
    print(f"Created (or confirmed) local data folders under: {cfg.DATA_DIR}")
    print(f"  - style_guide.md   your voice guide (open it any time with /style)")
    print(f"  - corpus/          pinned posts used to learn your voice over time")
    print(f"  - drafts/          every post you've generated, past and present")
    print(f"  - sessions/        a log of your conversations with the agent")


def run():
    print("=" * 60)
    print(" Founder Voice Agent — Guided Setup")
    print("=" * 60)
    print("This will take a few minutes. Everything set up here is free —")
    print("no subscriptions, no API keys, no paid services anywhere.")

    current_cfg = cfg.load_config()
    current_cfg = setup_ollama(current_cfg)
    current_cfg = setup_wordpress(current_cfg)
    current_cfg = setup_searxng(current_cfg)
    cfg.save_config(current_cfg)
    setup_data_dirs()

    print()
    line()
    print("Setup complete.")
    line()
    print("Start the agent with:")
    print("  python3 main.py")
    print("\nThen just type a raw take on a topic to draft your first post, or")
    print("type /help to see everything it can do.")


if __name__ == "__main__":
    run()
