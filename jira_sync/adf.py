"""Markdown to Atlassian Document Format (ADF), a pure-function module.

Supports the subset the plugin writes: headings, paragraphs, bullet and
ordered lists, fenced code blocks, and the inline marks bold, inline code and
links. Anything else (tables, block quotes, nested structure) is kept as
plain paragraph text; nothing is dropped. ADF rejects empty text nodes, so
none is ever emitted.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(\S.*)$")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(\S.*)$")
_FENCE = re.compile(r"^\s*```\s*(\S*)")
_INLINE = re.compile(
    r"\*\*(?P<bold>\S(?:.*?\S)?)\*\*"
    r"|`(?P<code>[^`]+)`"
    r"|\[(?P<label>[^\]]+)\]\((?P<href>[^)\s]+)\)"
)

Node = Dict[str, Any]


def _text(value: str, mark: Optional[Node] = None) -> Node:
    node: Node = {"type": "text", "text": value}
    if mark is not None:
        node["marks"] = [mark]
    return node


def _inline(value: str) -> List[Node]:
    out: List[Node] = []
    pos = 0
    for m in _INLINE.finditer(value):
        if m.start() > pos:
            out.append(_text(value[pos:m.start()]))
        if m.group("bold") is not None:
            out.append(_text(m.group("bold"), {"type": "strong"}))
        elif m.group("code") is not None:
            out.append(_text(m.group("code"), {"type": "code"}))
        else:
            out.append(
                _text(
                    m.group("label"),
                    {"type": "link", "attrs": {"href": m.group("href")}},
                )
            )
        pos = m.end()
    if pos < len(value):
        out.append(_text(value[pos:]))
    return out


def _paragraph(value: str) -> Node:
    return {"type": "paragraph", "content": _inline(value)}


def _list(kind: str, items: List[str]) -> Node:
    return {
        "type": kind,
        "content": [
            {"type": "listItem", "content": [_paragraph(item)]} for item in items
        ],
    }


def _code_block(language: str, lines: List[str]) -> Node:
    node: Node = {"type": "codeBlock"}
    if language:
        node["attrs"] = {"language": language}
    body = "\n".join(lines)
    if body:
        node["content"] = [_text(body)]
    return node


def markdown_to_adf(text: str) -> dict:
    blocks: List[Node] = []
    para: List[str] = []

    def flush_para() -> None:
        if para:
            blocks.append(_paragraph(" ".join(para)))
            para.clear()

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        stripped = line.strip()

        fence = _FENCE.match(line)
        if fence:
            flush_para()
            body: List[str] = []
            while i < len(lines) and lines[i].strip() != "```":
                body.append(lines[i])
                i += 1
            i += 1  # the closing fence; absent means closed at end of input
            blocks.append(_code_block(fence.group(1), body))
            continue

        if not stripped:
            flush_para()
            continue

        heading = _HEADING.match(stripped)
        if heading:
            flush_para()
            blocks.append(
                {
                    "type": "heading",
                    "attrs": {"level": len(heading.group(1))},
                    "content": _inline(heading.group(2).strip()),
                }
            )
            continue

        for pattern, kind in ((_BULLET, "bulletList"), (_ORDERED, "orderedList")):
            match = pattern.match(line)
            if match:
                flush_para()
                items = [match.group(1).strip()]
                while i < len(lines):
                    nxt = pattern.match(lines[i])
                    if not nxt:
                        break
                    items.append(nxt.group(1).strip())
                    i += 1
                blocks.append(_list(kind, items))
                break
        else:
            if stripped.startswith("|"):
                # Table rows keep their characters, one paragraph per row.
                flush_para()
                blocks.append(_paragraph(stripped))
            else:
                para.append(stripped)

    flush_para()
    return {"type": "doc", "version": 1, "content": blocks}


def _plain(node: Node) -> str:
    if node.get("type") == "text":
        return node.get("text", "")
    return "".join(_plain(child) for child in node.get("content", []))


def adf_lines(node: dict) -> List[str]:
    """The text of each top-level paragraph or heading, one string each."""
    return [
        _plain(block)
        for block in node.get("content", [])
        if block.get("type") in ("paragraph", "heading")
    ]
