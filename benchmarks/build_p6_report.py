"""Generate an offline interactive report, standard figures, PDF and traceable data."""

import json
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from matplotlib.path import Path as PlotPath

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
    refined_path = ROOT / "outputs/refined/report-data.json"
    data["refined"] = (json.loads(refined_path.read_text()) if refined_path.exists()
                       else {"available": False})
    for key, relative in (
        ("unified", "outputs/unified/summary.json"),
        ("design", "outputs/design/report-data.json"),
        ("energy", "outputs/energy/report-data.json"),
        ("coupling", "outputs/coupling/report-data.json"),
    ):
        path = ROOT / relative
        data[key] = json.loads(path.read_text()) if path.exists() else {"available": False}
    if data["design"].get("validations"):
        data["scope"]["design"] = data["design"]["scope"]
        data["commands"] = [
            "pip install -r benchmarks/design-requirements.txt", 'pip install -e ".[dev]"',
            "python benchmarks/validate_open_models.py",
            "python benchmarks/validate_unified_studies.py",
            "python benchmarks/validate_design_iteration.py",
            *data["commands"][2:],
        ]
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    template = (ROOT / "reports/p6-dashboard.html").read_text()
    (OUT / "index.html").write_text(template.replace("__REPORT_DATA__", payload), encoding="utf-8")
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    raw = OUT / "data"
    raw.mkdir(exist_ok=True)
    for path in INPUT.glob("*.csv"):
        shutil.copyfile(path, raw / path.name)

    if refined_path.exists():
        shutil.copytree(ROOT / "outputs/refined", OUT / "refined", dirs_exist_ok=True)
        shutil.copytree(ROOT / "research/licenses", OUT / "licenses", dirs_exist_ok=True)

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
    ax.text(5, 582, "蓝色实线：控制信号    青色实线：能量耦合"
            "    紫色虚线：反馈 / 停机", fontsize=10)
    ax.text(5, 616, "20 kHz：阈值锁存 → PI / 解耦 → 延迟选择"
            " → 电压保持 → RK4 子步 → 下一 tick", fontsize=9)
    ax.text(5, 644, "状态回放与详细连接见 index.html；"
            "参数和连接定义同时保留于 data.json。", fontsize=9)
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
    mechanism_fig.text(0.06, 0.04, "仿真状态回放；无速度/位置外环。"
                       "零电压停机仍保留电磁、机械与热动态。", fontsize=9)


    refined = data["refined"]
    if refined.get("passed"):
        cases = refined["electrical"]
        fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27), layout="constrained")
        fig.suptitle("开源电气模型 · 真实开关、母线与反馈", fontsize=18)
        names = [c["title"] for c in cases]
        errors = [c["metrics"]["tail_q_error_a"] for c in cases]
        axes[0, 0].barh(names, errors, color=palette[0])
        axes[0, 0].axvline(0.1, color=palette[3], linestyle="--")
        axes[0, 0].set(xlabel="尾段平均 q 偏差 A", title="目标未达保留，不放宽 0.1 A")
        for ident, color in zip(("average", "switching", "deadtime"), palette, strict=False):
            case = next(c for c in cases if c["id"] == ident)
            values = np.asarray(case["control"])
            axes[0, 1].plot(values[:, 0] * 1000, values[:, 2],
                            color=color, label=case["title"])
        axes[0, 1].set(xlabel="时间 ms", ylabel="q 电流 A", title="同参数电机的模型差异")
        case = next(c for c in cases if c["id"] == "deadtime")
        waves = np.asarray(case["wave_window"])
        for j, name in enumerate(("a", "b", "c")):
            axes[1, 0].plot(waves[:, 0] * 1000, waves[:, j + 1], label=name)
        axes[1, 0].set(xlabel="时间 ms", ylabel="相电流 A", title="真实 PWM 纹波窗口")
        for ident, color in zip(("capacitor", "diode"), palette, strict=False):
            case = next(c for c in cases if c["id"] == ident)
            values = np.asarray(case["control"])
            axes[1, 1].plot(values[:, 0] * 1000, values[:, 9],
                            color=color, label=case["title"])
        axes[1, 1].set(xlabel="时间 ms", ylabel="母线 V", title="储能母线与整流供电")
        for ax in axes.flat:
            ax.grid(alpha=0.15)
        for ax in (axes[0, 1], axes[1, 0], axes[1, 1]):
            ax.legend(fontsize=8)
        figures.append(("open-electrical", fig))

        fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27), layout="constrained")
        fig.suptitle("开源机器人负载 · 电机、传动与 UR5e", fontsize=18)
        for case, color in zip(refined["robot"]["cases"][:3], palette, strict=False):
            values = np.asarray(case["samples"])
            axes[0, 0].plot(values[:, 0], values[:, 1], color=color, label=case["title"])
            axes[0, 1].plot(values[:, 0], values[:, 6], color=color, label=case["title"])
            axes[1, 0].plot(values[:, 0], values[:, 9], color=color, label=case["title"])
        axes[0, 0].set(xlabel="时间 s", ylabel="肩部角 rad", title="姿态相关负载")
        axes[0, 1].set(xlabel="时间 s", ylabel="传动转矩 N·m", title="弹性 / 齿隙传力")
        axes[1, 0].set(xlabel="时间 s", ylabel="夹具接触力 N", title="MuJoCo 实际接触事件")
        axes[1, 1].imshow(plt.imread(OUT / "refined/ur5e-model.png"))
        axes[1, 1].axis("off")
        axes[1, 1].set_title("固定 Menagerie 模型；研究电机不等于厂商驱动器")
        for ax in (axes[0, 0], axes[0, 1], axes[1, 0]):
            ax.grid(alpha=0.15)
            ax.legend(fontsize=7)
        figures.append(("open-robot", fig))

        fig, axes = plt.subplots(1, 2, figsize=(11.69, 6.5), layout="constrained")
        curve = np.asarray(refined["magnetic_map"]["curve"])
        axes[0].plot(curve[:, 0], curve[:, 1], label="上游非线性磁图")
        axes[0].plot(curve[:, 0], curve[:, 2], "--", label="零电流 q 切线")
        axes[0].plot(curve[:, 0], curve[:, 3], label="d 磁链：交叉耦合")
        axes[0].set(xlabel="q 电流 A", ylabel="磁链 Wb",
                    title="同一上游示例电机 · 不是用户电机标定")
        thermal = np.asarray(refined["thermal"]["samples"])
        for j, name in enumerate(("绕组", "铁心", "壳体", "等效结", "板", "散热器")):
            axes[1].plot(thermal[:, 0], thermal[:, j + 1], label=name)
        axes[1].set(xlabel="时间 s", ylabel="温度 °C",
                    title="六节点热损耗回放 · 非长时完整 FOC")
        for ax in axes:
            ax.grid(alpha=0.15)
            ax.legend(fontsize=8)
        figures.append(("open-thermal", fig))

    design = data["design"]
    if design.get("validations"):
        fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27), layout="constrained")
        fig.suptitle("固定目标下的控制设计 · 平均模型训练，开关模型验证", fontsize=17)
        valid = [t for t in design["trials"] if "metrics" in t["verification"]]
        axes[0, 0].plot(
            [t["trial"] for t in valid],
            [t["verification"]["metrics"]["position_tail_error_rad"] for t in valid],
            "o-", color=palette[0],
        )
        axes[0, 0].axhline(0.03, linestyle="--", color=palette[3])
        axes[0, 0].set(xlabel="Optuna 试验", ylabel="尾段位置偏差 rad",
                       title="只调整 Kp / Kd；失败试验保留于数据")
        for ax, pair in zip(axes.flat[1:], design["validations"], strict=True):
            for key, color in (("baseline", palette[1]), ("optimized", palette[0])):
                trace = pair[key]["trace"]
                values = np.asarray(trace["samples"])
                column = trace["columns"].index("joint_angle_rad")
                ax.plot(values[:, 0] * 1000, values[:, column], label=key, color=color)
            reference = trace["columns"].index("reference_rad")
            ax.plot(values[:, 0] * 1000, values[:, reference], "--",
                    color=palette[3], label="fixed reference")
            ax.set(xlabel="时间 ms", ylabel="关节角 rad", title=pair["id"])
            ax.legend(fontsize=7)
        for ax in axes.flat:
            ax.grid(alpha=0.15)
        figures.append(("design-comparison", fig))

        fig, axes = plt.subplots(1, 2, figsize=(11.69, 6.5), layout="constrained")
        for key, color in (("baseline", palette[1]), ("optimized", palette[0])):
            values = np.asarray(design["linear_analysis"][key]["frequency"])
            axes[0].semilogx(values[:, 0], values[:, 1], label=key, color=color)
        axes[0].set(xlabel="角频率 rad/s", ylabel="开环幅值 dB",
                    title="python-control · 平衡点附近降阶模型")
        axes[0].legend()
        si = design["sensitivity"]
        axes[1].barh(["传动刚度", "负载惯量", "电流环带宽"],
                      si["mu_star"], color=palette[:3])
        axes[1].set(xlabel="Morris 平均绝对基本效应 rad",
                    title="SALib · 降阶模型 ±20% 范围")
        for ax in axes:
            ax.grid(alpha=0.15)
        fig.text(0.1, 0.01, "线性筛选和敏感度不是非线性系统稳定性证明或实测置信区间。",
                 fontsize=9)
        figures.append(("design-analysis", fig))

    energy_report = data["energy"]
    if energy_report.get("passed"):
        energy_cases = energy_report["cases"]
        case = energy_cases[3]
        values = np.asarray(case["streams"]["energy"]["samples"])
        columns = case["streams"]["energy"]["columns"]

        def energy_column(name):
            return values[:, columns.index(name)]

        time = energy_column("time_s") * 1000
        stored = sum(energy_column(n) - energy_column(n)[0]
                     for n in ("magnetic_j", "kinetic_j", "bus_j", "thermal_j"))
        fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27), layout="constrained")
        fig.suptitle("能量端口 · 直流、电磁、转子与连续热网络", fontsize=17)
        axes[0, 0].plot(time, energy_column("source_j"), label="直流馈入")
        axes[0, 0].plot(time, stored + energy_column("load_work_j")
                        + energy_column("ambient_j"), "--", label="储能变化 + 对外能量")
        axes[0, 0].set(xlabel="时间 ms", ylabel="能量 J", title="电容母线边界")
        axes[0, 1].plot(time, energy_column("local_residual_j"), label="局部余额")
        limit = case["metrics"]["energy_balance_limit_j"]
        axes[0, 1].axhline(limit, color=palette[3], linestyle="--")
        axes[0, 1].axhline(-limit, color=palette[3], linestyle="--")
        axes[0, 1].set(xlabel="时间 ms", ylabel="未平衡能量 J", title="固定能量门槛")
        for name, label in (("winding_c", "绕组"), ("junction_c", "等效结"),
                            ("case_c", "机壳")):
            axes[1, 0].plot(time, energy_column(name), label=label)
        axes[1, 0].set(xlabel="时间 ms", ylabel="温度 °C", title="连续积分，热源有实际能量来源")
        fault = energy_report["fault_demo"]
        fault_values = np.asarray(fault["streams"]["energy"]["samples"])
        fault_columns = fault["streams"]["energy"]["columns"]
        axes[1, 1].plot(
            fault_values[:, 0] * 1000,
            fault_values[:, fault_columns.index("local_residual_j")],
            color=palette[4], label="漏记额外直流耗能",
        )
        axes[1, 1].set(xlabel="时间 ms", ylabel="未平衡能量 J",
                       title="账本故障注入 · 保留明确失败")
        for ax in axes.flat:
            ax.grid(alpha=0.15)
            ax.legend(fontsize=8)
        figures.append(("energy-balance", fig))

        fig, axes = plt.subplots(1, 2, figsize=(11.69, 6.5), layout="constrained")
        for item in energy_cases:
            if "co_sim_energy" not in item["streams"]:
                continue
            trace = item["streams"]["co_sim_energy"]
            rows = np.asarray(trace["samples"])
            col = trace["columns"]
            for ax, name in zip(
                axes, ("interface_residual_j", "robot_balance_residual_j"), strict=True
            ):
                ax.plot(rows[:, 0] * 1000, rows[:, col.index(name)], label=item["title"])
        axes[0].set(title="电机—弹性传动—机器人接口余额",
                    xlabel="时间 ms", ylabel="未平衡能量 J")
        axes[1].set(title="机器人机械积分 / 做功求积余额",
                    xlabel="时间 ms", ylabel="未平衡能量 J")
        for ax in axes:
            ax.grid(alpha=0.15)
            ax.legend(fontsize=8)
        fig.text(0.08, 0.01, "宏步 200 / 100 / 50 μs；诊断曲线不等于全系统能量闭合证明。",
                 fontsize=9)
        figures.append(("energy-interfaces", fig))

    coupling_report = data["coupling"]
    if coupling_report.get("passed"):
        items = {c["id"]: c for c in coupling_report["cases"]}
        fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27), layout="constrained")
        fig.suptitle("同积分器公平对照 · 中点转矩预测", fontsize=18)
        for method, label, color in (
            ("jacobi", "Jacobi / RK4", palette[1]),
            ("midpoint_predictor", "中点预测 / RK4", palette[0]),
        ):
            for ax, metric in zip(
                axes.flat[:2], ("interface_residual_j", "extended_residual_j"), strict=True
            ):
                axes_values = [items[method + "-" + str(h)]["metrics"][metric]
                               for h in (50, 100, 200)]
                ax.loglog([50, 100, 200], axes_values, "o-", label=label, color=color)
        axes[0, 0].set(xlabel="宏步 μs", ylabel="峰值 J", title="实际端口接口余额")
        axes[0, 1].set(xlabel="宏步 μs", ylabel="峰值 J", title="扩展能量余额")
        for key, color in (("long-jacobi", palette[1]), ("long-midpoint", palette[0])):
            trace = items[key]["streams"]["joint"]
            rows = np.asarray(trace["samples"])
            axes[1, 0].plot(rows[:, 0] * 1000,
                            rows[:, trace["columns"].index("joint_angle_rad")],
                            label=key, color=color)
        axes[1, 0].plot(rows[:, 0] * 1000,
                        rows[:, trace["columns"].index("reference_rad")], "--",
                        color=palette[3], label="固定参考")
        axes[1, 0].set(xlabel="时间 ms", ylabel="关节角 rad",
                       title="250 ms / +0.08 rad · 增益固定")
        comparisons = coupling_report["comparisons"]
        axes[1, 1].barh(
            [p["label"] for p in comparisons],
            [p["interface_improvement_fraction"] * 100 for p in comparisons],
            color=palette[0],
        )
        axes[1, 1].axvline(75, linestyle="--", color=palette[3], label="固定最低改善 75%")
        axes[1, 1].set(xlabel="接口峰值降低 %", title="短轨迹 / 载荷留出 / 原长轨迹")
        for ax in axes.flat:
            ax.grid(alpha=0.15)
            ax.legend(fontsize=7)
        figures.append(("coupling-comparison", fig))

        item = items["midpoint_predictor-200"]
        trace = item["streams"]["coupling"]
        rows = np.asarray(trace["samples"])
        columns = trace["columns"]
        time = rows[:, 0] * 1000
        fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27), layout="constrained")
        fig.suptitle("预测器状态与仍然保留的能量误差", fontsize=18)
        for name, label in (("actual_delta_rad", "实际端点挠度"),
                            ("predicted_delta_rad", "预测中点挠度")):
            axes[0, 0].plot(time, rows[:, columns.index(name)], label=label)
        axes[0, 0].set(xlabel="起始宏步时间 ms", ylabel="挠度 rad",
                       title="预测不是实际储能状态")
        for name, label in (("instant_motor_torque_nm", "瞬时 PWM 取样"),
                            ("previous_mean_motor_torque_nm", "普通窗口均值"),
                            ("previous_weighted_motor_torque_nm", "位移加权均值"),
                            ("forecast_motor_torque_nm", "因果加权预测")):
            axes[0, 1].plot(time, rows[:, columns.index(name)], label=label)
        axes[0, 1].set(xlabel="起始宏步时间 ms", ylabel="电磁转矩 N·m",
                       title="使用真实转矩积分，减少采样相位偏差")
        axes[0, 1].legend(fontsize=8)
        axes[1, 0].plot(time, rows[:, columns.index("robot_effective_inertia_kg_m2")])
        axes[1, 0].set(xlabel="时间 ms", ylabel="有效惯量 kg·m²",
                       title="1 / (M⁻¹)[j,j]，包含其余自由度")
        audit = item["streams"]["co_sim_energy"]
        values = np.asarray(audit["samples"])
        for name, label in (("interface_residual_j", "接口余额"),
                            ("robot_balance_residual_j", "机器人积分/求积"),
                            ("extended_residual_j", "扩展余额")):
            axes[1, 1].plot(values[:, 0] * 1000,
                            values[:, audit["columns"].index(name)], label=label)
        axes[1, 1].set(xlabel="时间 ms", ylabel="未平衡能量 J",
                       title="误差单列，不补成发热")
        for ax in axes.flat:
            ax.grid(alpha=0.15)
        axes[0, 0].legend(fontsize=8)
        axes[1, 1].legend(fontsize=8)
        figures.append(("coupling-predictor", fig))

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
            "", "未覆盖：完整关节 FMU/OpenModelica、全系统能量闭合、真机实测。",
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
        report_lines.append(
            f"- {edge['from']} → {edge['to']}：{edge['label']}。{edge['mechanism']}"
        )
    report_lines += ["", "## 范围和复现", json.dumps(data["scope"], ensure_ascii=False, indent=2),
                     "", "所有参数与标定数据为合成研究值；不代表真机测量或硬件保护认证。",
                     "尚未实现完整关节 FMU/OpenModelica、全系统能量闭合与真机参数标定。",
                     "", "复现命令：", "~~~bash", *data["commands"], "~~~"]
    if refined.get("passed"):
        report_lines += [
            "", "## 开源模型深化实验", "",
            "motulator 负责开关/磁图/母线，MuJoCo 负责 UR5e 连杆与接触；"
            "通过固定数值门槛不代表每个物理目标都达成。",
            json.dumps(refined["sources"], ensure_ascii=False, indent=2),
            "", "| 实验 | 后端 | 物理目标 | 数值/域检查 |", "|---|---|---|---|",
        ]
        for case in refined["electrical"] + refined["robot"]["cases"]:
            goal = case.get("tracking_goal_passed", case.get("position_goal_passed"))
            report_lines.append(
                f"| {case['title']} | {case['backend']} | "
                f"{'达成' if goal else '未达'} | "
                f"{'通过' if case['numeric_passed'] else '失败'} |"
            )
        report_lines += [
            "", "独立参考：",
            json.dumps(refined["references"], ensure_ascii=False, indent=2),
            "", "机器人参考与宏步收敛：",
            json.dumps(refined["robot"]["references"], ensure_ascii=False, indent=2),
            str(refined["robot"]["macro_step_halving_error_rad"]) + " rad",
            "", "范围限制：", *refined["limits"],
        ]
    if design.get("validations"):
        report_lines += [
            "", "## 统一实验接口与受保护的控制设计",
            "IR 0.2 的五个配置共用带单位输入、结果流、CLI 和 Agent 工具接口。",
            "Optuna 仅修改 Kp / Kd；轨迹、时长、限流、验收阈值与预算固定。",
            "训练采用平均逆变器；验证采用 PWM、死区与压降；0.5 kg 载荷未参与训练。",
            "设计门槛：" + str(design["passed"]),
            "选定增益：" + json.dumps(design["best_gains"]),
            "基准尾段误差改善：" + str(design["baseline_improvement_fraction"]),
            "", "| 验证工况 | 原始误差 rad | 优化误差 rad | 优化后固定目标 |",
            "|---|---:|---:|---|",
        ]
        for pair in design["validations"]:
            old = pair["baseline"]["verification"]
            new = pair["optimized"]["verification"]
            report_lines.append(
                f"| {pair['id']} | {old['metrics']['position_tail_error_rad']:.6g} | "
                f"{new['metrics']['position_tail_error_rad']:.6g} | {new['passed']} |"
            )
        report_lines += ["", "分析边界：", *design["limits"]]
    if energy_report.get("passed"):
        report_lines += [
            "", "## 电驱与连续热网络能量核算",
            "局部边界：" + energy_report["boundary"],
            "固定门槛：" + energy_report["local_gate"],
            "内部损耗进入热储能，源功率从实际直流端口积分，不从守恒式反算。",
            "机器人接口与机械积分/做功求积误差单列，不用局部通过代表全局闭合。",
            "", "| 工况 | 局部最大余额 J | 固定容差 J | 数值/能量门槛 | 物理跟踪目标 |",
            "|---|---:|---:|---|---|",
        ]
        for item in energy_report["cases"]:
            metrics = item["metrics"]
            report_lines.append(
                f"| {item['title']} | {metrics['energy_balance_abs_j']:.6g} | "
                f"{metrics['energy_balance_limit_j']:.6g} | {item['numeric_passed']} | "
                f"{item['goal_passed']} |"
            )
        report_lines += [
            "", "负例为显式账本故障注入，不能冒充物理仿真。",
            json.dumps(energy_report["fault_demo"]["metrics"], ensure_ascii=False),
            "", *energy_report["limits"],
        ]
    if coupling_report.get("passed"):
        report_lines += [
            "", "## 中点预测与同积分器对照",
            "物理参数、轨迹和控制器固定；Jacobi 与预测器使用同一 RK4。",
            "原 implicitfast 单独保留，不把积分器贡献算作预测器贡献。",
            "固定门槛：" + coupling_report["fixed_gate"],
            "", "| 对照 | 接口峰值降低 | 扩展余额峰值降低 | 固定门槛 |",
            "|---|---:|---:|---|",
        ]
        for pair in coupling_report["comparisons"]:
            report_lines.append(
                f"| {pair['label']} | {pair['interface_improvement_fraction']:.2%} | "
                f"{pair['extended_improvement_fraction']:.2%} | {pair['passed']} |"
            )
        report_lines += [
            "", "预测器完整模型观测减半阶数：",
            str(coupling_report["observed_halving_orders"]),
            "孤立双惯量独立参考：",
            json.dumps(coupling_report["reference_checks"], ensure_ascii=False),
            "", *coupling_report["limits"],
        ]
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
