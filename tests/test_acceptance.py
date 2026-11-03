"""Checks the independent evaluator's execution and evidence handling."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from power_trading_agent.acceptance import Case, build_cases, run_benchmark


class AcceptanceSuiteTests(unittest.TestCase):
    def test_named_cases_are_independent_and_unique(self):
        cases = build_cases()
        self.assertGreaterEqual(len(cases), 30)
        self.assertEqual(len(cases), len({case.case_id for case in cases}))
        self.assertEqual({case.group for case in cases}, {"data", "portfolio", "task", "economics"})

    def test_all_business_cases(self):
        for case in build_cases():
            with self.subTest(case=case.case_id, description=case.description):
                case.check()

    def test_failure_is_recorded_and_does_not_abort_other_cases(self):
        def fail():
            raise AssertionError("injected independent mismatch")
        cases = [Case("bad", "test", "failure", "expected rejection", fail),
                 Case("good", "test", "success", "no failure", lambda: None)]
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            output = Path(directory) / "evidence"
            with patch("power_trading_agent.acceptance.build_cases", return_value=cases):
                result = run_benchmark(output)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["passed"], 1)
            self.assertEqual(result["status"], "failed")
            stored = json.loads((output / "benchmark.json").read_text())
            self.assertIn("injected", stored["cases"][0]["observed"])
            self.assertEqual(len((output / "cases.jsonl").read_text().splitlines()), 2)
            self.assertIn("FAIL", (output / "benchmark.md").read_text())
            with self.assertRaises(FileExistsError):
                run_benchmark(output)


if __name__ == "__main__":
    unittest.main()
