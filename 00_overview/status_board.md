# Status Board

| Module | Status | Owner | Latest artifact | Remaining gate |
|---|---|---|---|---|
| problem | FROZEN | lead + data audit | `07_decisions/canonical_fact_ledger.yaml` | none |
| data | GATES PASSED | data audit | `02_data/quality/two_gate_audit.md` | none |
| model | FROZEN | lead + model audit | `03_models/统一双柔性模型_复审修订版.md` | none |
| rationale | VERIFIED FOR MODEL CHOICE | dedicated rationale + opposing review | `03_models/rationale/model_rationale.md` | empirical claims now backed by solve |
| algorithm | REVISION IN PROGRESS | algorithm handoff | `04_algorithms/results/` | align four cells to `ExportPolicy=PERMIT_RE_ONLY`; emit run_manifest/witness/gap; S_K with M00_fair baseline |
| validation | V1 CHECKS PASSED; NEW GATES PENDING | opposing review | `05_validation/result_evidence_gate.md` | re-run energy/task checks under unified export policy |
| paper | NUMBERS BLOCKED UNTIL REVISION | paper handoff | `06_paper/数据洞察与作图清单.md` | do not cite v1 numbers for four-cell claims |

Current status: model semantics `FROZEN`（复审修订版）; boundary gates `PASSED`; `x_base` task baseline `PASSED`;
v1 algorithm results were delivered under the old semantics (M00 no-export), which is now `M00_Q1` (Q1-only).
The four-cell fair baseline `M00_fair` and all treatment cells must use identical
`ExportPolicy=PERMIT_RE_ONLY` plus attachment export caps and sell prices; `S_K` uses `M00_fair` as baseline.
Until regenerated outputs pass the result-evidence gate, four-cell improvement rates, `S_K` and Pareto
claims remain `BLOCKED`. B_ref (attachment official operation) remains the reference, not an optimization result.