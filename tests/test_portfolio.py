"""Portfolio invariants verified against hand-calculated quantities and states."""

import tempfile
import unittest
from pathlib import Path

from power_trading_agent.contracts import ValidationError
from power_trading_agent.portfolio import Ledger


DAY = "2026-10-15"
ORIGIN = "2026-10-14T12:00:00+08:00"


def event(**changes):
    value = dict(portfolio_id="P", event_id="trade-1", revision=1, kind="trade",
                 available_time="2026-10-14T09:00:00+08:00",
                 start="2026-10-15T00:00:00+08:00", end="2026-10-16T00:00:00+08:00",
                 status="confirmed", source="synthetic", hourly_mwh=2.0,
                 price_cny_per_mwh=300.0)
    value.update(changes)
    return value


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ledger.sqlite3"
        self.ledger = Ledger(self.path)

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def state(self, **kwargs):
        return self.ledger.state(kwargs.get("portfolio_id", "P"), DAY, kwargs.get("as_of", ORIGIN))

    def test_trade_quantity_cost_and_negative_price(self):
        self.ledger.record_event(event(price_cny_per_mwh=-10))
        state = self.state()
        self.assertEqual(sum(state["holdings_mwh"]), 48)
        self.assertEqual(sum(state["holding_cost_cny"]), -480)

    def test_exact_duplicate_is_idempotent(self):
        self.assertTrue(self.ledger.record_event(event()))
        self.assertFalse(self.ledger.record_event(event()))
        self.assertEqual(sum(self.state()["holdings_mwh"]), 48)

    def test_conflicting_same_revision_is_rejected(self):
        self.ledger.record_event(event())
        with self.assertRaises(ValidationError):
            self.ledger.record_event(event(hourly_mwh=8))
        self.assertEqual(sum(self.state()["holdings_mwh"]), 48)

    def test_revision_as_of_and_cancel(self):
        self.ledger.record_event(event())
        self.ledger.record_event(event(revision=2, status="cancelled", available_time="2026-10-14T13:00:00+08:00"))
        self.assertEqual(sum(self.state()["holdings_mwh"]), 48)
        self.assertEqual(sum(self.state(as_of="2026-10-14T14:00:00+08:00")["holdings_mwh"]), 0)

    def test_late_revision_changes_only_new_snapshot(self):
        self.ledger.record_event(event())
        before = self.state()
        self.ledger.record_event(event(revision=2, hourly_mwh=3, available_time="2026-10-14T13:00:00+08:00"))
        self.assertEqual(self.state()["state_id"], before["state_id"])
        self.assertEqual(sum(self.state(as_of="2026-10-14T14:00:00+08:00")["holdings_mwh"]), 72)

    def test_pending_trade_not_a_position(self):
        self.ledger.record_event(event(status="pending"))
        self.assertEqual(sum(self.state()["holdings_mwh"]), 0)

    def test_intent_and_declaration_separate_from_trade(self):
        self.ledger.record_event(event(event_id="intent", kind="intent", status="pending", hourly_mwh=4))
        self.ledger.record_event(event(event_id="declaration", kind="declaration", hourly_mwh=5))
        state = self.state()
        self.assertEqual(sum(state["holdings_mwh"]), 0)
        self.assertEqual(sum(state["intents_mwh"]), 96)
        self.assertEqual(sum(state["declarations_mwh"]), 120)

    def test_pending_revision_replaces_confirmed_version(self):
        self.ledger.record_event(event())
        self.ledger.record_event(event(revision=2, status="pending", available_time="2026-10-14T10:00:00+08:00"))
        self.assertEqual(sum(self.state()["holdings_mwh"]), 0)

    def test_portfolio_isolation_and_scope_change_rejection(self):
        self.ledger.record_event(event())
        self.assertEqual(sum(self.state(portfolio_id="OTHER")["holdings_mwh"]), 0)
        with self.assertRaises(ValidationError):
            self.ledger.record_event(event(portfolio_id="OTHER", revision=2))

    def test_customer_scope_cannot_change(self):
        item = event(kind="customer_event", customer_id="A", load_multiplier=0)
        self.ledger.record_event(item)
        with self.assertRaises(ValidationError):
            self.ledger.record_event(dict(item, revision=2, customer_id="B"))
        self.assertEqual(self.state()["customer_events"][0]["customer_id"], "A")

    def test_unconfirmed_customer_event_excluded(self):
        self.ledger.record_event(event(kind="customer_event", customer_id="A", load_multiplier=0, status="pending"))
        self.assertEqual(self.state()["customer_events"], [])

    def test_partial_day_hourly_delivery(self):
        self.ledger.record_event(event(start="2026-10-15T07:00:00+08:00", end="2026-10-15T09:00:00+08:00"))
        self.assertEqual(self.state()["holdings_mwh"], [0.0] * 7 + [2.0, 2.0] + [0.0] * 15)

    def test_naive_time_and_partial_hour_rejected(self):
        for changes in ({"available_time": "2026-10-14T09:00:00"},
                        {"start": "2026-10-15T00:15:00+08:00"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.ledger.record_event(event(**changes))

    def test_invalid_numeric_values_rejected(self):
        for value in (True, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.ledger.record_event(event(hourly_mwh=value))

    def test_overflowing_trade_cost_rejected_before_insertion(self):
        with self.assertRaises(ValidationError):
            self.ledger.record_event(event(hourly_mwh=1e300, price_cny_per_mwh=1e300))
        self.assertEqual(self.state()["event_refs"], [])

    def test_invalid_revision_domain(self):
        for value in (True, 0, -1, 1.5, 2 ** 64):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.ledger.record_event(event(revision=value))

    def test_out_of_order_arrival_and_time_order_validation(self):
        self.ledger.record_event(event(revision=2, hourly_mwh=3, available_time="2026-10-14T10:00:00+08:00"))
        self.ledger.record_event(event())
        self.assertEqual(sum(self.state()["holdings_mwh"]), 72)
        with self.assertRaises(ValidationError):
            self.ledger.record_event(event(revision=3))

    def test_restart_preserves_trade_and_completed_result(self):
        self.ledger.record_event(event())
        generation = self.ledger.start_run("T", "input-a")
        self.ledger.finish_run("T", generation, "input-a", {"value": 12})
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.assertEqual(sum(self.state()["holdings_mwh"]), 48)
        self.assertEqual(self.ledger.get_run("T")["result"], {"value": 12})

    def test_stale_worker_and_input_hash_rejected(self):
        first = self.ledger.start_run("T", "input-a")
        second = self.ledger.start_run("T", "input-b")
        with self.assertRaises(ValidationError):
            self.ledger.finish_run("T", first, "input-a", {})
        with self.assertRaises(ValidationError):
            self.ledger.finish_run("T", second, "input-a", {})
        self.ledger.finish_run("T", second, "input-b", {})

    def test_completed_result_is_immutable_and_retry_idempotent(self):
        generation = self.ledger.start_run("T", "input-a")
        self.assertTrue(self.ledger.finish_run("T", generation, "input-a", {"value": 1}))
        self.assertFalse(self.ledger.finish_run("T", generation, "input-a", {"value": 1}))
        with self.assertRaises(ValidationError):
            self.ledger.finish_run("T", generation, "input-a", {"value": 2})

    def test_selection_binds_completed_current_plan(self):
        first = self.ledger.start_run("T", "input-a")
        with self.assertRaises(ValidationError):
            self.ledger.select_plan("T", first, "A", "hash-a")
        self.ledger.finish_run("T", first, "input-a", {"plans": [{"plan_id": "A", "plan_hash": "hash-a"}]})
        with self.assertRaises(ValidationError):
            self.ledger.select_plan("T", first, "A", "wrong-hash")
        self.ledger.select_plan("T", first, "A", "hash-a")
        self.assertEqual(self.ledger.get_run("T")["selection"]["generation"], first)
        second = self.ledger.start_run("T", "input-b")
        self.assertIsNone(self.ledger.get_run("T")["selection"])
        with self.assertRaises(ValidationError):
            self.ledger.select_plan("T", first, "A", "hash-a")
        self.assertGreater(second, first)

    def test_cancellation_survives_restart_and_rejects_finish(self):
        generation = self.ledger.start_run("T", "input-a")
        self.ledger.cancel_run("T")
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.assertEqual(self.ledger.get_run("T")["status"], "cancelled")
        with self.assertRaises(ValidationError):
            self.ledger.start_run("T", "input-b")
        with self.assertRaises(ValidationError):
            self.ledger.finish_run("T", generation, "input-a", {})


if __name__ == "__main__":
    unittest.main()
