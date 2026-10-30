"""Four-figure offline report for nine real layered FE combinations."""
import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from p7_layered_reference import CASES, L, temperature
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-layered"
OUT = ROOT / "outputs/p7-layered-report"


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    fields = {}
    for c in data["cases"]:
        folder = SOURCE / c["id"] / f"n{c['n']}"
        arrays = np.load(folder / "field.npz")
        fields[c["id"]+"-"+str(c["n"])] = {k:arrays[k].tolist() for k in arrays.files}
        shutil.copytree(folder,OUT / c["id"] / f"n{c['n']}",dirs_exist_ok=True)
    figures = []
    fig,axes = plt.subplots(1,3,figsize=(13,4),layout="constrained")
    for ax,case in zip(axes,CASES,strict=True):
        f = fields[case["id"]+"-32"]
        points = np.array(f["points"])
        tri = mtri.Triangulation(points[:,0],points[:,1],f["triangles"])
        image = ax.tripcolor(tri,f["temperature_c"],shading="gouraud")
        ax.axvline(.04,color="white",linestyle="--")
        ax.set(title=case["id"],xlabel="x (m)",ylabel="y (m)",aspect="equal")
        fig.colorbar(image,ax=ax,label="Temperature (degC)")
    figures.append(("01-fields",fig))
    fig,axes = plt.subplots(1,3,figsize=(13,4),layout="constrained")
    for ax,case in zip(axes,CASES,strict=True):
        x = np.linspace(0.,L,401)
        ax.plot(x,temperature(x,case),label="Analytic",color="black")
        for n in (8,16,32):
            f = fields[case["id"]+"-"+str(n)]
            points = np.array(f["points"])
            index = np.flatnonzero(abs(points[:,1]-.05) < 1e-10)
            index = index[np.argsort(points[index,0])]
            ax.plot(points[index,0],np.array(f["temperature_c"])[index],".-",
                    markersize=3,label=f"FE n={n}")
        ax.set(title=case["id"],xlabel="x (m)",ylabel="Centerline temperature (degC)")
        ax.legend(fontsize=7)
    figures.append(("02-profile",fig))
    fig,axes = plt.subplots(1,2,figsize=(12,4),layout="constrained")
    for case in CASES:
        group = [c for c in data["cases"] if c["id"] == case["id"]]
        for ax,key in zip(axes,("l2_relative","h1_relative"),strict=True):
            ax.loglog([1/c["n"] for c in group],[c[key] for c in group],"o-",label=case["id"])
            ax.set(xlabel="1 / intervals per layer",ylabel=key)
            ax.legend(fontsize=8)
    figures.append(("03-convergence",fig))
    fig,axes = plt.subplots(1,2,figsize=(12,4),layout="constrained")
    for case in CASES:
        group = [c for c in data["cases"] if c["id"] == case["id"]]
        axes[0].semilogy([c["n"] for c in group],
                         [max(c["balance_relative"],1e-17) for c in group],"o-",label=case["id"])
        axes[1].semilogy([c["n"] for c in group],
                         [c["flux_errors"]["interface_jump"] for c in group],"o-",
                         label=case["id"])
    axes[0].set(xlabel="Intervals per layer",ylabel="Reaction + Robin - source / scale",
                title="Display floor 1e-17; signed flows retained")
    axes[1].set(xlabel="Intervals per layer",ylabel="Direct interface flux jump / power scale")
    for ax in axes:
        ax.legend(fontsize=8)
    figures.append(("04-flux",fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name,fig in figures:
            fig.savefig(plots / (name+".png"),dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    shutil.copyfile(SOURCE / "validation.json",OUT / "validation.json")
    shutil.copyfile(ROOT / "docs/p7-layered-contract.md",OUT / "contract.md")
    shutil.copytree(SOURCE / "zero-source",OUT / "zero-source",dirs_exist_ok=True)
    for name in ("gmsh-4.13.1","scikit-fem-11.0.0","meshio-5.3.5"):
        shutil.copyfile(ROOT / f"research/licenses/{name}.txt",OUT / (name+"-LICENSE.txt"))
    template = (ROOT / "reports/p7-layered.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__",json.dumps(data))
                                   .replace("__FIELDS__",json.dumps(fields)))
    (OUT / "README.txt").write_text(
        "解压打开index.html。三场景×三网格，双材料/恒温/对流/绝热有限元与解析对照。\n"
        "含四图PDF/PNG/SVG、MSH/VTU、全部节点/界面CSV和零源patch。不是实物标定。\n")
    errors,network = [],[]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440,height=1000),accept_downloads=True)
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.on("request",lambda r:network.append(r.url)
                if r.url.startswith(("http://","https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#case option").count() == 3
        assert page.locator("#results tbody tr").count() == 9
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for c in data["cases"]:
            page.select_option("#case",c["id"])
            page.select_option("#mesh",str(c["n"]))
            assert page.locator("#field polygon").count() == c["triangles"]
            values = page.locator("#heat .card b").all_text_contents()
            expected = [c[k] for k in ("source_w","left_out_w","right_out_w",
                                       "interface_left_right_w","interface_right_right_w")]
            expected.append(c["expected"]["interface_right_w"])
            for text,value in zip(values,expected,strict=True):
                assert abs(float(text.split()[0])-value) <= max(1e-8,abs(value)*6e-6)
            if c["id"] == "hot-ambient":
                assert float(values[2].split()[0]) < 0
            f = fields[c["id"]+"-"+str(c["n"])]
            for node in (0,c["nodes"]-1,int(np.argmax(f["temperature_c"]))):
                page.locator("#node").evaluate(
                    "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'));}",node)
                actual = page.locator("#state .card b").all_text_contents()[1:]
                target = [f["temperature_c"][node],f["exact_c"][node],
                          f["temperature_c"][node]-f["exact_c"][node]]
                for text,value in zip(actual,target,strict=True):
                    assert abs(float(text.split()[0])-value) <= max(1e-8,abs(value)*6e-6)
            for selector,rows in (("#csv",c["nodes"]+1),("#interface",c["n"]+1)):
                with page.expect_download() as download:
                    page.locator(selector).click()
                assert len(Path(download.value.path()).read_text().splitlines()) == rows
        page.locator("#node").focus()
        page.keyboard.press("Home")
        assert page.locator("#now").inner_text() == "0"
        page.keyboard.press("End")
        assert int(page.locator("#now").inner_text()) == data["cases"][-1]["nodes"]-1
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
              checks=["actual mesh","numeric heat/node states","negative ambient flow",
                                     "all node/interface CSVs","keyboard endpoints","390px",
                                     "four figures/PDF","material and boundary mechanisms"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui,indent=2))
    print("p7-layered-ui: "+json.dumps(ui),flush=True)


if __name__ == "__main__":
    main()
