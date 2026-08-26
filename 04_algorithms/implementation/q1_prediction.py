# -*- coding: utf-8 -*-
"""Q1A 需求画像与预测（03_models/统一双柔性模型.md Q1A 口径）。

口径：
  - 按 (Region, TaskType) 与聚合层级构建逐小时序列：任务数、GPU 需求、GPU-hour、平均时长；
  - 时间切分：训练 0-2351，验证 2352-2375，测试 2376-2399（最后 24 小时）；
  - 候选模型：季节性朴素 s=24、季节性朴素 s=168、Holt-Winters(s=24)、滞后特征随机森林；
  - 选择规则：验证集上按指标排序（RMSE 主排序，MAE/sMAPE/峰值误差/峰时识别为辅），
    每类指标选一个主模型，再在测试集上报告全部指标；
  - 预测仅用于评价；最后 24 小时调度使用实际到达任务（不在本模块调度）。

输出：output/q1/ 下 series.csv、predictions_test.csv、model_selection.md、scores.csv。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_loader import Problem

TRAIN_END = 2352      # 训练 0..2351
VAL_END = 2376        # 验证 2352..2375
TEST_END = 2400       # 测试 2376..2399
HOURS = 2400          # 0..2399 到达时域

METRICS = ["TaskCount", "GPU_Demand", "GPU_Hour", "AvgDuration"]
TYPES = ["RealTimeInference", "BatchInference", "AITraining"]


def build_series(problem: Problem) -> pd.DataFrame:
    """构建逐小时序列（长表，每行一个 (Region, TaskType, Hour)）。"""
    t = problem.tasks
    t = t.copy()
    t["duration_h"] = t["EstimatedDuration_min"] / 60.0
    t["gpu_hour"] = t["GPU_Demand"] * t["duration_h"]
    t["gpu_demand"] = t["GPU_Demand"].astype(float)

    records = []

    def emit(region, task_type, arr):
        counts = np.bincount(arr["ArrivalHour"].to_numpy(), minlength=HOURS).astype(float)
        gpu = np.zeros(HOURS)
        gpu_h = np.zeros(HOURS)
        dur = np.zeros(HOURS)
        for _, row in arr.iterrows():
            h = int(row["ArrivalHour"])
            gpu[h] += row["gpu_demand"]
            gpu_h[h] += row["gpu_hour"]
            dur[h] += row["duration_h"]
        dur = np.divide(dur, counts, out=np.zeros_like(dur), where=counts > 0)
        for h in range(HOURS):
            records.append({"Region": region, "TaskType": task_type, "Hour": h,
                            "TaskCount": counts[h], "GPU_Demand": gpu[h],
                            "GPU_Hour": gpu_h[h], "AvgDuration": dur[h]})

    # (region, type)
    for reg in problem.REGIONS:
        for ty in TYPES:
            sub = t[(t["SourceRegion"] == reg) & (t["TaskType"] == ty)]
            emit(reg, ty, sub)
    # (region, all)
    for reg in problem.REGIONS:
        emit(reg, "All", t[t["SourceRegion"] == reg])
    # (all, type)
    for ty in TYPES:
        emit("All", ty, t[t["TaskType"] == ty])
    # (all, all)
    emit("All", "All", t)

    return pd.DataFrame(records)


def _smape(actual: np.ndarray, pred: np.ndarray) -> float:
    denom = np.abs(actual) + np.abs(pred)
    return float(100.0 * np.mean(2 * np.abs(actual - pred) / np.where(denom == 0, 1e-12, denom)))


def evaluate(actual: np.ndarray, pred: np.ndarray) -> dict:
    err = actual - pred
    return {
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err ** 2))),
        "sMAPE": _smape(actual, pred),
        "PeakError": float(np.max(np.abs(err))),
        "PeakHourHit": peak_hour_accuracy(actual, pred),
    }


def peak_hour_accuracy(actual: np.ndarray, pred: np.ndarray, tol: int = 1) -> float:
    """逐日峰时识别准确率：预测日最大值的时刻与实际的时刻偏差 <= tol 小时。"""
    if len(actual) < 24:
        return float("nan")
    n_days = len(actual) // 24
    hits = 0
    for d in range(n_days):
        a = actual[d * 24:(d + 1) * 24]
        p = pred[d * 24:(d + 1) * 24]
        if np.max(a) <= 0:
            continue
        ha = int(np.argmax(a))
        hp = int(np.argmax(p))
        hits += int(abs(ha - hp) <= tol)
    return hits / max(n_days, 1)


def seasonal_naive(series: np.ndarray, period: int) -> np.ndarray:
    """用周期 period 的滞后值外推最后 24 小时：forecast[i] = series[len-p+i]。"""
    out = np.full(24, np.nan)
    if len(series) >= period:
        start = len(series) - period
        out = series[start:start + 24].copy()
    # 末尾不足时回退最近值
    for i, v in enumerate(out):
        if np.isnan(v):
            out[i] = series[-1] if len(series) else 0.0
    return out


def holt_winters_forecast(series: np.ndarray, period: int = 24) -> np.ndarray:
    """Holt-Winters（加法趋势+加法季节，s=24）。失败时回退季节性朴素。"""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    try:
        model = ExponentialSmoothing(
            series, trend="add", seasonal="add",
            seasonal_periods=period, initialization_method="estimated",
        ).fit(optimized=True, remove_bias=True)
        fc = model.forecast(24)
        return np.asarray(fc, dtype=float)
    except Exception:
        return seasonal_naive(series, period)


def rf_predict(series_df: pd.DataFrame, train_end_hour: int,
               target_df: pd.DataFrame, metric: str,
               series_cols=("Region", "TaskType")) -> dict:
    """滞后特征随机森林（每指标一个模型，跨系列共享）。

    特征：lag24/48/168、小时、星期、区域索引、类型索引。
    训练：series_df 中 Hour < train_end_hour 的行；预测：target_df 各系列在目标小时的值。
    返回 {(Region, TaskType): np.ndarray}。
    """
    from sklearn.ensemble import RandomForestRegressor

    def features(s: np.ndarray, hours: np.ndarray, reg_idx: int, ty_idx: int) -> np.ndarray:
        X = []
        for h in hours:
            X.append([s[h - 24], s[h - 48], s[h - 168], h % 24, (h // 24) % 7,
                      reg_idx, ty_idx])
        return np.asarray(X)

    Xtr, ytr = [], []
    for (reg, ty), grp in series_df.groupby(list(series_cols)):
        s = series_df[(series_df["Region"] == reg) & (series_df["TaskType"] == ty)
                      & (series_df["Hour"] < train_end_hour)].sort_values("Hour")[metric].to_numpy()
        if len(s) < 200:
            continue
        hours = np.arange(200, len(s))
        Xtr.append(features(s, hours, ord(reg[-1]) - 65,
                            TYPES.index(ty) if ty in TYPES else 3))
        ytr.append(s[hours])
    Xtr = np.vstack(Xtr)
    ytr = np.concatenate(ytr)
    model = RandomForestRegressor(n_estimators=200, random_state=0, n_jobs=-1)
    model.fit(Xtr, ytr)

    preds = {}
    for (reg, ty), grp in target_df.groupby(list(series_cols)):
        s = series_df[(series_df["Region"] == reg) & (series_df["TaskType"] == ty)
                      & (series_df["Hour"] < 2400)].sort_values("Hour")[metric].to_numpy()
        hours = grp.sort_values("Hour")["Hour"].to_numpy()
        X = features(s, hours, ord(reg[-1]) - 65, TYPES.index(ty) if ty in TYPES else 3)
        preds[(reg, ty)] = model.predict(X)
    return preds


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args()

    problem = Problem(args.data_dir)
    series = build_series(problem)

    out_dir = Path(__file__).resolve().parent / "output" / "q1"
    out_dir.mkdir(parents=True, exist_ok=True)
    series.to_csv(out_dir / "series.csv", index=False, encoding="utf-8-sig")

    train = series[series["Hour"] < TRAIN_END]
    val = series[(series["Hour"] >= TRAIN_END) & (series["Hour"] < VAL_END)]
    test = series[series["Hour"] >= VAL_END]

    scores_rows = []
    pred_rows = []
    selection = []

    for metric in METRICS:
        # 候选模型在验证集上的表现（序列只用到训练期，避免泄漏）
        model_scores = {}
        for key, fn in [
            ("SNaive24", lambda s: seasonal_naive(s, 24)),
            ("SNaive168", lambda s: seasonal_naive(s, 168)),
        ]:
            errs = []
            for (reg, ty), grp in val.groupby(["Region", "TaskType"]):
                s_full = series[(series["Region"] == reg) & (series["TaskType"] == ty)
                                & (series["Hour"] < TRAIN_END)].sort_values("Hour")[metric].to_numpy()
                pred = fn(s_full)
                act = grp.sort_values("Hour")[metric].to_numpy()
                if len(pred) == len(act):
                    errs.append(evaluate(act, pred))
            model_scores[key] = {k: float(np.nanmean([e[k] for e in errs])) for k in errs[0]}

        # Holt-Winters：在聚合层级（Region=All 或 TaskType=All）上评估以控制运行时间
        hw_errs = []
        for (reg, ty), grp in val.groupby(["Region", "TaskType"]):
            if reg != "All" and ty != "All":
                continue
            s_full = series[(series["Region"] == reg) & (series["TaskType"] == ty)
                            & (series["Hour"] < TRAIN_END)].sort_values("Hour")[metric].to_numpy()
            pred = holt_winters_forecast(s_full)
            act = grp.sort_values("Hour")[metric].to_numpy()
            if len(pred) == len(act):
                hw_errs.append(evaluate(act, pred))
        if hw_errs:
            model_scores["HW24"] = {k: float(np.nanmean([e[k] for e in hw_errs])) for k in hw_errs[0]}

        # 滞后特征 RF：验证集与测试集（逐系列对齐）
        rf_val = rf_predict(series, TRAIN_END, val, metric)
        rf_test = rf_predict(series, VAL_END, test, metric)
        rf_val_agg = [evaluate(grp.sort_values("Hour")[metric].to_numpy(), rf_val[(reg, ty)])
                      for (reg, ty), grp in val.groupby(["Region", "TaskType"])
                      if (reg, ty) in rf_val]
        rf_test_agg = [evaluate(grp.sort_values("Hour")[metric].to_numpy(), rf_test[(reg, ty)])
                       for (reg, ty), grp in test.groupby(["Region", "TaskType"])
                       if (reg, ty) in rf_test]
        if rf_val_agg:
            model_scores["LagRF"] = {k: float(np.nanmean([e[k] for e in rf_val_agg]))
                                     for k in rf_val_agg[0]}
        rf_test_scores = ({k: float(np.nanmean([e[k] for e in rf_test_agg]))
                           for k in rf_test_agg[0]} if rf_test_agg else None)

        # 选择：验证集 RMSE 主排序（sMAPE/MAE 平局参考）
        best_model = min(model_scores, key=lambda m: (model_scores[m]["RMSE"], model_scores[m]["MAE"]))
        selection.append({"Metric": metric, "BestModel": best_model,
                          "Val_RMSE": model_scores[best_model]["RMSE"]})
        for m, sc in model_scores.items():
            scores_rows.append({"Metric": metric, "Model": m,
                                "Val_MAE": sc["MAE"], "Val_RMSE": sc["RMSE"],
                                "Val_sMAPE": sc["sMAPE"], "Val_PeakErr": sc["PeakError"],
                                "Val_PeakHourHit": sc.get("PeakHourHit", np.nan)})

        # 用选定模型生成测试集预测（逐 (Region, TaskType) 系列；序列只用到验证期止，避免泄漏）
        for (reg, ty), grp in test.groupby(["Region", "TaskType"]):
            s_full = series[(series["Region"] == reg) & (series["TaskType"] == ty)
                            & (series["Hour"] < VAL_END)].sort_values("Hour")[metric].to_numpy()
            if best_model == "SNaive24":
                pred = seasonal_naive(s_full, 24)
            elif best_model == "SNaive168":
                pred = seasonal_naive(s_full, 168)
            elif best_model == "HW24":
                pred = holt_winters_forecast(s_full)
            else:
                # LagRF 按系列取预测
                pred = rf_test[(reg, ty)]
            act = grp.sort_values("Hour")[metric].to_numpy()
            sc = evaluate(act, pred)
            for i, h in enumerate(grp.sort_values("Hour")["Hour"].to_numpy()):
                pred_rows.append({"Region": reg, "TaskType": ty, "Metric": metric,
                                  "Hour": int(h), "Actual": act[i], "Predicted": pred[i]})
            scores_rows.append({"Metric": metric, "Model": best_model + "(test)",
                                "Test_MAE": sc["MAE"], "Test_RMSE": sc["RMSE"],
                                "Test_sMAPE": sc["sMAPE"], "Test_PeakErr": sc["PeakError"],
                                "Test_PeakHourHit": sc.get("PeakHourHit", np.nan)})

    pd.DataFrame(scores_rows).to_csv(out_dir / "scores.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(pred_rows).to_csv(out_dir / "predictions_test.csv", index=False, encoding="utf-8-sig")

    lines = ["# Q1 预测模型选择报告", "",
             "时间切分：训练 0-2351，验证 2352-2375，测试 2376-2399（最后 24 小时实际任务）。", "",
             "| 指标 | 主模型 | 验证 RMSE |",
             "|---|---|---:|"]
    for s in selection:
        lines.append(f"| {s['Metric']} | {s['BestModel']} | {s['Val_RMSE']:.3f} |")
    lines.append("")
    lines.append("详细分数见 scores.csv；测试期预测见 predictions_test.csv。")
    lines.append("")
    lines.append("> 注意：预测仅用于评价；最后 24 小时调度使用实际到达任务。")
    (out_dir / "model_selection.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
