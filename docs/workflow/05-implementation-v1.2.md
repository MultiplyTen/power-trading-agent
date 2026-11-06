# v1.2 实施记录 / Implementation record

- 日期 / Date: 2026-11-06
- 版本 / Version: 1.2.0
- 范围 / Scope: synthetic multidimensional risk and decision review, extending v1.1.

| 需求 / Requirement | 实际产物 / Artifact | 验收 / Verification |
| --- | --- | --- |
| R01 各类风险分别设限 / Independent dimensions | risk.py: nine metrics and three monotonic profiles; defaults unset | Each metric independently blocks choices |
| R02 多场景与极端 / Stress scenarios | risk.py: crossed load/DA/RT and seven event shocks plus spread reversal | 35 default scenarios; no probability claims |
| R03 人工决定 / Human choice | dashboard.py, review.py: explicit choice, rationale, bound hashes | Browser export followed by CLI validation; no execution |
| R04 当时信息 / Frozen information | Strict known-only context and availability checks | Future evidence rejected; altered actuals cannot change frozen references |
| R05 复盘三视角 / Three perspectives | review.py: chosen, ex-ante references, restricted hindsight candidate | Same realized inputs and frozen admissible set; empty set stays empty |
| R06 区分执行 / Execution distinction | Exact execution hours/units; absent evidence stays unknown | Wrong dates, ordering and kWh rejected |
| R07 日/月周期 / Cadence | Complete 24-hour day or complete calendar month, one preceding origin | Month completeness, leap year, daily loss despite monthly netting |
| R08 持续改进 / Learning | Proposed experiments bound to later untouched periods | Backdated, overlapping or duplicate review registration rejected |
| R09 可用交付 / Usable delivery | Local HTML, CLI, bilingual guide, default templates | 141 tests, guide execution, package and browser checks |

方法与接口详见 [指南](../risk-review-guide.md) 和 [契约](../risk-review-contracts.md)。实际证据和业务限制见 [验证记录](../validation/v1.2-validation.md)。

See the [guide](../risk-review-guide.md), [contracts](../risk-review-contracts.md), and [validation record](../validation/v1.2-validation.md) for implemented behavior, executed evidence and remaining business limitations.
