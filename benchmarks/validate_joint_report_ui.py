"""Exercise real offline interactions, exports, endpoints and mobile layout."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/joint-report"


def main():
    errors, requests = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        page = browser.new_page(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url)
                if request.url.startswith(("https://", "http://")) else None)
        page.goto((OUT / "index.html").as_uri(), wait_until="load")
        assert page.locator("#case option").count() == 7
        assert page.locator("#cases tr").count() == 7
        assert page.locator("#position polyline").count() == 2
        assert page.locator("#thermal polyline").count() == 6
        data = json.loads((OUT / "report-data.json").read_text())
        assert ("通过" in page.locator("#gate").inner_text()) == data["passed"]
        for name in ("nominal", "combined-holdout", "combined-fine"):
            page.select_option("#case", name)
            page.locator("#time").focus()
            page.keyboard.press("Home")
            assert "0.000 s" in page.locator("#time-label").inner_text()
            page.keyboard.press("End")
            assert "1.000 s" in page.locator("#time-label").inner_text()
            assert page.locator("#states .card").count() == 4
            with page.expect_download() as download:
                page.locator("#csv").click()
            downloaded = download.value
            assert downloaded.suggested_filename == name + "-joint.csv"
            contents = Path(downloaded.path()).read_text()
            assert contents.startswith("time_s,joint_angle_rad,")
            assert len(contents.splitlines()) >= 5002
            assert contents.splitlines()[-1].startswith("1,") or contents.splitlines()[-1].startswith("1.0,")
        assert "PWM" in page.locator("#mode-state").inner_text()
        with page.expect_download() as download:
            page.locator("#json").click()
        assert json.loads(Path(download.value.path()).read_text())["source_commit"] == data["source_commit"]
        page.screenshot(path=str(OUT / "ui-desktop.png"), full_page=True)
        page.set_viewport_size(dict(width=390, height=844))
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUT / "ui-mobile.png"), full_page=True)
        missing = page.locator("button,input,select").evaluate_all(
            "nodes => nodes.filter(n => !(n.textContent.trim() || n.labels?.length || n.getAttribute('aria-label'))).length")
        assert missing == 0
        version = browser.version
        browser.close()
    assert not errors, errors
    assert not requests, requests
    assert (OUT / "report.pdf").read_bytes().startswith(b"%PDF")
    assert len(list((OUT / "plots").glob("*.png"))) == 5
    report = dict(passed=True, browser=version, page_errors=errors, external_requests=requests,
                  checks=["seven cases", "honest verdict", "nominal and two holdout timelines",
                          "real 0/1 s endpoints", "full joint CSV", "JSON provenance",
                          "five PDF/PNG/SVG figures", "390px layout", "control labels",
                          "separate prescribed thermal replay"])
    (OUT / "ui-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("joint-ui.json: " + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
