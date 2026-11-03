# 电力交易研究回放 / Power Trading Research Replay

**合成研究数据 / Synthetic research only — v1.1.0**

不代表真实广东结算、实际收益或平台申报。No live execution or certified settlement.

成本单位 CNY；电量 MWh。增益=基准成本−候选成本。Gain = baseline cost minus candidate cost.

情景为压力假设，未校准概率；不输出期望收益或 CVaR。Stress scenarios have no probability claim.

| 策略 / Strategy | 天数 / Days | 增量合计 / Gain | 最差日 / Worst day | 最大回撤 / Drawdown |
| --- | ---: | ---: | ---: | ---: |
| baseline | 28 | 0.00 | 0.00 | 0.00 |
| spread_rule | 28 | -6675.46 | -529.47 | 6675.46 |
| bounded_rule | 28 | -3156.34 | -255.77 | 3156.34 |

## 每日结果 / Daily outcomes

| 日期 / Date | 分组 / Group | 策略 / Strategy | 实现增益 / Realized gain | 压力检查 / Stress check |
| --- | --- | --- | ---: | --- |
| 2026-01-15 | weekday | baseline | 0.00 | within_budget |
| 2026-01-15 | weekday | spread_rule | -306.18 | within_budget |
| 2026-01-15 | weekday | bounded_rule | -152.20 | within_budget |
| 2026-01-16 | weekday | baseline | 0.00 | within_budget |
| 2026-01-16 | weekday | spread_rule | -294.77 | within_budget |
| 2026-01-16 | weekday | bounded_rule | -146.87 | within_budget |
| 2026-01-17 | weekend | baseline | 0.00 | within_budget |
| 2026-01-17 | weekend | spread_rule | -241.56 | within_budget |
| 2026-01-17 | weekend | bounded_rule | -109.52 | within_budget |
| 2026-01-18 | weekend | baseline | 0.00 | within_budget |
| 2026-01-18 | weekend | spread_rule | -353.26 | within_budget |
| 2026-01-18 | weekend | bounded_rule | -160.84 | within_budget |
| 2026-01-19 | weekday | baseline | 0.00 | within_budget |
| 2026-01-19 | weekday | spread_rule | -352.02 | within_budget |
| 2026-01-19 | weekday | bounded_rule | -176.01 | within_budget |
| 2026-01-20 | weekday | baseline | 0.00 | within_budget |
| 2026-01-20 | weekday | spread_rule | -354.46 | within_budget |
| 2026-01-20 | weekday | bounded_rule | -177.23 | within_budget |
| 2026-01-21 | weekday | baseline | 0.00 | within_budget |
| 2026-01-21 | weekday | spread_rule | -267.53 | within_budget |
| 2026-01-21 | weekday | bounded_rule | -132.22 | within_budget |
| 2026-01-22 | weekday | baseline | 0.00 | within_budget |
| 2026-01-22 | weekday | spread_rule | -329.60 | within_budget |
| 2026-01-22 | weekday | bounded_rule | -154.73 | within_budget |
| 2026-01-23 | weekday | baseline | 0.00 | within_budget |
| 2026-01-23 | weekday | spread_rule | -409.42 | within_budget |
| 2026-01-23 | weekday | bounded_rule | -194.54 | within_budget |
| 2026-01-24 | weekend | baseline | 0.00 | within_budget |
| 2026-01-24 | weekend | spread_rule | -359.90 | within_budget |
| 2026-01-24 | weekend | bounded_rule | -175.04 | within_budget |
| 2026-01-25 | weekend | baseline | 0.00 | within_budget |
| 2026-01-25 | weekend | spread_rule | -332.47 | within_budget |
| 2026-01-25 | weekend | bounded_rule | -166.23 | within_budget |
| 2026-01-26 | synthetic_spike | baseline | 0.00 | within_budget |
| 2026-01-26 | synthetic_spike | spread_rule | 697.19 | within_budget |
| 2026-01-26 | synthetic_spike | bounded_rule | 360.52 | within_budget |
| 2026-01-27 | weekday | baseline | 0.00 | within_budget |
| 2026-01-27 | weekday | spread_rule | -261.86 | within_budget |
| 2026-01-27 | weekday | bounded_rule | -121.32 | within_budget |
| 2026-01-28 | weekday | baseline | 0.00 | within_budget |
| 2026-01-28 | weekday | spread_rule | -468.28 | within_budget |
| 2026-01-28 | weekday | bounded_rule | -219.98 | within_budget |
| 2026-01-29 | weekday | baseline | 0.00 | within_budget |
| 2026-01-29 | weekday | spread_rule | -529.47 | within_budget |
| 2026-01-29 | weekday | bounded_rule | -255.77 | within_budget |
| 2026-01-30 | weekday | baseline | 0.00 | within_budget |
| 2026-01-30 | weekday | spread_rule | -421.25 | within_budget |
| 2026-01-30 | weekday | bounded_rule | -201.00 | within_budget |
| 2026-01-31 | weekend | baseline | 0.00 | within_budget |
| 2026-01-31 | weekend | spread_rule | -331.50 | within_budget |
| 2026-01-31 | weekend | bounded_rule | -165.75 | within_budget |
| 2026-02-01 | weekend | baseline | 0.00 | within_budget |
| 2026-02-01 | weekend | spread_rule | -106.33 | within_budget |
| 2026-02-01 | weekend | bounded_rule | -52.29 | within_budget |
| 2026-02-02 | weekday | baseline | 0.00 | within_budget |
| 2026-02-02 | weekday | spread_rule | -20.63 | within_budget |
| 2026-02-02 | weekday | bounded_rule | -5.11 | within_budget |
| 2026-02-03 | synthetic_spike | baseline | 0.00 | within_budget |
| 2026-02-03 | synthetic_spike | spread_rule | 791.51 | within_budget |
| 2026-02-03 | synthetic_spike | bounded_rule | 395.75 | within_budget |
| 2026-02-04 | weekday | baseline | 0.00 | within_budget |
| 2026-02-04 | weekday | spread_rule | -261.28 | within_budget |
| 2026-02-04 | weekday | bounded_rule | -130.64 | within_budget |
| 2026-02-05 | weekday | baseline | 0.00 | within_budget |
| 2026-02-05 | weekday | spread_rule | -96.09 | within_budget |
| 2026-02-05 | weekday | bounded_rule | -48.04 | within_budget |
| 2026-02-06 | weekday | baseline | 0.00 | within_budget |
| 2026-02-06 | weekday | spread_rule | -211.34 | within_budget |
| 2026-02-06 | weekday | bounded_rule | -105.67 | within_budget |
| 2026-02-07 | weekend | baseline | 0.00 | within_budget |
| 2026-02-07 | weekend | spread_rule | -306.79 | within_budget |
| 2026-02-07 | weekend | bounded_rule | -132.44 | within_budget |
| 2026-02-08 | weekend | baseline | 0.00 | within_budget |
| 2026-02-08 | weekend | spread_rule | -365.60 | within_budget |
| 2026-02-08 | weekend | bounded_rule | -169.71 | within_budget |
| 2026-02-09 | weekday | baseline | 0.00 | within_budget |
| 2026-02-09 | weekday | spread_rule | -340.63 | within_budget |
| 2026-02-09 | weekday | bounded_rule | -162.44 | within_budget |
| 2026-02-10 | weekday | baseline | 0.00 | within_budget |
| 2026-02-10 | weekday | spread_rule | -328.74 | within_budget |
| 2026-02-10 | weekday | bounded_rule | -155.29 | within_budget |
| 2026-02-11 | weekday | baseline | 0.00 | within_budget |
| 2026-02-11 | weekday | spread_rule | -513.21 | within_budget |
| 2026-02-11 | weekday | bounded_rule | -241.71 | within_budget |

## 解释与边界 / Interpretation

- 基准为同一 F 的 k=1；固定持仓和费用。Baseline uses identical F, holdings and fees.
- 未成交意图不计入持仓，客户事件仅影响对应客户的 F。Intents are not filled trades.
- 压力检查通过不代表可实盘采用；风险预算缺失时标为待补。No automatic plan selection.
- 示例预测仅使用此前可得的七天数据；本次成绩不证明真实预测能力。Synthetic baseline only.
- 本报告比较固定预测下的策略；未宣称完成预测模型或 LLM 优劣评测。
  This run isolates strategy comparison, not model or LLM performance.
- 分组统计见 results.json；每组保留样本量。Group sample counts are in results.json.
- input.json、results.json 与 manifest.json 保存冻结输入、情景和校验值。
