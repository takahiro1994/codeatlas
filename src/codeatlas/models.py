from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class TodoItem:
    path: str
    line: int
    label: str
    text: str


@dataclass(slots=True)
class DocIssue:
    doc_path: str
    referenced_path: str
    issue: str


@dataclass(slots=True)
class RuleViolation:
    rule: str
    severity: str
    source: str
    target: str
    message: str


@dataclass(slots=True)
class SecurityFinding:
    kind: str
    severity: str
    path: str
    line: int
    message: str


@dataclass(slots=True)
class DuplicateBlock:
    fingerprint: str
    occurrences: list[dict[str, int | str]]
    line_count: int


@dataclass(slots=True)
class FileReport:
    path: str
    language: str
    lines: int
    size_bytes: int
    owners: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    outgoing_dependencies: list[str] = field(default_factory=list)
    incoming_dependencies: list[str] = field(default_factory=list)
    todos: list[TodoItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    health_details: dict[str, int] = field(default_factory=dict)
    code_health_score: int = 100
    hotspot_score: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["todos"] = [asdict(item) for item in self.todos]
        return data


@dataclass(slots=True)
class Summary:
    root: str
    total_files: int
    total_lines: int
    languages: dict[str, int]
    total_dependencies: int
    todo_count: int
    warning_count: int
    hottest_files: list[str]


@dataclass(slots=True)
class ProjectReport:
    summary: Summary
    files: list[FileReport]
    todos: list[TodoItem]
    doc_issues: list[DocIssue]
    rule_violations: list[RuleViolation]
    security_findings: list[SecurityFinding]
    duplicate_blocks: list[DuplicateBlock]
    cycles: list[list[str]]
    graph: dict[str, list[dict[str, str]]]
    insights: list[str]
    owners: list[dict[str, int]]
    authors: list[dict[str, int]]
    config: dict

    def to_dict(self) -> dict:
        return {
            "summary": asdict(self.summary),
            "files": [item.to_dict() for item in self.files],
            "todos": [asdict(item) for item in self.todos],
            "doc_issues": [asdict(item) for item in self.doc_issues],
            "rule_violations": [asdict(item) for item in self.rule_violations],
            "security_findings": [asdict(item) for item in self.security_findings],
            "duplicate_blocks": [asdict(item) for item in self.duplicate_blocks],
            "cycles": self.cycles,
            "graph": self.graph,
            "insights": self.insights,
            "owners": self.owners,
            "authors": self.authors,
            "config": self.config,
        }


@dataclass(slots=True)
class ReportDelta:
    base_root: str
    current_root: str
    new_todos: list[TodoItem]
    resolved_todos: list[TodoItem]
    new_doc_issues: list[DocIssue]
    resolved_doc_issues: list[DocIssue]
    hotspot_regressions: list[dict[str, int | str]]
    summary_lines: list[str]

    def to_dict(self) -> dict:
        return {
            "base_root": self.base_root,
            "current_root": self.current_root,
            "new_todos": [asdict(item) for item in self.new_todos],
            "resolved_todos": [asdict(item) for item in self.resolved_todos],
            "new_doc_issues": [asdict(item) for item in self.new_doc_issues],
            "resolved_doc_issues": [asdict(item) for item in self.resolved_doc_issues],
            "hotspot_regressions": self.hotspot_regressions,
            "summary_lines": self.summary_lines,
        }
