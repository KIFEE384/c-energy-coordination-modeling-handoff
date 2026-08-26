# -*- coding: utf-8 -*-
"""结果证据辅助：哈希计算与 witness 生成（result-evidence gate）。

哈希约定：
  - TaskScheduleHash: task_schedule.csv 字节的 SHA-256；
  - FacilityLoadHash: 由任务排程与非 AI 负荷派生的逐区域逐时设施负荷数组（round 6 位）的 SHA-256；
  - EnergyScheduleHash: energy_schedule.csv 字节的 SHA-256；
  - CodeRevision: git 提交短哈希（无 git 时取 'local'）。
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from data_loader import HOURS_ENERGY, REGIONS, Problem


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def sha256_df(df: pd.DataFrame) -> str:
    return sha256_bytes(pd.util.hash_pandas_object(df, index=True).values.tobytes())


def code_revision() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2],
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "local"


def facility_load_hash(problem: Problem, schedule: pd.DataFrame) -> str:
    """逐区域逐时设施负荷数组的哈希（四格共同口径）。"""
    fac = problem.facility_load_from_schedule(schedule)
    arr = np.concatenate([np.round(fac[r], 6) for r in REGIONS])
    return sha256_bytes(arr.tobytes())


# ----------------------------------------------------------------------
# witness_extremes.csv 生成
# ----------------------------------------------------------------------
def build_witness_rows(problem: Problem, energy: pd.DataFrame) -> list[dict]:
    """生成区域-小时 witness 行：
    - ZERO_PURCHASE / ZERO_CARBON：全时域购电（或碳排）为零的证明（区间统计 + 极值）；
    - HIGH_REVENUE：售电收入最高的区域-小时样例；
    - DEFICIT：RE 缺口小时（设施负荷 > 可用新能源）；
    - PEAK_PURCHASE：购电峰值区域-小时。
    """
    rows = []
    sub = energy.sort_values(["Region", "Hour"]).reset_index(drop=True)
    total_rh = len(sub)
    gp = sub["GridPurchase_MW"].to_numpy(dtype=float)
    # 售电收入按区域真实售价
    rev = np.zeros(total_rh)
    for r in REGIONS:
        mask = (sub["Region"] == r).to_numpy()
        rev[mask] = sub.loc[mask, "GridSell_MW"].to_numpy(dtype=float) * problem.sell_price(r)

    if float(np.max(gp)) <= 1e-6:
        rows.append({"Kind": "ZERO_PURCHASE", "ModelRegionHour": "all",
                     "Value_MW_or_CNY": 0.0,
                     "Evidence": f"全部 {total_rh} 个区域-小时 GridPurchase=0（max={np.max(gp):.2e} MW）"})
    else:
        h = int(np.argmax(gp))
        rows.append({"Kind": "PEAK_PURCHASE",
                     "ModelRegionHour": f"{sub.iloc[h]['Region']} Hour {sub.iloc[h]['Hour']}",
                     "Value_MW_or_CNY": float(np.max(gp)),
                     "Evidence": "峰值购电区域-小时"})

    # 碳排为零的证明（购电为零则碳排为零，口径一致）
    carbon = np.zeros(total_rh)
    for r in REGIONS:
        mask = (sub["Region"] == r).to_numpy()
        carbon[mask] = gp[mask] * problem.carbon_intensity(r)[sub.loc[mask, "Hour"].to_numpy(dtype=int)]
    if float(np.max(np.abs(carbon))) <= 1e-6:
        rows.append({"Kind": "ZERO_CARBON", "ModelRegionHour": "all",
                     "Value_MW_or_CNY": 0.0,
                     "Evidence": f"全部 {total_rh} 个区域-小时购电为零，故碳排为零（口径：Carbon=GridPurchase*Intensity）"})

    # 高售电收入
    if float(np.max(rev)) > 0:
        idx = np.argsort(rev)[-5:][::-1]
        for i in idx:
            rows.append({"Kind": "HIGH_REVENUE",
                         "ModelRegionHour": f"{sub.iloc[i]['Region']} Hour {sub.iloc[i]['Hour']}",
                         "Value_MW_or_CNY": round(float(rev[i]), 2),
                         "Evidence": f"GridSell={sub.iloc[i]['GridSell_MW']:.1f} MW × SellPrice={problem.sell_price(sub.iloc[i]['Region'])[0]:.2f} CNY/MWh"})

    # RE 缺口
    for r in REGIONS:
        pue = problem.capacity[r]["PUE"]
        fac = pue * (problem.non_ai_load(r)
                     + sub.loc[sub["Region"] == r, "AI_IT_Load_MW"].to_numpy(dtype=float))
        deficit = np.maximum(fac - problem.re_avail(r), 0.0)
        for h in np.nonzero(deficit > 1e-3)[0][:5]:
            rows.append({"Kind": "DEFICIT",
                         "ModelRegionHour": f"{r} Hour {int(h)}",
                         "Value_MW_or_CNY": round(float(deficit[h]), 2),
                         "Evidence": f"设施负荷 {fac[h]:.1f} MW > 可用新能源 {problem.re_avail(r)[h]:.1f} MW"})
    return rows
