# v1.1 Independent acceptance / 独立验收

Synthetic offline services only; no hosted LLM or live trading evaluation.
仅验证合成输入下的本地服务，未评价在线大模型或实际交易效果。

Result / 结果: **45 / 45 passed**, 0 failed.

| ID | Case / 案例 | Expected / 预期 | Result / 结果 |
| --- | --- | --- | --- |
| D01 | Complete day / 完整目标日 | 24 F=10, DA=100, RT=200 | PASS |
| D02 | As-of revision / 截点后修订隔离 | 10 before arrival; 999 at arrival | PASS |
| D03 | Inclusive cutoff / 截点等时接纳 | F[0]=12 | PASS |
| D04 | Missing interval / 缺点 | ValidationError | PASS |
| D05 | Wrong energy unit / 功率电量混用 | ValidationError | PASS |
| D06 | Wrong price basis / 节点用户侧混用 | ValidationError | PASS |
| D07 | Naive timestamp / 无时区时间 | ValidationError | PASS |
| D08 | Nonfinite load / 非有限值 | ValidationError | PASS |
| D09 | Negative load / 负电量 | ValidationError | PASS |
| D10 | Conflicting revision / 同版冲突 | ValidationError | PASS |
| D11 | Actuals isolation / 目标日实际值隔离 | Forecast curves unchanged | PASS |
| D12 | Arrival chronology / 接收前不可得 | ValidationError | PASS |
| P01 | Idempotent fill / 成交去重 | 2 MWh/h, not 4 | PASS |
| P02 | Conflicting fill / 同版成交冲突 | ValidationError | PASS |
| P03 | Revised fill / 修订替代 | 3 MWh/h; 240 CNY/h | PASS |
| P04 | Cancelled fill / 撤销成交 | Zero holdings | PASS |
| P05 | Future fill revision / 未来成交修订 | 2 MWh/h | PASS |
| P06 | Pending fill / 待确认成交 | Zero holdings | PASS |
| P07 | Intent separation / 采购意图分账 | Intent=5; holdings=0 | PASS |
| P08 | Declaration separation / 申报分账 | Declaration=8; holdings=0 | PASS |
| P09 | Half-open interval / 时段左闭右开 | Only hour 01 contains 2 MWh | PASS |
| P10 | Invalid volume / 负成交量 | ValidationError | PASS |
| P11 | Unconfirmed outage / 未确认停工 | No active customer events | PASS |
| P12 | Customer scope / 停工客户归属 | Only customer-a multiplier=0 | PASS |
| T01 | Late worker / 迟到结果 | ValidationError | PASS |
| T02 | Wrong snapshot / 输入版本不符 | ValidationError | PASS |
| T03 | Version-bound choice / 选择版本绑定 | New run has no inherited selection | PASS |
| T04 | Plan integrity / 方案哈希核验 | ValidationError | PASS |
| T05 | Restart and stop / 重启与持久停止 | Holdings retained; cancelled task cannot restart | PASS |
| E01 | Baseline cost / 基准成本手算 | 24000 CNY; fees=0 | PASS |
| E02 | Fees and F/L/Q / 量价费用手算 | 21648 CNY including 48 fee | PASS |
| E03 | Forward holdings / 持仓不重复采购 | 22800 CNY | PASS |
| E04 | Negative prices / 负价 | -24000 CNY | PASS |
| E05 | Rule scope / 演示规则不能冒充现行规则 | ValidationError | PASS |
| E06 | Incomplete day / 成本曲线缺点 | ValidationError | PASS |
| E07 | Forecast strategy direction / 预测价差方向 | Q=11 positive; Q=9 negative; baseline=10 | PASS |
| E08 | Stress semantics / 压力场景不冒充概率 | Worst loss=100; no probability/CVaR fields | PASS |
| E09 | Uncalibrated probabilities / 未校准概率 | ValidationError | PASS |
| E10 | Weight normalization / 权重合计 | ValidationError | PASS |
| E11 | Negative probability / 负概率 | ValidationError | PASS |
| E12 | Missing risk budget / 未设风险金额 | needs_risk_budget | PASS |
| E13 | Fractional weighted tail / 加权尾部分数 | CVaR90=60; mean gain=-7; loss probability=.15 | PASS |
| E14 | Budget equality / 风险边界等值 | within_budget at 60 CNY | PASS |
| E15 | Stress loss limit / 压力损失限额 | exceeds_budget at 90 CNY | PASS |
| E16 | Replay attribution / 回放分组与回撤 | Gain=20; drawdown=30; two extreme days gain=-35 | PASS |
