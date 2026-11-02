"""Light duty-cycle report with full CSV downloads and a separate full-evidence entry."""
import gzip
import hashlib
import json
import os
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-drive-cycle"
OUT = ROOT / "outputs/p7-drive-cycle-report"


def row_dict(row):
    return {name:float(row[name]) for name in row.dtype.names}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    all_controls, controls, thermal, raw_hashes = {}, {}, {}, {}
    special = (222, 223, 8002, 8003, 15999, 16000, 19999, 20000,
               8752, 8753, 8754, 18076, 18077, 18078)
    ticks = sorted(set(range(0, 40001, 25)) | set(special))
    for c in data["cases"]:
        folder = SOURCE / c["id"]
        a = np.genfromtxt(folder / "control.csv", delimiter=",", names=True)
        all_controls[c["id"]] = a
        controls[c["id"]] = [row_dict(a[t]) for t in ticks]
        t = np.genfromtxt(folder / "thermal.csv", delimiter=",", names=True)
        thermal[c["id"]] = [row_dict(r) for r in t]
        target = OUT / c["id"]
        target.mkdir(exist_ok=True)
        for name in ("control.csv", "thermal.csv", "native-controller.csv",
                     "input.json", "result.json"):
            shutil.copyfile(folder / name, target / name)
        with gzip.open(folder / "rhs.csv.gz", "rt") as stream:
            assert sum(1 for _ in stream) == c["rhs_rows"]+1
        fields = np.load(folder / "thermal-fields.npz")
        assert fields["rom_temperature_c"].shape == (c["thermal_rows"], 2178)
        assert fields["fom_temperature_c"].shape == (c["thermal_rows"], 2178)
        assert fields["fast_20khz_states"].shape == (40001, 22)
        for name in ("rhs.csv.gz", "thermal-fields.npz"):
            raw_hashes[c["id"]+"/"+name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
    figures = []
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    a = all_controls["cycle-feedback"]
    axes[0].plot(a["time_s"], a["iq_a"], label="Actual Iq")
    axes[0].plot(a["time_s"], a["iq_reference_a"], "--", label="Reference Iq")
    axes[0].set(xlabel="Time (s)", ylabel="Iq (A)")
    axes[0].legend()
    axes[1].plot(a["time_s"], a["speed_rad_s"], label="Rotor speed")
    axes[1].set(xlabel="Time (s)", ylabel="Mechanical speed (rad/s)")
    brake = axes[1].twinx()
    brake.plot(a["time_s"], a["held_brake_nms"], color="orange", label="External damping")
    brake.set_ylabel("Mechanical damping (N m s)")
    for ax in axes:
        ax.axvspan(.8, 2, alpha=.1, color="blue")
    figures.append(("01-cycle", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    for name in ("cycle-feedback", "cycle-frozen", "cycle-fine"):
        t = thermal[name]
        for ax, key in zip(axes, ("left_c", "right_c"), strict=True):
            ax.plot([r["time_s"] for r in t], [r[key] for r in t], label=name)
    for ax, side in zip(axes, ("Left", "Right"), strict=True):
        ax.axvspan(.8, 2, alpha=.1, color="blue")
        ax.set(xlabel="Time (s)", ylabel=side+" equivalent-region mean (degC)")
        ax.legend(fontsize=7)
    figures.append(("02-cooling", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    t = thermal["cycle-feedback"]
    for values, label in (
        ([r["input_left_j"]+r["input_right_j"] for r in t], "Copper + bridge input"),
        ([r["stored_left_j"]+r["stored_right_j"] for r in t], "Slab stored energy"),
        ([r["left_out_j"]+r["right_out_j"] for r in t], "Slab boundary out")):
        axes[0].plot([r["time_s"] for r in t], values, label=label)
    axes[0].set(xlabel="Time (s)", ylabel="Slab thermal energy (J)")
    for key, label in (("source_j", "DC feed"), ("friction_j", "Mechanical dissipation"),
                       ("load_j", "Signed external load work")):
        axes[1].plot(a["time_s"], a[key], label=label)
    axes[1].set(xlabel="Time (s)", ylabel="Separate electrical/mechanical ledger (J)")
    for ax in axes:
        ax.axvspan(.8, 2, alpha=.1, color="blue")
        ax.legend(fontsize=7)
    figures.append(("03-energy", fig))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    chunk = all_controls["cycle-chunked"]
    axes[0].semilogy(a["time_s"], np.maximum(abs(a["iq_a"]-chunk["iq_a"]), 1e-18))
    t, tc = thermal["cycle-feedback"], thermal["cycle-chunked"]
    for key in ("left_c", "right_c"):
        axes[1].semilogy([r["time_s"] for r in t],
                        np.maximum(abs(np.array([r[key] for r in t])
                                       -np.array([r[key] for r in tc])), 1e-18), label=key)
    axes[0].set(xlabel="Time (s)", ylabel="Continuation Iq difference (A); floor 1e-18")
    axes[1].set(xlabel="Time (s)", ylabel="Continuation mean T difference (K); floor 1e-18")
    axes[1].legend()
    for ax in axes:
        for tick in data["chunk_ticks"]:
            ax.axvline(tick*50e-6, linestyle="--", color="gray")
    figures.append(("04-continuation", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    for name in ("pymor-2026.1.1-LICENSE.txt", "pymor-2026.1.1-LICENSES_bundled.txt",
                 "gmsh-4.13.1.txt", "scikit-fem-11.0.0.txt", "meshio-5.3.5.txt",
                 "motulator-refinement.txt"):
        shutil.copyfile(ROOT / "research/licenses" / name, OUT / name)
    shutil.copyfile(SOURCE / "validation.json", OUT / "validation.json")
    shutil.copyfile(ROOT / "docs/p7-drive-cycle-contract.md", OUT / "contract.md")
    (OUT / "raw-file-hashes.json").write_text(json.dumps(raw_hashes, indent=2))
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = "https://github.com/lse872317312010/open-engineering-agent-lab/actions"
    if run_id:
        run_url += "/runs/"+run_id
    template = (ROOT / "reports/p7-drive-cycle.html").read_text()
    (OUT / "index.html").write_text(template.replace("__DATA__", json.dumps(data))
                                   .replace("__CONTROLS__", json.dumps(controls))
                                   .replace("__THERMAL__", json.dumps(thermal))
                                   .replace("__RUN_URL__", run_url))
    (OUT / "README.txt").write_text(
        "解压打开index.html。页面为每25tick+关键边界抽样回放；完整20kHz控制/热CSV随包。\n"
        "四图PDF/PNG/SVG、结果/输入、阶段及连续性；RHS/全场在独立raw-evidence artifact。\n"
        "原始数据入口为稳定GitHub运行页；本地完整证据在outputs/p7-drive-cycle。\n")
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: network.append(r.url)
                if r.url.startswith(("http://", "https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert page.locator("#results tbody tr").count() == 4
        assert page.locator("#raw").get_attribute("href") == run_url
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for c in data["cases"]:
            page.select_option("#case", c["id"])
            for tick in (0, 223, 8003, 15999, 16000, 8753, 18077, 20000, 40000):
                index = ticks.index(tick)
                page.locator("#time").evaluate(
                    "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'));}", index)
                r = controls[c["id"]][index]
                t = thermal[c["id"]][tick//c["ratio"]]
                for selector, expected in (
                    ("#thermal b", [r["held_left_c"], r["held_right_c"],
                                     r["temperature_age_ticks"],
                                     t["mean_left_w"]+t["mean_right_w"]]),
                    ("#energy b", [t["stored_left_j"]+t["stored_right_j"],
                                    t["left_out_j"]+t["right_out_j"], r["friction_j"]])):
                    texts = page.locator(selector).all_text_contents()
                    if selector == "#energy b":
                        texts = texts[1:]
                    for text, value in zip(texts, expected, strict=True):
                        assert abs(float(text.split()[0])-value) <= max(1e-9, abs(value)*6e-6)
                if tick >= 16000:
                    assert "控制保持启用" in page.locator("#phase").inner_text()
                if tick == 40000:
                    assert "终点无新控制命令" in page.locator("#phase").inner_text()
            for selector, count in (("#control", 40002), ("#windows", c["thermal_rows"]+1),
                                    ("#native", 40001)):
                with page.expect_download() as download:
                    page.locator(selector).click()
                assert len(Path(download.value.path()).read_text().splitlines()) == count
        page.locator("#time").focus()
        page.keyboard.press("Home")
        assert page.locator("#time").input_value() == "0"
        page.keyboard.press("End")
        assert int(page.locator("#time").input_value()) == len(ticks)-1
        page.locator("#play").click()
        page.wait_for_timeout(300)
        assert int(page.locator("#time").input_value()) > 0
        page.locator("#play").click()
        value = page.locator("#time").input_value()
        page.wait_for_timeout(200)
        assert page.locator("#time").input_value() == value
        page.screenshot(path=str(OUT / "ui-desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"), full_page=True)
        version = browser.version
        browser.close()
    assert not errors and not network, (errors, network)
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    ui = dict(passed=True, browser=version, cases=4, display_rows=len(ticks),
              page_errors=errors, external_requests=network,
              checks=["all stages/checkpoints/endpoints", "numeric held thermal/energy values",
                      "12 complete CSV downloads", "raw shape/gzip/hash audit",
                      "explicit sampled view", "keyboard/play/pause", "390px", "four figures/PDF"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui, indent=2))
    print("p7-cycle-ui: "+json.dumps(ui), flush=True)


if __name__ == "__main__":
    main()
