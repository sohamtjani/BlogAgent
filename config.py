"""
Config loading — a single local JSON file, no environment/server config needed.
Zero cost: nothing here talks to a paid service. Ollama runs locally; WordPress
is whatever site the founder already owns/hosts.
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",
    "wp_url": "",
    "wp_user": "",
    "wp_app_password": "",
}


def config_exists() -> bool:
    return os.path.exists(CONFIG_PATH)


def load_config() -> dict:
    if not config_exists():
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    return merged


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
