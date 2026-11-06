# 风控与复盘使用说明 / Risk and decision-review guide

本模块帮助你在决策前看清不同方案的风险，再在交割后检查：当时的信息是否够用、选择是否合理、执行是否一致，以及下一次该验证什么改进。系统不代替你选择档位或提交交易。当前实现只接受 `scope="synthetic"`，所有费用、场景、示例限额均属于研究演示；真实考核规则、交易平台与资金到账流程尚未接入。

This module compares the risks of alternative plans before a decision, then reviews information, choice, execution and possible improvements after delivery. You choose the profile and plan. The implementation accepts only `scope="synthetic"`; costs, scenarios and example limits are research demonstrations. Formal assessment rules, exchange execution and cash timing are not connected.

## 1. 先冻结当时知道的内容 / Freeze what was known

每个风控报告固定一个组合、一个交割期间和一个信息截止时点 `origin`。客户负荷预测 `f` 用于申报电量；`da`、`rt` 是同口径的用户侧价格预测。`holdings` 和 `holding_cost` 分别为已有持仓电量及其成本。各条证据必须带来源哈希和 `available_time`，且不能晚于 `origin`。实际负荷、实际价格只能在复盘阶段单独传入。

Each report freezes one portfolio, one delivery period and one information origin. Customer-load forecast `f` determines declaration demand; `da` and `rt` are comparable user-side price forecasts. `holdings` and `holding_cost` describe the existing position and its cost. Evidence carries a source hash and an availability timestamp no later than the origin. Realized load and prices enter only through the separate review input.

日决策覆盖完整 24 小时；月决策覆盖完整自然月，且只能使用月初以前的一个 `origin`。逐日更新过的信息不能拼接成“月前已知”。每日申报逐日复盘；月度申报按组合和月份形成一份复盘，修订时保留旧版。当前文件接口保留版本，但没有自动调度或月度唯一记录数据库。

Daily decisions cover all 24 hours. Monthly decisions cover the full calendar month with one origin before month start. A collection of daily refreshed forecasts is not a month-ahead information set. Review daily declarations daily and monthly declarations once per portfolio-month, retaining revisions. The file workflow preserves versions; it does not implement a scheduler or a database enforcing one monthly record.

## 2. 九项限额分别管什么 / What the nine limits control

以下符号都针对同一组合：`F` 为预测负荷，`Q=kF` 为候选申报，`H` 为已有持仓，`B` 为已有持仓成本，`L_s/DA_s/RT_s` 为场景值；`s` 遍历已冻结场景，`t` 遍历小时，`d` 遍历自然日。`[x]+ = max(x, 0)`。电量单位为 MWh，价格为 CNY/MWh，费用为 CNY。

For the same portfolio, `F` is forecast load, `Q=kF` is a candidate declaration, `H` is the existing holding, `B` is its cost, and `L_s/DA_s/RT_s` are scenario values. Indices `s`, `t` and `d` denote frozen scenarios, hours and calendar days. `[x]+ = max(x, 0)`. Energy is in MWh, prices in CNY/MWh, and costs in CNY.

合成账式 / Synthetic accounting:

```text
C_t(Q,L,DA,RT) = B_t + (Q_t-H_t) DA_t + (L_t-Q_t) RT_t + a |Q_t-L_t|
C_period = sum_t C_t
```

`a` 是非负的示例偏差费用单价，并非广东正式考核规则。`B` 已是金额，不再乘电价。小时电量不是某个瞬间的功率；未来接入更细时间粒度时需要重新核对单位。

`a` is a nonnegative illustrative deviation-fee rate, not a certified Guangdong assessment rule. `B` is already a monetary cost and is not multiplied by price again. Hourly energy is not instantaneous power; finer time resolutions require a fresh unit check.

| 配置键 / Limit key | 指标与公式 / Measurement | 时域与解释 / Horizon and meaning |
| --- | --- | --- |
| `max_price_shock_cost_cny` | `max_s [C(Q,F,DA_s,RT_s) − C(Q,F,DA_center,RT_center)]+` | 固定负荷为 F，单独观察价格冲击带来的整个期间成本增加；同 Q、同 F 的示例费用相消。 / Whole-period cost increase from prices alone, holding load at F; the identical fee cancels. |
| `max_hourly_deviation_mwh` | `max_(s,t) abs(Q_t − L_s,t)` | 单小时最严重申报偏差。 / Largest single-hour declaration deviation. |
| `max_daily_deviation_mwh` | `max_(s,d) sum_(t in d) abs(Q_t − L_s,t)` | 最坏自然日的绝对偏差总量；月模式也不把全月偏差相加。 / Largest daily absolute deviation; it remains a daily limit in monthly mode. |
| `max_assessment_fee_cny` | `max_s sum_t a abs(Q_t − L_s,t)` | 整个期间的示例偏差费用，页面标记为示例考核费用；不代表正式考核已通过。 / Whole-period illustrative deviation fee, not a formal assessment clearance. |
| `max_forecast_unhedged_mwh` | `max_t abs(F_t − H_t)` | 预测需求与已有持仓的最大逐时缺口，与申报系数 k 无关。 / Largest hourly forecast-versus-holding gap; independent of declaration k. |
| `max_gross_outflow_cny` | `max_s sum_t ([B_t]+ + [(Q_t−H_t)DA_s,t]+ + [(L_s,t−Q_t)RT_s,t]+ + a abs(Q_t−L_s,t))` | 整个期间正向支付腿之和的最大值，不用应收款抵消；只是资金需求代理。 / Maximum whole-period sum of positive payment legs, without receivable netting; a cash-demand proxy. |
| `max_incremental_loss_cny` | `max_s [C_period(Q,s) − C_period(F,s)]+` | 相对 k=1 基准的整个期间新增损失；不是整体采购成本上限。 / Whole-period additional loss against k=1, not a cap on total procurement cost. |
| `max_daily_incremental_loss_cny` | `max_(s,d) [C_d(Q,s) − C_d(F,s)]+` | 相对同一基准的最坏单日新增损失，防止月内好坏日相抵。 / Worst daily additional loss against the same baseline, preventing good days from hiding bad days. |
| `max_abs_k_deviation` | `max_t abs(k_t − 1)` | 申报动作幅度，例如 0.10 对应候选 k 在 0.90—1.10；不是盈利率或价格风险。 / Declaration action bound: 0.10 means candidate k lies in 0.90–1.10, not a return or price-risk estimate. |

这些指标有交叉，不能相加成“总风险”。例如示例费用已经包含在采购成本中；电量偏差和价格同时改变时，也会共同影响新增损失。某方案相对基准新增损失为零，仍可能面临很高的采购成本或持仓缺口。

These metrics overlap and must not be added into a “total risk” score. The illustrative fee already enters procurement cost; load and price jointly affect additional loss. Zero additional loss against the baseline can coexist with high procurement costs or a large holding gap.

月模式下，价格冲击、示例费用、正向支付及期间新增损失都按全月累计；名称带 `daily` 的两项仍取最坏单日。比如某两天新增损失分别为 +5,000 元、−5,000 元，期间净新增损失可以为零，最坏单日仍是 5,000 元。不能把用户认可的日限额直接乘天数当作获批月限额。演示生成器为了展示月度页面，会明确将部分演示金额按天数放大；正式输入没有这个推断。

In monthly mode, price-shock cost, illustrative fees, gross outflow and period additional loss accumulate over the whole month. The two `daily` metrics still measure the worst day. Two days with +5,000 and −5,000 CNY additional loss can net to zero while retaining a 5,000 CNY worst day. An approved daily budget does not authorize that budget multiplied by the number of days. The demo generator scales certain example amounts to illustrate monthly pages; supplied operating inputs are not scaled automatically.

如果所有方案的持仓缺口都超限，需要检查组合持仓、预测需求或用户给定限额。调整 k 无法修复 `F−H`。资金代理也没有模拟保证金、授信、结算日、净额结算和客户回款；这些缺口在 `coverage` 中保留为未接入。

If every plan breaches the holding-gap limit, inspect the position, forecast demand or supplied limit. Changing k cannot repair `F−H`. The cash proxy does not model margin, credit lines, settlement dates, netting or customer receipts; coverage retains those limitations.

## 3. 三档是三套边界 / Three profiles are three complete limit sets

保守、稳健、激进分别是一整套九项限额。每个指标沿这个顺序不能收紧；允许相等。默认全部为 `null`，表示尚未决定，零表示明确的零容忍限额。系统不会从档位名称、单个损失金额或 k 的大小推断其余限额。

Conservative, steady and aggressive each contain all nine limits. A metric cannot become stricter along that order; equal values are allowed. Every default is `null`, meaning unresolved. Zero is an explicit zero-tolerance limit. Profile names, one monetary limit or k alone do not determine the other limits.

| 状态 / Status | 含义 / Meaning |
| --- | --- |
| `eligible` | 九项限额均已填写，且该候选全部满足；仍只是在本次研究配置下可选。 / All limits are supplied and met, within this research configuration. |
| `needs_limits` | 至少一项未填写，不能作为新选择记录。 / At least one limit is missing; a new choice cannot be recorded. |
| `breached` | 至少一项已知限额超限；报告列出指标、观测值、限额与超额。即使另有缺失项，也保留这个已知违规状态。 / At least one known limit is exceeded; the report retains its value, threshold and excess even when other limits are missing. |

只有同档已通过的候选参与两个事前参考规则：`central_min_cost` 在中心预测下成本最低，`minimax_regret` 尽量减小“各场景下相对同档最佳候选的最大差距”。中心预测成本不是概率期望成本。Pareto 列表只比较中心成本和最坏期间新增损失两个目标；其他维度仍由九项门槛约束。参考规则、Pareto 和 `eligible` 都不会触发自动交易。

Only admissible candidates in the same profile enter the two ex-ante references. `central_min_cost` minimizes cost under the central forecast. `minimax_regret` minimizes the largest scenario cost gap against that profile's scenario-best candidate. Central cost is not a probability-weighted expected cost. The Pareto list compares only central cost and worst period additional loss; the other dimensions remain enforced by their limits. None of these outputs executes a trade.

## 4. 35 个场景如何使用 / How to interpret the 35 scenarios

默认生成 27 个负荷—日前价—实时价交叉组合：负荷为 F 的 70%、100%、130%，日前价变动 −100、0、+100，实时价变动 −150、0、+150 CNY/MWh。中心情景包含在 27 个里。另加 8 个情景：实时尖峰、日前尖峰、实时骤降、实时负价、日前负价、用电骤停、用电突增，以及价差方向反转。

The default includes 27 crossed trajectories: load at 70%, 100% or 130% of F; DA shifts of −100, 0 or +100; and RT shifts of −150, 0 or +150 CNY/MWh. The central case is one of the 27. Eight additional cases cover RT spikes, DA spikes, RT drops, negative RT, negative DA, load stops, load surges and spread reversal.

前七种附加情景默认作用于每天 17、18、19、20 时；尖峰/骤降幅度为 300，负价为 −50。用电骤停降到零，用电突增为 `1.5F+10 MWh`。价差反转作用于整个期间，令 `RT'=2DA−RT`。这些只是可配置的演示数值，不是市场价格边界、统计分位数或发生概率。

The first seven additional cases affect hours 17–20 each day by default. Spike/drop size is 300, negative price is −50, load stop reaches zero, and load surge is `1.5F+10 MWh`. Whole-period spread reversal sets `RT'=2DA−RT`. These configurable demonstration values are not market price limits, statistical quantiles or event probabilities.

35 条压力路径没有概率，不能计算“预期收益”“95%安全率”或把它们平均后称为 CVaR。它们也没有穷尽极端事件的组合、持续时间和发生顺序；例如客户停产同时出现连续多日价差反转，需要额外设计轨迹。当前引擎支持修改这些参数，但任意自定义路径接口、历史联合分布校准和概率模型尚未实现。v1.1 的概率情景接口是另一条研究接口，不会自动赋予本模块场景概率。

The 35 stress paths have no probabilities. They cannot justify expected returns, a “95% safe” claim or CVaR obtained by averaging them. They do not exhaust combinations, durations or event ordering. A customer outage during several days of reversed spreads requires an additional designed trajectory. Current parameters are configurable; arbitrary custom paths, historical joint calibration and a probability model are not implemented here. The separate v1.1 probability-scenario interface does not assign probabilities to these stress paths.

默认候选共 11 个：k=1 基准、按预测价差方向调整的完整/半幅度规则，以及 0.80—1.20 区间内间隔 0.05、排除重复基准的固定 k 候选。所有 Q 都等于同一 F 乘 k；事后实际数据不会用于生成候选。

There are 11 default candidates: baseline k=1, full/half-size forecast-spread rules, and constant-k candidates from 0.80 to 1.20 at 0.05 steps, excluding the duplicate baseline. Every Q uses the same F; realized outcomes never generate the candidates.

## 5. 复盘的三个视角 / Three views of the decision

| 视角 / View | 能回答什么 / Question answered | 不能推断什么 / Limit |
| --- | --- | --- |
| 记录的选择 / Recorded choice | 当时选择了哪个档位和候选、为什么，以及这条申报曲线在实际量价下的结果。 / What profile and candidate were recorded, why, and how that declaration performs under realized load and prices. | 没有执行记录时，不能称为实际成交、平台回执或已执行结果。 / Without execution evidence, this is not a fill or platform-confirmed execution. |
| 事前可执行的参考规则 / Ex-ante references | 当时固定的中心成本规则和最小最大后悔规则后来表现如何，是否值得用未来样本继续比较。 / How the previously frozen central-cost and minimax-regret rules performed and what merits future testing. | 不能在看到结果后换规则、改限额，再称“当时就该这样选”。 / Do not change the rule or limits after observing outcomes and call it an available prior decision. |
| 同一可选集合的事后最佳 / Hindsight best in the same set | 当时同档、已冻结且通过限额的候选中，哪条在本期实际量价下成本最低。 / Which candidate in the same frozen admissible set had the lowest realized cost. | 不是全局最优、下一期目标收益、过程错误的证据，也不是 EVPI。 / Not a global optimum, next-period return target, proof of a bad process or EVPI. |

如果输入 `execution`，系统另算所提供执行曲线的结果并检查其与记录选择的差异；这仍是调用方提供的信息，未自动核验交易平台。没有 `execution` 时返回 `not_provided`，不会用申报曲线冒充执行。历史导入允许保留一个当时超限或限额未齐的已观察选择，但必须附历史证据，标记为 `historical_observation_not_authorization`，不能借此授权下一笔操作。没有同档合格候选时，事后最佳为空；历史选择若在合格集合外，与集合最佳的差额也不叫“集合内后悔值”。

With `execution`, the review separately evaluates the supplied execution curve and its difference from the recorded choice. This is caller-supplied evidence, not independently verified exchange data. Without it, status is `not_provided`; declaration is not substituted for execution. A historical import may preserve an observed ineligible choice with evidence and the label `historical_observation_not_authorization`. It cannot authorize a new action. With no admissible candidates, hindsight best is unavailable. A historical choice outside that set produces a cost comparison, not within-set regret.

成本桥按固定顺序替换：中心预测 → 实际负荷 → 实际日前价 → 实际实时价 → 可选的执行电量。各步差额与总变化核对一致，但量价交互会随替换顺序分配到不同步骤，因此它是描述性拆分，不是各因素独立的因果贡献。人的选择与事前参考规则的比较单列，避免混入这个账式拆分。

The cost bridge replaces inputs in a fixed order: central forecast → realized load → realized DA → realized RT → optional executed Q. Its steps reconcile to the total change. Interactions are assigned differently under a different order, so this is descriptive decomposition rather than independent causal attribution. Human choice versus reference policies is reported separately.

复盘还检查实际负荷、DA、RT、价差是否超出当时场景逐小时包络。全部落在包络内只表示边际范围覆盖，不能证明实际联合路径被模拟、概率校准正确或所有风险已覆盖。

The review checks whether realized load, DA, RT or spreads leave the frozen hourly envelopes. Staying inside those marginal ranges does not prove that the realized joint trajectory was simulated, probabilities are calibrated or all risks are covered.

## 6. 把复盘变成可验证的改进 / Turn a review into a testable improvement

每条复盘建议应转化为一个未来实验：明确假设、只改什么、冻结候选版本、比较基准、评价指标、验收门槛和未使用的未来期间。`experiment-register` 检查登记时点不能早于所依据的复盘资料可得时间，测试开始必须晚于登记和全部已复盘期间/资料可得时间。输出固定为 `proposed_not_validated`；登记不会执行回测，也不会晋升新策略。

Translate a lesson into a future experiment: hypothesis, intended change, frozen candidate version, baseline, metric, acceptance criterion and an untouched future interval. `experiment-register` rejects registration before the underlying review evidence was available. Testing must begin after registration, all reviewed periods and all review-data availability times. Its status is `proposed_not_validated`; registration neither runs evaluation nor promotes a strategy.

可优先验证：增加有时间戳的客户停产信息是否改善负荷预测；额外连续尖峰场景是否提前暴露风险；缩小动作幅度是否降低最坏单日新增损失。不要同时改变预测、场景、限额和选取规则，否则难以区分哪项改动有用。单次结果好坏不证明未来有效。

Useful hypotheses include whether timestamped customer-outage information improves load forecasts, whether sustained spike scenarios expose missing risks, and whether smaller actions reduce worst daily additional loss. Changing forecasts, scenarios, limits and selection rules together makes their effects difficult to distinguish. One good or bad outcome does not establish future performance.

## 7. 本地运行完整示例 / Complete local examples

在仓库根目录运行以下命令，需 Python 3.9+，无第三方依赖。路径都相对仓库根目录；`outputs/` 已被 Git 忽略。每次使用新输出目录/新实验文件，避免覆盖证据。以下输入、选择者、时点、限额与结果全部为虚构演示，不能复用为真实业务授权。

Run from the repository root with Python 3.9+; no third-party packages are needed. Paths are relative to that root, and `outputs/` is Git-ignored. Use new output directories and experiment files to retain evidence. Every input, actor, timestamp, limit and result below is fictional and cannot serve as operating authorization.

### 7.1 先查看日/月演示 / View daily and monthly demos

```bash
python3 -m power_trading_agent risk-demo --period-type day --period 2026-11-05 --output outputs/risk-day-demo
python3 -m power_trading_agent review-demo --period-type day --period 2026-11-05 --output outputs/review-day-demo
python3 -m power_trading_agent review-demo --period-type month --period 2026-11 --output outputs/review-month-demo
```

查看 `outputs/risk-day-demo/risk/risk.html` 和 `outputs/review-day-demo/review/review.html`；月度对应 `outputs/review-month-demo/review/review.html`。每份页面都有同目录 JSON 和 Markdown 可核对。`review-demo` 内置虚构选择用于展示完整复盘，不代表用户作出选择；其执行记录仍为缺失。

Open the risk/review HTML files above; each has accompanying JSON and Markdown. The monthly review is at `outputs/review-month-demo/review/review.html`. `review-demo` inserts a fictional choice to demonstrate the workflow. It is not a user's decision, and execution evidence remains absent.

### 7.2 从已知数据重新评估 / Assess a known-only packet

以下先不提供限额，结果应显示限额待填。随后仅复用演示限额，展示完整命令链。用户自己的配置应逐项填写 `profiles-template.json` 的三套限额，并另存版本。

The first command omits limits and therefore yields unresolved eligibility. Subsequent steps reuse explicitly illustrative limits to show the full command chain. For your configuration, fill every metric in all three profiles in `profiles-template.json` and retain a separate version.

```bash
python3 -m power_trading_agent risk --input outputs/risk-day-demo/risk/context.json --output outputs/risk-unconfigured
python3 - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("outputs/risk-day-demo/risk/risk.json").read_text())
Path("outputs/demo-profiles.json").write_text(json.dumps(report["profiles"], ensure_ascii=False, indent=2))
PY
python3 -m power_trading_agent risk --input outputs/risk-day-demo/risk/context.json --profiles outputs/demo-profiles.json --output outputs/risk-configured
```

可选参数 `--stress`、`--candidates` 分别接收场景参数与候选参数 JSON。修改后会形成新报告哈希，原选择不能绑定到新报告。实际标签文件不能传给 `risk`。

Optional `--stress` and `--candidates` arguments accept scenario and candidate configuration JSON. Changes produce a new report hash; an old choice cannot be rebound to that report. Actual-label files do not belong in `risk`.

### 7.3 明确记录一次选择 / Record an explicit choice

本示例固定选择稳健档的 k=1 基准，仅用于说明如何填表，不是推荐。真实使用时应先查看页面，再把自己选择的 `profile_id`、`plan_id`、理由和时间写入请求；程序检查资格和时间范围。

This example explicitly selects the steady-profile k=1 baseline to illustrate the request format. It is not a recommendation. In use, inspect the report and enter your chosen profile, plan, reason and timestamp; the runtime checks eligibility and timing.

```bash
python3 - <<'PY'
import json
from datetime import datetime, timedelta
from pathlib import Path

report = json.loads(Path("outputs/risk-configured/risk.json").read_text())
baseline = next(p for p in report["plans"] if p["name"] == "baseline")
request = {
    "report_hash": report["report_hash"],
    "profile_id": "steady", "plan_id": baseline["plan_id"],
    "actor": "fictional-demo-operator",
    "reason": "Fictional baseline choice for the command example only",
    "selected_at": (datetime.fromisoformat(report["context"]["origin"]) + timedelta(minutes=10)).isoformat()
}
Path("outputs/demo-choice-request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2))
PY
python3 -m power_trading_agent decide --risk outputs/risk-configured/risk.json --request outputs/demo-choice-request.json --output outputs/recorded-choice
```

### 7.4 单独导入实际值复盘 / Review with separate outcomes

此处复用第 7.1 节生成的虚构实际值。真实接入前仍需完成正式规则及数据适配，不能把私有真实资料改名为 synthetic 来绕过边界。

This command reuses the fictional outcomes generated in Section 7.1. Real use still requires validated rules and data adapters; relabeling private operating data as synthetic does not provide that implementation.

```bash
python3 -m power_trading_agent review --risk outputs/risk-configured/risk.json --decision outputs/recorded-choice/decision.json --actuals outputs/review-day-demo/review/actuals.json --output outputs/recorded-review
```

若有独立执行输入，增加 `--execution path/to/execution.json`。其内容需要完整同期间 `hours`、`q`、`energy_unit="MWh"`、`source`、`available_time`，不能用空文件表示零偏差。没有该参数时，复盘明确保留执行未知。

With a separate execution input, add `--execution path/to/execution.json`. It must contain exactly matching `hours`, a complete `q` curve, `energy_unit="MWh"`, `source` and `available_time`; an empty file is not evidence of zero deviation. Without the argument, execution remains unknown.

### 7.5 登记下一次实验 / Register the next experiment

下面只登记“缩小动作幅度”的未来实验，并给候选规格计算哈希。日期来自已生成复盘的资料可得时点，确保先复盘、后登记、再测试；不会生成测试结果。

The following registers a future smaller-action experiment and hashes its candidate specification. Dates follow the review-data availability time, preserving review → registration → testing. No test results are produced.

```bash
python3 - <<'PY'
import json
from datetime import datetime, timedelta
from pathlib import Path
from power_trading_agent.contracts import digest

review = json.loads(Path("outputs/recorded-review/review.json").read_text())
registered = datetime.fromisoformat(review["review_data_available_time"]) + timedelta(hours=1)
candidate = {"max_abs_k_deviation": 0.08, "grid_step": 0.02, "spread_threshold": 5}
proposal = {
    "hypothesis": "Smaller actions reduce worst daily additional loss in a later period",
    "change": "Freeze this candidate specification; keep forecasts and other limits unchanged",
    "registered_at": registered.isoformat(),
    "test_start": (registered + timedelta(days=1)).isoformat(),
    "test_end": (registered + timedelta(days=31)).isoformat(),
    "metric": "worst daily additional loss and mean cost on the untouched test period",
    "baseline": "the frozen existing candidate specification and selection rule",
    "acceptance": "Lower worst daily loss, no higher mean cost, and no new limit breaches",
    "frozen_candidate_hash": digest(candidate)
}
Path("outputs/experiment-candidate.json").write_text(json.dumps(candidate, indent=2))
Path("outputs/experiment-proposal.json").write_text(json.dumps(proposal, indent=2))
PY
python3 -m power_trading_agent experiment-register --proposal outputs/experiment-proposal.json --reviews outputs/recorded-review/review.json --output outputs/registered-experiment.json
```

报告和计划哈希用于发现内容变化，风控校验还会从冻结输入重新计算，防止只改指标再重算哈希。然而哈希不认证来源、操作人身份或声称的历史时间。需要独立的平台回执/档案证据才能提高证据等级。

Report and plan hashes detect content changes; risk verification also recomputes results from frozen inputs to reject altered metrics with updated hashes. Hashes do not authenticate sources, operators or claimed historical timestamps. Independent platform receipts or archival evidence are needed for stronger provenance.

## 8. 方法来源与后续边界 / Method sources and remaining boundaries

GAMS 官方资料区分事前决策与揭示不确定性后的决策，并把期望值、VaR/CVaR 放在概率模型中。这支持本模块把无概率压力测试与概率风险度量分开；本实现未调用 GAMS，也不是随机规划求解器。 / GAMS distinguishes decisions before and after uncertainty is revealed and defines expectation and VaR/CVaR using probability models. This informs our separation of stress tests from probabilistic risk measures. This implementation neither calls GAMS nor solves a stochastic program. [GAMS Stochastic Programming](https://www.gams.com/latest/docs/UG_EMP_SP.html)

GAMS 的示例按场景概率比较事前最优和完全信息下的结果来计算 EVPI。本模块只有有限候选在一次实际结果上的事后差额，因此明确不称 EVPI。 / The GAMS example computes EVPI using probability-weighted comparisons of here-and-now and perfect-information outcomes. Our finite-candidate comparison on one realization does not provide that quantity. [GAMS AIRSP3](https://www.gams.com/latest/emplib_ml/libhtml/emplib_airsp3.html)

scikit-learn 的时间序列切分文档解释了为什么应避免用未来训练、过去测试；数据泄漏指南要求测试信息不参与模型选择或拟合。本模块据此保留信息可得时点、冻结候选，并把复盘后的改进留给新期间验证；来源时间仍需业务证据核实。 / scikit-learn's time-series split documentation explains why training on the future and testing on the past is inappropriate; its leakage guidance keeps test information out of fitting and selection. This motivates availability timestamps, frozen candidates and later evaluation of review-generated changes. Source timestamps still require evidence. [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html), [Common pitfalls: data leakage](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage)

月模式目前只是把同一合成日前/实时账式扩展到完整月度时域，并不代表实现了月度竞价、合同分解、真实考核或正式月度结算。下一步需要按业务地区和主体核实规则、补充真实客户与持仓版本、联合极端路径、资金时间轴和独立执行证据，再做持续的样本外验证。当前输出始终为 `research_only`，没有证明未来策略效果。

Monthly mode extends the same synthetic DA/RT accounting across a full month. It does not implement monthly auctions, contract allocation, formal assessments or certified monthly settlement. Further work requires applicable rules, versioned customer/position inputs, joint extreme paths, cash timing, independent execution evidence and sustained out-of-sample evaluation. Outputs remain `research_only`; future strategy performance is unproven.
