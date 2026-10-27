"""Offline FMI mechanism/state report, exportable figures, and real browser checks."""

import json
import shutil
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/fmi-servo"
OUT = ROOT / "outputs/fmi-servo-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    names = [case["id"] for case in data["cases"]]
    rows = {name: np.genfromtxt(SOURCE / (name+".csv"), delimiter=",", names=True)
            for name in names}
    figures = []
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    for name, row in rows.items():
        axes[0].plot(row["time_s"], row["load_angle_rad"], label=name)
        axes[1].plot(row["time_s"], row["load_speed_rad_s"])
    legacy = np.asarray(data["legacy_feedback"]["samples"])
    axes[0].plot(legacy[:, 0], legacy[:, 1], color="black", linestyle="--",
                 label="original A load-velocity")
    axes[0].set(ylabel="Load angle (rad)", title="Joint FMU: mechanical response")
    axes[0].legend(fontsize=8)
    axes[1].set(xlabel="Time (s)", ylabel="Load speed (rad/s)")
    figures.append(("01-mechanics", fig))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for name, row in rows.items():
        axes[0].plot(row["time_s"], row["iq_a"], label=name)
    axes[0].set(xlabel="Time (s)", ylabel="q current (A)", title="Electrical response")
    axes[0].legend(fontsize=8)
    positions = np.arange(len(names))
    axes[1].bar(positions, [c["metrics"]["position_tail_error_rad"] for c in data["cases"]])
    axes[1].axhline(.003, color="red", linestyle="--", label="fixed .003 rad goal")
    axes[1].set(yscale="log", title="Position tracking: retain expected failure",
                ylabel="Tail position error (rad)")
    axes[1].set_xticks(positions, names, rotation=20)
    axes[1].legend(fontsize=8)
    figures.append(("02-electrical-reference", fig))
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    for name, row in rows.items():
        axes[0].plot(row["time_s"], row["balance_j"], label=name)
        axes[1].plot(row["time_s"], row["board_c"]-25)
    axes[0].axhline(2e-6, color="red", linestyle="--")
    axes[0].axhline(-2e-6, color="red", linestyle="--")
    axes[0].set(ylabel="Energy balance (J)", title="All-domain energy ledger")
    axes[0].legend(fontsize=8)
    axes[1].set(xlabel="Time (s)", ylabel="Board rise (K)")
    figures.append(("03-energy-thermal", fig))
    fig, ax = plt.subplots(figsize=(10, 4))
    keys = ["stator_resistance_ohm", "d_inductance_h", "q_inductance_h",
            "flux_linkage_wb", "inertia_kg_m2", "viscous_friction_nms"]
    case = next(c for c in data["cases"] if c["id"] == "mismatch")
    deviations = [100*(case["physical_parameters"][k]/case["nominal_parameters"][k]-1)
                  for k in keys]
    ax.bar(np.arange(len(keys)), deviations)
    ax.set_xticks(np.arange(len(keys)), ["R25", "Ld", "Lq", "flux", "Jm", "Bm"])
    ax.set(ylabel="Actual / frozen nominal deviation (%)",
           title="Mismatch case: physical parameters change, controller estimates stay fixed")
    figures.append(("04-physical-parameters", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.tight_layout()
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    for name in names:
        shutil.copyfile(SOURCE / (name+".csv"), OUT / (name+".csv"))
    shutil.copyfile(SOURCE / "oeal-servo.fmu", OUT / "oeal-servo.fmu")
    shutil.copyfile(SOURCE / "validation.json", OUT / "report-data.json")
    shutil.copyfile(ROOT / "docs/fmi-servo-contract.md", OUT / "contract.md")
    template = (ROOT / "reports/fmi-servo.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__", json.dumps(data)))
    (OUT / "README.txt").write_text(
        "解压后打开 index.html。离线运行，无服务端。FMU 为 Linux x86_64 FMI 2.0。\n"
        "四个 PNG/SVG/PDF 图，六组完整 CSV，report-data.json 与固定契约随包提供。\n"
        "本版为外部位置/电流主机与可配置九状态 FMI 植物，不含 MuJoCo、开关 PWM 或 OpenModelica。\n"
    )
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: network.append(req.url)
                if req.url.startswith(("http://", "https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#case option").count() == 6
        assert page.locator("#results tbody tr").count() == 6
        for name in names:
            page.select_option("#case", name)
            page.locator("#time").focus()
            page.keyboard.press("Home")
            assert page.locator("#now").inner_text().startswith("0.00000 s")
            page.keyboard.press("End")
            assert page.locator("#now").inner_text().startswith("0.25000 s")
            assert page.locator("#states .card").count() == 4
            assert page.locator("#trace polyline").count() == 2
            assert page.locator("#parameters tbody tr").count() == 7
            with page.expect_download() as download:
                page.locator("#csv").click()
            lines = Path(download.value.path()).read_text().splitlines()
            assert len(lines) == 5002
            assert abs(float(lines[-1].split(",")[0])-.25) < 1e-12
        page.select_option("#case", "unreachable")
        assert "未达标" in page.locator("#case-result").inner_text()
        assert page.locator("#results tbody tr").last.locator("td").nth(1).inner_text() == "未达标"
        page.screenshot(path=str(OUT / "ui-desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"), full_page=True)
        version = browser.version
        browser.close()
    assert not errors and not network, (errors, network)
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    result = dict(passed=True, browser=version, charts=len(figures), page_errors=errors,
                  external_requests=network, matplotlib=matplotlib.__version__,
                  checks=["six cases with expected failure", "mechanism and state cards",
                          "keyboard endpoints",
                          "six full CSV exports", "390px layout", "PDF/PNG/SVG"])
    (OUT / "ui-validation.json").write_text(json.dumps(result, indent=2))
    print("fmi-servo-ui: " + json.dumps(result))


if __name__ == "__main__":
    main()
