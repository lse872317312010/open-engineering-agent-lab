"""Explicit-mode native FEMM sampling through the documented ActiveX dofile expression."""
from pathlib import Path

import femm
import numpy as np

SCRATCH = Path(__file__).resolve().parents[1] / "outputs/p7-femm/sampling"


def sample_native_b(count, radius_m, mode="on"):
    if (not isinstance(count, int) or not 1 <= count <= 12000 or mode not in {"on", "off"}
            or not np.isfinite(radius_m) or radius_m <= 0):
        raise ValueError("invalid trusted field-sampling request")
    phi = np.arange(count)*2*np.pi/count
    xs, ys = radius_m*1000*np.cos(phi), radius_m*1000*np.sin(phi)
    script = "mo_smooth("+femm.quote(mode)+");"
    script += 'xs={'+','.join(femm.num(v) for v in xs)+'};'
    script += 'ys={'+','.join(femm.num(v) for v in ys)+'};'
    script += ('s="" for k=1,'+str(count)+' do '
               'local a,bx,by=mo_getpointvalues(xs[k],ys[k]) '
               's=s..format("%.17g,%.17g,",bx,by) end return s')
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "query.lua"
    path.write_text(script, encoding="ascii", newline="\n")
    response = femm.HandleToFEMM.call2femm("dofile("+femm.quote(path.as_posix())+")")
    if response.startswith("error"):
        raise RuntimeError(response)
    values = np.fromstring(response.strip().rstrip(","), sep=",").reshape(count, 2)
    if not np.all(np.isfinite(values)):
        raise ValueError("nonfinite native FEMM field")
    return values
