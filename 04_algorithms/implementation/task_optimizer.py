# -*- coding: utf-8 -*-
"""M10（Q2）任务层优化器：开放时延可行迁移与时移，关闭储能。

设计（04_algorithms/算法实现接口.md 第 3 节）：
  - 静态影子成本：基于 x_base 负荷判定各 (区域, 小时) 的新能源富余/缺口。
    富余小时新增 AI 负荷边际购电成本与边际碳排为 0（绿电直供）；缺口小时为
    price / carbon intensity。
  - 贪心指派：按类型（训练 > 批量 > 实时）与截止期排序；对每个任务在可行区域内
    按候选启动点（影子成本 + lambda*碳价 标量化后的前 K 个 + 最早/最晚点）评分，
    选择第一个满足 GPU/IT/设施容量的候选。
  - 局部搜索：对边际成本贡献最大的任务做移除-重排（LNS 轻量版），多轮迭代。
  - 多目标：不同 lambda 生成近似非支配解（加权标量化，诚实标记为近似，不称 Pareto 最优）。

硬约束（不可违反）：
  - 实时任务 StartHour == ArrivalHour；任务不可拆分不可抢占；EndHour <= 2406；
  - EndHour <= LatestFinishHour；目标区域属于 EligibleRegions（单向时延 <= MaxLatency）；
  - GPU / IT / 设施功率逐区域逐时不超限。

输出 task_schedule DataFrame，列：
  TaskID, SourceRegion, TargetRegion, StartHour, EndHour, NetworkLatency_ms,
  GPU_Demand, TaskType, ArrivalHour, LatestFinishHour
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from data_loader import HOURS_ENERGY, HOURS_TASK, REGIONS, TOL, Problem

CANDIDATES_PER_REGION = 8   # 每个区域按信号取前 K 个候选启动点


class TaskOptimizer:
    def __init__(self, problem: Problem, x_base: pd.DataFrame):
        self.p = problem
        self.capacity = problem.capacity
        self.power = problem.power

        # 初始负荷来自 x_base（实时任务固定；柔性任务可重排）
        self.gpu_load, self.ai_load = problem._loads_from_schedule(x_base)
        self.schedule: dict[str, dict] = {}
        for _, row in x_base.iterrows():
            tid = str(row["TaskID"])
            self.schedule[tid] = {
                "TaskID": tid,
                "TaskType": row["TaskType"],
                "SourceRegion": row["SourceRegion"],
                "TargetRegion": row["TargetRegion"],
                "ArrivalHour": int(row["ArrivalHour"]),
                "StartHour": float(row["StartHour"]),
                "EndHour": float(row["EndHour"]),
                "LatestFinishHour": float(row["LatestFinishHour"]),
                "GPU_Demand": float(row["GPU_Demand"]),
                "NetworkLatency_ms": float(row["NetworkLatency_ms"]),
            }
        self.meta = problem.tasks.set_index("TaskID")

        # 保存 x_base 快照（影子价格迭代时重置排程用）
        self.x_base_gpu = {r: self.gpu_load[r].copy() for r in REGIONS}
        self.x_base_ai = {r: self.ai_load[r].copy() for r in REGIONS}
        self.x_base_schedule = {tid: dict(row) for tid, row in self.schedule.items()}

        # 预计算任务属性与非 AI 负荷（避免热路径中的 pandas 查找）
        self.non_ai = {r: problem.non_ai_load(r) for r in REGIONS}
        self.lat = problem.latency
        self.task_type: dict[str, str] = {}
        self.arrival: dict[str, int] = {}
        self.eligible: dict[str, list[str]] = {}
        self.attr: dict[str, dict] = {}
        for tid, row in self.schedule.items():
            m = self.meta.loc[tid]
            dur = float(m["EstimatedDuration_min"]) / 60.0
            self.task_type[tid] = row["TaskType"]
            self.arrival[tid] = int(row["ArrivalHour"])
            self.attr[tid] = {
                "duration_h": dur,
                "demand": float(row["GPU_Demand"]),
                "unit_power": self.power[row["TaskType"]],
                "earliest": max(int(row["ArrivalHour"]), int(m["EarliestStartHour"])),
                "latest": math.floor(min(float(m["LatestFinishHour"]), 2406.0) - dur + TOL),
            }
            self.eligible[tid] = [
                r for r in REGIONS
                if self.lat.get((row["SourceRegion"], r), math.inf)
                <= float(m["MaxLatency_ms"]) + TOL
            ]

        # 静态影子成本（基于 x_base 负荷；RE 缺口按设施负荷口径判断，即需乘 PUE）
        self.shadow_cost = {r: np.zeros(HOURS_ENERGY) for r in REGIONS}
        self.shadow_carbon = {r: np.zeros(HOURS_ENERGY) for r in REGIONS}
        self._update_shadows()

    # ------------------------------------------------------------------
    def _prepare_ranks(self, lam: float) -> None:
        """预计算各区域小时信号排名（静态，供候选启动点快速筛选）。"""
        self.ranks = {}
        for r in REGIONS:
            sig = self.shadow_cost[r] + lam * self.shadow_carbon[r]
            self.ranks[r] = np.argsort(sig, kind="stable")

    def _update_shadows(self) -> None:
        """按当前排程负荷更新缺口小时影子价格（设施口径，保留历史缺口）。"""
        for r in REGIONS:
            pue = self.p.capacity[r]["PUE"]
            surplus = (self.p.re_avail(r)
                       - pue * (self.p.non_ai_load(r) + self.ai_load[r]))
            deficit = surplus < -TOL
            new_cost = np.where(deficit, self.p.price(r), 0.0)
            new_carbon = np.where(deficit, self.p.carbon_intensity(r), 0.0)
            self.shadow_cost[r] = np.maximum(self.shadow_cost[r], new_cost)
            self.shadow_carbon[r] = np.maximum(self.shadow_carbon[r], new_carbon)

    def _candidate_hours(self, task: dict, region: str, lam: float) -> list[int]:
        """候选启动小时：信号排名前 K 个 + 最早/最晚。"""
        a = self.attr[task["TaskID"]]
        earliest = a["earliest"]
        latest = a["latest"]
        if latest < earliest:
            return []
        rk = self.ranks[region][earliest:latest + 1]
        k = min(CANDIDATES_PER_REGION, latest - earliest + 1)
        idx = np.sort(np.argpartition(rk, k - 1)[:k])
        hours = [earliest + int(i) for i in idx]
        if earliest not in hours:
            hours.append(earliest)
        if latest not in hours:
            hours.append(latest)
        return hours

    def _score(self, task: dict, region: str, start: float, lam: float) -> float:
        """候选 (区域, 启动) 的标量化信号（overlap 加权）。"""
        a = self.attr[task["TaskID"]]
        end = start + a["duration_h"]
        score = 0.0
        sh_c = self.shadow_cost[region]
        sh_m = self.shadow_carbon[region]
        for hour in range(math.floor(start), min(HOURS_TASK, math.ceil(end) - 1) + 1):
            ov = max(0.0, min(end, hour + 1.0) - max(start, float(hour)))
            if ov > 0:
                score += ov * (sh_c[hour] + lam * sh_m[hour])
        return score

    def _feasible(self, task: dict, region: str, start: float) -> bool:
        a = self.attr[task["TaskID"]]
        demand = a["demand"]
        unit_power = a["unit_power"]
        cap = self.capacity[region]
        gpu_l = self.gpu_load[region]
        ai_l = self.ai_load[region]
        non_ai = self.non_ai[region]
        end = start + a["duration_h"]
        for hour in range(math.floor(start), min(HOURS_TASK, math.ceil(end) - 1) + 1):
            ov = max(0.0, min(end, hour + 1.0) - max(start, float(hour)))
            if ov <= 0:
                continue
            gpu = gpu_l[hour] + demand * ov
            ai = ai_l[hour] + demand * unit_power * ov
            it = non_ai[hour] + ai
            if gpu > cap["Available_GPU"] + TOL:
                return False
            if it > cap["Max_IT_Power_MW"] + TOL:
                return False
            if it * cap["PUE"] > cap["Max_Facility_Power_MW"] + TOL:
                return False
        return True

    def _place(self, task: dict, region: str, start: float) -> None:
        a = self.attr[task["TaskID"]]
        demand = a["demand"]
        unit_power = a["unit_power"]
        end = start + a["duration_h"]
        gpu_l = self.gpu_load[region]
        ai_l = self.ai_load[region]
        for hour in range(math.floor(start), min(HOURS_TASK, math.ceil(end) - 1) + 1):
            ov = max(0.0, min(end, hour + 1.0) - max(start, float(hour)))
            if ov > 0:
                gpu_l[hour] += demand * ov
                ai_l[hour] += demand * unit_power * ov
        tid = str(task["TaskID"])
        self.schedule[tid].update({
            "TargetRegion": region,
            "StartHour": start,
            "EndHour": end,
            "NetworkLatency_ms": self.lat.get((task["SourceRegion"], region), float("nan")),
        })

    def _remove(self, tid: str) -> None:
        row = self.schedule[tid]
        a = self.attr[tid]
        demand = a["demand"]
        unit_power = a["unit_power"]
        region = row["TargetRegion"]
        gpu_l = self.gpu_load[region]
        ai_l = self.ai_load[region]
        for hour in range(math.floor(row["StartHour"]),
                          min(HOURS_TASK, math.ceil(row["EndHour"]) - 1) + 1):
            ov = max(0.0, min(row["EndHour"], hour + 1.0) - max(row["StartHour"], float(hour)))
            if ov > 0:
                gpu_l[hour] -= demand * ov
                ai_l[hour] -= demand * unit_power * ov

    # ------------------------------------------------------------------
    def _task_order(self) -> list[str]:
        """处理顺序：实时固定；柔性任务按类型（训练>批量）与截止期排序。"""
        flex = []
        for tid, row in self.schedule.items():
            if self.task_type[tid] == "RealTimeInference":
                continue
            flex.append((self.task_type[tid],
                         float(self.meta.loc[tid, "LatestFinishHour"]),
                         self.arrival[tid], tid))
        order = {
            "AITraining": 0, "BatchInference": 1,
        }
        flex.sort(key=lambda x: (order.get(x[0], 9), x[1], x[2]))
        return [x[3] for x in flex]

    def _reoptimize_task(self, tid: str, lam: float) -> bool:
        """移除任务并重新指派。返回是否发生了改变。"""
        row = self.schedule[tid]
        src = row["SourceRegion"]
        if self.task_type[tid] == "RealTimeInference":
            # 实时任务到达即开工，仅可选区域
            candidates = []
            for r in self.eligible[tid]:
                lat = self.lat.get((src, r), math.inf)
                candidates.append((self._score(row, r, float(self.arrival[tid]), lam),
                                   lat, 0.0, r, float(self.arrival[tid])))
            candidates.sort(key=lambda x: (x[0], x[1], x[2]))
            self._remove(tid)
            for _, _, _, r, s in candidates:
                if self._feasible(row, r, s):
                    self._place(row, r, s)
                    return True
            # 回退原位置
            r0, s0 = row["TargetRegion"], row["StartHour"]
            self._place(row, r0, s0)
            return False

        self._remove(tid)
        r0, s0 = row["TargetRegion"], row["StartHour"]
        orig_score = (self._score(row, r0, s0, lam),
                      self.lat.get((src, r0), math.inf), s0)
        best = None
        for r in self.eligible[tid]:
            for s in self._candidate_hours(row, r, lam):
                if not self._feasible(row, r, s):
                    continue
                score = (self._score(row, r, s, lam),
                         self.lat.get((src, r), math.inf),
                         s)
                if best is None or score < best[0]:
                    best = (score, r, s)
        if best is None or best[0] >= orig_score:
            # 无可行候选或未改进：回退原位置（移除前原位置可行）
            self._place(row, r0, s0)
            return False
        self._place(row, best[1], best[2])
        return True

    # ------------------------------------------------------------------
    # 第三种方案：以 x_base 为基础的“缺口小时定向修复”
    # 只移动落在 RE 缺口小时上的柔性任务到经核实的富余位置，带防新增缺口守卫，
    # 保证真实缺口购电成本单调不增、不破坏 x_base 已验证的可行排布。
    # ------------------------------------------------------------------
    def _deficit_hours(self) -> list[tuple[str, int]]:
        """当前排程负荷下的 RE 缺口小时（设施口径）。"""
        out = []
        for r in REGIONS:
            pue = self.p.capacity[r]["PUE"]
            surplus = (self.p.re_avail(r)
                       - pue * (self.p.non_ai_load(r) + self.ai_load[r]))
            for h in np.nonzero(surplus < -TOL)[0]:
                out.append((r, int(h)))
        return out

    def _tasks_overlapping(self, region: str, hour: int) -> list[str]:
        """落在 (region, hour) 上的柔性任务（训练优先，按时长降序）。"""
        cands = []
        for tid, row in self.schedule.items():
            if self.task_type[tid] == "RealTimeInference":
                continue
            if row["TargetRegion"] != region:
                continue
            if row["StartHour"] < hour + 1.0 and row["EndHour"] > float(hour):
                cands.append((self.task_type[tid] == "AITraining",
                              -float(self.attr[tid]["demand"] * self.attr[tid]["duration_h"]),
                              tid))
        cands.sort(reverse=True)
        return [c[2] for c in cands]

    def _surplus_ok(self, tid: str, region: str, start: float) -> bool:
        """目标位置的全部占用小时在放置后仍保持 RE 富余（防新增缺口）。"""
        a = self.attr[tid]
        pue = self.p.capacity[region]["PUE"]
        end = start + a["duration_h"]
        for hour in range(math.floor(start), min(HOURS_TASK, math.ceil(end) - 1) + 1):
            ov = max(0.0, min(end, hour + 1.0) - max(start, float(hour)))
            if ov <= 0:
                continue
            fac = pue * (self.p.non_ai_load(region)[hour] + self.ai_load[region][hour]
                         + a["demand"] * a["unit_power"] * ov)
            if fac > self.p.re_avail(region)[hour] + TOL:
                return False
        return True

    def _repair_hour(self, region: str, hour: int, lam: float) -> int:
        """修复一个缺口小时：把重叠的柔性任务迁到富余位置。返回移动数。"""
        moved = 0
        for tid in self._tasks_overlapping(region, hour):
            if self._deficit_at(region, hour) <= TOL:
                break  # 该小时缺口已消除
            row = self.schedule[tid]
            src = row["SourceRegion"]
            orig_score = self._score(row, region, row["StartHour"], lam)
            if orig_score <= 0:
                # 静态信号为 0 不代表真实无成本，但仍尝试迁移以消除真实缺口
                pass
            best = None
            for r in self.eligible[tid]:
                for s in self._candidate_hours(row, r, lam):
                    if not self._feasible(row, r, float(s)):
                        continue
                    if not self._surplus_ok(tid, r, float(s)):
                        continue
                    score = (self._score(row, r, float(s), lam),
                             self.lat.get((src, r), math.inf), s)
                    if best is None or score < best[0]:
                        best = (score, r, float(s))
            if best is None:
                continue
            self._remove(tid)
            self._place(row, best[1], best[2])
            moved += 1
        return moved

    def _deficit_at(self, region: str, hour: int) -> float:
        pue = self.p.capacity[region]["PUE"]
        fac = pue * (self.p.non_ai_load(region)[hour] + self.ai_load[region][hour])
        return max(0.0, fac - self.p.re_avail(region)[hour])

    def optimize(self, lam: float, repair_passes: int = 8) -> pd.DataFrame:
        """主流程：以 x_base 排程为基础，多轮缺口小时定向修复。

        每轮：找出全部 RE 缺口小时，把重叠的柔性任务迁往核实富余的位置；
        直到无缺口或一轮无移动。实时任务保持到达即开工、来源区域。
        """
        self._prepare_ranks(lam)
        for _ in range(repair_passes):
            deficit_hours = self._deficit_hours()
            if not deficit_hours:
                break
            moved = 0
            for (r, h) in deficit_hours:
                moved += self._repair_hour(r, h, lam)
            if moved == 0:
                break
        return self.to_dataframe()

    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for tid in sorted(self.schedule, key=lambda x: int(x)):
            r = self.schedule[tid]
            rows.append({
                "TaskID": r["TaskID"],
                "SourceRegion": r["SourceRegion"],
                "TargetRegion": r["TargetRegion"],
                "StartHour": r["StartHour"],
                "EndHour": r["EndHour"],
                "NetworkLatency_ms": r["NetworkLatency_ms"],
                "GPU_Demand": r["GPU_Demand"],
                "TaskType": r["TaskType"],
                "ArrivalHour": r["ArrivalHour"],
                "LatestFinishHour": r["LatestFinishHour"],
            })
        return pd.DataFrame(rows)
