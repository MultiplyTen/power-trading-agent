"""Bilingual CLI for reproducible local research."""
import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .contracts import ValidationError, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="电力交易智能体 / Power Trading Agent research runtime")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "run", "benchmark"):
        sub = commands.add_parser(name)
        sub.add_argument("--output", required=True, help="new output directory / 新输出目录")
        if name == "run":
            sub.add_argument("--input", required=True)
    for name in ("resume", "verify"):
        commands.add_parser(name).add_argument("--output", required=True)
    commands.add_parser("sample").add_argument("--output", required=True, help="new JSON file")
    commands.add_parser("tools")
    commands.add_parser("tool").add_argument("--request", required=True, help="JSON request file, or - for stdin")
    args = parser.parse_args(argv)
    try:
        if args.command in ("demo", "run", "resume"):
            from .runner import run_bundle
            if args.command == "demo":
                from .synthetic import demo_bundle
                bundle = demo_bundle()
            else:
                path = Path(args.input) if args.command == "run" else Path(args.output) / "input.json"
                bundle = json.loads(path.read_text(encoding="utf-8"))
            result = run_bundle(bundle, args.output, resume=args.command == "resume")
        elif args.command == "benchmark":
            from .acceptance import run_benchmark
            result = run_benchmark(args.output)
            print(json.dumps({k: v for k, v in result.items() if k != "cases"}, ensure_ascii=False, indent=2))
            return 1 if result["failed"] else 0
        elif args.command == "verify":
            from .runner import verify_output
            result = verify_output(args.output)
        elif args.command == "sample":
            from .synthetic import demo_bundle
            path = Path(args.output)
            if path.exists():
                raise ValidationError("OUTPUT_EXISTS", "sample output already exists")
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, demo_bundle())
            result = {"written": str(path), "scope": "synthetic"}
        elif args.command == "tools":
            from .tools import TOOL_CATALOG
            result = TOOL_CATALOG
        else:
            from .tools import dispatch
            raw = sys.stdin.read() if args.request == "-" else Path(args.request).read_text(encoding="utf-8")
            result = dispatch(json.loads(raw))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValidationError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "failed", "code": getattr(exc, "code", "INPUT_OR_IO_ERROR"),
                          "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
