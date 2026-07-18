"""Web research through a user-controlled SearXNG instance.

SearXNG finds candidate pages. This module then downloads the selected pages
and extracts readable text locally, so the writing model receives evidence
rather than relying on search-result snippets alone.
"""
from html.parser import HTMLParser
import os
import secrets
import shlex
import subprocess
import time
from urllib.parse import urlparse

import requests


class ResearchUnavailable(RuntimeError):
    pass


PREFERRED_DOMAINS = (
    "nrc.gov", "iaea.org", "oecd-nea.org", "energy.gov", "osti.gov",
    "gov", "edu", "org", "nature.com", "science.org", "ieee.org",
)


class _TextExtractor(HTMLParser):
    """Small dependency-free HTML-to-text fallback for ordinary article pages."""
    SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside"}
    BREAK_TAGS = {"p", "br", "li", "h1", "h2", "h3", "h4", "article", "section", "div"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
        elif not self.skip_depth and tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)

    def text(self):
        return " ".join("".join(self.parts).split())


def check_connection(searxng_url: str, timeout: int = 5) -> bool:
    try:
        response = requests.get(
            f"{searxng_url.rstrip('/')}/search",
            params={"q": "SearXNG", "format": "json"}, timeout=timeout,
        )
        return response.status_code == 200 and isinstance(response.json().get("results"), list)
    except (requests.RequestException, ValueError):
        return False


def _local_port(searxng_url: str):
    """Return a port only for a plain local HTTP address we can safely manage."""
    parsed = urlparse(searxng_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        return None
    try:
        return parsed.port or 80
    except ValueError:
        return None


def _docker(args: list):
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None


def ensure_local_instance(searxng_url: str, container_name: str,
                          timeout: int = 30) -> tuple:
    """Start (or first create) the app's local SearXNG Docker container.

    Remote endpoints are never managed. A running local endpoint is left alone,
    even if it was not created by this app.
    """
    if check_connection(searxng_url):
        return True, "SearXNG is ready."
    port = _local_port(searxng_url)
    if port is None:
        return False, "SearXNG is not reachable (the configured endpoint is not local)."

    inspect = _docker(["container", "inspect", container_name])
    if inspect is None:
        return False, "Docker Desktop is not installed or not available."
    if inspect.returncode == 0:
        launch = _docker(["start", container_name])
        action = "started"
    else:
        launch = _docker([
            "run", "-d", "--name", container_name, "-p", f"{port}:8080",
            "searxng/searxng:latest",
        ])
        action = "created"
    if launch is None or launch.returncode != 0:
        detail = (launch.stderr or launch.stdout).strip() if launch else ""
        return False, f"Could not {action} the local SearXNG container. {detail}".strip()

    deadline = time.time() + timeout
    while time.time() < deadline:
        if check_connection(searxng_url, timeout=3):
            return True, f"SearXNG {action} and ready."
        time.sleep(1)
    return False, "SearXNG started, but its JSON search API did not become ready."


def ensure_bare_metal_instance(searxng_url: str, source_dir: str,
                               launch_command: str, settings_dir: str,
                               timeout: int = 30) -> tuple:
    """Start an already-installed local SearXNG server without Docker."""
    if check_connection(searxng_url):
        return True, "SearXNG is ready."
    if not source_dir or not os.path.isdir(source_dir):
        return False, "SearXNG is not installed at the configured source directory."
    if not launch_command.strip():
        return False, "No bare-metal SearXNG launch command is configured."
    _write_settings_if_missing(settings_dir)
    try:
        environment = dict(os.environ)
        environment["SEARXNG_SETTINGS_PATH"] = settings_dir
        subprocess.Popen(
            shlex.split(launch_command), cwd=source_dir,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, env=environment,
        )
    except (OSError, ValueError) as exc:
        return False, f"Could not start local SearXNG: {exc}"

    deadline = time.time() + timeout
    while time.time() < deadline:
        if check_connection(searxng_url, timeout=3):
            return True, "SearXNG started and ready."
        time.sleep(1)
    return False, "SearXNG was launched, but its JSON search API did not become ready."


def _write_settings_if_missing(settings_dir: str):
    """Create the minimal local settings BlogAgent needs, without touching SearXNG source."""
    settings_path = os.path.join(settings_dir, "settings.yml")
    if os.path.exists(settings_path):
        return
    os.makedirs(settings_dir, exist_ok=True)
    contents = f'''use_default_settings: true

search:
  formats:
    - html
    - json

server:
  bind_address: "127.0.0.1"
  port: 8888
  secret_key: "{secrets.token_urlsafe(32)}"
  limiter: false
'''
    with open(settings_path, "w", encoding="utf-8") as settings_file:
        settings_file.write(contents)


def search(searxng_url: str, query: str, timeout: int = 15) -> list:
    try:
        response = requests.get(
            f"{searxng_url.rstrip('/')}/search",
            params={"q": query, "format": "json", "categories": "general"},
            timeout=timeout,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except (requests.RequestException, ValueError) as exc:
        raise ResearchUnavailable(f"Could not search via SearXNG at {searxng_url}: {exc}")
    return [result for result in results if result.get("url", "").startswith(("http://", "https://"))]


def _domain_score(url: str) -> int:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return max((len(domain) for domain in PREFERRED_DOMAINS if host == domain or host.endswith(f".{domain}")), default=0)


def _candidate_results(queries: list, searxng_url: str, timeout: int) -> list:
    candidates, seen_urls = [], set()
    for query in queries:
        for result in search(searxng_url, query, timeout):
            url = result["url"]
            normalized = url.split("#", 1)[0]
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            candidates.append({
                "title": result.get("title", "Untitled source").strip(),
                "url": normalized,
                "publisher": result.get("engine", "web"),
                "snippet": result.get("content", "").strip(),
                "query": query,
                "score": _domain_score(normalized),
            })
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def _fetch_text(url: str, timeout: int) -> str:
    try:
        response = requests.get(
            url, timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        response.raise_for_status()
    except requests.RequestException:
        return ""
    if "html" not in response.headers.get("Content-Type", "").lower():
        return ""
    parser = _TextExtractor()
    parser.feed(response.text)
    return parser.text()


def gather_research(queries: list, searxng_url: str, max_sources: int = 5,
                    timeout: int = 15, dry_run: bool = False) -> list:
    """Return source packets with page excerpts suitable for an LLM prompt."""
    if dry_run:
        return [{
            "id": 1,
            "title": "Dry-run example technical source",
            "url": "https://example.org/technical-source",
            "publisher": "example.org",
            "snippet": "Placeholder search result.",
            "query": queries[0] if queries else "example query",
            "excerpt": "[DRY RUN] Placeholder source text. No network request was made.",
        }]

    candidates = _candidate_results(queries, searxng_url, timeout)
    sources, seen_domains = [], set()
    for candidate in candidates:
        domain = urlparse(candidate["url"]).netloc.lower()
        if domain in seen_domains:
            continue
        text = _fetch_text(candidate["url"], timeout)
        excerpt = text[:3000]
        retrieval = "page"
        if len(text) < 400 and len(candidate["snippet"]) >= 120:
            excerpt = candidate["snippet"]
            retrieval = "search_snippet"
        if len(excerpt) < 120:
            continue
        seen_domains.add(domain)
        candidate.pop("score", None)
        candidate["id"] = len(sources) + 1
        candidate["excerpt"] = excerpt
        candidate["retrieval"] = retrieval
        sources.append(candidate)
        if len(sources) >= max_sources:
            break
    return sources
