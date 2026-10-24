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

        assert page.locator("#system-map .module").count() == 8
        assert page.locator("#system-map .flow").count() == 11
        assert page.locator("#system-states button").count() == 8
        page.locator('#system-map [data-module="thermal"]').click()
        assert "温差与热阻" in page.locator("#system-detail").inner_text()
        page.locator('#system-map [data-module="delay"]').focus()
        page.locator('#system-map [data-module="delay"]').press("Enter")
        assert "保持命令和 PI 内部量未在 CSV 导出" in page.locator("#system-detail").inner_text()
        page.screenshot(path=str(REPORT / "ui-desktop.png"), full_page=True)
        page.locator("#system-model").screenshot(path=str(REPORT / "ui-system-model.png"))

        page.locator("#case-select").select_option("4")
        assert "未达" in page.locator("#case-status").inner_text()

        assert "4 V" in page.locator("#case-insight").inner_text()
        assert "整段目标：未达" in page.locator("#system-goal").inner_text()
        assert "低母线" in page.locator("#system-time").inner_text()
        page.locator('#system-states [data-module="inverter"]').click()
        assert "实时母线 4.00 V" in page.locator("#system-detail").inner_text()

        page.locator("#compare").check()
        assert page.locator("#current-chart polyline").count() == 3
        page.locator("#time-cursor").focus()
        page.locator("#time-cursor").press("Home")
        assert page.locator("#cursor-time").inner_text() == "0.00 ms"
        page.locator("#time-cursor").press("End")
        assert "80.00 ms" in page.locator("#cursor-time").inner_text()

        page.locator("#case-select").select_option("5")
        assert "已锁存" in page.locator('#system-states [data-module="stop"]').inner_text()
        inverter_state = page.locator('#system-states [data-module="inverter"]')
        assert "零平均电压命令" in inverter_state.inner_text()
        page.locator('#system-states [data-module="stop"]').click()
        assert "CSV tripped = 1" in page.locator("#system-detail").inner_text()
        page.locator("#case-select").select_option("0")
        page.locator("#time-cursor").focus()
        page.locator("#time-cursor").press("Home")
        assert "等待目标阶跃" in page.locator('#system-states [data-module="control"]').inner_text()
        assert "0.00 ms" in page.locator("#system-time").inner_text()
        assert "未触发" in page.locator('#system-states [data-module="stop"]').inner_text()
        page.locator("#time-cursor").press("End")
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

        refined = json.loads((REPORT / "data.json").read_text()).get("refined", {})
        if refined.get("passed"):
            assert page.locator("#refined-case option").count() == 12
            assert page.locator("#refined-results tr").count() == 16
            page.locator("#refined-case").select_option("9")
            assert "未达" in page.locator("#refined-insight").inner_text()
            page.locator("#refined-case").select_option("7")
            page.locator("#refined-cursor").fill("500")
            page.locator("#refined-cursor").dispatch_event("input")
            assert "门极关闭" in page.locator("#refined-states").inner_text()
            page.locator("#refined-domain").select_option("robot")
            assert page.locator("#refined-case option").count() == 4
            page.locator("#refined-case").select_option("2")
            assert "MuJoCo" in page.locator("#refined-insight").inner_text()
            assert "peak_fixture_force_n" in page.locator("#refined-parameters").text_content()
            page.locator("#refined-cursor").focus()
            page.locator("#refined-cursor").press("Home")
            assert page.locator("#refined-time").inner_text() == "0.00 ms"
            page.locator("#refined-cursor").press("End")
            end_time = page.locator("#refined-time").inner_text()
            assert "250.00 ms" in end_time, repr(end_time)
            with page.expect_download() as info:
                page.locator("#refined-csv").click()
            file = REPORT / "refined-export-check.csv"
            info.value.save_as(str(file))
            assert file.read_text().startswith("time_s,joint_angle_rad")
            page.locator("#refined").screenshot(path=str(REPORT / "ui-open-models.png"))

        design = json.loads((REPORT / "data.json").read_text()).get("design", {})
        if design.get("validations"):
            assert page.locator("#unified-results tr").count() == 5
            assert page.locator("#design-trial-rows tr").count() == 8
            assert page.locator("#design-results tr").count() == 3
            assert page.locator("#design-trace-chart polyline").count() == 3
            page.locator("#design-case").select_option("2")
            assert "0.5 kg" in page.locator("#design-insight").inner_text()
            page.locator("#design-cursor").focus()
            page.locator("#design-cursor").press("Home")
            assert page.locator("#design-time").inner_text() == "0.00 ms"
            page.locator("#design-cursor").press("End")
            assert page.locator("#design-time").inner_text() == "250.00 ms"
            assert page.locator("#design-states .refined-state").count() == 4
            with page.expect_download() as info:
                page.locator("#design-csv").click()
            file = REPORT / "design-export-check.csv"
            info.value.save_as(str(file))
            assert file.read_text().startswith("time_s,baseline_angle_rad")
            page.locator("#design").screenshot(path=str(REPORT / "ui-design.png"))

        energy = json.loads((REPORT / "data.json").read_text()).get("energy", {})
        if energy.get("passed"):
            assert page.locator("#energy-case option").count() == 9
            assert page.locator("#energy-results tr").count() == 9
            assert page.locator("#energy-robot-results tr").count() == 3
            assert page.locator("#energy-flow-chart polyline").count() == 2
            page.locator("#energy-case").select_option("8")
            assert "应失败" in page.locator("#energy-case-status").inner_text()
            assert "故障注入" in page.locator("#energy-insight").inner_text()
            page.locator("#energy-case").select_option("4")
            page.locator("#energy-cursor").focus()
            page.locator("#energy-cursor").press("Home")
            assert page.locator("#energy-time").inner_text() == "0.00 ms"
            page.locator("#energy-cursor").press("End")
            assert page.locator("#energy-time").inner_text() == "60.00 ms"
            page.locator("#energy-case").select_option("5")
            assert not page.locator("#energy-robot-content").is_hidden()
            assert "全系统守恒证明" in page.locator("#energy-insight").inner_text()
            assert page.locator("#energy-interface-chart polyline").count() == 3
            with page.expect_download() as info:
                page.locator("#energy-csv").click()
            file = REPORT / "energy-export-check.csv"
            info.value.save_as(str(file))
            assert file.read_text().startswith("time_s,source_j,source_abs_j")
            page.locator("#energy").screenshot(path=str(REPORT / "ui-energy.png"))

        coupling = json.loads((REPORT / "data.json").read_text()).get("coupling", {})
        if coupling.get("passed"):
            assert page.locator("#coupling-pair option").count() == 6
            assert page.locator("#coupling-results tr").count() == 11
            assert page.locator("#coupling-comparisons tr").count() == 3
            assert page.locator("#coupling-residual-chart polyline").count() == 2
            page.locator("#coupling-pair").select_option("4")
            assert "Kp / Kd" in page.locator("#coupling-insight").inner_text()
            page.locator("#coupling-cursor").focus()
            page.locator("#coupling-cursor").press("Home")
            assert page.locator("#coupling-time").inner_text() == "0.00 ms"
            page.locator("#coupling-cursor").press("End")
            assert page.locator("#coupling-time").inner_text() == "250.00 ms"
            page.locator("#coupling-pair").select_option("5")
            assert "只改变积分器" in page.locator("#coupling-insight").inner_text()
            assert "未启用预测器" in page.locator("#coupling-law-note").inner_text()
            page.locator("#coupling-pair").select_option("0")
            assert page.locator("#coupling-states .refined-state").count() == 4
            assert page.locator("#coupling-law-chart polyline").count() == 3
            with page.expect_download() as info:
                page.locator("#coupling-csv").click()
            file = REPORT / "coupling-export-check.csv"
            info.value.save_as(str(file))
            assert file.read_text().startswith("time_s,held_torque_nm,actual_delta_rad")
            page.locator("#coupling").screenshot(path=str(REPORT / "ui-coupling.png"))

        page.set_viewport_size({"width": 390, "height": 844})
        page.reload(wait_until="load")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        page.locator("#case-select").select_option("3")
        page.locator("#explorer details summary").click()
        parameter_text = page.locator("#parameter-table").inner_text()
        assert "40 N·m/rad" in parameter_text, repr(parameter_text)

        page.locator('#system-states [data-module="joint"]').click()
        assert "外部负载 2 N·m" in page.locator("#system-detail").inner_text()
        assert "刚度 40 N·m/rad" in page.locator("#system-detail").inner_text()
        assert page.locator("#system-map").evaluate(
            "svg => svg.scrollWidth > svg.parentElement.clientWidth"
        )
        page.locator("#time-cursor").focus()
        page.locator("#time-cursor").press("ArrowLeft")
        assert page.locator("#time-cursor").input_value() == "999"

        if refined.get("passed"):
            page.locator("#refined-domain").select_option("robot")
            page.locator("#refined-case").select_option("1")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            assert page.locator("#refined-states .refined-state").count() == 4
        if design.get("validations"):
            page.locator("#design-case").select_option("1")
            assert "齿隙" in page.locator("#design-insight").inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        if energy.get("passed"):
            page.locator("#energy-case").select_option("8")
            assert "应失败" in page.locator("#energy-case-status").inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        if coupling.get("passed"):
            page.locator("#coupling-pair").select_option("3")
            assert "0.5 kg" in page.locator("#coupling-insight").inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
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
    assert len(pngs) == ((10 if design.get("validations") else 8 if refined.get("passed") else 5)
                         + (2 if energy.get("passed") else 0)
                         + (2 if coupling.get("passed") else 0))
    assert all(p.read_bytes().startswith(b"\x89PNG") for p in pngs)
    report = {
        "passed": True, "browser": "system Chrome via Playwright",
        "browser_version": browser_version,
        "checks": [
            "offline data and six scenarios", "failure state displayed", "baseline overlay",
            "keyboard time cursor", "thermal scenario", "dark theme", "CSV/JSON export",
            "390px mobile viewport without horizontal overflow", "control labels",
            "PDF and expected baseline/extended PNG figures",
            "eight system modules and eleven typed connections",
            "system state replay, boundary, trip and pre-step status",
            "module keyboard selection and mobile state cards",
        ],
        "page_errors": errors, "external_network_requests": network,
        "open_models_available": bool(refined.get("passed")),
        "design_available": bool(design.get("validations")),
        "energy_available": bool(energy.get("passed")),
        "coupling_available": bool(coupling.get("passed")),
        "energy_checks": ([
            "eight measured cases and one explicit fault-injection copy",
            "missing device branch shown as a failed balance",
            "0/60 ms keyboard endpoints and signed regeneration data",
            "robot interface diagnosis separated from the local gate",
            "CSV export and 390px layout",
        ] if energy.get("passed") else ["not run in this report"]),
        "open_model_checks": ([
            "12 electrical and four robot experiments", "negative physical goal retained",
            "blocked gates state replay", "robot timeline real endpoints",
            "CSV export and 390px component cards",
        ] if refined.get("passed") else ["not run in this baseline-only report"]),
        "screenshots": [
            "ui-desktop.png", "ui-dark-boundary.png", "ui-mobile.png", "ui-system-model.png",
            *(["ui-energy.png"] if energy.get("passed") else []),
            *(["ui-coupling.png"] if coupling.get("passed") else []),
        ],
    }
    (REPORT / "ui-validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print("report-ui.json: " + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
