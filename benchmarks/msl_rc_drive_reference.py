"""Independent RC loss routing using frozen equations and trusted parameter normalization."""
from msl_cooling_drive_reference import PythonCooling, gc_at
from msl_rc_parameters import rc_parameters
from msl_rc_reference import rates


class ParametricPython(PythonCooling):
    def __init__(self, area, varying=False, *, ambient_c=25., initial_temperatures_c=None,
                 capacities_j_per_k=None, link_resistances_k_per_w=None,
                 case_resistance_k_per_w=2.):
        super().__init__(area, varying, ambient_c=ambient_c,
                         initial_temperatures_c=initial_temperatures_c)
        (self.capacities_j_per_k, self.link_resistances_k_per_w,
         self.case_resistance_k_per_w) = rc_parameters(
             capacities_j_per_k, link_resistances_k_per_w, case_resistance_k_per_w)

    def independent_rates(self, temperatures, heat, gc, area, ambient):
        return rates(temperatures, heat, gc, area, ambient, self.capacities_j_per_k,
                     self.link_resistances_k_per_w, self.case_resistance_k_per_w)

    def evaluate(self, t, temperatures, heat, input_j, ambient_j, *,
                 branch_energy_j, accepted=False):
        if accepted:
            self.accepted.append([t, *branch_energy_j])
        return self.independent_rates(temperatures, heat, gc_at(t, self.varying),
                                      self.area, self.ambient_c)[0]

    def describe(self):
        return dict(kind="independent configurable RC port equations",
                    capacities_j_per_k=list(self.capacities_j_per_k),
                    link_resistances_k_per_w=list(self.link_resistances_k_per_w),
                    case_resistance_k_per_w=self.case_resistance_k_per_w,
                    ambient_c=self.ambient_c, area_m2=self.area)
