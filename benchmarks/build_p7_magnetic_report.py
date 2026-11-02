"""Magnetic fields, parameter extraction, convergence and an offline component-state UI."""
import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-magnetic"
OUT = ROOT / "outputs/p7-magnetic-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    fields, parameter_files = {}, {}
    for c in data["cases"]:
        rel = c["id"]+f"/n{c['n']}"
        arrays = np.load(SOURCE / rel / "field.npz")
        parameter_files[rel] = (SOURCE / rel / "parameters.json").read_text()
        fields[rel] = {k:arrays[k].tolist() for k in arrays.files}
        shutil.copytree(SOURCE / rel, OUT / rel, dirs_exist_ok=True)
    figures = []
    f = fields["contrast/n32"]
    points = np.array(f["points"])
    triangulation = mtri.Triangulation(points[:, 0], points[:, 1], f["triangles"])
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    image = axes[0].tripcolor(triangulation, f["az"], shading="gouraud", cmap="coolwarm")
    fig.colorbar(image, ax=axes[0], label="Az (Wb/m)")
    image = axes[1].tripcolor(triangulation, facecolors=np.array(f["b"])[:, 1], cmap="coolwarm")
    fig.colorbar(image, ax=axes[1], label="By (T)")
    for ax in axes:
        ax.axvline(.04, linestyle="--", color="black", linewidth=.8)
        ax.set(xlabel="x (m)", ylabel="y (m)", aspect="equal")
    figures.append(("01-fields", fig))
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), layout="constrained")
    for case in ("air", "contrast", "reverse", "double"):
        rows = [c for c in data["cases"] if c["id"] == case]
        for ax, key in zip(axes, ("az_l2_relative", "b_l2_relative",
                                  "inductance_relative_error"), strict=True):
            ax.loglog([1/c["n"] for c in rows], [c[key] for c in rows], "o-", label=case)
            ax.set(xlabel="1 / intervals per region", ylabel=key)
            ax.legend(fontsize=7)
    figures.append(("02-convergence", fig))
    fine = [c for c in data["cases"] if c["n"] == 32]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), layout="constrained")
    for ax, key, label, factor in (
        (axes[0], "linkage_wb", "Signed flux linkage (nWb)", 1e9),
        (axes[1], "energy_j", "Magnetic stored energy (nJ)", 1e9),
        (axes[2], "inductance_h", "Circuit inductance (nH)", 1e9)):
        ax.bar([c["id"] for c in fine], [c[key]*factor for c in fine])
        ax.set_ylabel(label)
    axes[2].plot(range(4), [c["analytic_inductance_h"]*1e9 for c in fine],
                 "rx", label="Independent analytic L")
    axes[2].legend(fontsize=7)
    figures.append(("03-scaling", fig))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for n in (8, 32):
        a = np.genfromtxt(SOURCE / f"contrast/n{n}/interface.csv", delimiter=",", names=True)
        axes[0].plot(a["y_m"], a["left_hy_a_per_m"], label=f"left n{n}")
        axes[0].plot(a["y_m"], a["right_hy_a_per_m"], "--", label=f"right n{n}")
    axes[0].axhline(10., color="black", linestyle=":", label="Analytic H")
    axes[0].set(xlabel="Interface y (m)", ylabel="Tangential Hy (A/m)")
    rows = [c for c in data["cases"] if c["id"] == "contrast"]
    axes[1].loglog([1/c["n"] for c in rows],
                   [c["interface_h_error_relative"] for c in rows], "o-",
                   label="Direct P1 trace relative error")
    axes[1].set(xlabel="1 / intervals per region", ylabel="Relative interface H error")
    for ax in axes:
        ax.legend(fontsize=7)
    figures.append(("04-interface", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    for name in ("validation.json", "contract.md"):
        shutil.copyfile(SOURCE / name, OUT / name)
    for name in ("gmsh-4.13.1", "scikit-fem-11.0.0", "meshio-5.3.5"):
        shutil.copyfile(ROOT / f"research/licenses/{name}.txt", OUT / (name+"-LICENSE.txt"))
    template = (ROOT / "reports/p7-magnetic.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__", json.dumps(data))
                                   .replace("__FIELDS__", json.dumps(fields))
                                   .replace("__PARAMETERS__", json.dumps(parameter_files)))
    (OUT / "README.txt").write_text(
        "解压打开index.html。实际Gmsh/scikit-fem磁静态基准，12工况/网格与完整场。\n"
        "可选Az/By/Hy着色、节点/单元状态、三类CSV、VTU/NPZ/电感JSON和四图PDF。\n"
        "有限矩形单匝去回流、线性合成材料；不是PMSM、Ld/Lq或真实器件验证。\n")
    errors, network = [], []
    downloads = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda e:errors.append(str(e)))
        page.on("request", lambda r:network.append(r.url)
                if r.url.startswith(("http://", "https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert not errors, errors
        assert page.locator("#results tbody tr").count() == 12
        assert page.locator("#mesh-comparison tbody tr").count() == 12
        assert "失败" in page.locator("#mesh-comparison").inner_text()
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for c in data["cases"]:
            page.select_option("#case", c["id"])
            page.select_option("#mesh", str(c["n"]))
            f = fields[c["id"]+f"/n{c['n']}"]
            assert page.locator("#polygons polygon").count() == c["triangles"]
            for quantity in ("az", "by", "hy"):
                page.select_option("#quantity", quantity)
                assert quantity in page.locator("#legend").inner_text()
            for node, cell in ((0, 0), (c["nodes"]//2, c["triangles"]//2),
                               (c["nodes"]-1, c["triangles"]-1)):
                for selector, value in (("#node", node), ("#cell", cell)):
                    page.locator(selector).evaluate(
                        "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'));}", value)
                expected = {"az":f["az"][node], "exact":f["exact_az"][node],
                            "error":f["az"][node]-f["exact_az"][node],
                            "by":f["b"][cell][1], "hy":f["h"][cell][1],
                            "jz":f["current_density"][cell], "cell-energy":f["energy_j"][cell],
                            "energy":c["energy_j"], "linkage":c["linkage_wb"],
                            "inductance":c["inductance_h"], "analytic-l":c["analytic_inductance_h"]}
                for selector, value in expected.items():
                    actual = float(page.locator("#"+selector).inner_text().split()[0])
                    assert abs(actual-value) <= max(1e-24, abs(value)*6e-6), (selector, value)
            for kind, count in (("nodes", c["nodes"]+1), ("cells", c["triangles"]+1),
                                 ("interface", c["n"]+1)):
                with page.expect_download() as download:
                    page.locator("#download-"+kind).click()
                assert len(Path(download.value.path()).read_text().splitlines()) == count
                downloads += 1
            with page.expect_download() as download:
                page.locator("#download-parameters").click()
            text = Path(download.value.path()).read_text()
            assert text == parameter_files[c["id"]+"/n"+str(c["n"])]
            parameters = json.loads(text)
            assert parameters["inductance_h"] == c["inductance_h"]
            assert parameters["quantity"] == "bounded_single_turn_return_pair_inductance"
            assert "not a PMSM" in parameters["scope"]
        page.locator("#node").focus()
        page.keyboard.press("Home")
        assert page.locator("#node-id").inner_text() == "0"
        page.keyboard.press("End")
        assert int(page.locator("#node-id").inner_text()) == data["cases"][-1]["nodes"]-1
        page.screenshot(path=str(OUT / "ui-desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"), full_page=True)
        version = browser.version
        browser.close()
    assert not errors and not network, (errors, network)
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    ui = dict(passed=True, browser=version, csv_downloads=downloads, parameter_downloads=12,
              page_errors=errors, external_requests=network,
              checks=["12 cases/meshes", "real polygons", "Az/By/Hy and signed state values",
                      "node/cell endpoints/interior", "full CSV/parameter downloads",
                      "keyboard", "390px", "four figures/PDF", "scope visible"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui, indent=2))
    print("p7-magnetic-ui: "+json.dumps(ui), flush=True)


if __name__ == "__main__":
    main()
