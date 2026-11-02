"""Offline FEMM motor states, five research figures and actual browser/download validation."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/p7-femm"
OUT = ROOT / "outputs/p7-femm-report"


def records(path):
    a = np.genfromtxt(path, delimiter=",", names=True)
    return [{k:float(r[k]) for k in a.dtype.names} for r in a]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = OUT / "plots"
    plots.mkdir(exist_ok=True)
    data = json.loads((SOURCE / "validation.json").read_text())
    probe = json.loads((SOURCE / "probe-validation.json").read_text())
    assert data["passed"] and probe["passed"]
    foc = {}
    for c in data["foc"]:
        path = OUT / "foc"
        path.mkdir(exist_ok=True)
        shutil.copyfile(SOURCE / "foc" / (c["id"]+".csv"), path / (c["id"]+".csv"))
        foc[c["id"]] = records(path / (c["id"]+".csv"))
    for g in data["grids"]:
        path = OUT / f"grid{g['grid']}"
        path.mkdir(exist_ok=True)
        for name in ("open-24.csv", "open-48.csv", "loaded.csv", "phase-inductance-h.csv"):
            shutil.copyfile(SOURCE / f"grid{g['grid']}" / name, path / name)
    spectrum = {}
    for g in data["grids"]:
        path = SOURCE / f"grid{g['grid']}/open-48.csv"
        rows = records(path)
        values = np.array([[r["lambda_"+p+"_wb"] for p in ("a", "b", "c")] for r in rows])
        amplitudes = 2*abs(np.fft.rfft(values, axis=0))/len(values)
        amplitudes[0] /= 2
        amplitudes[-1] /= 2
        thd = np.sqrt(np.sum(amplitudes[2:]**2, axis=0))/amplitudes[1]
        orders = np.arange(1, len(amplitudes))
        spectrum[str(g["grid"])] = dict(
            thd_relative=thd.tolist(), orders=orders.tolist(),
            amplitudes_wb=amplitudes[1:].tolist(),
            source_csv_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            scope="48 FE angles; harmonic orders 1..24, not a beyond-Nyquist bound")
        np.savetxt(OUT / f"grid{g['grid']}/harmonics.csv",
                   np.column_stack([orders, amplitudes[1:]]), delimiter=",", comments="",
                   header="harmonic_order,lambda_a_amplitude_wb,lambda_b_amplitude_wb,"
                          "lambda_c_amplitude_wb")
    (OUT / "harmonic-analysis.json").write_text(json.dumps(spectrum, indent=2))
    figures = []
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for key in ("az_relative_rms", "b_relative_rms"):
        axes[0].loglog([c["h_mm"] for c in probe["cases"]],
                       [c[key] for c in probe["cases"]], "o-", label=key)
    axes[0].set(xlabel="Mesh h (mm)", ylabel="Relative point-set RMS error")
    axes[0].legend(fontsize=7)
    a = np.genfromtxt(SOURCE / "cylinder-h0.5/points.csv", delimiter=",", names=True)
    axes[1].plot(a["bx_t"], "o", label="Actual FEMM Bx")
    axes[1].plot(a["exact_bx_t"], "--", label="Independent finite-boundary Bx")
    axes[1].set(xlabel="Frozen sample index", ylabel="Bx (T)")
    axes[1].legend(fontsize=7)
    figures.append(("01-cylinder", fig))
    fine = data["grids"][-1]
    f = records(SOURCE / f"grid{fine['grid']}/open-24.csv")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for phase in ("a", "b", "c"):
        axes[0].plot([r["angle_deg"] for r in f], [r["lambda_"+phase+"_wb"] for r in f],
                     "o-", label="FE phase "+phase)
    for key in ("lambda_d_wb", "lambda_q_wb"):
        axes[1].plot([r["angle_deg"] for r in f], [r[key] for r in f], "o-", label=key)
    for ax in axes:
        ax.set(xlabel="Rotor magnetization angle (mechanical deg)", ylabel="Flux linkage (Wb)")
        ax.legend(fontsize=7)
    figures.append(("02-flux", fig))
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), layout="constrained")
    for ax, key, factor, unit in ((axes[0], "psi_wb", 1e3, "mWb"),
                                  (axes[1], "ld_h", 1e6, "uH"),
                                  (axes[2], "lq_h", 1e6, "uH")):
        values = [g["extraction"][key] if key == "psi_wb" else g[key] for g in data["grids"]]
        ax.plot([g["h_mm"] for g in data["grids"]], np.array(values)*factor, "o-")
        ax.set(xlabel="Global mesh h (mm)", ylabel=key+" ("+unit+")")
    figures.append(("03-parameters", fig))
    fig, ax = plt.subplots(figsize=(10, 4), layout="constrained")
    keys = ("weighted_nm", "mst720_nm", "virtual_nm", "expected_nm")
    for i, key in enumerate(keys):
        ax.bar(np.arange(2)+(i-1.5)*.18, [fine["torque"][name][key]
                                         for name in ("qplus", "qminus")], .18, label=key)
    ax.set_xticks([0, 1], ["Iq +0.5 A", "Iq -0.5 A"])
    ax.set_ylabel("Torque (Nm)")
    ax.legend(fontsize=7)
    figures.append(("04-torque", fig))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for name, rows in foc.items():
        axes[0].plot([r["time_s"] for r in rows], [r["iq_a"] for r in rows], label=name)
        axes[1].plot([r["time_s"] for r in rows], [r["torque_nm"] for r in rows], label=name)
    axes[0].set(xlabel="Time (s)", ylabel="Actual Iq (A)")
    axes[1].set(xlabel="Time (s)", ylabel="Reduced-plant torque (Nm)")
    for ax in axes:
        ax.legend()
    figures.append(("05-foc", fig))
    with PdfPages(OUT / "report.pdf") as pdf:
        for name, fig in figures:
            fig.savefig(plots / (name+".png"), dpi=170)
            fig.savefig(plots / (name+".svg"))
            pdf.savefig(fig)
            plt.close(fig)
    for name in ("parameters.json", "validation.json", "probe-validation.json"):
        shutil.copyfile(SOURCE / name, OUT / name)
    shutil.copyfile(ROOT / "docs/p7-femm-motor-contract.md", OUT / "contract.md")
    for name in ("femm-source-review-AFPL.txt", "pyfemm-source-review-AFPL.txt"):
        shutil.copyfile(ROOT / "research/licenses" / name, OUT / name)
    if (SOURCE / "installed-licenses").exists():
        shutil.copytree(SOURCE / "installed-licenses", OUT / "installed-licenses",
                        dirs_exist_ok=True)
    parameter_text = (SOURCE / "parameters.json").read_text()
    assert hashlib.sha256((OUT / "parameters.json").read_bytes()).hexdigest() == (
        data["parameter_sha256"])
    run_url = "https://github.com/lse872317312010/open-engineering-agent-lab/actions/runs/"
    run_url += os.environ.get("GITHUB_RUN_ID", "")
    html = (ROOT / "reports/p7-femm-motor.html").read_text()
    html = html.replace("__DATA__", json.dumps(data)).replace("__PROBE__", json.dumps(probe))
    html = html.replace("__FOC__", json.dumps(foc))
    html = html.replace("__SPECTRUM__", json.dumps(spectrum))
    html = html.replace("__PARAMETER_TEXT__", json.dumps(parameter_text))
    (OUT / "index.html").write_text(html.replace("__RUN_URL__", run_url), encoding="utf-8")
    (OUT / "README.txt").write_text(
        "解压打开index.html。实际FEMM静态提参、三网格与降阶motulator FOC。\n"
        "静态扫角不是时间积分。14完整CSV、冻结参数、五图PDF、许可与原始证据入口。\n"
        "无槽两极合成模型，非实测或完整逐步电磁FE联合；真机由用户负责。\n",
        encoding="utf-8")
    errors, network = [], []
    csv_count = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda e:errors.append(str(e)))
        page.on("request", lambda r:network.append(r.url)
                if r.url.startswith(("http://", "https://")) else None)
        page.goto((OUT / "index.html").as_uri())
        assert not errors, errors
        assert page.locator("#results tbody tr").count() == 3
        assert page.evaluate("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
        for g in data["grids"]:
            page.select_option("#grid", str(g["grid"]))
            for i in (0, 6, 12, 18, 23, 24, 25, 26, 27):
                page.locator("#point").evaluate(
                    "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'));}", i)
                row = g["snapshots"][i]
                assert row["mode"] in page.locator("#state").inner_text()
                assert page.locator("#windings path").count() == 6
                assert page.locator("#gap-vectors path").count() == 36
                values = [row["current_a"], row["current_b"], row["current_c"],
                          row["lambda_a_wb"], row["lambda_b_wb"], row["lambda_c_wb"],
                          row["lambda_d_wb"], row["lambda_q_wb"], row["torque_weighted_nm"]]
                text = page.locator("#field-cards b").all_text_contents()
                for actual, expected in zip(text[:9], values, strict=True):
                    assert abs(float(actual.split()[0])-expected) <= max(1e-20, abs(expected)*6e-6)
            for selector, count in (("#open24", 25), ("#open48", 49), ("#loaded", 5),
                                     ("#harmonics", 25)):
                with page.expect_download() as download:
                    page.locator(selector).click()
                assert len(Path(download.value.path()).read_text().splitlines()) == count
                csv_count += 1
        for c in data["foc"]:
            page.select_option("#foc-case", c["id"])
            for i in (0, len(foc[c["id"]])//2, len(foc[c["id"]])-1):
                page.locator("#foc-time").evaluate(
                    "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'));}", i)
                row = foc[c["id"]][i]
                expected = [row[k] for k in ("iq_a", "iq_reference_a", "id_a", "torque_nm",
                                             "motor_speed_rad_s")]
                text = page.locator("#foc-cards b").all_text_contents()
                for actual, value in zip(text[:5], expected, strict=True):
                    assert abs(float(actual.split()[0])-value) <= max(1e-20, abs(value)*6e-6)
            with page.expect_download() as download:
                page.locator("#foc-csv").click()
            assert len(Path(download.value.path()).read_text().splitlines()) == c["rows"]+1
            csv_count += 1
        with page.expect_download() as download:
            page.locator("#parameters").click()
        assert Path(download.value.path()).read_bytes() == (SOURCE / "parameters.json").read_bytes()
        page.locator("#point").focus()
        page.keyboard.press("Home")
        assert page.locator("#point").input_value() == "0"
        page.keyboard.press("End")
        assert page.locator("#point").input_value() == "27"
        page.locator("#play").click()
        page.wait_for_timeout(350)
        assert int(page.locator("#point").input_value()) > 0
        page.locator("#play").click()
        value = page.locator("#point").input_value()
        page.wait_for_timeout(250)
        assert page.locator("#point").input_value() == value
        page.screenshot(path=str(OUT / "ui-desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"), full_page=True)
        version = browser.version
        browser.close()
    assert not errors and not network, (errors, network)
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    ui = dict(passed=True, browser=version,
              report_commit=subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], text=True).strip(),
              csv_downloads=csv_count, exact_parameter_download=True,
              page_errors=errors, external_requests=network,
              checks=["3 meshes/28 FE states", "geometry/circuits/gap vectors",
                      "signed numeric values", "2 actual FOC traces", "14 full CSV",
                      "exact parameter bytes", "keyboard/play/pause", "390px", "five figures/PDF"])
    (OUT / "ui-validation.json").write_text(json.dumps(ui, indent=2))
    print("p7-femm-ui: "+json.dumps(ui), flush=True)


if __name__ == "__main__":
    main()
