"""Verify immutable accepted FE-stage evidence; never accept its failed downstream FOC."""
import ast
import hashlib
import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSFER = ROOT / "outputs/p7-femm-transfer"
OUT = ROOT / "outputs/p7-femm"
ORIGIN = "d68e1ae53b4d677e3805f71b088804c73d9fdbc1"
PARAM_SHA = "eaaa797d053991ade614a3fd74195818e21918a1de7ccb54d138f1e5db162d37"
BASE = "https://raw.githubusercontent.com/lse872317312010/open-engineering-agent-lab/"


def producer(source):
    tree = ast.parse(source)
    functions = {"xy", "motor", "gap_samples", "radial_mst", "solve_point", "save_rows",
                 "phase_flux", "characterize", "grid_case"}
    result = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            result[node.name] = ast.dump(node, include_attributes=False)
        if isinstance(node, ast.Assign):
            names = [n.id for n in node.targets if isinstance(n, ast.Name)]
            if any(n in {"GRIDS", "DEPTH_M", "PHASES"} for n in names):
                result["constant:"+",".join(names)] = ast.dump(node, include_attributes=False)
    assert functions <= result.keys()
    return result


def original(path):
    with urllib.request.urlopen(BASE+ORIGIN+"/"+path, timeout=60) as response:
        return response.read().decode("utf-8").replace("\r\n", "\n")



def verify_manifest(folder, manifest):
    verified = set()
    for recorded_name, digest in manifest.items():
        name = recorded_name.replace("\\", "/")
        if not name.startswith("p7-femm/"):
            continue
        relative = Path(name).relative_to("p7-femm")
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder.resolve()):
            raise ValueError("source manifest escaped its artifact directory")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("source artifact manifest mismatch: "+name)
        verified.add(name)
    required = {"p7-femm/"+name for name in
                ("field-validation.json", "parameters.json", "validation.json",
                 "probe-validation.json")}
    if not verified or not required <= verified:
        raise ValueError("source manifest is empty or omits required field metadata")
    return verified


def main():
    manifest_path = TRANSFER / "manifest.json"
    if not manifest_path.exists():
        print("p7-femm-reuse: unavailable; execute a fresh field solve", flush=True)
        return
    manifest = json.loads(manifest_path.read_text())
    verified = verify_manifest(TRANSFER, manifest)
    folders = [f"open24/a{i:02d}" for i in range(24)]
    folders += [f"open48/a{i:02d}" for i in range(48)]
    folders += ["dplus", "dminus", "qplus", "qminus", "virtual-minus", "virtual-plus"]
    folders += [f"phase-{i}" for i in range(3)]
    native = {f"p7-femm/grid{g}/{p}/motor.{ext}"
              for g in range(3) for p in folders for ext in ("fem", "ans")}
    if not native <= verified:
        raise ValueError("manifest does not cover all 486 native motor inputs/solutions")
    field = json.loads((TRANSFER / "field-validation.json").read_text())
    assert field["passed"] is True and all(v is True for v in field["checks"].values())
    assert len(field["grids"]) == 3 and all(g["passed"] is True for g in field["grids"])
    parameter = TRANSFER / "parameters.json"
    assert hashlib.sha256(parameter.read_bytes()).hexdigest() == PARAM_SHA
    payload = json.loads(parameter.read_text())
    assert payload["commit"] == ORIGIN
    failed = json.loads((TRANSFER / "validation.json").read_text())
    assert failed["commit"] == ORIGIN and failed["checks"]["all_grids"] is True
    assert failed["checks"]["foc"] is False
    paths = ("benchmarks/p7_femm_probe.py", "benchmarks/p7_femm_reference.py",
             "benchmarks/p7_femm_sampling.py")
    try:
        previous = original("benchmarks/p7_femm_motor.py")
        current = (ROOT / "benchmarks/p7_femm_motor.py").read_text(encoding="utf-8")
        if producer(previous) != producer(current):
            print("p7-femm-reuse: producer changed; execute a fresh field solve", flush=True)
            return
        for path in paths:
            if original(path) != (ROOT / path).read_text(encoding="utf-8"):
                print("p7-femm-reuse: reference/API changed; fresh field solve", flush=True)
                return
    except (urllib.error.URLError, TimeoutError):
        print("p7-femm-reuse: provenance source unavailable; fresh field solve", flush=True)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    metadata = OUT / "field-source-other"
    metadata.mkdir(exist_ok=True)
    for path in TRANSFER.iterdir():
        if path.name in {"grid0", "grid1", "grid2", "field-validation.json", "parameters.json"}:
            target = OUT / path.name
        elif path.name == "foc":
            target = OUT / "rejected-foc"
        elif path.name == "validation.json":
            target = OUT / "rejected-foc-validation.json"
        else:
            target = metadata / path.name
        if target.exists():
            raise ValueError("refusing to mix source and existing field data")
        shutil.move(str(path), str(target))
    proof = dict(passed=True, accepted_stage="static_field_only", source_commit=ORIGIN,
                 source_run_id=41408065697, source_artifact_id=13125525677,
                 parameter_sha256=PARAM_SHA, verified_manifest_files=len(verified),
                 verified_native_motor_files=len(native),
                 producer_ast_identical=True, references_and_sampling_identical=True,
                 source_foc_accepted=False, downstream_foc_must_run=True)
    (OUT / "field-reuse.json").write_text(json.dumps(proof, indent=2))
    print("p7-femm-reuse: "+json.dumps(proof), flush=True)


if __name__ == "__main__":
    main()
