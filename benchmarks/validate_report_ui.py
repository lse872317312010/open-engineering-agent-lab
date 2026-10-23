"""Exercise the offline report in a real browser and retain desktop/mobile evidence."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "outputs/report"


def main():
    errors, network = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        browser_version = browser.version
        context = browser.new_context(viewport={"width": 1440, "height": 1024},
                                      accept_downloads=True, device_scale_factor=1)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: network.append(request.url)
                if request.url.startswith(("http://", "https://")) else None)
        page.goto((REPORT / "index.html").as_uri(), wait_until="load")
        page.wait_for_function("document.querySelector('#case-select').options.length === 6")
        assert "验收通过" in page.locator("#gate").inner_text()
        assert page.locator("#comparison-table tr").count() == 6
        assert page.locator("#current-chart polyline").count() == 2
        page.screenshot(path=str(REPORT / "ui-desktop.png"), full_page=True)
        page.locator("#case-select").select_option("4")
        assert "未达" in page.locator("#case-status").inner_text()
        assert "4 V" in page.locator("#case-insight").inner_text()
        page.locator("#compare").check()
        assert page.locator("#current-chart polyline").count() == 3
        page.locator("#time-cursor").focus()
        page.locator("#time-cursor").press("Home")
        assert page.locator("#cursor-time").inner_text() == "0.00 ms"
        page.locator("#time-cursor").press("End")
        assert "80.00 ms" in page.locator("#cursor-time").inner_text()
        page.locator("#thermal-select").select_option("stress")
        assert "高负荷" in page.locator("#thermal-insight").inner_text()
        page.locator("#theme").click()
        assert page.locator("html").get_attribute("data-theme") == "dark"
        page.screenshot(path=str(REPORT / "ui-dark-boundary.png"), full_page=True)
        with page.expect_download() as download_info:
            page.locator("#download-csv").click()
        download = download_info.value
        csv_path = REPORT / download.suggested_filename
        download.save_as(str(csv_path))
        assert csv_path.read_text().splitlines()[0].startswith("time_s,id_a,iq_a")
        with page.expect_download() as download_info:
            page.locator("#export-json").click()
        download = download_info.value
        json_path = REPORT / "ui-export-check.json"
        download.save_as(str(json_path))
        assert json.loads(json_path.read_text())["gate"]["passed"]
        page.set_viewport_size({"width": 390, "height": 844})
        page.reload(wait_until="load")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.locator("#case-select").select_option("3")
        page.locator("#explorer details summary").click()
        parameter_text = page.locator("#parameter-table").inner_text()
        assert "40 N·m/rad" in parameter_text, repr(parameter_text)
        page.locator("#time-cursor").focus()
        page.locator("#time-cursor").press("ArrowLeft")
        assert page.locator("#time-cursor").input_value() == "999"
        page.screenshot(path=str(REPORT / "ui-mobile.png"), full_page=True)
        missing_labels = page.locator("input,select,button").evaluate_all("""nodes => nodes.filter(
            n => !(n.getAttribute('aria-label') || n.labels?.length ||
                   n.textContent.trim())).length""")
        assert missing_labels == 0
        browser.close()
    assert not errors, errors
    assert not network, network
    assert (REPORT / "report.pdf").read_bytes().startswith(b"%PDF")
    pngs = list((REPORT / "plots").glob("*.png"))
    assert len(pngs) == 4
    assert all(p.read_bytes().startswith(b"\x89PNG") for p in pngs)
    report = {
        "passed": True, "browser": "system Chrome via Playwright",
        "browser_version": browser_version,
        "checks": [
            "offline data and six scenarios", "failure state displayed", "baseline overlay",
            "keyboard time cursor", "thermal scenario", "dark theme", "CSV/JSON export",
            "390px mobile viewport without horizontal overflow", "control labels",
            "PDF and four PNG figures",
        ],
        "page_errors": errors, "external_network_requests": network,
        "screenshots": ["ui-desktop.png", "ui-dark-boundary.png", "ui-mobile.png"],
    }
    (REPORT / "ui-validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print("report-ui.json: " + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
