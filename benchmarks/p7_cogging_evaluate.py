"""Freeze Fourier coenergy from audited FE points and test unseen angles/currents."""
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from p7_cogging_model import CoggingMotor, FourierSeries

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "outputs/cogging-source"
OUT = ROOT / "outputs/p7-cogging-report"
HASHES = {
    "deep.json": "b75d51fef81bbe42208961e5607c5a16ca6dd6cc9f4c7fa25dbba55c73cf6128",
    "fields.json": "ecfe1e9c2235811dfbe28967bc4226da7e90fb06f7ac2a8fa9f8e0ab615fae6f",
    "model.json": "dc8c5ca77d55c7fe876d7c18da1ad897896c9e0289b5d940417984fec1a6068e",
    "ui-validation.json": "df1b2efd805ff39bc11eb80481c75ff072e81f55392a889a932a915b933912f8",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, expected in HASHES.items():
        assert hashlib.sha256((INPUT / name).read_bytes()).hexdigest() == expected
    deep = json.loads((INPUT / "deep.json").read_text(encoding="utf-8"))
    fields = json.loads((INPUT / "fields.json").read_text(encoding="utf-8"))
    source_ui = json.loads((INPUT / "ui-validation.json").read_text(encoding="utf-8"))
    parameters = json.loads((INPUT / "model.json").read_text(encoding="utf-8"))
    assert deep["evidence_passed"] and len(deep["rows"]) == 130 and source_ui["passed"]
    assert fields["evidence_passed"] and fields["report_commit"] == (
        "a6f4db38df8c24c5f75eb1a1a8ad007925efbc20")
    zero, loaded = deep["rows"][::2], deep["rows"][1::2]
    assert len(zero) == len(loaded) == 65
    for i, (a, b) in enumerate(zip(zero, loaded, strict=True)):
        assert a["angle_deg"] == b["angle_deg"] == .703125*i
        assert (a["id_a"], a["iq_a"]) == (0, 0)
        assert (b["id_a"], b["iq_a"]) == (0, 2)
    training = zero[0:64:4]
    psi = FourierSeries.fit([r["actual_wb"] for r in training])
    torque_mean = float(np.mean([r["fe_torque_nm"] for r in training]))
    cog = FourierSeries.fit([[r["fe_torque_nm"]] for r in training], zero_mean=True)
    motor = CoggingMotor(psi, cog, parameters["inductance_h"])
    frozen = dict(psi_a=psi.a.tolist(), psi_b=psi.b.tolist(), cog_a=cog.a.tolist(),
                  cog_b=cog.b.tolist(), torque_mean_removed_nm=torque_mean,
                  inductance_h=motor.inductance.tolist(), period_rad=math.pi/4,
                  training_indices=list(range(0, 64, 4)), source_sha256=HASHES["deep.json"])
    model_bytes = (json.dumps(frozen, sort_keys=True, separators=(",", ":"))+"\n").encode()
    (OUT / "coenergy-model.json").write_bytes(model_bytes)
    model_sha = hashlib.sha256(model_bytes).hexdigest()
    rows = []
    for i, (z, q) in enumerate(zip(zero, loaded, strict=True)):
        angle = math.radians(z["angle_deg"])
        predicted_psi = psi.value(angle)
        predicted_cog = float(cog.value(angle)[0])
        loaded_prediction, _, increment = motor.torque(angle, [0, 2])
        role = "endpoint" if i == 64 else "training" if i % 4 == 0 else "holdout"
        flux_error = float(np.linalg.norm(predicted_psi-z["actual_wb"])/.05)
        zero_error = abs(predicted_cog-z["fe_torque_nm"])
        loaded_error = abs(loaded_prediction-q["fe_torque_nm"])
        rows.append(dict(index=i, angle_deg=z["angle_deg"], role=role,
                         actual_flux_wb=z["actual_wb"], predicted_flux_wb=predicted_psi.tolist(),
                         flux_error=flux_error, zero_fe_nm=z["fe_torque_nm"],
                         cog_nm=predicted_cog, zero_torque_error_nm=zero_error,
                         coenergy_j=float(cog.integral(angle)[0]), loaded_fe_nm=q["fe_torque_nm"],
                         loaded_predicted_nm=loaded_prediction, increment_nm=increment,
                         loaded_error_nm=loaded_error,
                         zero_supported=flux_error <= .02 and zero_error <= .10,
                         loaded_supported=loaded_error <= .15,
                         currents_a=z["currents_a"], field=z["field"], phi_rad=z["phi_rad"],
                         actual_angle_rad=z["actual_angle_rad"], commit=z["commit"],
                         origin=z["origin"]))
    holdout = [r for r in rows if r["role"] == "holdout"]
    assert len(training) == 16 and len(holdout) == 48 and len(rows) == 65
    checks = dict(mean=abs(torque_mean) <= .03,
                  holdout_flux=all(r["flux_error"] <= .02 for r in holdout),
                  holdout_zero_torque=all(r["zero_torque_error_nm"] <= .10 for r in holdout),
                  loaded=all(r["loaded_supported"] for r in rows))
    data = dict(evidence_passed=True, model_supported=all(checks.values()), checks=checks,
                rows=rows, geometry=fields["geometry"], source_run=42004300771,
                source_sha256=HASHES, model_sha256=model_sha, torque_mean_removed_nm=torque_mean,
                zero_endpoint_torque_diff_nm=zero[-1]["fe_torque_nm"]-zero[0]["fe_torque_nm"],
                endpoint_flux_diff_wb=math.dist(zero[-1]["actual_wb"], zero[0]["actual_wb"]),
                max_holdout_flux=max(r["flux_error"] for r in holdout),
                max_holdout_torque_nm=max(r["zero_torque_error_nm"] for r in holdout),
                max_loaded_torque_nm=max(r["loaded_error_nm"] for r in rows),
                failed_holdout=[r["index"] for r in holdout if not r["zero_supported"]],
                failed_loaded=[r["index"] for r in rows if not r["loaded_supported"]])
    (OUT / "fields.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    with (OUT / "coenergy-fields.csv").open("w", newline="", encoding="utf-8") as fp:
        keys = ["angle_deg", "role", "flux_error", "zero_fe_nm", "cog_nm", "coenergy_j",
                "zero_torque_error_nm", "loaded_fe_nm", "loaded_predicted_nm", "increment_nm",
                "loaded_error_nm", "zero_supported", "loaded_supported", "commit", "origin"]
        writer = csv.writer(fp)
        writer.writerow(keys+["actual_d_wb", "actual_q_wb", "predicted_d_wb", "predicted_q_wb"])
        for r in rows:
            writer.writerow([r[k] for k in keys]+r["actual_flux_wb"]+r["predicted_flux_wb"])
    print("cogging-field-summary: "+json.dumps({k: v for k, v in data.items()
          if k not in {"rows", "geometry"}}), flush=True)


if __name__ == "__main__":
    main()
