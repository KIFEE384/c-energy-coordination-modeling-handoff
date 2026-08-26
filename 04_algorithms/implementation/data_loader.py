# -*- coding: utf-8 -*-
"""共享数据加载与预处理模块（C题 面向算电协同的多目标调度优化研究）。

本模块统一加载六张附件 Excel，并构建：
  - 任务表（workload_trace）
  - 区域 GPU/功率容量（GPU_information）
  - 任务类型功率映射（power_mapping）
  - 单向网络时延矩阵（network_latency）
  - 区域逐时电价/碳强度/新能源/非AI负荷（region_time_data）
  - 储能参数（storage_information）

冻结口径（见 07_decisions/decision_log.md DEC-005 与 03_models/统一双柔性模型.md）：
  - 任务占用区间 [0, 2406)，即任务可在 2405 内结束于 2406，不得占用 Hour 2406；
  - 能源动作 t = 0..2406，共 2407 小时；
  - SOC_-1 = InitialSOC，SOC_t 为 Hour t 末状态，终端约束 SOC_2406 >= InitialSOC；
  - 成本、碳排、新能源利用率均包含 Hour 2406。

本模块不修改任何冻结事实；只负责读取与派生计算。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

HOURS_ENERGY = 2407          # 能源动作小时数 t = 0..2406
HOURS_TASK = 2406            # 任务可占用 [0, 2406)
REGIONS = ["RegionA", "RegionB", "RegionC", "RegionD", "RegionE", "RegionF"]
TOL = 1e-8
REAL_TIME_TYPE = "RealTimeInference"
FLEXIBLE_TYPES = ("BatchInference", "AITraining")


class Problem:
    """C 题统一数据问题实例。"""

    def __init__(self, data_dir: str | Path):
        data_dir = Path(data_dir)
        if not data_dir.is_dir():
            raise FileNotFoundError(f"数据目录不存在: {data_dir}")

        self.REGIONS = list(REGIONS)
        self.HOURS_ENERGY = HOURS_ENERGY
        self.HOURS_TASK = HOURS_TASK

        self.tasks: pd.DataFrame = pd.read_excel(data_dir / "workload_trace.xlsx", sheet_name=0)
        self.gpu_info: pd.DataFrame = pd.read_excel(data_dir / "GPU_information.xlsx", sheet_name=0)
        self.power_map: pd.DataFrame = pd.read_excel(data_dir / "power_mapping.xlsx", sheet_name=0)
        self.latency_df: pd.DataFrame = pd.read_excel(data_dir / "network_latency.xlsx", sheet_name=0)
        self.region_time: pd.DataFrame = pd.read_excel(data_dir / "region_time_data.xlsx", sheet_name=0)
        self.storage_df: pd.DataFrame = pd.read_excel(data_dir / "storage_information.xlsx", sheet_name=0)

        # ---- 容量 ----
        self.capacity: dict[str, dict] = {}
        for _, row in self.gpu_info.iterrows():
            self.capacity[row["Region"]] = {
                "Available_GPU": float(row["Available_GPU"]),
                "Max_IT_Power_MW": float(row["Max_IT_Power_MW"]),
                "PUE": float(row["PUE"]),
                "Max_Facility_Power_MW": float(row["Max_Facility_Power_MW"]),
            }

        # ---- 任务类型功率 ----
        self.power: dict[str, float] = {
            row["TaskType"]: float(row["GPU_Power_MW_per_EquivalentGPU"])
            for _, row in self.power_map.iterrows()
        }

        # ---- 单向时延矩阵 ----
        self.latency: dict[tuple[str, str], float] = {}
        for _, row in self.latency_df.iterrows():
            src = row["FromRegion"]
            dst = row["ToRegion"]
            self.latency[(src, dst)] = float(row["NetworkLatency_ms"])

        # ---- 区域逐时数据（按 (Region, Hour) 索引） ----
        rt = self.region_time.copy()
        rt["Hour"] = rt["Hour"].astype(int)
        rt["Region"] = rt["Region"].astype(str)
        self._rt = rt.set_index(["Region", "Hour"]).sort_index()
        # 校验 6 区域 x 2407 小时完整
        assert self._rt.shape[0] == 6 * HOURS_ENERGY, (
            f"region_time_data 应为 {6 * HOURS_ENERGY} 行，实际 {self._rt.shape[0]}"
        )

        # ---- 储能参数 ----
        self.storage: dict[str, dict] = {}
        for _, row in self.storage_df.iterrows():
            self.storage[row["Region"]] = {
                "StorageCapacity_MWh": float(row["StorageCapacity_MWh"]),
                "MinSOC_MWh": float(row["MinSOC_MWh"]),
                "InitialSOC_MWh": float(row["InitialSOC_MWh"]),
                "MaxChargePower_MW": float(row["MaxChargePower_MW"]),
                "MaxDischargePower_MW": float(row["MaxDischargePower_MW"]),
                "ChargeEfficiency": float(row["ChargeEfficiency"]),
                "DischargeEfficiency": float(row["DischargeEfficiency"]),
                "SellLimit_MW": float(row["SellLimit_MW"]),
                "MaxGridImport_MW": float(row["MaxGridImport_MW"]),
                "MaxGridExport_MW": float(row["MaxGridExport_MW"]),
            }

        # ---- 任务字段类型归一 ----
        t = self.tasks
        t["TaskID"] = t["TaskID"].astype(str)
        t["ArrivalHour"] = t["ArrivalHour"].astype(int)
        t["GPU_Demand"] = t["GPU_Demand"].astype(float)
        t["EstimatedDuration_min"] = t["EstimatedDuration_min"].astype(float)
        t["LatestFinishHour"] = t["LatestFinishHour"].astype(float)
        t["EarliestStartHour"] = t["EarliestStartHour"].astype(float)
        t["MaxLatency_ms"] = t["MaxLatency_ms"].astype(float)
        t["SourceRegion"] = t["SourceRegion"].astype(str)

    # ------------------------------------------------------------------
    # 逐时序列访问
    # ------------------------------------------------------------------
    def series(self, region: str, column: str) -> np.ndarray:
        """返回该区域 0..2406 的某一列（如 ElectricityPrice_CNY_per_MWh）。"""
        s = self._rt.loc[region, column].to_numpy(dtype=float)
        assert len(s) == HOURS_ENERGY
        return s

    def non_ai_load(self, region: str) -> np.ndarray:
        return self.series(region, "NonAI_IT_Load_MW")

    def baseline_ai_load(self, region: str) -> np.ndarray:
        """附件给定 AI IT 负荷（Q3 口径，对应到达即启动复现基准 x0 的 AI 负荷）。"""
        return self.series(region, "Baseline_AI_IT_Load_MW")

    def baseline_facility_load(self, region: str) -> np.ndarray:
        """Q3 固定设施负荷 = PUE * (Baseline_AI_IT_Load + NonAI_IT_Load)。"""
        pue = self.capacity[region]["PUE"]
        return pue * (self.baseline_ai_load(region) + self.non_ai_load(region))

    def re_avail(self, region: str) -> np.ndarray:
        return self.series(region, "AvailableRenewable_MW")

    def price(self, region: str) -> np.ndarray:
        return self.series(region, "ElectricityPrice_CNY_per_MWh")

    def sell_price(self, region: str) -> np.ndarray:
        return self.series(region, "SellPrice_CNY_per_MWh")

    def carbon_intensity(self, region: str) -> np.ndarray:
        return self.series(region, "CarbonIntensity_tCO2_per_MWh")

    # ------------------------------------------------------------------
    # 任务派生计算
    # ------------------------------------------------------------------
    def eligible_regions(self, task: pd.Series | dict) -> list[str]:
        """按任务 MaxLatency_ms 与单向时延矩阵筛出可行目标区域。"""
        src = task["SourceRegion"]
        limit = float(task["MaxLatency_ms"])
        return [r for r in REGIONS
                if self.latency.get((src, r), math.inf) <= limit + TOL]

    def task_power_mw(self, task: pd.Series | dict) -> float:
        """单任务 AI IT 功率（MW）= GPU_Demand * 单位功率。"""
        return float(task["GPU_Demand"]) * self.power[task["TaskType"]]

    @staticmethod
    def overlap(start_h: float, end_h: float, hour: int) -> float:
        """任务在小时 [hour, hour+1) 内的实际占用小时数（分钟级精度）。"""
        return max(0.0, min(end_h, hour + 1.0) - max(start_h, float(hour)))

    def task_hours(self, task: pd.Series | dict, start_h: float | None = None):
        """任务实际占用的 (hour, overlap) 序列。"""
        start = float(task["StartHour"] if start_h is None else start_h)
        duration = float(task["EstimatedDuration_min"]) / 60.0
        end = start + duration
        for hour in range(math.floor(start), min(HOURS_TASK, math.ceil(end) - 1) + 1):
            ov = self.overlap(start, end, hour)
            if ov > 0:
                yield hour, ov

    # ------------------------------------------------------------------
    # 由排程表计算区域逐时负荷
    # ------------------------------------------------------------------
    def _loads_from_schedule(self, schedule: pd.DataFrame):
        """由逐任务排程表累加 GPU 占用与 AI IT 功率。

        返回 (gpu_load, ai_it_load)：均为 {region: np.ndarray(2407)}。
        """
        gpu_load = {r: np.zeros(HOURS_ENERGY) for r in REGIONS}
        ai_load = {r: np.zeros(HOURS_ENERGY) for r in REGIONS}
        for _, task in schedule.iterrows():
            region = task["TargetRegion"]
            demand = float(task["GPU_Demand"])
            unit_power = self.power[task["TaskType"]]
            start = float(task["StartHour"])
            end = float(task["EndHour"])
            for hour in range(math.floor(start), min(HOURS_TASK, math.ceil(end) - 1) + 1):
                ov = self.overlap(start, end, hour)
                if ov > 0:
                    gpu_load[region][hour] += demand * ov
                    ai_load[region][hour] += demand * unit_power * ov
        return gpu_load, ai_load

    def facility_load_from_schedule(self, schedule: pd.DataFrame) -> dict[str, np.ndarray]:
        """设施负荷 P_fac = PUE * (NonAI + AI_IT)，按区域返回 0..2406 序列。"""
        _, ai_load = self._loads_from_schedule(schedule)
        fac = {}
        for r in REGIONS:
            pue = self.capacity[r]["PUE"]
            fac[r] = pue * (self.non_ai_load(r) + ai_load[r])
        return fac

    def ai_it_load_from_schedule(self, schedule: pd.DataFrame) -> dict[str, np.ndarray]:
        _, ai_load = self._loads_from_schedule(schedule)
        return ai_load

    # ------------------------------------------------------------------
    # 排程表读取
    # ------------------------------------------------------------------
    @staticmethod
    def load_task_schedule(path: str | Path) -> pd.DataFrame:
        df = pd.read_csv(path)
        df["TaskID"] = df["TaskID"].astype(str)
        for col in ("StartHour", "EndHour"):
            df[col] = df[col].astype(float)
        return df


def load_x_base(repo_root: str | Path) -> pd.DataFrame:
    """读取已冻结的 x_base 任务排程（02_data/processed/x_base_task_schedule.csv）。"""
    path = Path(repo_root) / "02_data" / "processed" / "x_base_task_schedule.csv"
    return Problem.load_task_schedule(path)
