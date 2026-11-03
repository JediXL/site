#!/usr/bin/env python3
"""Sync selected Obsidian notes into Hugo posts.

The Obsidian note is the source of the article body. Hugo front matter in the
blog file is kept, except date: a real content change sets date to the current
time in Asia/Shanghai. Wikilinks become ordinary links when the target note
has a source URL.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
VAULT = Path(
    "/Users/liujiadi/Library/Mobile Documents/iCloud~md~obsidian/Documents/Notes"
)

# source note -> blog post. The blog file must already contain Hugo front matter.
POSTS = [
    (
        VAULT / "❤️‍🔥 好东西.md",
        ROOT / "content/posts/好东西.md",
    ),
    (
        VAULT / "🪨 它山之石.md",
        ROOT / "content/posts/它山之石.md",
    ),
]

WIKILINK = re.compile(r"\[\[([^\[\]|#]+?)(#[^\[\]|]+)?(?:\|([^\[\]]+))?\]\]")
SOURCE_URL = re.compile(r'(?m)^source:\s*"?(https?://[^"\s]+)"?\s*$')
DATE_LINE = re.compile(r"(?m)^date:.*$")
SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules"}


def note_index(vault: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in vault.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        found.setdefault(path.stem, path)
    return found


def source_url(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = SOURCE_URL.search(text)
    return match.group(1) if match else None


def convert_body(text: str, notes: dict[str, Path]) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    body = "\n".join(lines).strip()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        label = (match.group(3) or name).strip()
        target = notes.get(name)
        url = source_url(target) if target else None
        if url:
            return f"[{label}]({url})"
        return label

    return WIKILINK.sub(replace, body)


def split_front_matter(text: str) -> str:
    if not text.startswith("---\n"):
        raise SystemExit("博客文章缺少文章头，无法同步。")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise SystemExit("博客文章的文章头没有结束。")
    return text[: end + 5]


def now_stamp() -> str:
    raw = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%dT%H:%M:%S%z")
    return raw[:-2] + ":" + raw[-2:]


def replace_date(front: str) -> str:
    if not DATE_LINE.search(front):
        raise SystemExit("博客文章缺少 date。")
    return DATE_LINE.sub(f"date: {now_stamp()}", front, count=1)


def sync_one(source: Path, target: Path, notes: dict[str, Path]) -> bool:
    if not source.is_file():
        raise SystemExit(f"找不到 Obsidian 笔记：{source}")
    current = target.read_text(encoding="utf-8")
    front = split_front_matter(current)
    body = convert_body(source.read_text(encoding="utf-8"), notes)
    if current[len(front) :].strip() == body:
        print(f"unchanged {target.relative_to(ROOT)}")
        return False
    updated = f"{replace_date(front)}\n{body}\n"
    target.write_text(updated, encoding="utf-8")
    print(f"updated {target.relative_to(ROOT)}")
    return True


def main() -> int:
    notes = note_index(VAULT)
    for source, target in POSTS:
        sync_one(source, target, notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
