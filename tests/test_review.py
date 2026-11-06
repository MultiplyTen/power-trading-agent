"""Independent decision/review checks: hand-calculated costs and time boundaries."""
import calendar
import copy
import unittest
from datetime import datetime, timedelta

from power_trading_agent.contracts import SHANGHAI, ValidationError, digest
from power_trading_agent.risk import assess_risk, default_profiles
from power_trading_agent.review import (record_decision, record_historical_decision,
                                        register_experiment, review_decision)


def context(period_type="day"):
    first = datetime(2026, 10, 2, tzinfo=SHANGHAI) if period_type == "day" else datetime(2026, 2, 1, tzinfo=SHANGHAI)
    count = 24 if period_type == "day" else calendar.monthrange(first.year, first.month)[1] * 24
    origin = first - timedelta(hours=12)
    rule = {"rule_id": "review-hand-example", "scope": "synthetic", "price_basis": "user_side",
            "currency": "CNY", "deviation_fee_cny_per_mwh": 3,
            "source": "invented arithmetic fixture", "valid_from": "2026-01-01", "valid_to": "2026-12-31"}
    return {"schema_version": "risk-review-1", "scope": "synthetic", "portfolio_id": "review-portfolio",
            "period_type": period_type, "period": first.strftime("%Y-%m-%d" if period_type == "day" else "%Y-%m"),
            "origin": origin.isoformat(), "hours": [(first + timedelta(hours=h)).isoformat() for h in range(count)],
            "f": [10.0] + [0.0] * (count - 1), "da": [100.0] + [0.0] * (count - 1),
            "rt": [200.0] + [0.0] * (count - 1), "holdings": [0.0] * count, "holding_cost": [0.0] * count,
            "rule": rule, "input_snapshot_id": "a" * 64, "portfolio_state_id": "b" * 64,
            "evidence": [{"id": "known-input", "available_time": origin.isoformat(), "source_hash": "c" * 64}]}


def profiles():
    result = default_profiles()
    for profile in result:
        profile["limits"] = {key: 1e9 for key in profile["limits"]}
        profile["limits"]["max_abs_k_deviation"] = 0.2
    return result


def observations(ctx, load=12.0, da=100.0, rt=50.0):
    n = len(ctx["hours"])
    end = datetime.fromisoformat(ctx["hours"][-1]) + timedelta(hours=7)
    return {"hours": list(ctx["hours"]), "l": [load] + [0.0] * (n - 1),
            "da": [da] + [0.0] * (n - 1), "rt": [rt] + [0.0] * (n - 1),
            "price_basis": "user_side", "energy_unit": "MWh", "price_unit": "CNY/MWh",
            "available_time": end.isoformat(), "source": "synthetic realized labels"}


def plan_named(report, name):
    return next(plan for plan in report["plans"] if plan["name"] == name)


def decision(report, name="baseline", profile_id="steady"):
    selected = datetime.fromisoformat(report["context"]["origin"]) + timedelta(hours=1)
    return record_decision(report, profile_id, plan_named(report, name)["plan_id"],
                           "demo-operator", "Explicit research comparison", selected.isoformat())


def historical(report, name="baseline", profile_id="steady"):
    selected = datetime.fromisoformat(report["context"]["origin"]) + timedelta(hours=1)
    evidence = {"source": "invented historical record", "reference": "audit-001",
                "available_time": (selected + timedelta(hours=1)).isoformat()}
    return record_historical_decision(report, profile_id, plan_named(report, name)["plan_id"],
                                      "historical-operator", "Review a declared past action", selected.isoformat(), evidence)


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = context()
        cls.report = assess_risk(cls.ctx, profiles())
        cls.choice = decision(cls.report)
        cls.actuals = observations(cls.ctx)
        cls.review = review_decision(cls.report, cls.choice, cls.actuals)

    def test_explicit_choice_has_hash_actor_reason_and_period(self):
        self.assertEqual(self.choice["actor"], "demo-operator")
        self.assertEqual(self.choice["period"], "2026-10-02")
        self.assertEqual(self.choice["admissibility_status"], "eligible")
        self.assertEqual(self.choice["decision_hash"], digest({k: v for k, v in self.choice.items() if k != "decision_hash"}))

    def test_review_decision_context_is_bound_to_frozen_choice_and_inputs(self):
        expected = {"origin": self.ctx["origin"], "selected_at": self.choice["selected_at"],
                    "profile_id": self.choice["profile_id"], "actor": self.choice["actor"],
                    "reason": self.choice["reason"], "input_snapshot_id": self.ctx["input_snapshot_id"],
                    "portfolio_state_id": self.ctx["portfolio_state_id"], "report_id": self.report["report_id"]}
        self.assertEqual(self.review["decision_context"], expected)
        changed_actuals = observations(self.ctx, 8, 300, 900)
        changed_actuals["actor"] = "not-the-decision-maker"
        changed_actuals["reason"] = "not-known-before-the-outcome"
        reviewed = review_decision(self.report, self.choice, changed_actuals)
        self.assertEqual(reviewed["decision_context"], expected)

    def test_choice_requires_actor_and_reason(self):
        base = plan_named(self.report, "baseline")["plan_id"]
        for actor, reason in (("", "reason"), ("operator", "   ")):
            with self.subTest(actor=actor, reason=reason), self.assertRaises(ValidationError):
                record_decision(self.report, "steady", base, actor, reason, self.choice["selected_at"])

    def test_choice_must_be_inside_original_information_window(self):
        base = plan_named(self.report, "baseline")["plan_id"]
        for selected in ("2026-10-01T11:59:59+08:00", "2026-10-02T00:00:00+08:00"):
            with self.subTest(selected=selected), self.assertRaises(ValidationError):
                record_decision(self.report, "steady", base, "operator", "reason", selected)

    def test_unknown_profile_or_plan_cannot_be_selected(self):
        for profile_id, plan_id in (("unknown", self.choice["plan_id"]), ("steady", "future-perfect-plan")):
            with self.subTest(profile=profile_id), self.assertRaises(ValidationError):
                record_decision(self.report, profile_id, plan_id, "operator", "reason", self.choice["selected_at"])

    def test_missing_limits_block_new_choice_but_allow_explicit_historical_import(self):
        report = assess_risk(self.ctx)
        with self.assertRaises(ValidationError):
            decision(report)
        imported = historical(report)
        reviewed = review_decision(report, imported, self.actuals)
        self.assertEqual(imported["record_type"], "historical_observation_not_authorization")
        self.assertEqual(imported["admissibility_status"], "needs_limits")
        self.assertIsNone(reviewed["hindsight_best"])
        self.assertEqual(reviewed["hindsight_status"], "unavailable_no_frozen_admissible_candidates")
        self.assertTrue(all(value is None for value in reviewed["ex_ante_references"].values()))
        self.assertIn("historical_admissibility", [lesson["topic"] for lesson in reviewed["lessons"]])

    def test_breached_new_choice_rejected_and_historical_violation_remains_visible(self):
        limits = profiles()
        limits[0]["limits"]["max_abs_k_deviation"] = 0.0
        report = assess_risk(self.ctx, limits)
        with self.assertRaises(ValidationError):
            decision(report, "spread_rule", "conservative")
        imported = historical(report, "spread_rule", "conservative")
        reviewed = review_decision(report, imported, self.actuals)
        self.assertEqual(imported["admissibility_status"], "breached")
        self.assertTrue(imported["violations"])
        self.assertEqual(reviewed["process_integrity"]["choice_admissibility"], "breached")
        self.assertFalse(reviewed["hindsight_best"]["chosen_in_comparison_set"])
        self.assertEqual(reviewed["hindsight_best"]["gap_interpretation"], "outside_set_cost_comparison_not_regret")

    def test_historical_evidence_requires_source_reference_and_valid_time(self):
        base = plan_named(self.report, "baseline")["plan_id"]
        cases = [{}, {"source": "x", "reference": "r", "available_time": "2026-10-01T12:00:00+08:00"}]
        for evidence in cases:
            with self.subTest(evidence=evidence), self.assertRaises(ValidationError):
                record_historical_decision(self.report, "steady", base, "operator", "reason",
                                           self.choice["selected_at"], evidence)

    def test_known_only_reference_plan_ids_do_not_change_with_actual_labels(self):
        other = review_decision(self.report, self.choice, observations(self.ctx, 8, 300, 900))
        first_ids = {name: item["plan_id"] for name, item in self.review["ex_ante_references"].items()}
        second_ids = {name: item["plan_id"] for name, item in other["ex_ante_references"].items()}
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(self.review["report_hash"], other["report_hash"])
        self.assertNotEqual(self.review["actuals_hash"], other["actuals_hash"])

    def test_hindsight_is_best_frozen_admissible_candidate_by_hand(self):
        # One nonzero hour: baseline=10*100+2*50+2*3=1106.
        # Lowest bounded Q=8: 8*100+4*50+4*3=1012, gap=94.
        self.assertAlmostEqual(self.review["chosen_outcome"]["cost_cny"], 1106)
        self.assertAlmostEqual(self.review["hindsight_best"]["cost_cny"], 1012)
        self.assertAlmostEqual(self.review["hindsight_best"]["gap_to_chosen_cny"], 94)
        admitted = next(p for p in self.report["profile_results"] if p["profile_id"] == "steady")["admissible_plan_ids"]
        self.assertIn(self.review["hindsight_best"]["plan_id"], admitted)
        self.assertTrue(self.review["hindsight_best"]["not_an_achievable_policy_target"])

    def test_hindsight_cannot_use_another_profiles_more_aggressive_plan(self):
        limits = profiles()
        limits[0]["limits"]["max_abs_k_deviation"] = 0.0
        report = assess_risk(self.ctx, limits)
        choice = decision(report, "baseline", "conservative")
        reviewed = review_decision(report, choice, self.actuals)
        self.assertEqual(reviewed["hindsight_best"]["plan_id"], choice["plan_id"])
        self.assertAlmostEqual(reviewed["hindsight_best"]["gap_to_chosen_cny"], 0)

    def test_actual_execution_is_not_assumed_from_human_choice(self):
        self.assertEqual(self.review["execution_status"], "not_provided")
        self.assertIsNone(self.review["execution_outcome"])
        self.assertEqual(len(self.review["cost_bridge"]["steps"]), 3)

    def test_execution_outside_candidate_set_does_not_enter_oracle(self):
        # Q=0 costs 12*50+12*3=636, below the bounded candidate oracle.
        # This out-of-set execution does not make hindsight regret negative.
        execution = {"hours": list(self.ctx["hours"]), "energy_unit": "MWh", "q": [0.0] * 24,
                     "source": "declared execution", "available_time": "2026-10-02T01:00:00+08:00"}
        reviewed = review_decision(self.report, self.choice, self.actuals, execution)
        self.assertAlmostEqual(reviewed["execution_outcome"]["cost_cny"], 636)
        self.assertAlmostEqual(reviewed["hindsight_best"]["cost_cny"], 1012)
        self.assertAlmostEqual(reviewed["hindsight_best"]["gap_to_chosen_cny"], 94)
        self.assertTrue(reviewed["execution_checks"]["action_bound_breached"])
        self.assertEqual(reviewed["execution_status"], "provided_unverified")

    def test_fixed_order_cost_bridge_reconciles_hand_calculations(self):
        actuals = observations(self.ctx, 12, 300, 500)
        execution = {"hours": list(self.ctx["hours"]), "energy_unit": "MWh", "q": [11.0] + [0.0] * 23,
                     "source": "synthetic execution",
                     "available_time": "2026-10-02T01:00:00+08:00"}
        reviewed = review_decision(self.report, self.choice, actuals, execution)
        bridge = reviewed["cost_bridge"]
        # Forecast:1000; actual L:1406; actual DA:3406; actual RT:4006; executed Q:3803.
        self.assertEqual([s["delta_cost_cny"] for s in bridge["steps"]], [406, 2000, 600, -203])
        self.assertEqual(bridge["forecast_cost_cny"], 1000)
        self.assertEqual(bridge["terminal_cost_cny"], 3803)
        self.assertEqual(bridge["total_change_cny"], 2803)
        self.assertAlmostEqual(bridge["reconciliation_error_cny"], 0)
        self.assertIn("not_independent_or_causal", bridge["interpretation"])

    def test_forecast_diagnostics_are_actual_minus_forecast(self):
        self.assertAlmostEqual(self.review["forecast_diagnostics"]["load_total_error_mwh"], 2)
        self.assertAlmostEqual(self.review["forecast_diagnostics"]["load_mae_mwh"], 2 / 24)
        self.assertEqual(self.review["forecast_diagnostics"]["error_convention"], "actual_minus_forecast")

    def test_scenario_coverage_is_explicitly_marginal(self):
        reviewed = review_decision(self.report, self.choice, observations(self.ctx, 500, 100000, -100000))
        coverage = reviewed["scenario_coverage"]
        self.assertTrue(coverage["has_uncovered_observation"])
        self.assertEqual(coverage["variables"]["da"]["outside_count"], 1)
        self.assertEqual(coverage["variables"]["load"]["outside_count"], 1)
        self.assertIn("not_joint_or_probability", coverage["interpretation"])
        self.assertTrue(all(not item["automatic_promotion"] for item in reviewed["lessons"]))

    def test_future_candidates_cannot_be_injected_by_rehashing_report(self):
        altered = copy.deepcopy(self.report)
        altered["plans"][0]["q"][0] = 0
        plan = altered["plans"][0]
        plan["plan_hash"] = digest({k: v for k, v in plan.items() if k != "plan_hash"})
        altered["report_hash"] = digest({k: v for k, v in altered.items() if k != "report_hash"})
        with self.assertRaises(ValidationError):
            review_decision(altered, self.choice, self.actuals)

    def test_decision_tampering_and_wrong_report_binding_are_rejected(self):
        choice = copy.deepcopy(self.choice)
        choice["reason"] = "changed after the fact"
        with self.assertRaises(ValidationError):
            review_decision(self.report, choice, self.actuals)
        choice["decision_hash"] = digest({k: v for k, v in choice.items() if k != "decision_hash"})
        with self.assertRaises(ValidationError):
            review_decision(self.report, choice, self.actuals)

    def test_actual_hours_units_source_scope_and_availability_are_required(self):
        patches = [{"hours": self.actuals["hours"][:-1]}, {"energy_unit": "MW"},
                   {"price_basis": "node"}, {"source": ""}, {"portfolio_id": "other"},
                   {"available_time": "2026-10-02T23:59:59+08:00"}, {"rt": [float("nan")] * 24}]
        for changes in patches:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                review_decision(self.report, self.choice, dict(self.actuals, **changes))

    def test_execution_requires_scope_complete_curve_and_post_choice_evidence(self):
        initial = {"hours": list(self.ctx["hours"]), "energy_unit": "MWh", "q": [10.0] + [0.0] * 23,
                   "source": "receipt", "available_time": "2026-10-02T01:00:00+08:00"}
        for changes in ({"q": [1]}, {"source": ""}, {"available_time": "2026-10-01T12:00:00+08:00"}, {"portfolio_id": "other"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                review_decision(self.report, self.choice, self.actuals, dict(initial, **changes))

    def test_execution_hours_reject_other_day_wrong_order_and_missing(self):
        initial = {"energy_unit": "MWh", "q": [10.0] + [0.0] * 23, "source": "receipt",
                   "available_time": "2026-10-02T01:00:00+08:00"}
        other_day = [(datetime.fromisoformat(hour) + timedelta(days=1)).isoformat()
                     for hour in self.ctx["hours"]]
        cases = {"other_day": dict(initial, hours=other_day),
                 "wrong_order": dict(initial, hours=list(reversed(self.ctx["hours"]))),
                 "missing": initial}
        for name, execution in cases.items():
            with self.subTest(case=name), self.assertRaises(ValidationError) as raised:
                review_decision(self.report, self.choice, self.actuals, execution)
            self.assertEqual(raised.exception.code, "EXECUTION_HOURS")

    def test_execution_energy_unit_rejects_kw_kwh_and_missing(self):
        initial = {"hours": list(self.ctx["hours"]), "q": [10.0] + [0.0] * 23,
                   "source": "receipt", "available_time": "2026-10-02T01:00:00+08:00"}
        cases = {"power_unit": dict(initial, energy_unit="MW"),
                 "wrong_energy_unit": dict(initial, energy_unit="kWh"), "missing": initial}
        for name, execution in cases.items():
            with self.subTest(case=name), self.assertRaises(ValidationError) as raised:
                review_decision(self.report, self.choice, self.actuals, execution)
            self.assertEqual(raised.exception.code, "EXECUTION_UNIT")

    def proposal(self):
        return {"hypothesis": "An available weather feature reduces prospective costs",
                "change": "Candidate model version b", "registered_at": "2026-10-03T07:00:00+08:00",
                "test_start": "2026-10-04", "test_end": "2026-10-11",
                "metric": "incremental procurement cost", "baseline": "frozen policy a",
                "acceptance": {"max_cost_increase_cny": 0}, "frozen_candidate_hash": "d" * 64}

    def test_future_experiment_is_registered_without_automatic_promotion(self):
        result = register_experiment(self.proposal(), [self.review])
        self.assertEqual(result["status"], "proposed_not_validated")
        self.assertEqual(result["test_start"], "2026-10-04T00:00:00+08:00")
        self.assertFalse(result["automatic_promotion"])
        self.assertEqual(result["review_hashes"], [self.review["review_hash"]])

    def test_experiment_registration_cannot_be_backdated_before_review_information(self):
        proposal = self.proposal()
        proposal["registered_at"] = "2026-10-03T05:59:59+08:00"
        with self.assertRaises(ValidationError):
            register_experiment(proposal, [self.review])

    def test_experiment_test_period_must_be_after_review_and_registration(self):
        for start in ("2026-10-02", "2026-10-03T07:00:00+08:00"):
            proposal = dict(self.proposal(), test_start=start)
            with self.subTest(start=start), self.assertRaises(ValidationError):
                register_experiment(proposal, [self.review])

    def test_experiment_uses_latest_execution_evidence(self):
        execution = {"hours": list(self.ctx["hours"]), "energy_unit": "MWh",
                     "q": list(plan_named(self.report, "baseline")["q"]),
                     "source": "late execution record",
                     "available_time": "2026-10-05T06:00:00+08:00"}
        reviewed = review_decision(self.report, self.choice, self.actuals, execution)
        with self.assertRaises(ValidationError):
            register_experiment(self.proposal(), [reviewed])

    def test_experiment_uses_latest_historical_choice_evidence(self):
        selected = self.choice["selected_at"]
        choice = record_historical_decision(self.report, "steady", self.choice["plan_id"], "operator", "reason", selected,
            {"source": "late archived record", "reference": "r1", "available_time": "2026-10-06T06:00:00+08:00"})
        reviewed = review_decision(self.report, choice, self.actuals)
        with self.assertRaises(ValidationError):
            register_experiment(self.proposal(), [reviewed])

    def test_experiment_rejects_unsealed_or_duplicate_review_and_missing_criteria(self):
        changed = copy.deepcopy(self.review)
        changed["actuals_available_time"] = "2026-10-01T00:00:00+08:00"
        for reviews in ([changed], [self.review, self.review], []):
            with self.subTest(count=len(reviews)), self.assertRaises(ValidationError):
                register_experiment(self.proposal(), reviews)
        with self.assertRaises(ValidationError):
            register_experiment(dict(self.proposal(), acceptance={}), [self.review])

    def test_review_does_not_mutate_frozen_input_or_actuals(self):
        before = digest([self.report, self.choice, self.actuals])
        review_decision(self.report, self.choice, self.actuals)
        self.assertEqual(digest([self.report, self.choice, self.actuals]), before)

    def test_calendar_month_uses_one_origin_and_complete_monthly_actuals(self):
        ctx = context("month")
        report = assess_risk(ctx, profiles())
        choice = decision(report)
        actual = observations(ctx)
        reviewed = review_decision(report, choice, actual)
        self.assertEqual(reviewed["period_type"], "month")
        self.assertEqual(reviewed["period"], "2026-02")
        self.assertEqual(reviewed["forecast_diagnostics"]["hours"], 28 * 24)
        self.assertEqual(reviewed["delivery_end"], "2026-03-01T00:00:00+08:00")
        self.assertAlmostEqual(reviewed["chosen_outcome"]["cost_cny"], 1106)
        with self.assertRaises(ValidationError):
            review_decision(report, choice, dict(actual, hours=actual["hours"][:24]))


if __name__ == "__main__":
    unittest.main()
