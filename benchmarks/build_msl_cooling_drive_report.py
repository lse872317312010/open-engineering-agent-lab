"""Five full-trajectory figures and a tested offline mechanism/state report."""
import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/msl-cooling-drive"
OUT = ROOT / "outputs/msl-cooling-drive-report"


def main(*, source=SOURCE, output=OUT,
         template="reports/msl-cooling-drive.html",
         contract="docs/msl-cooling-drive-contract.md"):
    output.mkdir(parents=True, exist_ok=True)
    plots = output / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((source / "validation.json").read_text())
    rows = {c["id"]:np.genfromtxt(source / c["id"] / "coupling.csv",
                                 delimiter=",", names=True) for c in data["cases"]}
    nominal = rows["radiation-feedback"]
    figures = []
    fig, ax = plt.subplots(figsize=(12, 4))
    for n in ("winding_c", "core_c", "case_c", "junction_c", "board_c", "sink_c"):
        ax.plot(nominal["time_s"], nominal[n], label=n)
    ax.set(xlabel="Time (s)", ylabel="Temperature (degC)",
           title="Actual drive losses, six configured initial temperatures")
    ax.legend(ncol=3)
    figures.append(("01-temperatures", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for n in ("case_w", "convection_w", "radiation_w"):
        axes[0].plot(nominal["time_s"], nominal[n], label=n)
    axes[0].set(xlabel="Time (s)", ylabel="Signed outward heat (W)")
    axes[0].legend()
    fan = rows["fan-varying"]
    axes[1].plot(fan["time_s"], fan["gc_w_k"], label="Equivalent Gc (W/K)")
    twin = axes[1].twinx()
    twin.plot(fan["time_s"], fan["convection_w"], color="orange", label="Convection (W)")
    axes[1].set(xlabel="Time (s)", ylabel="Gc (W/K)", title="Prescribed smooth Gc, not fan rpm")
    twin.set_ylabel("Actual convection (W)")
    figures.append(("02-cooling", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for key in ("radiation-feedback", "radiation-frozen"):
        r = rows[key]
        axes[0].plot(r["time_s"], r["iq_a"], label=key)
        axes[1].plot(r["time_s"], r["actual_r_ohm"], label=key)
    axes[0].set(xlabel="Time (s)", ylabel="Actual iq (A)")
    axes[1].set(xlabel="Time (s)", ylabel="Actual winding resistance (ohm)")
    for ax in axes:
        ax.legend(fontsize=8)
    figures.append(("03-control", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for n in ("case_out_j", "convection_out_j", "radiation_out_j"):
        axes[0].plot(nominal["time_s"], nominal[n], label=n)
    axes[0].set(xlabel="Time (s)", ylabel="Actual branch integral (J)")
    axes[0].legend()
    for case in data["cases"]:
        r = rows[case["id"]]
        axes[1].plot(r["time_s"], r["thermal_balance_j"], label=case["id"])
    axes[1].axhline(1e-7, color="red", linestyle="--")
    axes[1].axhline(-1e-7, color="red", linestyle="--")
    axes[1].set(xlabel="Time (s)", ylabel="Heat - storage change - ambient (J)")
    figures.append(("04-energy", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    names = [c["id"] for c in data["cases"]]
    axes[0].bar(names, [max(c["temperature_difference_k"], 1e-18) for c in data["cases"]])
    axes[0].axhline(2e-7, color="red", linestyle="--")
    axes[0].set(yscale="log", ylabel="Paired thermal-port temperature error (K)")
    axes[1].bar(names, [max(max(c["rhs_audit"]["derivative_errors"][:6]), 1e-18)
                        for c in data["cases"]])
    axes[1].axhline(2e-7, color="red", linestyle="--")
    axes[1].set(yscale="log", ylabel="Every serialized RHS thermal rate error (K/s)")
    for ax in axes:
        ax.tick_params(axis="x", rotation=30)
    figures.append(("05-validation", fig))
    with PdfPages(output / "report.pdf") as pdf:
        for name, fig in figures:
            fig.tight_layout()
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    for case in data["cases"]:
        shutil.copyfile(source / case["id"] / "coupling.csv", output / (case["id"]+".csv"))
    for path, target in [
        ("outputs/msl-cooling/OEALMSLCooling.fmu", "OEALMSLCooling.fmu"),
        (contract, "contract.md"),
        ("research/licenses/MSL-4.0.0.txt", "MSL-BSD3.txt"),
        ("research/licenses/motulator-refinement.txt", "motulator-LICENSE.txt"),
        ("LICENSE", "LICENSE")]:
        shutil.copyfile(ROOT / path, output / target)
    shutil.copyfile(source / "validation.json", output / "report-data.json")
    (output / "index.html").write_text((ROOT / template).read_text()
                                   .replace("__DATA__", json.dumps(data)))
    (output / "README.txt").write_text(
        "解压打开index.html。五图PDF/PNG/SVG、七组全控制CSV、热FMU及固定验收契约。\n"
        "实际电驱损耗联合仿真；环境和六节点初温见配置，不是长时耐久。\n"
        "原始包另含全部电磁细流、参考、RHS试探、故障副本和环境散列。\n")
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda r: network.append(r.url)
                if r.url.startswith(("http://", "https://")) else None)
        page.goto((output / "index.html").as_uri())
        assert page.locator("#case option").count() == 7
        assert page.locator("#results tbody tr").count() == 7
        assert page.evaluate("Array.from(document.images).every(i=>i.complete && i.naturalWidth>0)")
        for c in data["cases"]:
            page.select_option("#case", c["id"])
            page.locator("#time").focus()
            page.keyboard.press("Home")
            assert page.locator("#now").inner_text().startswith("0.00000 s")
            for i, initial in enumerate(c.get("initial_temperatures_c", [80.]*6)):
                assert f"{initial:.3f}" in page.locator(f"#n{i}").text_content()
            if page.locator("#ambient").count():
                assert str(c["ambient_c"]) in page.locator("#ambient").text_content()
                assert str(c["ambient_c"]) in page.locator("#configuration").inner_text()
            page.keyboard.press("End")
            assert abs(float(page.locator("#now").inner_text().split()[0])-c["duration_s"]) < 1e-10
            assert page.locator("#states .card").count() == 9
            assert "J" in page.locator("#states").inner_text()
            with page.expect_download() as download:
                page.locator("#csv").click()
            assert len(Path(download.value.path()).read_text().splitlines()) == c["rows"]+1
        page.select_option("#case", "fan-varying")
        for tick, status in ((.025, "高于基准"), (.075, "低于基准")):
            c = next(c for c in data["cases"] if c["id"] == "fan-varying")
            index = min(range(len(c["samples"])), key=lambda i:abs(c["samples"][i][0]-tick))
            page.locator("#time").evaluate(
                "(el,v)=>{el.value=v;el.dispatchEvent(new Event('input'))}",
                                            str(index))
            assert status in page.locator("#states").inner_text()
        page.locator("#play").click()
        assert page.locator("#play").get_attribute("aria-pressed") == "true"
        page.locator("#play").click()
        assert page.locator("#play").get_attribute("aria-pressed") == "false"
        page.screenshot(path=str(output / "ui-desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "ui-mobile.png"), full_page=True)
        version = browser.version
        browser.close()
    assert not errors and not network, (errors, network)
    assert (output / "report.pdf").read_bytes().startswith(b"%PDF")
    ui = dict(passed=True, browser=version, charts=5, page_errors=errors,
              external_requests=network, checks=["seven cases", "six node states",
                  "three real energy branches", "Gc high/low status", "keyboard endpoints",
                  "seven full CSVs", "play/pause", "390px", "PDF/PNG/SVG"])
    (output / "ui-validation.json").write_text(json.dumps(ui, ensure_ascii=False, indent=2))
    print("cooling-drive-ui: "+json.dumps(ui), flush=True)


if __name__ == "__main__":
    main()
