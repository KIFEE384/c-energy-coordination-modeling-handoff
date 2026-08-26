# Decision Log

## DEC-009 Algorithm handoff: cost metric, and M00_Q1/M00_fair alignment

- Date: 2026-08-26
- Owner: algorithm teammate (assisted); amended after lead's DEC-008 export-policy synchronization
- Affected questions: Q2, Q3, Q4 and the four-cell comparison
- Decision: the reported `Cost_CNY` is the **gross grid-purchase cost** (sum of GridPurchase*price over
  hours 0..2406, matching the model's "购电成本…结算" wording); sell revenue and net cost are reported
  as extension columns (`SellRevenue_CNY`, `NetCost_CNY`). Optimization objectives minimize net cost
  (purchase minus revenue), equivalent to maximizing renewable direct use and export.
  Per DEC-008, the v1 no-export M00 baseline is retained only as the Q1 explanatory state `M00_Q1`
  (`ExportPolicy=FORBID`, not part of four-cell attribution); the four-cell fair baseline is
  `M00_fair` (`ExportPolicy=PERMIT_RE_ONLY`, identical export caps/sell prices to M10/M01-xbase/M11).
- Consequences: only `M00_fair` may appear in four-cell improvement rates and `S_K`. All runs record
  `ExportPolicy` and input sources in `run_manifest`; zero-purchase/zero-carbon/high-revenue values are
  backed by `witness_extremes.csv`. B_ref remains the attachment's official operation (2.23B CNY gross
  purchase, 2.05M tCO2, RE utilization 31.1%) and is a reference, not an optimization result.
- Validation: energy cells pass conservation/SOC/mutual-exclusion/boundary assertions; the
  result-evidence gate requires regenerated outputs under the unified export policy.

## DEC-001 Audit before repair

- Date: 2026-08-26
- Owner: lead agent
- Affected questions: Q1-Q4
- Evidence: independent data and model audits
- Decision: preserve the original model files as `*_待修订.md` and issue a separate review report.
- Consequences: algorithm implementation remains blocked until P0/P1 findings close.

## DEC-002 Hard constraints remain non-negotiable

- Date: 2026-08-26
- Owner: lead agent
- Affected questions: Q1-Q4
- Decision: SLA, deadlines, GPU/IT/facility capacity, grid boundaries, SOC bounds, and terminal state remain hard constraints; they cannot be traded against cost or carbon.
- Validation: listed in `05_validation/多Agent复审报告.md`.

## DEC-003 Q1 no-migration baseline

- Date: 2026-08-26
- Owner: lead
- Affected questions: Q1, Q2, Q4
- Evidence: Q2 explicitly highlights migration; opposing review found that allowing it in Q1 invalidates a migration main-effect claim.
- Decision: Q1 fixes `TargetRegion=SourceRegion` and outputs the flexible no-migration schedule `x_Q1`; non-real-time tasks may be delayed. A separate attachment-reproduction baseline `x0` fixes every task at `ArrivalHour`. Q2/Q4 first open the directed-latency feasible set.
- Alternatives rejected: allow Q1 migration. It remains a sensitivity variant only and cannot be mixed with the M00/M10 comparison.
- Validation: `05_validation/acceptance_tests.md`.

## DEC-004 Q2 renewable export

- Date: 2026-08-26
- Owner: lead
- Affected questions: Q2, Q4
- Decision: Q2 has no storage but permits renewable export. Enforce renewable partition and `GridSell=RenewableSell`; grid purchase cannot be resold.
- Validation: per-hour conservation, export caps and mutual exclusion tests.

## DEC-005 Main 2406 convention

- Date: 2026-08-26
- Owner: lead
- Affected questions: Q3, Q4
- Decision: main results operate energy flows in hours 0--2406; `SOC_-1=InitialSOC` and `SOC_2406` is the end-of-hour terminal state.
- Evidence: storage convention explicitly says end-of-hour; Closure_2400_2406 contains nonzero Hour 2406 load, renewable and export fields.
- Consequences: all main cost, carbon and renewable KPIs include Hour 2406; tasks still cannot occupy Hour 2406.
- Validation: `02_data/quality/two_gate_audit.md`; RegionE Hour 0 source SOC residual is logged, not repaired.

## DEC-006 Four-cell comparability gate (passed)

- Date: 2026-08-26
- Owner: lead
- Affected questions: Q3, Q4
- Decision: `B_ref`, `B3_ref`, and M00 remain separately labelled. `B3_ref` equals the arrival-start `x0` facility load within source rounding, but `x0` fails the GPU-capacity check (44 violations), so it cannot be M00/M01. Generate a feasible common baseline `x_base` from Q1, use it for M00/M01/M10/M11, and keep Q3 as an external fixed-load experiment.
- Validation: max error `3.3333448e-7 MW`, MAE `2.7395816e-10 MW`, RMSE `9.1994657e-9 MW` over 14,442 region-hours.

## DEC-007 Feasible common baseline (passed)

- Date: 2026-08-26
- Owner: lead
- Affected questions: Q1, Q2, Q4 and the four-cell comparison
- Decision: freeze `02_data/processed/x_base_task_schedule.csv` as the common hard-constraint task baseline. It fixes target region to source region, starts real-time tasks at arrival, and delays flexible tasks only as needed using deadline-prioritized earliest-feasible placement.
- Validation: 50,000/50,000 tasks scheduled; 90 flexible tasks delayed; zero unique-assignment, release, real-time, deadline, Hour-2406, local-SLA, GPU, IT and facility violations. Maximum GPU utilization is 99.9931%.
- Consequences: use `x_base` for M00/M01 and as the closed-flexibility reference for M10/M11. Keep `x0` only for attachment load reproduction and keep Q3 as an external fixed-load experiment. `S_K` still requires all four optimization cells to be solved and validated.

## DEC-008 Export-policy synchronization

- Date: 2026-08-26
- Owner: lead + independent semantic review
- Affected questions: Q1-Q4
- Evidence: `03_models/统一双柔性模型_复审修订版.md`; `05_validation/semantic_design_gate.md`.
- Decision: Set `ExportPolicy=PERMIT_RE_ONLY` for `M00_fair`, `M10`, `M01-xbase`, `M11`, and `Q3-B3ref`. These runs use identical attachment `MaxGridExport`, `SellLimit`, and sell-price inputs; `GridSell=RenewableSell`; grid purchase cannot be resold. `M00_Q1` keeps `ExportPolicy=FORBID` because it only explains Q1 and does not enter four-cell attribution.
- Alternatives rejected: compare a no-export M00 with export-enabled treatments; this changes both a policy boundary and the flexibility factor, so neither improvement rates nor `S_K` are identifiable.
- Consequences: every run must record the policy and input sources in `run_manifest`. Q3 remains an independent fixed-load result and cannot be compared directly with `M01-xbase` even though their energy boundary is synchronized.
- Validation: require identical export-policy fields and sources across the four treatment rows, then re-evaluate energy schedules and KPIs.
