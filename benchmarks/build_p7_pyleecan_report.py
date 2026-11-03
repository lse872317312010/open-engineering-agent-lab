"""Offline slotted public-machine figures and actual browser/data validation."""
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
from matplotlib.patches import Circle, Polygon
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-pyleecan"
OUT = ROOT / "outputs/p7-pyleecan-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    geo = json.loads((SOURCE / "geometry.json").read_text())
    model_path = ROOT / "benchmarks/assets/pyleecan-spmsm001.json"
    model = json.loads(model_path.read_text())
    data.update(geometry=geo, model=model, report_commit=subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip())
    if (SOURCE / "report-reuse.json").exists():
        data["reuse"] = json.loads((SOURCE / "report-reuse.json").read_text())
    cases = data["cases"]
    columns = ["grid", "sign", "relative_angle_deg", "actual_angle_deg", "origin_deg",
               "length_m", "native_depth_m", "ia_a", "ib_a", "ic_a",
               "lambda_a_wb", "lambda_b_wb", "lambda_c_wb", "torque_nm", "gap_torque_nm",
               "library_torque_nm", "nodes", "elements", "max_area_relative",
               "phi_unit_error", "torque_unit_error_nm"]
    rows = [[r["grid"], r["sign"], r["angle_deg"], np.rad2deg(r["actual_angle_rad"]),
             np.rad2deg(r["angle_origin_rad"]), r["length_m"], r["native_depth_m"],
             *r["currents_a"], *r["flux_wb"], r["torque_nm"], r["gap_torque_nm"],
             r["library_torque_nm"], r["nodes"], r["elements"], r["max_area_relative"],
             r["phi_unit_error"], r["torque_unit_error_nm"]] for r in cases]
    np.savetxt(OUT / "cases.csv", rows, delimiter=",", header=",".join(columns), comments="")
    for name in ("winding.csv", "bh.csv", "geometry.json", "validation.json"):
        shutil.copyfile(SOURCE / name, OUT / name)
    shutil.copyfile(model_path, OUT / "original-model.json")
    for name, source in (("NOTICE.md", "benchmarks/assets/pyleecan-spmsm001-NOTICE.md"),
                         ("contract.md", "docs/p7-pyleecan-contract.md")):
        shutil.copyfile(ROOT / source, OUT / name)
    for name in ("pyleecan", "scidatatool", "swat-em"):
        shutil.copyfile(SOURCE / (name+"-LICENSE.txt"), OUT / (name+"-LICENSE.txt"))
    for r in cases:
        shutil.copyfile(SOURCE / r["case"] / "gap.csv", OUT / ("gap-"+r["case"]+".csv"))
    figures = []
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    ax = axes[0]
    for radius, color in ((50, "#607589"), (27.85, "white"),
                          (23.85, "#7e91a2"), (11.925, "white")):
        ax.add_patch(Circle((0, 0), radius, color=color))
    for s in geo["surfaces"]:
        xy = np.array(s["points"])*1000
        if "phase" in s or "Mag" in s["label"]:
            color = ["#e7924b", "#4b9bd8", "#9b72db"][s["phase"]] if "phase" in s else "#67c6a2"
            ax.add_patch(Polygon(xy, facecolor=color, edgecolor="#20384b", lw=.25))
        else:
            ax.plot(xy[:, 0], xy[:, 1], color="#233e54", lw=.35)
    ax.set(xlim=(-53, 53), ylim=(-53, 53), aspect="equal", xlabel="x [mm]", ylabel="y [mm]",
           title="Actual PYLEECAN contours")
    w = np.genfromtxt(SOURCE / "winding.csv", delimiter=",", names=True)
    connection = np.zeros((24, 3))
    connection[np.arange(24), w["phase"].astype(int)] = w["turns"]
    im = axes[1].imshow(connection, aspect="auto", cmap="coolwarm", vmin=-34, vmax=34)
    axes[1].set(title="Actual SWAT winding", xlabel="phase / signed turns",
                ylabel="24 coil sides", xticks=[0, 1, 2], xticklabels=["A", "B", "C"])
    fig.colorbar(im, ax=axes[1])
    figures.append(("geometry-winding", fig))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3))
    bh = np.array(geo["bh"])
    axes[0].plot(bh[:, 1], bh[:, 0], "o-", ms=3)
    axes[0].set(xlabel="B [T]", ylabel="H [A/m]", title="Upstream reference BH table")
    for key in ("winding_m2", "magnets_m2", "stator_core_m2", "rotor_core_m2"):
        axes[1].plot(range(12), [abs(r["native_areas_m2"][key]/geo["reference"][key]-1)*100
                                  for r in cases], "o-", ms=3, label=key.replace("_m2", ""))
    axes[1].set(xlabel="Static case", ylabel="Area error [%]", title="Independent annular areas")
    axes[1].legend(fontsize=7)
    figures.append(("material-area", fig))
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    for k, label in enumerate(("open", "positive", "negative")):
        for phase in range(3):
            selected = cases[k:9:3]
            axes[k].plot([r["nodes"] for r in selected],
                         [r["flux_wb"][phase] for r in selected], "o-", label="ABC"[phase])
        axes[k].set(xlabel="Mesh nodes", ylabel="Physical linkage [Wb]", title=label)
        axes[k].legend()
    figures.append(("mesh-flux", fig))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
    for key, label, style in (("torque_nm", "weighted x stack", "o-"),
                              ("gap_torque_nm", "gap MST x stack", "s--"),
                              ("library_torque_nm", "PYLEECAN physical", "x")):
        axes[0].plot(range(12), [r[key] for r in cases], style, label=label)
    axes[0].set(xlabel="Static case", ylabel="Torque [Nm]", title="Physical torque routes")
    axes[0].legend(fontsize=7)
    for key, label in (("native_torque_nm", "FEMM 1m"), ("torque_nm", "physical stack")):
        axes[1].plot(range(12), [r[key] for r in cases], "o-", label=label)
    axes[1].set(xlabel="Static case", ylabel="Declared-depth torque [Nm]", title="Depth identity")
    axes[1].legend(fontsize=7)
    figures.append(("torque-depth", fig))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3))
    for phase in range(3):
        axes[0].plot(range(4), [cases[i]["flux_wb"][phase] for i in (6, 9, 10, 11)],
                     "o-", label="ABC"[phase])
    axes[0].set(xticks=range(4), xticklabels=["rel 0deg", "rel 45deg", "rel 90deg", "2x stack"],
                ylabel="Linkage [Wb]", title="Specified symmetry / axial limits")
    axes[0].legend()
    r = cases[6]
    axes[1].plot(np.rad2deg(r["phi_rad"]), np.array(r["field"])[:, 0], label="Br")
    axes[1].plot(np.rad2deg(r["phi_rad"]), np.array(r["field"])[:, 1], label="Bt")
    axes[1].set(xlabel="Spatial angle [deg]", ylabel="Field [T]", title="Actual sliding-band field")
    axes[1].legend()
    figures.append(("symmetry-gap", fig))
    with PdfPages(OUT / "figures.pdf") as pdf:
        for name, fig in figures:
            for ax in fig.axes:
                ax.grid(alpha=.15)
            fig.tight_layout()
            fig.savefig(OUT / (name+".png"), dpi=150)
            fig.savefig(OUT / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    exports = []
    for path in sorted(OUT.glob("*.csv"))+sorted(OUT.glob("*.json"))+[OUT / "figures.pdf"]:
        content = path.read_bytes()
        exports.append(dict(name=path.name, sha256=hashlib.sha256(content).hexdigest(),
                            base64=base64.b64encode(content).decode(),
                            rows=(len(path.read_text().splitlines())-1
                                  if path.suffix == ".csv" else None)))
    data["exports"] = exports
    template = (ROOT / "reports/p7-pyleecan.html").read_text(encoding="utf-8")
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
        for i, r in enumerate(cases):
            page.select_option("#grid", "all")
            page.select_option("#case", str(i))
            assert page.evaluate("window.currentCase.case") == r["case"]
            for key in ("torque_nm", "gap_torque_nm", "length_m", "native_depth_m",
                        "angle_deg", "actual_angle_rad"):
                element = page.locator('[data-value="'+key+'"]')
                assert float(element.get_attribute("data-number")) == r[key]
            for q in range(3):
                element = page.locator('[data-value="flux'+str(q)+'"]')
                assert float(element.get_attribute("data-number")) == r["flux_wb"][q]
            assert page.locator(".coil").count() == 24
            assert page.locator(".gapvector").count() == 48
            assert page.locator(".magnet").count() == 8
        coil = page.locator(".coil").first
        coil.click()
        assert "NI " in page.locator("#component").inner_text()
        coil.focus()
        page.keyboard.press("Enter")
        assert "匝数" in page.locator("#component").inner_text()
        page.keyboard.press("Space")
        assert "电流" in page.locator("#component").inner_text()
        for grid, expected in (("1", 3), ("1.5", 3), ("2", 6)):
            page.select_option("#grid", grid)
            assert page.locator("#case option").count() == expected
        page.select_option("#grid", "all")
        page.locator("#case").focus()
        page.keyboard.press("End")
        assert page.locator("#case").input_value() == "11"
        page.keyboard.press("Home")
        assert page.locator("#case").input_value() == "0"
        for item in exports:
            print("p7-pyleecan-download: "+item["name"], flush=True)
            with page.expect_download() as event:
                page.locator('a[data-export="'+item["name"]+'"]').click()
            path = Path(tmp) / item["name"]
            event.value.save_as(path)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
            if item["rows"] is not None:
                assert len(path.read_text().splitlines())-1 == item["rows"]
        assert page.locator("figure img").count() == 5
        assert page.evaluate("Array.from(document.querySelectorAll('figure img'))"
                             ".every(i=>i.complete && i.naturalWidth>0)")
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        overflow = page.evaluate("""Array.from(document.querySelectorAll('main *'))
            .filter(e=>e.getBoundingClientRect().right>innerWidth+1)
            .map(e=>({id:e.id,tag:e.tagName,text:e.textContent.slice(0,80)}))""")
        print("p7-pyleecan-overflow: "+json.dumps(overflow), flush=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        result = dict(passed=not errors and not external, browser=browser.version,
                      states_checked=12, exact_downloads=len(exports),
                      errors=errors, external_requests=external,
                      report_commit=data["report_commit"],
                      checks=["24 winding / 8 magnet regions", "48 gap vectors", "numeric states",
                              "mesh filtering", "exact CSV/JSON/PDF", "keyboard",
                              "390px", "five figures"])
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(result, indent=2))
    print("p7-pyleecan-ui: "+json.dumps(result), flush=True)
    assert result["passed"]


if __name__ == "__main__":
    main()
