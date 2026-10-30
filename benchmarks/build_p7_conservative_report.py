"""Offline comparison of original P1 and conservative RT0 fluxes."""
import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-conservative"
OUT = ROOT / "outputs/p7-conservative-report"


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    names = list(data["convergence"])
    fields = {}
    for c in data["cases"]:
        folder = SOURCE / c["id"] / f"n{c['n']}"
        arrays = np.load(folder / "field.npz")
        fields[c["id"]+"-"+str(c["n"])] = {
            k:arrays[k].tolist() for k in ("points","triangles","cells")}
        shutil.copytree(folder,OUT / c["id"] / f"n{c['n']}",dirs_exist_ok=True)
    figures = []
    fig,axes = plt.subplots(1,3,figsize=(13,4),layout="constrained")
    for ax,name in zip(axes,names,strict=True):
        group = [c for c in data["cases"] if c["id"] == name]
        for key,label in (("p1_interface_rms_relative","Worse original one-sided gradient"),
                          ("interface_rms_relative","Conservative RT0")):
            ax.semilogy([c["n"] for c in group],
                        [max(c[key],1e-15) for c in group],"o-",label=label)
        ax.set(title=name,xlabel="Intervals per layer",ylabel="Local interface relative RMS")
        ax.legend(fontsize=7)
    figures.append(("01-interface",fig))
    fig,axes = plt.subplots(1,3,figsize=(13,4),layout="constrained")
    for ax,name in zip(axes,names,strict=True):
        group = [c for c in data["cases"] if c["id"] == name]
        for key,label in (("p1_flux_l2_relative","Original P1 gradient"),
                          ("rt_flux_l2_relative","Conservative RT0")):
            ax.loglog([1/c["n"] for c in group],[c[key] for c in group],"o-",label=label)
        ax.set(title=name,xlabel="1 / intervals per layer",ylabel="Full flux relative L2")
        ax.legend(fontsize=7)
    figures.append(("02-global",fig))
    fig,axes = plt.subplots(1,3,figsize=(13,4),layout="constrained")
    for ax,name in zip(axes,names,strict=True):
        f = fields[name+"-32"]
        p = np.asarray(f["points"])
        cells = np.asarray(f["cells"])
        tri = mtri.Triangulation(p[:,0],p[:,1],f["triangles"])
        image = ax.tripcolor(tri,facecolors=cells[:,3],shading="flat")
        ax.set(title=name,xlabel="x (m)",ylabel="y (m)",aspect="equal")
        fig.colorbar(image,ax=ax,label="Cell-mean RT0 qx (W/m2)")
    figures.append(("03-field",fig))
    fig,axes = plt.subplots(1,2,figsize=(12,4),layout="constrained")
    for name in names:
        group = [c for c in data["cases"] if c["id"] == name]
        for ax,key in zip(axes,("cell_balance_over_scale","normal_jump_w_m2"),strict=True):
            ax.semilogy([c["n"] for c in group],
                        [max(c[key],1e-18) for c in group],"o-",label=name)
    axes[0].set(xlabel="Intervals per layer",ylabel="Max independent cell balance / scale")
    axes[1].set(xlabel="Intervals per layer",ylabel="Max interior normal jump (W/m2)")
    for ax in axes:
        ax.set_title("Display floor 1e-18; accuracy is checked separately")
        ax.legend(fontsize=7)
    figures.append(("04-balance",fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name,fig in figures:
            fig.savefig(plots / (name+".png"),dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    shutil.copyfile(SOURCE / "validation.json",OUT / "validation.json")
    shutil.copyfile(ROOT / "docs/p7-conservative-contract.md",OUT / "contract.md")
    shutil.copytree(SOURCE / "zero-source",OUT / "zero-source",dirs_exist_ok=True)
    for name in ("gmsh-4.13.1","scikit-fem-11.0.0","meshio-5.3.5"):
        shutil.copyfile(ROOT / f"research/licenses/{name}.txt",OUT / (name+"-LICENSE.txt"))
    template = (ROOT / "reports/p7-conservative.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__",json.dumps(data))
                                   .replace("__FIELDS__",json.dumps(fields)))
    (OUT / "README.txt").write_text(
        "解压打开index.html。原P1温度不变，RT0守恒通量后处理与独立解析评价。\n"
        "九组合、四图PDF/PNG/SVG、全部cell/facet/interface CSV、通量VTU和DOF数组。\n"
        "界面RMS使用局部解析幅值；法向连续不单独证明准确度。不是新温度模型。\n")
    errors,network = [],[]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440,height=1000),accept_downloads=True)
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.on("request",lambda r:network.append(r.url)
                if r.url.startswith(("http://","https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#results tbody tr").count() == 9
        assert page.locator("#tradeoff").is_visible()
        worse = sum(c["rt_flux_l2_relative"] > c["p1_flux_l2_relative"] for c in data["cases"])
        assert int(page.locator("#tradeoff").get_attribute("data-worse")) == worse
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for c in data["cases"]:
            page.select_option("#case",c["id"])
            page.select_option("#mesh",str(c["n"]))
            assert page.locator("#field polygon").count() == c["triangles"]
            values = page.locator("#power .card b").all_text_contents()
            keys = ("source_w","left_out_w","right_out_w",
                    "rt_interface_right_w","exact_interface_right_w")
            for text,key in zip(values[:5],keys,strict=True):
                assert abs(float(text.split()[0])-c[key]) <= max(1e-9,abs(c[key])*6e-6)
            assert values[5] == "未改变"
            if c["id"] == "hot-ambient":
                assert float(values[2].split()[0]) < 0
            f = fields[c["id"]+"-"+str(c["n"])]
            for cell in (0,c["triangles"]-1,int(np.argmax(np.array(f["cells"])[:,3]))):
                page.locator("#cell").evaluate(
                    "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'));}",cell)
                values = page.locator("#state .card b").all_text_contents()
                expected = [f["cells"][cell][i] for i in (5,3,4,6,7,9)]
                for text,value in zip(values,expected,strict=True):
                    assert abs(float(text.split()[0])-value) <= max(1e-9,abs(value)*6e-6)
            for selector,rows in (("#cells",c["triangles"]+1),("#facets",c["facets"]+1),
                                  ("#interface",c["n"]+1)):
                with page.expect_download() as download:
                    page.locator(selector).click()
                assert len(Path(download.value.path()).read_text().splitlines()) == rows
        page.locator("#cell").focus()
        page.keyboard.press("Home")
        assert page.locator("#now").inner_text() == "0"
        page.keyboard.press("End")
        assert int(page.locator("#now").inner_text()) == data["cases"][-1]["triangles"]-1
        page.screenshot(path=str(OUT / "ui-desktop.png"),full_page=True)
        page.set_viewport_size(dict(width=390,height=844))
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"),full_page=True)
        version = browser.version
        browser.close()
    assert not errors and not network, (errors,network)
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    ui = dict(passed=True,browser=version,page_errors=errors,external_requests=network,
              combinations=9,
              checks=["numeric powers","unchanged P1 source","cell flux/source/balance",
                                     "negative ambient flow","all cell/facet/interface CSVs",
                                     "keyboard endpoints","390px","four figures/PDF",
                                     "global error tradeoff visible"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui,indent=2))
    print("p7-conservative-ui: "+json.dumps(ui),flush=True)


if __name__ == "__main__":
    main()
