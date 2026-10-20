"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdf_anonymizer.discovery import discover_pdfs, load_entities, save_entities
from pdf_anonymizer.fakes import build_mapping
from pdf_anonymizer.renderer import anonymize_pdf, clean_metadata
from pdf_anonymizer.validate import output_name_for, validate_outputs

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
OUTPUT = ROOT / "output"
ENTITIES_FILE = ROOT / "entities.yaml"
MAPPING_FILE = OUTPUT / "mapping.json"


def cmd_discover(_: argparse.Namespace) -> int:
    if not DOCS.exists():
        print(f"Docs directory not found: {DOCS}", file=sys.stderr)
        return 1
    entities = discover_pdfs(DOCS)
    save_entities(ENTITIES_FILE, entities)
    print(f"Discovered {len(entities)} entities -> {ENTITIES_FILE}")
    for e in entities:
        print(f"  [{e.kind}] {e.id}: {e.original!r}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not ENTITIES_FILE.exists():
        print("entities.yaml not found. Run: pdf-anonymizer discover", file=sys.stderr)
        return 1
    if not DOCS.exists():
        print(f"Docs directory not found: {DOCS}", file=sys.stderr)
        return 1

    entities = load_entities(ENTITIES_FILE)
    mapping = build_mapping(entities, seed=args.seed)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    MAPPING_FILE.write_text(json.dumps(mapping, indent=2, ensure_ascii=False))

    pdfs = sorted(DOCS.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {DOCS}", file=sys.stderr)
        return 1

    total = 0
    for pdf in pdfs:
        out = OUTPUT / output_name_for(pdf)
        n = anonymize_pdf(pdf, out, entities, mapping)
        clean_metadata(out)
        total += n
        print(f"  {pdf.name}: {n} replacements -> {out}")

    print(f"Done. {total} replacements across {len(pdfs)} files.")
    print(f"Mapping saved to {MAPPING_FILE}")
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    if not MAPPING_FILE.exists():
        print("mapping.json not found. Run: pdf-anonymizer run", file=sys.stderr)
        return 1
    mapping = json.loads(MAPPING_FILE.read_text())
    entities = load_entities(ENTITIES_FILE) if ENTITIES_FILE.exists() else None
    result = validate_outputs(OUTPUT, DOCS, mapping, entities=entities)

    for w in result.warnings:
        print(f"WARNING: {w}")
    for e in result.errors:
        print(f"ERROR: {e}", file=sys.stderr)

    if result.ok:
        print("Validation passed.")
        return 0
    print("Validation failed.", file=sys.stderr)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Anonymize HISCON PDF documents")
    sub = parser.add_subparsers(dest="command", required=True)

    p_discover = sub.add_parser("discover", help="Scan docs/ and write entities.yaml")
    p_discover.set_defaults(func=cmd_discover)

    p_run = sub.add_parser("run", help="Anonymize PDFs to output/")
    p_run.add_argument("--seed", type=int, default=42, help="RNG seed for fake values")
    p_run.set_defaults(func=cmd_run)

    p_val = sub.add_parser("validate", help="Validate output/ PDFs")
    p_val.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
