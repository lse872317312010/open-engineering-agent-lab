"""Pinned joint FMI plant and a sampled external current-controller host."""

import hashlib
import io
import math
import platform
import tempfile
import zipfile
from pathlib import Path
from xml.etree.ElementTree import fromstring

import numpy as np

from oeal.current_control import CurrentPIParameters, CurrentPIState, current_control_step

GUID = "{a5505b9e-0ea1-4060-b701-000000000018}"
IDENT = "oeal_joint"
BINARY_SHA256 = "4359d05cc9f395f25b204dfada7f90423f655882a047ecae59168903f893562b"
SOURCE_SHA256 = "722bd72853cf8a63422f6b0e51ebf525b472a5a8927813f0a6c362d17c2e813f"
BINARY = "binaries/linux64/oeal_joint.so"
NAMES = ["id_a", "iq_a", "motor_angle_rad", "motor_speed_rad_s",
         "load_angle_rad", "load_speed_rad_s", "winding_c", "case_c", "board_c",
         "input_energy_j", "load_work_j", "ambient_heat_j",
         "vd_v", "vq_v", "load_nm", "board_w", "internal_step_s", "shaft_nm"]
UNITS = ["A", "A", "rad", "rad/s", "rad", "rad/s", "degC", "degC", "degC",
         "J", "J", "J", "V", "V", "N*m", "W", "s", "N*m"]
WAVE_COLUMNS = ["time_s", *NAMES[:12], "shaft_torque_nm"]
CONTROL_COLUMNS = [*WAVE_COLUMNS, "vd_v", "vq_v", "load_nm", "board_power_w",
                   "id_reference_a", "iq_reference_a", "voltage_limited", "current_limited"]


def load_asset(root, *, filename="oeal-joint.fmu", binary_path=BINARY,
               binary_sha256=BINARY_SHA256, source_sha256=SOURCE_SHA256,
               guid=GUID, ident=IDENT, port_names=NAMES, port_units=UNITS):
    if root is None:
        raise ValueError("FMI profile needs the trusted host's --assets-root")
    base = Path(root).resolve()
    path = (base / filename).resolve()
    if not path.is_relative_to(base):
        raise ValueError("FMI asset escapes trusted root")
    if path.stat().st_size > 4_000_000:
        raise ValueError("FMI package exceeds size limit")
    raw = path.read_bytes()
    if len(raw) > 4_000_000:
        raise ValueError("FMI package exceeds size limit")
    allowed = {"modelDescription.xml", binary_path, "resources/joint.c", "resources/contract.md",
               "resources/LICENSE", "resources/THIRD_PARTY.txt"}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != allowed:
            raise ValueError("FMI package contains missing, duplicate or unregistered entries")
        if sum(x.file_size for x in archive.infolist()) > 4_000_000:
            raise ValueError("FMI inflated size limit")
        xml = archive.read("modelDescription.xml")
        if len(xml) > 65536 or b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise ValueError("FMI descriptor outside fixed contract")
        binary = archive.read(binary_path)
        source = archive.read("resources/joint.c")
    if hashlib.sha256(binary).hexdigest() != binary_sha256:
        raise ValueError("pinned FMI binary hash mismatch")
    if hashlib.sha256(source).hexdigest() != source_sha256:
        raise ValueError("pinned FMI source hash mismatch")
    description = fromstring(xml)
    cs = description.find("CoSimulation")
    if (description.tag != "fmiModelDescription" or description.get("fmiVersion") != "2.0"
            or description.get("guid") != guid or cs is None
            or cs.get("modelIdentifier") != ident or description.find("ModelExchange") is not None):
        raise ValueError("FMI type/GUID/identifier mismatch")
    variables = description.findall("./ModelVariables/ScalarVariable")
    if len(variables) != len(port_names):
        raise ValueError("FMI port count mismatch")
    for index, node in enumerate(variables):
        causality = "output" if index < 12 or index == 17 else (
            "parameter" if index == 16 or index >= 18 else "input")
        real = node.find("Real")
        if (node.get("name") != port_names[index] or node.get("valueReference") != str(index)
                or node.get("causality") != causality or real is None
                or real.get("unit") != port_units[index]):
            raise ValueError("FMI port reference/unit/causality mismatch")
    return dict(xml=xml, binary=binary, binary_path=binary_path,
                hashes=dict(binary_sha256=binary_sha256, xml_sha256=hashlib.sha256(xml).hexdigest(),
                            archive_sha256=hashlib.sha256(raw).hexdigest()))


def subdivisions(settings):
    count = math.ceil(settings["control_period_s"]/settings["integration_step_s"])
    step = settings["control_period_s"]/count
    calls = 5*count*math.ceil(step/settings["integration_step_s"])
    return count, step, calls


def pi_parameters(s):
    return CurrentPIParameters(.0008*s["bandwidth_per_s"], .3*s["bandwidth_per_s"],
                               .0008*s["bandwidth_per_s"], .3*s["bandwidth_per_s"],
                               s["vdc_v"]/math.sqrt(3), s["current_limit_a"],
                               s["tracking_rate_per_s"])


def control(s, x, tick, state):
    active = tick >= round(s["step_time_s"]/s["control_period_s"])
    return current_control_step(
        pi_parameters(s), state,
        reference_d_a=s["id_reference_a"] if active else 0.,
        reference_q_a=s["iq_reference_a"] if active else 0.,
        measured_d_a=x[0], measured_q_a=x[1], period_s=s["control_period_s"],
        feedforward_d_v=-7*x[3]*.0008*x[1],
        feedforward_q_v=7*x[3]*(.0008*x[0]+.03),
    )


def torque(x):
    return 80*(x[2]/10-x[4])+.15*(x[3]/10-x[5])


def run(s, payload, *, guid=GUID, ident=IDENT, command=control, motor_values=None):
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise ValueError("pinned FMI binary supports Linux x86_64 only")
    from fmpy import read_model_description
    from fmpy.fmi2 import FMU2Slave

    ticks = round(s["duration_s"]/s["control_period_s"])
    count, dt, calls = subdivisions(s)
    rows, waves = [], []
    with tempfile.TemporaryDirectory(prefix="oeal-fmi-") as directory:
        root = Path(directory)
        binary = root / payload.get("binary_path", BINARY)
        binary.parent.mkdir(parents=True)
        binary.write_bytes(payload["binary"])
        (root / "modelDescription.xml").write_bytes(payload["xml"])
        (root / "resources").mkdir()
        read_model_description(directory, validate=True)
        model = FMU2Slave(guid=guid, unzipDirectory=directory, modelIdentifier=ident,
                         instanceName="oeal-host")
        model.instantiate()
        try:
            model.setupExperiment(startTime=0., stopTime=s["duration_s"])
            model.enterInitializationMode()
            model.setReal([16], [s["integration_step_s"]])
            if motor_values is not None:
                model.setReal(list(range(18, 25)), motor_values)
                if model.getReal(list(range(18, 25))) != list(motor_values):
                    raise ValueError("FMI physical parameters were not applied")
            model.exitInitializationMode()
            x = model.getReal(list(range(12)))
            waves.append([0., *x, torque(x)])
            state, pending = CurrentPIState(), (0., 0.)
            extra = None
            for tick in range(ticks):
                t = tick*s["control_period_s"]
                output = command(s, x, tick, state)
                state = output.next_state
                applied = pending if s["delay_samples"] else (output.vd_v, output.vq_v)
                pending = (output.vd_v, output.vq_v)
                extra = [*applied, s.get("load_nm", 0.), s.get("board_power_w", 0.),
                         output.reference_d_a, output.reference_q_a,
                         float(output.voltage_limited), float(output.current_reference_limited)]
                rows.append([t, *x, torque(x), *extra])
                model.setReal([12, 13, 14, 15], extra[:4])
                for sub in range(count):
                    model.doStep(t+sub*dt, dt)
                    x = model.getReal(list(range(12)))
                    waves.append([t+(sub+1)*dt, *x, torque(x)])
            rows.append([s["duration_s"], *x, torque(x), *extra])
            model.terminate()
        finally:
            model.freeInstance()
    return rows, waves, dict(fmi_asset_hashes=payload["hashes"],
                             solver_evaluations=ticks*calls,
                             hold_frame="rotating_dq", fmi_version="2.0",
                             physical_parameters="joint-fmi-contract-v1")


def audit(s, signals, context, *, command=control, binary_sha256=BINARY_SHA256,
          storage=None):
    """Rebuild commands, complete clocks and all-domain storage from physical states."""
    if context.get("fmi_asset_hashes", {}).get("binary_sha256") != binary_sha256:
        raise ValueError("FMI attestation differs from the fixed binary")
    if context.get("hold_frame") != "rotating_dq":
        raise ValueError("FMI hold frame mismatch")
    if set(signals) != {"control", "waveforms"}:
        raise ValueError("FMI requires complete registered control and waveforms")
    if (signals["control"]["columns"] != CONTROL_COLUMNS
            or signals["waveforms"]["columns"] != WAVE_COLUMNS):
        raise ValueError("FMI columns differ from registered contract")
    rows = np.asarray(signals["control"]["samples"])
    waves = np.asarray(signals["waveforms"]["samples"])
    ticks = round(s["duration_s"]/s["control_period_s"])
    count, dt, calls = subdivisions(s)
    if len(rows) != ticks+1 or len(waves) != ticks*count+1:
        raise ValueError("FMI missing clock endpoints")
    if (not np.allclose(rows[:, 0], np.arange(ticks+1)*s["control_period_s"], atol=1e-12,
                        rtol=0)
            or not np.allclose(waves[:, 0], np.arange(ticks*count+1)*dt,
                               atol=1e-12, rtol=0)):
        raise ValueError("FMI waveform/control clock mismatch")
    if not np.allclose(rows[:, :14], waves[::count], atol=1e-12, rtol=0):
        raise ValueError("FMI control/state binding mismatch")
    expected_initial = np.array([0.]*6+[25.]*3+[0.]*3)
    if not np.array_equal(waves[0, 1:13], expected_initial):
        raise ValueError("FMI initial state differs from reset contract")
    if context.get("solver_evaluations") != ticks*calls:
        raise ValueError("FMI solver budget record mismatch")
    state, pending = CurrentPIState(), (0., 0.)
    for tick, row in enumerate(rows[:-1]):
        output = command(s, row[1:13], tick, state)
        state = output.next_state
        applied = pending if s["delay_samples"] else (output.vd_v, output.vq_v)
        pending = (output.vd_v, output.vq_v)
        extra = [*applied, s.get("load_nm", 0.), s.get("board_power_w", 0.),
                 output.reference_d_a, output.reference_q_a, float(output.voltage_limited),
                 float(output.current_reference_limited)]
        if not np.allclose(row[14:], extra, atol=1e-12, rtol=0):
            raise ValueError("FMI protected reference/command/hold mismatch")
    if not np.array_equal(rows[-1, 14:], rows[-2, 14:]):
        raise ValueError("FMI endpoint must repeat the previous hold")
    x = waves[:, 1:13]
    shaft = 80*(x[:, 2]/10-x[:, 4])+.15*(x[:, 3]/10-x[:, 5])
    if not np.allclose(shaft, waves[:, 13], atol=1e-12, rtol=0):
        raise ValueError("FMI torque/state mismatch")
    energy = (.0006*(x[:, 0]**2+x[:, 1]**2)+.000025*x[:, 3]**2+.01*x[:, 5]**2
              + 40*(x[:, 2]/10-x[:, 4])**2
              + 60*(x[:, 6]-25)+200*(x[:, 7]-25)+25*(x[:, 8]-25))
    if storage is not None:
        energy = storage(x)
    residual = energy-energy[0]-x[:, 9]+x[:, 10]+x[:, 11]
    metrics = dict(energy_balance_abs_j=float(np.max(np.abs(residual))),
                   shaft_torque_peak_nm=float(np.max(np.abs(shaft))),
                   current_peak_a=float(np.max(np.hypot(x[:, 0], x[:, 1]))))
    finite = bool(np.all(np.isfinite(rows)) and np.all(np.isfinite(waves)))
    return metrics, bool(finite and metrics["energy_balance_abs_j"] <= 2e-6)
