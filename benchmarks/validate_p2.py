"""Cross-backend IR round trip and endpoint equivalence."""

import copy
import json
from pathlib import Path

import numpy as np

from oeal.experiments import run_experiment
from oeal.ir import canonical, document_hash, validate_document

root = Path(__file__).resolve().parents[1]
spec = json.loads((root / "examples/ir/foc-experiment.json").read_text())
spec["mode"] = "open_loop"
spec["input"] = {"vd_v": 0.0, "vq_v": 5.0, "load_torque_nm": 0.1}
native = run_experiment(spec)
other = copy.deepcopy(spec)
other["backend"] = "pathsim"
pathsim = run_experiment(other)
error = float(np.max(np.abs(
    np.array(native["samples"]) - np.array(pathsim["samples"])
)))
restored = json.loads(canonical(spec))
validate_document(restored)
report = {
    "passed": error < 1e-5 and document_hash(restored) == document_hash(spec),
    "max_endpoint_error": error, "tolerance": 1e-5,
    "native_input": spec, "pathsim_input": other,
    "native_result": native, "pathsim_result": pathsim,
}
output = root / "outputs/p2"
output.mkdir(parents=True, exist_ok=True)
(output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
print("p2.json: " + json.dumps({"passed": report["passed"], "max_error": error}))
if not report["passed"]:
    raise AssertionError("P2 cross-backend equivalence failed")
