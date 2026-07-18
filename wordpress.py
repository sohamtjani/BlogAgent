"""
WordPress publishing via its built-in REST API + a free Application Password
(no plugin purchase, no SaaS scheduler). New posts are always created as
drafts — nothing ever goes live without an explicit /publish confirm.
"""
import base64
import html
import re

import requests


class WordPressError(RuntimeError):
    pass


def _auth_header(wp_user: str, wp_app_password: str) -> dict:
    token = base64.b64encode(f"{wp_user}:{wp_app_password}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def markdown_to_html(md: str) -> str:
    """Minimal, dependency-free markdown->HTML conversion (headings, paragraphs, bullets)."""
    lines_out = []
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("## "):
            lines_out.append(f"<h2>{_inline_markdown(s[3:].strip())}</h2>")
        elif s.startswith("# "):
            lines_out.append(f"<h1>{_inline_markdown(s[2:].strip())}</h1>")
        elif s.startswith("- "):
            lines_out.append(f"<li>{_inline_markdown(s[2:].strip())}</li>")
        elif s == "":
            lines_out.append("")
        else:
            lines_out.append(f"<p>{_inline_markdown(s)}</p>")
    return "\n".join(lines_out)


def _inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<a href="\2" rel="noopener noreferrer">\1</a>', escaped,
    )


def test_connection(wp_url: str, wp_user: str, wp_app_password: str) -> bool:
    resp = requests.get(
        f"{wp_url.rstrip('/')}/wp-json/wp/v2/users/me",
        headers=_auth_header(wp_user, wp_app_password),
        timeout=15,
    )
    return resp.status_code == 200


def create_draft_post(wp_url: str, wp_user: str, wp_app_password: str,
                       title: str, body_markdown: str, excerpt: str,
                       dry_run: bool = False) -> dict:
    if dry_run:
        return {"id": 0, "link": f"{wp_url or '<WP_URL not set>'}/?p=0&preview=true", "dry_run": True}

    endpoint = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts"
    data = {
        "title": title,
        "content": markdown_to_html(body_markdown),
        "excerpt": excerpt,
        "status": "draft",
    }
    resp = requests.post(endpoint, json=data, headers=_auth_header(wp_user, wp_app_password), timeout=30)
    if resp.status_code >= 300:
        raise WordPressError(f"WordPress API error {resp.status_code}: {resp.text}")
    result = resp.json()
    post_id = result["id"]
    preview_link = f"{wp_url.rstrip('/')}/?p={post_id}&preview=true"
    return {"id": post_id, "link": preview_link, "dry_run": False}


def update_existing_draft(wp_url: str, wp_user: str, wp_app_password: str, post_id: int,
                           title: str, body_markdown: str, excerpt: str,
                           dry_run: bool = False) -> dict:
    if dry_run:
        return {"id": post_id, "link": f"{wp_url or '<WP_URL not set>'}/?p={post_id}&preview=true", "dry_run": True}

    endpoint = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"
    data = {"title": title, "content": markdown_to_html(body_markdown), "excerpt": excerpt}
    resp = requests.post(endpoint, json=data, headers=_auth_header(wp_user, wp_app_password), timeout=30)
    if resp.status_code >= 300:
        raise WordPressError(f"WordPress API error {resp.status_code}: {resp.text}")
    preview_link = f"{wp_url.rstrip('/')}/?p={post_id}&preview=true"
    return {"id": post_id, "link": preview_link, "dry_run": False}


def publish_post(wp_url: str, wp_user: str, wp_app_password: str, post_id: int,
                  dry_run: bool = False) -> dict:
    """Flips an existing draft's status to 'publish'. This is the one call gated
    behind the /publish y/n confirm in main.py."""
    if dry_run:
        return {"id": post_id, "link": f"{wp_url or '<WP_URL not set>'}/?p={post_id}", "dry_run": True}

    endpoint = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"
    resp = requests.post(endpoint, json={"status": "publish"},
                          headers=_auth_header(wp_user, wp_app_password), timeout=30)
    if resp.status_code >= 300:
        raise WordPressError(f"WordPress API error {resp.status_code}: {resp.text}")
    result = resp.json()
    return {"id": post_id, "link": result.get("link"), "dry_run": False}
