"""Independent configurable-boundary hand calculations, committed before adapter changes."""
import math
import numpy as np

SIGMA = 2*math.pi**5*(1.380649e-23)**4/(15*(6.62607015e-34)**3*299792458**2)


def boundary(temperatures_c, ambient_c, gc, area):
    t = np.asarray(temperatures_c, dtype=float)
    return np.array([(t[2]-ambient_c)/2, gc*(t[5]-ambient_c),
                     area*SIGMA*((t[5]+273.15)**4-(ambient_c+273.15)**4)])


def initial_storage(temperatures_c):
    return float((np.asarray(temperatures_c)-25) @ [60,70,200,.5,25,100])
