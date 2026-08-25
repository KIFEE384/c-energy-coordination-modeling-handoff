# C题算电协同建模交接

This repository is the complete, auditable mathematical-modeling handoff for C题. Historical audits are retained, but current normative content is identified below. The 2406 gate, the `B3_ref`/`x0` load-identity gate, and the feasible common task baseline gate have passed. The arrival-start reconstruction `x0` is retained only for load identity because it has 44 GPU-limit violations; `x_base` is the hard-constraint task baseline. `S_K` remains blocked until M00/M01/M10/M11 are solved and validated on `x_base`.

## Agent / teammate reading order

**For any Agent, read first:** `00_overview/Agent总交接说明.md`, then `07_decisions/canonical_fact_ledger.yaml`, `03_models/统一双柔性模型.md`, `04_algorithms/算法实现接口.md`, and `05_validation/当前状态与验收.md`.

**For the algorithm teammate:** read `00_overview/建模手最终交接总结.md` sections “交给算法手” and `04_algorithms/算法实现接口.md`.

**For the modeling/paper teammate:** read `00_overview/建模手最终交接总结.md` sections “交给论文手” and `03_models/rationale/model_rationale.md`.

`05_validation/多Agent复审报告.md` is historical only. Its unresolved findings must not override the current decision log or current model files.

## Historical reading order

1. `00_overview/status_board.md`
2. `07_decisions/canonical_fact_ledger.yaml` and `decision_log.md`
3. `03_models/统一双柔性模型.md`
4. `03_models/rationale/model_rationale.md`
5. `04_algorithms/算法实现接口.md`
6. `05_validation/acceptance_tests.md`
7. `06_paper/`

The main branch is the stable handoff. Specialist work belongs on module/<name> branches.
