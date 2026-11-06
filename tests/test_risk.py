"""Independent arithmetic and information-boundary checks for multidimensional risk."""
import calendar
import copy
import unittest
from datetime import date, datetime, timedelta

from power_trading_agent.contracts import SHANGHAI, ValidationError, digest
from power_trading_agent.risk import (
    LIMIT_DIMENSIONS, assess_risk, build_candidates, build_stress_scenarios,
    default_profiles, period_cost, validate_context, verify_risk_report,
)


def context(period_type="day", period="2026-02-01"):
    first = date.fromisoformat(period if period_type == "day" else period + "-01")
    n = 24 if period_type == "day" else calendar.monthrange(first.year, first.month)[1] * 24
    start = datetime(first.year, first.month, first.day, tzinfo=SHANGHAI)
    origin = (start - timedelta(hours=12)).isoformat()
    return {"schema_version": "risk-review-1", "scope": "synthetic", "portfolio_id": "test-portfolio",
            "period_type": period_type, "period": period, "origin": origin,
            "hours": [(start + timedelta(hours=h)).isoformat() for h in range(n)],
            "f": [10.0] * n, "da": [300.0] * n, "rt": [500.0] * n,
            "holdings": [4.0] * n, "holding_cost": [1120.0] * n,
            "rule": {"rule_id": "independent-synthetic-fixture", "scope": "synthetic",
                     "price_basis": "user_side", "currency": "CNY", "deviation_fee_cny_per_mwh": 3.0,
                     "valid_from": "2020-01-01", "valid_to": "2030-12-31", "source": "invented arithmetic fixture"},
            "input_snapshot_id": digest("test-input"), "portfolio_state_id": digest("test-state"),
            "evidence": [{"id": "forecast-source", "available_time": origin, "source_hash": digest("forecast-source")}]}


def generous_profiles():
    profiles = default_profiles()
    for p in profiles:
        p["limits"] = {key: 1e12 for key in LIMIT_DIMENSIONS}
    return profiles


def named_plan(report, name):
    return next(p for p in report["plans"] if p["name"] == name)


def check_for(report, profile_id, plan_id):
    group = next(p for p in report["profile_results"] if p["profile_id"] == profile_id)
    return next(p for p in group["checks"] if p["plan_id"] == plan_id)


class RiskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = assess_risk(context(), generous_profiles())

    def test_default_profiles_leave_all_nine_limits_unresolved(self):
        profiles = default_profiles()
        self.assertEqual([p["id"] for p in profiles], ["conservative", "steady", "aggressive"])
        self.assertEqual(len(profiles[0]["limits"]), 9)
        self.assertTrue(all(v is None for p in profiles for v in p["limits"].values()))
        profiles[0]["limits"]["max_incremental_loss_cny"] = 12
        self.assertIsNone(profiles[1]["limits"]["max_incremental_loss_cny"])
        self.assertIsNone(default_profiles()[0]["limits"]["max_incremental_loss_cny"])

    def test_no_limit_means_no_eligible_plan_or_reference(self):
        report = assess_risk(context())
        for group in report["profile_results"]:
            self.assertEqual(group["admissible_plan_ids"], [])
            self.assertTrue(all(c["status"] == "needs_limits" for c in group["checks"]))
            self.assertEqual(group["reference_choices"], {"central_min_cost": None, "minimax_regret": None})

    def test_nine_dimensions_can_independently_block_the_same_candidate(self):
        expected = named_plan(self.report, "constant_k_1.1000")
        for metric in LIMIT_DIMENSIONS:
            with self.subTest(metric=metric):
                self.assertGreater(expected["metrics"][metric], 0)
                profiles = generous_profiles()
                profiles[0]["limits"][metric] = expected["metrics"][metric] * 0.5
                result = assess_risk(context(), profiles)
                check = check_for(result, "conservative", expected["plan_id"])
                self.assertEqual(check["status"], "breached")
                self.assertEqual([v["metric"] for v in check["violations"]], [metric])
                self.assertEqual(check_for(result, "steady", expected["plan_id"])["status"], "eligible")

    def test_equal_measured_limit_is_eligible(self):
        plan = named_plan(self.report, "constant_k_1.1000")
        profiles = generous_profiles()
        profiles[0]["limits"] = dict(plan["metrics"])
        result = assess_risk(context(), profiles)
        self.assertEqual(check_for(result, "conservative", plan["plan_id"])["status"], "eligible")

    def test_missing_one_dimension_still_blocks_reference_choices(self):
        profiles = generous_profiles()
        for p in profiles:
            p["limits"]["max_assessment_fee_cny"] = None
        result = assess_risk(context(), profiles)
        for group in result["profile_results"]:
            self.assertFalse(group["admissible_plan_ids"])
            self.assertEqual(group["checks"][0]["missing_limits"], ["max_assessment_fee_cny"])

    def test_profile_limits_must_be_monotonic_in_each_dimension(self):
        for metric in LIMIT_DIMENSIONS:
            profiles = generous_profiles()
            profiles[0]["limits"][metric] = 20
            profiles[1]["limits"][metric] = 10
            with self.subTest(metric=metric), self.assertRaises(ValidationError):
                assess_risk(context(), profiles)

    def test_zero_limit_is_a_limit_not_a_missing_value(self):
        profiles = generous_profiles()
        for p in profiles:
            p["limits"]["max_incremental_loss_cny"] = 0
            p["limits"]["max_daily_incremental_loss_cny"] = 0
        report = assess_risk(context(), profiles)
        baseline = named_plan(report, "baseline")
        self.assertEqual(check_for(report, "conservative", baseline["plan_id"])["status"], "eligible")
        candidate = named_plan(report, "constant_k_1.1000")
        self.assertEqual(check_for(report, "conservative", candidate["plan_id"])["status"], "breached")

    def test_profile_unknown_metric_duplicate_id_and_nonfinite_limits_rejected(self):
        profiles = generous_profiles()
        profiles[0]["limits"]["max_unknown_risk"] = 1
        with self.assertRaises(ValidationError):
            assess_risk(context(), profiles)
        profiles = generous_profiles()
        profiles[1]["id"] = "conservative"
        with self.assertRaises(ValidationError):
            assess_risk(context(), profiles)
        for invalid in (True, float("inf"), -1):
            profiles = generous_profiles()
            profiles[0]["limits"]["max_assessment_fee_cny"] = invalid
            with self.subTest(value=invalid), self.assertRaises(ValidationError):
                assess_risk(context(), profiles)

    def test_baseline_center_and_multidimensional_metrics_match_hand_calculation(self):
        baseline = named_plan(self.report, "baseline")
        self.assertAlmostEqual(baseline["central_cost_cny"], 24 * (1120 + 6 * 300))
        self.assertAlmostEqual(baseline["metrics"]["max_price_shock_cost_cny"], 24 * 6 * 100)
        self.assertEqual(baseline["metrics"]["max_hourly_deviation_mwh"], 15)
        self.assertEqual(baseline["metrics"]["max_daily_deviation_mwh"], 72)
        self.assertEqual(baseline["metrics"]["max_assessment_fee_cny"], 216)
        self.assertEqual(baseline["metrics"]["max_forecast_unhedged_mwh"], 6)
        self.assertEqual(baseline["metrics"]["max_gross_outflow_cny"], 24 * (1120 + 6 * 400 + 3 * 650 + 9))
        self.assertEqual(baseline["metrics"]["max_incremental_loss_cny"], 0)
        self.assertGreater(baseline["worst_total_cost_cny"], 0)

    def test_price_shock_holds_load_fixed_and_keeps_fee_separate(self):
        plan = named_plan(self.report, "constant_k_1.1000")
        # At Q=11, DA+100 and RT-150 changes fixed-F cost by 7*100+(-1)*(-150) each hour.
        self.assertAlmostEqual(plan["metrics"]["max_price_shock_cost_cny"], 20400)
        self.assertAlmostEqual(plan["central_cost_cny"], 24 * (1120 + 7 * 300 - 500 + 3))
        self.assertAlmostEqual(plan["metrics"]["max_assessment_fee_cny"], 24 * 4 * 3)
        # The spread-reversal scenario has RT=100 and makes Q=11 cost (200+3) more per hour.
        self.assertAlmostEqual(plan["metrics"]["max_incremental_loss_cny"], 4872)
        self.assertAlmostEqual(plan["metrics"]["max_daily_incremental_loss_cny"], 4872)

    def test_structural_position_gap_cannot_be_repaired_by_coefficient_choice(self):
        gaps = {p["metrics"]["max_forecast_unhedged_mwh"] for p in self.report["plans"]}
        self.assertEqual(gaps, {6})
        profiles = generous_profiles()
        profiles[0]["limits"]["max_forecast_unhedged_mwh"] = 5
        result = assess_risk(context(), profiles)
        self.assertFalse(result["profile_results"][0]["admissible_plan_ids"])
        self.assertIn("structural", result["coverage"]["position_metric"])

    def test_crossed_scenarios_cover_both_load_price_directions(self):
        scenarios = self.report["scenarios"]
        self.assertEqual(scenarios["kind"], "stress")
        self.assertEqual(len(scenarios["items"]), 35)
        self.assertEqual(scenarios["items"][0]["scenario_id"], "central")
        triplets = {(s["l"][0], s["da"][0], s["rt"][0]) for s in scenarios["items"]
                    if s["category"] in ("central", "crossed_load_prices")}
        self.assertEqual(len(triplets), 27)
        self.assertIn((13, 400, 350), triplets)
        self.assertIn((7, 200, 650), triplets)
        self.assertTrue(all("weight" not in s for s in scenarios["items"]))
        self.assertFalse(any("expected_cost_cny" in p or "cvar90_loss_cny" in p for p in self.report["plans"]))

    def test_zero_forecast_has_zero_candidates_but_nonzero_unplanned_load_stress(self):
        c = context()
        c["f"] = [0] * 24
        candidates = build_candidates(c)
        self.assertTrue(all(all(q == 0 for q in p["q"]) for p in candidates))
        surge = next(s for s in build_stress_scenarios(c)["items"] if s["scenario_id"] == "load_surge")
        self.assertEqual(surge["l"][17:21], [10] * 4)
        self.assertEqual(surge["l"][0], 0)

    def test_candidates_use_same_forecast_and_declared_coefficient_bounds(self):
        candidates = build_candidates(context())
        self.assertEqual(len(candidates), 11)
        for plan in candidates:
            for k, q in zip(plan["k"], plan["q"]):
                self.assertGreaterEqual(k, 0.8)
                self.assertLessEqual(k, 1.2)
                self.assertAlmostEqual(q, k * 10)
        self.assertEqual(len({p["plan_id"] for p in candidates}), len(candidates))

    def test_reference_rules_use_frozen_risk_only_and_symmetric_regret_prefers_baseline(self):
        c = context()
        c["da"], c["rt"] = [100] * 24, [100] * 24
        c["rule"]["deviation_fee_cny_per_mwh"] = 0
        result = assess_risk(c, generous_profiles())
        # Full-day crossed +/-200 spread dominates narrower hourly shocks. Equal up/down
        # regret is minimized at k=1; all references are calculated before actual labels exist.
        baseline = named_plan(result, "baseline")
        self.assertEqual(result["profile_results"][0]["reference_choices"]["minimax_regret"], baseline["plan_id"])
        self.assertFalse(result["coverage"]["automatic_selection"])
        self.assertFalse(result["coverage"]["overlapping_metrics_are_additive"])
        self.assertFalse(result["coverage"]["business_ready"])

    def test_future_evidence_and_missing_evidence_are_rejected(self):
        c = context()
        c["evidence"][0]["available_time"] = c["hours"][0]
        with self.assertRaises(ValidationError):
            validate_context(c)
        for missing in ([], [{"id": "x", "available_time": c["origin"], "source_hash": ""}]):
            c = context()
            c["evidence"] = missing
            with self.subTest(evidence=missing), self.assertRaises(ValidationError):
                validate_context(c)

    def test_actual_labels_cannot_be_added_to_known_context(self):
        for name in ("actuals", "l", "actual_rt"):
            c = context()
            c[name] = [999] * 24
            with self.subTest(field=name), self.assertRaises(ValidationError):
                validate_context(c)

    def test_full_calendar_month_and_premonth_origin_required(self):
        c = context("month", "2026-02")
        self.assertEqual(len(validate_context(c)["hours"]), 672)
        leap = context("month", "2028-02")
        self.assertEqual(len(validate_context(leap)["hours"]), 696)
        c["origin"] = "2026-02-01T12:00:00+08:00"
        with self.assertRaises(ValidationError):
            validate_context(c)
        c = context("month", "2026-02")
        c["hours"] = c["hours"][:-1]
        with self.assertRaises(ValidationError):
            validate_context(c)

    def test_month_uses_period_fee_cap_but_individual_day_volume_cap(self):
        profiles = generous_profiles()
        profiles[0]["limits"]["max_assessment_fee_cny"] = 500
        profiles[0]["limits"]["max_daily_deviation_mwh"] = 75
        stress = {"load_factors": [1], "da_shifts": [0], "rt_shifts": [0]}
        candidates = {"max_abs_k_deviation": 0}
        daily = assess_risk(context(), profiles, stress, candidates)
        monthly = assess_risk(context("month", "2026-02"), profiles, stress, candidates)
        d, m = named_plan(daily, "baseline"), named_plan(monthly, "baseline")
        self.assertEqual(d["metrics"]["max_assessment_fee_cny"], 180)
        self.assertEqual(m["metrics"]["max_assessment_fee_cny"], 180 * 28)
        self.assertEqual(m["metrics"]["max_daily_deviation_mwh"], 60)
        self.assertEqual(check_for(daily, "conservative", d["plan_id"])["status"], "eligible")
        self.assertEqual([v["metric"] for v in check_for(monthly, "conservative", m["plan_id"])["violations"]],
                         ["max_assessment_fee_cny"])

    def test_rule_period_currency_and_basis_are_enforced(self):
        for key, value in (("valid_to", "2026-01-31"), ("scope", "live"),
                           ("currency", "USD"), ("price_basis", "node"), ("source", "")):
            c = context()
            c["rule"][key] = value
            with self.subTest(field=key), self.assertRaises(ValidationError):
                validate_context(c)

    def test_invalid_curve_and_hour_order_rejected(self):
        c = context()
        c["hours"][0], c["hours"][1] = c["hours"][1], c["hours"][0]
        with self.assertRaises(ValidationError):
            validate_context(c)
        for invalid in (float("nan"), float("inf"), True, -1):
            c = context()
            c["f"][0] = invalid
            with self.subTest(value=invalid), self.assertRaises(ValidationError):
                validate_context(c)

    def test_period_cost_hand_calculation_and_shape_gate(self):
        c = context()
        result = period_cost([10] * 48, [12] * 48, [300] * 48, [500] * 48,
                             [4] * 48, [1120] * 48, c["rule"])
        self.assertEqual(result["total_cost_cny"], 3926 * 48)
        self.assertEqual(result["fee_cny"], 6 * 48)
        self.assertEqual(len(result["hourly_cost_cny"]), 48)
        with self.assertRaises(ValidationError):
            period_cost([10] * 25, [12] * 25, [300] * 25, [500] * 25, [4] * 25, [1120] * 25, c["rule"])

    def test_report_recomputation_rejects_tampering_even_with_updated_hashes(self):
        self.assertTrue(verify_risk_report(self.report)["verified"])
        changed = copy.deepcopy(self.report)
        changed["plans"][0]["metrics"]["max_gross_outflow_cny"] = 1
        changed["plans"][0]["plan_hash"] = digest({k: v for k, v in changed["plans"][0].items() if k != "plan_hash"})
        changed["report_hash"] = digest({k: v for k, v in changed.items() if k != "report_hash"})
        with self.assertRaises(ValidationError) as raised:
            verify_risk_report(changed)
        self.assertEqual(raised.exception.code, "RISK_REPORT_RECOMPUTE")

    def test_report_hash_and_inputs_are_stable(self):
        c, profiles = context(), generous_profiles()
        before = digest({"c": c, "profiles": profiles})
        first = assess_risk(c, profiles)
        second = assess_risk(c, profiles)
        self.assertEqual(first["report_hash"], second["report_hash"])
        self.assertEqual(before, digest({"c": c, "profiles": profiles}))


if __name__ == "__main__":
    unittest.main()
