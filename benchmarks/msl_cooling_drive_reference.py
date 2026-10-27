"""Independent nonlinear cooling coupling reference, frozen before implementation."""
import numpy as np
from msl_cooling_reference import SIGMA
from msl_thermal_reference import CAPACITY, EDGES

BRANCHES = ("case_out_j", "convection_out_j", "radiation_out_j")
BASE = dict(energy_consistent=True, duration_s=.1, period_s=50e-6, bus_v=48.,
            step_time_s=.005, iq_reference_a=5., current_limit_a=6.,
            load_nm=1.5, pwm=False, delay=False, thermal_feedback=True,
            bandwidth_per_s=1000., tracking_rate_per_s=1000., rtol=1e-8,
            max_step_s=20e-6, seed=20261027)
CASES = [
    ("radiation-feedback", {}, .02, False),
    ("linear-limit", {}, 0., False),
    ("radiation-frozen", dict(thermal_feedback=False), .02, False),
    ("fan-varying", {}, .02, True),
    ("radiation-fine", dict(max_step_s=10e-6), .02, False),
    ("pwm-feedback", dict(duration_s=.02, pwm=True, delay=True,
                          deadtime_s=1e-6, device_drop_v=.4, max_step_s=5e-6), .02, False),
    ("regeneration", dict(duration_s=.04, iq_reference_a=-2., load_nm=-2.,
                          max_step_s=10e-6), .02, False),
]


def gc_at(t, varying):
    # Smooth prescribed input, not fan speed or a protection event.
    return 1/3 + .25*np.sin(2*np.pi*t/.1) if varying else 1/3


def rates(temperatures, heat, gc, area):
    temp = np.atleast_2d(temperatures)
    net = np.atleast_2d(heat).copy()
    for a, b, r in EDGES:
        q = (temp[:, a]-temp[:, b])/r
        net[:, a] -= q
        net[:, b] += q
    branch = np.column_stack([
        (temp[:, 2]-25)/2,
        np.asarray(gc)*(temp[:, 5]-25),
        area*SIGMA*((temp[:, 5]+273.15)**4-298.15**4),
    ])
    net[:, 2] -= branch[:, 0]
    net[:, 5] -= branch[:, 1]+branch[:, 2]
    return np.column_stack([net/CAPACITY, np.atleast_2d(heat).sum(axis=1),
                            branch.sum(axis=1), branch])


class PythonCooling:
    state_names = BRANCHES
    initial_temperatures_c = (80.,)*6

    def __init__(self, area, varying=False):
        self.area, self.varying = area, varying

    def evaluate(self, t, temperatures, heat, input_j, ambient_j, *,
                 branch_energy_j, accepted=False):
        return rates(temperatures, heat, gc_at(t, self.varying), self.area)[0]

    def describe(self):
        return dict(kind="independent Python port equations", area_m2=self.area,
                    initial_temperatures_c=list(self.initial_temperatures_c))
