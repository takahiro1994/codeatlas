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
class FileReport:
    path: str
    language: str
    lines: int
    size_bytes: int
    outgoing_dependencies: list[str] = field(default_factory=list)
    incoming_dependencies: list[str] = field(default_factory=list)
    todos: list[TodoItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
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
    graph: dict[str, list[dict[str, str]]]
    insights: list[str]

    def to_dict(self) -> dict:
        return {
            "summary": asdict(self.summary),
            "files": [item.to_dict() for item in self.files],
            "todos": [asdict(item) for item in self.todos],
            "doc_issues": [asdict(item) for item in self.doc_issues],
            "graph": self.graph,
            "insights": self.insights,
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
