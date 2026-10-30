"""Offline contact report, scientific figures and real browser verification."""
import json
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from p7_contact_reference import LENGTH, SPLIT, temperature
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-contact"
OUT = ROOT / "outputs/p7-contact-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    fields = {}
    for c in data["cases"]:
        folder = SOURCE / c["id"] / f"n{c['n']}"
        nodes = np.loadtxt(folder / "nodes.csv", delimiter=",", skiprows=1)
        reference = []
        for tag, a, b in ((10, 0, SPLIT), (20, SPLIT, LENGTH)):
            for x in np.linspace(a, b, 61):
                reference.append([tag, float(x), float(temperature(x, c["config"], tag))])
        fields[c["id"]+"-"+str(c["n"])] = dict(nodes=nodes.tolist(), reference=reference)
        shutil.copytree(folder, OUT / c["id"] / f"n{c['n']}", dirs_exist_ok=True)
    figures = []
    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    for name in data["convergence"]:
        group = [c for c in data["cases"] if c["id"] == name]
        ax.loglog([1/c["n"] for c in group], [c["l2_relative"] for c in group], "o-", label=name)
    ax.set(xlabel="1 / intervals per material", ylabel="Temperature rise relative L2")
    ax.legend()
    figures.append(("01-convergence", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for c in data["cases"]:
        if c["n"] != 32:
            continue
        f = fields[c["id"]+"-32"]
        nodes = np.asarray(f["nodes"])
        for tag in (10, 20):
            selected = nodes[nodes[:, 1] == tag]
            axes[0].scatter(selected[:, 2], selected[:, 4], s=2)
        interface = np.loadtxt(SOURCE / c["id"] / "n32/interface.csv", delimiter=",", skiprows=1)
        order = np.argsort(interface[:, 1])
        axes[1].plot(interface[order, 1], interface[order, 4], label=c["id"])
    axes[0].set(xlabel="x (m); all 2D nodes", ylabel="Temperature (degC)")
    axes[1].set(xlabel="Interface y (m)", ylabel="TL - TR (K)")
    axes[1].legend()
    figures.append(("02-contact", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    patches = data["patches"]
    axes[0].loglog([c["config"]["rc"] for c in patches],
                   [c["interface_right_w"] for c in patches], "o-", label="FE")
    axes[0].loglog([c["config"]["rc"] for c in patches],
                   [c["expected"]["interface_right_w"] for c in patches], "x", label="Series law")
    axes[0].set(xlabel="Areal contact resistance (m2 K/W)", ylabel="Zero-source heat power (W)")
    axes[0].legend()
    for index, name in enumerate(("global", "left region", "right region")):
        axes[1].semilogy(range(12), [max(abs(c["balances_w"][index])/c["power_scale_w"], 1e-18)
                                   for c in data["cases"]], "o-", label=name)
    axes[1].set(xlabel="All 12 case/mesh combinations", ylabel="Balance / power scale; floor 1e-18")
    axes[1].legend()
    figures.append(("03-sensitivity", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    shutil.copyfile(SOURCE / "validation.json", OUT / "validation.json")
    shutil.copyfile(ROOT / "docs/p7-contact-contract.md", OUT / "contract.md")
    for c in patches:
        shutil.copytree(SOURCE / c["id"], OUT / c["id"], dirs_exist_ok=True)
    for name in ("gmsh-4.13.1", "scikit-fem-11.0.0", "meshio-5.3.5"):
        shutil.copyfile(ROOT / f"research/licenses/{name}.txt", OUT / (name+"-LICENSE.txt"))
    template = (ROOT / "reports/p7-contact.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__", json.dumps(data))
                                   .replace("__FIELDS__", json.dumps(fields)))
    (OUT / "README.txt").write_text(
        "解压后打开index.html。三图PDF/PNG/SVG、十二组合、双区状态与接触机制。\n"
        "全部节点/界面CSV、分裂VTU、矩阵/解/原节点映射、冻结契约与验证JSON。\n")
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: network.append(r.url)
                if r.url.startswith(("http://", "https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#results tbody tr").count() == 12
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for c in data["cases"]:
            page.select_option("#case", c["id"])
            page.select_option("#mesh", str(c["n"]))
            assert page.locator("#profile circle").count() == c["nodes"]
            texts = page.locator("#powers b").all_text_contents()
            for text, key in zip(texts, ("left_out_w", "right_out_w",
                                        "interface_right_w", "jump_mean_k"), strict=True):
                assert abs(float(text.split()[0])-c[key]) <= max(1e-9, abs(c[key])*6e-6)
            assert page.locator("#balance").get_attribute("class") == "good"
            if c["id"] == "hot-ambient":
                assert "向左传热" in page.locator("#mechanism").inner_text()
                assert "提供热量" in page.locator("#mechanism").inner_text()
            for selector, rows in (("#nodes", c["nodes"]+1), ("#interface", 2*c["n"]+1)):
                with page.expect_download() as download:
                    page.locator(selector).click()
                assert len(Path(download.value.path()).read_text().splitlines()) == rows
        page.locator("#case").focus()
        page.keyboard.press("Home")
        assert page.locator("#case").input_value() == data["cases"][0]["id"]
        page.keyboard.press("End")
        assert page.locator("#case").input_value() == data["cases"][-1]["id"]
        page.screenshot(path=str(OUT / "ui-desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"), full_page=True)
        version = browser.version
        browser.close()
    assert not errors and not network, (errors, network)
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    ui = dict(passed=True, browser=version, combinations=12, page_errors=errors,
              external_requests=network, checks=["powers/jump", "contact direction", "all CSVs",
              "actual node plots", "keyboard", "390px", "three figures/PDF"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui, indent=2))
    print("p7-contact-ui: "+json.dumps(ui), flush=True)


if __name__ == "__main__":
    main()
