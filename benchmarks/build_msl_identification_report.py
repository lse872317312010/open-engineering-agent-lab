"""Five identification figures, full prediction CSVs and offline six-node state UI."""
import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from msl_identification_protocol import NODES, physical_vector
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/msl-identification"
OUT = ROOT / "outputs/msl-identification-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    fit, truth, ideal = [physical_vector(data[k]) for k in ("fit", "truth", "ideal_fit")]
    nominal = np.array([60,70,200,.5,25,100,.6,.4,2,.8,1.2,2.])
    figures = []
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, section, labels in [
        (axes[0], slice(0,6), ["winding","core","case","junction","board","sink"]),
        (axes[1], slice(6,12),
         ["w-core","core-case","case-board","j-board","board-sink","case-air"]),
    ]:
        x = np.arange(6)
        for offset, values, name in [(-.27,truth,"Synthetic truth"),(-.09,nominal,"Nominal"),
                                    (.09,ideal,"Ideal-data reference"),(.27,fit,"Noisy-train fit")]:
            ax.bar(x+offset, values[section], .18, label=name)
        ax.set_xticks(x, labels, rotation=25)
        ax.legend(fontsize=7)
    axes[0].set(yscale="log", ylabel="Capacity (J/K)", title="Six capacities; full observation")
    axes[1].set(ylabel="Resistance (K/W)", title="Five links and case-to-ambient")
    figures.append(("01-parameters", fig))
    train = np.genfromtxt(SOURCE / "train/trajectory.csv", delimiter=",", names=True)
    noisy = np.genfromtxt(SOURCE / "train/measurements.csv", delimiter=",", names=True)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, group in zip(axes, (NODES[:3], NODES[3:]), strict=True):
        for n in group:
            line = ax.plot(train["time_s"], train[n+"_c"], label=n)[0]
            ax.scatter(noisy["time_s"][::20], noisy[n+"_c"][::20], s=2, alpha=.25,
                       color=line.get_color())
        ax.set(xlabel="Time (s)", ylabel="Temperature (degC)")
        ax.legend(fontsize=8)
    fig.suptitle("Training only: actual MSL and sampled 0.02 K Gaussian measurement noise")
    figures.append(("02-training", fig))
    traces = {c["id"]:np.genfromtxt(SOURCE / ("prediction-"+c["id"]) / "prediction.csv",
                                    delimiter=",", names=True) for c in data["evaluated"]}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, case in zip(axes, data["evaluated"], strict=True):
        row = traces[case["id"]]
        for n in ("winding","junction","sink"):
            line = ax.plot(row["time_s"], row[n+"_c"], label=n+" fitted FMU")[0]
            ax.plot(row["time_s"], row["truth_"+n+"_c"], linestyle="--",
                    color=line.get_color(), alpha=.6, label=n+" synthetic truth")
        ax.set(xlabel="Time (s)", ylabel="Temperature (degC)",
               title=case["id"]+"; unused by fitting")
        ax.legend(fontsize=7)
    figures.append(("03-predictions", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, case in zip(axes, data["evaluated"], strict=True):
        row = traces[case["id"]]
        errors = np.column_stack([row[n+"_c"]-row["truth_"+n+"_c"] for n in NODES])
        before = np.column_stack([row["nominal_"+n+"_c"]-row["truth_"+n+"_c"] for n in NODES])
        ax.plot(row["time_s"], np.maximum(np.max(abs(before), axis=1), 1e-6), label="Nominal")
        ax.plot(row["time_s"], np.maximum(np.max(abs(errors), axis=1), 1e-6), label="Fitted")
        ax.set(xlabel="Time (s)", ylabel="Max node absolute error (K)", yscale="log",
               title=case["id"]+"; display floor 1e-6 K")
        ax.legend()
    figures.append(("04-errors", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].semilogy(np.arange(1,13), data["fit"]["singular_values"], "o-")
    axes[0].set(xlabel="Normalized singular value index", ylabel="Singular value",
                title="Rank "+str(data["fit"]["normalized_rank"])+"/12; fixed windows")
    for case in data["evaluated"]:
        row = traces[case["id"]]
        axes[1].plot(row["time_s"], row["balance_j"], label=case["id"])
    axes[1].axhline(1e-5, color="red", linestyle="--")
    axes[1].axhline(-1e-5, color="red", linestyle="--")
    axes[1].set(xlabel="Time (s)", ylabel="Stored + ambient - input (J)")
    axes[1].legend()
    figures.append(("05-diagnostics", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.tight_layout()
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    for case in data["evaluated"]:
        shutil.copyfile(SOURCE / ("prediction-"+case["id"]) / "prediction.csv",
                        OUT / (case["id"]+".csv"))
    for source, target in [
        (SOURCE / "train/measurements.csv", "training-measurements.csv"),
        (SOURCE / "fitted.json", "fitted.json"),
        (SOURCE / "validation.json", "report-data.json"),
        (ROOT / "outputs/msl-parametric/OEALMSLParametric.fmu", "OEALMSLParametric.fmu"),
        (ROOT / "docs/msl-identification-contract.md", "contract.md"),
        (ROOT / "research/licenses/MSL-4.0.0.txt", "MSL-BSD3.txt"),
        (ROOT / "research/licenses/SciPy-1.15.3.txt", "SciPy-LICENSE.txt"),
        (ROOT / "LICENSE", "LICENSE"),
    ]:
        shutil.copyfile(source, OUT / target)
    (OUT / "index.html").write_text((ROOT / "reports/msl-identification.html").read_text()
                                   .replace("__DATA__", json.dumps(data)))
    (OUT / "README.txt").write_text(
        "解压打开index.html。六节点全观测/已知热源下的仿真内合成标定，不是实物标定。\n"
        "仅train参与拟合；验证/留出在参数冻结后评估。五图PDF/PNG/SVG、两组全预测CSV及训练测量。\n"
        "原始包另含所有RHS、三组数据、真值、设计矩阵、故障副本、环境和散列。\n")
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda e:errors.append(str(e)))
        page.on("request", lambda r:network.append(r.url)
                if r.url.startswith(("http://","https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#case option").count() == 2
        assert page.locator("#parameters tbody tr").count() == 12
        assert page.locator("#results tbody tr").count() == 2
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for case in data["evaluated"]:
            page.select_option("#case", case["id"])
            page.locator("#time").focus()
            page.keyboard.press("Home")
            assert page.locator("#now").inner_text().startswith("0.00 s")
            assert float(page.locator("#ambient").text_content().split()[1]) == (
                case["config"]["ambient_c"])
            for i, initial in enumerate(case["config"]["initial_c"]):
                assert abs(float(page.locator(f"#n{i}").text_content()[:-2])-initial) <= .00051
            page.keyboard.press("End")
            assert abs(float(page.locator("#now").inner_text().split()[0])
                       -case["config"]["duration_s"]) <= 1e-10
            assert page.locator("#states .card").count() == 9
            with page.expect_download() as download:
                page.locator("#csv").click()
            assert len(Path(download.value.path()).read_text().splitlines()) == case["rows"]+1
        page.locator("#play").click()
        assert page.locator("#play").get_attribute("aria-pressed") == "true"
        page.locator("#play").click()
        assert page.locator("#play").get_attribute("aria-pressed") == "false"
        page.screenshot(path=str(OUT / "ui-desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"), full_page=True)
        version = browser.version
        browser.close()
    assert not errors and not network, (errors, network)
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    ui = dict(passed=True, browser=version, charts=5, page_errors=errors,
              external_requests=network, checks=["12 parameters", "two unused cases",
                  "six node states", "actual ambient and initial states", "heat/energy status",
                  "keyboard endpoints", "full CSV downloads", "play/pause", "390px",
                  "PDF/PNG/SVG", "training-only assumption visible"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui, ensure_ascii=False, indent=2))
    print("identification-ui: "+json.dumps(ui), flush=True)


if __name__ == "__main__":
    main()
