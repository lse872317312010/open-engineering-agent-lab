"""Train a local flux model at one angle, freeze, and evaluate the other angle."""
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
import numpy as np
from p7_local_flux_model import LocalFluxModel
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-local-flux-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = ROOT / "outputs/p7-loaded-report/validation.json"
    evidence = json.loads(source.read_text())
    assert evidence["passed"] and len(evidence["rows"]) == 10
    rows = evidence["rows"]
    assert all(r["angle_deg"] == 0 for r in rows[:5])
    assert all(r["angle_deg"] == 22.5 for r in rows[5:])
    flux = np.array([[r["d_wb"], r["q_wb"]] for r in rows])
    psi = flux[0]
    raw = np.column_stack(((flux[3]-flux[4])/4, (flux[1]-flux[2])/4))
    matrix = (raw+raw.T)/2
    model = LocalFluxModel(psi, matrix)
    frozen = dict(psi_wb=psi.tolist(), inductance_h=matrix.tolist(), raw_inductance_h=raw.tolist(),
                  training_indices=list(range(5)), holdout_indices=list(range(5, 10)),
                  domain="abs(id)+abs(iq)<=2 A; pointwise validation only",
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    path = OUT / "model.json"
    path.write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = []
    for index, r in enumerate(rows):
        current = [r["id_a"], r["iq_a"]]
        prediction = model.flux(current)
        error = float(np.linalg.norm(prediction-flux[index])/.05)
        torque = float(6*(prediction[0]*current[1]-prediction[1]*current[0]))
        result.append(dict(index=index, split="training" if index < 5 else "holdout",
                           angle_deg=r["angle_deg"], id_a=current[0], iq_a=current[1],
                           actual_wb=flux[index].tolist(), predicted_wb=prediction.tolist(),
                           error_normalized=error, fe_increment_nm=r["increment_nm"],
                           predicted_torque_nm=torque,
                           torque_error_nm=abs(torque-r["increment_nm"])))
    train = max(r["error_normalized"] for r in result[:5])
    holdout = max(r["error_normalized"] for r in result[5:])
    torque_error = max(r["torque_error_nm"] for r in result)
    checks = dict(training=train <= .002, holdout=holdout <= .02, torque=torque_error <= .10,
                  frozen=digest == hashlib.sha256(path.read_bytes()).hexdigest())
    data = dict(passed=all(checks.values()), checks=checks, rows=result, model=frozen,
                eigenvalues_h=np.linalg.eigvalsh(matrix).tolist(),
                reciprocity_residual_h=float(np.max(abs(raw-raw.T))),
                train_error=train, holdout_error=holdout, torque_error_nm=torque_error,
                frozen_sha256=digest, source_commit=evidence["source_commit"],
                commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    (OUT / "validation.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (OUT / "verified-source.json").write_bytes(source.read_bytes())
    with (OUT / "cases.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["index", "split", "angle_deg", "id_a", "iq_a", "actual_d_wb", "actual_q_wb",
                    "predicted_d_wb", "predicted_q_wb", "flux_error_normalized",
                    "fe_increment_nm", "predicted_torque_nm", "torque_error_nm"])
        for r in result:
            w.writerow([r["index"], r["split"], r["angle_deg"], r["id_a"], r["iq_a"],
                        *r["actual_wb"], *r["predicted_wb"], r["error_normalized"],
                        r["fe_increment_nm"], r["predicted_torque_nm"], r["torque_error_nm"]])
    print("local-flux-summary: "+json.dumps({k: v for k, v in data.items() if k != "rows"}),
          flush=True)
    assert data["passed"], checks
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for q, label in enumerate(("d", "q")):
        axes[0].plot(range(10), flux[:, q], "o", label="FE "+label)
        axes[0].plot(range(10), [r["predicted_wb"][q] for r in result], "x--", label="model "+label)
    axes[0].set(xlabel="case (0-4 train, 5-9 holdout)", ylabel="flux linkage [Wb]")
    axes[0].legend()
    axes[1].plot(range(10), [r["torque_error_nm"] for r in result], "o-")
    axes[1].set(xlabel="case", ylabel="torque discrepancy [Nm]")
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("model."+suffix))
    plt.close(fig)
    template = (ROOT / "reports/p7-local-flux.html").read_text(encoding="utf-8")
    (OUT / "index.html").write_text(
        template.replace("__DATA__", json.dumps(data).replace("</", "<\\/")), encoding="utf-8")
    errors, external = [], []
    with sync_playwright() as p, TemporaryDirectory() as tmp:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: external.append(r.url)
                if r.url.startswith(("http:", "https:")) else None)
        page.goto((OUT / "index.html").as_uri())
        for r in result:
            page.select_option("#case", str(r["index"]))
            for key in ("error_normalized", "predicted_torque_nm", "torque_error_nm"):
                assert float(page.locator("#"+key).get_attribute("data-number")) == r[key]
        with page.expect_download() as event:
            page.locator("#csv").click()
        saved = Path(tmp) / "cases.csv"
        event.value.save_as(saved)
        assert saved.read_bytes() == (OUT / "cases.csv").read_bytes()
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        ui = dict(passed=not errors and not external, cases=10,
                  errors=errors, external_requests=external, browser=browser.version)
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(ui), encoding="utf-8")
    print("local-flux-ui: "+json.dumps(ui), flush=True)
    assert ui["passed"]


if __name__ == "__main__":
    main()
