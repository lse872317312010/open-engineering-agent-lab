"""Offline five-figure report for true continuous motulator/MSL feedback."""

import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/msl-drive"
OUT = ROOT / "outputs/msl-drive-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    rows = {c["id"]: np.genfromtxt(SOURCE / c["id"] / "coupling.csv",
                                   delimiter=",", names=True) for c in data["cases"]}
    figures = []
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    for ax, case in zip(axes.flat, data["cases"][:4], strict=True):
        r = rows[case["id"]]
        ax.plot(r["time_s"], r["iq_a"], label="MSL coupled")
        ax.plot(r["time_s"], r["native_iq_a"], "--", label="native coupled")
        ax.set(title=case["id"], xlabel="Time (s)", ylabel="q current (A)")
        ax.legend(fontsize=8)
    figures.append(("01-current", fig))
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for name in ("average-feedback", "average-frozen"):
        r = rows[name]
        axes[0].plot(r["time_s"], r["winding_c"]-25., label=name)
        axes[1].plot(r["time_s"], r["actual_r_ohm"], label=name)
    axes[0].set(ylabel="Winding rise (K)",
                title="Frozen nominal controller, actual thermal feedback")
    axes[0].legend(fontsize=8)
    axes[1].set(xlabel="Time (s)", ylabel="Actual resistance (ohm)")
    figures.append(("02-feedback", fig))
    fig, axes = plt.subplots(2, 1, figsize=(10, 6))
    r = rows["pwm-feedback"]
    axes[0].plot(r["time_s"], r["copper_w"], label="actual copper to winding")
    axes[0].plot(r["time_s"], r["device_w"], label="actual device heat to junction")
    axes[0].set(xlabel="Time (s)", ylabel="Heat input (W)", title="Physical loss ports")
    axes[0].legend(fontsize=8)
    r = rows["regeneration"]
    axes[1].plot(r["time_s"], r["source_w"], label="signed DC source power")
    axes[1].axhline(0, color="gray", linewidth=.7)
    axes[1].set(xlabel="Time (s)", ylabel="Source power (W)", title="Regeneration remains signed")
    axes[1].legend(fontsize=8)
    figures.append(("03-losses", fig))
    fig, axes = plt.subplots(2, 1, figsize=(10, 6))
    for case in data["cases"]:
        r = rows[case["id"]]
        axes[0].plot(r["time_s"], abs(r["local_balance_j"])/case["local_limit_j"],
                     label=case["id"])
        axes[1].plot(r["time_s"], r["thermal_balance_j"])
    axes[0].axhline(1., color="red", linestyle="--")
    axes[0].set(ylabel="Absolute balance / fixed limit", title="Independent energy reconstruction")
    axes[0].legend(fontsize=8)
    axes[1].axhline(1e-7, color="red", linestyle="--")
    axes[1].axhline(-1e-7, color="red", linestyle="--")
    axes[1].set(xlabel="Time (s)", ylabel="Thermal balance (J)")
    figures.append(("04-energy", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    names = [c["id"] for c in data["cases"]]
    axes[0].bar(names, [max(c["temperature_difference_k"], 1e-18) for c in data["cases"]])
    axes[0].axhline(2e-7, color="red", linestyle="--")
    axes[0].set(yscale="log", ylabel="Paired temperature error (K)",
                title="Full accepted control trajectories")
    axes[1].bar(names, [max(max(c["rhs_audit"]["derivative_errors"][:6]), 1e-18)
                        for c in data["cases"]])
    axes[1].axhline(2e-7, color="red", linestyle="--")
    axes[1].set(yscale="log", ylabel="Independent derivative error (K/s)",
                title="Every serialized RHS trial; display floor 1e-18")
    for ax in axes:
        ax.tick_params(axis="x", rotation=25)
    figures.append(("05-derivatives", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.tight_layout()
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    for case in data["cases"]:
        shutil.copyfile(SOURCE / case["id"] / "coupling.csv", OUT / (case["id"]+".csv"))
    shutil.copyfile(ROOT / "outputs/msl-thermal/OEALMSLThermal.fmu", OUT / "OEALMSLThermal.fmu")
    shutil.copyfile(ROOT / "docs/msl-drive-contract.md", OUT / "contract.md")
    shutil.copyfile(ROOT / "research/licenses/MSL-4.0.0.txt", OUT / "MSL-BSD3.txt")
    shutil.copyfile(ROOT / "research/licenses/motulator-refinement.txt",
                    OUT / "motulator-LICENSE.txt")
    shutil.copyfile(ROOT / "LICENSE", OUT / "LICENSE")
    shutil.copyfile(SOURCE / "validation.json", OUT / "report-data.json")
    template = (ROOT / "reports/msl-drive.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__", json.dumps(data)))
    (OUT / "README.txt").write_text(
        "解压打开index.html。五图PDF/PNG/SVG、五组全控制CSV、完整验证摘要和Linux热FMU。\n"
        "实际损耗/同阶段温度反馈；不是热源回放或一小时电机/机器人运行。\n"
        "CSV中R在|i|>.1A由真实铜耗/电流恢复，其余点显示已核验温度映射。\n"
        "完整电磁/能量/原生对照及所有RHS试探gzipCSV在原始证据包。\n")
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: network.append(req.url)
                if req.url.startswith(("http://", "https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#case option").count() == 5
        assert page.locator("#results tbody tr").count() == 5
        assert page.evaluate("Array.from(document.images).every(i=>i.complete && i.naturalWidth>0)")
        for case in data["cases"]:
            page.select_option("#case", case["id"])
            page.locator("#time").focus()
            page.keyboard.press("Home")
            assert page.locator("#now").inner_text().startswith("0.00000 s")
            page.keyboard.press("End")
            assert abs(float(page.locator("#now").inner_text().split()[0])
                       - case["duration_s"]) <= 1e-10
            assert page.locator("#states .card").count() == 4
            assert page.locator("#trace polyline").count() == 2
            with page.expect_download() as download:
                page.locator("#csv").click()
            lines = Path(download.value.path()).read_text().splitlines()
            assert len(lines) == case["rows"]+1
            assert abs(float(lines[-1].split(",")[0])-case["duration_s"]) <= 1e-12
        page.locator("#play").click()
        assert page.locator("#play").get_attribute("aria-pressed") == "true"
        page.locator("#play").click()
        assert page.locator("#play").get_attribute("aria-pressed") == "false"
        page.screenshot(path=str(OUT / "ui-desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"), full_page=True)
        version = browser.version
        browser.close()
    assert not errors and not network, (errors, network)
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    ui = dict(passed=True, browser=version, charts=5, page_errors=errors,
              external_requests=network,
              checks=["five cases", "four state cards with all six temperatures",
                      "keyboard endpoints",
                      "five full control CSVs", "play/pause", "390px layout", "PDF/PNG/SVG"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui, indent=2))
    print("msl-drive-ui: "+json.dumps(ui), flush=True)


if __name__ == "__main__":
    main()
