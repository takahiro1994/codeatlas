from __future__ import annotations

import argparse
from pathlib import Path

from .scanner import format_summary, report_to_json, report_to_markdown, scan_project
from .server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codeatlas",
        description="Scan a local repository and surface hotspots, TODO pressure, and doc drift.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Analyze a repository and print a summary.")
    scan_parser.add_argument("path", nargs="?", default=".", help="Path to the repository root.")
    scan_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    scan_parser.add_argument("--markdown", action="store_true", help="Emit Markdown instead of text.")
    scan_parser.add_argument("--output", help="Write the report to a file.")

    serve_parser = subparsers.add_parser("serve", help="Launch the dashboard.")
    serve_parser.add_argument("path", nargs="?", default=".", help="Path to the repository root.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8123)

    demo_parser = subparsers.add_parser("demo", help="Launch the bundled demo repository.")
    demo_parser.add_argument("--host", default="127.0.0.1")
    demo_parser.add_argument("--port", type=int, default=8123)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "scan":
        report = scan_project(args.path)
        output = (
            report_to_json(report)
            if args.json
            else report_to_markdown(report)
            if args.markdown
            else format_summary(report)
        )
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
        print(output)
        return
    if args.command == "serve":
        serve(args.path, host=args.host, port=args.port)
        return
    if args.command == "demo":
        demo_root = Path(__file__).resolve().parents[2] / "examples" / "sample_repo"
        serve(str(demo_root), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
