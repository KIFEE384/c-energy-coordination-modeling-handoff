# Conflict Log

## CONFLICT-001 Q1 migration boundary (resolved)

- Evidence for fixed source: Q2 explicitly introduces task migration as a decision and Q1 is described as a basic schedule.
- Evidence for allowing migration: network latency is listed for Q1 and all task schedules must satisfy latency.
- Resolution: DEC-003 fixes source region in Q1 as a declared baseline assumption and opens migration only in Q2/Q4.

## CONFLICT-002 Q2 grid selling (resolved)

- Evidence for disabling: Q2 is designed to isolate migration/start-time effects and does not introduce storage decisions.
- Evidence for allowing: the unified renewable-utilization definition includes export and the data contain sell prices/export boundaries.
- Resolution: DEC-004 permits renewable export but disables storage; `GridSell=RenewableSell`, and the unified renewable-utilization denominator/numerator are used.

## CONFLICT-003 Hour 2406 (resolved)

- Confirmed: tasks cannot occupy hour 2406; storage terminal state is evaluated at 2406.
- Resolution: DEC-005 uses operational hours 0--2406, `SOC_-1=InitialSOC`, and end-of-hour `SOC_2406`; all costs, carbon and renewable KPIs include Hour 2406. Tasks remain excluded from Hour 2406.
