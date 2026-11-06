"""Frozen multidimensional stress analysis for daily/monthly research decisions.

Limits are user inputs. Default profiles contain no assumed authorization. Stress
trajectories are conditional experiments, with no probabilities or live-rule claim.
"""
import calendar
import copy
import itertools
import math
from datetime import date, datetime, timedelta

from .contracts import SHANGHAI, ValidationError, digest, number, parse_time
from .economics import settlement


LIMIT_DIMENSIONS = {
    "max_price_shock_cost_cny": "price",
    "max_hourly_deviation_mwh": "volume",
    "max_daily_deviation_mwh": "volume",
    "max_assessment_fee_cny": "synthetic_assessment",
    "max_forecast_unhedged_mwh": "position",
    "max_gross_outflow_cny": "gross_outflow_proxy",
    "max_incremental_loss_cny": "incremental_period_loss",
    "max_daily_incremental_loss_cny": "incremental_daily_loss",
    "max_abs_k_deviation": "action_bound",
}
PROFILE_IDS = ("conservative", "steady", "aggressive")
PROFILE_LABELS = ("保守 / Conservative", "稳健 / Steady", "激进 / Aggressive")
DEFAULT_STRESS = {
    "load_factors": [0.7, 1.0, 1.3],
    "da_shifts": [-100.0, 0.0, 100.0],
    "rt_shifts": [-150.0, 0.0, 150.0],
    "shock_hours": [17, 18, 19, 20],
    "spike_delta_cny_per_mwh": 300.0,
    "negative_price_cny_per_mwh": -50.0,
    "surge_multiplier": 1.5,
    "surge_add_mwh": 10.0,
    "stop_multiplier": 0.0,
}
DEFAULT_CANDIDATES = {"max_abs_k_deviation": 0.2, "grid_step": 0.05,
                      "spread_threshold": 5.0}


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("RISK_ID", field + " must be nonempty text")
    return value


def _sum(values, field):
    try:
        return number(math.fsum(values), field)
    except OverflowError as exc:
        raise ValidationError("RISK_OVERFLOW", field + " overflowed") from exc


def _vector(values, name, n, nonnegative=False):
    if not isinstance(values, (list, tuple)) or len(values) != n:
        raise ValidationError("RISK_CURVE", name + " must cover the full decision period")
    return [number(v, name, 0 if nonnegative else None) for v in values]


def _period_hours(period_type, period):
    try:
        if period_type == "day":
            first = date.fromisoformat(period)
            if first.isoformat() != period:
                raise ValueError("noncanonical date")
            days = 1
        elif period_type == "month":
            first = date.fromisoformat(period + "-01")
            if first.strftime("%Y-%m") != period:
                raise ValueError("noncanonical month")
            days = calendar.monthrange(first.year, first.month)[1]
        else:
            raise ValueError("period_type must be day or month")
    except (ValueError, TypeError) as exc:
        raise ValidationError("RISK_PERIOD", str(exc)) from exc
    start = datetime(first.year, first.month, first.day, tzinfo=SHANGHAI)
    return [(start + timedelta(hours=h)).isoformat() for h in range(days * 24)]


def validate_context(context):
    """Validate one known-only origin, including a complete calendar month if used."""
    if not isinstance(context, dict):
        raise ValidationError("RISK_CONTEXT", "context must be an object")
    required = {"schema_version", "scope", "portfolio_id", "period_type", "period", "origin",
                "hours", "f", "da", "rt", "holdings", "holding_cost", "rule",
                "input_snapshot_id", "portfolio_state_id", "evidence"}
    if set(context) != required:
        raise ValidationError("RISK_FIELDS", "context must contain only the declared known-information fields")
    if context["schema_version"] != "risk-review-1" or context["scope"] != "synthetic":
        raise ValidationError("RISK_SCOPE", "only risk-review-1 synthetic research is supported")
    for field in ("portfolio_id", "input_snapshot_id", "portfolio_state_id"):
        _text(context[field], field)
    delivery = _period_hours(context["period_type"], context["period"])
    if context["hours"] != delivery:
        raise ValidationError("RISK_HOURS", "hours must be the complete ordered +08:00 delivery period")
    origin = parse_time(context["origin"])
    if origin >= parse_time(delivery[0]):
        raise ValidationError("RISK_ORIGIN", "one information origin must precede the whole delivery period")
    for field in ("f", "da", "rt", "holdings", "holding_cost"):
        _vector(context[field], field, len(delivery), field in ("f", "holdings"))
    evidence = context["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValidationError("RISK_EVIDENCE", "known inputs require source evidence")
    seen = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise ValidationError("RISK_EVIDENCE", "evidence must be objects")
        identifier = _text(item.get("id"), "evidence.id")
        _text(item.get("source_hash"), "evidence.source_hash")
        if identifier in seen:
            raise ValidationError("RISK_EVIDENCE", "evidence identifiers must be unique")
        seen.add(identifier)
        if parse_time(item.get("available_time")) > origin:
            raise ValidationError("RISK_FUTURE_INFORMATION", "evidence was unavailable at the origin")
    rule = context["rule"]
    if not isinstance(rule, dict):
        raise ValidationError("RISK_RULE", "rule must be an object")
    _text(rule.get("source"), "rule.source")
    try:
        begin = date.fromisoformat(rule["valid_from"])
        end = date.fromisoformat(rule["valid_to"])
    except (ValueError, TypeError, KeyError) as exc:
        raise ValidationError("RISK_RULE_VALIDITY", "rule validity dates are required") from exc
    if not begin <= parse_time(delivery[0]).date() <= parse_time(delivery[-1]).date() <= end:
        raise ValidationError("RISK_RULE_VALIDITY", "rule must cover the complete delivery period")
    # Reuse v1.1's explicit synthetic fee/basis/currency validation.
    settlement([0.0] * 24, [0.0] * 24, [0.0] * 24, [0.0] * 24,
               [0.0] * 24, [0.0] * 24, rule)
    digest(context)
    return copy.deepcopy(context)


def period_cost(q, l, da, rt, holdings, holding_cost, rule):
    """Sum the same settlement adapter over complete daily blocks."""
    if not isinstance(q, (list, tuple)) or not q or len(q) % 24:
        raise ValidationError("RISK_CURVE", "cost inputs must contain complete 24-hour blocks")
    n = len(q)
    vectors = [_vector(v, label, n, label in ("q", "l", "holdings"))
               for v, label in ((q, "q"), (l, "l"), (da, "da"), (rt, "rt"),
                                (holdings, "holdings"), (holding_cost, "holding_cost"))]
    pieces = [settlement(*(v[i:i + 24] for v in vectors), rule)
              for i in range(0, n, 24)]
    return {"total_cost_cny": _sum([p["total_cost_cny"] for p in pieces], "period_cost"),
            "fee_cny": _sum([p["fee_cny"] for p in pieces], "period_fee"),
            "energy_cost_cny": _sum([p["energy_cost_cny"] for p in pieces], "period_energy_cost"),
            "hourly_cost_cny": [c for p in pieces for c in p["hourly_cost_cny"]]}


def default_profiles():
    return [{"id": name, "label": label, "limits": {key: None for key in LIMIT_DIMENSIONS}}
            for name, label in zip(PROFILE_IDS, PROFILE_LABELS)]


def _profiles(profiles):
    if profiles is None:
        return default_profiles()
    if not isinstance(profiles, list) or len(profiles) != 3:
        raise ValidationError("RISK_PROFILES", "three profiles are required")
    by_id = {}
    for profile in profiles:
        if not isinstance(profile, dict) or profile.get("id") not in PROFILE_IDS:
            raise ValidationError("RISK_PROFILES", "unknown profile identifier")
        if profile["id"] in by_id:
            raise ValidationError("RISK_PROFILES", "duplicate profile identifier")
        limits = profile.get("limits")
        if not isinstance(limits, dict) or set(limits) - set(LIMIT_DIMENSIONS):
            raise ValidationError("RISK_LIMITS", "limits contain unknown fields")
        by_id[profile["id"]] = {"id": profile["id"], "label": _text(profile.get("label"), "profile.label"),
                                "limits": {key: None if limits.get(key) is None else
                                           number(limits[key], key, 0) for key in LIMIT_DIMENSIONS}}
    result = [by_id[name] for name in PROFILE_IDS]
    for key in LIMIT_DIMENSIONS:
        previous = None
        for profile in result:
            value = profile["limits"][key]
            if value is not None:
                if previous is not None and value < previous:
                    raise ValidationError("RISK_LIMIT_ORDER", key + " must not decrease toward aggressive")
                previous = value
    return result


def _stress_config(config):
    if config is not None and (not isinstance(config, dict) or set(config) - set(DEFAULT_STRESS)):
        raise ValidationError("RISK_STRESS_CONFIG", "unknown stress configuration")
    result = copy.deepcopy(DEFAULT_STRESS)
    result.update(copy.deepcopy(config or {}))
    for field, center in (("load_factors", 1.0), ("da_shifts", 0.0), ("rt_shifts", 0.0)):
        values = result[field]
        if not isinstance(values, list) or not values or len(values) > 9:
            raise ValidationError("RISK_STRESS_CONFIG", field + " requires 1 to 9 values")
        values = [number(v, field, 0 if field == "load_factors" else None) for v in values]
        if center not in values or len(values) != len(set(values)):
            raise ValidationError("RISK_STRESS_CONFIG", field + " must include the center once")
        result[field] = sorted(values)
    if math.prod(len(result[k]) for k in ("load_factors", "da_shifts", "rt_shifts")) > 343:
        raise ValidationError("RISK_STRESS_CONFIG", "at most 343 crossed scenarios are supported")
    hs = result["shock_hours"]
    if (not isinstance(hs, list) or not hs or len(set(hs)) != len(hs)
            or any(isinstance(h, bool) or not isinstance(h, int) or not 0 <= h < 24 for h in hs)):
        raise ValidationError("RISK_STRESS_CONFIG", "shock_hours must be unique hours 0 to 23")
    result["shock_hours"] = sorted(hs)
    for key in ("spike_delta_cny_per_mwh", "surge_multiplier", "surge_add_mwh", "stop_multiplier"):
        result[key] = number(result[key], key, 0)
    result["negative_price_cny_per_mwh"] = number(result["negative_price_cny_per_mwh"], "negative_price")
    if result["negative_price_cny_per_mwh"] >= 0:
        raise ValidationError("RISK_STRESS_CONFIG", "negative price scenario requires a negative price")
    if result["surge_multiplier"] < 1 or result["stop_multiplier"] > 1:
        raise ValidationError("RISK_STRESS_CONFIG", "surge >=1 and stop <=1 are required")
    return result


def build_stress_scenarios(context, config=None):
    c = validate_context(context)
    config = _stress_config(config)
    items = [{"scenario_id": "central", "label": "中心预测 / Central forecast", "category": "central",
              "l": list(c["f"]), "da": list(c["da"]), "rt": list(c["rt"])}]
    for i, (factor, d_shift, r_shift) in enumerate(itertools.product(config["load_factors"],
                                                                  config["da_shifts"], config["rt_shifts"])):
        if factor == 1 and d_shift == 0 and r_shift == 0:
            continue
        items.append({"scenario_id": "cross-{:03d}".format(i), "category": "crossed_load_prices",
                      "label": "L×{}; DA{:+g}; RT{:+g}".format(factor, d_shift, r_shift),
                      "l": [number(v * factor, "stress_l", 0) for v in c["f"]],
                      "da": [number(v + d_shift, "stress_da") for v in c["da"]],
                      "rt": [number(v + r_shift, "stress_rt") for v in c["rt"]]})
    mask = [parse_time(h).hour in config["shock_hours"] for h in c["hours"]]
    extra = [
        ("rt_spike", "尖峰实时价 / RT spike", "price_spike", "rt", lambda v: v + config["spike_delta_cny_per_mwh"]),
        ("da_spike", "尖峰日前价 / DA spike", "price_spike", "da", lambda v: v + config["spike_delta_cny_per_mwh"]),
        ("rt_drop", "实时价骤降 / RT drop", "price_drop", "rt", lambda v: v - config["spike_delta_cny_per_mwh"]),
        ("negative_rt", "实时负价 / Negative RT", "negative_price", "rt", lambda v: config["negative_price_cny_per_mwh"]),
        ("negative_da", "日前负价 / Negative DA", "negative_price", "da", lambda v: config["negative_price_cny_per_mwh"]),
        ("load_stop", "用电骤停 / Load stop", "volume_shock", "l", lambda v: v * config["stop_multiplier"]),
        ("load_surge", "用电突增 / Load surge", "volume_shock", "l", lambda v: v * config["surge_multiplier"] + config["surge_add_mwh"]),
    ]
    for identifier, label, category, field, transform in extra:
        item = {"scenario_id": identifier, "label": label, "category": category,
                "l": list(c["f"]), "da": list(c["da"]), "rt": list(c["rt"])}
        item[field] = [number(transform(v) if active else v, "stress_" + field,
                              0 if field == "l" else None) for v, active in zip(item[field], mask)]
        items.append(item)
    items.append({"scenario_id": "spread_reversal", "label": "价差方向反转 / Spread reversal",
                  "category": "spread_reversal", "l": list(c["f"]), "da": list(c["da"]),
                  "rt": [number(2 * d - r, "reversed_rt") for d, r in zip(c["da"], c["rt"])]})
    return {"kind": "stress", "items": items, "config": config,
            "scenario_set_id": digest({"context_id": digest(c), "config": config, "items": items})}


def _candidate_config(config):
    if config is not None and (not isinstance(config, dict) or set(config) - set(DEFAULT_CANDIDATES)):
        raise ValidationError("RISK_CANDIDATE_CONFIG", "unknown candidate configuration")
    result = dict(DEFAULT_CANDIDATES, **(config or {}))
    for key in result:
        result[key] = number(result[key], key, 0)
    if result["max_abs_k_deviation"] > 1 or result["grid_step"] <= 0:
        raise ValidationError("RISK_CANDIDATE_CONFIG", "deviation <=1 and grid_step >0 required")
    if result["max_abs_k_deviation"] / result["grid_step"] > 50:
        raise ValidationError("RISK_CANDIDATE_CONFIG", "coefficient grid exceeds 101 points")
    return result


def build_candidates(context, config=None):
    c = validate_context(context)
    config = _candidate_config(config)
    limit, step, threshold = (config[k] for k in ("max_abs_k_deviation", "grid_step", "spread_threshold"))
    signals = [1 if r - d > threshold else -1 if r - d < -threshold else 0
               for d, r in zip(c["da"], c["rt"])]
    vectors = [("baseline", [1.0] * len(c["f"]))]
    for name, fraction in (("spread_rule", 1.0), ("bounded_rule", 0.5)):
        vectors.append((name, [round(1 + direction * limit * fraction, 12) for direction in signals]))
    offsets = {0.0, -limit, limit}
    for i in range(1, int(math.floor(limit / step + 1e-12)) + 1):
        offsets.update((round(min(limit, i * step), 12), round(-min(limit, i * step), 12)))
    for offset in sorted(offsets):
        if offset:
            vectors.append(("constant_k_{:.4f}".format(1 + offset), [round(1 + offset, 12)] * len(c["f"])))
    plans = []
    for name, k in vectors:
        q = [number(multiplier * f, "q", 0) for multiplier, f in zip(k, c["f"])]
        identity = {"context_id": digest(c), "name": name, "k": k, "q": q}
        plans.append({"plan_id": name + "-" + digest(identity)[:16], "name": name, "k": k, "q": q})
    return plans


def _gross_outflow(q, scenario, context):
    fee = context["rule"]["deviation_fee_cny_per_mwh"]
    return _sum([number(max(b, 0) + max((a - h) * d, 0) + max((l - a) * r, 0)
                        + abs(a - l) * fee, "gross_hourly_outflow", 0)
                 for a, l, d, r, h, b in zip(q, scenario["l"], scenario["da"], scenario["rt"],
                                            context["holdings"], context["holding_cost"])], "gross_outflow")


def assess_risk(context, profiles=None, stress_config=None, candidate_config=None):
    c = validate_context(context)
    profiles = _profiles(profiles)
    scenarios = build_stress_scenarios(c, stress_config)
    candidate_config = _candidate_config(candidate_config)
    candidates = build_candidates(c, candidate_config)
    baseline = candidates[0]
    base = {s["scenario_id"]: period_cost(baseline["q"], s["l"], s["da"], s["rt"],
                                         c["holdings"], c["holding_cost"], c["rule"])
            for s in scenarios["items"]}
    plans = []
    for candidate in candidates:
        q = candidate["q"]
        center = period_cost(q, c["f"], c["da"], c["rt"], c["holdings"], c["holding_cost"], c["rule"])
        metrics = {key: 0.0 for key in LIMIT_DIMENSIONS}
        metrics["max_forecast_unhedged_mwh"] = max(abs(f - h) for f, h in zip(c["f"], c["holdings"]))
        metrics["max_abs_k_deviation"] = max(abs(k - 1) for k in candidate["k"])
        witnesses = {key: {"scenario_id": "central"} for key in LIMIT_DIMENSIONS}
        witnesses["max_forecast_unhedged_mwh"] = {"scenario_id": None, "basis": "structural_forecast_minus_holdings"}
        witnesses["max_abs_k_deviation"] = {"scenario_id": None, "basis": "fixed_candidate_action"}
        rows = []
        daily_incremental_loss = 0.0
        for scenario in scenarios["items"]:
            previous_metrics = dict(metrics)
            cost = period_cost(q, scenario["l"], scenario["da"], scenario["rt"],
                               c["holdings"], c["holding_cost"], c["rule"])
            price_only = period_cost(q, c["f"], scenario["da"], scenario["rt"],
                                     c["holdings"], c["holding_cost"], c["rule"])["total_cost_cny"]
            deviations = [abs(a - l) for a, l in zip(q, scenario["l"])]
            gross = _gross_outflow(q, scenario, c)
            baseline_cost = base[scenario["scenario_id"]]
            gain = number(baseline_cost["total_cost_cny"] - cost["total_cost_cny"], "incremental_gain")
            metrics["max_price_shock_cost_cny"] = max(metrics["max_price_shock_cost_cny"], price_only - center["total_cost_cny"])
            metrics["max_hourly_deviation_mwh"] = max(metrics["max_hourly_deviation_mwh"], max(deviations))
            metrics["max_daily_deviation_mwh"] = max(metrics["max_daily_deviation_mwh"],
                max(_sum(deviations[i:i + 24], "daily_deviation") for i in range(0, len(q), 24)))
            metrics["max_assessment_fee_cny"] = max(metrics["max_assessment_fee_cny"], cost["fee_cny"])
            metrics["max_gross_outflow_cny"] = max(metrics["max_gross_outflow_cny"], gross)
            metrics["max_incremental_loss_cny"] = max(metrics["max_incremental_loss_cny"], -gain)
            for start in range(0, len(q), 24):
                day_loss = _sum(cost["hourly_cost_cny"][start:start + 24], "day_cost") - _sum(
                    baseline_cost["hourly_cost_cny"][start:start + 24], "baseline_day_cost")
                daily_incremental_loss = max(daily_incremental_loss, day_loss)
            metrics["max_daily_incremental_loss_cny"] = daily_incremental_loss
            for key in metrics:
                if metrics[key] > previous_metrics[key]:
                    witnesses[key] = {"scenario_id": scenario["scenario_id"]}
            rows.append({"scenario_id": scenario["scenario_id"], "cost_cny": cost["total_cost_cny"],
                         "incremental_gain_cny": gain, "fee_cny": cost["fee_cny"], "gross_outflow_cny": gross})
        metrics["max_daily_incremental_loss_cny"] = daily_incremental_loss
        plan = dict(candidate, metrics={key: number(v, key, 0) for key, v in metrics.items()}, metric_witnesses=witnesses,
                    scenario_results=rows, central_cost_cny=center["total_cost_cny"],
                    worst_total_cost_cny=max(r["cost_cny"] for r in rows),
                    max_daily_incremental_loss_cny=number(daily_incremental_loss, "daily_loss", 0))
        plan["plan_hash"] = digest(plan)
        plans.append(plan)
    profile_results = []
    for profile in profiles:
        checks = []
        for plan in plans:
            missing = [key for key, limit in profile["limits"].items() if limit is None]
            violations = [{"metric": key, "dimension": LIMIT_DIMENSIONS[key], "observed": plan["metrics"][key],
                           "limit": limit, "excess": plan["metrics"][key] - limit}
                          for key, limit in profile["limits"].items() if limit is not None
                          and plan["metrics"][key] > limit + max(1e-9, abs(limit) * 1e-12)]
            checks.append({"plan_id": plan["plan_id"], "status": "breached" if violations else
                           "needs_limits" if missing else "eligible", "violations": violations,
                           "missing_limits": missing})
        ids = [x["plan_id"] for x in checks if x["status"] == "eligible"]
        eligible = [p for p in plans if p["plan_id"] in ids]
        references = {"central_min_cost": None, "minimax_regret": None}
        regrets, pareto = {}, []
        if eligible:
            references["central_min_cost"] = min(eligible, key=lambda p: (p["central_cost_cny"], p["plan_id"]))["plan_id"]
            scenario_best = [min(p["scenario_results"][i]["cost_cny"] for p in eligible)
                             for i in range(len(scenarios["items"]))]
            regrets = {p["plan_id"]: max(r["cost_cny"] - best for r, best in zip(p["scenario_results"], scenario_best))
                       for p in eligible}
            references["minimax_regret"] = min(ids, key=lambda identifier: (regrets[identifier], identifier))
            for p in eligible:
                x = (p["central_cost_cny"], p["metrics"]["max_incremental_loss_cny"])
                dominated = any(other["central_cost_cny"] <= x[0]
                                and other["metrics"]["max_incremental_loss_cny"] <= x[1]
                                and (other["central_cost_cny"] < x[0] or other["metrics"]["max_incremental_loss_cny"] < x[1])
                                for other in eligible)
                if not dominated:
                    pareto.append(p["plan_id"])
        profile_results.append({"profile_id": profile["id"], "checks": checks, "admissible_plan_ids": ids,
                                "reference_choices": references, "pareto_plan_ids": pareto,
                                "max_regret_cny_by_plan": regrets})
    report = {"schema_version": "risk-report-1", "status": "research_only", "context": c,
              "profiles": profiles, "scenarios": scenarios, "candidate_config": candidate_config,
              "plans": plans, "profile_results": profile_results,
              "coverage": {"dimensions": dict(LIMIT_DIMENSIONS), "data_checks": "passed",
                           "operational_readiness": "not_connected", "probabilities": "not_assigned",
                           "rule_validation": "synthetic_adapter_only", "automatic_selection": False,
                           "formal_assessment_rule": "not_connected", "business_ready": False,
                           "overlapping_metrics_are_additive": False,
                           "position_metric": "max_hour_abs_F_minus_H_is_structural_and_shared_by_all_candidates",
                           "money_limit_horizon": "entire_decision_period",
                           "volume_daily_limit_horizon": "maximum_individual_calendar_day",
                           "cash_proxy_boundary": "gross_positive_settlement_legs_not_margin_or_timing_liquidity",
                           "not_modelled": ["certified_assessment_rules", "counterparty_default", "settlement_timing_liquidity",
                                             "exchange_execution", "joint_probability_calibration"]}}
    report["report_id"] = "risk-" + digest({"context": c, "profiles": profiles,
                                          "stress_config": scenarios["config"], "candidate_config": candidate_config})[:24]
    report["report_hash"] = digest(report)
    return report


def verify_risk_report(report):
    """Recompute consequences and profile qualifications, in addition to hashes."""
    if not isinstance(report, dict):
        raise ValidationError("RISK_REPORT", "risk report must be an object")
    unsigned = {k: v for k, v in report.items() if k != "report_hash"}
    if report.get("report_hash") != digest(unsigned):
        raise ValidationError("RISK_REPORT_HASH", "risk report was changed")
    try:
        for plan in report["plans"]:
            if plan["plan_hash"] != digest({k: v for k, v in plan.items() if k != "plan_hash"}):
                raise ValidationError("RISK_PLAN_HASH", "risk plan was changed")
        fresh = assess_risk(report["context"], report["profiles"], report["scenarios"]["config"], report["candidate_config"])
    except (KeyError, TypeError) as exc:
        raise ValidationError("RISK_REPORT", "risk report is incomplete") from exc
    if fresh["report_hash"] != report["report_hash"]:
        raise ValidationError("RISK_REPORT_RECOMPUTE", "report does not match recomputed risk")
    return {"verified": True, "report_id": report["report_id"], "report_hash": report["report_hash"]}
