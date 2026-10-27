"""Five scientific figures and offline nonlinear cooling interaction acceptance."""

import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/msl-cooling"
OUT = ROOT / "outputs/msl-cooling-report"
NAMES = ["winding_c", "core_c", "case_c", "junction_c", "board_c", "sink_c"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    rows = {c["id"]: np.genfromtxt(SOURCE / (c["id"]+".csv"), delimiter=",", names=True)
            for c in data["cases"]}
    nominal = rows["radiation"]
    figures = []
    fig, ax = plt.subplots(figsize=(10, 5))
    for name in NAMES:
        ax.plot(nominal["time_s"]/60, nominal[name], label=name.removesuffix("_c"))
    ax.set(xlabel="Time (min)", ylabel="Temperature (degC)",
           title="Actual MSL convection and Kelvin fourth-power radiation")
    ax.legend(ncol=3, fontsize=9)
    ax.grid(alpha=.2)
    figures.append(("01-temperatures", fig))
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for case in ("linear-limit", "radiation"):
        r = rows[case]
        axes[0].plot(r["time_s"]/60, r["sink_c"], label=case)
        axes[1].plot(r["time_s"]/60, r["winding_c"], label=case)
    axes[0].set(ylabel="Sink temperature (degC)", title="Same prescribed heat, added radiation")
    axes[0].legend()
    axes[1].set(xlabel="Time (min)", ylabel="Winding temperature (degC)")
    figures.append(("02-radiation", fig))
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    fan = rows["fan-loss-recovery"]
    axes[0].step(fan["time_s"]/60, fan["previous_gc_w_k"], where="pre")
    axes[0].set(ylabel="Convection Gc (W/K)",
                title="Prescribed fan proxy: weak cooling and recovery")
    axes[1].plot(fan["time_s"]/60, fan["sink_c"], label="fan-loss-recovery")
    axes[1].plot(nominal["time_s"]/60, nominal["sink_c"], "--", label="constant Gc")
    axes[1].set(xlabel="Time (min)", ylabel="Sink temperature (degC)")
    axes[1].legend()
    for ax in axes:
        ax.axvline(20, color="gray", linestyle=":")
        ax.axvline(40, color="gray", linestyle=":")
    figures.append(("03-fan", fig))
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for name in ("case_energy_j", "convection_energy_j", "radiation_energy_j"):
        axes[0].plot(nominal["time_s"]/60, nominal[name], label=name.removesuffix("_j"))
    axes[0].set(ylabel="Energy to ambient (J)", title="Three actual cooling-branch integrals")
    axes[0].legend(fontsize=8)
    for name, r in rows.items():
        axes[1].plot(r["time_s"]/60, r["balance_j"], label=name)
    axes[1].axhline(1e-5, color="red", linestyle="--")
    axes[1].axhline(-1e-5, color="red", linestyle="--")
    axes[1].set(xlabel="Time (min)", ylabel="Independent balance (J)")
    axes[1].legend(fontsize=7, ncol=2)
    figures.append(("04-energy", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].bar([c["id"] for c in data["cases"]],
                [max(c["max_reference_error_k"], 1e-18) for c in data["cases"]])
    axes[0].axhline(2e-7, color="red", linestyle="--")
    axes[0].set(yscale="log", ylabel="All-endpoint maximum difference (K)",
                title="Independent Radau reference")
    axes[0].tick_params(axis="x", rotation=25)
    for name in ("radiation", "hot-ambient", "cold-ambient"):
        r = rows[name]
        axes[1].plot(r["time_s"]/60, r["radiation_heat_w"], label=name)
    axes[1].set(xlabel="Time (min)", ylabel="Radiation heat (W)",
                title="Absolute-temperature nonlinear boundary")
    axes[1].legend(fontsize=8)
    figures.append(("05-validation", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.tight_layout()
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    for case in data["cases"]:
        shutil.copyfile(SOURCE / (case["id"]+".csv"), OUT / (case["id"]+".csv"))
    for name in ("OEALMSLCooling.fmu", "OEALMSLCooling.mo", "contract.md",
                 "build-provenance.json", "compiler-package-copyright.txt"):
        shutil.copyfile(SOURCE / name, OUT / name)
    shutil.copyfile(ROOT / "LICENSE", OUT / "LICENSE")
    shutil.copyfile(ROOT / "research/licenses/MSL-4.0.0.txt", OUT / "MSL-BSD3.txt")
    shutil.copyfile(SOURCE / "validation.json", OUT / "report-data.json")
    template = (ROOT / "reports/msl-cooling.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__", json.dumps(data)))
    (OUT / "README.txt").write_text(
        "解压打开index.html；五图PDF/PNG/SVG、六组完整CSV、Linux x86_64 ME FMU。\n"
        "真实MSL Convection/BodyRadiation；三散热支路有符号功率及积分。\n"
        "Gc为外部等效导热系数，Gr为合成有效面积；不是风速/CFD或器件额定值。\n"
        "一小时预设损耗回放，不是一小时电机/机器人联合耐久。\n")
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
            assert page.locator("#network path").count() == 2
            assert "辐射 Gr" in page.locator("#network").text_content()
            assert page.locator("#trace polyline").count() == 6
            assert "辐射" in page.locator("#ledger").inner_text()
            assert "m²" in page.locator("#ledger").inner_text()
            with page.expect_download() as download:
                page.locator("#csv").click()
            lines = Path(download.value.path()).read_text().splitlines()
            assert len(lines) == case["rows"]+1
            assert float(lines[-1].split(",")[0]) == 3600.
        page.select_option("#case", "fan-loss-recovery")
        fan_case = next(c for c in data["cases"] if c["id"] == "fan-loss-recovery")
        mid = next(i for i, r in enumerate(fan_case["samples"]) if r[0] == 1800.)
        page.locator("#time").evaluate(
            "(e,i)=>{e.value=i;e.dispatchEvent(new Event('input'))}", mid)
        assert "风冷 减弱" in page.locator("#ledger").inner_text()
        page.locator("#time").focus()
        page.keyboard.press("End")
        assert "风冷 增强" in page.locator("#ledger").inner_text()
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
    result = dict(passed=True, browser=version, charts=5, page_errors=errors,
                  external_requests=network,
                  checks=["six one-hour cases", "six node cards", "three cooling branches",
                          "Kelvin fourth-power radiation", "fan proxy and energy states",
                          "keyboard endpoints", "six full CSVs", "play/pause",
                          "390px layout", "PDF/PNG/SVG"])
    (OUT / "ui-validation.json").write_text(json.dumps(result, indent=2))
    print("msl-cooling-ui: "+json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
