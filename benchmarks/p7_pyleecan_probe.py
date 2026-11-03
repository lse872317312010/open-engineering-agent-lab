"""Bounded first-case diagnostic; never counted as the full benchmark."""
import subprocess
import sys

from p7_pyleecan import OUT, ROOT, archive

OUT.mkdir(parents=True, exist_ok=True)
script = (
    "import sys,faulthandler;sys.path.insert(0,'benchmarks');"
    "import p7_pyleecan as n;"
    "faulthandler.dump_traceback_later(30,repeat=True);"
    "n.solve('isolated-first-case',1.);"
    "faulthandler.cancel_dump_traceback_later()"
)
try:
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, check=True, timeout=300)
finally:
    archive()
