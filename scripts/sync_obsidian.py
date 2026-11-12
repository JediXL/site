#!/usr/bin/env python3
"""Sync selected Obsidian notes into Hugo posts.

The Obsidian note is the source of the article body. Hugo front matter in the
blog file is kept, except date: a real content change sets date to the current
time in Asia/Shanghai. Wikilinks become ordinary links when the target note
has a source URL.
"""

from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
VAULT = Path(
    "/Users/liujiadi/Library/Mobile Documents/iCloud~md~obsidian/Documents/Notes"
)

# Evergreen notes stay on their original paths. The wasteland folder is where
# new essays are written; those are created on the blog when they do not exist yet.
WASTELAND = VAULT / "🔥 浓雾荒原"
POSTS_DIR = ROOT / "content/posts"
EVERGREEN_STEMS = {"好东西", "它山之石", "流水残心"}
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}

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
    (
        VAULT / "🌊  流水残心.md",
        ROOT / "content/posts/流水残心.md",
    ),
]

WIKILINK = re.compile(r"\[\[([^\[\]|#]+?)(#[^\[\]|]+)?(?:\|([^\[\]]+))?\]\]")
PROPERTY = re.compile(r"^- [^:\n]+:.*$")
SOURCE_URL = re.compile(r'(?m)^source:\s*"?(https?://[^"\s]+)"?\s*$')
DATE_LINE = re.compile(r"(?m)^date:.*$")
PRIVATE_TAG = re.compile(r"(?<!\S)#私密(?:/[^\s#/]+)*(?!\S)")
ENTRY_LEAD = r"\s*(?:[-*+]|\d+\.)[ \t]+(?:\[[ xX]\][ \t]+)?"
ENTRY_TIME = re.compile(
    rf"""^
    (?P<lead>{ENTRY_LEAD})?
    (?P<time>
        \d{{1,2}}:\d{{2}}
        (?:[ \t\u00a0\u202f]*[AaPp][Mm])?
        [ \t\u00a0\u202f]*
        [:：]?
    )
    """,
    re.VERBOSE,
)
LIST_LEAD = re.compile(rf"^(?:{ENTRY_LEAD})")
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


def strip_property_block(body: str) -> str:
    lines = body.splitlines()
    index = 0
    while index < len(lines) and lines[index].strip() == "":
        index += 1
    start = index
    while index < len(lines) and PROPERTY.match(lines[index]):
        index += 1
    if index == start:
        return body
    while index < len(lines) and lines[index].strip() == "":
        index += 1
    if index < len(lines) and lines[index].strip() == "---":
        return "\n".join(lines[index + 1 :]).strip()
    return body


def block_bar(text: str) -> str:
    count = len(re.sub(r"\s+", "", text))
    return "█" * max(count, 4)


def kept_prefix(text: str) -> str:
    timed = ENTRY_TIME.match(text)
    if timed and timed.group("time"):
        return timed.group(0)
    listed = LIST_LEAD.match(text)
    if listed:
        return listed.group(0)
    return re.match(r"\s*", text).group(0)


def redact_text(text: str) -> str:
    prefix = kept_prefix(text)
    hidden = PRIVATE_TAG.sub("", text[len(prefix) :])
    bar = block_bar(hidden)
    if prefix.strip():
        return prefix.rstrip() + " " + bar
    return prefix + bar


def redact_private_line(line: str) -> str:
    if line.strip().startswith("|"):
        cells = []
        for cell in line.split("|"):
            if PRIVATE_TAG.search(cell):
                cells.append(" " + redact_text(cell.strip()) + " ")
            else:
                cells.append(cell)
        return "|".join(cells)
    return redact_text(line)


def redact_private(body: str) -> str:
    return "\n".join(
        redact_private_line(line) if PRIVATE_TAG.search(line) else line
        for line in body.splitlines()
    )


def convert_body(text: str, notes: dict[str, Path]) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    body = strip_property_block("\n".join(lines).strip())

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


def note_stem(path: Path) -> str:
    return path.parent.name if path.name == "index.md" else path.stem


def blog_target(source: Path) -> Path:
    stem = note_stem(source)
    bundled = POSTS_DIR / stem / "index.md"
    if source.name == "index.md" or bundled.exists():
        return bundled
    return POSTS_DIR / f"{stem}.md"


def split_note(text: str) -> tuple[str | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    return text[: end + 5], text[end + 5 :]


def yaml_title(value: str) -> str:
    if re.search(r'[:#"\']', value) or value.strip() != value:
        return '"' + value.replace('"', '\\"') + '"'
    return value


def normalize_tags(front: str) -> str:
    lines: list[str] = []
    for line in front.splitlines():
        match = re.match(r"^(\s+-\s+)(.+)$", line)
        if match:
            value = match.group(2).strip().strip("\"'")
            value = value[1:].strip() if value.startswith("#") else value
            line = match.group(1) + value
        lines.append(line)
    return "\n".join(lines) + "\n"


def default_front(title: str) -> str:
    return (
        "---\n"
        f"title: {yaml_title(title)}\n"
        f"date: {now_stamp()}\n"
        "draft: false\n"
        "tags:\n"
        "  - 回旋的阶梯\n"
        "summary:\n"
        "---\n"
    )


def note_front_and_body(text: str, notes: dict[str, Path], title: str) -> tuple[str, str]:
    front, rest = split_note(text)
    if front is None:
        heading = ""
        for line in rest.splitlines():
            if line.startswith("# "):
                heading = line[2:].strip()
                break
        front = default_front(heading or title)
    else:
        front = normalize_tags(front)
    return front, convert_body(rest, notes)


def copy_media(source: Path, target: Path) -> None:
    if source.name != "index.md":
        return
    for item in source.parent.iterdir():
        if item.name.startswith("."):
            continue
        if item.suffix.lower() not in MEDIA_SUFFIXES and not (
            item.is_dir() and item.name == "images"
        ):
            continue
        dest = target.parent / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or item.stat().st_mtime > dest.stat().st_mtime:
                shutil.copy2(item, dest)


def sync_wasteland(source: Path, notes: dict[str, Path]) -> None:
    if note_stem(source) in EVERGREEN_STEMS:
        return
    target = blog_target(source)
    text = source.read_text(encoding="utf-8")
    front, body = note_front_and_body(text, notes, note_stem(source))
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{front}\n{body}\n", encoding="utf-8")
        copy_media(source, target)
        print(f"created {target.relative_to(ROOT)}")
        return
    current = target.read_text(encoding="utf-8")
    front = split_front_matter(current)
    if current[len(front) :].strip() == body.strip():
        print(f"unchanged {target.relative_to(ROOT)}")
        return
    if source.stat().st_mtime <= target.stat().st_mtime:
        print(f"kept newer blog copy {target.relative_to(ROOT)}")
        return
    target.write_text(f"{replace_date(front)}\n{body}\n", encoding="utf-8")
    copy_media(source, target)
    print(f"updated {target.relative_to(ROOT)}")


def sync_one(source: Path, target: Path, notes: dict[str, Path]) -> bool:
    if not source.is_file():
        raise SystemExit(f"找不到 Obsidian 笔记：{source}")
    current = target.read_text(encoding="utf-8")
    front = split_front_matter(current)
    body = convert_body(source.read_text(encoding="utf-8"), notes)
    if "流水残心" in source.stem:
        body = redact_private(body)
    if current[len(front) :].strip() == body:
        print(f"unchanged {target.relative_to(ROOT)}")
        return False
    updated = f"{replace_date(front)}\n{body}\n"
    target.write_text(updated, encoding="utf-8")
    print(f"updated {target.relative_to(ROOT)}")
    return True


def main() -> int:
    if not WASTELAND.is_dir():
        raise SystemExit(f"找不到浓雾荒原文件夹：{WASTELAND}")
    notes = note_index(VAULT)
    for source, target in POSTS:
        sync_one(source, target, notes)
    for source in sorted(WASTELAND.rglob("*.md")):
        if any(part in SKIP_DIRS for part in source.parts):
            continue
        if source.name == "_index.md":
            continue
        sync_wasteland(source, notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
