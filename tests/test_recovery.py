"""Process-interruption behavior at the coordinator boundary."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from power_trading_agent.contracts import ValidationError
from power_trading_agent.data import actual_curves
from power_trading_agent.portfolio import Ledger
from power_trading_agent.runner import run_bundle, verify_output
from power_trading_agent.synthetic import demo_bundle


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "run"
        self.bundle = demo_bundle()
        self.bundle["days"] = self.bundle["days"][:2]

    def interrupt_second_day(self):
        def interrupted(bundle, target_date):
            if target_date == bundle["days"][1]["target_date"]:
                raise OSError("injected worker interruption")
            return actual_curves(bundle, target_date)
        with patch("power_trading_agent.runner.actual_curves", side_effect=interrupted):
            with self.assertRaises(OSError):
                run_bundle(self.bundle, self.output)

    def test_resume_keeps_completed_day_and_reassigns_interrupted_day(self):
        self.interrupt_second_day()
        run_bundle(self.bundle, self.output, resume=True)
        result = json.loads((self.output / "results.json").read_text())
        self.assertEqual([d["generation"] for d in result["days"]], [1, 2])
        self.assertTrue(verify_output(self.output)["verified"])

    def test_resume_cannot_revive_cancelled_task(self):
        self.interrupt_second_day()
        task = self.bundle["portfolio_id"] + "/day-ahead/" + self.bundle["days"][1]["target_date"]
        with Ledger(self.output / "ledger.sqlite3") as ledger:
            ledger.cancel_run(task)
        with self.assertRaises(ValidationError) as raised:
            run_bundle(self.bundle, self.output, resume=True)
        self.assertEqual(raised.exception.code, "task_cancelled")


if __name__ == "__main__":
    unittest.main()
