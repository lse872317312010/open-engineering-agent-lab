"""Frozen synthetic generator inputs, never imported by the noisy-data fitting process."""
import numpy as np

DT = .05
AREA = .02
GC = 1/3
NOISE = .02
TRUTH_C = [75.,90.,260.,.8,32.,130.]
TRUTH_R = [.75,.5,2.4,1.05,1.5]
TRUTH_CASE_R = 2.8
NODES = ("winding", "core", "case", "junction", "board", "sink")
SPLITS = [
    dict(id="train", duration_s=1200., ambient_c=25., initial_c=[25.]*6,
         amplitude_w=[20.,12.,18.,6.,8.,10.], period_s=[30,45,60,8,35,50],
         phase=[0,1,0,1,0,1], noise_seed=2026102801),
    dict(id="validation", duration_s=300., ambient_c=25., initial_c=[45.,40.,35.,50.,38.,32.],
         amplitude_w=[15.,9.,12.,4.,6.,7.], period_s=[19,23,31,5,17,29],
         phase=[1,0,1,0,1,0], noise_seed=2026102802),
    dict(id="holdout", duration_s=300., ambient_c=60., initial_c=[60.]*6,
         amplitude_w=[18.,10.,14.,5.,7.,9.], period_s=[13,21,27,7,16,25],
         phase=[0,0,1,1,0,1], noise_seed=2026102803),
]


def inputs(case):
    ticks = np.arange(round(case["duration_s"]/DT)+1)
    period_ticks = np.rint(np.asarray(case["period_s"])/DT).astype(int)
    return (ticks[:, None]//period_ticks+case["phase"]) % 2 * case["amplitude_w"]


def physical_vector(config):
    return np.r_[config["capacities_j_per_k"], config["link_resistances_k_per_w"],
                 config["case_resistance_k_per_w"]]


def truth():
    return dict(capacities_j_per_k=TRUTH_C, link_resistances_k_per_w=TRUTH_R,
                case_resistance_k_per_w=TRUTH_CASE_R)
