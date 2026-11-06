"""Decision review with a frozen information set and explicit hindsight boundaries.

Only synthetic accounting is implemented. Human identity, input sources and historical
timestamps are declarations, not authenticated exchange receipts or approval records.
"""
import calendar
import copy
import math
import re
from datetime import date, datetime, timedelta

from .contracts import SHANGHAI, ValidationError, digest, number, parse_time
from .risk import period_cost, verify_risk_report


def _object(value, field):
    if not isinstance(value, dict):
        raise ValidationError("REVIEW_OBJECT", field + " must be an object")
    return value


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("REVIEW_TEXT", field + " must be nonempty text")
    return value


def _curve(value, length, field, nonnegative=False):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValidationError("REVIEW_CURVE", field + " must cover the complete decision period")
    return [number(v, field, 0 if nonnegative else None) for v in value]


def _sum(values, field):
    try:
        return number(math.fsum(values), field)
    except OverflowError as exc:
        raise ValidationError("REVIEW_OVERFLOW", field + " overflowed") from exc


def _seal(payload, hash_field):
    result = copy.deepcopy(payload)
    result[hash_field] = digest(result)
    return result


def _check_seal(payload, hash_field):
    _object(payload, hash_field)
    expected = payload.get(hash_field)
    body = {key: value for key, value in payload.items() if key != hash_field}
    if not isinstance(expected, str) or expected != digest(body):
        raise ValidationError("REVIEW_HASH", hash_field + " does not match its content")


def _period_bounds(period_type, period):
    try:
        if period_type == "day":
            value = date.fromisoformat(period)
            if value.isoformat() != period:
                raise ValueError("noncanonical date")
            begin = datetime(value.year, value.month, value.day, tzinfo=SHANGHAI)
            return begin, begin + timedelta(days=1)
        if period_type == "month" and isinstance(period, str) and re.fullmatch(r"\d{4}-\d{2}", period):
            value = date.fromisoformat(period + "-01")
            begin = datetime(value.year, value.month, 1, tzinfo=SHANGHAI)
            return begin, begin + timedelta(days=calendar.monthrange(value.year, value.month)[1])
    except (ValueError, TypeError) as exc:
        raise ValidationError("REVIEW_PERIOD", "invalid decision period") from exc
    raise ValidationError("REVIEW_PERIOD", "period must be a day or a calendar month")


def _choice_payload(report, profile_id, plan_id, actor, reason, selected_at, historical_evidence=None):
    context = report["context"]
    for field, value in (("profile_id", profile_id), ("plan_id", plan_id),
                         ("actor", actor), ("reason", reason)):
        _text(value, field)
    chosen_at = parse_time(selected_at)
    if not parse_time(context["origin"]) <= chosen_at < parse_time(context["hours"][0]):
        raise ValidationError("DECISION_TIME", "choice must be at/after origin and before delivery starts")
    profiles = [p for p in report["profile_results"] if p["profile_id"] == profile_id]
    plans = [p for p in report["plans"] if p["plan_id"] == plan_id]
    if len(profiles) != 1 or len(plans) != 1:
        raise ValidationError("DECISION_SCOPE", "profile or plan is absent from the frozen report")
    checks = [c for c in profiles[0]["checks"] if c["plan_id"] == plan_id]
    if len(checks) != 1:
        raise ValidationError("DECISION_SCOPE", "plan has no unique frozen admissibility check")
    eligible = checks[0]["status"] == "eligible" and plan_id in profiles[0]["admissible_plan_ids"]
    if not eligible and historical_evidence is None:
        raise ValidationError("DECISION_INELIGIBLE", "unresolved or breached limits cannot authorize a choice")
    if historical_evidence is not None:
        _object(historical_evidence, "historical evidence")
        _text(historical_evidence.get("source"), "historical evidence source")
        _text(historical_evidence.get("reference"), "historical evidence reference")
        if parse_time(historical_evidence.get("available_time")) < chosen_at:
            raise ValidationError("HISTORICAL_TIME", "evidence cannot precede the declared choice")
    payload = {"schema_version": "risk-review-1", "scope": "synthetic",
               "record_type": ("declared_research_choice" if historical_evidence is None
                               else "historical_observation_not_authorization"),
               "report_hash": report["report_hash"],
               "report_id": report["report_id"], "portfolio_id": context["portfolio_id"],
               "period_type": context["period_type"], "period": context["period"],
               "profile_id": profile_id, "plan_id": plan_id, "plan_hash": plans[0]["plan_hash"],
               "actor": actor, "reason": reason, "selected_at": selected_at,
               "admissibility_status": checks[0]["status"],
               "violations": copy.deepcopy(checks[0]["violations"]),
               "missing_limits": copy.deepcopy(checks[0]["missing_limits"]),
               "identity_and_time_evidence": "caller_declared_not_authenticated"}
    if historical_evidence is not None:
        payload["historical_evidence"] = copy.deepcopy(historical_evidence)
        payload["historical_evidence_hash"] = digest(historical_evidence)
    payload["decision_id"] = "decision-" + digest(payload)[:24]
    return payload


def record_decision(report, profile_id, plan_id, actor, reason, selected_at):
    """Record one explicit human research choice after checking all frozen limits."""
    verify_risk_report(report)
    return _seal(_choice_payload(report, profile_id, plan_id, actor, reason, selected_at), "decision_hash")


def record_historical_decision(report, profile_id, plan_id, actor, reason, selected_at, evidence):
    """Import a historical observation, including violations, without authorizing it."""
    verify_risk_report(report)
    _object(evidence, "historical evidence")
    return _seal(_choice_payload(report, profile_id, plan_id, actor, reason, selected_at,
                                historical_evidence=evidence), "decision_hash")


def _observations(context, actuals, execution, selected_at):
    _object(actuals, "actuals")
    if actuals.get("hours") != context["hours"]:
        raise ValidationError("ACTUAL_HOURS", "actuals must match every frozen delivery hour in order")
    for field, expected in (("price_basis", "user_side"), ("energy_unit", "MWh"), ("price_unit", "CNY/MWh")):
        if actuals.get(field) != expected:
            raise ValidationError("ACTUAL_BASIS", field + " differs from the research contract")
    for field in ("portfolio_id", "period_type", "period"):
        if field in actuals and actuals[field] != context[field]:
            raise ValidationError("ACTUAL_SCOPE", "actuals refer to another " + field)
    _text(actuals.get("source"), "actuals.source")
    length = len(context["hours"])
    observed = {"l": _curve(actuals.get("l"), length, "actual load", True),
                "da": _curve(actuals.get("da"), length, "actual DA"),
                "rt": _curve(actuals.get("rt"), length, "actual RT")}
    available = parse_time(actuals.get("available_time"))
    end = parse_time(context["hours"][-1]) + timedelta(hours=1)
    if available < end:
        raise ValidationError("ACTUAL_TIME", "complete-period actuals cannot precede delivery completion")
    executed = None
    if execution is not None:
        _object(execution, "execution")
        if execution.get("hours") != context["hours"]:
            raise ValidationError("EXECUTION_HOURS", "execution must match every frozen delivery hour in order")
        if execution.get("energy_unit") != "MWh":
            raise ValidationError("EXECUTION_UNIT", "execution energy_unit must be MWh")
        _text(execution.get("source"), "execution.source")
        for field in ("portfolio_id", "period_type", "period"):
            if field in execution and execution[field] != context[field]:
                raise ValidationError("EXECUTION_SCOPE", "execution refers to another " + field)
        execution_available = parse_time(execution.get("available_time"))
        if execution_available < parse_time(selected_at):
            raise ValidationError("EXECUTION_TIME", "execution evidence cannot precede the recorded choice")
        executed = {"hours": list(execution["hours"]), "energy_unit": execution["energy_unit"],
                    "q": _curve(execution.get("q"), length, "executed Q", True),
                    "source": execution["source"], "available_time": execution["available_time"]}
        available = max(available, execution_available)
    return observed, executed, available


def _diagnostics(context, observed):
    n = len(context["hours"])
    load_error = [a - f for a, f in zip(observed["l"], context["f"])]
    da_error = [a - f for a, f in zip(observed["da"], context["da"])]
    rt_error = [a - f for a, f in zip(observed["rt"], context["rt"])]
    predicted_spread = [r - d for r, d in zip(context["rt"], context["da"])]
    actual_spread = [r - d for r, d in zip(observed["rt"], observed["da"])]
    sign = lambda value: (value > 0) - (value < 0)
    return {"hours": n, "error_convention": "actual_minus_forecast",
            "load_mae_mwh": _sum([abs(x) for x in load_error], "load MAE") / n,
            "load_bias_mwh": _sum(load_error, "load bias") / n,
            "load_total_error_mwh": _sum(load_error, "load error total"),
            "da_mae_cny_per_mwh": _sum([abs(x) for x in da_error], "DA MAE") / n,
            "rt_mae_cny_per_mwh": _sum([abs(x) for x in rt_error], "RT MAE") / n,
            "spread_mae_cny_per_mwh": _sum([abs(a - p) for a, p in zip(actual_spread, predicted_spread)], "spread MAE") / n,
            "spread_direction_match_fraction": sum(sign(a) == sign(p) for a, p in zip(actual_spread, predicted_spread)) / n,
            "interpretation": "descriptive_outcome_metrics_not_future_performance"}


def _coverage(context, observed, scenarios):
    n = len(context["hours"])
    fields = {}
    any_outside = set()
    for name in ("load", "da", "rt", "spread"):
        key = "l" if name == "load" else name
        actual = ([r - d for r, d in zip(observed["rt"], observed["da"])]
                  if name == "spread" else observed[key])
        paths = ([[r - d for r, d in zip(s["rt"], s["da"])] for s in scenarios]
                 if name == "spread" else [s[key] for s in scenarios])
        lower, upper = [], []
        for h, value in enumerate(actual):
            if value < min(path[h] for path in paths) - 1e-9:
                lower.append(h)
            if value > max(path[h] for path in paths) + 1e-9:
                upper.append(h)
        outside = sorted(set(lower + upper))
        any_outside.update(outside)
        fields[name] = {"outside_count": len(outside), "total_count": n,
                        "lower_breach_count": len(lower), "upper_breach_count": len(upper),
                        "outside_hours": [context["hours"][h] for h in outside]}
    return {"variables": fields, "outside_any_count": len(any_outside),
            "has_uncovered_observation": bool(any_outside),
            "interpretation": "per_hour_marginal_envelope_only_not_joint_or_probability_coverage"}


def _execution_checks(context, selected, executed, profile):
    if executed is None:
        return {"status": "not_provided", "source_verified": False}
    n = len(context["hours"])
    differences = [q - p for q, p in zip(executed["q"], selected["q"])]
    positive_at_zero_forecast = [context["hours"][h] for h in range(n)
                                 if context["f"][h] == 0 and executed["q"][h] != 0]
    ratios = [abs(q / f - 1) for q, f in zip(executed["q"], context["f"]) if f > 0]
    limit = profile["limits"]["max_abs_k_deviation"]
    changed_hours = [context["hours"][h] for h, value in enumerate(differences) if abs(value) > 1e-9]
    return {"status": "provided_unverified", "source_verified": False,
            "changed_hour_count": len(changed_hours), "changed_hours": changed_hours,
            "absolute_change_mwh": _sum([abs(v) for v in differences], "execution change"),
            "max_abs_k_deviation": max(ratios, default=0.0),
            "positive_q_at_zero_forecast_hours": positive_at_zero_forecast,
            "action_bound_breached": (None if limit is None else
                                      bool(positive_at_zero_forecast) or max(ratios, default=0.0) > limit + 1e-9),
            "action_bound_status": "needs_limits" if limit is None else "evaluated",
            "scope": "action_bound_only_not_full_ex_ante_risk_reassessment"}


def review_decision(report, decision, actuals, execution=None):
    """Evaluate the frozen choice without turning hindsight into a feasible policy."""
    verify_risk_report(report)
    _check_seal(decision, "decision_hash")
    record_type = decision.get("record_type")
    if record_type not in ("declared_research_choice", "historical_observation_not_authorization"):
        raise ValidationError("DECISION_TYPE", "unknown decision record type")
    historical = (decision.get("historical_evidence")
                  if record_type == "historical_observation_not_authorization" else None)
    if record_type == "historical_observation_not_authorization":
        _object(historical, "historical evidence")
    expected = _choice_payload(report, decision.get("profile_id"), decision.get("plan_id"),
                               decision.get("actor"), decision.get("reason"), decision.get("selected_at"), historical)
    if decision != _seal(expected, "decision_hash"):
        raise ValidationError("DECISION_BINDING", "decision does not match the supplied frozen report")
    context = report["context"]
    observed, executed, known_at = _observations(context, actuals, execution, decision["selected_at"])
    if historical is not None:
        known_at = max(known_at, parse_time(historical["available_time"]))
    plans = {p["plan_id"]: p for p in report["plans"]}
    selected = plans[decision["plan_id"]]
    baseline = next(p for p in report["plans"] if p["name"] == "baseline")
    profile_result = next(p for p in report["profile_results"] if p["profile_id"] == decision["profile_id"])
    profile = next(p for p in report["profiles"] if p["id"] == decision["profile_id"])
    admissible = profile_result["admissible_plan_ids"]

    def cost(q, l, da, rt):
        return period_cost(q, l, da, rt, context["holdings"], context["holding_cost"], context["rule"])

    baseline_cost = cost(baseline["q"], observed["l"], observed["da"], observed["rt"])

    def outcome(plan):
        result = cost(plan["q"], observed["l"], observed["da"], observed["rt"])
        return {"plan_id": plan["plan_id"], "name": plan["name"], "plan_hash": plan["plan_hash"],
                "cost_cny": result["total_cost_cny"], "fee_cny": result["fee_cny"],
                "incremental_gain_cny": number(baseline_cost["total_cost_cny"] - result["total_cost_cny"], "realized gain")}

    frozen_outcomes = [outcome(plans[plan_id]) for plan_id in admissible]
    chosen = outcome(selected)
    references = {}
    for name, plan_id in profile_result["reference_choices"].items():
        if plan_id is not None:
            if plan_id not in admissible:
                raise ValidationError("REFERENCE_SCOPE", "reference policy is outside the frozen admissible set")
            references[name] = dict(outcome(plans[plan_id]),
                                    selection_basis="frozen_ex_ante_risk_report_only",
                                    gain_vs_chosen_cny=number(chosen["cost_cny"] - outcome(plans[plan_id])["cost_cny"], "reference gain"))
        else:
            references[name] = None
    hindsight = None
    if frozen_outcomes:
        hindsight = dict(min(frozen_outcomes, key=lambda item: (item["cost_cny"], item["plan_id"])))
        hindsight.update({"selection_basis": "hindsight_only_within_frozen_admissible_candidates",
                          "candidate_count": len(frozen_outcomes),
                          "gap_to_chosen_cny": number(chosen["cost_cny"] - hindsight["cost_cny"], "hindsight gap"),
                          "chosen_in_comparison_set": selected["plan_id"] in admissible,
                          "gap_interpretation": ("within_set_hindsight_gap" if selected["plan_id"] in admissible
                                                 else "outside_set_cost_comparison_not_regret"),
                          "not_an_achievable_policy_target": True})
    stages = [("forecast_center", context["f"], context["da"], context["rt"], selected["q"]),
              ("actual_load", observed["l"], context["da"], context["rt"], selected["q"]),
              ("actual_da_price", observed["l"], observed["da"], context["rt"], selected["q"]),
              ("actual_rt_price", observed["l"], observed["da"], observed["rt"], selected["q"])]
    if executed is not None:
        stages.append(("provided_execution_q", observed["l"], observed["da"], observed["rt"], executed["q"]))
    costs = [(name, cost(q, l, da, rt)["total_cost_cny"]) for name, l, da, rt, q in stages]
    steps = [{"factor": after_name, "before_cost_cny": before_cost, "after_cost_cny": after_cost,
              "delta_cost_cny": number(after_cost - before_cost, "bridge delta")}
             for (_, before_cost), (after_name, after_cost) in zip(costs, costs[1:])]
    total_change = number(costs[-1][1] - costs[0][1], "total bridge change")
    sum_components = _sum([s["delta_cost_cny"] for s in steps], "bridge components")
    bridge = {"order": [s["factor"] for s in steps], "steps": steps,
              "forecast_cost_cny": costs[0][1], "selected_actual_cost_cny": chosen["cost_cny"],
              "terminal_cost_cny": costs[-1][1], "total_change_cny": total_change,
              "sum_components_cny": sum_components,
              "reconciliation_error_cny": number(sum_components - total_change, "bridge reconciliation"),
              "interpretation": "fixed_order_descriptive_bridge_not_independent_or_causal_contributions"}
    coverage = _coverage(context, observed, report["scenarios"]["items"])
    diagnostics = _diagnostics(context, observed)
    execution_checks = _execution_checks(context, selected, executed, profile)
    lessons = [{"topic": "decision_vs_outcome", "evidence": "frozen choice admissibility: " + decision["admissibility_status"],
                "proposal": "Compare the pre-registered reference policies on a later untouched period.",
                "status": "proposed_not_validated", "automatic_promotion": False}]
    if decision["admissibility_status"] != "eligible":
        lessons.append({"topic": "historical_admissibility", "evidence": decision["admissibility_status"],
                        "proposal": "Resolve the recorded limit violations or missing limits before any new authorization.",
                        "status": "needs_process_review", "automatic_promotion": False})
    if coverage["has_uncovered_observation"]:
        lessons.append({"topic": "scenario_coverage", "evidence": coverage["outside_any_count"],
                        "proposal": "Design additional joint stress trajectories, then freeze and test them prospectively.",
                        "status": "proposed_not_validated", "automatic_promotion": False})
    if diagnostics["load_mae_mwh"] > 0 or diagnostics["spread_mae_cny_per_mwh"] > 0:
        lessons.append({"topic": "forecast_information", "evidence": "forecast and outcome differ",
                        "proposal": "Test an additional as-of-available input or forecast against the same frozen policy.",
                        "status": "proposed_not_validated", "automatic_promotion": False})
    if executed is not None and execution_checks["changed_hour_count"]:
        lessons.append({"topic": "execution_difference", "evidence": execution_checks["changed_hour_count"],
                        "proposal": "Reconcile the declared choice with provided execution records and their sources.",
                        "status": "needs_reconciliation", "automatic_promotion": False})
    begin, end = _period_bounds(context["period_type"], context["period"])
    result = {"schema_version": "risk-review-1", "scope": "synthetic", "status": "research_only",
              "period_type": context["period_type"], "period": context["period"],
              "portfolio_id": context["portfolio_id"], "delivery_start": begin.isoformat(),
              "delivery_end": end.isoformat(), "report_hash": report["report_hash"],
              "decision_hash": decision["decision_hash"], "actuals_hash": digest(actuals),
              "decision_context": {"origin": context["origin"], "selected_at": decision["selected_at"],
                                   "profile_id": decision["profile_id"], "actor": decision["actor"],
                                   "reason": decision["reason"], "input_snapshot_id": context["input_snapshot_id"],
                                   "portfolio_state_id": context["portfolio_state_id"], "report_id": report["report_id"]},
              "actuals_available_time": actuals["available_time"],
              "review_data_available_time": known_at.isoformat(),
              "execution_available_time": executed["available_time"] if executed else None,
              "historical_evidence_available_time": historical["available_time"] if historical else None,
              "execution_hash": digest(execution) if execution is not None else None,
              "execution_status": execution_checks["status"], "execution_checks": execution_checks,
              "execution_outcome": ({"cost_cny": costs[-1][1],
                                     "incremental_gain_cny": baseline_cost["total_cost_cny"] - costs[-1][1],
                                     "change_vs_chosen_cny": costs[-1][1] - chosen["cost_cny"]}
                                    if executed is not None else None),
              "chosen_outcome": chosen, "baseline_outcome": outcome(baseline),
              "ex_ante_references": references, "hindsight_best": hindsight,
              "hindsight_status": "available" if hindsight is not None else "unavailable_no_frozen_admissible_candidates",
              "admissible_outcomes": frozen_outcomes, "cost_bridge": bridge,
              "forecast_diagnostics": diagnostics, "scenario_coverage": coverage, "lessons": lessons,
              "process_integrity": {"hashes_scope_and_limits": "verified",
                                    "choice_admissibility": decision["admissibility_status"],
                                    "decision_record_type": record_type,
                                    "choice_timing": "declared_within_window",
                                    "source_identity_and_timestamps": "not_independently_authenticated"},
              "evaluation_boundaries": [
                  "Hindsight chooses only among the frozen admissible candidates; it is not a global optimum or EVPI.",
                  "A hindsight gap alone does not show the original decision process was wrong.",
                  "Reference policies were chosen before outcomes; this review does not establish future superiority.",
                  "Cost bridge is fixed-order and descriptive; components are not independent causal effects.",
                  "Scenario envelope checks are marginal, not joint distribution or probability calibration.",
                  "Execution inputs and historical choice timestamps are caller declarations, not verified platform evidence.",
                  "All costs use the same frozen synthetic rule, not certified market settlement."]}
    result["review_id"] = "review-" + digest({key: result[key] for key in (
        "portfolio_id", "period_type", "period", "report_hash", "decision_hash", "actuals_hash", "execution_hash")})[:24]
    return _seal(result, "review_hash")


def _experiment_time(value, field):
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            value = date.fromisoformat(value).isoformat() + "T00:00:00+08:00"
        except ValueError as exc:
            raise ValidationError("EXPERIMENT_TIME", "invalid " + field) from exc
    return parse_time(value)


def register_experiment(proposal, reviews):
    """Freeze a proposed future experiment; never turn in-sample review into validation."""
    _object(proposal, "proposal")
    if not isinstance(reviews, list) or not reviews:
        raise ValidationError("EXPERIMENT_REVIEWS", "at least one sealed review is required")
    for field in ("hypothesis", "change", "metric", "baseline"):
        _text(proposal.get(field), field)
    acceptance = proposal.get("acceptance")
    if not isinstance(acceptance, (dict, str)) or not acceptance:
        raise ValidationError("EXPERIMENT_ACCEPTANCE", "explicit acceptance criteria are required")
    candidate_hash = proposal.get("frozen_candidate_hash")
    if not isinstance(candidate_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", candidate_hash):
        raise ValidationError("EXPERIMENT_CANDIDATE", "frozen_candidate_hash must be a SHA256 digest")
    registered = parse_time(proposal.get("registered_at"))
    begin = _experiment_time(proposal.get("test_start"), "test_start")
    end = _experiment_time(proposal.get("test_end"), "test_end")
    if end <= begin:
        raise ValidationError("EXPERIMENT_WINDOW", "test_end must follow test_start")
    seen = set()
    availability = []
    delivery_ends = []
    for review in reviews:
        _check_seal(review, "review_hash")
        if review.get("scope") != "synthetic" or review.get("status") != "research_only":
            raise ValidationError("EXPERIMENT_SCOPE", "only synthetic research reviews are supported")
        key = (review.get("portfolio_id"), review.get("period_type"), review.get("period"))
        if key in seen:
            raise ValidationError("EXPERIMENT_DUPLICATE", "one review revision per portfolio and period is required")
        seen.add(key)
        delivery_start, delivery_end = _period_bounds(review["period_type"], review["period"])
        if (parse_time(review.get("delivery_start")) != delivery_start or
                parse_time(review.get("delivery_end")) != delivery_end):
            raise ValidationError("EXPERIMENT_PERIOD", "review delivery interval is inconsistent")
        actual_at = parse_time(review.get("actuals_available_time"))
        known_at = parse_time(review.get("review_data_available_time"))
        execution_at = review.get("execution_available_time")
        historical_at = review.get("historical_evidence_available_time")
        if (actual_at < delivery_end or known_at < actual_at or
                (execution_at and known_at < parse_time(execution_at)) or
                (historical_at and known_at < parse_time(historical_at))):
            raise ValidationError("EXPERIMENT_AVAILABILITY", "review availability is inconsistent")
        availability.append(known_at)
        delivery_ends.append(delivery_end)
    if registered < max(availability):
        raise ValidationError("EXPERIMENT_BACKDATE", "registration cannot precede the data used for review")
    if begin <= max([registered] + availability + delivery_ends):
        raise ValidationError("EXPERIMENT_LEAKAGE", "test period must start after registration and all reviewed information")
    result = {"schema_version": "risk-review-1", "scope": "synthetic",
              "status": "proposed_not_validated", "proposal": copy.deepcopy(proposal),
              "test_start": begin.isoformat(), "test_end": end.isoformat(),
              "test_interval_convention": "[start,end)",
              "review_ids": [r["review_id"] for r in reviews],
              "review_hashes": [r["review_hash"] for r in reviews],
              "latest_review_data_available_time": max(availability).isoformat(),
              "automatic_promotion": False,
              "timestamp_evidence": "caller_declared_not_authenticated"}
    result["experiment_id"] = "experiment-" + digest(result)[:24]
    return _seal(result, "experiment_hash")
