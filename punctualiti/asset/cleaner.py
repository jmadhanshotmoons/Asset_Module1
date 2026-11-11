"""Module 1: turn a client asset list into Punctualiti's standard asset template.

Every change the tool is not sure about is left visible in the output cell:
  red   = the reviewer must fix it (missing, unreadable, conflicting)
  amber = the tool changed or inferred it; the reviewer should confirm
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from .. import ai, config
from ..columns import EXACT, FUZZY, SYNONYM, ColumnMap, find_header_row
from ..excel import AMBER, RED, Highlighter, TemplateColumn
from ..location import find_floors, normalise_building, split_location
from ..text import NA, clean_spaces, format_date, is_empty, normalise_name, number_text, smart_case
from ..units import split_capacity

DEFAULT_TEMPLATE = config.DATA_DIR / "asset_template.xlsx"

# Template column keys this module gives special treatment (see display_header()).
NAME, CATEGORY, SUBCATEGORY, ASSET_TYPE = "Asset Name", "Category", "Subcategory", "Asset Type"
BUILDING, WING, FLOOR, ROOM = "Building", "Wing", "Floor", "Room"
CAPACITY, UOM = "Capacity", "UOM"
CLASSIFICATION = (CATEGORY, SUBCATEGORY, ASSET_TYPE)


@dataclass
class CleanResult:
    content: bytes
    rows: int
    red_cells: int
    amber_cells: int
    column_report: list[dict]
    issue_summary: dict[str, int]
    unmapped_columns: list[str]
    ai_status: str
    header_row: int = 1
    warnings: list[str] = field(default_factory=list)


@dataclass
class Row:
    source_row: int
    values: dict[str, str] = field(default_factory=dict)
    marks: list[tuple[str, str, str]] = field(default_factory=list)  # (column key, level, note)

    def mark(self, key: str, level: str, note: str) -> None:
        self.marks.append((key, level, note))


# ---------------------------------------------------------------- loading

def _template_columns(ws) -> list[TemplateColumn]:
    return [TemplateColumn.from_header(c.column, str(c.value)) for c in ws[1] if c.value not in (None, "")]


def _pick_sheet(wb, columns, synonyms):
    """Use the sheet whose headers match the template best."""
    best = None
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(min_row=1, max_row=10, values_only=True))
        _, cmap = find_header_row(rows, columns, synonyms)
        if best is None or len(cmap.found) > len(best[1].found):
            best = (ws, cmap)
    return best


# ---------------------------------------------------------------- per-cell rules

def _match_allowed(value: str, allowed: list[str]) -> str | None:
    squash = lambda s: re.sub(r"[\s_-]+", "", s).lower()
    for a in allowed:
        if squash(a) == squash(value):
            return a
    return None


def _clean_classification(row: Row, key: str, raw, corrections: dict[str, str]) -> None:
    text = clean_spaces(raw)
    if not text or is_empty(text):
        row.values[key] = ""
        return
    fixed = corrections.get(text) or corrections.get(text.title())
    if fixed:
        row.mark(key, AMBER, f"Corrected '{text}' to '{fixed}'")
        text = fixed
    row.values[key] = smart_case(text)


def _process_row(raw: dict[str, object], src_row: int, columns: list[TemplateColumn], rules: dict) -> Row:
    row = Row(src_row)
    width = int(rules.get("name_number_width", 2))
    allowed = rules.get("allowed_values", {})
    corrections = {k: v for k, v in rules.get("value_corrections", {}).items() if not k.startswith("_")}

    # Asset name
    name = clean_spaces(raw.get(NAME))
    row.values[NAME] = normalise_name(name, width) if name else ""

    # Category / Subcategory / Asset Type: keep the client's words, tidy spacing and case only.
    for key in CLASSIFICATION:
        _clean_classification(row, key, raw.get(key), corrections)
    if row.values[ASSET_TYPE] and find_floors(row.values[ASSET_TYPE]):
        row.mark(ASSET_TYPE, RED, f"Asset Type '{row.values[ASSET_TYPE]}' looks like a location, not an equipment type")

    # Location
    building, b_note = normalise_building(raw.get(BUILDING)) if not is_empty(raw.get(BUILDING)) else ("", None)
    loc = split_location(building, "" if is_empty(raw.get(FLOOR)) else raw.get(FLOOR),
                         "" if is_empty(raw.get(ROOM)) else raw.get(ROOM))
    row.values[BUILDING], row.values[FLOOR], row.values[ROOM] = loc.building, loc.floor, loc.room
    if b_note:
        row.mark(BUILDING, AMBER, b_note)
    if loc.building_note:
        row.mark(BUILDING, AMBER, loc.building_note)
    if loc.floor_level:
        row.mark(FLOOR, loc.floor_level, loc.floor_note)
    if loc.room_note:
        row.mark(ROOM, AMBER, loc.room_note)
    wing = clean_spaces(raw.get(WING))
    row.values[WING] = smart_case(wing) if wing and not is_empty(wing) else ""

    # Capacity + UOM
    cap = split_capacity(raw.get(CAPACITY), raw.get(UOM))
    row.values[CAPACITY], row.values[UOM] = cap.value, cap.uom
    if cap.level:
        row.mark(CAPACITY, cap.level, cap.note)

    # Everything else
    handled = {NAME, *CLASSIFICATION, BUILDING, WING, FLOOR, ROOM, CAPACITY, UOM}
    for col in columns:
        if col.key in handled:
            continue
        value = raw.get(col.key)
        if is_empty(value):
            row.values[col.key] = ""
            continue
        if col.is_date:
            date = format_date(value)
            if date:
                row.values[col.key] = date
            else:
                row.values[col.key] = clean_spaces(value)
                row.mark(col.key, RED, f"'{clean_spaces(value)}' is not a date (dd-mm-yyyy)")
            continue
        text = number_text(value)
        if col.key in allowed:
            hit = _match_allowed(text, allowed[col.key])
            if hit:
                row.values[col.key] = hit
            else:
                row.values[col.key] = text
                row.mark(col.key, RED, f"'{text}' is not an allowed value ({', '.join(allowed[col.key])})")
            continue
        row.values[col.key] = text
    return row


def _finish_row(row: Row, columns: list[TemplateColumn]) -> None:
    """Required-field and length checks, then 'NA' for optional blanks (as the template does)."""
    for col in columns:
        v = row.values.get(col.key, "")
        if not v:
            if col.required:
                if col.key in CLASSIFICATION and any(k == col.key for k, _, _ in row.marks):
                    continue  # already explained by the AI step
                row.mark(col.key, RED, f"{col.key} is required but empty")
            else:
                row.values[col.key] = NA
            continue
        if v == NA:
            continue
        if col.max_chars and len(v) > col.max_chars:
            row.mark(col.key, RED, f"Longer than {col.max_chars} characters ({len(v)})")
        if col.max_digits and len(re.sub(r"\D", "", v)) > col.max_digits:
            row.mark(col.key, RED, f"More than {col.max_digits} digits")


# ---------------------------------------------------------------- filling gaps

def _base_name(name: str) -> str:
    return re.sub(r"[\s\-_.#]*(no\.?)?[\s\-_.#]*\d+$", "", name, flags=re.I).strip().lower()


def _fill_from_other_rows(rows: list[Row]) -> None:
    """A missing Category/Subcategory/Asset Type is filled only when every other row
    sharing a clue (same asset type, subcategory or base name) agrees on one value."""
    clues = {
        CATEGORY: [(ASSET_TYPE, "asset type"), (SUBCATEGORY, "subcategory"), ("_base", "asset name")],
        SUBCATEGORY: [("_base", "asset name"), (ASSET_TYPE, "asset type")],
        ASSET_TYPE: [(SUBCATEGORY, "subcategory"), ("_base", "asset name")],
    }

    def clue_value(r: Row, clue: str) -> str:
        return _base_name(r.values[NAME]) if clue == "_base" else r.values.get(clue, "").lower()

    for target, clue_list in clues.items():
        index: dict[tuple[str, str], set[str]] = {}
        for r in rows:
            if r.values.get(target):
                for clue, _ in clue_list:
                    cv = clue_value(r, clue)
                    if cv:
                        index.setdefault((clue, cv), set()).add(r.values[target])
        for r in rows:
            if r.values.get(target):
                continue
            for clue, label in clue_list:
                cv = clue_value(r, clue)
                options = index.get((clue, cv)) if cv else None
                if options and len(options) == 1:
                    r.values[target] = next(iter(options))
                    r.mark(target, AMBER, f"Filled from other rows with the same {label}")
                    break


def _fill_with_ai(rows: list[Row]) -> str:
    gaps = [r for r in rows if r.values.get(NAME) and any(not r.values.get(k) for k in CLASSIFICATION)]
    if not gaps:
        return "Not needed (no missing Category / Subcategory / Asset Type)"

    items = [{"id": str(i), "asset_name": r.values[NAME],
              "category": r.values[CATEGORY], "subcategory": r.values[SUBCATEGORY],
              "asset_type": r.values[ASSET_TYPE]} for i, r in enumerate(gaps)]
    seen, examples = set(), []
    for r in rows:
        triple = tuple(r.values.get(k, "") for k in CLASSIFICATION)
        if all(triple) and triple not in seen:
            seen.add(triple)
            examples.append({"asset_name": r.values[NAME], "category": triple[0],
                             "subcategory": triple[1], "asset_type": triple[2]})
        if len(examples) >= 40:
            break

    try:
        suggestions = ai.classify(items, examples)
    except ai.AIUnavailable as e:
        for r in gaps:
            for k in CLASSIFICATION:
                if not r.values[k]:
                    r.mark(k, RED, f"{k} is required but empty. {e}" if k != SUBCATEGORY else f"Subcategory empty. {e}")
        return str(e)

    filled = 0
    for i, r in enumerate(gaps):
        s = suggestions.get(str(i))
        for k, attr in ((CATEGORY, "category"), (SUBCATEGORY, "subcategory"), (ASSET_TYPE, "asset_type")):
            if r.values[k]:
                continue
            value = smart_case(getattr(s, attr)) if s else ""
            if value:
                r.values[k] = value
                r.mark(k, AMBER, "Suggested by AI; please confirm")
                filled += 1
            else:
                r.mark(k, RED, f"{k} is empty and AI could not suggest one")
    return f"Used for {len(gaps)} rows ({filled} values suggested)"


def _flag_duplicate_names(rows: list[Row]) -> None:
    counts: dict[str, int] = {}
    for r in rows:
        if r.values.get(NAME):
            counts[r.values[NAME].lower()] = counts.get(r.values[NAME].lower(), 0) + 1
    for r in rows:
        n = counts.get(r.values.get(NAME, "").lower(), 0)
        if n > 1:
            r.mark(NAME, AMBER, f"Same name used by {n} assets; add a number if they are separate assets")


# ---------------------------------------------------------------- main entry

def clean_asset_file(client_file, template_file=None, use_ai: bool = True) -> CleanResult:
    """client_file / template_file: a path or a binary file-like object (.xlsx)."""
    rules = config.asset_rules()
    synonyms = rules.get("header_synonyms", {})

    tpl_wb = openpyxl.load_workbook(template_file or DEFAULT_TEMPLATE)
    tpl_ws = tpl_wb.worksheets[0]
    columns = _template_columns(tpl_ws)
    if not columns:
        raise ValueError("The template's first row has no headers.")

    src_wb = openpyxl.load_workbook(client_file, data_only=True)
    src_ws, cmap = _pick_sheet(src_wb, columns, synonyms)
    if len(cmap.found) < 2:
        raise ValueError("Could not find the column headers in the client file "
                         "(fewer than 2 columns matched the asset template).")

    # Read client rows into {template key: raw value}.
    rows: list[Row] = []
    for r_idx, values in enumerate(src_ws.iter_rows(min_row=cmap.header_row + 1, values_only=True),
                                   start=cmap.header_row + 1):
        if all(is_empty(v) for v in values):
            continue
        raw = {key: (values[i] if i < len(values) else None) for key, (i, _, _) in cmap.found.items()}
        rows.append(_process_row(raw, r_idx, columns, rules))

    _fill_from_other_rows(rows)
    ai_status = _fill_with_ai(rows) if use_ai else "Switched off for this run"
    _flag_duplicate_names(rows)
    for r in rows:
        _finish_row(r, columns)

    # Write into a clean copy of the template.
    if tpl_ws.max_row > 1:
        tpl_ws.delete_rows(2, tpl_ws.max_row - 1)
    hl = Highlighter()
    col_index = {c.key: c.index for c in columns}
    for out_row, r in enumerate(rows, start=2):
        for col in columns:
            tpl_ws.cell(row=out_row, column=col.index, value=r.values.get(col.key) or None)
        for key, level, note in r.marks:
            if key in col_index:
                hl.mark(out_row, col_index[key], level, note)

    # Column-level report and header highlights.
    report = []
    for col in columns:
        hit = cmap.found.get(col.key)
        if hit:
            _, how, client_header = hit
            report.append({"column": col.key, "client_column": client_header, "how": how, "required": col.required})
            if how in (SYNONYM, FUZZY):
                hl.mark(1, col.index, AMBER, f"Matched to client column '{client_header}'; confirm this is right")
        else:
            report.append({"column": col.key, "client_column": None, "how": "missing", "required": col.required})
            if col.required:
                hl.mark(1, col.index, RED, "Column missing in client file")
    hl.apply(tpl_ws)
    tpl_ws.freeze_panes = "B2"

    buf = io.BytesIO()
    tpl_wb.save(buf)
    counts = hl.counts()
    warnings = []
    if cmap.header_row != 1:
        warnings.append(f"Headers were found on row {cmap.header_row} of the client file, not row 1.")
    if src_wb.worksheets and src_ws is not src_wb.worksheets[0]:
        warnings.append(f"Used sheet '{src_ws.title}' (best match for the template).")
    return CleanResult(
        content=buf.getvalue(), rows=len(rows), red_cells=counts[RED], amber_cells=counts[AMBER],
        column_report=report, issue_summary=hl.notes_summary(), unmapped_columns=cmap.unmapped,
        ai_status=ai_status, header_row=cmap.header_row, warnings=warnings,
    )


def output_name(original: str) -> str:
    return f"{Path(original).stem or 'assets'}_cleaned.xlsx"
