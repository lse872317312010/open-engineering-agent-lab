"""Render independently audited case artifacts; no new physical simulation."""

import json
import shutil
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/cyclic-report"


def values(stream, name):
    return np.asarray(stream["samples"])[:, stream["columns"].index(name)]


def main():
    data = json.loads((ROOT / "outputs/cyclic/report-data.json").read_text())
    data["series"] = {c["id"]: c["streams"] for c in data["cases"]}
    OUT.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
    (OUT / "report-data.json").write_text(encoded)
    template = (ROOT / "reports/cyclic-mismatch.html").read_text()
    (OUT / "index.html").write_text(template.replace("__CYCLIC_DATA__",
                                                   encoded.replace("<", "\\u003c")))
    csv = OUT / "csv"
    csv.mkdir(exist_ok=True)
    for case in data["cases"]:
        path = ROOT / "outputs/cyclic" / case["id"] / "joint.csv"
        if path.exists():
            shutil.copyfile(path, csv / (case["id"] + "-joint.csv"))
    plt.rcParams.update({"font.sans-serif": ["Noto Sans CJK JP", "DejaVu Sans"],
                         "axes.unicode_minus": False, "axes.grid": True, "grid.alpha": .2})
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    available = [c for c in data["cases"] if c["streams"]]
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
        cyclic = [c for c in available if c["id"] != "legacy-step"]
        ax.bar([c["id"] for c in cyclic],
               [c["metrics"]["position_peak_error_rad"] for c in cyclic])
        ax.axhline(.03, color="red", linestyle="--", label="fixed peak error limit")
        ax.tick_params(axis="x", rotation=25)
        ax.set(ylabel="Whole-cycle peak position error / rad", title="Frozen nominal controller")
        ax.legend()
        save(fig, "whole-cycle-goals")
        fig, axes = plt.subplots(2, 1, figsize=(11, 8))
        for case in available:
            if case["id"] in {"nominal", "combined", "combined-fine"}:
                joint = case["streams"]["joint"]
                t = values(joint, "time_s")
                axes[0].plot(t, values(joint, "joint_angle_rad"), label=case["id"])
                axes[1].plot(t, values(joint, "joint_angle_rad")
                             - values(joint, "reference_rad"), label=case["id"])
        if cyclic:
            joint = cyclic[0]["streams"]["joint"]
            axes[0].plot(values(joint, "time_s"), values(joint, "reference_rad"),
                         "--", color="black", label="independent target")
        axes[0].set(ylabel="Joint angle / rad", title="Two cycles with actual motor mismatch")
        axes[1].set(xlabel="Time / s", ylabel="Position error / rad")
        for ax in axes:
            ax.legend()
        save(fig, "two-cycle-response")
        fig, ax = plt.subplots(figsize=(11, 5))
        keys = (("R_s", "stator_resistance_ohm"), ("L_q", "q_inductance_h"),
                ("psi_f", "flux_linkage_wb"))
        for i, (nominal, physical) in enumerate(keys):
            offsets = np.arange(len(available)) + (i - 1) * .25
            deviation = [(c["context"]["physical_machine"][physical]
                          / c["context"]["nominal_machine"][nominal] - 1) * 100
                         for c in available]
            ax.bar(offsets, deviation, width=.25, label=physical)
        ax.set_xticks(np.arange(len(available)), [c["id"] for c in available], rotation=25)
        ax.set(ylabel="Actual / frozen nominal deviation / %",
               title="Separate plant and controller")
        ax.legend()
        save(fig, "nominal-vs-actual")
        fig, axes = plt.subplots(2, 1, figsize=(11, 8))
        for case in available:
            if case["id"] in {"combined", "combined-fine"}:
                control, ledger = (case["streams"][k] for k in ("control", "co_sim_energy"))
                axes[0].plot(values(control, "time_s"),
                             np.hypot(values(control, "id_a"), values(control, "iq_a")),
                             label=case["id"])
                axes[1].plot(values(ledger, "time_s"), values(ledger, "extended_residual_j"),
                             label=case["id"])
        axes[0].set(ylabel="Actual dq current / A", title="PWM/sensor holdout; display samples")
        axes[1].set(xlabel="Time / s", ylabel="Extended energy residual / J")
        for ax in axes:
            ax.legend()
        save(fig, "holdout-current-and-energy")
    (OUT / "README.md").write_text(
        "# 循环轨迹与未知电气参数失配\n\n"
        "解压后打开 index.html。八组全量关节 CSV、四组 PNG/SVG、PDF 与报告 JSON 随包提供。\n"
        "门槛来自独立进程重读完整序列化结果；聚合阶段核对同一运行的文件散列。\n"
        "完整电磁轨迹保存在每组 cycle-case artifact 的 result.json.gz 中。\n"
        "这里只覆盖两个循环与指定电气参数偏差，耦合器仍使用实际物理参数。真机由用户负责。\n"
    )
    (OUT / "report.json").write_text(json.dumps(dict(passed=data["passed"], charts=count)))
    print("cycle-report.json: " + json.dumps(dict(passed=data["passed"], charts=count)))


if __name__ == "__main__":
    main()
