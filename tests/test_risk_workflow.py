"""End-to-end decisions, artifact isolation, and independent monthly limits."""
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from power_trading_agent.__main__ import main
from power_trading_agent.contracts import ValidationError, write_json
from power_trading_agent.dashboard import risk_html, review_html
from power_trading_agent.risk import assess_risk, default_profiles
from power_trading_agent.risk_workflow import (
    context_from_bundle, create_decision_workspace, create_risk_workspace,
    demo_workspaces, illustrative_profiles, synthetic_context, synthetic_actuals,
)
from power_trading_agent.review import record_decision, review_decision
from power_trading_agent.synthetic import demo_bundle


class RiskWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_cli_daily_research_lifecycle_and_new_directory(self):
        path = self.root / "demo"
        code, _, err = self.cli("review-demo", "--output", str(path))
        self.assertEqual(code, 0, err)
        report = json.loads((path / "risk/risk.json").read_text())
        decision = json.loads((path / "choice/decision.json").read_text())
        self.assertEqual(decision["actor"], "synthetic-demo-operator")
        request = {k: decision[k] for k in ("report_hash", "profile_id", "plan_id", "actor", "reason", "selected_at")}
        write_json(self.root / "request.json", request)
        code, _, err = self.cli("decide", "--risk", str(path / "risk/risk.json"), "--request", str(self.root / "request.json"), "--output", str(self.root / "choice"))
        self.assertEqual(code, 0, err)
        code, _, err = self.cli("review", "--risk", str(path / "risk/risk.json"), "--decision", str(self.root / "choice/decision.json"), "--actuals", str(path / "review/actuals.json"), "--output", str(self.root / "review"))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.cli("review-demo", "--output", str(path))[0], 2)
        self.assertEqual(json.loads((self.root / "review/review.json").read_text())["report_hash"], report["report_hash"])

    def test_no_actual_file_in_risk_workspace_and_default_limits_block(self):
        c = synthetic_context()
        write_json(self.root / "context.json", c)
        code, _, err = self.cli("risk", "--input", str(self.root / "context.json"), "--output", str(self.root / "risk"))
        self.assertEqual(code, 0, err)
        report = json.loads((self.root / "risk/risk.json").read_text())
        self.assertTrue(all(not p["admissible_plan_ids"] for p in report["profile_results"]))
        self.assertFalse((self.root / "risk/actuals.json").exists())
        self.assertNotIn("invented-post-delivery-labels", (self.root / "risk/risk.html").read_text())

    def test_context_adapter_does_not_read_actuals(self):
        bundle = demo_bundle()
        day = bundle["days"][0]
        c = context_from_bundle(bundle, day["target_date"], day["origin"])
        bundle["actuals"] = [{"malformed": "must not be read"}]
        self.assertEqual(c, context_from_bundle(bundle, day["target_date"], day["origin"]))
        self.assertEqual(assess_risk(c)["status"], "research_only")

    def test_html_escapes_untrusted_labels_and_no_network_assets(self):
        c = synthetic_context()
        c["portfolio_id"] = '</script><script>alert("x")</script>'
        profiles = illustrative_profiles(c)
        profiles[0]["label"] = '<img src=x onerror=alert(1)>'
        report = assess_risk(c, profiles)
        output = risk_html(report)
        self.assertNotIn(c["portfolio_id"], output)
        self.assertNotIn(profiles[0]["label"], output)
        self.assertIn("\\u003c/script\\u003e", output)
        self.assertIn("connect-src 'none'", output)
        self.assertNotIn('<script src=', output)
        self.assertIn('<button id="download" disabled>', output)

    def test_stale_choice_and_invalid_request_leave_no_output(self):
        c = synthetic_context()
        r = assess_risk(c, illustrative_profiles(c))
        p = r["profile_results"][1]["admissible_plan_ids"][0]
        request = {"profile_id": "steady", "plan_id": p, "actor": "tester", "reason": "fixture", "selected_at": c["origin"], "report_hash": "old"}
        with self.assertRaises(ValidationError):
            create_decision_workspace(r, request, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())
        request.pop("report_hash")
        request["unexpected"] = True
        with self.assertRaises(ValidationError):
            create_decision_workspace(r, request, self.root / "bad")

    def test_monthly_netting_cannot_hide_daily_loss(self):
        c = synthetic_context("month", "2026-02")
        c["f"] = [0 if h % 24 == 0 else 10 for h in range(672)]
        c["da"] = [500 if h < 336 else 100 for h in range(672)]
        c["rt"] = [100 if h < 336 else 500 for h in range(672)]
        c["rule"]["deviation_fee_cny_per_mwh"] = 0
        profiles = default_profiles()
        for p in profiles:
            p["limits"] = {key: 1e12 for key in p["limits"]}
            p["limits"].update(max_incremental_loss_cny=0, max_daily_incremental_loss_cny=100)
        r = assess_risk(c, profiles, {"load_factors": [1], "da_shifts": [0], "rt_shifts": [0], "shock_hours": [0], "surge_add_mwh": 0})
        p = next(p for p in r["plans"] if p["name"] == "constant_k_1.1000")
        self.assertAlmostEqual(p["metrics"]["max_incremental_loss_cny"], 0)
        self.assertAlmostEqual(p["metrics"]["max_daily_incremental_loss_cny"], 9200)
        check = next(x for x in r["profile_results"][1]["checks"] if x["plan_id"] == p["plan_id"])
        self.assertEqual([v["metric"] for v in check["violations"]], ["max_daily_incremental_loss_cny"])

    def test_metric_witnesses_point_to_frozen_scenarios(self):
        r = assess_risk(synthetic_context())
        ids = {s["scenario_id"] for s in r["scenarios"]["items"]}
        for p in r["plans"]:
            self.assertEqual(set(p["metric_witnesses"]), set(p["metrics"]))
            for witness in p["metric_witnesses"].values():
                self.assertTrue(witness["scenario_id"] in ids or witness["scenario_id"] is None)

    def test_review_page_does_not_claim_execution(self):
        c = synthetic_context()
        r = assess_risk(c, illustrative_profiles(c))
        d = record_decision(r, "steady", r["profile_results"][1]["admissible_plan_ids"][0], "tester", "fixture", c["origin"])
        review = review_decision(r, d, synthetic_actuals(c))
        page = review_html(review)
        self.assertIn("未提供，不能把选择称为实际成交", page)
        self.assertIn("顺序会影响分项", page)
        self.assertNotIn('<script', page)

    def test_cli_monthly_research_uses_one_origin(self):
        path = self.root / "month"
        code, _, err = self.cli("review-demo", "--period-type", "month", "--period", "2026-02", "--output", str(path))
        self.assertEqual(code, 0, err)
        context = json.loads((path / "risk/context.json").read_text())
        self.assertEqual(len(context["hours"]), 672)
        self.assertEqual(context["origin"], "2026-01-31T12:00:00+08:00")


if __name__ == "__main__":
    unittest.main()
