"""Four-figure offline transient replay and actual Chrome interaction checks."""
import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-transient"
OUT = ROOT / "outputs/p7-transient-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    fields = {}
    arrays = {}
    for c in data["cases"]:
        folder = SOURCE / c["id"]
        f = np.load(folder / "field.npz")
        offset = len(f["points"])//2
        assert np.all(f["points"][:offset, 0] <= .04+1e-12)
        fields[c["id"]] = dict(points=f["points"].tolist(), rows=f["rows"].tolist(),
                               temperatures=f["temperature_c"].tolist(),
                               high=float(np.max(f["temperature_c"]))+.2, offset=offset)
        arrays[c["id"]] = f["rows"]
        shutil.copytree(folder, OUT / c["id"], dirs_exist_ok=True)
    finest = arrays["n32-dt0.05"]
    figures = []
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    axes[0].plot(finest[:, 0], finest[:, 2], label="Material 1 volume mean")
    axes[0].plot(finest[:, 0], finest[:, 3], label="Material 2 volume mean")
    axes[1].plot(finest[:, 0], finest[:, 4], label="Interface left")
    axes[1].plot(finest[:, 0], finest[:, 5], label="Interface right")
    for ax in axes:
        ax.axvline(8, color="gray", linestyle="--")
        ax.set(xlabel="Time (s)", ylabel="Temperature (degC)")
        ax.legend()
    figures.append(("01-time", fig))
    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    for col, label in ((13, "Input"), (12, "Stored change"), (14, "Left out"), (15, "Right out")):
        ax.plot(finest[:, 0], finest[:, col], label=label)
    ax.set(xlabel="Time (s)", ylabel="Energy relative to initial state (J)")
    ax.legend()
    figures.append(("02-energy", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    group = [c for c in data["cases"] if c["n"] == 8]
    axes[0].loglog([c["dt_s"] for c in group], [c["time_rms_relative"] for c in group], "o-")
    axes[0].set(xlabel="Time step (s)", ylabel="Same-FE modal time relative RMS")
    for key, label in (("richardson_rms_relative", "Time Richardson estimate"),
                       ("cn_dt005_rms_relative", "Actual CN dt=.05")):
        axes[1].loglog([1/c["n"] for c in data["spatial"]],
                      [c[key] for c in data["spatial"]], "o-", label=label)
    axes[1].set(xlabel="1 / intervals per material", ylabel="Independent FV relative RMS")
    axes[1].legend()
    figures.append(("03-convergence", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    for col, label in ((6, "Source"), (7, "Left out"), (8, "Right out"), (9, "Interface right")):
        axes[0].plot(finest[:, 0], finest[:, col], label=label)
    axes[0].set(xlabel="Time (s)", ylabel="Previous interval mean power (W)")
    for col, label in ((17, "Correct global"), (18, "Correct left"), (19, "Correct right"),
                       (22, "FAULT: omitted fixed-row transient capacity")):
        axes[1].semilogy(finest[:, 0], np.maximum(abs(finest[:, col]), 1e-18), label=label)
    axes[1].set(xlabel="Time (s)", ylabel="Absolute energy balance (J), floor 1e-18")
    for ax in axes:
        ax.legend(fontsize=7)
    figures.append(("04-flux", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    shutil.copytree(SOURCE / "double-capacity", OUT / "double-capacity", dirs_exist_ok=True)
    for p in SOURCE.glob("fv-reference-*.npz"):
        shutil.copyfile(p, OUT / p.name)
    shutil.copyfile(SOURCE / "validation.json", OUT / "validation.json")
    shutil.copyfile(ROOT / "docs/p7-transient-contract.md", OUT / "contract.md")
    for name in ("gmsh-4.13.1", "scikit-fem-11.0.0", "meshio-5.3.5"):
        shutil.copyfile(ROOT / f"research/licenses/{name}.txt", OUT / (name+"-LICENSE.txt"))
    template = (ROOT / "reports/p7-transient.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__", json.dumps(data))
                                   .replace("__FIELDS__", json.dumps(fields)))
    (OUT / "README.txt").write_text(
        "解压打开index.html。九组合、完整时间/节点CSV、四图PDF/PNG/SVG、矩阵/全场。\n"
        "瞬态为理想合成热源，功率卡显示上一区间平均；参考职责见契约。\n")
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: network.append(r.url)
                if r.url.startswith(("http://", "https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#results tbody tr").count() == 9
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for c in data["cases"]:
            page.select_option("#mesh", str(c["n"]))
            page.select_option("#dt", str(c["dt_s"]))
            rows = arrays[c["id"]]
            for step in (0, round(4/c["dt_s"]), round(8/c["dt_s"]), c["rows"]-1):
                page.locator("#time").evaluate(
                    "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'));}", step)
                assert page.locator("#field circle").count() == c["nodes"]
                r = rows[step]
                for selector, expected in (
                    ("#state b", r[2:6]), ("#mechanism b", r[6:10]),
                    ("#energy b", r[[13, 10, 11, 12, 14, 15]])):
                    for text, value in zip(
                            page.locator(selector).all_text_contents(), expected, strict=True):
                        assert abs(float(text.split()[0])-value) <= max(1e-9, abs(value)*6e-6)
                if r[0] >= 8:
                    assert "热源关闭" in page.locator("#phase").inner_text()
            for selector, count in (("#series", c["rows"]+1),
                                    ("#nodes", c["rows"]*c["nodes"]+1)):
                with page.expect_download() as download:
                    page.locator(selector).click()
                assert len(Path(download.value.path()).read_text().splitlines()) == count
        page.locator("#time").focus()
        page.keyboard.press("Home")
        assert page.locator("#time").input_value() == "0"
        page.keyboard.press("End")
        assert page.locator("#time").input_value() == str(data["cases"][-1]["rows"]-1)
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
    ui = dict(passed=True, browser=version, combinations=9, page_errors=errors,
              external_requests=network, checks=["all endpoint/midpoint temperatures/powers/energy",
              "source off after pulse", "18 full CSV downloads", "node plot counts",
              "keyboard/play/pause", "390px", "four figures/PDF"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui, indent=2))
    print("p7-transient-ui: "+json.dumps(ui), flush=True)


if __name__ == "__main__":
    main()
