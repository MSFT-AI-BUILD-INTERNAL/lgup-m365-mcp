"""HWP/HWPX preprocessing CLI.

Usage:
    python -m src.preprocess <folder|file> [--out <dir>]

For every ``.hwp`` / ``.hwpx`` under the target it writes, into the output dir:
    <name>.md    cleaned Markdown
    <name>.json  structured record (paragraphs/tables/headings)
and an aggregate ``_summary.json``. Exit code 0 if all succeed, 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .core import SUPPORTED_SUFFIXES, blocks_to_markdown, process_file


def parse_cli(argv: list[str]) -> tuple[str | None, str | None]:
    """Parse args. Returns (target path or None, output dir or None)."""
    target = None
    out = None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("--out", "-o"):
            i += 1
            if i < len(argv):
                out = argv[i]
        elif a.startswith("--out="):
            out = a.split("=", 1)[1]
        elif target is None:
            target = a
        i += 1
    return target, out


def collect_inputs(target_arg: str | None) -> tuple[list[Path], Path | None]:
    """Resolve the target: a folder -> its hwp/hwpx files; a file -> that file."""
    if target_arg is None:
        return [], None

    target = Path(target_arg)
    if target.is_dir():
        files = sorted(
            p
            for p in target.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
        )
        return files, target
    if target.is_file():
        return [target], target.parent
    return [], target


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    target_arg, out_arg = parse_cli(argv)
    inputs, base = collect_inputs(target_arg)

    if base is None:
        print("Specify a folder or file to process.")
        print("  e.g.  python -m src.preprocess ./docs --out ./outputs")
        return 1

    output_dir = Path(out_arg) if out_arg else (base if base.is_dir() else base.parent) / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("HWP/HWPX preprocessing")
    print(f"input  : {base}")
    print(f"output : {output_dir}")
    print("=" * 64)

    if not inputs:
        print("\nNo .hwp / .hwpx files to process.")
        print(f"  -> checked: {base}")
        return 1

    summary = []
    success = 0
    failed = 0

    for path in inputs:
        print(f"\n[target] {path.name}")
        try:
            record = process_file(path)
        except Exception as exc:  # noqa: BLE001 - keep going on per-file failure
            print(f"    [X] failed: {exc}")
            summary.append(
                {"source_file": path.name, "status": "failed", "reason": str(exc)}
            )
            failed += 1
            continue

        stem = path.stem
        md_path = output_dir / (stem + ".md")
        json_path = output_dir / (stem + ".json")
        try:
            md_path.write_text(
                blocks_to_markdown(stem, record["blocks"]), encoding="utf-8"
            )
            json_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            print(f"    [X] failed: write error: {exc}")
            summary.append(
                {"source_file": path.name, "status": "failed", "reason": f"write: {exc}"}
            )
            failed += 1
            continue

        c = record["block_counts"]
        print(f"    [OK] {record['extraction_method']}")
        print(
            f"      chars {record['char_count']:,} / heading {c['heading']}, "
            f"paragraph {c['paragraph']}, table {c['table']}"
        )
        summary.append(
            {
                "source_file": path.name,
                "status": "success",
                "format": record["format"],
                "extraction_method": record["extraction_method"],
                "char_count": record["char_count"],
                "block_counts": c,
                "outputs": [md_path.name, json_path.name],
            }
        )
        success += 1

    (output_dir / "_summary.json").write_text(
        json.dumps(
            {
                "input": str(base),
                "total": len(inputs),
                "success": success,
                "failed": failed,
                "files": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n" + "=" * 64)
    print("Result summary")
    print(f"  total   : {len(inputs)}")
    print(f"  success : {success}")
    print(f"  failed  : {failed}")
    print(f"  summary : {output_dir / '_summary.json'}")
    print("=" * 64)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
