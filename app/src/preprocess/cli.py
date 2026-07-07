"""HWP/HWPX preprocessing CLI — a thin wrapper over :mod:`src.preprocess.service`.

Usage:
    python -m src.preprocess <folder|file> [--out <dir>]

For every ``.hwp`` / ``.hwpx`` under the target it writes, into the output dir:
    <name>.md    cleaned Markdown
    <name>.json  structured record (paragraphs/tables/headings)
and an aggregate ``_summary.json``. Exit code 0 if all succeed, 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .service import collect_inputs, default_output_dir, preprocess_path


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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    target_arg, out_arg = parse_cli(argv)
    inputs, base = collect_inputs(target_arg)

    if base is None:
        print("Specify a folder or file to process.")
        print("  e.g.  python -m src.preprocess ./docs --out ./outputs")
        return 1

    output_dir = Path(out_arg) if out_arg else default_output_dir(base)

    print("=" * 64)
    print("HWP/HWPX preprocessing")
    print(f"input  : {base}")
    print(f"output : {output_dir}")
    print("=" * 64)

    if not inputs:
        print("\nNo .hwp / .hwpx files to process.")
        print(f"  -> checked: {base}")

    # Do all the work through the callable service (writes md/json + _summary.json).
    summary = preprocess_path(base, output_dir)

    for entry in summary["files"]:
        print(f"\n[target] {entry['source_file']}")
        if entry["status"] == "success":
            c = entry["block_counts"]
            print(f"    [OK] {entry['extraction_method']}")
            print(
                f"      chars {entry['char_count']:,} / heading {c['heading']}, "
                f"paragraph {c['paragraph']}, table {c['table']}"
            )
            print(f"      -> {', '.join(entry['outputs'])}")
        else:
            print(f"    [X] failed: {entry['reason']}")

    print("\n" + "=" * 64)
    print("Result summary")
    print(f"  total   : {summary['total']}")
    print(f"  success : {summary['success']}")
    print(f"  failed  : {summary['failed']}")
    print(f"  summary : {Path(summary['output_dir']) / '_summary.json'}")
    print("=" * 64)

    if summary["total"] == 0:
        return 1
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
