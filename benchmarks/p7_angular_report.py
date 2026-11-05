"""Offline angular-model support report: valid evidence may reject the model hypothesis."""
import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-angular-report"


def main():
    data = json.loads((OUT / "validation.json").read_text())
    assert data["evidence_passed"]
    rows = data["rows"]
    assert len(rows) == 40
    angles = data["angles"]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for condition in range(5):
        selected = rows[condition::5]
        label = f"id={selected[0]['id_a']}, iq={selected[0]['iq_a']}"
        for axis in range(2):
            axes[0, axis].plot(angles, [r["actual_wb"][axis] for r in selected],
                               "o-", ms=3, label=label)
            axes[0, axis].plot(angles, [r["predicted_wb"][axis] for r in selected], "--", lw=.8)
        if condition in (1, 2):
            axes[1, 0].plot(angles, [r["increment_nm"] for r in selected], "o-", label=label)
            axes[1, 0].plot(angles, [r["predicted_torque_nm"] for r in selected], "--")
    axes[0, 0].set(ylabel="d linkage [Wb]")
    axes[0, 1].set(ylabel="q linkage [Wb]")
    axes[1, 0].set(ylabel="FE increment / model torque [Nm]")
    axes[1, 1].plot(angles, [r["torque_error_nm"] for r in data["envelopes"]],
                    "o-", label="max torque discrepancy")
    axes[1, 1].axhline(.10, color="red", ls="--", label="frozen 0.10 Nm budget")
    axes[1, 1].set(ylabel="torque discrepancy [Nm]")
    for ax in axes.flat:
        ax.set(xlabel="relative mechanical angle [deg]")
        ax.grid(alpha=.15)
        ax.legend(fontsize=6)
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("angular."+suffix))
    plt.close(fig)
    data["exports"] = [dict(name=name, base64=base64.b64encode((OUT / name).read_bytes()).decode())
                       for name in ("validation.json", "angular.pdf")]
    template = (ROOT / "reports/p7-angular.html").read_text(encoding="utf-8")
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
            page.select_option("#angle", str(r["index"]//5))
            page.select_option("#current", str(r["index"]%5))
            for key in ("flux_error", "torque_error_nm", "increment_nm"):
                assert float(page.locator("#"+key).get_attribute("data-number")) == r[key]
            assert page.locator("#point-status").get_attribute("data-supported") == (
                str(r["supported"]).lower())
            assert page.locator(".coil").count() == 24
            assert page.locator(".magnet").count() == 8
            assert page.locator(".gapvector").count() == 48
        assert page.locator("#model-status").get_attribute("data-supported") == (
            str(data["model_supported"]).lower())
        page.locator(".coil").first.click()
        assert "匝" in page.locator("#component").inner_text()
        page.locator(".coil").first.focus()
        page.keyboard.press("Enter")
        assert "电流" in page.locator("#component").inner_text()
        for name in ("angular.csv", "validation.json", "angular.pdf"):
            with page.expect_download() as event:
                page.locator(f'a[data-export="{name}"]').click()
            path = Path(tmp) / name
            event.value.save_as(path)
            assert hashlib.sha256(path.read_bytes()).digest() == (
                hashlib.sha256((OUT / name).read_bytes()).digest())
        assert page.evaluate("Array.from(document.images).every(i=>i.complete && i.naturalWidth)")
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        ui = dict(passed=not errors and not external, states=40, exact_downloads=3,
                  model_supported=data["model_supported"], errors=errors,
                  external_requests=external, browser=browser.version)
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(ui), encoding="utf-8")
    print("angular-ui: "+json.dumps(ui), flush=True)
    assert ui["passed"]


if __name__ == "__main__":
    main()
