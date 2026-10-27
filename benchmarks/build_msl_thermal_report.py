"""Four scientific figures, offline component replay, and real browser acceptance."""

import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/msl-thermal"
OUT = ROOT / "outputs/msl-thermal-report"
NAMES = ["winding_c", "core_c", "case_c", "junction_c", "board_c", "sink_c"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    rows = {c["id"]: np.genfromtxt(SOURCE / (c["id"]+".csv"), delimiter=",", names=True)
            for c in data["cases"]}
    nominal = rows["ambient-25-step-0.5"]
    figures = []
    fig, ax = plt.subplots(figsize=(10, 5))
    for name in NAMES:
        ax.plot(nominal["time_s"]/60, nominal[name], label=name.removesuffix("_c"))
    ax.set(xlabel="Time (min)", ylabel="Temperature (degC)",
           title="Actual MSL six-node network: one-hour prescribed loss replay")
    ax.legend(ncol=3, fontsize=9)
    ax.grid(alpha=.2)
    figures.append(("01-temperatures", fig))
    fig, ax = plt.subplots(figsize=(10, 4))
    x = np.arange(len(data["cases"]))
    ax.bar(x-.18, [c["max_reference_error_k"] for c in data["cases"]],
           width=.36, label="vs independent Radau")
    ax.bar(x+.18, [c["max_native_error_k"] for c in data["cases"]],
           width=.36, label="vs native matrix exponential")
    ax.axhline(2e-7, color="red", linestyle="--", label="fixed gate")
    ax.set_xticks(x, [c["id"] for c in data["cases"]], rotation=20, ha="right")
    ax.set(yscale="log", ylabel="Maximum full-trajectory temperature difference (K)",
           title="Every node and communication endpoint is checked")
    ax.legend(fontsize=8)
    figures.append(("02-reference-errors", fig))
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    stored = sum(c*(nominal[n]-25.) for c, n in
                 zip([60., 70., 200., .5, 25., 100.], NAMES, strict=True))
    for key, label in [("input_energy_j", "Input"), ("ambient_energy_j", "To ambient")]:
        axes[0].plot(nominal["time_s"]/60, nominal[key], label=label)
    axes[0].plot(nominal["time_s"]/60, stored, label="Stored thermal energy")
    axes[0].set(ylabel="Energy (J)", title="Signed energy accounting")
    axes[0].legend(fontsize=8)
    for name, row in rows.items():
        axes[1].plot(row["time_s"]/60, row["balance_j"], label=name)
    axes[1].axhline(1e-5, color="red", linestyle="--")
    axes[1].axhline(-1e-5, color="red", linestyle="--")
    axes[1].set(xlabel="Time (min)", ylabel="Balance (J)")
    axes[1].legend(fontsize=7, ncol=2)
    figures.append(("03-energy", fig))
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = ["winding to core", "core to case", "case to board",
              "junction to board", "board to sink"]
    for i, label in enumerate(labels, 1):
        ax.plot(nominal["time_s"]/60, nominal[f"link_{i}_w"], label=label)
    ax.plot(nominal["time_s"]/60, nominal["heat_to_ambient_w"],
            linestyle="--", label="total to ambient")
    ax.axhline(0, color="gray", linewidth=.7)
    ax.set(xlabel="Time (min)", ylabel="Signed heat flow (W)",
           title="Actual component port flows and heat rejection")
    ax.legend(fontsize=8, ncol=2)
    figures.append(("04-flows", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.tight_layout()
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    for case in data["cases"]:
        shutil.copyfile(SOURCE / (case["id"]+".csv"), OUT / (case["id"]+".csv"))
    for name in ["OEALMSLThermal.fmu", "contract.md", "build-provenance.json",
                 "compiler-package-copyright.txt", "OEALMSLThermal.mo"]:
        shutil.copyfile(SOURCE / name, OUT / name)
    shutil.copyfile(ROOT / "research/licenses/MSL-4.0.0.txt", OUT / "MSL-BSD3.txt")
    shutil.copyfile(ROOT / "LICENSE", OUT / "LICENSE")
    shutil.copyfile(SOURCE / "validation.json", OUT / "report-data.json")
    template = (ROOT / "reports/msl-thermal.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__", json.dumps(data)))
    (OUT / "README.txt").write_text(
        "解压打开index.html；离线六节点温度/有符号热流/状态回放与四图PDF/PNG/SVG。\n"
        "六组完整CSV保留真实通信端点，输入列为该点前窗保持功率。\n"
        "实际MSL4.0.0组件与OpenModelica1.25.5导出，Linux x86_64 ME FMU。\n"
        "固定合成热阻热容与损耗回放；不是一小时电机/机器人联合运行或实物标定。\n")
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
        assert page.evaluate("Array.from(document.images).every(i=>i.complete && i.naturalWidth>0)")
        for case in data["cases"]:
            page.select_option("#case", case["id"])
            page.locator("#time").focus()
            page.keyboard.press("Home")
            assert page.locator("#now").inner_text().startswith("0.0 s")
            page.keyboard.press("End")
            assert page.locator("#now").inner_text().startswith("3600.0 s")
            assert page.locator("#states .card").count() == 6
            assert page.locator("#network rect").count() == 7
            assert page.locator("#network line").count() == 7
            assert page.locator("#trace polyline").count() == 6
            with page.expect_download() as download:
                page.locator("#csv").click()
            lines = Path(download.value.path()).read_text().splitlines()
            assert len(lines) == case["rows"]+1
            assert float(lines[-1].split(",")[0]) == 3600.
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
    result = dict(passed=True, browser=version, charts=len(figures), page_errors=errors,
                  external_requests=network,
                  checks=["six one-hour cases", "six node cards", "seven signed heat edges",
                          "six temperature traces", "keyboard endpoints", "play/pause",
                          "six complete CSV downloads", "390px layout", "PDF/PNG/SVG"])
    (OUT / "ui-validation.json").write_text(json.dumps(result, indent=2))
    print("msl-ui: "+json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
