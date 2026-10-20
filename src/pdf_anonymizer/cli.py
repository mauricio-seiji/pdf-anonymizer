"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pdf_anonymizer.cases import case_dir, entities_path, mapping_path, output_path
from pdf_anonymizer.discovery import (
    discover_pdf,
    discover_pdfs,
    load_entities,
    save_entities,
)
from pdf_anonymizer.fakes import Entity, build_mapping
from pdf_anonymizer.renderer import anonymize_pdf, clean_metadata
from pdf_anonymizer.validate import (
    render_preview_pngs,
    validate_case,
    validate_outputs,
    output_name_for,
)

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
OUTPUT = ROOT / "output"
ENTITIES_FILE = ROOT / "entities.yaml"
MAPPING_FILE = OUTPUT / "mapping.json"

PREVIEW_PAGES: dict[str, list[int]] = {
    "IRENE": [1, 4, 9, 11],
    "MARINES": [1, 3, 4, 30],
}


def _preview_pages_for(name: str | None) -> list[int]:
    if not name:
        return [1]
    upper = name.upper()
    if "IRENE" in upper or "STOLF" in upper:
        return PREVIEW_PAGES["IRENE"]
    if "MARINES" in upper or "BARANOSKI" in upper:
        return PREVIEW_PAGES["MARINES"]
    return [1, 2]


def _apply_fake_name_to_entities(
    entities: list[Entity], fake_name: str | None
) -> list[Entity]:
    if not fake_name:
        return entities
    out: list[Entity] = []
    for e in entities:
        if e.kind == "name" and e.replacement is None:
            out.append(
                Entity(
                    id=e.id,
                    kind=e.kind,
                    original=e.original,
                    replacement=fake_name,
                    anchor=e.anchor,
                )
            )
        else:
            out.append(e)
    return out


def cmd_discover(args: argparse.Namespace) -> int:
    if args.pdf:
        pdf = Path(args.pdf).resolve()
        if not pdf.is_file():
            print(f"PDF not found: {pdf}", file=sys.stderr)
            return 1
        entities = discover_pdf(
            pdf,
            holder_name=args.name,
            fake_name=args.fake_name,
            account=args.account,
            agency=args.agency,
        )
        ent_path = entities_path(pdf)
        save_entities(ent_path, entities)
        print(f"Discovered {len(entities)} entities -> {ent_path}")
        for e in entities:
            print(f"  [{e.kind}] {e.id}: {e.original!r}")
        return 0

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
    if args.pdf:
        pdf = Path(args.pdf).resolve()
        ent_path = entities_path(pdf)
        if not ent_path.exists():
            print(f"entities.yaml not found. Run: pdf-anonymizer discover {pdf}", file=sys.stderr)
            return 1
        entities = _apply_fake_name_to_entities(load_entities(ent_path), args.fake_name)
        mapping = build_mapping(entities, seed=args.seed)
        case_dir(pdf).mkdir(parents=True, exist_ok=True)
        map_path = mapping_path(pdf)
        map_path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False))

        holder = args.name or next((e.original for e in entities if e.kind == "name"), None)
        fake = args.fake_name or next(
            (e.replacement for e in entities if e.kind == "name"), None
        )
        out = output_path(pdf, holder, fake)
        n = anonymize_pdf(pdf, out, entities, mapping)
        clean_metadata(out)
        print(f"  {pdf.name}: {n} replacements -> {out}")
        print(f"Mapping saved to {map_path}")
        return 0

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


def cmd_validate(args: argparse.Namespace) -> int:
    if args.pdf:
        pdf = Path(args.pdf).resolve()
        map_path = mapping_path(pdf)
        ent_path = entities_path(pdf)
        if not map_path.exists():
            print("mapping.json not found. Run: pdf-anonymizer run", file=sys.stderr)
            return 1
        mapping = json.loads(map_path.read_text())
        entities = load_entities(ent_path) if ent_path.exists() else []
        holder = args.name or next((e.original for e in entities if e.kind == "name"), None)
        fake = args.fake_name or next(
            (e.replacement for e in entities if e.kind == "name"), None
        )
        out = output_path(pdf, holder, fake)
        if not out.exists():
            print(f"Output not found: {out}", file=sys.stderr)
            return 1

        result = validate_case(pdf, out, mapping, entities, holder_name=holder)
        preview_dir = case_dir(pdf) / "preview"
        render_preview_pngs(pdf, out, _preview_pages_for(holder), preview_dir)
        print(f"Preview PNGs -> {preview_dir}")

        for w in result.warnings:
            print(f"WARNING: {w}")
        for e in result.errors:
            print(f"ERROR: {e}", file=sys.stderr)

        if result.ok:
            print("Validation passed.")
            return 0
        print("Validation failed.", file=sys.stderr)
        return 1

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

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("pdf", nargs="?", help="Path to a single PDF (case mode)")
    common.add_argument("--name", help="Beneficiary full name to anonymize")
    common.add_argument("--fake-name", help="Replacement name")
    common.add_argument("--account", help="Bank account digits (optional)")
    common.add_argument("--agency", help="Agency digits (optional, matched with anchor)")

    p_discover = sub.add_parser("discover", parents=[common], help="Scan PDF(s) and write entities.yaml")
    p_discover.set_defaults(func=cmd_discover)

    p_run = sub.add_parser("run", parents=[common], help="Anonymize PDF(s)")
    p_run.add_argument("--seed", type=int, default=42, help="RNG seed for fake values")
    p_run.set_defaults(func=cmd_run)

    p_val = sub.add_parser("validate", parents=[common], help="Validate output PDF(s)")
    p_val.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
