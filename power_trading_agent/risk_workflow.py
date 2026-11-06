"""File workflows for human risk choices and information-bounded review."""
import calendar
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

from .contracts import SHANGHAI, ValidationError, digest, hours, parse_time, write_json
from .data import apply_customer_events, build_snapshot
from .portfolio import Ledger


def period_hours(period_type, period):
    if period_type == "day":
        return hours(period)
    if period_type != "month":
        raise ValidationError("PERIOD_TYPE", "period_type must be day or month")
    try:
        start = date.fromisoformat(period + "-01")
        if start.strftime("%Y-%m") != period:
            raise ValueError("month format")
    except (ValueError, TypeError) as exc:
        raise ValidationError("PERIOD", "month must be YYYY-MM") from exc
    result = []
    for day in range(1, calendar.monthrange(start.year, start.month)[1] + 1):
        result.extend(hours(date(start.year, start.month, day).isoformat()))
    return result


def context_from_bundle(bundle, target_date, origin):
    """Adapt a v1.1 daily bundle; never copy actuals into the risk workspace."""
    if bundle.get("scope") != "synthetic":
        raise ValidationError("SCOPE", "only explicitly synthetic adapters are implemented")
    snapshot = build_snapshot(bundle, target_date, origin)
    with Ledger(":memory:") as ledger:
        for event in bundle.get("events", []):
            if event.get("portfolio_id") != bundle["portfolio_id"]:
                raise ValidationError("SCOPE", "events mix portfolios")
            ledger.record_event(event)
        state = ledger.state(bundle["portfolio_id"], target_date, origin)
    evidence = [{"id": r["source"] + ":" + r["record_id"] + ":" + str(r["revision"]),
                 "available_time": r["available_time"], "source_hash": r["source_hash"]}
                for r in snapshot["record_refs"]]
    evidence.extend({"id": e["event_id"] + ":" + str(e["revision"]),
                     "available_time": e["available_time"], "source_hash": e["content_hash"]}
                    for e in state["event_refs"])
    return {"schema_version": "risk-review-1", "scope": "synthetic",
            "portfolio_id": bundle["portfolio_id"], "period_type": "day", "period": target_date,
            "origin": origin, "hours": snapshot["hours"], "f": apply_customer_events(snapshot, state),
            "da": snapshot["da"], "rt": snapshot["rt"], "holdings": state["holdings_mwh"],
            "holding_cost": state["holding_cost_cny"], "rule": bundle["rule"],
            "input_snapshot_id": snapshot["input_snapshot_id"], "portfolio_state_id": state["state_id"],
            "evidence": evidence}


def synthetic_context(period_type="day", period=None):
    """Invented known-only decision packet; daily and monthly origins are distinct."""
    period = period or ("2026-11-05" if period_type == "day" else "2026-11")
    times = period_hours(period_type, period)
    first = parse_time(times[0])
    origin = (first - timedelta(hours=12)).isoformat()
    f, da, rt = [], [], []
    for i in range(len(times)):
        h, day = i % 24, i // 24
        demand = 20 + 5 * math.sin((h - 7) * math.pi / 12) + math.cos(day / 4)
        price = 300 + 50 * math.sin((h - 8) * math.pi / 12) + 10 * math.cos(day / 5)
        spread = 25 * math.sin((h + 2) * math.pi / 8)
        f.append(round(demand, 6)); da.append(round(price, 6)); rt.append(round(price + spread, 6))
    known = {"f": f, "da": da, "rt": rt}
    holdings = [8.0] * len(times)
    rule = {"rule_id": "synthetic-physical-forward-v1", "scope": "synthetic", "price_basis": "user_side",
            "currency": "CNY", "deviation_fee_cny_per_mwh": 3, "source": "Invented fee, not a formal assessment rule",
            "valid_from": times[0][:10], "valid_to": times[-1][:10]}
    return {"schema_version": "risk-review-1", "scope": "synthetic", "portfolio_id": "research-portfolio",
            "period_type": period_type, "period": period, "origin": origin, "hours": times,
            "f": f, "da": da, "rt": rt, "holdings": holdings, "holding_cost": [2400.0] * len(times),
            "rule": rule, "input_snapshot_id": digest(known), "portfolio_state_id": digest(holdings),
            "evidence": [{"id": "invented-known-curves", "available_time": origin, "source_hash": digest(known)}]}


def synthetic_actuals(context):
    """Separate scoring fixture, intentionally outside some frozen stress envelopes."""
    l, da, rt = [], [], []
    for i, forecast in enumerate(context["f"]):
        h, day = i % 24, i // 24
        load = forecast * (1 + 0.08 * math.cos((h + day) / 3))
        actual_da = context["da"][i] + 12 * math.sin((h + day) / 5)
        actual_rt = context["rt"][i] - 35 * math.sin((h + 2) * math.pi / 8)
        if day % 9 == 0 and 18 <= h <= 20:
            actual_rt += 700
            load *= 1.55
        l.append(round(load, 6)); da.append(round(actual_da, 6)); rt.append(round(actual_rt, 6))
    end = parse_time(context["hours"][-1]) + timedelta(hours=7)
    return {"hours": list(context["hours"]), "l": l, "da": da, "rt": rt,
            "price_basis": "user_side", "energy_unit": "MWh", "price_unit": "CNY/MWh",
            "available_time": end.isoformat(), "source": "invented-post-delivery-labels"}


def illustrative_profiles(context):
    """Explicit demonstration limits, never the defaults for a user's input."""
    from .risk import default_profiles
    profiles = default_profiles()
    days = len(context["hours"]) // 24
    rows = [
        (35000, 35, 400, 1500, 25, 450000, 500, 500, 0.05),
        (70000, 45, 650, 3000, 35, 700000, 3000, 3000, 0.10),
        (150000, 60, 1000, 6000, 50, 1000000, 15000, 15000, 0.20),
    ]
    keys = ["max_price_shock_cost_cny", "max_hourly_deviation_mwh", "max_daily_deviation_mwh",
            "max_assessment_fee_cny", "max_forecast_unhedged_mwh", "max_gross_outflow_cny",
            "max_incremental_loss_cny", "max_daily_incremental_loss_cny", "max_abs_k_deviation"]
    period_totals = {"max_price_shock_cost_cny", "max_assessment_fee_cny", "max_gross_outflow_cny", "max_incremental_loss_cny"}
    for profile, row in zip(profiles, rows):
        profile["limits"] = {k: v * days if k in period_totals else v for k, v in zip(keys, row)}
    return profiles


def _new_output(output):
    path = Path(output)
    if path.exists():
        raise ValidationError("OUTPUT_EXISTS", "use a new output directory to retain earlier versions")
    path.mkdir(parents=True)
    return path


def create_risk_workspace(context, output, profiles=None, stress_config=None, candidate_config=None):
    from .risk import assess_risk, default_profiles
    from .dashboard import risk_html, risk_markdown
    report = assess_risk(context, profiles, stress_config, candidate_config)
    path = _new_output(output)
    write_json(path / "context.json", context)
    write_json(path / "risk.json", report)
    write_json(path / "profiles-template.json", default_profiles())
    (path / "risk.html").write_text(risk_html(report), encoding="utf-8")
    (path / "risk.md").write_text(risk_markdown(report), encoding="utf-8")
    return report


def create_decision_workspace(report, request, output):
    from .review import record_decision, record_historical_decision
    required = {"profile_id", "plan_id", "actor", "reason", "selected_at"}
    allowed = required | {"report_hash", "historical_evidence"}
    if not isinstance(request, dict) or not required <= set(request) or set(request) - allowed:
        raise ValidationError("DECISION_REQUEST", "decision request has missing or unsupported fields")
    if request.get("report_hash", report["report_hash"]) != report["report_hash"]:
        raise ValidationError("STALE_REPORT", "selection request refers to another risk report")
    args = [report, request["profile_id"], request["plan_id"], request["actor"], request["reason"], request["selected_at"]]
    if "historical_evidence" in request:
        decision = record_historical_decision(*args, evidence=request["historical_evidence"])
    else:
        decision = record_decision(*args)
    path = _new_output(output)
    write_json(path / "decision.json", decision)
    return decision


def create_review_workspace(report, decision, actuals, output, execution=None):
    from .review import review_decision
    from .dashboard import review_html, review_markdown
    review = review_decision(report, decision, actuals, execution)
    path = _new_output(output)
    write_json(path / "review.json", review)
    write_json(path / "actuals.json", actuals)
    write_json(path / "decision.json", decision)
    if execution is not None:
        write_json(path / "execution.json", execution)
    (path / "review.html").write_text(review_html(review), encoding="utf-8")
    (path / "review.md").write_text(review_markdown(review), encoding="utf-8")
    return review


def demo_workspaces(output, period_type="day", period=None, include_review=False):
    context = synthetic_context(period_type, period)
    root = _new_output(output)
    report = create_risk_workspace(context, root / "risk", illustrative_profiles(context))
    result = {"scope": "synthetic", "status": "research_only", "period_type": period_type,
              "period": context["period"], "risk_report": str(root / "risk/risk.html"),
              "scenario_count": len(report["scenarios"]["items"]), "plan_count": len(report["plans"]),
              "limits_source": "illustrative_example_not_operating_limits"}
    if include_review:
        # This explicit demo fixture is NOT a user's choice or a live automatic policy.
        profile = report["profile_results"][1]
        plan_id = profile["reference_choices"]["central_min_cost"]
        if plan_id is None:
            raise ValidationError("DEMO_LIMITS", "illustrative steady limits admitted no plan")
        request = {"profile_id": profile["profile_id"], "plan_id": plan_id, "actor": "synthetic-demo-operator",
                   "reason": "Invented demonstration choice, not an actual user instruction",
                   "selected_at": (parse_time(context["origin"]) + timedelta(minutes=10)).isoformat(),
                   "report_hash": report["report_hash"]}
        decision = create_decision_workspace(report, request, root / "choice")
        actuals = synthetic_actuals(context)
        review = create_review_workspace(report, decision, actuals, root / "review")
        result["review_report"] = str(root / "review/review.html")
        result["review_id"] = review["review_id"]
    write_json(root / "workspace-summary.json", result)
    return result
