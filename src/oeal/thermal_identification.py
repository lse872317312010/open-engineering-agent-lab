"""Six-node thermal identification from integral windows with explicit excitation checks."""
import numpy as np

EDGES = ((0,1),(1,2),(2,4),(3,4),(4,5))
NOMINAL_C = np.array([60.,70.,200.,.5,25.,100.])
NOMINAL_G = 1/np.array([.6,.4,2.,.8,1.2,2.])
SIGMA = 5.6703744191844314e-8
WINDOWS = (20.,20.,20.,.5,20.,20.)


def design_matrix(time_s, temperature_c, mean_power_w, ambient_c, area_m2=.02,
                  convection_w_per_k=1/3, windows_s=WINDOWS):
    """Return SI integral equations; interval power is an interval mean, not a point sample."""
    time = np.asarray(time_s, dtype=float)
    temperature = np.asarray(temperature_c, dtype=float)
    power = np.asarray(mean_power_w, dtype=float)
    if (time.ndim != 1 or len(time) < 3 or temperature.shape != (len(time), 6)
            or power.shape != (len(time)-1, 6)
            or not all(np.all(np.isfinite(x)) for x in (time, temperature, power))):
        raise ValueError("aligned finite time, six temperatures and interval powers required")
    ambient, area, gc = float(ambient_c), float(area_m2), float(convection_w_per_k)
    if (not np.all(np.isfinite([ambient, area, gc])) or ambient <= -273.15
            or np.min(temperature) <= -273.15 or not 0 <= area <= .1 or not 0 <= gc <= 2):
        raise ValueError("invalid absolute temperature or known boundary")
    steps = np.diff(time)
    dt = steps[0]
    if dt <= 0 or not np.allclose(steps, dt, rtol=1e-10, atol=1e-10):
        raise ValueError("strictly increasing uniform time grid required")
    windows = np.asarray(windows_s, dtype=float)
    if windows.shape != (6,) or not np.all(np.isfinite(windows)) or np.min(windows) <= 0:
        raise ValueError("six finite positive windows required")
    counts = np.rint(windows/dt).astype(int)
    if np.any(counts < 2) or np.any(counts % 2) or not np.allclose(counts*dt, windows):
        raise ValueError("Simpson windows require even interval counts aligned to the grid")
    if np.max(counts) >= len(time):
        raise ValueError("insufficient samples for identification windows")
    source_integral = np.vstack([np.zeros(6), np.cumsum(power*dt, axis=0)])
    boundary = gc*(temperature[:, 5]-ambient)+area*SIGMA*(
        (temperature[:, 5]+273.15)**4-(ambient+273.15)**4)
    rows, right, nodes = [], [], []
    for node, count in enumerate(counts):
        weights = np.ones(count+1)
        weights[1:-1:2] = 4.
        weights[2:-1:2] = 2.
        weights *= dt/3
        for start in range(0, len(time)-count, count):
            stop = start+count
            integral = weights @ temperature[start:stop+1]
            row = np.zeros(12)
            row[node] = temperature[stop, node]-temperature[start, node]
            for k, (a, b) in enumerate(EDGES):
                if node == a:
                    row[6+k] = integral[a]-integral[b]
                elif node == b:
                    row[6+k] = integral[b]-integral[a]
            if node == 2:
                row[11] = integral[2]-ambient*(time[stop]-time[start])
            energy = source_integral[stop, node]-source_integral[start, node]
            if node == 5:
                energy -= weights @ boundary[start:stop+1]
            rows.append(row)
            right.append(energy)
            nodes.append(node)
    return np.asarray(rows), np.asarray(right), np.asarray(nodes, dtype=int)


def fit_network(time_s, temperature_c, mean_power_w, ambient_c, area_m2=.02,
                convection_w_per_k=1/3, windows_s=WINDOWS):
    """Fit only the supplied observation arrays; no truth/validation/holdout inputs."""
    from scipy.optimize import lsq_linear

    design, right, nodes = design_matrix(time_s, temperature_c, mean_power_w, ambient_c,
                                         area_m2, convection_w_per_k, windows_s)
    nominal = np.r_[NOMINAL_C, NOMINAL_G]
    weighted = design*nominal/NOMINAL_C[nodes, None]
    target = right/NOMINAL_C[nodes]
    norms = np.linalg.norm(weighted, axis=0)
    if np.any(norms <= 1e-12):
        raise ValueError("insufficient excitation: zero parameter column")
    scaled = weighted/norms
    singular = np.linalg.svd(scaled, compute_uv=False)
    rank = int(np.sum(singular > singular[0]*1e-10))
    condition = float(singular[0]/singular[-1]) if singular[-1] > 0 else float("inf")
    if rank != 12 or condition > 1e5:
        raise ValueError("insufficient excitation: rank/conditioning gate failed")
    lower = np.r_[np.full(6, .05), np.full(6, .05)]/nominal*norms
    upper = np.r_[np.full(6, 1000.), np.full(6, 20.)]/nominal*norms
    result = lsq_linear(scaled, target, bounds=(lower, upper),
                        method="trf", tol=1e-12, max_iter=500)
    if not result.success or not np.all(np.isfinite(result.x)):
        raise ValueError("bounded thermal parameter optimization failed")
    parameter = result.x/norms*nominal
    residual = design @ parameter-right
    resistance = 1/parameter[6:]
    return dict(capacities_j_per_k=parameter[:6].tolist(),
                link_resistances_k_per_w=resistance[:5].tolist(),
                case_resistance_k_per_w=float(resistance[5]),
                conductances_w_per_k=parameter[6:].tolist(),
                normalized_rank=rank, normalized_condition=condition,
                singular_values=singular.tolist(), equation_count=len(right),
                residual_rms_j_by_node=[float(np.sqrt(np.mean(residual[nodes == i]**2)))
                                        for i in range(6)],
                optimality=float(result.optimality), cost=float(result.cost),
                iterations=int(result.nit),
                optimizer_status=int(result.status),
                active_bounds=np.asarray(result.active_mask, dtype=int).tolist(),
                column_norms=norms.tolist(), windows_s=list(windows_s),
                method="scipy.optimize.lsq_linear; fixed integral windows; nominal-C row scaling")
