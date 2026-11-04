"""Audit actual loaded native evidence, compare torque routes, and validate offline UI."""
import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-loaded-report"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    commit = os.environ["LOADED_COMMIT"]
    subprocess.run(["git", "fetch", "origin", commit, "--depth=1"], check=True)
    subprocess.run(["git", "diff", "--exit-code", commit, "HEAD", "--",
                    "benchmarks/p7_loaded_native.py", "benchmarks/p7_loaded_solver.py",
                    "benchmarks/p7_pyleecan.py", "benchmarks/assets/pyleecan-spmsm001.json",
                    "src/oeal/transforms.py"], check=True)
    rows, counts = [], []
    for shard in range(2):
        folder = ROOT / f"outputs/loaded/loaded-{shard}"
        manifest = json.loads((folder / "manifest.json").read_text())
        for name, digest in manifest.items():
            assert not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
        environment = json.loads((folder / "environment.json").read_text())
        assert environment["source_commit"] == commit
        assert environment["executable_sha256"] == (
            "5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21")
        lane = json.loads((folder / "loaded.json").read_text())
        assert lane["commit"] == commit and lane["shard"] == shard
        assert lane["passed"] and all(lane["checks"].values()) and len(lane["cases"]) == 5
        assert hashlib.sha256((folder / "frame.json").read_bytes()).hexdigest() == (
            "541602aad016740d7263493d6062244edfae0923c2b59a1ac349889547c9234f")
        native = {n for n in manifest if n.endswith((".fem", ".ans"))}
        seen = set()
        for r in lane["cases"]:
            assert r["passed"] and all(r["checks"].values())
            for name, digest in r["native_files"].items():
                assert name in native and manifest[name] == digest
                seen.add(name)
            r["d_wb"], r["q_wb"], r["zero_wb"] = (
                r["lambda_d_wb"], r["lambda_q_wb"], r["lambda_zero_wb"])
            r["ia_a"], r["ib_a"], r["ic_a"] = r["native_currents_a"]
            r["index"] = len(rows)
            rows.append(r)
        assert seen == native and len(seen) == 10
        counts.append(len(manifest))
    data = dict(passed=True, rows=rows, manifest_counts=counts, source_commit=commit,
                report_commit=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                      text=True).strip(),
                run_id=os.environ["LOADED_RUN"],
                max_formula_error_nm=max(r["formula_error_nm"] for r in rows))
    (OUT / "validation.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with (OUT / "loaded.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        keys = ["angle_deg", "id_a", "iq_a", "ia_a", "ib_a", "ic_a",
                "electrical_rad", "d_wb", "q_wb", "zero_wb",
                "torque_nm", "gap_torque_nm", "fundamental_torque_nm",
                "increment_nm", "formula_error_nm"]
        w.writerow(keys)
        w.writerows([[r[k] for k in keys] for r in rows])
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for key in ("torque_nm", "gap_torque_nm", "fundamental_torque_nm"):
        axes[0].plot(range(10), [r[key] for r in rows], "o-", label=key)
    axes[0].set(xlabel="static load case", ylabel="torque [Nm]")
    axes[0].legend(fontsize=7)
    for key in ("d_wb", "q_wb"):
        axes[1].plot(range(10), [r[key] for r in rows], "o-", label=key)
    axes[1].set(xlabel="static load case", ylabel="linkage [Wb]")
    axes[1].legend()
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("loaded."+suffix))
    plt.close(fig)
    template = (ROOT / "reports/p7-loaded.html").read_text(encoding="utf-8")
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
        for r in rows:
            page.select_option("#state", str(r["index"]))
            for key in ("d_wb", "q_wb", "torque_nm", "id_a", "iq_a"):
                assert float(page.locator("#"+key).get_attribute("data-number")) == r[key]
        with page.expect_download() as event:
            page.locator("#csv").click()
        path = Path(tmp) / "loaded.csv"
        event.value.save_as(path)
        assert path.read_bytes() == (OUT / "loaded.csv").read_bytes()
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        result = dict(passed=not errors and not external, states=10,
                      errors=errors, external_requests=external, browser=browser.version)
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(result), encoding="utf-8")
    print("loaded-report: "+json.dumps({k: v for k, v in data.items() if k != "rows"}), flush=True)
    print("loaded-ui: "+json.dumps(result), flush=True)
    for r in rows:
        print("loaded-case: "+json.dumps({k: r[k] for k in
              ("angle_deg", "id_a", "iq_a", "torque_nm", "increment_nm",
               "fundamental_torque_nm", "formula_error_nm")}), flush=True)
    assert result["passed"]


if __name__ == "__main__":
    main()
