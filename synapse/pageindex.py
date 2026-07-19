"""
PageIndex-style structure-aware document navigator (POC).

Not VectifyAI PageIndex — same architectural role: layout/heading tree so
retrieval can route to leaf sections without a dense vector monoculture.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional
from uuid import uuid4

_HEADING = re.compile(
    r"^(#{1,6})\s+(.+)$"  # markdown
    r"|^([A-Z][A-Z0-9 /_-]{2,60})$"  # ALL CAPS line
    r"|^(\d+(?:\.\d+)*)\s+([A-Z].{2,80})$",  # 1.2 Title
    re.MULTILINE,
)
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_NUM_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$", re.MULTILINE)
_CAPS_HEADING = re.compile(r"^([A-Z][A-Z0-9][A-Z0-9 /_-]{1,58})$", re.MULTILINE)


@dataclass
class DocNode:
    node_id: str
    title: str
    level: int
    start_line: int
    end_line: int
    text: str
    children: list["DocNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "level": self.level,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "char_len": len(self.text),
            "preview": self.text[:160].replace("\n", " "),
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class DocTree:
    doc_id: str
    title: str
    roots: list[DocNode]
    line_count: int
    backend: str = "pageindex_lite"

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "backend": self.backend,
            "line_count": self.line_count,
            "roots": [r.to_dict() for r in self.roots],
        }

    def flatten(self) -> list[DocNode]:
        out: list[DocNode] = []

        def walk(n: DocNode) -> None:
            out.append(n)
            for c in n.children:
                walk(c)

        for r in self.roots:
            walk(r)
        return out


class PageIndexLite:
    """Build a section tree and route queries to best leaves by keyword score."""

    name = "pageindex_lite"

    def build(self, text: str, *, title: str = "document", doc_id: Optional[str] = None) -> DocTree:
        lines = text.replace("\r\n", "\n").split("\n")
        headings: list[tuple[int, int, str]] = []  # (line_idx, level, title)

        for i, line in enumerate(lines):
            s = line.strip()
            if not s:
                continue
            m = _MD_HEADING.match(s)
            if m:
                headings.append((i, len(m.group(1)), m.group(2).strip()))
                continue
            m = _NUM_HEADING.match(s)
            if m:
                depth = m.group(1).count(".") + 1
                headings.append((i, min(depth, 6), m.group(2).strip()))
                continue
            m = _CAPS_HEADING.match(s)
            if m and len(s.split()) <= 8:
                headings.append((i, 2, m.group(1).strip()))

        if not headings:
            # Single leaf document
            node = DocNode(
                node_id=str(uuid4()),
                title=title,
                level=1,
                start_line=0,
                end_line=len(lines) - 1,
                text=text,
            )
            return DocTree(
                doc_id=doc_id or str(uuid4()),
                title=title,
                roots=[node],
                line_count=len(lines),
            )

        # Build nodes with content slices
        nodes: list[DocNode] = []
        for idx, (line_i, level, htitle) in enumerate(headings):
            end = headings[idx + 1][0] - 1 if idx + 1 < len(headings) else len(lines) - 1
            chunk = "\n".join(lines[line_i : end + 1]).strip()
            nodes.append(
                DocNode(
                    node_id=str(uuid4()),
                    title=htitle,
                    level=level,
                    start_line=line_i,
                    end_line=end,
                    text=chunk,
                )
            )

        # Nest by level stack
        roots: list[DocNode] = []
        stack: list[DocNode] = []
        for node in nodes:
            while stack and stack[-1].level >= node.level:
                stack.pop()
            if not stack:
                roots.append(node)
            else:
                stack[-1].children.append(node)
            stack.append(node)

        return DocTree(
            doc_id=doc_id or str(uuid4()),
            title=title,
            roots=roots,
            line_count=len(lines),
        )

    def route(
        self,
        tree: DocTree,
        query: str,
        *,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Score leaves by keyword overlap; return top_k sections."""
        q_tokens = {t.lower() for t in re.findall(r"[a-zA-Z0-9_-]+", query) if len(t) > 2}
        if not q_tokens:
            leaves = [n for n in tree.flatten() if not n.children] or tree.flatten()
            return [
                {
                    "score": 0.0,
                    "node": leaves[0].to_dict() if leaves else None,
                    "route": "default_first_leaf",
                }
            ]

        scored: list[tuple[float, DocNode]] = []
        for node in tree.flatten():
            blob = (node.title + "\n" + node.text).lower()
            hits = sum(1 for t in q_tokens if t in blob)
            if hits:
                score = hits / len(q_tokens)
                # Prefer deeper/more specific nodes slightly
                score += 0.05 * min(node.level, 4)
                scored.append((score, node))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, node in scored[:top_k]:
            out.append(
                {
                    "score": round(score, 4),
                    "node": node.to_dict(),
                    "route": "keyword_leaf",
                }
            )
        if not out:
            leaves = [n for n in tree.flatten() if not n.children] or tree.flatten()
            if leaves:
                out.append(
                    {
                        "score": 0.0,
                        "node": leaves[0].to_dict(),
                        "route": "fallback_leaf",
                    }
                )
        return out
