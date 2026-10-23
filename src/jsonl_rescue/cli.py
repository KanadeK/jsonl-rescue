from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import RescueError, reassemble, split


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lossless JSONL quarantine and byte reassembly")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    split_parser = commands.add_parser("split", help="Create a new recovery bundle")
    split_parser.add_argument("input", help="Input path, or - for binary stdin")
    split_parser.add_argument("--output", type=Path, required=True, help="A NEW bundle directory")
    split_parser.add_argument("--max-line-bytes", type=int, default=1024 * 1024)
    split_parser.add_argument("--objects-only", action="store_true")
    split_parser.add_argument("--require-key", action="append", default=[])
    join_parser = commands.add_parser("reassemble", help="Verify and reconstruct original bytes")
    join_parser.add_argument("bundle", type=Path)
    join_parser.add_argument("--output", type=Path, required=True, help="A NEW output file")
    args = parser.parse_args(argv)
    try:
        if args.command == "reassemble":
            result = reassemble(args.bundle, args.output)
            status = 0
        else:
            options = {
                "max_line_bytes": args.max_line_bytes,
                "objects_only": args.objects_only,
                "required": tuple(args.require_key),
            }
            if args.input == "-":
                result = split(sys.stdin.buffer, args.output, **options)
            else:
                with Path(args.input).open("rb") as source:
                    result = split(source, args.output, **options)
            status = 1 if result["rejected"] else 0
        print(json.dumps(result, sort_keys=True))
        return status
    except RescueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print('{"error": "io_or_input_error"}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('{"error": "interrupted"}', file=sys.stderr)
        return 130
