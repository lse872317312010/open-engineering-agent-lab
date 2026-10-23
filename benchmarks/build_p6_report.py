"""Generate an offline interactive report, standard figures, PDF and traceable data."""

import json
import os
import platform
import resource
import re
import textwrap
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from matplotlib.path import Path as PlotPath
from matplotlib.font_manager import FontProperties, fontManager

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "outputs/p6"
OUT = ROOT / "outputs/report"


def read(name):
    return json.loads((INPUT / name).read_text())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    font = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if font.exists():
        fontManager.addfont(str(font))
        plt.rcParams["font.family"] = FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.unicode_minus": False, "axes.labelcolor": "#33445e",
        "text.color": "#18273e", "axes.titleweight": "bold",
        "font.size": 10, "savefig.facecolor": "white",
    })
    run, refs, fit, scenarios, fmi = map(
        read, ("run.json", "references.json", "calibration.json", "scenarios.json", "fmi.json")
    )
    gate = {"passed": all(d["passed"] for d in (run, refs, fit, scenarios, fmi)),
            "scope": "P6 synthetic multi-physics simulation, RC FMI, report delivery"}
    if not gate["passed"]:
        raise AssertionError("cannot publish a passing report for failed P6 evidence")
    generated = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M %Z")
    data = {
        "generated_date": generated, "run": run, "references": refs, "calibration": fit,
        "scenarios": scenarios, "fmi": fmi, "gate": gate,
        "system_model": json.loads((ROOT / "reports/system-model.json").read_text()),
        "scope": {
            "parameters": "synthetic_research", "hardware": "user-owned, not required",
            "short_simulation": "9-state full coupling, 20 kHz control, 0.08 s",
            "long_thermal": "prescribed current envelope, 120 s; not full FOC",
            "FMI": "single-node thermal RC, not full joint FMU/OpenModelica",
            "report_sampling": "every 4 control samples; complete CSV in evidence",
        },
        "commands": [
            "pip install -r benchmarks/p6-requirements.txt", 'pip install -e ".[dev]"',
            "ruff check .", "python -m pytest", "python benchmarks/validate_p6.py",
            "python benchmarks/validate_fmi_thermal.py", "python benchmarks/build_p6_report.py",
            "python benchmarks/validate_report_ui.py",
        ],
    }
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    template = (ROOT / "reports/p6-dashboard.html").read_text()
    (OUT / "index.html").write_text(template.replace("__REPORT_DATA__", payload), encoding="utf-8")
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    raw = OUT / "data"
    raw.mkdir(exist_ok=True)
    for path in INPUT.glob("*.csv"):
        shutil.copyfile(path, raw / path.name)

    palette = ["#087d79", "#3b62c9", "#7b51b6", "#b46c25", "#cf5963", "#687c91"]
    figures = []
    fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27), layout="constrained")
    fig.suptitle("P6 · 多物理研究概览", fontsize=19)
    for case, color in zip(scenarios["cases"], palette, strict=True):
        values = np.array(case["samples"])
        axes[0, 0].plot(values[:, 0] * 1000, values[:, 2], color=color, label=case["title"])
        axes[0, 1].plot(values[:, 0] * 1000, values[:, 10], color=color, label=case["title"])
    axes[0, 0].set(xlabel="时间 (ms)", ylabel="q 轴电流 (A)", title="全耦合电流响应")
    axes[0, 1].set(xlabel="时间 (ms)", ylabel="输出转矩 (N·m)", title="柔性关节转矩")
    thermal = np.array(scenarios["thermal_cases"][1]["samples"])
    for index, label, color in zip((1, 2, 3), ("绕组", "壳体", "功率板"), palette, strict=False):
        axes[1, 0].plot(thermal[:, 0], thermal[:, index], label=label, color=color)
    axes[1, 0].set(xlabel="时间 (s)", ylabel="温度 (°C)", title="长时热包络 · 5 A")
    validation = np.array(fit["holdout"])
    axes[1, 1].plot(validation[:, 0], validation[:, 1], color=palette[0], label="解析参考")
    axes[1, 1].plot(validation[:, 0], validation[:, 2], "--", color=palette[2], label="辨识预测")
    axes[1, 1].set(xlabel="时间 (s)", ylabel="温度 (°C)", title="独立验证数据集")
    for ax in axes.flat:
        ax.grid(alpha=0.15)
        ax.legend(fontsize=7)
    figures.append(("overview", fig))

    fig, axes = plt.subplots(1, 2, figsize=(11.69, 6.5), layout="constrained")
    names = [c["title"] for c in scenarios["cases"]]
    errors = [c["metrics"]["q_tail_error_a"] for c in scenarios["cases"]]
    axes[0].barh(names, errors, color=palette)
    axes[0].axvline(0.1, color="#b46c25", linestyle="--", label="研究目标 0.1 A")
    axes[0].set(xlabel="尾段 q 轴误差 (A)", title="目标达成与未达边界")
    axes[0].legend(fontsize=8)
    stress = np.array(scenarios["thermal_stress"]["samples"])
    for index, label, color in zip((1, 2, 3), ("绕组", "壳体", "功率板"), palette, strict=False):
        axes[1].plot(stress[:, 0], stress[:, index], label=label, color=color)
    axes[1].axhline(100, color="#b46c25", linestyle="--", label="示例板温范围 100°C")
    axes[1].set(xlabel="时间 (s)", ylabel="温度 (°C)", title="高负荷热包络 · 12 A / 40°C")
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=0.15)
    figures.append(("scenario-comparison", fig))

    fig, axes = plt.subplots(1, 2, figsize=(11.69, 6.5), layout="constrained")
    for case, color in zip(scenarios["thermal_cases"], palette, strict=False):
        values = np.array(case["samples"])
        axes[0].plot(values[:, 0], values[:, 1], color=color,
                     label=f"热阻 × {case['resistance_factor']:.1f}")
    axes[0].set(xlabel="时间 (s)", ylabel="绕组温度 (°C)", title="±20% 热阻情景 · 非置信区间")
    axes[0].legend()
    noise_r = [item["resistance_k_per_w"] for item in fit["noise_repetitions"]]
    noise_c = [item["capacity_j_per_k"] for item in fit["noise_repetitions"]]
    axes[1].scatter(noise_r, noise_c, c=palette[2], s=25, alpha=0.7, label="合成噪声重复实验")
    axes[1].scatter([1.5], [80], marker="*", s=130, c=palette[0], label="合成真值")
    axes[1].set(xlabel="热阻 R (K/W)", ylabel="热容 C (J/K)", title="标定对合成噪声的敏感度")
    axes[1].legend()
    for ax in axes:
        ax.grid(alpha=0.15)
    figures.append(("uncertainty-calibration", fig))

    checks = [
        ("机械能误差", refs["mechanical_energy_error_j"], 1e-6),
        ("热网络矩阵参考", refs["thermal_expm_error_k"], 1e-6),
        ("全耦合 DOP853", refs["coupled_dop853_error"], 2e-5),
        ("步长减半", scenarios["step_halving_max_state_difference"], 2e-4),
        ("独立标定验证", fit["holdout_rmse_k"], 0.15),
        ("FMI 热模型", fmi["max_error_k"], 1e-6),
    ]
    fig, ax = plt.subplots(figsize=(11.69, 6.5), layout="constrained")
    ratios = [max(value / tolerance, 1e-15) for _, value, tolerance in checks]
    ax.barh([name for name, _, _ in checks], ratios, color=palette[0])
    ax.set_xscale("log")
    ax.axvline(1, color="#b46c25", linestyle="--")
    ax.set(title="预声明验收 · 误差与容差之比（小于 1 为通过）", xlabel="无量纲误差 / 容差")
    ax.grid(alpha=0.15, axis="x")
    for index, ratio in enumerate(ratios):
        ax.text(ratio * 1.2, index, f"{ratio:.2e}", va="center", fontsize=9)
    figures.append(("validation", fig))


    # The same module/connection specification drives HTML, PDF and source data.
    spec = data["system_model"]
    fig, ax = plt.subplots(figsize=(11.69, 8.27), layout="constrained")
    ax.set(xlim=(-10, 1140), ylim=(660, -10))
    ax.axis("off")
    ax.set_title("系统模型 · 控制、电气、机械与热反馈", fontsize=18, pad=16)
    edge_colors = {"signal": palette[1], "energy": palette[0], "feedback": palette[2]}
    for edge in spec["edges"]:
        tokens = re.findall(r"[MLHV]|-?\d+(?:\.\d+)?", edge["path"])
        vertices, codes, pos = [], [], [0.0, 0.0]
        i = 0
        while i < len(tokens):
            command = tokens[i]
            i += 1
            if command in ("M", "L"):
                pos = [float(tokens[i]), float(tokens[i + 1])]
                i += 2
            elif command == "H":
                pos = [float(tokens[i]), pos[1]]
                i += 1
            elif command == "V":
                pos = [pos[0], float(tokens[i])]
                i += 1
            vertices.append(tuple(pos))
            codes.append(PlotPath.MOVETO if command == "M" else PlotPath.LINETO)
        ax.add_patch(FancyArrowPatch(
            path=PlotPath(vertices, codes), arrowstyle="-|>", mutation_scale=11,
            color=edge_colors[edge["kind"]], linewidth=1.3,
            linestyle="--" if edge["kind"] == "feedback" else "-",
        ))
    for node in spec["nodes"]:
        x, y = node["x"], node["y"]
        ax.add_patch(FancyBboxPatch(
            (x, y), 220, 115, boxstyle="round,pad=0,rounding_size=12",
            facecolor="#f3f6fb", edgecolor="#c5d3e4",
        ))
        ax.text(x + 12, y + 32, node["title"], fontsize=11, weight="bold")
        ax.text(x + 12, y + 62, node["subtitle"], fontsize=8)
    ax.text(285, 22, "电流 / 角度 / 转速反馈", color=palette[2], fontsize=9)
    ax.text(550, 546, "绕组温度 → 实际铜阻", color=palette[2], fontsize=9)
    ax.text(5, 582, "蓝色实线：控制信号    青色实线：能量耦合    紫色虚线：反馈 / 停机", fontsize=10)
    ax.text(5, 616, "20 kHz：阈值锁存 → PI / 解耦 → 延迟选择 → 电压保持 → RK4 子步 → 下一 tick", fontsize=9)
    ax.text(5, 644, "状态回放与详细连接见 index.html；参数和连接定义同时保留于 data.json。", fontsize=9)
    figures.append(("system-model", fig))

    mechanism_fig = plt.figure(figsize=(11.69, 8.27))
    mechanism_fig.text(0.06, 0.94, "各模块的必要运行机制", fontsize=19, weight="bold")
    y = 0.88
    for node in spec["nodes"]:
        mechanism_fig.text(0.06, y, node["title"], fontsize=11, weight="bold")
        lines = textwrap.wrap(node["mechanism"], width=70)
        mechanism_fig.text(0.06, y - 0.024, "\n".join(lines), fontsize=9,
                           va="top", linespacing=1.5)
        y -= 0.032 + len(lines) * 0.022
    mechanism_fig.text(0.06, 0.04, "仿真状态回放；无速度/位置外环。零电压停机仍保留电磁、机械与热动态。", fontsize=9)

    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.savefig(plots / (name + ".png"), dpi=180)
            fig.savefig(plots / (name + ".svg"))
            pdf.savefig(fig)
        pdf.savefig(mechanism_fig)
        plt.close(mechanism_fig)
        fig = plt.figure(figsize=(11.69, 8.27))
        fig.text(0.08, 0.91, "P6 · 结论、方法与适用边界", fontsize=22, weight="bold")
        lines = [
            "结论：本报告声明的仿真范围通过固定验收指标。",
            f"全耦合独立参考误差：{refs['coupled_dop853_error']:.4e}",
            f"独立验证温度 RMSE：{fit['holdout_rmse_k']:.5f} K",
            f"FMI 热模型误差：{fmi['max_error_k']:.4e} K",
            "", "方法与数据：",
            "20 kHz 电流环；9 状态短时全耦合；独立矩阵指数与 DOP853 数学参考。",
            "120 秒热研究采用指定理想电流包络，未运行完整 20 kHz FOC。",
            "标定与独立验证功率工况分开；所有温度数据均为合成解析数据。",
            "±20% 热阻扫描是限定情景，不是实测不确定度或统计置信区间。",
            "", "未覆盖：完整关节 FMU/OpenModelica、开关级逆变器、齿隙接触、真机实测。",
            "真实设备/HAL/硬件测试由用户负责；未通过的物理目标保留失败状态。",
            "", "运行来源：", str(run["source_commit"]), generated,
            "完整参数、逐工况数据、方法约定和可复现命令见同目录 index.html / data.json。",
        ]
        fig.text(0.08, 0.84, "\n".join(lines), fontsize=11, va="top", linespacing=1.8)
        pdf.savefig(fig)
        plt.close(fig)
    for _, fig in figures:
        plt.close(fig)

    report_lines = [
        "# P6 多物理仿真研究报告", "", f"生成：{generated}",
        f"提交：{run['source_commit']}", "", "## 本轮结论",
        "声明范围的模型、独立数值参考、合成独立验证和 FMI RC 互操作均通过。",
        "交互报告：index.html；PDF：report.pdf；图表：plots/；完整 CSV：data/。",
        "", "## 核心指标", "",
        "| 指标 | 实际值 | 预声明容差 |", "|---|---:|---:|",
    ]
    for name, value, tolerance in checks:
        report_lines.append(f"| {name} | {value:.6g} | {tolerance:.6g} |")
    report_lines += ["", "## 研究工况", "",
                     "| 工况 | 尾段 q 误差 A | 电流目标 | 数值检查 |",
                     "|---|---:|---|---|"]
    for case in scenarios["cases"]:
        report_lines.append(
            f"| {case['title']} | {case['metrics']['q_tail_error_a']:.5f} | "
            f"{'达成' if case['tracking_goal_passed'] else '未达/停机'} | "
            f"{'通过' if case['numeric_passed'] else '失败'} |"
        )
    report_lines += ["", "## 系统运行机制", spec["timing"], spec["scope"]]
    for node in spec["nodes"]:
        report_lines += ["", "### " + node["title"], node["mechanism"],
                         node["equation"], node["limits"]]
    report_lines += ["", "## 模块连接"]
    for edge in spec["edges"]:
        report_lines.append(f"- {edge['from']} → {edge['to']}：{edge['label']}。{edge['mechanism']}")
    report_lines += ["", "## 范围和复现", json.dumps(data["scope"], ensure_ascii=False, indent=2),
                     "", "所有参数与标定数据为合成研究值；不代表真机测量或硬件保护认证。",
                     "尚未实现完整关节 FMU/OpenModelica、开关级与齿隙接触。",
                     "", "复现命令：", "~~~bash", *data["commands"], "~~~"]
    (OUT / "report.md").write_text("\n".join(report_lines), encoding="utf-8")
    (OUT / "START-HERE.txt").write_text(
        "打开 index.html 浏览中文交互报告；无需服务器或联网。\n"
        "PDF: report.pdf；图表: plots/；完整原始数据: data/；完整结构: data.json。\n",
        encoding="utf-8",
    )
    environment = {
        "python": sys.version, "platform": platform.platform(),
        "matplotlib": matplotlib.__version__,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "commit": os.environ.get("GITHUB_SHA"), "font": str(font) if font.exists() else "fallback",
        "packages": subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True),
    }
    (INPUT / "report-environment.json").write_text(json.dumps(environment, indent=2))
    print("report.json: " + json.dumps({
        "passed": gate["passed"], "entry": str(OUT / "index.html"),
        "pdf": str(OUT / "report.pdf"), "chart_count": len(figures),
    }))


if __name__ == "__main__":
    main()
