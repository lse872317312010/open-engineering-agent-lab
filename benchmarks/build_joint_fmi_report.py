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
SOURCE = ROOT / "outputs/joint-fmi"
OUT = ROOT / "outputs/joint-fmi-report"


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
    axes[1].bar(positions-.18, [c["max_state_error"] for c in data["cases"]],
                width=.36, label="5 us")
    axes[1].bar(positions+.18, [c["fine_state_error"] for c in data["cases"]],
                width=.36, label="2.5 us")
    axes[1].axhline(2e-5, color="red", linestyle="--", label="fixed gate")
    axes[1].set(yscale="log", title="Independent DOP853 discrepancy",
                ylabel="Max absolute error in each state's SI unit")
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
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.tight_layout()
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    for name in names:
        shutil.copyfile(SOURCE / (name+".csv"), OUT / (name+".csv"))
    shutil.copyfile(SOURCE / "oeal-joint.fmu", OUT / "oeal-joint.fmu")
    shutil.copyfile(SOURCE / "validation.json", OUT / "report-data.json")
    shutil.copyfile(ROOT / "docs/joint-fmi-contract.md", OUT / "contract.md")
    template = (ROOT / "reports/joint-fmi.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__", json.dumps(data)))
    (OUT / "README.txt").write_text(
        "解压后打开 index.html。离线运行，无服务端。FMU 为 Linux x86_64 FMI 2.0。\n"
        "三个 PNG/SVG/PDF 图，四组完整 CSV，report-data.json 与固定契约随包提供。\n"
        "本版为合成九状态植物，不含控制器、MuJoCo、开关 PWM 或 OpenModelica。\n"
    )
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: network.append(req.url)
                if req.url.startswith(("http://", "https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#case option").count() == 4
        assert page.locator("#results tbody tr").count() == 4
        for name in names:
            page.select_option("#case", name)
            page.locator("#time").focus()
            page.keyboard.press("Home")
            assert page.locator("#now").inner_text().startswith("0.00000 s")
            page.keyboard.press("End")
            assert page.locator("#now").inner_text().startswith("0.08000 s")
            assert page.locator("#states .card").count() == 4
            assert page.locator("#trace polyline").count() == 2
            with page.expect_download() as download:
                page.locator("#csv").click()
            lines = Path(download.value.path()).read_text().splitlines()
            assert len(lines) == 1602
            assert abs(float(lines[-1].split(",")[0])-.08) < 1e-12
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
                  checks=["four cases", "mechanism and state cards", "keyboard endpoints",
                          "four full CSV exports", "390px layout", "PDF/PNG/SVG"])
    (OUT / "ui-validation.json").write_text(json.dumps(result, indent=2))
    print("joint-fmi-ui: " + json.dumps(result))


if __name__ == "__main__":
    main()
