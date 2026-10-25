"""Build a standalone, offline joint campaign report, including thermal evidence."""

import json
import shutil
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/joint-report"


def column(stream, name):
    return np.asarray(stream["samples"])[:, stream["columns"].index(name)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads((ROOT / "outputs/joint-robustness/report-data.json").read_text())
    thermal_root = ROOT / "outputs/thermal-endurance"
    thermal_report = json.loads((thermal_root / "report.json").read_text())
    thermal = np.loadtxt(thermal_root / "ambient-25-step-0.5.csv", delimiter=",", skiprows=1)
    data["thermal"] = dict(report=thermal_report, samples=thermal[::12].tolist())
    data["passed"] = data["passed"] and thermal_report["passed"]
    text = json.dumps(data, ensure_ascii=False, allow_nan=False)
    (OUT / "report-data.json").write_text(text)
    template = (ROOT / "reports/joint-robustness.html").read_text()
    html = template.replace("__CAMPAIGN_DATA__", text.replace("<", "\\u003c"))
    (OUT / "index.html").write_text(html)
    csv_dir = OUT / "csv"
    csv_dir.mkdir(exist_ok=True)
    for case in data["cases"]:
        source = ROOT / "outputs/joint-robustness" / case["id"] / "raw/joint.csv"
        shutil.copyfile(source, csv_dir / (case["id"] + "-joint.csv"))
    shutil.copytree(thermal_root, OUT / "thermal-endurance", dirs_exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": [
        "Noto Sans CJK JP", "DejaVu Sans"], "axes.unicode_minus": False,
        "figure.facecolor": "#f4f7fb", "axes.grid": True, "grid.alpha": .2})
    count = 0
    with PdfPages(OUT / "report.pdf") as pdf:
        def save(fig, name):
            nonlocal count
            fig.tight_layout()
            fig.savefig(plots / (name + ".png"), dpi=160)
            fig.savefig(plots / (name + ".svg"))
            pdf.savefig(fig)
            plt.close(fig)
            count += 1

        fig, ax = plt.subplots(figsize=(11, 5))
        ids = [c["id"] for c in data["cases"]]
        ax.bar(ids, [c["metrics"]["hold_max_error_rad"] for c in data["cases"]])
        ax.axhline(.03, color="red", linestyle="--", label="fixed 0.03 rad limit")
        ax.set(ylabel="Last 0.5 s max absolute error / rad",
               title="Frozen position PD: seven cases")
        ax.tick_params(axis="x", rotation=25)
        ax.legend()
        save(fig, "tracking-gates")
        fig, axes = plt.subplots(2, 1, figsize=(11, 8))
        for case in data["cases"]:
            stream = data["series"][case["id"]]["joint"]
            t = column(stream, "time_s")
            axes[0].plot(t, column(stream, "joint_angle_rad")
                         - column(stream, "reference_rad"), label=case["id"])
            axes[1].plot(t, column(stream, "shaft_torque_nm"), label=case["id"])
        axes[0].set(ylabel="Position error / rad",
                    title="Actual one-second electromechanical trajectories")
        axes[1].set(xlabel="Time / s", ylabel="Shaft torque / N m")
        axes[0].legend(ncol=2)
        save(fig, "joint-trajectories")
        fig, axes = plt.subplots(2, 1, figsize=(11, 8))
        for case in data["cases"]:
            stream = data["series"][case["id"]]["co_sim_energy"]
            for ax, name in zip(axes, ("interface_residual_j", "extended_residual_j"), strict=True):
                ax.plot(column(stream, "time_s"), column(stream, name), label=case["id"])
                ax.set(ylabel=name + " / J")
        axes[0].set_title("Independent port ledgers; residuals are not heat")
        axes[0].legend(ncol=2)
        axes[1].set_xlabel("Time / s")
        save(fig, "energy-ledgers")
        fig, axes = plt.subplots(2, 1, figsize=(11, 8))
        for name in ("combined-holdout", "combined-fine"):
            stream = data["series"][name]["control"]
            t = column(stream, "time_s")
            axes[0].plot(t, np.hypot(column(stream, "id_a"), column(stream, "iq_a")), label=name)
            axes[1].plot(t, column(stream, "winding_c"), label=name + " winding")
            axes[1].plot(t, column(stream, "junction_c"), label=name + " junction")
        axes[0].set(ylabel="Actual dq current / A", title="PWM + sensors holdout; display samples")
        axes[0].legend()
        axes[1].set(xlabel="Time / s", ylabel="Temperature / C")
        axes[1].legend()
        save(fig, "pwm-sensor-holdout")
        fig, ax = plt.subplots(figsize=(11, 5))
        for i, name in enumerate(("winding", "core", "case", "junction", "board", "sink")):
            ax.plot(thermal[:, 0], thermal[:, i + 1], label=name)
        ax.set(xlabel="Time / s", ylabel="Temperature / C",
               title="3600 s prescribed-loss replay, NOT a coupled motor/robot run")
        ax.legend(ncol=3)
        save(fig, "thermal-replay")
    notes = (
        "# 关节多工况验证报告\n\n"
        + ("固定联合验收通过。" if data["passed"] else "存在未通过工况。")
        + "\n\n七组 1 s 联合实验，位置 PD 冻结。原始全量证据见对应七个 case artifact；"
        "本包含完整关节 CSV、显示抽样数据、五组 PNG/SVG、PDF 与离线 HTML。\n\n"
        "电机参数为控制器已知配置，不是未知参数失配鲁棒性证明。"
        "一小时热网络为预设损耗回放，不代表一小时电机/机器人联合运行。"
        "真机由用户负责。\n"
    )
    (OUT / "README.md").write_text(notes)
    (OUT / "report.json").write_text(json.dumps(dict(
        passed=data["passed"], chart_count=count, source_commit=data["source_commit"]
    ), indent=2))
    print("joint-report.json: " + json.dumps(dict(passed=data["passed"], charts=count)))


if __name__ == "__main__":
    main()
