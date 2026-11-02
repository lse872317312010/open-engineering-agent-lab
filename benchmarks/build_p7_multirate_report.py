"""Offline multirate event/energy report with actual Chrome playback verification."""
import gzip
import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-multirate"
OUT = ROOT / "outputs/p7-multirate-report"


def records(path):
    values = np.genfromtxt(path, delimiter=",", names=True)
    return [{n:float(r[n]) for n in values.dtype.names} for r in values]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    controls, thermal = {}, {}
    for c in data["cases"]:
        folder = SOURCE / c["id"]
        controls[c["id"]] = records(folder / "control.csv")
        thermal[c["id"]] = records(folder / "thermal.csv")
        shutil.copytree(folder, OUT / c["id"], dirs_exist_ok=True)
    figures = []
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    for name in ("feedback", "frozen-resistance", "regeneration"):
        a = controls[name]
        axes[0].plot([r["time_s"] for r in a], [r["iq_a"] for r in a], label=name)
        axes[1].plot([r["time_s"] for r in a], [r["resistance_ohm"] for r in a], label=name)
    a = controls["feedback"]
    axes[0].plot([r["time_s"] for r in a], [r["iq_reference_a"] for r in a],
                 "--", label="Positive reference")
    axes[0].set(xlabel="Time (s)", ylabel="Iq (A)")
    axes[1].set(xlabel="Time (s)", ylabel="Physical R (ohm), nominal R frozen")
    for ax in axes:
        ax.legend(fontsize=7)
    figures.append(("01-control", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    for name in ("feedback", "fine-thermal", "regeneration"):
        a = thermal[name]
        for ax, key in zip(axes, ("left_c", "right_c"), strict=True):
            ax.plot([r["time_s"] for r in a], [r[key] for r in a], label=name)
    for ax, side in zip(axes, ("left", "right"), strict=True):
        a = thermal["feedback"]
        ax.plot([r["time_s"] for r in a], [r["fom_"+side+"_c"] for r in a],
                "--", label="FOM same-heat replay")
        ax.plot([r["time_s"] for r in a], [r["fast_"+side+"_c"] for r in a],
                ":", label="20 kHz ROM heat replay")
        ax.set(xlabel="Time (s)", ylabel=side+" mean temperature (degC)")
        ax.legend(fontsize=7)
    figures.append(("02-thermal", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    a = thermal["feedback"]
    t = [r["time_s"] for r in a]
    for values, label in (
        ([r["input_left_j"]+r["input_right_j"] for r in a], "Real mapped heat"),
        ([r["stored_left_j"]+r["stored_right_j"] for r in a], "Stored change"),
        ([r["left_out_j"]+r["right_out_j"] for r in a], "Boundary out")):
        axes[0].plot(t, values, label=label)
    for name in controls:
        a = controls[name]
        axes[1].semilogy([r["time_s"] for r in a],
                        [max(abs(r["electrical_balance_j"]), 1e-18) for r in a], label=name)
    axes[0].set(xlabel="Time (s)", ylabel="Thermal energy (J)")
    axes[1].set(xlabel="Time (s)", ylabel="Electrical ledger balance (J), floor 1e-18")
    for ax in axes:
        ax.legend(fontsize=7)
    figures.append(("03-energy", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    for name in ("feedback", "fine-thermal"):
        a = controls[name]
        axes[0].step([r["time_s"] for r in a], [r["thermal_updates"] for r in a], label=name)
    for c in data["cases"]:
        axes[1].semilogy([0, 1, 2], [max(c[k], 1e-18) for k in
                        ("mapped_energy_error_j", "last_sample_fault_j", "missing_final_fault_j")],
                        "o-", label=c["id"])
    axes[0].set(xlabel="Time (s)", ylabel="Closed thermal windows")
    axes[1].set(xticks=[0, 1, 2], xticklabels=["Correct", "Last sample fault", "Drop last window"],
                ylabel="Source mapping error (J), floor 1e-18")
    for ax in axes:
        ax.legend(fontsize=7)
    figures.append(("04-clock", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    shutil.copyfile(SOURCE / "validation.json", OUT / "validation.json")
    shutil.copyfile(ROOT / "docs/p7-multirate-contract.md", OUT / "contract.md")
    for name in ("pymor-2026.1.1-LICENSE.txt", "pymor-2026.1.1-LICENSES_bundled.txt",
                 "gmsh-4.13.1.txt", "scikit-fem-11.0.0.txt", "meshio-5.3.5.txt",
                 "motulator-refinement.txt"):
        shutil.copyfile(ROOT / "research/licenses" / name, OUT / name)
    template = (ROOT / "reports/p7-multirate.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__", json.dumps(data))
                                   .replace("__CONTROLS__", json.dumps(controls))
                                   .replace("__THERMAL__", json.dumps(thermal)))
    (OUT / "README.txt").write_text(
        "解压打开index.html。四组实际平均桥电驱、20k控制与400/800Hz热窗口。\n"
        "全部控制/热窗口CSV、RHS试探gzip、FE/ROM热重放场、四图PDF/PNG/SVG。\n")
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: network.append(r.url)
                if r.url.startswith(("http://", "https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#results tbody tr").count() == 4
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for c in data["cases"]:
            page.select_option("#case", c["id"])
            for tick in (0, 223, c["ratio"]*10-1, c["ratio"]*10, 2713, 5000):
                page.locator("#time").evaluate(
                    "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'));}", tick)
                r = controls[c["id"]][tick]
                t = thermal[c["id"]][tick//c["ratio"]]
                for selector, expected in (
                    ("#electrical b", [r[n] for n in
                                      ("iq_a", "iq_reference_a", "speed_rad_s", "resistance_ohm")]),
                    ("#thermal b", [r[n] for n in ("held_left_c", "held_right_c",
                                                  "temperature_age_ticks",
                                                  "nominal_resistance_ohm")]),
                    ("#energy b", [r["copper_j"], r["device_j"],
                                    t["input_left_j"]+t["input_right_j"],
                                    t["stored_left_j"]+t["stored_right_j"]]),
                    ("#power b", [t["mean_left_w"], t["mean_right_w"], t["interface_right_w"],
                                   t["left_out_j"]+t["right_out_j"]])):
                    for text, value in zip(
                            page.locator(selector).all_text_contents(), expected, strict=True):
                        assert abs(float(text.split()[0])-value) <= max(1e-9, abs(value)*6e-6)
                assert float(page.locator("#window").get_attribute("value")) == (
                    r["temperature_age_ticks"])
                if tick == 5000:
                    assert "不再发新控制命令" in page.locator("#phase").inner_text()
            for selector, count in (("#control", c["control_rows"]+1),
                                    ("#windows", c["thermal_rows"]+1)):
                with page.expect_download() as download:
                    page.locator(selector).click()
                assert len(Path(download.value.path()).read_text().splitlines()) == count
            with page.expect_download() as download:
                page.locator("#rhs").click()
            with gzip.open(download.value.path(), "rt") as raw:
                assert sum(1 for _ in raw) == c["rhs_rows"]+1
            with page.expect_download() as download:
                page.locator("#fields").click()
            fields = np.load(download.value.path())
            assert fields["rom_temperature_c"].shape == (c["thermal_rows"], 2178)
            assert fields["fom_temperature_c"].shape == (c["thermal_rows"], 2178)
            assert fields["fast_20khz_states"].shape == (5001, 22)
        page.locator("#time").focus()
        page.keyboard.press("Home")
        assert page.locator("#time").input_value() == "0"
        page.keyboard.press("End")
        assert page.locator("#time").input_value() == "5000"
        page.locator("#play").click()
        page.wait_for_timeout(350)
        assert int(page.locator("#time").input_value()) > 0
        page.locator("#play").click()
        value = page.locator("#time").input_value()
        page.wait_for_timeout(200)
        assert page.locator("#time").input_value() == value
        assert page.locator("#play").get_attribute("aria-pressed") == "false"
        page.screenshot(path=str(OUT / "ui-desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"), full_page=True)
        version = browser.version
        browser.close()
    assert not errors and not network, (errors, network)
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    ui = dict(passed=True, browser=version, cases=4, page_errors=errors, external_requests=network,
              checks=["state/power/energy numbers", "window age and boundary ordering",
                      "terminal no extra command", "8 full CSVs and 4 RHS gzip/NPZ",
                      "keyboard/play/pause", "390px", "four figures/PDF"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui, indent=2))
    print("p7-multirate-ui: "+json.dumps(ui), flush=True)


if __name__ == "__main__":
    main()
