"""Replay prescribed-speed scenarios and the deliberately rejected low-voltage prefix."""
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-rotation-report"


def main():
    data = json.loads((OUT / "validation.json").read_text())
    assert data["passed"]
    names = ("forward", "reverse", "fine", "undervoltage")
    series = {name:np.genfromtxt(OUT / (name+".csv"), delimiter=",", skip_header=1).tolist()
              for name in names}
    data["series"] = series
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    for name, values in series.items():
        v = np.array(values)
        axes[0, 0].plot(v[:, 0], v[:, 2], label=name)
        axes[0, 1].plot(v[:, 0], v[:, 18], label=name)
        axes[1, 0].plot(v[:, 0], v[:, 13], label=name)
    forward = np.array(series["forward"])
    axes[0, 0].plot(forward[:, 0], forward[:, 3], "k--", label="reference")
    for column, label in ((9, "source"), (10, "copper"), (11, "shaft"), (12, "stored")):
        axes[1, 1].plot(forward[:, 0], forward[:, column], label=label)
    for ax, label in zip(axes.flat, ("iq [A]", "electrical angle [rad]", "balance [J]", "energy [J]"),
                         strict=True):
        ax.set(xlabel="time [s]", ylabel=label)
        ax.grid(alpha=.15)
        ax.legend(fontsize=7)
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("rotation."+suffix))
    plt.close(fig)
    template = (ROOT / "reports/p7-rotation.html").read_text(encoding="utf-8")
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
            assert len(values) == data["scenarios"][name]["samples"]
            page.select_option("#scenario", name)
            last = len(values)-1
            for index in (0, min(19, last), min(20, last), min(599, last),
                          min(600, last), min(1000, last), last):
                page.eval_on_selector("#tick", """(e, v) => {
                    e.value=v; e.dispatchEvent(new Event('input', {bubbles:true}));
                }""", str(index))
                for key, column in (("iq", 2), ("reference", 3), ("angle", 18), ("balance", 13)):
                    assert float(page.locator("#"+key).get_attribute("data-number")) == (
                        values[index][column])
            with page.expect_download() as event:
                page.locator("#csv").click()
            target = Path(tmp) / (name+".csv")
            event.value.save_as(target)
            assert target.read_bytes() == (OUT / (name+".csv")).read_bytes()
            with target.open() as fp:
                assert len(list(csv.reader(fp))) == len(values)+1
        assert "拒绝" in page.locator("#gate").inner_text()
        page.locator("#tick").focus()
        page.keyboard.press("Home")
        assert page.locator("#tick").input_value() == "0"
        page.keyboard.press("End")
        assert page.locator("#tick").input_value() == str(len(series["undervoltage"])-1)
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        ui = dict(passed=not errors and not external, states=28, exact_csv=4,
                  errors=errors, external_requests=external, browser=browser.version)
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(ui), encoding="utf-8")
    print("rotation-ui: "+json.dumps(ui), flush=True)
    assert ui["passed"]


if __name__ == "__main__":
    main()
