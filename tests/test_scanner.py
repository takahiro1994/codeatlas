import unittest
from pathlib import Path

from codeatlas.scanner import format_summary, report_to_markdown, scan_project
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
        html = render_dashboard(str(FIXTURE_ROOT))
        self.assertIn("CodeAtlas", html)
        self.assertIn("Hotspots", html)
        self.assertIn(str(FIXTURE_ROOT.resolve()), summary)
        self.assertIn("# CodeAtlas Report", markdown)


if __name__ == "__main__":
    unittest.main()
