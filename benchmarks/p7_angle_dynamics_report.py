"""Render and exercise the combined loaded field and dynamic interface report."""
import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-angle-dynamics"


def main():
    fields = json.loads((OUT / "fields.json").read_text())
    dynamics = json.loads((OUT / "dynamics.json").read_text())
    assert fields["evidence_passed"] and len(fields["rows"]) == 36
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for i in range(4):
        group = fields["rows"][i::4]
        label = f"id={group[0]['id_a']} iq={group[0]['iq_a']}"
        axes[0, 0].plot(fields["angles"], [r["actual_wb"][0] for r in group], "o-", label=label)
        axes[0, 1].plot(fields["angles"], [r["fe_torque_nm"] for r in group], "o-", label=label)
    axes[0, 0].set(xlabel="mechanical angle [deg]", ylabel="d linkage [Wb]")
    axes[0, 1].set(xlabel="mechanical angle [deg]", ylabel="absolute FE torque [Nm]")
    axes[0, 2].plot(range(16), [v["flux_error"] for v in fields["comparisons"]],
                    "o-", label="flux / 0.05 Wb")
    axes[0, 2].axhline(.02, color="red", ls="--", label="budget")
    axes[0, 2].set(xlabel="midpoint/current case", ylabel="interpolation discrepancy")
    for case in dynamics["cases"]:
        rows = case["rows"]
        axes[1, 0].plot([r["time_s"]*1000 for r in rows], [r["iq_a"] for r in rows],
                        label=f"{case['rpm']} rpm iq")
        axes[1, 1].plot([r["time_s"]*1000 for r in rows], [r["balance_j"] for r in rows],
                        label=f"{case['rpm']} rpm")
    axes[1, 0].set(xlabel="time [ms]", ylabel="iq [A]")
    axes[1, 1].set(xlabel="time [ms]", ylabel="energy balance [J]")
    axes[1, 2].bar(range(4), [v["torque_diff_nm"] for v in fields["endpoint"]],
                   label="0 vs 45 deg absolute torque")
    axes[1, 2].set(xlabel="current case", ylabel="closure discrepancy [Nm]")
    for ax in axes.flat:
        ax.grid(alpha=.15)
        ax.legend(fontsize=7)
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("overview."+suffix))
    plt.close(fig)
    files = ("fields.json", "dynamics.json", "overview.pdf")
    data = dict(fields=fields, dynamics=dynamics,
                exports=[dict(name=name, base64=base64.b64encode((OUT/name).read_bytes()).decode())
                         for name in files])
    template = (ROOT / "reports/p7-angle-dynamics.html").read_text(encoding="utf-8")
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
        for r in fields["rows"]:
            page.select_option("#angle", str(r["index"]//4))
            page.select_option("#current", str(r["index"]%4))
            for key in ("flux_error", "torque_error_nm", "increment_nm"):
                assert float(page.locator("#"+key).get_attribute("data-number")) == r[key]
            assert page.locator("#point-status").get_attribute("data-supported") == str(
                r["supported"]).lower()
            assert page.locator(".coil").count() == 24
            assert page.locator(".magnet").count() == 8
            assert page.locator(".gapvector").count() == 48
        for index, case in enumerate(dynamics["cases"]):
            page.select_option("#case", str(index))
            for tick in (0, len(case["rows"])//2, len(case["rows"])-1):
                page.locator("#tick").fill(str(tick))
                for key in ("time_s", "id_a", "iq_a", "source_j", "mechanical_j", "balance_j"):
                    assert float(page.locator("#"+key).get_attribute("data-number")) == (
                        case["rows"][tick][key])
            assert page.locator("#dyn-point").get_attribute("data-supported") == str(
                case["passed"]).lower()
        for selector, value in (("#angle-status", fields["angle_supported"]),
                                ("#model-status", fields["model_supported"]),
                                ("#dynamic-status", dynamics["passed"])):
            assert page.locator(selector).get_attribute("data-supported") == str(value).lower()
        page.locator(".coil").first.click()
        assert "匝" in page.locator("#component").inner_text()
        page.locator(".coil").first.focus()
        page.keyboard.press("Enter")
        assert "电流" in page.locator("#component").inner_text()
        names = ("fields.csv", "positive.csv", "negative.csv", *files)
        for name in names:
            with page.expect_download() as event:
                page.locator(f'a[data-export="{name}"]').click()
            path = Path(tmp) / name
            event.value.save_as(path)
            assert hashlib.sha256(path.read_bytes()).digest() == (
                hashlib.sha256((OUT/name).read_bytes()).digest())
        assert page.evaluate("Array.from(document.images).every(i=>i.complete && i.naturalWidth)")
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        ui = dict(passed=not errors and not external, field_states=36, dynamic_states=6,
                  exact_downloads=6, errors=errors, external_requests=external,
                  browser=browser.version)
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(ui), encoding="utf-8")
    print("angle-dynamics-ui: "+json.dumps(ui), flush=True)
    assert ui["passed"]


if __name__ == "__main__":
    main()
