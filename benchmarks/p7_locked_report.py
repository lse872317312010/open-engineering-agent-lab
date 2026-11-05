"""Offline replay of actual sampled locked-rotor closed-loop trajectories."""
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-locked-report"


def main():
    data = json.loads((OUT / "validation.json").read_text())
    assert data["passed"]
    series = {name:np.genfromtxt(OUT / (name+".csv"), delimiter=",", skip_header=1).tolist()
              for name in ("nominal", "fine", "undervoltage")}
    data["series"] = series
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    for name, values in series.items():
        v = np.array(values)
        axes[0, 0].plot(v[:, 0], v[:, 2], label=name)
        axes[0, 1].plot(v[:, 0], v[:, 5], label=name)
        axes[1, 0].plot(v[:, 0], v[:, 12], label=name)
    nominal = np.array(series["nominal"])
    axes[0, 0].plot(nominal[:, 0], nominal[:, 3], "k--", label="reference")
    for column, label in ((9, "source"), (10, "copper"), (11, "stored")):
        axes[1, 1].plot(nominal[:, 0], nominal[:, column], label=label)
    for ax, ylabel in zip(axes.flat, ("iq [A]", "vq [V]", "balance [J]", "energy [J]"),
                         strict=True):
        ax.set(xlabel="time [s]", ylabel=ylabel)
        ax.legend(fontsize=7)
        ax.grid(alpha=.15)
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("current-loop."+suffix))
    plt.close(fig)
    template = (ROOT / "reports/p7-locked.html").read_text(encoding="utf-8")
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
        for name, values in series.items():
            assert len(values) == 801
            page.select_option("#scenario", name)
            for index in (0, 19, 20, 399, 400, 700, 800):
                page.eval_on_selector("#tick", """(e, v) => {
                    e.value=v; e.dispatchEvent(new Event('input', {bubbles:true}));
                }""", str(index))
                for key, column in (("iq", 2), ("reference", 3), ("vq", 5), ("balance", 12)):
                    actual = float(page.locator("#"+key).get_attribute("data-number"))
                    assert actual == values[index][column]
            with page.expect_download() as event:
                page.locator("#csv").click()
            target = Path(tmp) / (name+".csv")
            event.value.save_as(target)
            assert target.read_bytes() == (OUT / (name+".csv")).read_bytes()
            with (OUT / (name+".csv")).open() as fp:
                assert len(list(csv.reader(fp))) == 802
        page.locator("#tick").focus()
        page.keyboard.press("Home")
        assert page.locator("#tick").input_value() == "0"
        page.keyboard.press("End")
        assert page.locator("#tick").input_value() == "800"
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        ui = dict(passed=not errors and not external, states=21, exact_csv=3,
                  errors=errors, external_requests=external, browser=browser.version)
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(ui), encoding="utf-8")
    print("locked-ui: "+json.dumps(ui), flush=True)
    assert ui["passed"]


if __name__ == "__main__":
    main()
