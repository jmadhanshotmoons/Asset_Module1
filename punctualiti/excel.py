"""Shared Excel helpers: header normalisation, template limits and in-cell highlighting."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from openpyxl.comments import Comment
from openpyxl.styles import PatternFill

RED = "red"      # reviewer must fix
AMBER = "amber"  # tool changed or inferred a value; reviewer should confirm

FILLS = {
    RED: PatternFill(fill_type="solid", start_color="FFFF9999", end_color="FFFF9999"),
    AMBER: PatternFill(fill_type="solid", start_color="FFFFE699", end_color="FFFFE699"),
}
AUTHOR = "Punctualiti Cleaner"


def norm_header(text) -> str:
    """'Asset Name(Max-120 characters) *' -> 'asset name'."""
    s = str(text or "")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("*", " ").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def display_header(text) -> str:
    """'Asset Name(Max-120 characters) *' -> 'Asset Name'. Used as the column key."""
    s = re.sub(r"\((?:max|Max)[^)]*\)", "", str(text or ""))
    s = re.sub(r"\((?:dd|DD)[^)]*\)", "", s)
    s = s.replace("*", "")
    return " ".join(s.split())


@dataclass
class TemplateColumn:
    index: int          # 1-based column number in the template
    header: str         # exact header text in the template
    key: str            # display_header(), e.g. 'Asset Name'
    required: bool
    max_chars: int | None = None
    max_digits: int | None = None
    is_date: bool = False

    @classmethod
    def from_header(cls, index: int, header: str) -> "TemplateColumn":
        chars = re.search(r"max-\s*(\d+)\s*char", header, re.I)
        digits = re.search(r"max-\s*(\d+)\s*digit", header, re.I)
        return cls(
            index=index,
            header=header,
            key=display_header(header),
            required="*" in header,
            max_chars=int(chars.group(1)) if chars else None,
            max_digits=int(digits.group(1)) if digits else None,
            is_date="dd-mm-yyyy" in header.lower(),
        )


@dataclass
class Issue:
    level: str
    note: str


@dataclass
class Highlighter:
    """Collects highlights per (row, column) and writes them onto a sheet."""
    cells: dict[tuple[int, int], list[Issue]] = field(default_factory=dict)

    def mark(self, row: int, col: int, level: str, note: str) -> None:
        self.cells.setdefault((row, col), []).append(Issue(level, note))

    def apply(self, ws) -> None:
        for (row, col), issues in self.cells.items():
            cell = ws.cell(row=row, column=col)
            level = RED if any(i.level == RED for i in issues) else AMBER
            cell.fill = FILLS[level]
            text = "\n".join(f"[{'FIX' if i.level == RED else 'CHECK'}] {i.note}" for i in issues)
            cell.comment = Comment(text, AUTHOR, width=320, height=110)

    def counts(self) -> dict[str, int]:
        out = {RED: 0, AMBER: 0}
        for issues in self.cells.values():
            out[RED if any(i.level == RED for i in issues) else AMBER] += 1
        return out

    def notes_summary(self) -> dict[str, int]:
        """Issue note (with specific values removed) -> number of cells."""
        out: dict[str, int] = {}
        for issues in self.cells.values():
            for i in issues:
                key = re.sub(r"'[^']*'", "'...'", i.note)
                key = re.sub(r"\d+", "N", key)
                out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))
