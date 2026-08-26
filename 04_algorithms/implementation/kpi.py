# -*- coding: utf-8 -*-
"""KPI 计算与 kpi_summary 行组装（符合 04_algorithms/算法实现接口.md 输出契约）。

kpi_summary 列：
  ModelID, ScenarioID, Cost_CNY, Carbon_tCO2, RenewableUtilization,
  MeanLatency_ms, P95Latency_ms, PeakGridPurchase_MW, GridPurchaseStd_MW,
  Violations, Runtime_s, LowerBound_or_Gap
  （扩展列：GrossCost_CNY = Cost_CNY 即购电成本；SellRevenue_CNY；NetCost_CNY = 购电-售电收入）

口径：
  - Cost_CNY = sum(GridPurchase*price)（购电成本，含 Hour 2406；与模型“购电成本…结算”一致）；
  - NetCost_CNY = Cost_CNY - sum(GridSell*SellPrice)（优化目标使用净成本，报告时另列）；
  - Carbon_tCO2 = sum(GridPurchase * CarbonIntensity)；
  - RenewableUtilization = sum(RE_direct+RE_charge+RE_sell) / sum(RE_avail)；
  - 时延为平均/P95 的单向网络时延（未加权）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data_loader import HOURS_ENERGY, REGIONS, Problem


def task_latency_stats(problem: Problem, schedule: pd.DataFrame) -> dict:
    """由排程表计算平均/P95 网络时延。优先使用排程表 NetworkLatency_ms 列。"""
    if "NetworkLatency_ms" in schedule.columns:
        lat = schedule["NetworkLatency_ms"].astype(float).to_numpy()
    else:
        lat = np.array([
            problem.latency.get((r["SourceRegion"], r["TargetRegion"]), np.nan)
            for _, r in schedule.iterrows()
        ])
    return {
        "MeanLatency_ms": float(np.nanmean(lat)),
        "P95Latency_ms": float(np.nanpercentile(lat, 95)),
    }


def energy_kpis(problem: Problem, energy: pd.DataFrame) -> dict:
    """由 energy_schedule 汇总 KPI（全部区域、全部 0..2406 小时）。"""
    cost = 0.0          # 购电成本（毛）
    revenue = 0.0       # 售电收入
    co2 = 0.0
    re_used = 0.0
    re_avail = 0.0
    peak = 0.0
    purchases = []
    for r in REGIONS:
        sub = energy[energy["Region"] == r].sort_values("Hour")
        price = problem.price(r)
        carbon = problem.carbon_intensity(r)
        gp = sub["GridPurchase_MW"].to_numpy(dtype=float)
        gs = sub["GridSell_MW"].to_numpy(dtype=float)
        cost += float(np.sum(gp * price))
        revenue += float(np.sum(gs * problem.sell_price(r)))
        co2 += float(np.sum(gp * carbon))
        re_used += float(np.sum(sub["RenewableDirect_MW"] + sub["RenewableCharge_MW"]
                                + sub["RenewableSell_MW"]))
        re_avail += float(np.sum(problem.re_avail(r)))
        peak = max(peak, float(np.max(gp)))
        purchases.extend(gp.tolist())
    return {
        "Cost_CNY": cost,
        "SellRevenue_CNY": revenue,
        "NetCost_CNY": cost - revenue,
        "Carbon_tCO2": co2,
        "RenewableUtilization": re_used / re_avail if re_avail > 0 else 0.0,
        "PeakGridPurchase_MW": peak,
        "GridPurchaseStd_MW": float(np.std(purchases)),
    }


def make_kpi_row(model_id: str, scenario_id: str, problem: Problem,
                 schedule: pd.DataFrame | None, energy: pd.DataFrame,
                 violations: int, runtime_s: float,
                 bound_or_gap: str) -> dict:
    """组装一行 kpi_summary。schedule 为 None 时（如纯能源实验）时延填 NaN。"""
    row = {
        "ModelID": model_id,
        "ScenarioID": scenario_id,
        "MeanLatency_ms": np.nan,
        "P95Latency_ms": np.nan,
    }
    if schedule is not None:
        row.update(task_latency_stats(problem, schedule))
    row.update(energy_kpis(problem, energy))
    row.update({
        "Violations": violations,
        "Runtime_s": round(runtime_s, 3),
        "LowerBound_or_Gap": bound_or_gap,
    })
    return row
