"""Freeze training-only open-circuit frame and validate interleaved FE holdout."""
import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
import numpy as np
from p7_dq_reference import fit_frame
from playwright.sync_api import sync_playwright

from oeal.transforms import clarke, inverse_clarke, inverse_park, park

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-dq-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = ROOT / "outputs/p7-refinement-report/angle-data.json"
    data = json.loads(source.read_text())
    assert data["passed"]
    (OUT / "verified-source.json").write_bytes(source.read_bytes())
    cases = data["lanes"][0]["cases"]
    assert len(cases) == 24
    angles = np.deg2rad([r["angle_deg"] for r in cases])
    flux = np.array([r["flux_wb"] for r in cases])
    assert all(r["grid"] == 2 and r["length_m"] == .05
               and all(i == 0 for i in r["currents_a"]) for r in cases)
    train, holdout = list(range(0, 24, 2)), list(range(1, 24, 2))
    assert not set(train) & set(holdout)
    frame = fit_frame(angles[train], flux[train])
    frame.update(training_indices=train, holdout_indices=holdout,
                 absolute_offset_rad=frame["offset_rad"]-math.pi/2,
                 source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    path = OUT / "frame.json"
    path.write_text(json.dumps(frame, indent=2), encoding="utf-8")
    frozen = hashlib.sha256(path.read_bytes()).hexdigest()
    rows, errors = [], []
    for i, (angle, row) in enumerate(zip(angles, flux, strict=True)):
        alpha, beta, zero = clarke(*row)
        electrical = 4*angle+frame["offset_rad"]
        d, q = park(alpha, beta, electrical)
        aa, bb = inverse_park(d, q, electrical)
        restored = inverse_clarke(aa, bb, zero)
        errors.append(max(abs(float(x)-y) for x, y in zip(row, restored, strict=True)))
        rows.append(dict(index=i, angle_deg=math.degrees(angle), electrical_rad=electrical,
                         d_wb=d, q_wb=q, zero_wb=zero, abc=row.tolist(),
                         split="training" if i % 2 == 0 else "holdout"))
    q_error = max(abs(rows[i]["q_wb"]) for i in holdout)/.05
    d_error = max(abs(rows[i]["d_wb"]-frame["amplitude_wb"]) for i in holdout)/.05
    checks = dict(holdout_q=q_error <= .08, holdout_d=d_error <= .08,
                  roundtrip=max(errors) <= 1e-12,
                  frozen=frozen == hashlib.sha256(path.read_bytes()).hexdigest())
    report = dict(passed=all(checks.values()), checks=checks, frame=frame, rows=rows,
                  holdout_q_normalized=q_error, holdout_d_normalized=d_error,
                  roundtrip_wb=max(errors), frozen_sha256=frozen,
                  commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  source_commits=[data["source_commit"], data["fine_commit"]])
    (OUT / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (OUT / "dq.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["index", "split", "relative_deg", "electrical_rad",
                    "lambda_d_wb", "lambda_q_wb", "lambda_zero_wb"])
        for r in rows:
            w.writerow([r[k] for k in ("index", "split", "angle_deg", "electrical_rad",
                                      "d_wb", "q_wb", "zero_wb")])
    print("dq-summary: "+json.dumps({k: v for k, v in report.items() if k != "rows"}), flush=True)
    assert report["passed"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for key in ("d_wb", "q_wb", "zero_wb"):
        axes[0].plot([r["angle_deg"] for r in rows], [r[key] for r in rows], "o-", label=key)
    axes[0].set(xlabel="mechanical relative angle [deg]", ylabel="linkage [Wb]")
    axes[0].legend()
    axes[1].plot(holdout, [rows[i]["q_wb"] for i in holdout], "o", label="held-out q")
    axes[1].set(xlabel="holdout index", ylabel="q-axis linkage [Wb]")
    axes[1].legend()
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("dq."+suffix))
    plt.close(fig)
    template = (ROOT / "reports/p7-dq.html").read_text(encoding="utf-8")
    (OUT / "index.html").write_text(
        template.replace("__DATA__", json.dumps(report).replace("</", "<\\/")), encoding="utf-8")
    errors, external = [], []
    with sync_playwright() as p, TemporaryDirectory() as tmp:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: external.append(r.url)
                if r.url.startswith(("http:", "https:")) else None)
        page.goto((OUT / "index.html").as_uri())
        for r in rows:
            page.select_option("#state", str(r["index"]))
            for key in ("d_wb", "q_wb", "zero_wb"):
                assert float(page.locator("#"+key).get_attribute("data-number")) == r[key]
        with page.expect_download() as ev:
            page.locator("#csv").click()
        saved = Path(tmp) / "dq.csv"
        ev.value.save_as(saved)
        assert saved.read_bytes() == (OUT / "dq.csv").read_bytes()
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        result = dict(passed=not errors and not external, states=24, errors=errors,
                      external_requests=external, browser=browser.version)
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(result), encoding="utf-8")
    print("dq-ui: "+json.dumps(result), flush=True)
    assert result["passed"]


if __name__ == "__main__":
    main()
