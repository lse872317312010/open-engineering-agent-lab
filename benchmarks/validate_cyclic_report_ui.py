"""Real browser verification of cyclic endpoints, nominal/actual data and full CSV."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/cyclic-report"


def main():
    errors, network = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: network.append(request.url)
                if request.url.startswith(("http://", "https://")) else None)
        page.goto((OUT / "index.html").as_uri(), wait_until="load")
        assert page.locator("#case option").count() == 8
        assert page.locator("#cases tr").count() == 8
        assert page.locator("#position polyline").count() == 2
        data = json.loads((OUT / "report-data.json").read_text())
        expected = "固定联合验收通过" if data["passed"] else "存在未通过工况，请查看下表"
        assert page.locator("#gate").inner_text() == expected
        for name, end in (("nominal", 1.22), ("combined", 1.22),
                          ("combined-fine", 1.22), ("legacy-step", .25)):
            page.select_option("#case", name)
            page.locator("#time").focus()
            page.keyboard.press("Home")
            assert page.locator("#time-label").inner_text().startswith("0.000 s")
            page.keyboard.press("End")
            assert page.locator("#time-label").inner_text().startswith(f"{end:.3f} s")
            assert page.locator("#states .card").count() == 4
            assert page.locator("#parameter-table tr").count() == 4
            if name in {"combined", "combined-fine", "legacy-step"}:
                text = page.locator("#parameter-table tr").first.inner_text()
                assert "0.30000" in text and "0.36000" in text and "20.0%" in text
            with page.expect_download() as download:
                page.locator("#csv").click()
            rows = Path(download.value.path()).read_text().splitlines()
            assert rows[0].startswith("time_s,joint_angle_rad")
            assert abs(float(rows[-1].split(",")[0]) - end) < 1e-12
            assert len(rows) >= (1252 if name == "legacy-step" else 6102)
        page.screenshot(path=str(OUT / "ui-desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"), full_page=True)
        version = browser.version
        browser.close()
    assert not errors, errors
    assert not network, network
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    assert len(list((OUT / "plots").glob("*.png"))) == 4
    report = dict(passed=True, browser=version, page_errors=errors, external_requests=network,
                  checks=["eight cases", "frozen nominal vs actual parameters",
                          "real 0/1.22 s cyclic and 0/.25 s legacy endpoints",
                          "full joint CSV", "390px layout", "four PDF/PNG/SVG figures"])
    (OUT / "ui-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("cycle-ui.json: " + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
