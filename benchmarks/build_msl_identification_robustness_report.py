"""Four exported figures and offline twenty-case diagnostics with actual browser gates."""
import csv
import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/msl-identification-robustness"
OUT = ROOT / "outputs/msl-identification-robustness-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "evaluation.json").read_text())
    cases = data["cases"]
    names = [c["id"] for c in cases]
    successful = [c for c in cases if c["solver_succeeded"]]
    figures = []
    fig, ax = plt.subplots(figsize=(10, 4))
    for noise in (.02, .1, .5):
        group = [c for c in cases if c["kind"] == "noise" and c["noise_k"] == noise]
        assert len(group) == 4
        ax.scatter([noise]*4, [100*c["max_parameter_relative_error"] for c in group],
                   label=f"{noise:.2f} K; four fixed seeds")
    ax.axhline(10., color="red", linestyle="--", label="Synthetic suitability limit")
    ax.set(xscale="log", yscale="log", xlabel="IID temperature noise sigma (K)",
           ylabel="Maximum physical C/R relative error (%)")
    ax.legend(fontsize=8)
    figures.append(("01-noise", fig))
    fig, ax = plt.subplots(figsize=(13, 8))
    grid = np.full((20, 12), np.nan)
    for i, c in enumerate(cases):
        if c["solver_succeeded"]:
            grid[i] = np.log10(np.maximum(c["parameter_relative_errors"], 1e-8))
    image = ax.imshow(grid, aspect="auto", vmin=-5, vmax=1, cmap="magma")
    ax.set_yticks(range(20), names)
    ax.set_xticks(range(12), ["Cw","Cc","Ccase","Cj","Cb","Cs",
                             "Rw-c","Rc-case","Rcase-b","Rj-b","Rb-s","Rcase-a"],
                  rotation=30)
    ax.set(title="log10 physical parameter relative error; rejected fits blank")
    fig.colorbar(image, ax=ax, label="log10 relative error")
    figures.append(("02-parameters", fig))
    fig, axes = plt.subplots(1, 2, figsize=(13, 8))
    y = np.arange(len(successful))
    axes[0].barh(y, [max(c["rmse_by_node_k"]) for c in successful])
    axes[1].barh(y, [c["peak_error_k"] for c in successful])
    for ax, limit, title in zip(axes, (.5, 1.5), ("Max node RMSE (K)", "Global peak (K)"),
                               strict=True):
        ax.axvline(limit, color="red", linestyle="--")
        ax.set_yticks(y, [c["id"] for c in successful])
        ax.set(xlabel=title, xscale="symlog", xlim=(0, None))
    figures.append(("03-prediction", fig))
    fig, ax = plt.subplots(figsize=(11, 6))
    for c in successful:
        residual = max(c["fit"]["residual_rms_j_by_node"])
        value = max(c["rmse_by_node_k"])
        ax.scatter(residual, value, color="teal" if c["suitable"] else "darkorange")
        ax.annotate(c["id"], (residual, value), fontsize=6, xytext=(3,3),
                    textcoords="offset points")
    ax.axhline(.5, color="red", linestyle="--")
    ax.set(xscale="log", yscale="log", xlabel="Largest node training integral residual RMS (J)",
           ylabel="Largest node independent holdout RMSE (K)",
           title="Residual is a training diagnostic, not a substitute for unused-case validation")
    figures.append(("04-residual", fig))
    fig, ax = plt.subplots(figsize=(11, 6))
    for c in successful:
        q = c["quality"]
        if q["status"] in ("unknown", "invalid"):
            continue
        ratio = min(np.asarray(q["span_k"])/np.asarray(q["threshold_k"]))
        ax.scatter(ratio, max(c["rmse_by_node_k"]),
                   color="teal" if c["suitable"] else "darkorange")
        ax.annotate(c["id"], (ratio, max(c["rmse_by_node_k"])), fontsize=6)
    ax.axvline(1., color="red", linestyle="--")
    ax.axhline(.5, color="red", linestyle=":")
    ax.set(xscale="log", yscale="log", xlabel="Minimum node span / declared noise threshold",
           ylabel="Largest node holdout RMSE (K)",
           title="Amplitude support is not a certificate of prediction accuracy")
    figures.append(("05-quality", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.tight_layout()
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    shutil.copytree(SOURCE / "fits", OUT / "fits", dirs_exist_ok=True)
    for c in successful:
        shutil.copyfile(SOURCE / c["prediction_csv"], OUT / c["prediction_csv"])
    shutil.copyfile(SOURCE / "evaluation.json", OUT / "report-data.json")
    shutil.copyfile(ROOT / "docs/msl-identification-robustness-contract.md", OUT / "contract.md")
    with (OUT / "summary.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case","noise_k","seed","solver_succeeded","synthetic_suitable",
                         "max_parameter_relative_error","max_node_rmse_k","peak_k","error",
                         "observation_status","observation_noise_source"])
        for c in cases:
            writer.writerow([c["id"],c["noise_k"],c["seed"],c["solver_succeeded"],c["suitable"],
                             c.get("max_parameter_relative_error",""),
                             max(c.get("rmse_by_node_k",[]), default=""),
                             c.get("peak_error_k",""),c.get("error",""),
                             c["quality"]["status"],c["quality"].get("noise_source","")])
    template = ROOT / "reports/msl-identification-robustness.html"
    (OUT / "index.html").write_text(template.read_text().replace("__DATA__", json.dumps(data)))
    (OUT / "README.txt").write_text(
        "解压后打开 index.html。20组固定训练扰动，参数冻结后预测MSL留出真值。\n"
        "优化成功和合成适用性单独显示；适用性评价依赖合成真值，不是实测故障检测器。\n"
        "含五图PDF/PNG/SVG、逐组完整300秒CSV、拟合JSON、指标CSV与冻结契约。\n")
    shutil.copyfile(ROOT / "docs/msl-quality-report-contract.md", OUT / "quality-contract.md")
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda e:errors.append(str(e)))
        page.on("request", lambda r:network.append(r.url)
                if r.url.startswith(("http://","https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#case option").count() == 20
        assert page.locator("#results tbody tr").count() == 20
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for c in cases:
            page.select_option("#case", c["id"])
            assert page.locator("#fit").get_attribute("href") == "fits/"+c["id"]+".json"
            assert page.locator("#quality-status").get_attribute("data-status") == (
                c["quality"]["status"])
            expected_rows = 0 if c["quality"]["status"] == "invalid" else 6
            assert page.locator("#quality-table tbody tr").count() == expected_rows
            if not c["solver_succeeded"]:
                assert page.locator("#unavailable").is_visible()
                assert not page.locator("#runtime").is_visible()
                assert page.locator("#parameters tbody tr").count() == 0
                continue
            assert page.locator("#parameters tbody tr").count() == 12
            assert page.locator("#runtime").is_visible()
            page.locator("#time").focus()
            page.keyboard.press("Home")
            assert page.locator("#now").inner_text() == "0.00 s"
            for j in range(6):
                assert abs(float(page.locator(f"#n{j}").text_content()[:-2])-60.) < .00051
            page.keyboard.press("End")
            assert page.locator("#now").inner_text() == "300.00 s"
            assert page.locator("#states .card").count() == 20
            with page.expect_download() as download:
                page.locator("#csv").click()
            assert len(Path(download.value.path()).read_text().splitlines()) == 6002
        page.select_option("#case", "ideal")
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
    ui = dict(passed=True, browser=version, page_errors=errors, external_requests=network,
              case_count=20, chart_count=5, successful_predictions=len(successful),
              checks=["all cases", "rejection hides runtime", "12 parameters", "six temperatures",
                      "20 mechanism cards", "full CSV downloads", "time endpoints", "play/pause",
                      "390px without overflow", "five figures/PDF",
                      "training observation status and six spans", "synthetic scope visible"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui, indent=2))
    print("robustness-ui: "+json.dumps(ui), flush=True)


if __name__ == "__main__":
    main()
