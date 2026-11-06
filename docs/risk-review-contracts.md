# 风控与复盘扩展契约 / Risk and review contracts

Date: 2026-11-04. Implementation baseline; retain v1.1 compatibility.
Python 3.9+, standard library. All outputs remain synthetic research, not certified rules.

## User requirements

- Risk is multidimensional: price, volume, assessment/fees, positions, gross outflow,
  and data/operational readiness. Conservative / steady / aggressive are whole limit
  sets selected by the user, never inferred from one coefficient or one money amount.
- Daily declaration review is daily. Monthly declaration/procurement is a separate
  monthly decision with one pre-month information origin, not summed daily foresight.
- Review separates a recorded choice, policies executable using the frozen known set,
  and the hindsight-best member of the SAME frozen admissible candidate set.
  Hindsight gap is not an achievable return, proof of poor process, EVPI, or causal loss.

## Context (shared object)

`context` is a dict with schema_version="risk-review-1", scope="synthetic",
portfolio_id, period_type="day"|"month", period (YYYY-MM-DD or YYYY-MM), origin,
hours (complete ordered +08:00 hourly starts for the day/calendar month), f, da, rt,
holdings, holding_cost (all length N), rule (v1.1 synthetic rule incl valid_from/to/source),
input_snapshot_id, portfolio_state_id, evidence=[{id, available_time, source_hash}].
Evidence must be nonempty and <= origin; origin strictly before first delivery hour.
No actual curves are in this object. Monthly inputs have ONE origin before month start.

## Risk engine (risk.py)

- `default_profiles()` -> list of conservative/steady/aggressive profiles. Fields id,
  label, limits. All numeric limits default None, so no profile is silently authorized.
- Required limit keys (all nonnegative, None means unresolved):
  max_price_shock_cost_cny, max_hourly_deviation_mwh, max_daily_deviation_mwh,
  max_assessment_fee_cny, max_forecast_unhedged_mwh, max_gross_outflow_cny,
  max_incremental_loss_cny, max_daily_incremental_loss_cny, max_abs_k_deviation.
  Limits are nondecreasing across conservative -> steady -> aggressive when provided.
  max_daily_deviation_mwh is maximum per-calendar-day sum, even for month context;
  monetary limits cover the ENTIRE decision period. Forecast unhedged is max hour |F-H|.
- `validate_context(context)` validates the full scope/time/shape/evidence/rule contract.
- `build_stress_scenarios(context, config=None)` -> {kind:"stress", items:[{scenario_id,
  label, category,l,da,rt}], scenario_set_id, config}. Default crossed load/DA/RT shocks
  (>=27 combinations including central), spikes, negative prices, load stop/surge.
  Full trajectories, no probabilities. All generated solely from known curves.
- `build_candidates(context, config=None)` -> plans [{plan_id,name,k,q}]. Must include
  baseline k=1, existing direction policies and a bounded coefficient grid. Config
  default max_abs_k_deviation=.2, grid_step=.05, spread_threshold=5 (illustrative only).
  Q=kF; no actual-dependent plan creation. IDs deterministic.
- `assess_risk(context, profiles=None, stress_config=None, candidate_config=None)` ->
  report with context, profiles, scenarios, plans, profile_results, status=research_only,
  report_id, report_hash, coverage. Report hash=digest(report without report_hash).
  plans contain plan_id/name/k/q, metrics, scenario_results (scenario_id,cost_cny,
  incremental_gain_cny,fee_cny,gross_outflow_cny), central_cost_cny, plan_hash.
  plan_hash=digest(plan without plan_hash). Include full frozen scenario trajectories.
  metrics keys equal limit keys, representing measured consequences/action magnitude.
  Price shock cost = max(0, C(Q,F,DA_s,RT_s)-C(Q,F,DA_center,RT_center)); isolate prices
  at fixed forecast load and same holdings/rule. Fees isolated in fee metric.
  Gross outflow=sum positive B + positive (Q-H)*DA + positive (L-Q)*RT + fee; proxy only.
  profile_results list {profile_id, checks:[{plan_id,status,violations,missing_limits}],
  admissible_plan_ids, reference_choices:{central_min_cost, minimax_regret}, pareto_plan_ids}.
  check.status=eligible|breached|needs_limits. No reference choice if missing required limits.
  References are nonbinding rules using ONLY risk report. Minimax regret compared to
  the same profile's admissible set, deterministic plan_id tie-breaking.
- `period_cost(q,l,da,rt,holdings,holding_cost,rule)` sums v1.1 settlement over 24h blocks,
  returns total_cost_cny, fee_cny, energy_cost_cny, hourly_cost_cny; validates equal N.
- `verify_risk_report(report)` verifies hashes and substantive calculation by recomputing
  from context and frozen configs/profiles (or equivalent independent checks).

## Decision review (review.py)

- `record_decision(report, profile_id, plan_id, actor, reason, selected_at)` -> dict
  decision_id, report_hash, profile_id, plan_id, plan_hash, actor, reason, selected_at,
  decision_hash, scope=synthetic, record_type=declared_research_choice. Verify report;
  selected_at>=origin and <first delivery hour. Reject needs_limits/breached/unknown plan.
  No automatic selection; declared historical timestamps are not independently authenticated.
- `record_historical_decision(report, profile_id, plan_id, actor, reason, selected_at,
  evidence)` imports an observed choice from the frozen set for review even if it breached
  limits or had unresolved limits. Mark historical_observation_not_authorization and
  retain admissibility_status/violations; this must never authorize a new choice.
- `review_decision(report, decision, actuals, execution=None)` -> dict with review_id,
  period_type,period,portfolio_id, report_hash, decision_hash, actuals_hash, status,
  chosen_outcome, baseline_outcome, ex_ante_references, hindsight_best,
  cost_bridge, forecast_diagnostics, scenario_coverage, lessons, evaluation_boundaries,
  decision_context (origin, selected_at, profile_id, actor, reason and frozen input/position/report IDs).
  actuals={hours,l,da,rt,price_basis:"user_side",energy_unit:"MWh",price_unit:"CNY/MWh",
  available_time, source}. Full same hours; available_time >= delivery end.
  execution optional {hours,q,energy_unit:"MWh",source,available_time}; require exact frozen hours and unit; if absent report
  execution_status="not_provided", never claim adopted/filled/platform-confirmed.
  Compare each frozen admissible plan under identical actuals, holdings, fees.
  ex_ante_references scores frozen central_min_cost/minimax_regret choices, not chosen
  using actuals. hindsight_best is minimum actual cost ONLY among frozen admissible set;
  label as candidate-set oracle, not global optimum, future strategy, or EVPI.
  If no frozen plans were admissible, hindsight_best is unavailable, not fabricated.
  cost_bridge fixed order: central forecast -> actual L -> actual DA -> actual RT ->
  optional actual execution Q. Components sum total change; order-dependent descriptive
  decomposition, not causal attribution. Include human choice vs fixed references separately.
  scenario_coverage flags observed load/DA/RT/spread outside frozen per-hour envelopes;
  marginal coverage is not joint distribution coverage/probability validation.
  lessons are proposed next experiments, never auto-promote based on this same period.
- `register_experiment(proposal, reviews)` -> experiment record. Proposal includes
  hypothesis, change, registered_at, test_start, test_end, metric, baseline, acceptance,
  frozen_candidate_hash. test_start strictly after all review periods and review data
  availability/registered_at. Returns immutable hash and status=proposed_not_validated.

## Root integration

Root owns risk_workflow.py (daily/monthly synthetic adapters, CLI, files), dashboard.py
(offline human comparison, no labels in pre-decision page), __main__, tools, docs.
Commands: risk-demo; risk (known-only context); decide (explicit actor/reason/profile/plan);
review (separate actuals); review-demo; experiment-register. Every output new directory.
Risk input templates leave real limits blank. Demonstration profiles are explicitly
synthetic examples. Daily/monthly reports use distinct period keys, never mix origins.

## Acceptance priorities

All v1.1 checks remain. Add crossed shocks, independent limit dimensions, monotonic
profiles, empty limits blocking, budget boundary, price-only isolation, zero load,
full monthly coverage and month-origin gates, frozen-known vs actual-label separation,
hindsight oracle confinement, actual execution vs selected plan, bridge reconciliation,
unknown source, report/decision tampering, chronological experiment registration.
