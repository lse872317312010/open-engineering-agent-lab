"""Resolve a real compiler image once, export FMI2 ME, retain its provenance."""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/openmodelica"
IMAGE = "openmodelica/openmodelica:v1.25.5-minimal"


def run(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["docker", "pull", IMAGE], check=True)
    info = json.loads(run(["docker", "image", "inspect", IMAGE]))[0]
    digest = next(d for d in info["RepoDigests"] if d.startswith("openmodelica/openmodelica@"))
    base = ["docker", "run", "--rm", "--network=none",
            "-v", str(ROOT)+":/work", "-w", "/work/outputs/openmodelica", digest]
    version = run(base + ["omc", "--version"]).strip()
    assert "1.25.5" in version, version
    (OUT / "compiler-version.txt").write_text(version+"\n")
    (OUT / "compiler-image.json").write_text(json.dumps(
        dict(tag=IMAGE, digest=digest, image_id=info["Id"], version=version), indent=2))
    log = run(base + ["omc", "/work/models/modelica/export.mos"], stderr=subprocess.STDOUT)
    (OUT / "export.log").write_text(log)
    print(log)
    artifact = OUT / "OEALJointExchange.fmu"
    assert artifact.is_file(), "compiler did not export a real FMU; inspect export.log"
    copyright_text = run(base + ["sh", "-c",
        "cat /usr/share/doc/omc/copyright"])
    (OUT / "compiler-package-copyright.txt").write_text(copyright_text)
    shutil.copyfile(ROOT / "models/modelica/OEALJointExchange.mo", OUT / "OEALJointExchange.mo")
    shutil.copyfile(ROOT / "docs/openmodelica-interop-contract.md", OUT / "contract.md")
    print("openmodelica-compiler: "+json.dumps(dict(version=version, digest=digest)))


if __name__ == "__main__":
    main()
