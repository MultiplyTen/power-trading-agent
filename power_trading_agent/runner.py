"""Single-writer research coordinator: freeze, compute, record, then score."""
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

from . import __version__
from .contracts import ValidationError, digest, number, parse_time, write_json
from .data import actual_curves, apply_customer_events, build_snapshot
from .economics import evaluate_plans, make_plans, replay_metrics, settlement
from .portfolio import Ledger


def source_hash():
    root = Path(__file__).parent
    return digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.py"))})


def validate_bundle(bundle):
    if not isinstance(bundle, dict) or bundle.get("scope") != "synthetic":
        raise ValidationError("UNSUPPORTED_SCOPE", "v1.1 runner accepts explicitly synthetic research bundles only")
    if bundle.get("schema_version") != "1.1":
        raise ValidationError("SCHEMA_VERSION", "schema_version must be 1.1")
    if not isinstance(bundle.get("days"), list) or not bundle["days"]:
        raise ValidationError("MISSING_DAYS", "replay days are required")
    rule = bundle.get("rule", {})
    try:
        begin, end = date.fromisoformat(rule["valid_from"]), date.fromisoformat(rule["valid_to"])
    except (ValueError, TypeError, KeyError) as exc:
        raise ValidationError("RULE_VALIDITY", "rule valid_from/valid_to are required dates") from exc
    if not rule.get("source"):
        raise ValidationError("RULE_SOURCE", "rule source is required")
    previous = None
    for day in bundle["days"]:
        try:
            current = date.fromisoformat(day["target_date"])
            parse_time(day["origin"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError("INVALID_DAY", "target_date and aware origin required") from exc
        if previous is not None and current <= previous:
            raise ValidationError("DAY_ORDER", "days must be unique and increasing")
        if not begin <= current <= end:
            raise ValidationError("RULE_EXPIRED", "rule does not cover target date")
        previous = current
    if bundle.get("risk_budget_cny") is not None:
        number(bundle["risk_budget_cny"], "risk_budget_cny", 0)
    digest(bundle)


def stress_scenarios(f, da, rt):
    items = []
    for name, load_factor, spread_shift in (("central", 1, 0), ("high_load_high_rt", 1.15, 100),
                                             ("low_load_low_rt", 0.85, -100)):
        items.append({"scenario_id": name, "l": [v * load_factor for v in f],
                      "da": list(da), "rt": [v + spread_shift for v in rt]})
    return {"scenario_set_id": digest(items), "kind": "stress",
            "calibration_status": "not_calibrated", "items": items}


def evaluate_day(bundle, day, ledger):
    """Decision path has no access to actual_curves or target-day scoring labels."""
    snapshot = build_snapshot(bundle, day["target_date"], day["origin"])
    state = ledger.state(bundle["portfolio_id"], day["target_date"], day["origin"])
    f = apply_customer_events(snapshot, state)
    plans = make_plans(f, snapshot["da"], snapshot["rt"], bundle["strategy"])
    scenarios = stress_scenarios(f, snapshot["da"], snapshot["rt"])
    context = {"input_snapshot_id": snapshot["input_snapshot_id"], "state_id": state["state_id"],
               "f_after_events": f, "rule_hash": digest(bundle["rule"]),
               "strategy_hash": digest(bundle["strategy"]), "scenario_set_id": scenarios["scenario_set_id"],
               "risk_budget_cny": bundle.get("risk_budget_cny"), "version": __version__}
    evaluated = evaluate_plans(plans, scenarios, state["holdings_mwh"], state["holding_cost_cny"],
                               bundle["rule"], bundle.get("risk_budget_cny"))
    for plan in evaluated["plans"]:
        plan["plan_hash"] = digest({"context": context, "plan": plan})
        plan["plan_id"] = plan["name"] + "-" + plan["plan_hash"][:16]
    return {"target_date": day["target_date"], "origin": day["origin"], "status": "research_only",
            "decision_hash": digest(context), "snapshot": snapshot, "portfolio_state": state,
            "f": f, "scenario_set": scenarios, "plans": evaluated["plans"],
            "no_automatic_selection": True}


def _score(decision, bundle, day):
    # Called only after the complete decision object (including hashes) exists.
    labels = actual_curves(bundle, day["target_date"])
    state = decision["portfolio_state"]
    scores = {}
    for plan in decision["plans"]:
        scores[plan["name"]] = settlement(plan["q"], labels["l"], labels["da"], labels["rt"],
                                          state["holdings_mwh"], state["holding_cost_cny"], bundle["rule"])
    return {"actuals": labels, "strategies": scores, "group": day.get("group", "unclassified")}


def _report(result):
    lines = ["# 电力交易研究回放 / Power Trading Research Replay", "",
             "**合成研究数据 / Synthetic research only — v1.1.0**", "",
             "不代表真实广东结算、实际收益或平台申报。No live execution or certified settlement.", "",
             "成本单位 CNY；电量 MWh。增益=基准成本−候选成本。Gain = baseline cost minus candidate cost.", "",
             "情景为压力假设，未校准概率；不输出期望收益或 CVaR。Stress scenarios have no probability claim.", "",
             "| 策略 / Strategy | 天数 / Days | 增量合计 / Gain | 最差日 / Worst day | 最大回撤 / Drawdown |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for name, metrics in result["metrics"].items():
        lines.append("| {} | {} | {:.2f} | {:.2f} | {:.2f} |".format(
            name, metrics["days"], metrics["total_incremental_gain_cny"],
            metrics["worst_day_gain_cny"], metrics["max_drawdown_cny"]))
    lines += ["", "## 每日结果 / Daily outcomes", "",
              "| 日期 / Date | 分组 / Group | 策略 / Strategy | 实现增益 / Realized gain | 压力检查 / Stress check |",
              "| --- | --- | --- | ---: | --- |"]
    for run in result["days"]:
        scoring = run["scoring"]
        baseline = scoring["strategies"]["baseline"]["total_cost_cny"]
        for plan in run["plans"]:
            gain = baseline - scoring["strategies"][plan["name"]]["total_cost_cny"]
            lines.append("| {} | {} | {} | {:.2f} | {} |".format(
                run["target_date"], scoring["group"], plan["name"], gain, plan["risk_status"]))
    lines += ["", "## 解释与边界 / Interpretation", "",
              "- 基准为同一 F 的 k=1；固定持仓和费用。Baseline uses identical F, holdings and fees.",
              "- 未成交意图不计入持仓，客户事件仅影响对应客户的 F。Intents are not filled trades.",
              "- 压力检查通过不代表可实盘采用；风险预算缺失时标为待补。No automatic plan selection.",
              "- 示例预测仅使用此前可得的七天数据；本次成绩不证明真实预测能力。Synthetic baseline only.",
              "- 本报告比较固定预测下的策略；未宣称完成预测模型或 LLM 优劣评测。",
              "  This run isolates strategy comparison, not model or LLM performance.",
              "- 分组统计见 results.json；每组保留样本量。Group sample counts are in results.json.",
              "- input.json、results.json 与 manifest.json 保存冻结输入、情景和校验值。", ""]
    return "\n".join(lines)


def run_bundle(bundle, output_dir, resume=False):
    validate_bundle(bundle)
    out = Path(output_dir)
    input_hash = digest(bundle)
    meta = {"version": __version__, "input_hash": input_hash, "source_hash": source_hash(),
            "scope": "synthetic", "business_ready": False, "production_approved": False, "deployed": False}
    if resume:
        if not out.is_dir() or json.loads((out / "run_meta.json").read_text()) != meta:
            raise ValidationError("RESUME_MISMATCH", "resume requires unchanged input and runtime sources")
        if digest(json.loads((out / "input.json").read_text(encoding="utf-8"))) != input_hash:
            raise ValidationError("RESUME_MISMATCH", "archived input differs from the run input hash")
    else:
        if out.exists():
            raise ValidationError("OUTPUT_EXISTS", "choose a new output directory or use resume")
        out.mkdir(parents=True)
        write_json(out / "input.json", bundle)
        write_json(out / "run_meta.json", meta)
    completed = []
    with Ledger(out / "ledger.sqlite3") as ledger:
        for event in bundle.get("events", []):
            if event.get("portfolio_id") != bundle["portfolio_id"]:
                raise ValidationError("SCOPE_MISMATCH", "event belongs to another portfolio")
            ledger.record_event(event)
        for day in bundle["days"]:
            task_id = bundle["portfolio_id"] + "/day-ahead/" + day["target_date"]
            try:
                previous = ledger.get_run(task_id)
            except ValidationError as exc:
                if exc.code != "unknown_task":
                    raise
                previous = None
            if previous and previous["status"] == "completed" and previous["input_hash"] == input_hash:
                if digest(previous["result"]) != previous["result_hash"]:
                    raise ValidationError("LEDGER_HASH", "saved task result does not match its hash")
                completed.append(previous["result"])
                continue
            generation = ledger.start_run(task_id, input_hash)
            decision = evaluate_day(bundle, day, ledger)
            decision["scoring"] = _score(decision, bundle, day)
            decision["task_id"], decision["generation"] = task_id, generation
            ledger.finish_run(task_id, generation, input_hash, decision)
            completed.append(decision)
    names = [p["name"] for p in completed[0]["plans"]]
    metrics = {}
    for name in names:
        rows = [{"date": d["target_date"], "group": d["scoring"]["group"],
                 "baseline_cost_cny": d["scoring"]["strategies"]["baseline"]["total_cost_cny"],
                 "candidate_cost_cny": d["scoring"]["strategies"][name]["total_cost_cny"]} for d in completed]
        metrics[name] = replay_metrics(rows)
    result = dict(meta, portfolio_id=bundle["portfolio_id"], days=completed, metrics=metrics,
                  evaluation_axis="strategy_with_fixed_forecasts", status="research_only")
    write_json(out / "results.json", result)
    (out / "report.md").write_text(_report(result), encoding="utf-8")
    with (out / "hourly.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["target_date", "hour", "strategy", "F_MWh", "Q_MWh", "L_MWh", "DA_CNY_MWh",
                         "RT_CNY_MWh", "H_MWh", "intent_MWh", "cost_CNY", "plan_hash"])
        for d in completed:
            actual = d["scoring"]["actuals"]
            state = d["portfolio_state"]
            for p in d["plans"]:
                costs = d["scoring"]["strategies"][p["name"]]["hourly_cost_cny"]
                for h in range(24):
                    writer.writerow([d["target_date"], h, p["name"], d["f"][h], p["q"][h], actual["l"][h],
                                     actual["da"][h], actual["rt"][h], state["holdings_mwh"][h],
                                     state["intents_mwh"][h], costs[h], p["plan_hash"]])
    manifest = {"algorithm": "sha256", "scope": "synthetic", "version": __version__,
                "mutable_ledger": "ledger.sqlite3", "files": {}}
    for name in ("input.json", "run_meta.json", "results.json", "report.md", "hourly.csv"):
        manifest["files"][name] = hashlib.sha256((out / name).read_bytes()).hexdigest()
    write_json(out / "manifest.json", manifest)
    verify_output(out)
    return {"status": "research_only", "days": len(completed), "output": str(out),
            "metrics": metrics, "input_hash": input_hash}


def verify_output(output_dir):
    """Artifact integrity and independent hourly-to-daily cost reconciliation."""
    out = Path(output_dir)
    manifest = json.loads((out / "manifest.json").read_text())
    expected = {"input.json", "run_meta.json", "results.json", "report.md", "hourly.csv"}
    if set(manifest.get("files", {})) != expected:
        raise ValidationError("MANIFEST_FILES", "manifest file set differs from contract")
    for name, value in manifest["files"].items():
        if hashlib.sha256((out / name).read_bytes()).hexdigest() != value:
            raise ValidationError("HASH_MISMATCH", "artifact changed: " + name)
    result = json.loads((out / "results.json").read_text())
    archived = json.loads((out / "input.json").read_text(encoding="utf-8"))
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    if (digest(archived) != meta.get("input_hash") or result.get("input_hash") != meta.get("input_hash")
            or result.get("source_hash") != meta.get("source_hash") or result.get("version") != meta.get("version")):
        raise ValidationError("INPUT_BINDING", "input, metadata and result provenance disagree")
    expected_rows = {}
    fee = number(archived["rule"]["deviation_fee_cny_per_mwh"], "fee", 0)
    for day in result["days"]:
        actual = day["scoring"]["actuals"]
        state = day["portfolio_state"]
        for plan in day["plans"]:
            for h in range(24):
                key = day["target_date"], plan["name"], h
                if key in expected_rows:
                    raise ValidationError("DUPLICATE_RESULT", "result contains duplicate plan/day")
                q, l = plan["q"][h], actual["l"][h]
                cost = number(state["holding_cost_cny"][h] + (q - state["holdings_mwh"][h]) * actual["da"][h]
                              + (l - q) * actual["rt"][h] + abs(q - l) * fee, "independent_cost")
                expected_rows[key] = {"F_MWh": day["f"][h], "Q_MWh": q, "L_MWh": l,
                                      "DA_CNY_MWh": actual["da"][h], "RT_CNY_MWh": actual["rt"][h],
                                      "H_MWh": state["holdings_mwh"][h], "intent_MWh": state["intents_mwh"][h],
                                      "cost_CNY": cost, "plan_hash": plan["plan_hash"]}
                saved = number(day["scoring"]["strategies"][plan["name"]]["hourly_cost_cny"][h], "saved_cost")
                if abs(saved - cost) > 0.00001:
                    raise ValidationError("RECONCILIATION", "saved cost differs from independent formula")
    totals, seen = {}, set()
    with (out / "hourly.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                key = row["target_date"], row["strategy"], int(row["hour"])
            except (ValueError, KeyError) as exc:
                raise ValidationError("CSV_KEY", "invalid CSV hour/key") from exc
            if key not in expected_rows or key in seen:
                raise ValidationError("CSV_KEY", "duplicate or unexpected CSV hour/key")
            seen.add(key)
            for field, value in expected_rows[key].items():
                if field == "plan_hash":
                    if row.get(field) != value:
                        raise ValidationError("PLAN_BINDING", "CSV references wrong plan hash")
                else:
                    try:
                        observed = number(float(row[field]), field)
                    except (KeyError, ValueError, TypeError) as exc:
                        raise ValidationError("CSV_NUMBER", "invalid CSV numeric value") from exc
                    if abs(observed - number(value, field)) > 0.00001:
                        raise ValidationError("RECONCILIATION", "CSV value differs from result: " + field)
            daily_key = key[:2]
            totals[daily_key] = number(totals.get(daily_key, 0) + float(row["cost_CNY"]), "daily_cost")
    if seen != set(expected_rows):
        raise ValidationError("CSV_KEY", "CSV hour/key coverage is incomplete")
    for day in result["days"]:
        for name, score in day["scoring"]["strategies"].items():
            key = day["target_date"], name
            if abs(totals[key] - number(score["total_cost_cny"], "total_cost")) > 0.00001:
                raise ValidationError("RECONCILIATION", "hourly/daily cost mismatch")
    return {"verified": True, "files": len(expected), "days": len(result["days"])}
