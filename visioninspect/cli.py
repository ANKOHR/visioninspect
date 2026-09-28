"""Command line interface for VisionInspect."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import HONESTY_STATEMENT
from .audit import append_audit
from .engine import PROFILE_CONFIG, batch_inspect, canonical_json_bytes, inspect_image, write_annotation, write_json_report
from .fixtures import generate_fixtures
from .reports import render_html, render_markdown


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="visioninspect",
        description="Inspect image files with deterministic, explicit image-analysis heuristics.",
        epilog=HONESTY_STATEMENT,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="inspect one image")
    inspect_parser.add_argument("image", type=Path)
    inspect_parser.add_argument("--profile", choices=sorted(PROFILE_CONFIG), default="general")
    inspect_parser.add_argument("--out", type=Path, help="write the deterministic JSON report here")
    inspect_parser.add_argument("--annotated", type=Path, help="write an annotated PNG here")
    inspect_parser.add_argument("--audit", type=Path, default=Path("vi-audit.jsonl"))

    batch_parser = subparsers.add_parser("batch", help="inspect images in a directory recursively")
    batch_parser.add_argument("directory", type=Path)
    batch_parser.add_argument("--profile", choices=sorted(PROFILE_CONFIG), default="general")
    batch_parser.add_argument("--out", type=Path, default=Path("visioninspect-report.json"))
    batch_parser.add_argument("--annotated-dir", type=Path, default=Path("visioninspect-output/batch-annotated"))
    batch_parser.add_argument("--audit", type=Path, default=Path("vi-audit.jsonl"))

    report_parser = subparsers.add_parser("report", help="render a JSON inspection report as Markdown or HTML")
    report_parser.add_argument("--input", type=Path, default=Path("visioninspect-report.json"))
    report_parser.add_argument("--format", choices=("md", "html"), required=True)
    report_parser.add_argument("--out", type=Path, help="write the rendered report here, otherwise print it")

    rules_parser = subparsers.add_parser("rules", help="list named checks and their measurements")
    rules_parser.add_argument("--format", choices=("text", "json"), default="text")

    fixtures_parser = subparsers.add_parser("fixtures", help="generate synthetic fictional local fixtures")
    fixtures_parser.add_argument("--out", type=Path, required=True)
    return parser


_RULES: list[dict[str, str]] = [
    {"check": "format_integrity", "measures": "Magic bytes, decoded format, byte count, SHA-256, and decoder integrity."},
    {"check": "dimensions", "measures": "Decoded pixel width, height, pixel count, and selected-profile bounds."},
    {"check": "aspect_ratio", "measures": "Decoded width divided by height compared with selected-profile bounds."},
    {"check": "blur", "measures": "Variance of a 3 by 3 Laplacian filter on grayscale pixels, with a fixed threshold."},
    {"check": "exposure", "measures": "Mean grayscale luminance and histogram clipping fractions at both ends."},
    {"check": "metadata_consistency", "measures": "Declared versus decoded dimensions, metadata presence, software tag, and declared profile."},
    {"check": "document_field_plausibility", "measures": "Count of text-like horizontal ink bands for invoice, receipt, and form profiles. It does not read words."},
]


def _print_json(value: Any) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(value))


def _write_text(content: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(content)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8", newline="\n")
    print(HONESTY_STATEMENT)
    print(f"Report written to {output.resolve().as_posix()}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "fixtures":
            manifest = generate_fixtures(args.out)
            print(HONESTY_STATEMENT)
            print(f"Generated {len(manifest['fixtures'])} synthetic fictional fixtures in {args.out.resolve().as_posix()}")
            return 0
        if args.command == "rules":
            if args.format == "json":
                _print_json({
                    "header": {"title": "VisionInspect check catalogue", "honesty_statement": HONESTY_STATEMENT},
                    "honesty_statement": HONESTY_STATEMENT,
                    "checks": _RULES,
                })
            else:
                print(HONESTY_STATEMENT)
                for rule in _RULES:
                    print(f"{rule['check']}: {rule['measures']}")
            return 0
        if args.command == "inspect":
            report = inspect_image(args.image, args.profile)
            append_audit(report, args.audit)
            annotated_path = args.annotated
            if annotated_path is None and report["findings"]:
                annotated_path = Path("visioninspect-output/annotated") / f"{args.image.stem}.annotated.png"
            if annotated_path is not None:
                write_annotation(report, annotated_path)
            if args.out is None:
                _print_json(report)
            else:
                write_json_report(report, args.out)
                print(HONESTY_STATEMENT)
                print(f"Inspection JSON report written to {args.out.resolve().as_posix()}")
                if annotated_path is not None:
                    print(f"Annotated PNG written to {annotated_path.resolve().as_posix()}")
            return 0
        if args.command == "batch":
            report = batch_inspect(args.directory, args.profile, args.annotated_dir)
            append_audit(report, args.audit)
            write_json_report(report, args.out)
            print(HONESTY_STATEMENT)
            print(f"Inspected {report['summary']['image_count']} images, found {report['summary']['finding_count']} findings.")
            print(f"Batch JSON report written to {args.out.resolve().as_posix()}")
            print(f"Annotated flagged images written under {args.annotated_dir.resolve().as_posix()}")
            return 0
        if args.command == "report":
            report_data = json.loads(args.input.read_text(encoding="utf-8"))
            rendered = render_markdown(report_data) if args.format == "md" else render_html(report_data)
            _write_text(rendered, args.out)
            return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"visioninspect error: {exc}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2
