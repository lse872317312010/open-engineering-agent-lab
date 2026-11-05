"""Frozen virtual-work comparison of FEMM block and sliding-gap coenergy."""
import math

import numpy as np

FINE_RAD = math.radians(.703125)
COARSE_RAD = math.radians(1.40625)


def compare(block, gap, stress, gap_torque):
    block = np.asarray(block, dtype=float)
    gap = np.asarray(gap, dtype=float)
    if (block.shape != (5,) or gap.shape != (5,)
            or not np.isfinite(block).all() or not np.isfinite(gap).all()
            or not math.isfinite(stress) or not math.isfinite(gap_torque)):
        raise ValueError("five finite energy values and finite torque required")
    total = block+gap
    fine = float((total[3]-total[1])/(2*FINE_RAD))
    coarse = float((total[4]-total[0])/(2*COARSE_RAD))
    block_only = float((block[3]-block[1])/(2*FINE_RAD))
    return dict(energy_torque_nm=fine, coarse_torque_nm=coarse,
                block_only_torque_nm=block_only, stress_torque_nm=float(stress),
                gap_torque_nm=float(gap_torque), error_nm=abs(fine-stress),
                coarse_error_nm=abs(coarse-stress), refinement_nm=abs(fine-coarse),
                gap_omission_effect_nm=abs(fine-block_only),
                passed=bool(abs(fine-stress) <= .10 and abs(stress-gap_torque) <= .05))
