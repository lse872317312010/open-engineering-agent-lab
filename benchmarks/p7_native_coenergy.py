"""Read original FEMM solutions and compare magnetic coenergy to stress torque."""
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

import femm
from p7_native_coenergy_ref import compare

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/p7-native-coenergy"
DEEP = "4030532a05a932b3c84f7742218d23130be2f819"
SECOND = "ec41e9b79de7d918c11a04a5c4ae455a7b900938"
FRAME = "541602aad016740d7263493d6062244edfae0923c2b59a1ac349889547c9234f"
EXE = "5e83cf0899cabae2017868ddcce338e3ba4ac25d1bf8e511eac77eda2bc92a21"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle(folder, lane_name, expected_commit, shard):
    manifest = json.loads((folder / "manifest.json").read_text())
    required = {"environment.json", "frame.json", lane_name}
    assert required <= set(manifest)
    for name, digest in manifest.items():
        path = PurePosixPath(name)
        assert not path.is_absolute() and ".." not in path.parts
        assert sha(folder / name) == digest
    assert sha(folder / "frame.json") == FRAME
    environment = json.loads((folder / "environment.json").read_text())
    assert environment["source_commit"] == expected_commit
    assert environment["executable_sha256"] == EXE
    lane = json.loads((folder / lane_name).read_text())
    assert lane["evidence_passed"] and lane["commit"] == expected_commit
    assert lane["shard"] == shard and lane["grid"] == 2.
    assert lane["frame_sha256"] == FRAME
    return lane, manifest


def read_case(folder, lane, manifest, angle):
    selected = [r for r in lane["cases"] if r["angle_deg"] == angle
                and (r["id_a"], r["iq_a"]) == (0, 0)]
    assert len(selected) == 1
    r = selected[0]
    assert r["passed"] and all(r["checks"].values())
    assert r["grid"] == 2. and r["length_m"] == .05 and r["native_depth_m"] == 1.
    assert abs(r["actual_angle_rad"]-(math.pi/8+math.radians(angle))) <= 1e-12
    assert max(abs(v) for v in r["native_currents_a"]) <= 1e-10
    files = r["native_files"]
    assert len(files) == 2
    for name, digest in files.items():
        assert manifest[name] == digest and sha(folder / name) == digest
    fem = next(folder / n for n in files if n.endswith(".fem"))
    ans = next(folder / n for n in files if n.endswith(".ans"))
    femm.opendocument(str(fem))
    try:
        femm.mi_loadsolution()
        info = femm.mo_getprobleminfo()
        assert float(info[1]) == 0 and abs(float(info[2])-1.) <= 1e-12
        currents = [float(femm.mo_getcircuitproperties("Circs"+str(i))[0]) for i in range(3)]
        assert max(abs(v) for v in currents) <= 1e-10
        femm.mo_clearblock()
        femm.mo_groupselectblock()
        block = float(femm.mo_blockintegral(17))
        energy = float(femm.mo_blockintegral(2))
        area = float(femm.mo_blockintegral(5))
        femm.mo_clearblock()
        gap = float(femm.mo_gapintegral("bc_ag2", 2))
        assert all(math.isfinite(v) for v in (block, energy, area, gap))
        assert area > 0 and gap > 0
    finally:
        femm.mo_close()
        femm.mi_close()
    assert all(sha(folder / name) == digest for name, digest in files.items())
    return dict(angle_deg=angle, block_coenergy_j=block*.05, block_energy_j=energy*.05,
                gap_energy_j=gap*.05, area_m2=area, nodes=r["nodes"],
                stress_torque_nm=r["torque_nm"], gap_torque_nm=r["gap_torque_nm"],
                currents_a=currents, fem=str(fem.relative_to(ROOT)),
                ans=str(ans.relative_to(ROOT)), native_files=files)


def main():
    shard = int(sys.argv[1])
    assert shard in range(8)
    exe = Path(os.environ["FEMM_EXE"])
    assert sha(exe) == EXE
    for commit, producer in ((DEEP, "benchmarks/p7_deep_angle_native.py"),
                             (SECOND, "benchmarks/p7_second_angle_native.py")):
        subprocess.run(["git", "fetch", "origin", commit, "--depth=1"], check=True)
        subprocess.run(["git", "diff", "--exit-code", commit, "HEAD", "--",
                        producer, "benchmarks/p7_loaded_solver.py", "benchmarks/p7_pyleecan.py",
                        "benchmarks/assets/pyleecan-spmsm001.json", "src/oeal/transforms.py"],
                       check=True)
    folder_a = ROOT / "outputs/native/deep3"
    folder_b = ROOT / "outputs/native/deep4"
    folder_c = ROOT / "outputs/native/second"
    a, ma = bundle(folder_a, "deep-angle.json", DEEP, shard)
    b, mb = bundle(folder_b, "deep-angle.json", DEEP, shard+8)
    c, mc = bundle(folder_c, "second-angle.json", SECOND, shard)
    center = 2.8125+5.625*shard
    targets = [(folder_a, a, ma, center-1.40625),
               (folder_b, b, mb, center-.703125),
               (folder_c, c, mc, center),
               (folder_b, b, mb, center+.703125),
               (folder_a, a, ma, center+1.40625)]
    femm.openfemm(1)
    try:
        samples = [read_case(*target) for target in targets]
    finally:
        femm.closefemm()
    result = compare([r["block_coenergy_j"] for r in samples],
                     [r["gap_energy_j"] for r in samples],
                     samples[2]["stress_torque_nm"], samples[2]["gap_torque_nm"])
    OUT.mkdir(parents=True, exist_ok=True)
    data = dict(evidence_passed=True, shard=shard, center_deg=center, samples=samples,
                comparison=result, source_commits=[DEEP, SECOND], executable_sha256=EXE,
                commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    (OUT / "native-coenergy.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("native-coenergy: "+json.dumps(data), flush=True)


if __name__ == "__main__":
    main()
