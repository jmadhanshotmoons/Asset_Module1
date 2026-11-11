"""Match a client's column headers to a Punctualiti template's columns."""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from .excel import TemplateColumn, norm_header

EXACT, SYNONYM, FUZZY = "exact", "synonym", "fuzzy"
FUZZY_CUTOFF = 0.85


@dataclass
class ColumnMap:
    found: dict[str, tuple[int, str, str]] = field(default_factory=dict)  # key -> (client col idx 0-based, how, client header)
    unmapped: list[str] = field(default_factory=list)                    # client headers not used
    header_row: int = 1                                                  # 1-based row of the client headers

    def missing(self, columns: list[TemplateColumn]) -> list[TemplateColumn]:
        return [c for c in columns if c.key not in self.found]


def map_columns(client_headers: list, columns: list[TemplateColumn], synonyms: dict[str, list[str]]) -> ColumnMap:
    result = ColumnMap()
    targets = {norm_header(c.key): c.key for c in columns}
    syn = {norm_header(s): key for key, words in synonyms.items() for s in words}
    taken: set[str] = set()

    normed = [(i, norm_header(h), str(h).strip()) for i, h in enumerate(client_headers) if h not in (None, "")]

    # Pass 1: exact matches win over everything else, so 'Room' beats a 'Location' synonym.
    for i, n, raw in normed:
        key = targets.get(n)
        if key and key not in taken:
            result.found[key] = (i, EXACT, raw)
            taken.add(key)
    used = {v[0] for v in result.found.values()}

    # Pass 2: synonyms from config/asset_rules.json.
    for i, n, raw in normed:
        if i in used:
            continue
        key = syn.get(n)
        if key and key not in taken:
            result.found[key] = (i, SYNONYM, raw)
            taken.add(key)
            used.add(i)

    # Pass 3: close spellings ('Asset Nmae'). Always shown to the reviewer.
    for i, n, raw in normed:
        if i in used:
            continue
        free = {t: k for t, k in targets.items() if k not in taken}
        match = difflib.get_close_matches(n, list(free), n=1, cutoff=FUZZY_CUTOFF)
        if match:
            key = free[match[0]]
            result.found[key] = (i, FUZZY, raw)
            taken.add(key)
            used.add(i)

    result.unmapped = [raw for i, _, raw in normed if i not in used]
    return result


def find_header_row(rows: list[tuple], columns: list[TemplateColumn], synonyms: dict, scan: int = 10) -> tuple[int, ColumnMap]:
    """Client files sometimes have title rows above the headers: use the row that maps best."""
    best = (0, ColumnMap())
    for r, row in enumerate(rows[:scan]):
        cmap = map_columns(list(row), columns, synonyms)
        if len(cmap.found) > len(best[1].found):
            cmap.header_row = r + 1
            best = (r, cmap)
    return best
