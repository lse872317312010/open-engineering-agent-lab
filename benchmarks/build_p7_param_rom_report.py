"""Scientific ROM figures, physical replay and actual browser gates."""
import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-param-rom"
OUT = ROOT / "outputs/p7-param-rom-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    rows = {}
    for c in data["cases"]:
        folder = SOURCE / c["id"]
        rows[c["id"]] = np.loadtxt(folder / "timeseries.csv", delimiter=",", skiprows=1)
        shutil.copytree(folder, OUT / c["id"], dirs_exist_ok=True)
    shutil.copytree(SOURCE / "model", OUT / "model", dirs_exist_ok=True)
    rom = np.load(SOURCE / "model/rom.npz")
    figures = []
    fig, ax = plt.subplots(figsize=(8, 4), layout="constrained")
    ax.semilogy(np.arange(len(rom["singular_values"]))+1, rom["singular_values"], "o-")
    ax.set(xlabel="Retained training POD mode", ylabel="Mass-weighted singular value",
           title="Up to 20 POD modes + two regional energy test vectors")
    figures.append(("01-spectrum", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    for name in ("validation-r.03", "holdout-r.07", "above-range"):
        a = rows[name]
        axes[0].plot(a[:, 0], a[:, 5], label=name+" FOM right")
        axes[0].plot(a[:, 0], a[:, 6], "--", label=name+" parametric ROM")
        axes[0].plot(a[:, 0], a[:, 26], ":", label=name+" frozen Rc=.1 ROM")
        axes[1].plot(a[:, 0], a[:, 6]-a[:, 5], label=name)
    axes[0].set(xlabel="Time (s)", ylabel="Right material mean temperature (degC)")
    axes[1].set(xlabel="Time (s)", ylabel="ROM - FOM mean temperature (K)")
    for ax in axes:
        ax.legend(fontsize=7)
    figures.append(("02-trajectories", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    a = rows["holdout-r.07"]
    for col, label in ((17, "Input"), (11, "Left stored FOM"), (12, "Left stored ROM"),
                       (13, "Right stored FOM"), (14, "Right stored ROM")):
        axes[0].plot(a[:, 0], a[:, col], label=label)
    for c in data["cases"]:
        a = rows[c["id"]]
        axes[1].semilogy(a[:, 0], np.maximum(abs(a[:, 24]), 1e-18), label=c["id"])
    axes[0].set(xlabel="Time (s)", ylabel="Independent holdout energy (J)")
    axes[1].set(xlabel="Time (s)", ylabel="ROM own-model balance (J), floor 1e-18",
                title="Own-model conservation does not validate out-of-domain physics")
    for ax in axes:
        ax.legend(fontsize=7)
    figures.append(("03-energy", fig))
    fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
    for name in data["timing"]:
        samples = np.loadtxt(SOURCE / (name+"-latency.csv"), delimiter=",", skiprows=1)/1000
        ax.hist(samples, bins=50, alpha=.5, label=name)
        shutil.copyfile(SOURCE / (name+"-latency.csv"), OUT / (name+".csv"))
    ax.axvline(2500, linestyle="--", color="black", label="2.5 ms host p95 budget")
    ax.set(xlabel="Step elapsed (microseconds)", ylabel="Sample count", xscale="log")
    ax.legend(fontsize=7)
    figures.append(("04-latency", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    shutil.copyfile(SOURCE / "validation.json", OUT / "validation.json")
    shutil.copyfile(ROOT / "docs/p7-param-rom-contract.md", OUT / "contract.md")
    for name in ("pymor-2026.1.1-LICENSE.txt", "pymor-2026.1.1-LICENSES_bundled.txt",
                 "gmsh-4.13.1.txt", "scikit-fem-11.0.0.txt", "meshio-5.3.5.txt"):
        shutil.copyfile(ROOT / "research/licenses" / name, OUT / name)
    template = (ROOT / "reports/p7-param-rom.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__", json.dumps(data))
                                   .replace("__ROWS__", json.dumps({k:v.tolist()
                                                                   for k, v in rows.items()})))
    (OUT / "README.txt").write_text(
        "解压打开index.html。八案例验证/留出/域外身份、完整物理状态CSV及全场NPZ。\n"
        "全场NPZ保留所有节点和时刻，页面只嵌入物理状态。域外ROM仅为反事实。\n"
        "四图PDF/PNG/SVG、冻结模型/基底、性能逐样本CSV和许可。\n")
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: network.append(r.url)
                if r.url.startswith(("http://", "https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#results tbody tr").count() == 8
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for c in data["cases"]:
            page.select_option("#case", c["id"])
            for step in (0, 160, c["rows"]-1):
                page.locator("#time").evaluate(
                    "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'));}", step)
                r = rows[c["id"]][step]
                for selector, indices in (("#state b", ((3, 4), (5, 6), (15, 16), (25, 26))),
                                          ("#energy b", ((11, 12), (13, 14), (17, 18)))):
                    texts = page.locator(selector).all_text_contents()
                    for text, pair in zip(texts, indices, strict=True):
                        a, b = text.split(" / ")
                        for actual, expected in ((float(a), r[pair[0]]),
                                                 (float(b.split()[0]), r[pair[1]])):
                            assert abs(actual-expected) <= max(1e-9, abs(expected)*6e-6)
                assert page.locator("#guard").get_attribute("class") == (
                    "good" if c["supported"] else "bad")
            for selector, count in (("#series", c["rows"]+1), ("#nodes", c["nodes"]+1)):
                with page.expect_download() as download:
                    page.locator(selector).click()
                assert len(Path(download.value.path()).read_text().splitlines()) == count
            with page.expect_download() as download:
                page.locator("#fields").click()
            arrays = np.load(download.value.path())
            assert arrays["fom_temperature_c"].shape == (c["rows"], c["nodes"])
            assert arrays["rom_temperature_c"].shape == (c["rows"], c["nodes"])
            assert arrays["fixed_temperature_c"].shape == (c["rows"], c["nodes"])
        page.locator("#time").focus()
        page.keyboard.press("Home")
        assert page.locator("#time").input_value() == "0"
        page.keyboard.press("End")
        assert page.locator("#time").input_value() == "640"
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
    ui = dict(passed=True, browser=version, cases=8, page_errors=errors,
              external_requests=network, checks=["FOM/ROM state/energy/power numbers",
              "domain guard", "sixteen complete CSVs", "eight complete NPZs", "keyboard/play/pause",
              "390px", "four figures/PDF"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui, indent=2))
    print("p7-param-ui: "+json.dumps(ui), flush=True)


if __name__ == "__main__":
    main()
