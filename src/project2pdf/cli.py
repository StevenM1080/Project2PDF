from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .ingest import analyze_inputs
from .pdf import default_output_path, generate_pdf
from .sites import CachedWebClient, enrich_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="project2pdf", description="Create source-linked PDFs for 3D-print projects.")
    subparsers = parser.add_subparsers(dest="command")

    analyze = subparsers.add_parser("analyze", help="Inspect inputs and print normalized metadata as JSON.")
    analyze.add_argument("inputs", nargs="+", help="Files, folders, or model URLs")
    analyze.add_argument("--offline", action="store_true", help="Do not fetch or search websites")

    generate = subparsers.add_parser("generate", help="Analyze inputs and generate PDFs.")
    generate.add_argument("inputs", nargs="+", help="Files, folders, or model URLs")
    generate.add_argument("-o", "--output", type=Path, default=Path.cwd(), help="Output directory")
    generate.add_argument("--offline", action="store_true", help="Do not fetch or search websites")
    generate.add_argument("--theme", choices=("light", "dark"), default="light", help="PDF color theme")

    subparsers.add_parser("gui", help="Launch the desktop application")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command or args.command == "gui":
        from .app import main as gui_main

        return gui_main()

    records = analyze_inputs(args.inputs)
    cache_dir = Path.cwd() / ".project2pdf-cache"
    if not args.offline:
        records = enrich_records(records, cache_dir=cache_dir, allow_search=True)

    if args.command == "analyze":
        json.dump([record.to_dict() for record in records], sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    args.output.mkdir(parents=True, exist_ok=True)
    web = None if args.offline else CachedWebClient(cache_dir=cache_dir)
    try:
        for record in records:
            output = default_output_path(record, args.output)
            generate_pdf(record, output, web=web, theme=args.theme)
            print(output)
    finally:
        if web:
            web.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
