from __future__ import annotations

import argparse
import json
from pathlib import Path

from .scanner import (
    compare_reports,
    format_delta,
    format_owner_summary,
    format_reviewer_suggestions,
    format_summary,
    focus_report_on_paths,
    list_changed_files,
    load_report,
    report_to_json,
    report_to_markdown,
    report_to_sarif,
    scan_project,
    suggest_reviewers,
)
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
    scan_parser.add_argument("--sarif", action="store_true", help="Emit SARIF instead of text.")
    scan_parser.add_argument("--output", help="Write the report to a file.")

    compare_parser = subparsers.add_parser("compare", help="Compare a baseline report JSON to a current path.")
    compare_parser.add_argument("baseline", help="Path to a baseline report generated with --json.")
    compare_parser.add_argument("path", nargs="?", default=".", help="Path to the repository root.")
    compare_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    compare_parser.add_argument("--output", help="Write the diff report to a file.")

    owners_parser = subparsers.add_parser("owners", help="Summarize CODEOWNERS coverage and hotspots.")
    owners_parser.add_argument("path", nargs="?", default=".", help="Path to the repository root.")
    owners_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    owners_parser.add_argument("--output", help="Write the owner report to a file.")

    reviewers_parser = subparsers.add_parser("reviewers", help="Suggest reviewers from owners and git blame.")
    reviewers_parser.add_argument("path", nargs="?", default=".", help="Path to the repository root.")
    reviewers_parser.add_argument("--base", default="HEAD~1", help="Base git ref for the diff.")
    reviewers_parser.add_argument("--head", default="HEAD", help="Head git ref for the diff.")
    reviewers_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    reviewers_parser.add_argument("--output", help="Write the reviewer suggestions to a file.")

    changes_parser = subparsers.add_parser("changes", help="Analyze only files changed between two git refs.")
    changes_parser.add_argument("path", nargs="?", default=".", help="Path to the repository root.")
    changes_parser.add_argument("--base", default="HEAD~1", help="Base git ref for the diff.")
    changes_parser.add_argument("--head", default="HEAD", help="Head git ref for the diff.")
    changes_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    changes_parser.add_argument("--markdown", action="store_true", help="Emit Markdown instead of text.")
    changes_parser.add_argument("--sarif", action="store_true", help="Emit SARIF instead of text.")
    changes_parser.add_argument("--output", help="Write the focused report to a file.")

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
            else report_to_sarif(report)
            if args.sarif
            else format_summary(report)
        )
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
        print(output)
        return
    if args.command == "compare":
        baseline = load_report(args.baseline)
        current = scan_project(args.path)
        delta = compare_reports(baseline, current)
        output = json.dumps(delta.to_dict(), indent=2) if args.json else format_delta(delta)
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
        print(output)
        return
    if args.command == "owners":
        report = scan_project(args.path)
        output = (
            json.dumps({"root": report.summary.root, "owners": report.owners, "authors": report.authors}, indent=2)
            if args.json
            else format_owner_summary(report)
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
        return
    if args.command == "changes":
        report = scan_project(args.path)
        changed = list_changed_files(args.path, base_ref=args.base, head_ref=args.head)
        focused = focus_report_on_paths(report, changed)
        output = (
            report_to_json(focused)
            if args.json
            else report_to_markdown(focused)
            if args.markdown
            else report_to_sarif(focused)
            if args.sarif
            else format_summary(focused)
        )
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
        print(output)
        return
    if args.command == "reviewers":
        report = scan_project(args.path)
        changed = list_changed_files(args.path, base_ref=args.base, head_ref=args.head)
        focused = focus_report_on_paths(report, changed)
        output = (
            json.dumps({"root": focused.summary.root, "reviewers": suggest_reviewers(focused)}, indent=2)
            if args.json
            else format_reviewer_suggestions(focused)
        )
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
        print(output)


if __name__ == "__main__":
    main()
