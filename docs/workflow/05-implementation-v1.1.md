# v1.1 实施记录 / Implementation record

- 日期 / Date: 2026-11-03
- 版本 / Version: 1.1.0
- 范围 / Scope: synthetic local research, one portfolio, day-ahead replay.

| 任务 / Task | 实际产物 / Artifact | 状态 / Status |
| --- | --- | --- |
| T01 数据契约与截点 / Data and cutoff | contracts.py, data.py | Implemented; version order, source identity, units and missing-cell gates |
| T02 组合状态 / Portfolio state | portfolio.py | Implemented; SQLite revisions, as-of, intent/trade separation, customer scope |
| T03 策略与计算 / Policies and calculation | economics.py | Implemented; three rule baselines, synthetic settlement, stress and weighted probability arithmetic |
| T04 协调与恢复 / Coordination and recovery | runner.py | Implemented; frozen input, generation checks, cancellation, version-bound selection APIs, resume |
| T05 事件与工具 / Events and tools | events.py, tools.py, __main__.py | Implemented; conservative template parser, allowlisted JSON tools, local CLI |
| T06 回放与验收 / Replay and acceptance | synthetic.py, acceptance.py, tests/ | Executed results in ../validation/v1.1-validation.md |
| T07 使用与参考 / Usage and references | README.md, v1.1-contracts.md, v1.1-methodology.md | Bilingual entrypoint and methodology; historical design retained |

## 实施取舍 / Implementation decisions

- C01：公开演示采用原创合成数据与结算适配器；不复用客户、合同或凭据。Synthetic inputs make the public demonstration reproducible without private business data.
- C02：先实现确定性协调与可调用服务；模型宿主接入仍需单独集成验收。A deterministic coordinator makes numerical and workflow checks independent of a hosted LLM.
- C03：默认只运行压力情景；概率接口提供数学计算，不把标志位称为校准证据。Default stress tests do not imply calibrated probabilities.
- C04：候选策略是价差方向规则及半幅规则，不冒称约束优化最优解。Policies are explainable baselines, not optimizers.
- C05：针对审查发现的修订排序、恢复输入一致性、CSV重复小时及非有限数漏洞，补充回归检查。Review fixes have corresponding regression coverage.

## 尚未完成的业务能力 / Remaining business work

真实数据适配与业务覆盖核查、广东适用结算规则、生产风险金额、训练模型及校准证据、约束优化、通用自然语言理解、实际 DeepSeek/LLM 宿主连接、外部平台回执和对账、长期影子运行均未完成。

Real-data adapters and coverage, applicable Guangdong settlement, operating risk budgets, trained models and calibration, constrained optimization, general language understanding, a live DeepSeek/LLM host, exchange receipts/reconciliation, and sustained shadow operation remain future work.

本版本的功能验收不能替代上述业务验收；`business_ready=false`, `production_approved=false`, `deployed=false`。

Technical acceptance does not replace business acceptance. See the separate validation record for executed evidence and exact limits.
