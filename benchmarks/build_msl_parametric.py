"""Export real MSL component network using pinned source and compiler."""

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import build_msl_thermal as thermal_source
from build_openmodelica import IMAGE, run

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/msl-parametric"
LIBRARY = thermal_source.LIBRARY
COMPONENTS = thermal_source.COMPONENTS+[
    "Modelica/Thermal/HeatTransfer/Components/Convection.mo",
    "Modelica/Thermal/HeatTransfer/Components/BodyRadiation.mo",
    "Modelica/Constants.mo",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source_hashes = thermal_source.source()
    source_hashes.update({p: sha(LIBRARY / p) for p in COMPONENTS})
    subprocess.run(["docker", "pull", IMAGE], check=True)
    info = json.loads(run(["docker", "image", "inspect", IMAGE]))[0]
    base = ["docker", "run", "--rm", "--network=none", "-v", str(ROOT)+":/work",
            "-w", "/work/outputs/msl-parametric", IMAGE]
    version = run(base+["omc", "--version"]).strip()
    assert "1.25.5" in version
    try:
        log = run(base+["omc", "/work/models/modelica/export-msl-parametric.mos"],
                  stderr=subprocess.STDOUT)
    finally:
        run(base+["chown", "-R", f"{os.getuid()}:{os.getgid()}", "/work/outputs/msl-parametric"])
    (OUT / "export.log").write_text(log)
    print(log, flush=True)
    archive = OUT / "OEALMSLParametric.fmu"
    assert archive.is_file() and '"4.0.0"' in log
    assert all(n in log for n in ("HeatCapacitor", "ThermalResistor",
                                 "PrescribedHeatFlow", "FixedTemperature",
                                 "Convection", "BodyRadiation"))
    copyright_text = run(base+["cat", "/usr/share/doc/omc/copyright"])
    metadata = dict(msl_version="4.0.0", msl_commit=thermal_source.MSL_COMMIT,
                    component_source_sha256=source_hashes, image=IMAGE,
                    image_id=info["Id"], compiler=version,
                    command=base+["omc", "/work/models/modelica/export-msl-parametric.mos"])
    (OUT / "build-provenance.json").write_text(json.dumps(metadata, indent=2))
    (OUT / "compiler-package-copyright.txt").write_text(copyright_text)
    with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED) as z:
        prefix = "resources/oeal-licenses/"
        z.writestr(prefix+"compiler-package-copyright.txt", copyright_text)
        for path, target in [
            ("LICENSE", "OEAL-MIT.txt"), ("research/licenses/MSL-4.0.0.txt", "MSL-BSD3.txt"),
            ("research/licenses/OpenModelica-v1.25.5.txt", "OSMC-License.txt"),
            ("research/licenses/OSMC-USAGE-MODE.txt", "OSMC-USAGE-MODE.txt"),
            ("docs/msl-rc-contract.md", "contract.md"),
            ("models/modelica/OEALMSLParametric.mo", "OEALMSLParametric.mo"),
        ]:
            z.write(ROOT / path, prefix+target)
        z.write(OUT / "build-provenance.json", prefix+"build-provenance.json")
        for path in COMPONENTS:
            z.write(LIBRARY / path, "resources/msl-used/"+path)
    shutil.copyfile(ROOT / "docs/msl-rc-contract.md", OUT / "contract.md")
    shutil.copyfile(ROOT / "models/modelica/OEALMSLParametric.mo", OUT / "OEALMSLParametric.mo")
    print("msl-parametric-build: "+json.dumps(metadata), flush=True)


if __name__ == "__main__":
    main()
