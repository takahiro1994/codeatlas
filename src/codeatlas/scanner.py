from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from .models import DocIssue, FileReport, ProjectReport, Summary, TodoItem

LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".md": "Markdown",
    ".json": "JSON",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".sh": "Shell",
    ".html": "HTML",
    ".css": "CSS",
}

IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "venv",
    "dist",
    "build",
    "coverage",
}

TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|NOTE)\b[:\-\s]*(.*)", re.IGNORECASE)
PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+([A-Za-z0-9_\.]+)\s+import|import\s+([A-Za-z0-9_\.]+))", re.MULTILINE)
JS_IMPORT_RE = re.compile(
    r"""(?:import\s+.*?from\s+["']([^"']+)["']|require\(\s*["']([^"']+)["']\s*\))""",
    re.MULTILINE,
)
DOC_PATH_RE = re.compile(r"(?:\[[^\]]+\]\(([^)]+)\)|`([^`]+\.[A-Za-z0-9]+)`)")


def should_skip(path: Path) -> bool:
    return any(part in IGNORE_DIRS for part in path.parts)


def detect_language(path: Path) -> str:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "Other")


def iter_files(root: Path) -> list[Path]:
    git_dir = root / ".git"
    if git_dir.exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
                check=True,
                capture_output=True,
                text=True,
            )
            git_files = []
            for line in proc.stdout.splitlines():
                item = line.strip()
                if not item:
                    continue
                path = root / item
                if path.exists() and path.is_file() and not path.is_symlink() and not should_skip(path):
                    git_files.append(path)
            return sorted(git_files)
        except (OSError, subprocess.CalledProcessError):
            pass

    files: list[Path] = []
    for current_root, dirs, filenames in os.walk(root):
        current = Path(current_root)
        dirs[:] = [name for name in dirs if name not in IGNORE_DIRS and not name.startswith(".tmp")]
        for filename in filenames:
            path = current / filename
            if should_skip(path) or path.is_symlink():
                continue
            files.append(path)
    return sorted(files)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def extract_dependencies(path: Path, text: str) -> list[str]:
    deps: list[str] = []
    suffix = path.suffix.lower()
    if suffix == ".py":
        for match in PY_IMPORT_RE.finditer(text):
            dep = match.group(1) or match.group(2)
            if dep:
                deps.append(dep)
    elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
        for match in JS_IMPORT_RE.finditer(text):
            dep = match.group(1) or match.group(2)
            if dep:
                deps.append(dep)
    return sorted(set(deps))


def extract_todos(rel_path: str, text: str) -> list[TodoItem]:
    items: list[TodoItem] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = TODO_RE.search(line)
        if not match:
            continue
        label = match.group(1).upper()
        detail = (match.group(2) or "").strip() or line.strip()
        items.append(TodoItem(path=rel_path, line=line_number, label=label, text=detail))
    return items


def normalize_doc_reference(doc_path: Path, root: Path, reference: str) -> str | None:
    if "://" in reference or reference.startswith("#"):
        return None
    candidate = (doc_path.parent / reference).resolve()
    try:
        return str(candidate.relative_to(root.resolve()))
    except ValueError:
        return None


def analyze_docs(root: Path, file_set: set[str]) -> list[DocIssue]:
    issues: list[DocIssue] = []
    for doc_path in iter_files(root):
        if doc_path.suffix.lower() not in {".md", ".rst", ".txt"}:
            continue
        text = read_text(doc_path)
        rel_doc = str(doc_path.relative_to(root))
        for match in DOC_PATH_RE.finditer(text):
            reference = match.group(1) or match.group(2)
            normalized = normalize_doc_reference(doc_path, root, reference)
            if not normalized:
                continue
            if normalized not in file_set:
                issues.append(DocIssue(doc_path=rel_doc, referenced_path=normalized, issue="missing-reference"))
    return issues


def resolve_local_edges(files: list[FileReport], path_map: dict[str, FileReport]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    rel_paths = list(path_map)
    for report in files:
        path_without_suffix = report.path.rsplit(".", 1)[0]
        for dep in report.outgoing_dependencies:
            dep_key = dep.replace(".", "/")
            matches = [
                candidate
                for candidate in rel_paths
                if candidate.rsplit(".", 1)[0].endswith(dep_key)
                or candidate.startswith(dep.strip("./"))
            ]
            if matches:
                target = sorted(matches, key=len)[0]
                edges.append({"source": report.path, "target": target})
                path_map[target].incoming_dependencies.append(report.path)
            elif dep.startswith("."):
                local_candidate = str((Path(path_without_suffix).parent / dep).with_suffix(Path(report.path).suffix))
                if local_candidate in path_map:
                    edges.append({"source": report.path, "target": local_candidate})
                    path_map[local_candidate].incoming_dependencies.append(report.path)
    return edges


def compute_hotspot(report: FileReport, doc_issue_count: int) -> int:
    return (
        len(report.todos) * 3
        + len(report.outgoing_dependencies)
        + len(report.incoming_dependencies)
        + (report.lines // 120)
        + len(report.warnings) * 2
        + doc_issue_count * 2
    )


def load_git_churn(root: Path) -> dict[str, int]:
    git_dir = root / ".git"
    if not git_dir.exists():
        return {}
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "--pretty=format:", "--name-only"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return {}
    churn: Counter[str] = Counter()
    for line in proc.stdout.splitlines():
        item = line.strip()
        if item:
            churn[item] += 1
    return dict(churn)


def generate_insights(summary: Summary, files: list[FileReport], doc_issues: list[DocIssue]) -> list[str]:
    insights: list[str] = []
    if summary.total_files == 0:
        return ["No files were detected in the target path."]
    if summary.todo_count:
        insights.append(f"{summary.todo_count} TODO-style markers were found across the codebase.")
    if doc_issues:
        insights.append(f"{len(doc_issues)} documentation references point to missing files.")
    if summary.hottest_files:
        insights.append(f"Highest-risk area: {summary.hottest_files[0]}.")
    dense = max(files, key=lambda item: len(item.outgoing_dependencies), default=None)
    if dense and dense.outgoing_dependencies:
        insights.append(
            f"Most connected file: {dense.path} with {len(dense.outgoing_dependencies)} outgoing dependencies."
        )
    docs = summary.languages.get("Markdown", 0)
    code = summary.total_files - docs
    if code and docs and docs / max(code, 1) < 0.15:
        insights.append("Documentation coverage looks thin relative to the amount of source code.")
    return insights


def scan_project(root: str | Path) -> ProjectReport:
    root_path = Path(root).resolve()
    file_reports: list[FileReport] = []
    languages = Counter()
    all_todos: list[TodoItem] = []
    file_set: set[str] = set()
    git_churn = load_git_churn(root_path)

    for path in iter_files(root_path):
        rel_path = str(path.relative_to(root_path))
        text = read_text(path)
        language = detect_language(path)
        languages[language] += 1
        todos = extract_todos(rel_path, text)
        lines = text.count("\n") + (1 if text else 0)
        report = FileReport(
            path=rel_path,
            language=language,
            lines=lines,
            size_bytes=path.stat().st_size,
            outgoing_dependencies=extract_dependencies(path, text),
            todos=todos,
        )
        if lines > 500:
            report.warnings.append("large-file")
        if len(report.outgoing_dependencies) > 12:
            report.warnings.append("dense-dependencies")
        if path.name.lower().startswith("temp"):
            report.warnings.append("temporary-naming")
        if git_churn.get(rel_path, 0) >= 5:
            report.warnings.append("high-churn")
        file_reports.append(report)
        all_todos.extend(todos)
        file_set.add(rel_path)

    path_map = {report.path: report for report in file_reports}
    edges = resolve_local_edges(file_reports, path_map)
    doc_issues = analyze_docs(root_path, file_set)
    doc_issue_count_by_file = defaultdict(int)
    for issue in doc_issues:
        doc_issue_count_by_file[issue.doc_path] += 1

    for report in file_reports:
        if report.language == "Markdown" and report.path.startswith("docs/") and not report.outgoing_dependencies:
            report.warnings.append("doc-without-linked-code")
        report.hotspot_score = compute_hotspot(report, doc_issue_count_by_file[report.path]) + min(
            git_churn.get(report.path, 0), 8
        )

    ranked = sorted(file_reports, key=lambda item: (-item.hotspot_score, item.path))
    summary = Summary(
        root=str(root_path),
        total_files=len(file_reports),
        total_lines=sum(item.lines for item in file_reports),
        languages=dict(sorted(languages.items())),
        total_dependencies=len(edges),
        todo_count=len(all_todos),
        warning_count=sum(len(item.warnings) for item in file_reports) + len(doc_issues),
        hottest_files=[item.path for item in ranked[:5]],
    )
    insights = generate_insights(summary, file_reports, doc_issues)
    return ProjectReport(
        summary=summary,
        files=ranked,
        todos=all_todos,
        doc_issues=doc_issues,
        graph={"nodes": [{"id": item.path, "language": item.language} for item in file_reports], "edges": edges},
        insights=insights,
    )


def format_summary(report: ProjectReport) -> str:
    summary = report.summary
    languages = ", ".join(f"{name}:{count}" for name, count in summary.languages.items()) or "none"
    hottest = ", ".join(summary.hottest_files[:3]) or "none"
    insights = "\n".join(f"- {item}" for item in report.insights) or "- No insights generated."
    return (
        f"Root: {summary.root}\n"
        f"Files: {summary.total_files}\n"
        f"Lines: {summary.total_lines}\n"
        f"Languages: {languages}\n"
        f"Dependencies: {summary.total_dependencies}\n"
        f"TODOs: {summary.todo_count}\n"
        f"Warnings: {summary.warning_count}\n"
        f"Hotspots: {hottest}\n"
        f"Insights:\n{insights}"
    )


def report_to_json(report: ProjectReport) -> str:
    return json.dumps(report.to_dict(), indent=2)


def report_to_markdown(report: ProjectReport) -> str:
    summary = report.summary
    lines = [
        "# CodeAtlas Report",
        "",
        f"- Root: `{summary.root}`",
        f"- Files: **{summary.total_files}**",
        f"- Lines: **{summary.total_lines}**",
        f"- Dependencies: **{summary.total_dependencies}**",
        f"- TODOs: **{summary.todo_count}**",
        f"- Warnings: **{summary.warning_count}**",
        "",
        "## Insights",
        "",
    ]
    lines.extend(f"- {item}" for item in report.insights or ["No insights generated."])
    lines.extend(
        [
            "",
            "## Hotspots",
            "",
            "| Path | Language | Lines | Deps | TODOs | Score |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in report.files[:15]:
        lines.append(
            f"| `{item.path}` | {item.language} | {item.lines} | {len(item.outgoing_dependencies)} | "
            f"{len(item.todos)} | {item.hotspot_score} |"
        )
    if report.doc_issues:
        lines.extend(["", "## Documentation Drift", ""])
        lines.extend(
            f"- `{item.doc_path}` references missing `{item.referenced_path}`" for item in report.doc_issues[:20]
        )
    if report.todos:
        lines.extend(["", "## TODO Feed", ""])
        lines.extend(
            f"- `{item.label}` in `{item.path}:{item.line}`: {item.text}" for item in report.todos[:20]
        )
    return "\n".join(lines)
