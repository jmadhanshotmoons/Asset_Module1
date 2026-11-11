# Asset Module 1: Asset Master Cleaner (backend)

Python backend that converts a messy client asset list (`.xlsx`) into Punctualiti's standard **Asset template**. Problems are highlighted **in the cell itself**, with a note on the cell, for a human reviewer.

| Colour | Meaning |
|---|---|
| **Red** | Reviewer must fix: missing required value or column, unreadable value, conflict |
| **Amber** | Tool changed or inferred a value: reviewer should confirm |

The tool never guesses silently: anything it isn't sure about is written as-is (or best-guess) and highlighted.

## Quick start

```bash
pip install -r requirements.txt
python -m punctualiti.asset "Client asset list.xlsx"            # writes Client asset list_cleaned.xlsx
python -m punctualiti.asset "Client asset list.xlsx" --no-ai    # skip Claude
python -m punctualiti.asset in.xlsx -o out.xlsx --template "Asset Template.xlsx"
```

From Python:

```python
from punctualiti.asset import clean_asset_file

result = clean_asset_file("Client asset list.xlsx")     # path or binary file object
open("cleaned.xlsx", "wb").write(result.content)
print(result.rows, result.red_cells, result.amber_cells, result.ai_status)
```

`CleanResult` also carries `column_report` (how each template column was matched), `unmapped_columns`, `issue_summary` and `warnings`, for a UI to display.

## What it does

1. **Structure check.** Finds the header row (even below title rows) and the best-matching sheet, then maps client columns to template columns: exact name, then synonyms (`config/asset_rules.json`), then close spellings. Synonym and close-spelling matches are amber on the header. Missing required columns are red on the header. Output always uses the exact template layout.
2. **Asset name.** Trims, collapses spaces, capitalises words, keeps abbreviations upper-case (`Fhc` → `FHC`), and zero-pads the trailing number (`UPS-1` → `UPS-01`, `Compressor no-1` → `Compressor No-01`).
3. **Category / Subcategory / Asset Type.** Keeps the client's own values (spacing and case tidied only). Known typos in `value_corrections` are fixed and flagged amber. Asset types that look like locations (`B-1`, `UGF Washroom`) are red.
4. **Gaps.** A missing Category, Subcategory or Asset Type is filled from other rows when every row sharing a clue (same asset type, subcategory or base name) agrees on one value (amber). Anything still missing is sent to Claude (amber "Suggested by AI"). With no API key, the gaps stay red.
5. **Location.** Building: `Tower c`, `Towerr-b`, `TB`, `T-01` → `Tower C`, `Tower B`, `Tower B`, `Tower 1` (unclear readings are amber). Floor and Room are read from free text using `config/floors.json`, for example `Pump Room, Basement 2` → `BM2` and `Pump Room`, and `CW-B1-LT room` → `CW` / `BM1` / `LT Room`. Swapped Floor/Room columns are fixed and flagged amber. Unknown or conflicting floors are red.
6. **Capacity + UOM.** `6KG` → `6` / `KG`, `9 liters` → `9` / `Liter`, `Capacity : 10KL` → `10` / `KL`. Unit/UOM conflicts and unsplittable values are red.
7. **Dropdowns.** Status, Critical, Service Type and similar columns are checked against `allowed_values`, ignoring case and spacing. Out-of-list values are red.
8. **Template limits.** Required (`*`) columns, `Max-N characters/digits` and `dd-mm-yyyy` dates are read from the template headers and enforced. Optional blanks become `NA`, as in the template.
9. **Duplicates.** Asset names used by more than one row are amber.

## Configuration (no code changes)

| File | What to edit |
|---|---|
| `config/abbreviations.json` | Words that keep exact casing (UPS, FHC, kVA, …) |
| `config/floors.json` | Floor words and the codes they become (BM1, GF, 1F, Terrace) |
| `config/units.json` | Unit spellings → standard UOM |
| `config/asset_rules.json` | Number padding width, allowed dropdown values, header synonyms, typo corrections, empty markers |

The bundled template is `punctualiti/data/asset_template.xlsx`. Pass `--template` to use another.

## AI credentials (Amazon Bedrock or Claude API)

Uses Punctualiti's own account. Copy `.env.example` to `.env` (git-ignored) and fill in **one** option:

```
# Amazon Bedrock
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1          # a region where Claude is enabled in Bedrock

# or the Claude API
ANTHROPIC_API_KEY=...
```

Real environment variables override `.env`. If both are set, the Claude API is used unless `PUNCTUALITI_AI_PROVIDER=bedrock`. On Bedrock, the IAM user needs `bedrock:InvokeModel` and the Claude model must be enabled under Bedrock **Model access**.

Credentials are never stored in code. Only rows with a missing Category, Subcategory or Asset Type are sent, in batches of 60, using `claude-opus-5-5` (`anthropic.claude-opus-5-5` on Bedrock; override with `PUNCTUALITI_AI_MODEL`) with low effort and structured JSON output. On the Claude API the server-side refusal fallback is also on (Bedrock doesn't offer it). Any AI error leaves those cells red with the reason, and the rest of the file is still cleaned.

## Layout

```
punctualiti/
  asset/cleaner.py   Module 1 pipeline (clean_asset_file)
  asset/__main__.py  command line
  columns.py         client → template column matching
  excel.py           template header parsing, red/amber highlighting
  text.py            spacing, casing, padding, dates
  location.py        building / floor / room parsing
  units.py           capacity + UOM split
  ai.py              Claude fallback
  config.py, env.py  config + .env loading
config/              editable rules (JSON)
tests/               pytest suite
```

## Tests

```bash
python -m pytest -q
```

The end-to-end test runs on the real client file at `samples/Asset list.xlsx`. Client files are not committed, so that test is skipped unless you add the file locally.

## Open questions (Punctualiti to confirm)

- Floor codes (`BM1`, `GF`, `1F`, …) and whether `L001` means level 1 or a lift.
- Full allowed values for Status, Critical, Service Type and Maintenance Policy.
- Full abbreviation list and padding width (default 2).
- Whether duplicate asset names are acceptable.
- Whether AI-filled values should be amber (current) or red.
