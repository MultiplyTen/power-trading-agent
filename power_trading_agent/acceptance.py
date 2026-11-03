"""Independent offline acceptance cases; oracle expectations never enter services.

This evaluates the deterministic v1.1 services, not a hosted language model.
Fixtures are synthetic and no real market rule is certified by these checks.
"""
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .contracts import ValidationError, hours
from .data import build_snapshot
from .economics import evaluate_plans, make_plans, replay_metrics, settlement
from .portfolio import Ledger

TARGET = "2026-10-02"
ORIGIN = "2026-10-01T12:00:00+08:00"
EARLY = "2026-10-01T11:00:00+08:00"
LATE = "2026-10-01T13:00:00+08:00"
RULE = {
    "rule_id": "acceptance-synthetic-v1", "scope": "synthetic",
    "price_basis": "user_side", "currency": "CNY",
    "deviation_fee_cny_per_mwh": 0,
}


@dataclass(frozen=True)
class Case:
    case_id: str
    group: str
    description: str
    expected: str
    check: Callable


def _equal(actual, expected):
    if actual != expected:
        raise AssertionError("expected {!r}; observed {!r}".format(expected, actual))


def _near(actual, expected, tolerance=1e-7):
    if abs(actual - expected) > tolerance:
        raise AssertionError("expected {}; observed {}".format(expected, actual))


def _reject(call):
    try:
        call()
    except ValidationError:
        return
    raise AssertionError("invalid input was accepted")


def _bundle():
    records = []
    for metric, value, unit in (("load_forecast", 10, "MWh"),
                                ("da_forecast", 100, "CNY/MWh"),
                                ("rt_forecast", 200, "CNY/MWh")):
        for hour, target_time in enumerate(hours(TARGET)):
            records.append({
                "record_id": "{}-{}".format(metric, hour), "revision": 1,
                "source": "independent-synthetic-fixture", "available_time": EARLY,
                "issue_time": "2026-10-01T10:00:00+08:00", "received_at": EARLY,
                "target_time": target_time, "metric": metric, "value": value,
                "unit": unit, "price_basis": "user_side",
            })
    return {"portfolio_id": "portfolio-a", "records": records}


def _event(kind="trade", **overrides):
    event = {
        "portfolio_id": "portfolio-a", "event_id": "event-a", "revision": 1,
        "kind": kind, "available_time": EARLY, "start": hours(TARGET)[0],
        "end": "2026-10-03T00:00:00+08:00", "status": "confirmed",
        "source": "independent-synthetic-fixture", "hourly_mwh": 2,
    }
    if kind == "trade":
        event["price_cny_per_mwh"] = 80
    if kind == "customer_event":
        event.pop("hourly_mwh")
        event.update(customer_id="customer-a", load_multiplier=0)
    event.update(overrides)
    return event


def _ledger_check(check):
    # tempfile honors the caller's task-scoped TMPDIR.
    with tempfile.TemporaryDirectory(prefix="pta-acceptance-", dir=os.environ.get("TMPDIR")) as directory:
        with Ledger(Path(directory) / "ledger.sqlite3") as ledger:
            check(ledger)


def _state(ledger, as_of=ORIGIN):
    return ledger.state("portfolio-a", TARGET, as_of)


def _plans():
    return [
        {"name": "baseline", "k": [1] * 24, "q": [10] * 24},
        {"name": "candidate", "k": [1.1] * 24, "q": [11] * 24},
    ]


def _scenarios(kind="stress"):
    items = []
    for scenario_id, first_rt, weight in (("loss100", 0, 0.05),
                                           ("loss20", 80, 0.10),
                                           ("flat", 100, 0.85)):
        item = {"scenario_id": scenario_id, "l": [10] * 24,
                "da": [100] * 24, "rt": [first_rt] + [100] * 23}
        if kind == "probabilistic":
            item["weight"] = weight
        items.append(item)
    return {"kind": kind, "scenario_set_id": "independent-case-set",
            "calibration_status": "validated" if kind == "probabilistic" else "not_calibrated",
            "items": items}


def _evaluate(scenarios=None, budget=None):
    return evaluate_plans(_plans(), scenarios or _scenarios(), [0] * 24,
                          [0] * 24, RULE, budget)


def _candidate(result):
    return next(plan for plan in result["plans"] if plan["name"] == "candidate")


def build_cases():
    """Return independent cases with human-readable, fixed oracle expectations."""
    cases = []

    def add(case_id, group, description, expected, check):
        cases.append(Case(case_id, group, description, expected, check))

    def snapshot_complete():
        result = build_snapshot(_bundle(), TARGET, ORIGIN)
        _equal(result["f"], [10] * 24)
        _equal(result["da"], [100] * 24)
        _equal(result["rt"], [200] * 24)
    add("D01", "data", "Complete day / 完整目标日", "24 F=10, DA=100, RT=200", snapshot_complete)

    def late_revision():
        bundle = _bundle()
        revised = dict(bundle["records"][0], revision=2, value=999,
                       available_time=LATE, received_at=LATE)
        bundle["records"].append(revised)
        _equal(build_snapshot(bundle, TARGET, ORIGIN)["f"][0], 10)
        _equal(build_snapshot(bundle, TARGET, LATE)["f"][0], 999)
    add("D02", "data", "As-of revision / 截点后修订隔离", "10 before arrival; 999 at arrival", late_revision)

    def boundary_revision():
        bundle = _bundle()
        bundle["records"].append(dict(bundle["records"][0], revision=2, value=12,
                                       available_time=ORIGIN, received_at=ORIGIN))
        _equal(build_snapshot(bundle, TARGET, ORIGIN)["f"][0], 12)
    add("D03", "data", "Inclusive cutoff / 截点等时接纳", "F[0]=12", boundary_revision)

    def missing():
        bundle = _bundle()
        bundle["records"].pop()
        _reject(lambda: build_snapshot(bundle, TARGET, ORIGIN))
    add("D04", "data", "Missing interval / 缺点", "ValidationError", missing)

    def mutation_rejected(field, value, index=0):
        bundle = _bundle()
        bundle["records"][index][field] = value
        _reject(lambda: build_snapshot(bundle, TARGET, ORIGIN))
    add("D05", "data", "Wrong energy unit / 功率电量混用", "ValidationError",
        lambda: mutation_rejected("unit", "MW"))
    add("D06", "data", "Wrong price basis / 节点用户侧混用", "ValidationError",
        lambda: mutation_rejected("price_basis", "nodal", 24))
    add("D07", "data", "Naive timestamp / 无时区时间", "ValidationError",
        lambda: mutation_rejected("available_time", "2026-10-01T11:00:00"))
    add("D08", "data", "Nonfinite load / 非有限值", "ValidationError",
        lambda: mutation_rejected("value", float("nan")))
    add("D09", "data", "Negative load / 负电量", "ValidationError",
        lambda: mutation_rejected("value", -1))

    def conflicting_record():
        bundle = _bundle()
        bundle["records"].append(dict(bundle["records"][0], value=11))
        _reject(lambda: build_snapshot(bundle, TARGET, ORIGIN))
    add("D10", "data", "Conflicting revision / 同版冲突", "ValidationError", conflicting_record)

    def actual_separation():
        bundle = _bundle()
        bundle["actuals"] = [{"target_time": hour, "l": 9999, "da": 9999, "rt": -9999}
                             for hour in hours(TARGET)]
        result = build_snapshot(bundle, TARGET, ORIGIN)
        _equal(result["f"], [10] * 24)
        _equal(result["da"], [100] * 24)
        _equal(result["rt"], [200] * 24)
    add("D11", "data", "Actuals isolation / 目标日实际值隔离", "Forecast curves unchanged", actual_separation)
    add("D12", "data", "Arrival chronology / 接收前不可得", "ValidationError",
        lambda: mutation_rejected("available_time", "2026-10-01T10:30:00+08:00"))

    def duplicate(ledger):
        _equal(ledger.record_event(_event()), True)
        _equal(ledger.record_event(_event()), False)
        _equal(_state(ledger)["holdings_mwh"], [2] * 24)
    add("P01", "portfolio", "Idempotent fill / 成交去重", "2 MWh/h, not 4", lambda: _ledger_check(duplicate))

    def conflict(ledger):
        ledger.record_event(_event())
        _reject(lambda: ledger.record_event(_event(hourly_mwh=3)))
    add("P02", "portfolio", "Conflicting fill / 同版成交冲突", "ValidationError", lambda: _ledger_check(conflict))

    def revise(ledger):
        ledger.record_event(_event())
        ledger.record_event(_event(revision=2, hourly_mwh=3))
        _equal(_state(ledger)["holdings_mwh"], [3] * 24)
        _equal(_state(ledger)["holding_cost_cny"], [240] * 24)
    add("P03", "portfolio", "Revised fill / 修订替代", "3 MWh/h; 240 CNY/h", lambda: _ledger_check(revise))

    def cancelled(ledger):
        ledger.record_event(_event())
        ledger.record_event(_event(revision=2, status="cancelled"))
        _equal(_state(ledger)["holdings_mwh"], [0] * 24)
    add("P04", "portfolio", "Cancelled fill / 撤销成交", "Zero holdings", lambda: _ledger_check(cancelled))

    def future(ledger):
        ledger.record_event(_event())
        ledger.record_event(_event(revision=2, hourly_mwh=3, available_time=LATE))
        _equal(_state(ledger)["holdings_mwh"], [2] * 24)
    add("P05", "portfolio", "Future fill revision / 未来成交修订", "2 MWh/h", lambda: _ledger_check(future))

    def pending(ledger):
        ledger.record_event(_event(status="pending"))
        _equal(_state(ledger)["holdings_mwh"], [0] * 24)
    add("P06", "portfolio", "Pending fill / 待确认成交", "Zero holdings", lambda: _ledger_check(pending))

    def intent(ledger):
        ledger.record_event(_event("intent", status="pending", hourly_mwh=5))
        _equal(_state(ledger)["holdings_mwh"], [0] * 24)
        _equal(_state(ledger)["intents_mwh"], [5] * 24)
    add("P07", "portfolio", "Intent separation / 采购意图分账", "Intent=5; holdings=0", lambda: _ledger_check(intent))

    def declaration(ledger):
        ledger.record_event(_event("declaration", hourly_mwh=8))
        _equal(_state(ledger)["holdings_mwh"], [0] * 24)
        _equal(_state(ledger)["declarations_mwh"], [8] * 24)
    add("P08", "portfolio", "Declaration separation / 申报分账", "Declaration=8; holdings=0", lambda: _ledger_check(declaration))

    def half_open(ledger):
        ledger.record_event(_event(start=hours(TARGET)[1], end=hours(TARGET)[2]))
        _equal(_state(ledger)["holdings_mwh"], [0, 2] + [0] * 22)
    add("P09", "portfolio", "Half-open interval / 时段左闭右开", "Only hour 01 contains 2 MWh", lambda: _ledger_check(half_open))
    add("P10", "portfolio", "Invalid volume / 负成交量", "ValidationError",
        lambda: _ledger_check(lambda ledger: _reject(lambda: ledger.record_event(_event(hourly_mwh=-1)))))

    def customer_pending(ledger):
        ledger.record_event(_event("customer_event", status="pending"))
        _equal(_state(ledger)["customer_events"], [])
    add("P11", "portfolio", "Unconfirmed outage / 未确认停工", "No active customer events", lambda: _ledger_check(customer_pending))

    def scoped_event(ledger):
        ledger.record_event(_event("customer_event"))
        events = _state(ledger)["customer_events"]
        _equal(len(events), 1)
        _equal(events[0]["customer_id"], "customer-a")
        _equal(events[0]["load_multiplier"], 0)
    add("P12", "portfolio", "Customer scope / 停工客户归属", "Only customer-a multiplier=0", lambda: _ledger_check(scoped_event))

    def stale(ledger):
        old = ledger.start_run("task-a", "input-a")
        ledger.start_run("task-a", "input-b")
        _reject(lambda: ledger.finish_run("task-a", old, "input-a", {"plans": []}))
    add("T01", "task", "Late worker / 迟到结果", "ValidationError", lambda: _ledger_check(stale))

    def wrong_hash(ledger):
        generation = ledger.start_run("task-a", "input-a")
        _reject(lambda: ledger.finish_run("task-a", generation, "input-b", {"plans": []}))
    add("T02", "task", "Wrong snapshot / 输入版本不符", "ValidationError", lambda: _ledger_check(wrong_hash))

    def select_version(ledger):
        generation = ledger.start_run("task-a", "input-a")
        result = {"plans": [{"plan_id": "plan-a", "plan_hash": "hash-a"}]}
        ledger.finish_run("task-a", generation, "input-a", result)
        ledger.select_plan("task-a", generation, "plan-a", "hash-a")
        if ledger.get_run("task-a")["selection"] is None:
            raise AssertionError("selection was not retained")
        ledger.start_run("task-a", "input-b")
        _equal(ledger.get_run("task-a")["selection"], None)
        _reject(lambda: ledger.select_plan("task-a", generation, "plan-a", "hash-a"))
    add("T03", "task", "Version-bound choice / 选择版本绑定", "New run has no inherited selection", lambda: _ledger_check(select_version))

    def wrong_plan_hash(ledger):
        generation = ledger.start_run("task-a", "input-a")
        ledger.finish_run("task-a", generation, "input-a", {"plans": [{"plan_id": "a", "plan_hash": "right"}]})
        _reject(lambda: ledger.select_plan("task-a", generation, "a", "wrong"))
    add("T04", "task", "Plan integrity / 方案哈希核验", "ValidationError", lambda: _ledger_check(wrong_plan_hash))

    def restart():
        with tempfile.TemporaryDirectory(prefix="pta-restart-", dir=os.environ.get("TMPDIR")) as directory:
            path = Path(directory) / "ledger.sqlite3"
            with Ledger(path) as ledger:
                ledger.record_event(_event())
                ledger.start_run("task-a", "input-a")
                ledger.cancel_run("task-a")
            with Ledger(path) as ledger:
                _equal(_state(ledger)["holdings_mwh"], [2] * 24)
                _equal(ledger.get_run("task-a")["status"], "cancelled")
                _reject(lambda: ledger.start_run("task-a", "input-b"))
    add("T05", "task", "Restart and stop / 重启与持久停止", "Holdings retained; cancelled task cannot restart", restart)

    def cost_zero_fee():
        result = settlement([10] * 24, [10] * 24, [100] * 24, [200] * 24,
                            [0] * 24, [0] * 24, RULE)
        _near(result["total_cost_cny"], 24000)
        _near(result["fee_cny"], 0)
    add("E01", "economics", "Baseline cost / 基准成本手算", "24000 CNY; fees=0", cost_zero_fee)

    def cost_fee():
        result = settlement([11] * 24, [10] * 24, [100] * 24, [200] * 24,
                            [0] * 24, [0] * 24, dict(RULE, deviation_fee_cny_per_mwh=2))
        _near(result["total_cost_cny"], 21648)
        _near(result["fee_cny"], 48)
    add("E02", "economics", "Fees and F/L/Q / 量价费用手算", "21648 CNY including 48 fee", cost_fee)

    def forward_cost():
        result = settlement([10] * 24, [10] * 24, [100] * 24, [200] * 24,
                            [2] * 24, [150] * 24, RULE)
        _near(result["total_cost_cny"], 22800)
    add("E03", "economics", "Forward holdings / 持仓不重复采购", "22800 CNY", forward_cost)

    def negative_prices():
        result = settlement([10] * 24, [10] * 24, [-100] * 24, [-50] * 24,
                            [0] * 24, [0] * 24, RULE)
        _near(result["total_cost_cny"], -24000)
    add("E04", "economics", "Negative prices / 负价", "-24000 CNY", negative_prices)

    def invalid_rule():
        _reject(lambda: settlement([10] * 24, [10] * 24, [100] * 24, [200] * 24,
                                   [0] * 24, [0] * 24, dict(RULE, scope="guangdong_live")))
    add("E05", "economics", "Rule scope / 演示规则不能冒充现行规则", "ValidationError", invalid_rule)

    def invalid_curve():
        _reject(lambda: settlement([10] * 23, [10] * 24, [100] * 24, [200] * 24,
                                   [0] * 24, [0] * 24, RULE))
    add("E06", "economics", "Incomplete day / 成本曲线缺点", "ValidationError", invalid_curve)

    def strategy_direction():
        config = {"k_min": 0.9, "k_max": 1.1, "adjustment": 0.1, "spread_threshold": 50}
        plans = make_plans([10] * 24, [100] * 24, [200] * 12 + [0] * 12, config)
        baseline = next(plan for plan in plans if plan["name"] == "baseline")
        candidate = next(plan for plan in plans if plan["name"] == "spread_rule")
        _equal(baseline["q"], [10] * 24)
        for value in candidate["q"][:12]:
            _near(value, 11)
        for value in candidate["q"][12:]:
            _near(value, 9)
    add("E07", "economics", "Forecast strategy direction / 预测价差方向", "Q=11 positive; Q=9 negative; baseline=10", strategy_direction)

    def stress_metrics():
        result = _evaluate()
        forbidden = {"expected_cost_cny", "expected_incremental_gain_cny", "loss_probability", "cvar90_loss_cny"}
        for plan in result["plans"]:
            _equal(sorted(set(plan) & forbidden), [])
        _near(_candidate(result)["worst_loss_cny"], 100)
    add("E08", "economics", "Stress semantics / 压力场景不冒充概率", "Worst loss=100; no probability/CVaR fields", stress_metrics)

    def uncalibrated():
        scenarios = _scenarios("probabilistic")
        scenarios["calibration_status"] = "not_calibrated"
        _reject(lambda: _evaluate(scenarios))
    add("E09", "economics", "Uncalibrated probabilities / 未校准概率", "ValidationError", uncalibrated)

    def weights():
        scenarios = _scenarios("probabilistic")
        scenarios["items"][0]["weight"] = 0.04
        _reject(lambda: _evaluate(scenarios))
    add("E10", "economics", "Weight normalization / 权重合计", "ValidationError", weights)

    def negative_weight():
        scenarios = _scenarios("probabilistic")
        scenarios["items"][0]["weight"] = -0.05
        scenarios["items"][2]["weight"] = 0.95
        _reject(lambda: _evaluate(scenarios))
    add("E11", "economics", "Negative probability / 负概率", "ValidationError", negative_weight)

    def missing_budget():
        result = _evaluate()
        _equal(_candidate(result)["risk_status"], "needs_risk_budget")
    add("E12", "economics", "Missing risk budget / 未设风险金额", "needs_risk_budget", missing_budget)

    def cvar_fraction():
        result = _candidate(_evaluate(_scenarios("probabilistic"), 50))
        _near(result["cvar90_loss_cny"], 60)
        _near(result["expected_incremental_gain_cny"], -7)
        _near(result["loss_probability"], 0.15)
        _equal(result["risk_status"], "exceeds_budget")
    add("E13", "economics", "Fractional weighted tail / 加权尾部分数", "CVaR90=60; mean gain=-7; loss probability=.15", cvar_fraction)

    def exact_budget():
        result = _candidate(_evaluate(_scenarios("probabilistic"), 60))
        _equal(result["risk_status"], "within_budget")
    add("E14", "economics", "Budget equality / 风险边界等值", "within_budget at 60 CNY", exact_budget)

    def stress_budget():
        result = _candidate(_evaluate(budget=90))
        _equal(result["risk_status"], "exceeds_budget")
    add("E15", "economics", "Stress loss limit / 压力损失限额", "exceeds_budget at 90 CNY", stress_budget)

    def replay():
        gains = [10, -30, 5, -5, 40]
        rows = [{"date": "2026-10-{:02d}".format(index + 1),
                 "group": "extreme" if gain < 0 else "normal",
                 "baseline_cost_cny": 100, "candidate_cost_cny": 100 - gain}
                for index, gain in enumerate(gains)]
        result = replay_metrics(rows)
        _equal(result["days"], 5)
        _near(result["total_incremental_gain_cny"], 20)
        _near(result["loss_day_fraction"], 0.4)
        _near(result["max_drawdown_cny"], 30)
        _near(result["worst_day_gain_cny"], -30)
        _equal(result["groups"]["extreme"]["days"], 2)
        _near(result["groups"]["extreme"]["total_incremental_gain_cny"], -35)
    add("E16", "economics", "Replay attribution / 回放分组与回撤", "Gain=20; drawdown=30; two extreme days gain=-35", replay)
    return cases


def run_benchmark(output_dir):
    """Run cases and retain failures; caller exits nonzero if summary['failed'] > 0."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    records = []
    started = time.perf_counter()
    for case in build_cases():
        case_start = time.perf_counter()
        record = {"case_id": case.case_id, "group": case.group,
                  "description": case.description, "expected": case.expected}
        try:
            case.check()
            record.update(passed=True, observed="All independent assertions passed")
        except Exception as error:
            record.update(passed=False, observed=str(error), error_type=type(error).__name__)
        record["elapsed_ms"] = round((time.perf_counter() - case_start) * 1000, 3)
        records.append(record)
        # Keep partial evidence if interrupted between cases.
        with (output / "cases.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    failed = sum(not record["passed"] for record in records)
    summary = {"suite": "power-trading-agent-v1.1-independent-acceptance",
               "scope": "synthetic_offline_services", "hosted_llm_evaluated": False,
               "total": len(records), "passed": len(records) - failed, "failed": failed,
               "status": "passed" if failed == 0 else "failed",
               "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
               "cases": records}
    (output / "benchmark.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# v1.1 Independent acceptance / 独立验收", "",
             "Synthetic offline services only; no hosted LLM or live trading evaluation.",
             "仅验证合成输入下的本地服务，未评价在线大模型或实际交易效果。", "",
             "Result / 结果: **{} / {} passed**, {} failed.".format(summary["passed"], summary["total"], failed), "",
             "| ID | Case / 案例 | Expected / 预期 | Result / 结果 |",
             "| --- | --- | --- | --- |"]
    for record in records:
        outcome = "PASS" if record["passed"] else "FAIL: " + record["observed"].replace("|", "\\|").replace("\n", " ")
        lines.append("| {} | {} | {} | {} |".format(record["case_id"], record["description"], record["expected"], outcome))
    (output / "benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
