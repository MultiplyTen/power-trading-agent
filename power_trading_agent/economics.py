"""Deterministic synthetic settlement and strategy evaluation.

This adapter is deliberately NOT a certified Guangdong settlement implementation.
Q means total day-ahead coverage; H means physical forward delivery already bought.
All money uses CNY, energy MWh, prices CNY/MWh, with exactly 24 hourly intervals.
"""

import math
from datetime import date

from .contracts import ValidationError, curve, number


def _object(value, field):
    if not isinstance(value, dict):
        raise ValidationError("invalid_object", field + " must be an object")
    return value


def _identifier(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("invalid_identifier", field + " must be nonempty text")
    return value


def _required(obj, key):
    if key not in obj:
        raise ValidationError("missing_field", key + " is required")
    return obj[key]


def _sum(values, field):
    try:
        return number(math.fsum(values), field)
    except OverflowError as exc:
        raise ValidationError("numeric_overflow", field + " overflowed") from exc


def _rule_fee(rule):
    _object(rule, "rule")
    _identifier(rule.get("rule_id"), "rule_id")
    if rule.get("scope") != "synthetic":
        raise ValidationError("unsupported_rule", "Only the synthetic settlement adapter is implemented")
    if rule.get("price_basis") != "user_side":
        raise ValidationError("price_basis", "The synthetic adapter requires user_side prices")
    if rule.get("currency") != "CNY":
        raise ValidationError("currency", "Currency must be CNY")
    return number(_required(rule, "deviation_fee_cny_per_mwh"),
                  "deviation_fee_cny_per_mwh", minimum=0)


def settlement(q, l, da, rt, holdings, holding_cost, rule):
    """Calculate a 24-hour synthetic cost, without double-counting holdings.

    Cost = holding_cost + (Q-H)*DA + (L-Q)*RT + abs(Q-L)*deviation_fee.
    Negative prices and signed settlement legs are valid. Fee is nonnegative.
    Rounded display values must not be used as subsequent calculation inputs.
    """
    q = curve(q, "q", nonnegative=True)
    l = curve(l, "l", nonnegative=True)
    da = curve(da, "da")
    rt = curve(rt, "rt")
    holdings = curve(holdings, "holdings", nonnegative=True)
    holding_cost = curve(holding_cost, "holding_cost")
    fee_rate = _rule_fee(rule)
    energy = []
    fees = []
    hourly = []
    for i in range(24):
        e = number(holding_cost[i] + (q[i] - holdings[i]) * da[i]
                   + (l[i] - q[i]) * rt[i], "hourly_energy_cost")
        fee = number(abs(q[i] - l[i]) * fee_rate, "hourly_fee", minimum=0)
        energy.append(e)
        fees.append(fee)
        hourly.append(number(e + fee, "hourly_total_cost"))
    return {
        "total_cost_cny": _sum(hourly, "total_cost_cny"),
        "energy_cost_cny": _sum(energy, "energy_cost_cny"),
        "fee_cny": _sum(fees, "fee_cny"),
        "hourly_cost_cny": hourly,
    }


def make_plans(f, da, rt, config):
    """Produce three transparent candidates using forecast curves only.

    The bounded rule uses half the configured adjustment. These are baseline
    policies, not trained models or claims of globally optimal decisions.
    """
    f = curve(f, "f", nonnegative=True)
    da = curve(da, "da")
    rt = curve(rt, "rt")
    _object(config, "config")
    k_min = number(_required(config, "k_min"), "k_min", minimum=0)
    k_max = number(_required(config, "k_max"), "k_max", minimum=0)
    adjustment = number(_required(config, "adjustment"), "adjustment", minimum=0)
    threshold = number(_required(config, "spread_threshold"), "spread_threshold", minimum=0)
    if not k_min <= 1 <= k_max:
        raise ValidationError("coefficient_bounds", "Coefficient bounds must enclose baseline k=1")
    plans = []
    for name, scale in (("baseline", 0.0), ("spread_rule", 1.0), ("bounded_rule", 0.5)):
        coefficients = []
        for d, r in zip(da, rt):
            spread = number(r - d, "spread")
            direction = 1 if spread > threshold else -1 if spread < -threshold else 0
            raw = number(1 + direction * scale * adjustment, "coefficient")
            coefficients.append(min(k_max, max(k_min, raw)))
        plans.append({"name": name, "k": coefficients,
                      "q": [number(k * value, "q") for k, value in zip(coefficients, f)]})
    return plans


def _validate_plans(plans):
    if not isinstance(plans, list) or not plans:
        raise ValidationError("invalid_plans", "At least the baseline plan is required")
    normalized = []
    seen = set()
    baseline = None
    for plan in plans:
        _object(plan, "plan")
        name = _identifier(plan.get("name"), "plan.name")
        if name in seen:
            raise ValidationError("duplicate_plan", "Plan names must be unique")
        seen.add(name)
        item = {"name": name, "k": curve(plan.get("k"), "k", nonnegative=True),
                "q": curve(plan.get("q"), "q", nonnegative=True)}
        normalized.append(item)
        if name == "baseline":
            baseline = item
    if baseline is None or any(k != 1 for k in baseline["k"]):
        raise ValidationError("invalid_baseline", "A baseline with all k=1 is required")
    for item in normalized:
        for k, q, f in zip(item["k"], item["q"], baseline["q"]):
            expected = number(k * f, "q=k*f")
            if not math.isclose(q, expected, rel_tol=1e-10, abs_tol=1e-9):
                raise ValidationError("forecast_mismatch", "All plans must use the same F and Q=kF")
    return normalized, baseline


def _validate_scenarios(scenarios):
    _object(scenarios, "scenarios")
    scenario_set_id = _identifier(scenarios.get("scenario_set_id"), "scenario_set_id")
    kind = scenarios.get("kind")
    if kind not in ("stress", "probabilistic"):
        raise ValidationError("scenario_kind", "Scenario kind must be stress or probabilistic")
    if kind == "probabilistic" and scenarios.get("calibration_status") != "validated":
        raise ValidationError("uncalibrated_probability", "Probability metrics require validated calibration")
    items = scenarios.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationError("empty_scenarios", "A nonempty full-day scenario set is required")
    normalized = []
    seen = set()
    for item in items:
        _object(item, "scenario")
        identifier = _identifier(item.get("scenario_id"), "scenario_id")
        if identifier in seen:
            raise ValidationError("duplicate_scenario", "Scenario IDs must be unique")
        seen.add(identifier)
        record = {"scenario_id": identifier,
                  "l": curve(item.get("l"), "scenario.l", nonnegative=True),
                  "da": curve(item.get("da"), "scenario.da"),
                  "rt": curve(item.get("rt"), "scenario.rt")}
        if kind == "probabilistic":
            record["weight"] = number(_required(item, "weight"), "weight", minimum=0)
        elif "weight" in item:
            raise ValidationError("stress_weight", "Stress scenarios must not carry probability weights")
        normalized.append(record)
    if kind == "probabilistic":
        total = _sum([x["weight"] for x in normalized], "weight_sum")
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValidationError("weight_sum", "Scenario weights must sum to one")
        # Correct only floating point summation noise, never normalize arbitrary weights.
        for item in normalized:
            item["weight"] /= total
    return kind, scenario_set_id, normalized


def _cvar90(losses, weights):
    """Weighted upper-tail mean, including a fractional boundary scenario.

    Loss is signed candidate cost minus baseline cost. An all-profitable tail
    may have a negative CVaR; zero is not inserted into this distribution.
    """
    remaining = 0.1
    terms = []
    for loss, weight in sorted(zip(losses, weights), reverse=True):
        take = min(remaining, weight)
        terms.append(number(take * loss, "tail_loss"))
        remaining -= take
        if remaining <= 1e-12:
            break
    return number(_sum(terms, "tail_sum") / 0.1, "cvar90_loss_cny")


def evaluate_plans(plans, scenarios, holdings, holding_cost, rule, risk_budget):
    """Compare every candidate against the same F, portfolio, rule and scenarios.

    The function never chooses or executes a plan. A missing budget is explicit.
    Stress metrics are conditional extrema, not probability or expected values.
    In probabilistic mode zero-weight rows remain auditable but are not risk mass.
    """
    plans, baseline = _validate_plans(plans)
    kind, scenario_set_id, items = _validate_scenarios(scenarios)
    holdings = curve(holdings, "holdings", nonnegative=True)
    holding_cost = curve(holding_cost, "holding_cost")
    _rule_fee(rule)
    if risk_budget is not None:
        risk_budget = number(risk_budget, "risk_budget", minimum=0)
    base_costs = [settlement(baseline["q"], s["l"], s["da"], s["rt"],
                             holdings, holding_cost, rule)["total_cost_cny"] for s in items]
    evaluated = []
    for plan in plans:
        scenario_results = []
        for scenario, base_cost in zip(items, base_costs):
            result = settlement(plan["q"], scenario["l"], scenario["da"], scenario["rt"],
                                holdings, holding_cost, rule)
            scenario_results.append({"scenario_id": scenario["scenario_id"],
                                     "total_cost_cny": result["total_cost_cny"],
                                     "baseline_cost_cny": base_cost,
                                     "incremental_gain_cny": number(base_cost - result["total_cost_cny"], "gain")})
        gains = [row["incremental_gain_cny"] for row in scenario_results]
        # The worst supplied scenario is reported even if its probability is zero.
        # Probability-based acceptance, in contrast, uses CVaR of positive mass.
        result = dict(plan)
        result.update({"scenario_results": scenario_results,
                       "worst_loss_cny": max(0.0, -min(gains)),
                       "worst_incremental_gain_cny": min(gains)})
        risk_measure = result["worst_loss_cny"]
        if kind == "probabilistic":
            weights = [s["weight"] for s in items]
            costs = [r["total_cost_cny"] for r in scenario_results]
            result.update({"expected_cost_cny": _sum([w * c for w, c in zip(weights, costs)], "expected_cost"),
                           "expected_incremental_gain_cny": _sum([w * g for w, g in zip(weights, gains)], "expected_gain"),
                           "loss_probability": _sum([w for w, g in zip(weights, gains) if g < 0], "loss_probability"),
                           "cvar90_loss_cny": _cvar90([-g for g in gains], weights)})
            risk_measure = result["cvar90_loss_cny"]
        result["risk_status"] = ("needs_risk_budget" if risk_budget is None
                                 else "within_budget" if risk_measure <= risk_budget
                                 else "exceeds_budget")
        evaluated.append(result)
    return {"kind": kind, "scenario_set_id": scenario_set_id, "status": "research_only",
            "risk_budget_cny": risk_budget, "plans": evaluated}


def _gain_metrics(gains):
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for gain in gains:
        cumulative = number(cumulative + gain, "cumulative_gain")
        peak = max(peak, cumulative)
        drawdown = max(drawdown, number(peak - cumulative, "drawdown"))
    return {"days": len(gains), "total_incremental_gain_cny": _sum(gains, "total_gain"),
            "mean_daily_incremental_gain_cny": _sum(gains, "total_gain") / len(gains),
            "loss_day_fraction": sum(g < 0 for g in gains) / len(gains),
            "worst_day_gain_cny": min(gains), "max_drawdown_cny": drawdown}


def replay_metrics(rows):
    """Summarize one fixed candidate's realized daily comparisons.

    Dates must be unique and strictly increasing. Group drawdowns follow the
    subsequence of dates in that group, not a continuous full-calendar strategy.
    Loss-day fractions are historical frequencies, not forecast probabilities.
    """
    if not isinstance(rows, list) or not rows:
        raise ValidationError("empty_replay", "Replay needs at least one realized day")
    previous = None
    gains = []
    grouped = {}
    for row in rows:
        _object(row, "replay row")
        raw_day = row.get("date")
        try:
            day = date.fromisoformat(raw_day)
        except (ValueError, TypeError) as exc:
            raise ValidationError("invalid_date", "Replay date must be YYYY-MM-DD") from exc
        if day.isoformat() != raw_day:
            raise ValidationError("invalid_date", "Replay date must be YYYY-MM-DD")
        if previous is not None and day <= previous:
            raise ValidationError("replay_order", "Replay dates must be unique and increasing")
        previous = day
        group = _identifier(row.get("group"), "group")
        baseline = number(_required(row, "baseline_cost_cny"), "baseline_cost_cny")
        candidate = number(_required(row, "candidate_cost_cny"), "candidate_cost_cny")
        gain = number(baseline - candidate, "incremental_gain_cny")
        gains.append(gain)
        grouped.setdefault(group, []).append(gain)
    result = _gain_metrics(gains)
    result["groups"] = {group: _gain_metrics(values) for group, values in sorted(grouped.items())}
    return result
