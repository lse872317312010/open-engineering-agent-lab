"""Configurable pinned FMI plant, frozen nominal current PI and outer position PD."""

import math
from dataclasses import replace

import numpy as np

from oeal.backends import fmi_joint

GUID = "{a5505b9e-0ea1-4060-b701-000000000020}"
IDENT = "oeal_servo"
BINARY_SHA256 = "d28f04a0a677fa5ccbe29e0eb4d244ba52b52e11ce22819c4390c77ef728f4d9"
SOURCE_SHA256 = "f22169762b3b0d044b661b0b28877787fb25502508c52e15cfcec8f57cda8e45"
PARAMETERS = ["stator_resistance_ohm", "d_inductance_h", "q_inductance_h",
              "flux_linkage_wb", "pole_pairs", "inertia_kg_m2", "viscous_friction_nms"]
DEFAULTS = dict(zip(PARAMETERS, [.3, .0008, .0008, .03, 7, 5e-5, 1e-5], strict=True))
LOW = [.15, .0004, .0004, .015, 1, 2.5e-5, 0.]
HIGH = [.6, .0016, .0016, .045, 14, 2e-4, 5e-5]
JOINT_COLUMNS = ["time_s", "joint_angle_rad", "joint_speed_rad_s", "reference_rad",
                 "reference_speed_rad_s", "shaft_torque_nm"]


def validate_parameters(p):
    if set(p) != set(PARAMETERS):
        raise ValueError("configurable FMI requires its registered motor parameters")
    if any(not low <= p[name] <= high for name, low, high in zip(
        PARAMETERS, LOW, HIGH, strict=True
    )) or type(p["pole_pairs"]) is not int:
        raise ValueError("FMI motor parameter outside fixed range")


def load_asset(root):
    return fmi_joint.load_asset(
        root, filename="oeal-servo.fmu", binary_path="binaries/linux64/oeal_servo.so",
        binary_sha256=BINARY_SHA256, source_sha256=SOURCE_SHA256, guid=GUID, ident=IDENT,
        port_names=fmi_joint.NAMES+PARAMETERS,
        port_units=fmi_joint.UNITS+["ohm", "H", "H", "Wb", "1", "kg*m^2", "N*m*s"],
    )


def reference(t, s):
    elapsed = t-s["position_start_s"]
    progress = min(1., max(0., elapsed/s["position_ramp_s"]))
    velocity = (s["position_step_rad"]/s["position_ramp_s"]
                if s["position_start_s"] <= t < s["position_start_s"]+s["position_ramp_s"] else 0.)
    return s["position_step_rad"]*progress, velocity


def bounded_voltage(output, s):
    """Keep rounded saturated commands strictly inside the declared circular port."""
    norm = math.hypot(output.vd_v, output.vq_v)
    interior = (s["vdc_v"]/math.sqrt(3))*(1-4e-15)
    if norm > interior:
        return replace(output, vd_v=output.vd_v*interior/norm,
                       vq_v=output.vq_v*interior/norm)
    return output


def control(s, x, tick, state):
    q, v = reference(tick*s["control_period_s"], s)
    torque = s["outer_kp_nm_per_rad"]*(q-x[4])+s["outer_kd_nms_per_rad"]*(v-x[3]/10)
    # The nominal torque constant and all PI/feedforward parameters stay frozen.
    requested = torque/(10*1.5*7*.03)
    return bounded_voltage(fmi_joint.control(
        dict(s, id_reference_a=0., iq_reference_a=requested, step_time_s=0.),
        x, tick, state), s)


def storage(x, p):
    x = np.asarray(x)
    return (.75*(p["d_inductance_h"]*x[:, 0]**2+p["q_inductance_h"]*x[:, 1]**2)
            + .5*p["inertia_kg_m2"]*x[:, 3]**2+.01*x[:, 5]**2
            + 40*(x[:, 2]/10-x[:, 4])**2
            + 60*(x[:, 6]-25)+200*(x[:, 7]-25)+25*(x[:, 8]-25))


def run(s, payload, p):
    validate_parameters(p)
    rows, waves, context = fmi_joint.run(
        s, payload, guid=GUID, ident=IDENT, command=control,
        motor_values=[p[name] for name in PARAMETERS],
    )
    joint = [[row[0], row[5], row[6], *reference(row[0], s), row[13]] for row in rows]
    context.update(physical_parameters=dict(p), nominal_parameters=dict(DEFAULTS))
    return rows, waves, joint, context


def audit(s, signals, context, p):
    validate_parameters(p)
    if (context.get("physical_parameters") != p
            or context.get("nominal_parameters") != DEFAULTS):
        raise ValueError("FMI actual/nominal motor parameter binding mismatch")
    if set(signals) != {"control", "waveforms", "joint"}:
        raise ValueError("servo requires complete joint/control/waveform streams")
    if signals["joint"]["columns"] != JOINT_COLUMNS:
        raise ValueError("FMI joint columns differ from the registered contract")
    metrics, numeric = fmi_joint.audit(
        s, {k: signals[k] for k in ("control", "waveforms")}, context,
        command=control, binary_sha256=BINARY_SHA256, storage=lambda x: storage(x, p),
    )
    control_rows = np.asarray(signals["control"]["samples"])
    joint = np.asarray(signals["joint"]["samples"])
    times = control_rows[:, 0]
    expected_q = s["position_step_rad"]*np.clip(
        (times-s["position_start_s"])/s["position_ramp_s"], 0, 1)
    expected_v = np.where((times >= s["position_start_s"])
                          & (times < s["position_start_s"]+s["position_ramp_s"]),
                          s["position_step_rad"]/s["position_ramp_s"], 0.)
    expected = np.column_stack([times, control_rows[:, 5], control_rows[:, 6],
                                expected_q, expected_v, control_rows[:, 13]])
    if joint.shape != expected.shape or not np.allclose(joint, expected, atol=1e-12, rtol=0):
        raise ValueError("FMI position/state/reference velocity binding mismatch")
    return metrics, numeric
