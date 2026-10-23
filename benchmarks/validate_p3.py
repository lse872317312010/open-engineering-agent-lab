"""Repeat the fixed-goal proposal/failure/repair tool trace twice."""

import json
from pathlib import Path

from oeal.agent_tools import run_design_iteration
from oeal.ir import document_hash

root = Path(__file__).resolve().parents[1]
goal = json.loads((root / "examples/ir/foc-experiment.json").read_text())
output = root / "outputs/p3"
first = run_design_iteration(goal, output / "ledger")
second = run_design_iteration(goal, output / "ledger")
passed = (
    first["passed"] and not first["trace"][0]["verification"]["passed"]
    and document_hash(first) == document_hash(second)
)
report = {"passed": passed, "repeat_sha256": document_hash(first), "iteration": first}
(output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
print("p3.json: " + json.dumps(report, allow_nan=False))
if not passed:
    raise AssertionError("P3 fixed-goal repair/repeatability failed")
