"""Offline nonlinear FEMM map, constitutive states, full exports and browser checks."""
import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-femm-nonlinear"
OUT = ROOT / "outputs/p7-femm-nonlinear-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    exports = []
    for path in sorted(SOURCE.rglob("*.csv"))+sorted(SOURCE.glob("grid*/flux-map.json")):
        # Detailed native point CSV remain in the raw archive; export complete aggregate series.
        if path.name not in {"bh.csv", "training.csv", "holdouts.csv", "increments.csv",
                             "angles.csv", "linear.csv", "flux-map.json"}:
            continue
        name = str(path.relative_to(SOURCE)).replace("\\", "-").replace("/", "-")
        shutil.copyfile(path, OUT / name)
        exports.append(dict(name=name, base64=base64.b64encode(path.read_bytes()).decode(),
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            rows=(len(path.read_text().splitlines())-1
                                  if path.suffix == ".csv" else None)))
    data["exports"] = exports
    data["report_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    figures = []
    bh = np.array(data["bh_table_si"])
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(bh[:, 0], bh[:, 1], "o-")
    ax.set(xlabel="B [T]", ylabel="H [A/m]", title="Synthetic BH nodes (not measured material)")
    ax.grid(alpha=.2)
    figures.append(("bh", fig))
    fine = data["grids"][1]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, key, label in zip(axes, ("lambda_d_wb", "lambda_q_wb"),
                               ("d flux [Wb]", "q flux [Wb]"), strict=True):
        a = np.array([r[key] for r in fine["training"]]).reshape(5, 5)
        im = ax.imshow(a, origin="lower", extent=[-40, 40, -40, 40], aspect="equal")
        ax.set(xlabel="iq [A]", ylabel="id [A]", title=label)
        fig.colorbar(im, ax=ax)
    figures.append(("flux-map", fig))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for g in data["grids"]:
        axes[0].plot(range(4), [r["prediction_error"]*100 for r in g["holdouts"]],
                     "o-", label="h="+str(g["mesh"]["h_mm"])+" mm")
        axes[1].scatter([r["dq_torque_nm"] for r in g["training"]],
                         [r["torque_nm"] for r in g["training"]], label="grid"+str(g["grid"]))
    axes[0].axhline(2, color="red", ls="--", label="frozen 2% gate")
    axes[0].set(xlabel="Unseen holdout", ylabel="Flux error / 0.026 Wb [%]")
    axes[1].set(xlabel="dq flux torque [Nm]", ylabel="Weighted stress torque [Nm]")
    for ax in axes:
        ax.legend(fontsize=7)
        ax.grid(alpha=.2)
    figures.append(("validation", fig))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for k, key in enumerate(("lambda_d_wb", "lambda_q_wb")):
        nl = [next(t for t in fine["training"] if t["id_a"] == r["id_a"]
                   and t["iq_a"] == r["iq_a"])[key] for r in fine["linear"]]
        axes[k].plot(range(5), nl, "o-", label="actual nonlinear FE")
        axes[k].plot(range(5), [r[key] for r in fine["linear"]], "s--", label="actual linear FE")
        axes[k].set(xlabel="Matched excitation", ylabel=key+" [Wb]")
        axes[k].legend(fontsize=7)
        axes[k].grid(alpha=.2)
    figures.append(("paired", fig))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, g in zip(axes, data["grids"], strict=True):
        m = np.array(g["incremental_matrices_h"][1])*1e6
        im = ax.imshow(m)
        for i in range(2):
            for j in range(2):
                ax.text(j, i, f"{m[i, j]:.5f}", ha="center", va="center", color="red")
        ax.set(title="Local differential L [uH], grid"+str(g["grid"]),
               xticks=[0, 1], xticklabels=["id", "iq"], yticks=[0, 1],
               yticklabels=["lambda d", "lambda q"])
        fig.colorbar(im, ax=ax)
    figures.append(("incremental", fig))
    with PdfPages(OUT / "figures.pdf") as pdf:
        for name, fig in figures:
            fig.tight_layout()
            fig.savefig(OUT / (name+".png"), dpi=150)
            fig.savefig(OUT / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    shutil.copyfile(ROOT / "docs/p7-femm-nonlinear-contract.md", OUT / "contract.md")
    shutil.copyfile(SOURCE / "validation.json", OUT / "validation.json")
    template = (ROOT / "reports/p7-femm-nonlinear.html").read_text(encoding="utf-8")
    encoded = json.dumps(data).replace("</", "<\\/")
    (OUT / "index.html").write_text(template.replace("__DATA__", encoded), encoding="utf-8")
    with sync_playwright() as p, TemporaryDirectory() as tmp:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(accept_downloads=True)
        errors, external = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: external.append(r.url)
                if r.url.startswith(("http:", "https:")) else None)
        page.goto((OUT / "index.html").as_uri())
        inspected = 0
        for gi, grid in enumerate(data["grids"]):
            page.select_option("#grid", str(gi))
            for mode in ("training", "holdouts", "increments", "angles", "linear"):
                if not grid[mode]:
                    continue
                page.select_option("#mode", mode)
                for i, row in enumerate(grid[mode]):
                    page.select_option("#state", str(i))
                    actual = page.evaluate("window.currentState")
                    for key in ("id_a", "iq_a", "angle_deg", "lambda_d_wb",
                                "lambda_q_wb", "torque_nm"):
                        assert actual[key] == row[key], (gi, mode, i, key)
                        element = page.locator('[data-value="'+key+'"]')
                        assert float(element.get_attribute("data-number")) == row[key]
                    assert page.locator(".coil").count() == 6
                    assert page.locator(".gapvector").count() == 36
                    assert page.locator(".statornode").count() == 12
                    inspected += 1
        page.select_option("#mode", "training")
        page.locator("#state").focus()
        page.keyboard.press("Home")
        assert page.locator("#state").input_value() == "0"
        page.keyboard.press("End")
        assert page.locator("#state").input_value() == "24"
        for item in exports:
            with page.expect_download() as event:
                page.locator('a[data-export="'+item["name"]+'"]').click()
            download = event.value
            path = Path(tmp) / item["name"]
            download.save_as(path)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
            if item["rows"] is not None:
                assert len(path.read_text().splitlines())-1 == item["rows"]
        assert page.locator("figure img").count() == 5
        assert page.evaluate("Array.from(document.querySelectorAll('figure img'))"
                             ".every(i=>i.complete && i.naturalWidth>0)")
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        result = dict(passed=not errors and not external, browser=browser.version,
                      states_checked=inspected, exact_downloads=len(exports),
                      page_errors=errors, external_requests=external,
                      checks=["2 grids", "all 82 states", "signed numeric values",
                              "6 coils / 36 gap vectors / 12 stator nodes",
                              "exact CSV/JSON downloads", "keyboard Home/End",
                              "390px", "five figures"])
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(result, indent=2))
    print("p7-nonlinear-ui: "+json.dumps(result), flush=True)
    assert result["passed"]


if __name__ == "__main__":
    main()
