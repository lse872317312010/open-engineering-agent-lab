"""Export real MSL component network using pinned source and compiler."""

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from build_openmodelica import IMAGE, run

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-thermal"
LIBRARY = ROOT / "outputs/msl-source"
MSL_COMMIT = "6626538a236a34a390655b55d5e8c906bfe31772"
COMPONENTS = [
    "Modelica/Thermal/HeatTransfer/Components/HeatCapacitor.mo",
    "Modelica/Thermal/HeatTransfer/Components/ThermalResistor.mo",
    "Modelica/Thermal/HeatTransfer/Sources/PrescribedHeatFlow.mo",
    "Modelica/Thermal/HeatTransfer/Sources/FixedTemperature.mo",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source():
    if not (LIBRARY / ".git").is_dir():
        LIBRARY.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(LIBRARY)], check=True)
        subprocess.run(["git", "-C", str(LIBRARY), "remote", "add", "origin",
                        "https://github.com/modelica/ModelicaStandardLibrary.git"], check=True)
        subprocess.run(["git", "-C", str(LIBRARY), "fetch", "--depth=1", "origin", MSL_COMMIT],
                       check=True)
        subprocess.run(["git", "-C", str(LIBRARY), "checkout", "--detach", "FETCH_HEAD"],
                       check=True)
    commit = run(["git", "-C", str(LIBRARY), "rev-parse", "HEAD"]).strip()
    assert commit == MSL_COMMIT
    assert not run(["git", "-C", str(LIBRARY), "status", "--porcelain"]).strip()
    assert (LIBRARY / "LICENSE").read_bytes() == (
        ROOT / "research/licenses/MSL-4.0.0.txt").read_bytes()
    return {p: sha(LIBRARY / p) for p in COMPONENTS+[
        "LICENSE", "Modelica/package.mo", "ModelicaServices/package.mo", "Complex.mo"]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source_hashes = source()
    subprocess.run(["docker", "pull", IMAGE], check=True)
    info = json.loads(run(["docker", "image", "inspect", IMAGE]))[0]
    base = ["docker", "run", "--rm", "--network=none", "-v", str(ROOT)+":/work",
            "-w", "/work/outputs/msl-thermal", IMAGE]
    version = run(base+["omc", "--version"]).strip()
    assert "1.25.5" in version
    try:
        log = run(base+["omc", "/work/models/modelica/export-msl-thermal.mos"],
                  stderr=subprocess.STDOUT)
    finally:
        run(base+["chown", "-R", f"{os.getuid()}:{os.getgid()}", "/work/outputs/msl-thermal"])
    (OUT / "export.log").write_text(log)
    print(log, flush=True)
    archive = OUT / "OEALMSLThermal.fmu"
    assert archive.is_file() and '"4.0.0"' in log
    assert all(n in log for n in ("HeatCapacitor", "ThermalResistor",
                                 "PrescribedHeatFlow", "FixedTemperature"))
    copyright_text = run(base+["cat", "/usr/share/doc/omc/copyright"])
    metadata = dict(msl_version="4.0.0", msl_commit=MSL_COMMIT,
                    component_source_sha256=source_hashes, image=IMAGE,
                    image_id=info["Id"], compiler=version,
                    command=base+["omc", "/work/models/modelica/export-msl-thermal.mos"])
    (OUT / "build-provenance.json").write_text(json.dumps(metadata, indent=2))
    (OUT / "compiler-package-copyright.txt").write_text(copyright_text)
    with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as z:
        prefix = "resources/oeal-licenses/"
        z.writestr(prefix+"compiler-package-copyright.txt", copyright_text)
        for path, target in [
            ("LICENSE", "OEAL-MIT.txt"), ("research/licenses/MSL-4.0.0.txt", "MSL-BSD3.txt"),
            ("research/licenses/OpenModelica-v1.25.5.txt", "OSMC-License.txt"),
            ("research/licenses/OSMC-USAGE-MODE.txt", "OSMC-USAGE-MODE.txt"),
            ("docs/msl-thermal-contract.md", "contract.md"),
            ("models/modelica/OEALMSLThermal.mo", "OEALMSLThermal.mo"),
        ]:
            z.write(ROOT / path, prefix+target)
        z.write(OUT / "build-provenance.json", prefix+"build-provenance.json")
        for path in COMPONENTS:
            z.write(LIBRARY / path, "resources/msl-used/"+path)
    shutil.copyfile(ROOT / "docs/msl-thermal-contract.md", OUT / "contract.md")
    shutil.copyfile(ROOT / "models/modelica/OEALMSLThermal.mo", OUT / "OEALMSLThermal.mo")
    print("msl-build: "+json.dumps(metadata), flush=True)


if __name__ == "__main__":
    main()
