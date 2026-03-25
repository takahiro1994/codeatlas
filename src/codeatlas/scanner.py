from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from fnmatch import fnmatch
from pathlib import Path

from .models import DocIssue, FileReport, ProjectReport, ReportDelta, RuleViolation, Summary, TodoItem

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


def normalize_prefix(pattern: str) -> str:
    normalized = pattern.strip().lstrip("./")
    if not normalized:
        return normalized
    if normalized.endswith("/"):
        return normalized
    return normalized + "/"


def matches_any_prefix(path: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return False
    normalized_path = path.replace("\\", "/")
    return any(normalized_path.startswith(normalize_prefix(prefix)) or normalized_path == prefix.strip().lstrip("./") for prefix in prefixes)


def load_config(root: Path) -> dict:
    for name in ("codeatlas.json", ".codeatlas.json"):
        path = root / name
        if not path.exists():
            continue
        try:
            payload = json.loads(read_text(path))
        except json.JSONDecodeError:
            return {"path": str(path.relative_to(root)), "rules": [], "layers": [], "errors": ["invalid-json"]}
        payload["path"] = str(path.relative_to(root))
        payload.setdefault("rules", [])
        payload.setdefault("layers", [])
        return payload
    return {"path": None, "rules": [], "layers": [], "errors": []}


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
    suffix = Path(rel_path).suffix.lower()
    for line_number, line in enumerate(text.splitlines(), start=1):
        candidate = extract_comment_text(line, suffix)
        if not candidate:
            continue
        match = TODO_RE.search(candidate)
        if not match:
            continue
        label = match.group(1).upper()
        detail = (match.group(2) or "").strip() or candidate.strip()
        items.append(TodoItem(path=rel_path, line=line_number, label=label, text=detail))
    return items


def extract_comment_text(line: str, suffix: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    if suffix in {".py", ".sh", ".yml", ".yaml", ".rb"}:
        comment = text_after_unquoted_hash(line)
        if comment is None:
            return None
        return comment
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go", ".rs", ".c", ".cpp", ".h", ".hpp"}:
        if "//" in line:
            return line.split("//", 1)[1].strip()
        if "/*" in line:
            return line.split("/*", 1)[1].split("*/", 1)[0].strip()
        if stripped.startswith("*"):
            return stripped.lstrip("*").strip()
        return None
    if suffix in {".md", ".rst", ".txt"}:
        if stripped.startswith("<!--"):
            return stripped.replace("<!--", "").replace("-->", "").strip()
        if stripped.startswith(("- [ ]", "* [ ]")):
            return stripped[5:].strip()
        return None
    return stripped


def text_after_unquoted_hash(line: str) -> str | None:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            return line[index + 1 :].strip()
    return None


def normalize_doc_reference(doc_path: Path, root: Path, reference: str) -> str | None:
    if "://" in reference or reference.startswith("#"):
        return None
    candidate = (doc_path.parent / reference).resolve()
    try:
        return str(candidate.relative_to(root.resolve()))
    except ValueError:
        return None


def load_codeowners(root: Path) -> list[tuple[str, list[str]]]:
    candidates = [root / "CODEOWNERS", root / ".github" / "CODEOWNERS", root / "docs" / "CODEOWNERS"]
    for path in candidates:
        if not path.exists():
            continue
        rules: list[tuple[str, list[str]]] = []
        for raw_line in read_text(path).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            pattern, owners = parts[0], parts[1:]
            rules.append((pattern, owners))
        return rules
    return []


def match_codeowners(rel_path: str, rules: list[tuple[str, list[str]]]) -> list[str]:
    normalized = rel_path.replace("\\", "/")
    matched: list[str] = []
    for pattern, owners in rules:
        normalized_pattern = pattern.lstrip("/")
        if pattern.endswith("/"):
            normalized_pattern = normalized_pattern.rstrip("/") + "/**"
        if fnmatch(normalized, normalized_pattern) or fnmatch("/" + normalized, pattern):
            matched = owners
            continue
        if "/" not in normalized_pattern and fnmatch(Path(normalized).name, normalized_pattern):
            matched = owners
    return matched


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
                if candidate.rsplit(".", 1)[0] == dep_key
                or candidate.rsplit(".", 1)[0].endswith("/" + dep_key)
                or candidate == dep.strip("./")
                or candidate.startswith(dep.strip("./") + "/")
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


def detect_cycles(edges: list[dict[str, str]]) -> list[list[str]]:
    graph: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        graph[edge["source"]].append(edge["target"])

    seen: set[tuple[str, ...]] = set()
    cycles: list[list[str]] = []

    def canonicalize(path: list[str]) -> tuple[str, ...]:
        ring = path[:-1]
        if not ring:
            return tuple()
        rotations = [tuple(ring[index:] + ring[:index]) for index in range(len(ring))]
        return min(rotations)

    def dfs(node: str, stack: list[str], visiting: set[str]) -> None:
        stack.append(node)
        visiting.add(node)
        for target in graph.get(node, []):
            if target in visiting:
                cycle = stack[stack.index(target) :] + [target]
                key = canonicalize(cycle)
                if key and key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
                continue
            if target in stack:
                continue
            dfs(target, stack, visiting)
        visiting.remove(node)
        stack.pop()

    for node in sorted(graph):
        dfs(node, [], set())
    return sorted(cycles)


def evaluate_rules(edges: list[dict[str, str]], config: dict) -> list[RuleViolation]:
    violations: list[RuleViolation] = []
    for rule in config.get("rules", []):
        rule_name = rule.get("name", "unnamed-rule")
        source_prefixes = rule.get("from", [])
        target_prefixes = rule.get("to", []) or rule.get("disallow", [])
        if not source_prefixes or not target_prefixes:
            continue
        severity = rule.get("severity", "warning")
        message = rule.get("message", f"{rule_name} violated")
        for edge in edges:
            if matches_any_prefix(edge["source"], source_prefixes) and matches_any_prefix(edge["target"], target_prefixes):
                violations.append(
                    RuleViolation(
                        rule=rule_name,
                        severity=severity,
                        source=edge["source"],
                        target=edge["target"],
                        message=message,
                    )
                )
    return violations


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


def list_changed_files(root: str | Path, base_ref: str = "HEAD~1", head_ref: str = "HEAD") -> list[str]:
    root_path = Path(root).resolve()
    if not (root_path / ".git").exists():
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", str(root_path), "diff", "--name-only", f"{base_ref}..{head_ref}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    changed = []
    for line in proc.stdout.splitlines():
        item = line.strip()
        if item:
            changed.append(item)
    return changed


def load_git_authors(root: Path) -> dict[str, list[str]]:
    if not (root / ".git").exists():
        return {}
    authors_by_file: dict[str, list[str]] = {}
    for path in iter_files(root):
        rel_path = str(path.relative_to(root))
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "blame", "--line-porcelain", rel_path],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        counter: Counter[str] = Counter()
        for line in proc.stdout.splitlines():
            if line.startswith("author "):
                counter[line[7:].strip()] += 1
        if counter:
            authors_by_file[rel_path] = [name for name, _ in counter.most_common(3)]
    return authors_by_file


def generate_insights(
    summary: Summary,
    files: list[FileReport],
    doc_issues: list[DocIssue],
    rule_violations: list[RuleViolation],
    cycles: list[list[str]],
) -> list[str]:
    insights: list[str] = []
    if summary.total_files == 0:
        return ["No files were detected in the target path."]
    if summary.todo_count:
        insights.append(f"{summary.todo_count} TODO-style markers were found across the codebase.")
    if doc_issues:
        insights.append(f"{len(doc_issues)} documentation references point to missing files.")
    if rule_violations:
        insights.append(f"{len(rule_violations)} structural rule violations were detected.")
    if cycles:
        insights.append(f"{len(cycles)} dependency cycles were detected.")
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
    owner_counter = Counter(owner for item in files for owner in item.owners)
    if owner_counter:
        owner, count = owner_counter.most_common(1)[0]
        insights.append(f"Most loaded owner: {owner} across {count} tracked files.")
    author_counter = Counter(author for item in files for author in item.authors)
    if author_counter:
        author, count = author_counter.most_common(1)[0]
        insights.append(f"Most visible author in blame data: {author} across {count} tracked files.")
    return insights


def scan_project(root: str | Path) -> ProjectReport:
    root_path = Path(root).resolve()
    file_reports: list[FileReport] = []
    languages = Counter()
    all_todos: list[TodoItem] = []
    file_set: set[str] = set()
    git_churn = load_git_churn(root_path)
    codeowners = load_codeowners(root_path)
    git_authors = load_git_authors(root_path)
    config = load_config(root_path)

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
            owners=match_codeowners(rel_path, codeowners),
            authors=git_authors.get(rel_path, []),
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
    cycles = detect_cycles(edges)
    rule_violations = evaluate_rules(edges, config)
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
        warning_count=sum(len(item.warnings) for item in file_reports) + len(doc_issues) + len(rule_violations) + len(cycles),
        hottest_files=[item.path for item in ranked[:5]],
    )
    insights = generate_insights(summary, file_reports, doc_issues, rule_violations, cycles)
    owner_counter = Counter(owner for item in file_reports for owner in item.owners)
    author_counter = Counter(author for item in file_reports for author in item.authors)
    return ProjectReport(
        summary=summary,
        files=ranked,
        todos=all_todos,
        doc_issues=doc_issues,
        rule_violations=rule_violations,
        cycles=cycles,
        graph={"nodes": [{"id": item.path, "language": item.language} for item in file_reports], "edges": edges},
        insights=insights,
        owners=[{"owner": owner, "files": count} for owner, count in owner_counter.most_common()],
        authors=[{"author": author, "files": count} for author, count in author_counter.most_common()],
        config=config,
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
            f"{len(item.todos)} | {item.hotspot_score} | {', '.join(item.owners) or '-'} |"
        )
    lines[lines.index("| Path | Language | Lines | Deps | TODOs | Score |")] = (
        "| Path | Language | Lines | Deps | TODOs | Score | Owners |"
    )
    lines[lines.index("| --- | --- | ---: | ---: | ---: | ---: |")] = (
        "| --- | --- | ---: | ---: | ---: | ---: | --- |"
    )
    if report.doc_issues:
        lines.extend(["", "## Documentation Drift", ""])
        lines.extend(
            f"- `{item.doc_path}` references missing `{item.referenced_path}`" for item in report.doc_issues[:20]
        )
    if report.rule_violations:
        lines.extend(["", "## Structural Rules", ""])
        lines.extend(
            f"- `{item.rule}`: `{item.source}` -> `{item.target}` ({item.severity})"
            for item in report.rule_violations[:20]
        )
    if report.cycles:
        lines.extend(["", "## Dependency Cycles", ""])
        lines.extend(f"- {' -> '.join(item)}" for item in report.cycles[:12])
    if report.owners:
        lines.extend(["", "## Ownership", ""])
        lines.extend(f"- `{item['owner']}` owns {item['files']} tracked files" for item in report.owners[:12])
    if report.authors:
        lines.extend(["", "## Blame Authors", ""])
        lines.extend(f"- `{item['author']}` appears in {item['files']} tracked files" for item in report.authors[:12])
    if report.todos:
        lines.extend(["", "## TODO Feed", ""])
        lines.extend(
            f"- `{item.label}` in `{item.path}:{item.line}`: {item.text}" for item in report.todos[:20]
        )
    return "\n".join(lines)


def report_to_sarif(report: ProjectReport) -> str:
    results: list[dict] = []
    for todo in report.todos:
        results.append(
            {
                "ruleId": f"codeatlas.todo.{todo.label.lower()}",
                "level": "warning" if todo.label in {"TODO", "FIXME", "HACK"} else "note",
                "message": {"text": f"{todo.label}: {todo.text}"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": todo.path},
                            "region": {"startLine": todo.line},
                        }
                    }
                ],
            }
        )
    for issue in report.doc_issues:
        results.append(
            {
                "ruleId": "codeatlas.doc.missing-reference",
                "level": "warning",
                "message": {"text": f"{issue.doc_path} references missing file {issue.referenced_path}"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": issue.doc_path},
                        }
                    }
                ],
            }
        )
    for violation in report.rule_violations:
        results.append(
            {
                "ruleId": f"codeatlas.arch.{violation.rule}",
                "level": violation.severity,
                "message": {"text": f"{violation.message}: {violation.source} -> {violation.target}"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": violation.source},
                        }
                    }
                ],
            }
        )
    for item in report.files:
        for warning in item.warnings:
            results.append(
                {
                    "ruleId": f"codeatlas.file.{warning}",
                    "level": "note",
                    "message": {"text": f"{item.path} triggered warning {warning}"},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": item.path},
                            }
                        }
                    ],
                }
            )

    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "CodeAtlas",
                        "informationUri": "https://github.com/takahiro1994/codeatlas",
                        "rules": [
                            {"id": "codeatlas.todo.todo", "name": "TODO marker"},
                            {"id": "codeatlas.todo.fixme", "name": "FIXME marker"},
                            {"id": "codeatlas.todo.hack", "name": "HACK marker"},
                            {"id": "codeatlas.todo.note", "name": "NOTE marker"},
                            {"id": "codeatlas.doc.missing-reference", "name": "Missing doc reference"},
                            {"id": "codeatlas.arch.rule", "name": "Architectural rule violation"},
                        ],
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2)


def _todo_key(item: TodoItem) -> tuple[str, int, str, str]:
    return (item.path, item.line, item.label, item.text)


def _doc_issue_key(item: DocIssue) -> tuple[str, str, str]:
    return (item.doc_path, item.referenced_path, item.issue)


def compare_reports(base: ProjectReport, current: ProjectReport) -> ReportDelta:
    base_todos = {_todo_key(item): item for item in base.todos}
    current_todos = {_todo_key(item): item for item in current.todos}
    base_docs = {_doc_issue_key(item): item for item in base.doc_issues}
    current_docs = {_doc_issue_key(item): item for item in current.doc_issues}
    base_hotspots = {item.path: item.hotspot_score for item in base.files}
    current_hotspots = {item.path: item.hotspot_score for item in current.files}

    new_todos = [current_todos[key] for key in sorted(current_todos.keys() - base_todos.keys())]
    resolved_todos = [base_todos[key] for key in sorted(base_todos.keys() - current_todos.keys())]
    new_doc_issues = [current_docs[key] for key in sorted(current_docs.keys() - base_docs.keys())]
    resolved_doc_issues = [base_docs[key] for key in sorted(base_docs.keys() - current_docs.keys())]

    hotspot_regressions = []
    for path, current_score in sorted(current_hotspots.items()):
        base_score = base_hotspots.get(path)
        if base_score is None or current_score <= base_score:
            continue
        hotspot_regressions.append(
            {"path": path, "base_score": base_score, "current_score": current_score, "delta": current_score - base_score}
        )

    summary_lines = [
        f"New TODOs: {len(new_todos)}",
        f"Resolved TODOs: {len(resolved_todos)}",
        f"New doc issues: {len(new_doc_issues)}",
        f"Resolved doc issues: {len(resolved_doc_issues)}",
        f"Hotspot regressions: {len(hotspot_regressions)}",
    ]
    return ReportDelta(
        base_root=base.summary.root,
        current_root=current.summary.root,
        new_todos=new_todos,
        resolved_todos=resolved_todos,
        new_doc_issues=new_doc_issues,
        resolved_doc_issues=resolved_doc_issues,
        hotspot_regressions=hotspot_regressions,
        summary_lines=summary_lines,
    )


def format_delta(delta: ReportDelta) -> str:
    lines = [
        f"Base: {delta.base_root}",
        f"Current: {delta.current_root}",
        *delta.summary_lines,
    ]
    if delta.new_todos:
        lines.append("New TODO markers:")
        lines.extend(f"- {item.label} {item.path}:{item.line} {item.text}" for item in delta.new_todos[:10])
    if delta.new_doc_issues:
        lines.append("New doc issues:")
        lines.extend(f"- {item.doc_path} -> {item.referenced_path}" for item in delta.new_doc_issues[:10])
    if delta.hotspot_regressions:
        lines.append("Hotspot regressions:")
        lines.extend(
            f"- {item['path']}: {item['base_score']} -> {item['current_score']}"
            for item in delta.hotspot_regressions[:10]
        )
    return "\n".join(lines)


def format_owner_summary(report: ProjectReport) -> str:
    lines = [f"Root: {report.summary.root}", "Owners:"]
    if not report.owners:
        lines.append("- No CODEOWNERS file detected.")
        if not report.authors:
            return "\n".join(lines)
    for owner_info in report.owners[:20]:
        owner = owner_info["owner"]
        owned_files = [item for item in report.files if owner in item.owners]
        hottest = sorted(owned_files, key=lambda item: (-item.hotspot_score, item.path))[:3]
        hottest_text = ", ".join(f"{item.path}({item.hotspot_score})" for item in hottest) or "none"
        lines.append(f"- {owner}: {owner_info['files']} files; hotspots: {hottest_text}")
    if report.authors:
        lines.append("Authors:")
        for author_info in report.authors[:20]:
            author = author_info["author"]
            touched_files = [item for item in report.files if author in item.authors]
            hottest = sorted(touched_files, key=lambda item: (-item.hotspot_score, item.path))[:3]
            hottest_text = ", ".join(f"{item.path}({item.hotspot_score})" for item in hottest) or "none"
            lines.append(f"- {author}: {author_info['files']} files; hotspots: {hottest_text}")
    return "\n".join(lines)


def suggest_reviewers(report: ProjectReport) -> list[dict[str, object]]:
    scores: Counter[str] = Counter()
    reasons: defaultdict[str, list[str]] = defaultdict(list)
    ignored_authors = {"Not Committed Yet", "Unknown"}
    for file in report.files:
        weight = max(file.hotspot_score, 1)
        for owner in file.owners:
            scores[owner] += weight + 3
            reasons[owner].append(f"owner:{file.path}")
        for author in file.authors:
            if author in ignored_authors:
                continue
            scores[author] += weight
            reasons[author].append(f"author:{file.path}")
    return [
        {
            "candidate": candidate,
            "score": score,
            "reasons": sorted(set(reasons[candidate]))[:8],
        }
        for candidate, score in scores.most_common()
    ]


def format_reviewer_suggestions(report: ProjectReport) -> str:
    suggestions = suggest_reviewers(report)
    lines = [f"Root: {report.summary.root}", "Reviewer suggestions:"]
    if not suggestions:
        lines.append("- No reviewer candidates found.")
        return "\n".join(lines)
    for item in suggestions[:10]:
        lines.append(f"- {item['candidate']} ({item['score']}): {', '.join(item['reasons'])}")
    return "\n".join(lines)


def load_report(path: str | Path) -> ProjectReport:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    summary = Summary(**payload["summary"])
    files = []
    for item in payload["files"]:
        todos = [TodoItem(**todo) for todo in item.get("todos", [])]
        files.append(
            FileReport(
                path=item["path"],
                language=item["language"],
                lines=item["lines"],
                size_bytes=item["size_bytes"],
                owners=item.get("owners", []),
                authors=item.get("authors", []),
                outgoing_dependencies=item.get("outgoing_dependencies", []),
                incoming_dependencies=item.get("incoming_dependencies", []),
                todos=todos,
                warnings=item.get("warnings", []),
                hotspot_score=item.get("hotspot_score", 0),
            )
        )
    return ProjectReport(
        summary=summary,
        files=files,
        todos=[TodoItem(**item) for item in payload.get("todos", [])],
        doc_issues=[DocIssue(**item) for item in payload.get("doc_issues", [])],
        rule_violations=[RuleViolation(**item) for item in payload.get("rule_violations", [])],
        cycles=payload.get("cycles", []),
        graph=payload.get("graph", {"nodes": [], "edges": []}),
        insights=payload.get("insights", []),
        owners=payload.get("owners", []),
        authors=payload.get("authors", []),
        config=payload.get("config", {"path": None, "rules": [], "layers": [], "errors": []}),
    )


def focus_report_on_paths(report: ProjectReport, paths: list[str]) -> ProjectReport:
    normalized = set(paths)
    files = [item for item in report.files if item.path in normalized]
    todos = [item for item in report.todos if item.path in normalized]
    doc_issues = [item for item in report.doc_issues if item.doc_path in normalized or item.referenced_path in normalized]
    node_ids = {item.path for item in files}
    edges = [
        item
        for item in report.graph.get("edges", [])
        if item.get("source") in node_ids or item.get("target") in node_ids
    ]
    nodes = [item for item in report.graph.get("nodes", []) if item.get("id") in node_ids]
    summary = Summary(
        root=report.summary.root,
        total_files=len(files),
        total_lines=sum(item.lines for item in files),
        languages=dict(sorted(Counter(item.language for item in files).items())),
        total_dependencies=len(edges),
        todo_count=len(todos),
        warning_count=sum(len(item.warnings) for item in files) + len(doc_issues),
        hottest_files=[item.path for item in files[:5]],
    )
    insights = [
        f"Focused report across {len(files)} changed files.",
        f"{len(todos)} TODO-style markers are present in changed files.",
        f"{len(doc_issues)} documentation issues touch the changed surface.",
    ]
    owner_counter = Counter(owner for item in files for owner in item.owners)
    author_counter = Counter(author for item in files for author in item.authors)
    return ProjectReport(
        summary=summary,
        files=files,
        todos=todos,
        doc_issues=doc_issues,
        rule_violations=[item for item in report.rule_violations if item.source in normalized or item.target in normalized],
        cycles=[cycle for cycle in report.cycles if any(node in normalized for node in cycle)],
        graph={"nodes": nodes, "edges": edges},
        insights=insights,
        owners=[{"owner": owner, "files": count} for owner, count in owner_counter.most_common()],
        authors=[{"author": author, "files": count} for author, count in author_counter.most_common()],
        config=report.config,
    )
