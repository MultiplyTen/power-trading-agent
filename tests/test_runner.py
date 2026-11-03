"""v1.1 coordinator/tool integration checks, added 2026-11-03.

Tests use independent invariants and explicitly task-scoped temporary storage.
"""
import copy
import csv
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from power_trading_agent.contracts import ValidationError, digest, write_json
from power_trading_agent.data import apply_customer_events, build_snapshot
from power_trading_agent.events import parse_customer_message
from power_trading_agent.portfolio import Ledger
from power_trading_agent.runner import evaluate_day, run_bundle, verify_output
from power_trading_agent.synthetic import demo_bundle
from power_trading_agent.tools import TOOL_CATALOG, dispatch


class RunnerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pta-runner-test-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = demo_bundle()

    def one_day(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["days"] = bundle["days"][:1]
        return bundle

    def ledger(self):
        ledger = Ledger(self.root / "decision.sqlite3")
        self.addCleanup(ledger.close)
        return ledger

    def produce(self):
        out = self.root / "run"
        bundle = self.one_day()
        run_bundle(bundle, out)
        return bundle, out

    def rehash(self, out, name):
        manifest = json.loads((out / "manifest.json").read_text())
        manifest["files"][name] = hashlib.sha256((out / name).read_bytes()).hexdigest()
        write_json(out / "manifest.json", manifest)

    def rewrite_csv(self, out, transform):
        with (out / "hourly.csv").open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, list(reader)
        transform(rows)
        with (out / "hourly.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        self.rehash(out, "hourly.csv")

    def test_demo_complete_28_days_2016_hourly_rows(self):
        out = self.root / "full-demo"
        result = run_bundle(self.bundle, out)
        self.assertEqual(result["days"], 28)
        self.assertEqual(result["status"], "research_only")
        stored = json.loads((out / "results.json").read_text())
        self.assertEqual(len(stored["days"]), 28)
        self.assertEqual(set(stored["metrics"]), {"baseline", "spread_rule", "bounded_rule"})
        self.assertFalse(stored["business_ready"])
        self.assertFalse(stored["production_approved"])
        self.assertFalse(stored["deployed"])
        for day in stored["days"]:
            self.assertTrue(day["no_automatic_selection"])
            self.assertEqual(len(day["plans"]), 3)
        with (out / "hourly.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 28 * 24 * 3)
        self.assertEqual(len({(row["target_date"], row["strategy"], row["hour"]) for row in rows}), 2016)
        self.assertEqual(verify_output(out)["days"], 28)
        self.assertEqual(json.loads((out / "input.json").read_text()), self.bundle)

    def test_saved_run_resumes_without_changing_results(self):
        bundle, out = self.produce()
        before = (out / "results.json").read_bytes()
        before_csv = (out / "hourly.csv").read_bytes()
        resumed = run_bundle(copy.deepcopy(bundle), out, resume=True)
        self.assertEqual(resumed["days"], 1)
        self.assertEqual((out / "results.json").read_bytes(), before)
        self.assertEqual((out / "hourly.csv").read_bytes(), before_csv)
        self.assertTrue(verify_output(out)["verified"])

    def test_existing_output_cannot_be_silently_overwritten(self):
        bundle, out = self.produce()
        with self.assertRaises(ValidationError):
            run_bundle(bundle, out)

    def test_missing_risk_budget_remains_unselected(self):
        bundle = self.one_day()
        bundle["risk_budget_cny"] = None
        out = self.root / "missing-budget"
        run_bundle(bundle, out)
        result = json.loads((out / "results.json").read_text())
        self.assertTrue(result["days"][0]["no_automatic_selection"])
        self.assertTrue(all(plan["risk_status"] == "needs_risk_budget" for plan in result["days"][0]["plans"]))

    def test_actual_label_changes_do_not_change_decision_hash(self):
        ledger = self.ledger()
        for event in self.bundle["events"]:
            ledger.record_event(event)
        day = self.bundle["days"][0]
        original = evaluate_day(self.bundle, day, ledger)
        changed = copy.deepcopy(self.bundle)
        for record in changed["actuals"]:
            record["l"] = [9999] * 24
            record["da"] = [99999] * 24
            record["rt"] = [-99999] * 24
        rescored = evaluate_day(changed, day, ledger)
        self.assertEqual(original["decision_hash"], rescored["decision_hash"])
        self.assertEqual([p["plan_hash"] for p in original["plans"]], [p["plan_hash"] for p in rescored["plans"]])

    def test_revision_chronology_is_checked_independent_of_input_order(self):
        bundle = self.one_day()
        day = bundle["days"][0]
        original = bundle["records"][0]
        prefix = original["available_time"].split("T")[0]
        revisions = []
        for revision, hour in ((3, 10), (1, 9), (2, 8)):
            timestamp = "{}T{:02d}:00:00+08:00".format(prefix, hour)
            revisions.append(dict(original, revision=revision, available_time=timestamp,
                                  issue_time=timestamp, received_at=timestamp))
        bundle["records"] = revisions + [record for record in bundle["records"]
                                          if record["record_id"] != original["record_id"]]
        with self.assertRaises(ValidationError):
            build_snapshot(bundle, day["target_date"], day["origin"])

    def test_stop_event_only_removes_affected_customer_hours(self):
        day = next(day for day in self.bundle["days"] if day["target_date"] == "2026-01-21")
        ledger = self.ledger()
        for event in self.bundle["events"]:
            ledger.record_event(event)
        result = evaluate_day(self.bundle, day, ledger)
        customer_curves = result["snapshot"]["customer_forecasts"]
        for hour in range(24):
            expected = customer_curves["customer-b"][hour]
            if not 10 <= hour < 15:
                expected += customer_curves["customer-a"][hour]
            self.assertAlmostEqual(result["f"][hour], expected)
        self.assertEqual(result["portfolio_state"]["holdings_mwh"], [8] * 24)
        self.assertEqual(result["portfolio_state"]["intents_mwh"], [3] * 24)

    def test_overlapping_confirmed_customer_events_require_resolution(self):
        day = next(day for day in self.bundle["days"] if day["target_date"] == "2026-01-21")
        ledger = self.ledger()
        for event in self.bundle["events"]:
            ledger.record_event(event)
        stop = next(event for event in self.bundle["events"] if event["kind"] == "customer_event")
        ledger.record_event(dict(stop, event_id="conflicting-stop", load_multiplier=0.5))
        with self.assertRaises(ValidationError) as context:
            evaluate_day(self.bundle, day, ledger)
        self.assertEqual(context.exception.code, "EVENT_CONFLICT")

    def test_unknown_event_customer_is_rejected(self):
        day = next(day for day in self.bundle["days"] if day["target_date"] == "2026-01-21")
        snapshot = build_snapshot(self.bundle, day["target_date"], day["origin"])
        event = next(event for event in self.bundle["events"] if event["kind"] == "customer_event")
        with self.assertRaises(ValidationError):
            apply_customer_events(snapshot, {"customer_events": [dict(event, customer_id="unknown-customer")]})

    def test_tool_catalog_exposes_only_bounded_operations(self):
        self.assertEqual({tool["name"] for tool in TOOL_CATALOG},
                         {"validate_input", "portfolio_state", "evaluate_day", "parse_customer_event"})
        with self.assertRaises(ValidationError):
            dispatch({"name": "run_shell", "arguments": {"command": "anything"}})

    def test_tool_rejects_undeclared_arguments(self):
        day = self.bundle["days"][0]
        with self.assertRaises(ValidationError):
            dispatch({"name": "validate_input", "arguments": {
                "bundle": self.bundle, "target_date": day["target_date"], "origin": day["origin"],
                "output_path": "/unrequested/path"}})

    def test_tool_refuses_cross_portfolio_events(self):
        day = self.bundle["days"][0]
        event = dict(self.bundle["events"][0], portfolio_id="different-portfolio")
        with self.assertRaises(ValidationError) as context:
            dispatch({"name": "portfolio_state", "arguments": {
                "portfolio_id": self.bundle["portfolio_id"], "target_date": day["target_date"],
                "origin": day["origin"], "events": [event]}})
        self.assertEqual(context.exception.code, "SCOPE_MISMATCH")

    def test_evaluation_tool_refuses_live_scope(self):
        day = self.bundle["days"][0]
        bundle = copy.deepcopy(self.bundle)
        bundle["scope"] = "live"
        with self.assertRaises(ValidationError) as context:
            dispatch({"name": "evaluate_day", "arguments": {
                "bundle": bundle, "target_date": day["target_date"], "origin": day["origin"]}})
        self.assertEqual(context.exception.code, "UNSUPPORTED_SCOPE")

    def test_tool_evaluation_matches_direct_service(self):
        day = self.bundle["days"][0]
        ledger = self.ledger()
        for event in self.bundle["events"]:
            ledger.record_event(event)
        direct = evaluate_day(self.bundle, day, ledger)
        tool = dispatch({"name": "evaluate_day", "arguments": {
            "bundle": self.bundle, "target_date": day["target_date"], "origin": day["origin"]}})
        self.assertEqual(tool, direct)

    def test_absolute_event_template_is_pending_only(self):
        event = parse_customer_message("2026-01-21 10:00 至 2026-01-21 15:00 停产",
                                       "portfolio-a", "customer-a", "2026-01-20T10:00:00+08:00", "message", "event-a")
        self.assertEqual(event["status"], "pending_confirmation")
        self.assertEqual(event["event"]["status"], "pending")
        self.assertEqual(event["event"]["start"], "2026-01-21T10:00:00+08:00")

    def test_relative_negated_cancelled_events_cannot_change_load(self):
        messages = ["下周一停产三天", "2026-01-21 10:00 至 2026-01-21 15:00 不停产",
                    "取消 2026-01-21 10:00 至 2026-01-21 15:00 停产",
                    "2026-01-21 10:00 至 2026-01-21 15:00 停产，然后恢复"]
        for message in messages:
            with self.subTest(message=message):
                event = parse_customer_message(message, "portfolio-a", "customer-a",
                                               "2026-01-20T10:00:00+08:00", "message", "event-a")
                self.assertEqual(event["status"], "needs_clarification")
                self.assertIsNone(event["event"])

    def test_reversed_event_interval_is_rejected(self):
        with self.assertRaises(ValidationError):
            parse_customer_message("2026-01-21 15:00 至 2026-01-21 10:00 停产",
                                   "portfolio-a", "customer-a", "2026-01-20T10:00:00+08:00", "message", "event-a")

    def test_artifact_tampering_is_detected(self):
        _, out = self.produce()
        with (out / "report.md").open("a", encoding="utf-8") as stream:
            stream.write("\nUnrecorded edit\n")
        with self.assertRaises(ValidationError):
            verify_output(out)

    def test_duplicate_hour_is_detected_even_with_updated_file_hash(self):
        _, out = self.produce()
        self.rewrite_csv(out, lambda rows: rows[1].update(hour=rows[0]["hour"]))
        with self.assertRaises(ValidationError):
            verify_output(out)

    def test_nonfinite_cost_is_detected_even_with_updated_file_hash(self):
        _, out = self.produce()
        self.rewrite_csv(out, lambda rows: rows[0].update(cost_CNY="nan"))
        with self.assertRaises(ValidationError):
            verify_output(out)

    def test_unregistered_strategy_row_is_detected(self):
        _, out = self.produce()
        self.rewrite_csv(out, lambda rows: rows.append(dict(rows[0], strategy="unregistered-strategy")))
        with self.assertRaises(ValidationError):
            verify_output(out)

    def test_api_resume_rejects_modified_archived_input(self):
        bundle, out = self.produce()
        modified = copy.deepcopy(bundle)
        modified["risk_budget_cny"] += 1
        write_json(out / "input.json", modified)
        # API input and original run_meta agree; archived input deliberately does not.
        with self.assertRaises(ValidationError):
            run_bundle(bundle, out, resume=True)

    def test_api_resume_rejects_meta_changed_without_matching_archive(self):
        bundle, out = self.produce()
        modified = copy.deepcopy(bundle)
        modified["risk_budget_cny"] += 1
        meta = json.loads((out / "run_meta.json").read_text())
        meta["input_hash"] = digest(modified)
        write_json(out / "run_meta.json", meta)
        with self.assertRaises(ValidationError):
            run_bundle(modified, out, resume=True)

    def test_verify_checks_input_hash_against_run_metadata(self):
        bundle, out = self.produce()
        changed = copy.deepcopy(bundle)
        changed["risk_budget_cny"] += 1
        write_json(out / "input.json", changed)
        self.rehash(out, "input.json")
        with self.assertRaises(ValidationError):
            verify_output(out)


if __name__ == "__main__":
    unittest.main()
