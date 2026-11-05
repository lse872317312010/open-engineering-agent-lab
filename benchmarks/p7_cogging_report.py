"""Produce and exercise the offline cogging and mechanical coenergy report."""
import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-cogging-report"


def main():
    fields = json.loads((OUT / "fields.json").read_text())
    dynamics = json.loads((OUT / "dynamics.json").read_text())
    native = json.loads((OUT / "native.json").read_text())
    assert native["evidence_passed"] and len(native["rows"]) == 8
    assert fields["evidence_passed"] and len(fields["rows"]) == 65
    rows = fields["rows"]
    angles = [r["angle_deg"] for r in rows]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    axes[0, 0].plot(angles, [r["zero_fe_nm"] for r in rows], "o", ms=2, label="actual FE")
    axes[0, 0].plot(angles, [r["cog_nm"] for r in rows], "-", label="periodic fit")
    axes[0, 0].set(xlabel="mechanical angle [deg]", ylabel="zero-current torque [Nm]")
    axes[0, 1].plot(angles, [r["coenergy_j"] for r in rows], label="integrated torque")
    axes[0, 1].set(xlabel="mechanical angle [deg]", ylabel="reconstructed coenergy [J]")
    axes[0, 2].plot(angles, [r["loaded_fe_nm"] for r in rows], "o", ms=2, label="FE +2 A")
    axes[0, 2].plot(angles, [r["loaded_predicted_nm"] for r in rows], label="model +2 A")
    axes[0, 2].set(xlabel="mechanical angle [deg]", ylabel="absolute torque [Nm]")
    for case in dynamics["cases"][:2]:
        trajectory = case["rows"]
        times = [r["time_s"]*1000 for r in trajectory]
        label = "forward" if case["direction"] > 0 else "reverse"
        axes[1, 0].plot(times, [r["omega_rad_s"] for r in trajectory], label=label)
        axes[1, 1].plot(times, [r["iq_a"] for r in trajectory], label=label)
        axes[1, 2].plot(times, [r["balance_j"] for r in trajectory], label=label)
    axes[1, 0].set(xlabel="time [ms]", ylabel="mechanical speed [rad/s]")
    axes[1, 1].set(xlabel="time [ms]", ylabel="iq [A]")
    axes[1, 2].set(xlabel="time [ms]", ylabel="energy balance [J]")
    for ax in axes.flat:
        ax.grid(alpha=.15)
        ax.legend(fontsize=7)
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("cogging."+suffix))
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    centers = [r["center_deg"] for r in native["rows"]]
    for key, label in (("stress_torque_nm", "rotor stress"),
                       ("gap_torque_nm", "gap stress"),
                       ("energy_torque_nm", "fine coenergy difference"),
                       ("coarse_torque_nm", "coarse coenergy difference")):
        axes[0, 0].plot(centers, [r[key] for r in native["rows"]], "o-", label=label)
    axes[0, 0].set(ylabel="zero-current torque [Nm]")
    axes[0, 1].plot(centers, [r["error_nm"] for r in native["rows"]], "o-", label="fine")
    axes[0, 1].plot(centers, [r["coarse_error_nm"] for r in native["rows"]], "o-", label="coarse")
    axes[0, 1].axhline(.10, color="red", ls="--", label="fine budget")
    axes[0, 1].set(ylabel="stress discrepancy [Nm]")
    for key, label in (("native_relative_j", "native total coenergy"),
                       ("reconstructed_relative_j", "reconstructed coenergy")):
        axes[1, 0].plot(centers, [r[key] for r in native["rows"]], "o-", label=label)
    axes[1, 0].set(ylabel="relative coenergy [J]")
    axes[1, 1].bar([str(v) for v in centers],
                   [r["gap_omission_effect_nm"] for r in native["rows"]],
                   label="omitting sliding gap")
    axes[1, 1].set(ylabel="torque difference [Nm]")
    for ax in axes.flat:
        ax.set(xlabel="mechanical angle [deg]")
        ax.grid(alpha=.15)
        ax.legend(fontsize=7)
    fig.tight_layout()
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(OUT / ("native."+suffix))
    plt.close(fig)
    files = ("fields.json", "dynamics.json", "coenergy-model.json", "cogging.pdf",
             "native.json", "native.pdf")
    data = dict(fields=fields, dynamics=dynamics, native=native,
                exports=[dict(name=name, base64=base64.b64encode((OUT/name).read_bytes()).decode())
                         for name in files])
    template = (ROOT / "reports/p7-cogging.html").read_text(encoding="utf-8")
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
            page.select_option("#angle", str(r["index"]))
            for key in ("zero_fe_nm", "cog_nm", "coenergy_j", "zero_torque_error_nm",
                        "flux_error", "loaded_error_nm"):
                assert float(page.locator("#"+key).get_attribute("data-number")) == r[key]
            assert page.locator("#point-status").get_attribute("data-supported") == str(
                r["zero_supported"] and r["loaded_supported"]).lower()
            assert page.locator("#machine .coil").count() == 24
            assert page.locator("#machine .magnet").count() == 8
            assert page.locator("#machine .gapvector").count() == 48
        for r in native["rows"]:
            page.select_option("#native-case", str(r["index"]))
            for key in ("energy_torque_nm", "stress_torque_nm", "error_nm", "gap_torque_nm",
                        "gap_omission_effect_nm", "relative_coenergy_error_j"):
                assert float(page.locator("#native_"+key).get_attribute("data-number")) == r[key]
            assert page.locator("#native-point").get_attribute("data-supported") == str(
                r["passed"]).lower()
            assert page.locator("#native-table tr").count() == 5
        page.locator("#show-native").click()
        assert page.locator("#angle").input_value() == str(
            round(native["rows"][-1]["center_deg"]/.703125))
        for index, case in enumerate(dynamics["cases"]):
            page.select_option("#case", str(index))
            for tick in (0, len(case["rows"])//2, len(case["rows"])-1):
                page.locator("#tick").fill(str(tick))
                for key in ("time_s", "theta_rad", "omega_rad_s", "id_a", "iq_a", "torque_nm",
                            "cog_torque_nm", "increment_torque_nm", "balance_j"):
                    assert float(page.locator("#"+key).get_attribute("data-number")) == (
                        case["rows"][tick][key])
            assert page.locator("#dynamic-point").get_attribute("data-completed") == str(
                case["completed"]).lower()
        for selector, value in (("#model-status", fields["model_supported"]),
                                ("#dynamic-status", dynamics["passed"]),
                                ("#native-status", native["supported"])):
            assert page.locator(selector).get_attribute("data-supported") == str(value).lower()
        page.locator("#machine .coil").first.click()
        assert "匝" in page.locator("#component").inner_text()
        page.locator("#machine .coil").first.focus()
        page.keyboard.press("Enter")
        assert "电流" in page.locator("#component").inner_text()
        names = ("coenergy-fields.csv", "forward.csv", "reverse.csv", "fine.csv",
                 "native.csv", "native-samples.csv", *files)
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
        ui = dict(passed=not errors and not external, field_states=65, dynamic_states=9,
                  native_states=8,
                  exact_downloads=12, errors=errors, external_requests=external,
                  browser=browser.version)
        browser.close()
    (OUT / "ui-validation.json").write_text(json.dumps(ui), encoding="utf-8")
    print("cogging-ui: "+json.dumps(ui), flush=True)
    assert ui["passed"]


if __name__ == "__main__":
    main()
