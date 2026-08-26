# Status Board

| Module | Status | Owner | Latest artifact | Remaining gate |
|---|---|---|---|---|
| problem | FROZEN | lead + data audit | `07_decisions/canonical_fact_ledger.yaml` | none |
| data | GATES PASSED | data audit | `02_data/quality/two_gate_audit.md` | optimization inputs still pending |
| model | FROZEN | lead + model audit | `03_models/统一双柔性模型_复审修订版.md` | solve four cells on `x_base` with one export policy |
| rationale | VERIFIED FOR MODEL CHOICE | dedicated rationale + opposing review | `03_models/rationale/model_rationale.md` | empirical advantages remain `EXPECTED` until solve |
| algorithm | INTERFACE FROZEN | lead | `04_algorithms/算法实现接口.md` | implement Q1-Q4 |
| validation | BOUNDARY PASSED | opposing review | `05_validation/当前状态与验收.md` | optimization result checks pending |
| paper | DRAFT / RESULTS BLOCKED | paper handoff | `06_paper/数据洞察与作图清单.md` | do not make numerical claims before solve |

Current status: model semantics `FROZEN`; boundary gates `PASSED WITH CONDITIONS`; `x_base` task baseline `PASSED`; Q1 final prediction and Q2-Q4 numerical optimization `PENDING`; paper numerical claims `BLOCKED BY SOLVE`. `S_K` is not yet a result. Q3 remains an external fixed-load storage experiment, while four-cell `M01` uses `x_base` load. Before optimization, `M00_fair/M10/M01-xbase/M11/Q3-B3ref` must declare the same `ExportPolicy=PERMIT_RE_ONLY`; the Q1-only `M00_Q1` remains no-export.
