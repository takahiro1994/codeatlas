import json
import tempfile
import unittest
from pathlib import Path

from codeatlas.scanner import compare_reports, format_summary, load_report, report_to_markdown, report_to_sarif, scan_project
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


if __name__ == "__main__":
    unittest.main()
