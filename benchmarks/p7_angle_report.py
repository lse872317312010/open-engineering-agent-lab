"""Render and browser-verify the offline angular sweep report."""
import base64
import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-angle-report"


def main():
    data = json.loads((OUT / "angle-data.json").read_text(encoding="utf-8"))
    assert data["passed"]
    angle = np.arange(12)*7.5
    fig1, axes = plt.subplots(1, 2, figsize=(10, 4))
    for q, name in enumerate("ABC"):
        axes[0].plot(angle, [r["flux_wb"][q] for r in data["lanes"][2]["cases"][:12]],
                     "o-", label=name)
        axes[1].plot(angle, np.array(data["e12"])[2, :, q], "o-", label=name)
    axes[0].set(xlabel="relative mechanical angle [deg]", ylabel="flux linkage [Wb]")
    axes[1].set(xlabel="relative mechanical angle [deg]", ylabel="quasi-static EMF [V]",
                title="600 rpm / zero current")
    fig2, axes = plt.subplots(1, 2, figsize=(10, 4))
    for j, grid in enumerate((1, 1.5, 2)):
        axes[0].plot(angle, np.array(data["e12"])[j, :, 0], "o-", label=f"K={grid}")
    axes[0].set(xlabel="relative mechanical angle [deg]", ylabel="phase A EMF [V]",
                title="Three actual FE meshes")
    axes[1].plot(angle, np.array(data["e12"])[2, :, 0], "o-", label="7.5 deg")
    axes[1].plot(angle[::2], np.array(data["e6"])[2, :, 0], "s--", label="15 deg")
    axes[1].set(xlabel="relative mechanical angle [deg]", ylabel="phase A EMF [V]",
                title="Angular sensitivity")
    figures = [fig1, fig2]
    with PdfPages(OUT / "figures.pdf") as pdf:
        for i, fig in enumerate(figures, 1):
            for ax in fig.axes:
                ax.grid(alpha=.2)
                ax.legend()
            fig.tight_layout()
            fig.savefig(OUT / f"figure-{i}.png", dpi=150)
            fig.savefig(OUT / f"figure-{i}.svg")
            pdf.savefig(fig)
            plt.close(fig)
    data["exports"] = [dict(name=name, base64=base64.b64encode((OUT / name).read_bytes()).decode())
                       for name in ("angle-data.json", "figures.pdf")]
    template = (ROOT / "reports/p7-pyleecan-angle.html").read_text(encoding="utf-8")
    encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    (OUT / "index.html").write_text(template.replace("__DATA__", encoded), encoding="utf-8")
    errors, external = [], []
    with sync_playwright() as p, TemporaryDirectory() as tmp:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: external.append(r.url)
                if r.url.startswith(("http:", "https:")) else None)
        page.goto((OUT / "index.html").as_uri())
        for grid in range(3):
            page.select_option("#grid", str(grid))
            for index in range(12):
                page.locator("#angle").fill(str(index))
                page.locator("#angle").dispatch_event("input")
                assert float(page.locator('[data-value="angle"]').get_attribute("data-number")) == (
                    index*7.5)
                for q in range(3):
                    el = page.locator(f'[data-value="flux{q}"]')
                    assert float(el.get_attribute("data-number")) == (
                        data["lanes"][grid]["cases"][index]["flux_wb"][q])
                    el = page.locator(f'[data-value="emf{q}"]')
                    assert float(el.get_attribute("data-number")) == data["e12"][grid][index][q]
        for value in ("-600", "1200"):
            page.select_option("#speed", value)
            q = float(page.locator('[data-value="emf0"]').get_attribute("data-number"))
            assert math.isclose(q, data["e12"][2][11][0]*int(value)/600, abs_tol=1e-12)
        assert page.locator(".coil").count() == 24
        assert page.locator(".magnet").count() == 8
        page.locator(".coil").first.click()
        assert "匝" in page.locator("#component").inner_text()
        for name in ("angle-scan.csv", "angle-data.json", "figures.pdf"):
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
        result = dict(passed=not errors and not external, browser=browser.version,
                      angle_states=36, speeds=[600, -600, 1200],
                      exact_downloads=3, errors=errors, external_requests=external)
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("angle-ui: "+json.dumps(result), flush=True)
    assert result["passed"]


if __name__ == "__main__":
    main()
