"""Hand-computed financial identities and adverse-input cases, no live rules."""

import copy
import unittest

from power_trading_agent.contracts import ValidationError
from power_trading_agent.economics import evaluate_plans, make_plans, replay_metrics, settlement


def constant(value):
    return [value] * 24


def rule(fee=0):
    return {"rule_id": "synthetic-test-v1", "scope": "synthetic",
            "price_basis": "user_side", "currency": "CNY", "deviation_fee_cny_per_mwh": fee}


def config():
    return {"k_min": 0.8, "k_max": 1.2, "adjustment": 0.1, "spread_threshold": 0}


def scenario(kind="stress"):
    item = {"scenario_id": "one", "l": constant(10), "da": constant(100), "rt": constant(200)}
    if kind == "probabilistic":
        item["weight"] = 1
    return {"scenario_set_id": "test", "kind": kind,
            "calibration_status": "validated" if kind == "probabilistic" else "not_applicable",
            "items": [item]}


class EconomicsTests(unittest.TestCase):
    def plans(self):
        return make_plans(constant(10), constant(100), constant(200), config())

    def evaluate(self, scenarios=None, budget=None, plans=None):
        return evaluate_plans(plans or self.plans(), scenarios or scenario(),
                              constant(0), constant(0), rule(), budget)

    def test_physical_forward_is_not_double_counted(self):
        # Each hour: 6*80 + (10-6)*100 + (9-10)*200 = 680 CNY.
        result = settlement(constant(10), constant(9), constant(100), constant(200),
                            constant(6), constant(480), rule())
        self.assertEqual(result["total_cost_cny"], 16320)
        self.assertEqual(result["hourly_cost_cny"], constant(680))

    def test_fee_is_on_absolute_energy_deviation(self):
        # Above physical cost plus abs(10-9)*10 = 690 CNY/hour.
        result = settlement(constant(10), constant(9), constant(100), constant(200),
                            constant(6), constant(480), rule(10))
        self.assertEqual(result["fee_cny"], 240)
        self.assertEqual(result["energy_cost_cny"], 16320)
        self.assertEqual(result["total_cost_cny"], 16560)

    def test_f_l_q_are_distinct(self):
        # Q=11,L=10, DA100,RT200 => 900/hour; Q=10 costs1000/hour.
        result = self.evaluate()
        self.assertAlmostEqual(result["plans"][1]["scenario_results"][0]["incremental_gain_cny"], 2400)
        self.assertAlmostEqual(result["plans"][1]["scenario_results"][0]["total_cost_cny"], 21600)

    def test_negative_prices_are_valid(self):
        result = settlement(constant(10), constant(10), constant(-20), constant(-50),
                            constant(0), constant(0), rule())
        self.assertEqual(result["total_cost_cny"], -4800)

    def test_half_adjustment_and_clip(self):
        settings = config()
        settings["adjustment"] = 0.6
        plans = make_plans(constant(2), constant(100), constant(200), settings)
        self.assertEqual(plans[0]["k"], constant(1))
        self.assertEqual(plans[1]["k"], constant(1.2))
        self.assertEqual(plans[2]["k"], constant(1.2))
        self.assertEqual(plans[1]["q"], constant(2.4))
        normal = self.plans()
        self.assertEqual(normal[2]["k"], constant(1.05))

    def test_negative_spread_lowers_coefficient(self):
        plans = make_plans(constant(10), constant(200), constant(100), config())
        self.assertEqual(plans[1]["q"], constant(9))

    def test_threshold_boundary_keeps_baseline(self):
        settings = config()
        settings["spread_threshold"] = 100
        plans = make_plans(constant(10), constant(100), constant(200), settings)
        self.assertEqual(plans[1]["k"], constant(1))

    def test_zero_forecast_does_not_create_energy(self):
        plans = make_plans(constant(0), constant(100), constant(200), config())
        self.assertEqual(plans[1]["q"], constant(0))

    def test_baseline_must_fit_configured_bounds(self):
        settings = config()
        settings["k_max"] = 0.95
        with self.assertRaises(ValidationError):
            make_plans(constant(10), constant(100), constant(200), settings)

    def test_unknown_live_rule_is_rejected(self):
        live_rule = rule()
        live_rule["scope"] = "guangdong_live"
        with self.assertRaises(ValidationError):
            settlement(constant(10), constant(10), constant(100), constant(200),
                       constant(0), constant(0), live_rule)

    def test_wrong_currency_and_price_basis_are_rejected(self):
        for key, value in (("currency", "USD"), ("price_basis", "nodal")):
            with self.subTest(key=key):
                invalid = rule()
                invalid[key] = value
                with self.assertRaises(ValidationError):
                    settlement(constant(10), constant(10), constant(100), constant(200),
                               constant(0), constant(0), invalid)

    def test_nan_negative_energy_and_incomplete_curve_are_rejected(self):
        for q in (constant(float("nan")), constant(-1), [10] * 23, constant(True)):
            with self.subTest(q=q[:1]):
                with self.assertRaises(ValidationError):
                    settlement(q, constant(10), constant(100), constant(200),
                               constant(0), constant(0), rule())

    def test_stress_has_no_probability_metrics(self):
        result = self.evaluate()
        for plan in result["plans"]:
            self.assertEqual(plan["risk_status"], "needs_risk_budget")
            for field in ("expected_cost_cny", "expected_incremental_gain_cny", "loss_probability", "cvar90_loss_cny"):
                self.assertNotIn(field, plan)

    def test_stress_cannot_be_given_probability_weights(self):
        scenarios = scenario()
        scenarios["items"][0]["weight"] = 1
        with self.assertRaises(ValidationError):
            self.evaluate(scenarios)

    def test_uncalibrated_probability_is_rejected(self):
        scenarios = scenario("probabilistic")
        scenarios["calibration_status"] = "not_validated"
        with self.assertRaises(ValidationError):
            self.evaluate(scenarios)

    def test_probability_weights_are_not_silently_normalized(self):
        for bad_weight in (0.9, -1, True):
            scenarios = scenario("probabilistic")
            scenarios["items"][0]["weight"] = bad_weight
            with self.assertRaises(ValidationError):
                self.evaluate(scenarios)

    def test_duplicate_scenarios_are_rejected(self):
        scenarios = scenario()
        scenarios["items"].append(copy.deepcopy(scenarios["items"][0]))
        with self.assertRaises(ValidationError):
            self.evaluate(scenarios)

    def test_mixed_forecast_candidates_are_rejected(self):
        plans = self.plans()
        plans[1]["q"][0] += 1
        with self.assertRaises(ValidationError):
            self.evaluate(plans=plans)

    def test_invalid_baseline_and_duplicate_plan_are_rejected(self):
        missing = self.plans()[1:]
        duplicate = self.plans() + [self.plans()[0]]
        for plans in (missing, duplicate):
            with self.assertRaises(ValidationError):
                self.evaluate(plans=plans)

    def test_cvar_uses_fractional_tail_mass(self):
        # Candidate buys 1 extra MWh only in hour 0. Losses: 100,20,0.
        # Worst 10% = (5%*100 + 5%*20)/10% = 60, not a 2-row average.
        f = [10] + [0] * 23
        plans = make_plans(f, constant(100), constant(200), config())
        items = []
        for loss, weight in ((100, 0.05), (20, 0.10), (0, 0.85)):
            items.append({"scenario_id": str(loss), "l": f,
                          "da": constant(100), "rt": [100 - loss] + [100] * 23,
                          "weight": weight})
        scenarios = {"kind": "probabilistic", "scenario_set_id": "tail",
                     "calibration_status": "validated", "items": items}
        result = self.evaluate(scenarios, 60, plans)["plans"][1]
        self.assertAlmostEqual(result["cvar90_loss_cny"], 60)
        self.assertAlmostEqual(result["expected_incremental_gain_cny"], -7)
        self.assertAlmostEqual(result["loss_probability"], 0.15)
        self.assertEqual(result["worst_loss_cny"], 100)
        self.assertEqual(result["risk_status"], "within_budget")
        lower = self.evaluate(scenarios, 59, plans)["plans"][1]
        self.assertEqual(lower["risk_status"], "exceeds_budget")

    def test_entire_profitable_tail_keeps_signed_cvar(self):
        result = self.evaluate(scenario("probabilistic"), 0)["plans"][1]
        self.assertAlmostEqual(result["cvar90_loss_cny"], -2400)
        self.assertEqual(result["loss_probability"], 0)
        self.assertEqual(result["worst_loss_cny"], 0)

    def test_stress_budget_uses_worst_supplied_day(self):
        scenarios = scenario()
        scenarios["items"][0]["rt"] = constant(0)
        result = self.evaluate(scenarios, 2399)["plans"][1]
        self.assertAlmostEqual(result["worst_loss_cny"], 2400)
        self.assertEqual(result["risk_status"], "exceeds_budget")

    def test_zero_budget_is_not_missing(self):
        result = self.evaluate(budget=0)
        self.assertEqual(result["plans"][0]["risk_status"], "within_budget")
        with self.assertRaises(ValidationError):
            self.evaluate(budget=-1)

    def test_replay_drawdown_groups_and_frequency(self):
        # Gain path 10,-30,5,20: cumulative10,-20,-15,5; peak10 => drawdown30.
        rows = [{"date": "2026-01-0" + str(i + 1), "group": group,
                 "baseline_cost_cny": 100, "candidate_cost_cny": 100 - gain}
                for i, (gain, group) in enumerate(((10, "normal"), (-30, "hot"), (5, "normal"), (20, "hot")))]
        result = replay_metrics(rows)
        self.assertEqual(result["days"], 4)
        self.assertEqual(result["total_incremental_gain_cny"], 5)
        self.assertEqual(result["max_drawdown_cny"], 30)
        self.assertEqual(result["worst_day_gain_cny"], -30)
        self.assertEqual(result["loss_day_fraction"], 0.25)
        self.assertEqual(result["groups"]["normal"]["days"], 2)
        self.assertEqual(result["groups"]["normal"]["total_incremental_gain_cny"], 15)
        self.assertEqual(result["groups"]["hot"]["max_drawdown_cny"], 30)

    def test_initial_loss_counts_as_drawdown(self):
        result = replay_metrics([{"date": "2026-01-01", "group": "cold",
                                  "baseline_cost_cny": 100, "candidate_cost_cny": 140}])
        self.assertEqual(result["max_drawdown_cny"], 40)

    def test_replay_requires_real_dates_in_strict_order(self):
        row = {"date": "2026-01-02", "group": "normal", "baseline_cost_cny": 100, "candidate_cost_cny": 90}
        for rows in ([], [row, row], [row, dict(row, date="2026-01-01")], [dict(row, date="2026-02-30")]):
            with self.assertRaises(ValidationError):
                replay_metrics(rows)

    def test_inputs_are_not_mutated(self):
        scenarios = scenario("probabilistic")
        plans = self.plans()
        before = copy.deepcopy((scenarios, plans))
        self.evaluate(scenarios, plans=plans)
        self.assertEqual((scenarios, plans), before)


if __name__ == "__main__":
    unittest.main()
