import json
import tempfile
import unittest
from pathlib import Path

from codeatlas.scanner import (
    compare_reports,
    detect_base_ref,
    extract_todos,
    extract_python_dependencies,
    focus_report_on_paths,
    format_summary,
    format_owner_summary,
    format_reviewer_suggestions,
    list_worktree_files,
    load_report,
    report_to_markdown,
    report_to_sarif,
    scan_project,
    suggest_reviewers,
)
from codeatlas.server import render_dashboard


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "examples" / "sample_repo"


class ScannerTests(unittest.TestCase):
    def test_scan_project_detects_core_signals(self) -> None:
        report = scan_project(FIXTURE_ROOT)
        self.assertGreaterEqual(report.summary.total_files, 4)
        self.assertGreaterEqual(report.summary.todo_count, 2)
        self.assertTrue(any(item.issue == "missing-reference" for item in report.doc_issues))
        self.assertTrue(any(file.path.endswith("app.py") for file in report.files))

    def test_summary_and_dashboard_render(self) -> None:
        report = scan_project(FIXTURE_ROOT)
        summary = format_summary(report)
        markdown = report_to_markdown(report)
        sarif = report_to_sarif(report)
        html = render_dashboard(str(FIXTURE_ROOT))
        self.assertIn("CodeAtlas", html)
        self.assertIn("Hotspots", html)
        self.assertIn(str(FIXTURE_ROOT.resolve()), summary)
        self.assertIn("# CodeAtlas Report", markdown)
        self.assertIn('"version": "2.1.0"', sarif)

    def test_compare_reports_and_reload_json(self) -> None:
        base = scan_project(FIXTURE_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            sample = tmp_root / "sample"
            sample.mkdir()
            for source in FIXTURE_ROOT.rglob("*"):
                target = sample / source.relative_to(FIXTURE_ROOT)
                if source.is_dir():
                    target.mkdir(exist_ok=True)
                else:
                    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            app_path = sample / "src" / "app.py"
            app_path.write_text(app_path.read_text(encoding="utf-8") + "\n# TODO: new regression\n", encoding="utf-8")
            current = scan_project(sample)
            delta = compare_reports(base, current)
            self.assertEqual(len(delta.new_todos), 1)
            self.assertEqual(delta.new_todos[0].text, "new regression")

            payload = current.to_dict()
            report_path = tmp_root / "report.json"
            report_path.write_text(json.dumps(payload), encoding="utf-8")
            reloaded = load_report(report_path)
            self.assertEqual(reloaded.summary.total_files, current.summary.total_files)

    def test_focus_report_on_paths(self) -> None:
        report = scan_project(FIXTURE_ROOT)
        focused = focus_report_on_paths(report, ["src/app.py"])
        self.assertEqual(focused.summary.total_files, 1)
        self.assertEqual(focused.files[0].path, "src/app.py")
        self.assertTrue(all(item.path == "src/app.py" for item in focused.todos))

    def test_codeowners_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("# TODO: keep owner mapping\n", encoding="utf-8")
            (root / ".github").mkdir()
            (root / ".github" / "CODEOWNERS").write_text("src/* @team-core @alice\n", encoding="utf-8")
            report = scan_project(root)
            app_file = next(item for item in report.files if item.path == "src/app.py")
            self.assertEqual(app_file.owners, ["@team-core", "@alice"])
            self.assertTrue(any(item["owner"] == "@team-core" for item in report.owners))
            owner_summary = format_owner_summary(report)
            self.assertIn("@team-core", owner_summary)

    def test_reviewer_suggestions_use_owners(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("# TODO: keep owner mapping\n", encoding="utf-8")
            (root / ".github").mkdir()
            (root / ".github" / "CODEOWNERS").write_text("src/* @team-core @alice\n", encoding="utf-8")
            report = scan_project(root)
            focused = focus_report_on_paths(report, ["src/app.py"])
            suggestions = suggest_reviewers(focused)
            summary = format_reviewer_suggestions(focused)
            self.assertTrue(any(item["candidate"] == "@team-core" for item in suggestions))
            self.assertIn("@team-core", summary)

    def test_todo_extraction_prefers_comment_context(self) -> None:
        py_items = extract_todos(
            "demo.py",
            'message = "TODO should not count"\n# TODO: keep this one\nvalue = 1\n',
        )
        md_items = extract_todos(
            "README.md",
            "- [ ] TODO: checklist item\nParagraph mentioning TODO should not count.\n",
        )
        self.assertEqual(len(py_items), 1)
        self.assertEqual(py_items[0].text, "keep this one")
        self.assertEqual(len(md_items), 1)

    def test_config_rules_and_cycle_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "ui").mkdir(parents=True)
            (root / "src" / "db").mkdir(parents=True)
            (root / "src" / "ui" / "screen.py").write_text("from db.repo import load\n", encoding="utf-8")
            (root / "src" / "db" / "repo.py").write_text("from ui.screen import render\n", encoding="utf-8")
            (root / "codeatlas.json").write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "name": "ui-must-not-import-db",
                                "from": ["src/ui/"],
                                "to": ["src/db/"],
                                "severity": "warning",
                                "message": "UI must not depend on DB"
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = scan_project(root)
            self.assertEqual(report.config["path"], "codeatlas.json")
            self.assertEqual(len(report.rule_violations), 1)
            self.assertEqual(report.rule_violations[0].rule, "ui-must-not-import-db")
            self.assertEqual(len(report.cycles), 1)
            self.assertIn("src/ui/screen.py", report.cycles[0])

    def test_layer_rules_and_ast_python_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src" / "ui").mkdir(parents=True)
            (root / "src" / "domain").mkdir(parents=True)
            (root / "src" / "infra").mkdir(parents=True)
            ui_path = root / "src" / "ui" / "screen.py"
            ui_text = "from ..infra.repo import load\n"
            ui_path.write_text(ui_text, encoding="utf-8")
            (root / "src" / "infra" / "repo.py").write_text("def load():\n    return 1\n", encoding="utf-8")
            (root / "codeatlas.json").write_text(
                json.dumps(
                    {
                        "layers": [
                            {"name": "ui", "paths": ["src/ui/"], "may_depend_on": ["domain"], "message": "UI must stay above domain"},
                            {"name": "domain", "paths": ["src/domain/"], "may_depend_on": []},
                            {"name": "infra", "paths": ["src/infra/"], "may_depend_on": []}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            deps = extract_python_dependencies(Path("src/ui/screen.py"), ui_text)
            report = scan_project(root)
            self.assertIn("..infra.repo", deps)
            self.assertTrue(any(item.rule == "layer:ui" for item in report.rule_violations))

    def test_detect_base_ref_and_worktree_listing(self) -> None:
        self.assertTrue(detect_base_ref(FIXTURE_ROOT.parent) in {"origin/main", "main", "origin/master", "master", "HEAD~1"})
        self.assertIsInstance(list_worktree_files(FIXTURE_ROOT.parent), list)

    def test_security_and_health_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "import subprocess\nAPI_KEY = 'abcd1234SECRET'\n"
                "def run(cmd):\n    if cmd:\n        if len(cmd) > 1:\n            subprocess.run(cmd, shell=True)\n",
                encoding="utf-8",
            )
            (root / "requirements.txt").write_text("requests>=2.0\n", encoding="utf-8")
            report = scan_project(root)
            app = next(item for item in report.files if item.path == "app.py")
            self.assertLess(app.code_health_score, 100)
            self.assertTrue(any(item.kind == "possible-secret" for item in report.security_findings))
            self.assertTrue(any(item.kind == "shell-true" for item in report.security_findings))
            self.assertTrue(any(item.kind == "unpinned-python-dependency" for item in report.security_findings))


if __name__ == "__main__":
    unittest.main()
