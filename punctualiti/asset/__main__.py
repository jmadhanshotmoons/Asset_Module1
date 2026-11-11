"""Command line: python -m punctualiti.asset "Client list.xlsx" [-o out.xlsx] [--template T.xlsx] [--no-ai]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import ai
from ..env import load_dotenv
from .cleaner import clean_asset_file, output_name


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m punctualiti.asset", description="Clean a client asset list into the Punctualiti asset template.")
    p.add_argument("client_file", type=Path)
    p.add_argument("-o", "--output", type=Path, help="output .xlsx (default: <client>_cleaned.xlsx next to the input)")
    p.add_argument("--template", type=Path, help="asset template .xlsx (default: bundled template)")
    p.add_argument("--no-ai", action="store_true", help="don't call Claude for missing Category / Subcategory / Asset Type")
    args = p.parse_args(argv)

    load_dotenv()
    result = clean_asset_file(args.client_file, args.template, use_ai=not args.no_ai)
    out = args.output or args.client_file.with_name(output_name(args.client_file.name))
    out.write_bytes(result.content)

    print(f"Wrote {out}")
    print(f"Rows: {result.rows} | red cells (fix): {result.red_cells} | amber cells (check): {result.amber_cells}")
    print(f"AI: {ai.describe()} - {result.ai_status}")
    for w in result.warnings:
        print(f"Note: {w}")
    missing = [c["column"] for c in result.column_report if c["how"] == "missing" and c["required"]]
    if missing:
        print("Required columns missing in client file: " + ", ".join(missing))
    if result.unmapped_columns:
        print("Client columns not used: " + ", ".join(result.unmapped_columns))
    print("Top issues:")
    for note, n in list(result.issue_summary.items())[:10]:
        print(f"  {n:>4}  {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
