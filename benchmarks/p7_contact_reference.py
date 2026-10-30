"""Independent closed-form slab with an areal contact resistance; SI units."""
import numpy as np

LENGTH = .1
SPLIT = .04
HEIGHT = .1
THICKNESS = .01
BASE = dict(k1=2., k2=.2, h=10., left_c=50., ambient_c=25., s1=1000., s2=2000.)
CASES = [dict(BASE, id=f"rc-{r:g}", rc=r) for r in (.01, .1, 1.)]
CASES += [dict(BASE, id="hot-ambient", rc=.1, left_c=25., ambient_c=60.)]
PATCH = dict(BASE, id="zero-source", rc=.1, s1=0., s2=0.)


def constants(c):
    b = LENGTH-SPLIT
    resistance = SPLIT/c["k1"]+c["rc"]+b/c["k2"]
    offset = (c["s1"]*SPLIT**2/(2*c["k1"])+c["rc"]*c["s1"]*SPLIT
              +c["s1"]*SPLIT*b/c["k2"]+c["s2"]*b*b/(2*c["k2"]))
    total = c["s1"]*SPLIT+c["s2"]*b
    q0 = (c["h"]*(c["left_c"]-c["ambient_c"]-offset)-total)/(1+c["h"]*resistance)
    ti_left = c["left_c"]-(q0*SPLIT+c["s1"]*SPLIT**2/2)/c["k1"]
    qi = q0+c["s1"]*SPLIT
    return q0, ti_left, ti_left-c["rc"]*qi


def temperature(x, c, region):
    x = np.asarray(x)
    q0, tl, tr = constants(c)
    if region == 10:
        return c["left_c"]-(q0*x+c["s1"]*x*x/2)/c["k1"]
    if region != 20:
        raise ValueError("unknown material region")
    z = x-SPLIT
    return tr-((q0+c["s1"]*SPLIT)*z+c["s2"]*z*z/2)/c["k2"]


def powers(c):
    q0, tl, tr = constants(c)
    qi = q0+c["s1"]*SPLIT
    scale = HEIGHT*THICKNESS
    return dict(source_w=(c["s1"]*SPLIT+c["s2"]*(LENGTH-SPLIT))*scale,
                left_out_w=-q0*scale,
                right_out_w=(qi+c["s2"]*(LENGTH-SPLIT))*scale,
                interface_right_w=qi*scale, jump_k=tl-tr)
