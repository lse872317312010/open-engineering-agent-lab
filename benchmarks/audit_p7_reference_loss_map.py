"""Post-result diagnostic checks; these do not override the original acceptance gate."""
import json
from pathlib import Path

import numpy as np
from p7_cogging_simulation import OFFSET
from p7_reference_loss_map import OUT, checked_parent
from p7_reference_ramp import reference_case, reference_values
from p7_stator_fast_rom import check_files
from p7_winding_heat import ROOT, digest

from oeal.reference_loss_map import ReferenceCopperLossMap
from oeal.transforms import park


def audit():
    checked_parent()
    frozen = json.loads((OUT / "frozen.json").read_text(encoding="utf-8"))
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    check_files(ROOT, frozen["source_sha256"])
    check_files(OUT, frozen["frozen_sha256"])
    check_files(OUT, manifest)
    assert digest(OUT / "frozen.json") == summary["frozen_sha256"]
    checked = 0
    for path in OUT.glob("*.npz"):
        with np.load(path, allow_pickle=False) as packet:
            assert all(np.isfinite(packet[key]).all() for key in packet.files), path.name
        checked += 1
    raw = []
    for case in summary["dynamics"]:
        with np.load(OUT / (case["name"]+".npz"), allow_pickle=False) as packet:
            control, thermal = packet["control"], packet["thermal"]
            commands, references = packet["stationary_commands"], packet["reference_commands"]
            np.testing.assert_allclose(control[50::50, 8], thermal[1:, 9], atol=1e-14, rtol=0)
            np.testing.assert_allclose(np.diff(thermal[:, 9]), thermal[1:, 7], atol=1e-14, rtol=0)
            np.testing.assert_allclose(control[:-1, 11],
                thermal[np.arange(len(commands))//50, 6], atol=1e-14, rtol=0)
            np.testing.assert_allclose(control[:-1, 12], references, atol=0, rtol=0)
            np.testing.assert_allclose(references,
                case["direction"]*reference_values(np.arange(len(commands)), case["profile"]),
                atol=1e-14, rtol=0)
            padded = np.vstack((commands, commands[-1]))
            voltage = np.array([park(*v, OFFSET+4*theta)
                                for v, theta in zip(padded, control[:, 1], strict=True)])
            np.testing.assert_allclose(voltage, control[:, 5:7], atol=4e-12, rtol=0)
            error = abs(thermal[1:, 8]/thermal[1:, 7]-1)
            score = thermal[1:, 0] > .2
            ready = thermal[1:, 12].astype(bool)
            maximum = float(np.max(error[score & ready]))
            np.testing.assert_allclose(maximum, case["max_window_relative_error"], atol=1e-14)
            assert int(np.sum(score & ~ready)) == case["unready_scored_windows"]
            raw.append(dict(name=case["name"], windows_above_five_percent=int(
                np.sum(score & ready & (error > .05))), max_ready_window_error=maximum))
    model = ReferenceCopperLossMap.from_npz(OUT / "inference.npz")
    fine, arrays = reference_case(model, -1., 100., dt=2.5e-6, replay=True)
    with np.load(OUT / "smooth--1.npz", allow_pickle=False) as packet:
        current = float(np.max(abs(packet["control"][:, 3:5]-arrays["control"][:, 3:5])))
        copper = abs(float(packet["control"][-1, 8]/arrays["control"][-1, 8]-1))
    destination = ROOT / "outputs/p7-reference-loss-map-diagnostics"
    destination.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(destination / "reverse-fine.npz", **arrays)
    passed = bool(current <= 1e-5 and copper <= 1e-5 and fine["dop_current_error_a"] <= 1e-5
                  and max(fine["dop_energy_error_j"]) <= 1e-7)
    result = dict(audit_passed=passed, transient_gate_passed=summary["passed"],
        summary_sha256=digest(OUT / "summary.json"), audit_source_sha256=digest(Path(__file__)),
        manifest_files=len(manifest), finite_npz_files=checked, raw_window_checks=raw,
        fine=fine, max_current_difference_a=current, relative_copper_difference=copper)
    (destination / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("reference-loss-map-audit:", json.dumps(result), flush=True)
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    audit()
