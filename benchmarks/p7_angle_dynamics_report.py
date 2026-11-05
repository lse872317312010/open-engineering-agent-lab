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
    control = json.loads((OUT / "control.json").read_text())
    spot = json.loads((OUT / "spot.json").read_text())
    second = json.loads((OUT / "second.json").read_text())
    deep = json.loads((OUT / "deep.json").read_text())
    assert deep["evidence_passed"] and len(deep["rows"]) == 130
    assert second["evidence_passed"] and len(second["rows"]) == 34
    assert spot["evidence_passed"] and len(spot["rows"]) == 8
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
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for case in control["scenarios"][:2]:
        rows = case["rows"]
        times = [v["time_s"]*1000 for v in rows]
        axes[0, 0].plot(times, [v["iq_a"] for v in rows], label=f"{case['rpm']} rpm iq")
        axes[0, 1].plot(times, [v["id_a"] for v in rows], label=f"{case['rpm']} rpm id")
        axes[1, 0].plot(times, [v["balance_j"] for v in rows], label=f"{case['rpm']} rpm")
    normal = control["scenarios"][0]["rows"]
    axes[0, 0].plot([v["time_s"]*1000 for v in normal],
                    [v["reference_a"] for v in normal], "--", label="reference")
    low = control["scenarios"][3]["rows"]
    axes[1, 1].plot([v["time_s"]*1000 for v in low], [v["iq_a"] for v in low],
                    label="undervoltage valid prefix")
    axes[0, 0].set(ylabel="iq [A]")
    axes[0, 1].set(ylabel="id [A]")
    axes[1, 0].set(ylabel="energy balance [J]")
    axes[1, 1].set(ylabel="iq [A]")
    for ax in axes.flat:
        ax.set(xlabel="time [ms]")
        ax.grid(alpha=.15)
        ax.legend(fontsize=7)
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("control."+suffix))
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for i in range(2):
        group = second["rows"][i::2]
        axes[0, 0].plot(second["angles"], [v["fe_torque_nm"] for v in group],
                        "o-", label=f"iq={group[0]['iq_a']} A")
        axes[0, 1].plot(second["angles"], [v["increment_nm"] for v in group],
                        "o-", label=f"iq={group[0]['iq_a']} A")
    for values, label in ((second["previous_comparisons"], "11.25 to 5.625 deg"),
                          (second["comparisons"], "5.625 to 2.8125 deg")):
        axes[1, 0].plot([v["angle_deg"] for v in values], [v["flux_error"] for v in values],
                        "o", label=label)
        axes[1, 1].plot([v["angle_deg"] for v in values], [v["torque_error_nm"] for v in values],
                        "o", label=label)
    axes[0, 0].set(ylabel="absolute torque [Nm]")
    axes[0, 1].set(ylabel="baseline-subtracted torque [Nm]")
    axes[1, 0].set(ylabel="flux difference / 0.05 Wb")
    axes[1, 1].set(ylabel="absolute torque difference [Nm]")
    axes[1, 0].axhline(.02, color="red", ls="--", label="budget")
    axes[1, 1].axhline(.10, color="red", ls="--", label="budget")
    for ax in axes.flat:
        ax.set(xlabel="relative mechanical angle [deg]")
        ax.grid(alpha=.15)
        ax.legend(fontsize=7)
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("second."+suffix))
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for i in range(2):
        group = deep["rows"][i::2]
        axes[0, 0].plot(deep["angles"], [v["fe_torque_nm"] for v in group],
                        label=f"iq={group[0]['iq_a']} A")
        axes[0, 1].plot(deep["angles"], [v["increment_nm"] for v in group],
                        label=f"iq={group[0]['iq_a']} A")
    labels = [str(v["midpoint_step_deg"]) for v in deep["levels"]]
    axes[1, 0].bar(labels, [v["max_torque_nm"] for v in deep["levels"]],
                   label="maximum absolute torque discrepancy")
    axes[1, 1].bar(labels, [v["max_flux"] for v in deep["levels"]],
                   label="maximum flux discrepancy")
    axes[1, 0].axhline(.10, color="red", ls="--", label="frozen budget")
    axes[1, 1].axhline(.02, color="red", ls="--", label="frozen budget")
    axes[0, 0].set(xlabel="relative mechanical angle [deg]", ylabel="absolute torque [Nm]")
    axes[0, 1].set(xlabel="relative mechanical angle [deg]", ylabel="increment torque [Nm]")
    axes[1, 0].set(xlabel="refined step [deg]", ylabel="absolute torque discrepancy [Nm]")
    axes[1, 1].set(xlabel="refined step [deg]", ylabel="flux discrepancy / 0.05 Wb")
    for ax in axes.flat:
        ax.grid(alpha=.15)
        ax.legend(fontsize=7)
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("deep."+suffix))
    plt.close(fig)
    files = ("fields.json", "dynamics.json", "control.json", "spot.json", "second.json",
             "deep.json", "overview.pdf", "control.pdf", "second.pdf", "deep.pdf")
    data = dict(fields=fields, dynamics=dynamics, control=control, spot=spot,
                second=second, deep=deep,
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
            assert page.locator("#machine .coil").count() == 24
            assert page.locator("#machine .magnet").count() == 8
            assert page.locator("#machine .gapvector").count() == 48
        for row in second["rows"]:
            page.select_option("#second-angle", str(row["index"]//2))
            page.select_option("#second-current", str(row["index"]%2))
            for key in ("fe_torque_nm", "increment_nm", "nodes"):
                assert float(page.locator("#sec_"+key).get_attribute("data-number")) == row[key]
            assert page.locator("#second-machine .coil").count() == 24
            assert page.locator("#second-machine .magnet").count() == 8
            assert page.locator("#second-machine .gapvector").count() == 48
        assert page.locator("#second-table tr").count() == 16
        page.locator("#second-machine .coil").first.click()
        assert "匝" in page.locator("#second-component").inner_text()
        assert float(page.locator("#closure").get_attribute("data-number")) == (
            fields["endpoint"][0]["flux_diff"])
        for row in deep["rows"]:
            page.select_option("#deep-angle", str(row["index"]//2))
            page.select_option("#deep-current", str(row["index"]%2))
            for key in ("fe_torque_nm", "increment_nm", "nodes"):
                assert float(page.locator("#deep_"+key).get_attribute("data-number")) == row[key]
            assert page.locator("#deep-machine .coil").count() == 24
            assert page.locator("#deep-machine .magnet").count() == 8
            assert page.locator("#deep-machine .gapvector").count() == 48
        assert page.locator("#deep-table tr").count() == 4
        page.locator("#deep-machine .coil").first.click()
        assert "匝" in page.locator("#deep-component").inner_text()
        for index, case in enumerate(dynamics["cases"]):
            page.select_option("#case", str(index))
            for tick in (0, len(case["rows"])//2, len(case["rows"])-1):
                page.locator("#tick").fill(str(tick))
                for key in ("time_s", "id_a", "iq_a", "source_j", "mechanical_j", "balance_j"):
                    assert float(page.locator("#"+key).get_attribute("data-number")) == (
                        case["rows"][tick][key])
            assert page.locator("#dyn-point").get_attribute("data-supported") == str(
                case["passed"]).lower()
        for index, case in enumerate(control["scenarios"]):
            page.select_option("#control-case", str(index))
            for tick in (0, len(case["rows"])//2, len(case["rows"])-1):
                page.locator("#control-tick").fill(str(tick))
                for key in ("time_s", "id_a", "iq_a", "reference_a", "source_j", "balance_j"):
                    assert float(page.locator("#ctl_"+key).get_attribute("data-number")) == (
                        case["rows"][tick][key])
            assert page.locator("#control-point").get_attribute("data-completed") == str(
                case["completed"]).lower()
        for selector, value in (("#angle-status", fields["angle_supported"]),
                                ("#model-status", fields["model_supported"]),
                                ("#dynamic-status", dynamics["passed"]),
                                ("#control-status", control["passed"]),
                                ("#spot-status", spot["mesh_supported"]),
                                ("#second-status", second["angle_supported"]),
                                ("#deep-status", deep["levels"][3]["supported"])):
            assert page.locator(selector).get_attribute("data-supported") == str(value).lower()
        assert page.locator("#spot-table tr").count() == 8
        assert page.locator("#table tr").count() == 16
        page.locator("#machine .coil").first.click()
        assert "匝" in page.locator("#component").inner_text()
        page.locator("#machine .coil").first.focus()
        page.keyboard.press("Enter")
        assert "电流" in page.locator("#component").inner_text()
        names = ("fields.csv", "positive.csv", "negative.csv", "control-forward.csv",
                 "control-reverse.csv", "control-fine.csv", "control-undervoltage.csv", "spot.csv",
                 "second.csv", "deep.csv",
                 *files)
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
                  control_states=12, second_states=34, deep_states=130, exact_downloads=20,
                  errors=errors, external_requests=external,
                  browser=browser.version)
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(ui), encoding="utf-8")
    print("angle-dynamics-ui: "+json.dumps(ui), flush=True)
    assert ui["passed"]


if __name__ == "__main__":
    main()
