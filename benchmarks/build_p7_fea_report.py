"""Export three-mesh field, error, convergence and heat figures with an offline UI."""
import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-fea-baseline"
OUT = ROOT / "outputs/p7-fea-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    fields = {}
    for c in data["cases"]:
        arrays = np.load(SOURCE / f"n{c['n']}/field.npz")
        fields[str(c["n"])] = {k:arrays[k].tolist() for k in arrays.files}
        shutil.copytree(SOURCE / f"n{c['n']}", OUT / f"n{c['n']}", dirs_exist_ok=True)
    figures = []
    fig, axes = plt.subplots(1,3,figsize=(13,4), layout="constrained")
    for ax,c in zip(axes,data["cases"],strict=True):
        f = fields[str(c["n"])]
        points = np.array(f["points"])
        tri = mtri.Triangulation(points[:,0],points[:,1],f["triangles"])
        image = ax.tripcolor(tri,f["temperature_c"],shading="gouraud",vmin=25,vmax=35)
        ax.triplot(tri,linewidth=.1,color="black")
        ax.set(title=f"{c['n']} intervals",xlabel="x (m)",ylabel="y (m)",aspect="equal")
    fig.colorbar(image,ax=axes,label="Temperature (degC)")
    figures.append(("01-fields",fig))
    fig, axes = plt.subplots(1,3,figsize=(13,4),layout="constrained")
    for ax,c in zip(axes,data["cases"],strict=True):
        f = fields[str(c["n"])]
        points = np.array(f["points"])
        tri = mtri.Triangulation(points[:,0],points[:,1],f["triangles"])
        image = ax.tripcolor(tri,np.array(f["temperature_c"])-f["exact_c"],shading="gouraud")
        ax.set(title=f"{c['n']} intervals",xlabel="x (m)",ylabel="y (m)",aspect="equal")
        fig.colorbar(image,ax=ax,label="Node temperature error (K)")
    figures.append(("02-errors",fig))
    fig, ax = plt.subplots(figsize=(8,5))
    h = [1/c["n"] for c in data["cases"]]
    ax.loglog(h,[c["l2_relative"] for c in data["cases"]],"o-",label="Relative L2")
    ax.loglog(h,[c["h1_relative"] for c in data["cases"]],"s-",label="Relative H1 seminorm")
    ax.set(xlabel="Normalized mesh spacing h/L",ylabel="Relative field error")
    ax.legend()
    figures.append(("03-convergence",fig))
    fig, ax = plt.subplots(figsize=(9,5))
    x = np.arange(3)
    for offset,key,label in [(-.25,"source_w","Integrated source"),
                             (0.,"reaction_w","Dirichlet reaction"),
                             (.25,"direct_boundary_flux_w","Direct gradient flux")]:
        ax.bar(x+offset,[c[key] for c in data["cases"]],.25,label=label)
    ax.axhline(1.6,color="red",linestyle="--",label="Analytic total 1.6 W")
    ax.set_xticks(x,[c["n"] for c in data["cases"]])
    ax.set(xlabel="Intervals per edge",ylabel="Thermal power (W)")
    ax.legend(fontsize=8)
    figures.append(("04-energy",fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name,fig in figures:
            fig.savefig(plots / (name+".png"),dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    shutil.copyfile(SOURCE / "validation.json",OUT / "validation.json")
    shutil.copyfile(ROOT / "docs/p7-fea-baseline-contract.md",OUT / "contract.md")
    for name in ("gmsh-4.13.1","scikit-fem-11.0.0","meshio-5.3.5"):
        shutil.copyfile(ROOT / f"research/licenses/{name}.txt",OUT / (name+"-LICENSE.txt"))
    template = (ROOT / "reports/p7-fea-baseline.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__",json.dumps(data))
                                   .replace("__FIELDS__",json.dumps(fields)))
    (OUT / "README.txt").write_text(
        "解压打开index.html。真实Gmsh网格和scikit-fem稳态制造解基准。\n"
        "三档网格/场/误差/收敛/热量、MSH/VTU/CSV/PDF；不是实物验证或完整P7。\n")
    errors,network = [],[]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440,height=1000),accept_downloads=True)
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.on("request",lambda r:network.append(r.url)
                if r.url.startswith(("http://","https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#mesh option").count() == 3
        assert page.locator("#results tbody tr").count() == 3
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for c in data["cases"]:
            page.select_option("#mesh",str(c["n"]))
            assert page.locator("#field polygon").count() == c["triangles"]
            page.locator("#node").focus()
            page.keyboard.press("Home")
            assert page.locator("#node-id").inner_text() == "0"
            page.keyboard.press("End")
            assert int(page.locator("#node-id").inner_text()) == c["nodes"]-1
            assert page.locator("#node-state .card").count() == 4
            field = fields[str(c["n"])]
            for node in (0,c["nodes"]-1):
                page.locator("#node").evaluate(
                    "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'));}", node)
                expected = [field["temperature_c"][node],field["exact_c"][node],
                            field["temperature_c"][node]-field["exact_c"][node]]
                actual = page.locator("#node-state .card b").all_text_contents()[1:]
                for text,value in zip(actual,expected,strict=True):
                    displayed = float(text.split()[0])
                    assert abs(displayed-value) <= max(1e-7,abs(value)*6e-5)
            for selector,key in (("#source","source_w"),("#reaction","reaction_w"),
                                 ("#flux","direct_boundary_flux_w")):
                displayed = float(page.locator(selector).text_content().split()[0])
                assert abs(displayed-c[key]) <= max(1e-7,abs(c[key])*6e-5)
            with page.expect_download() as download:
                page.locator("#csv").click()
            assert len(Path(download.value.path()).read_text().splitlines()) == c["nodes"]+1
        page.screenshot(path=str(OUT / "ui-desktop.png"),full_page=True)
        page.set_viewport_size(dict(width=390,height=844))
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"),full_page=True)
        version = browser.version
        browser.close()
    assert not errors and not network, (errors,network)
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    report = dict(passed=True,browser=version,page_errors=errors,external_requests=network,
                  checks=["three meshes","actual polygons","node endpoints","full CSV downloads",
                          "numeric node and heat states","390px","four figures/PDF","scope visible"])
    (OUT / "ui-validation.json").write_text(json.dumps(report,indent=2))
    print("p7-fea-ui: "+json.dumps(report),flush=True)


if __name__ == "__main__":
    main()
