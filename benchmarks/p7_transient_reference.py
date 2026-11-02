"""Independent transient references: exact modal time response and 1D finite volumes."""
import numpy as np
from scipy.linalg import eigh, eigh_tridiagonal


def pulse(t, period=8.):
    t = np.asarray(t)
    return np.where((t >= 0) & (t <= period), .5*(1-np.cos(2*np.pi*t/period)), 0.)


def pulse_integral(t, period=8.):
    clipped = np.clip(np.asarray(t), 0, period)
    return clipped/2-period*np.sin(2*np.pi*clipped/period)/(4*np.pi)


def modal_response(rates, forcing, times, period=8.):
    """Exact zero-initial solution of a' + lambda*a = b*pulse(t)."""
    rates, forcing, times = np.asarray(rates), np.asarray(forcing), np.asarray(times)
    if np.any(rates <= 0):
        raise ValueError("positive modal rates required")
    t = np.minimum(np.maximum(times, 0), period)[:, None]
    lam = rates[None, :]
    omega = 2*np.pi/period
    decay = np.exp(-lam*t)
    constant = -np.expm1(-lam*t)/lam
    harmonic = (lam*np.cos(omega*t)+omega*np.sin(omega*t)-lam*decay)/(lam*lam+omega*omega)
    amplitude = .5*forcing[None, :]*(constant-harmonic)
    return amplitude*np.exp(-lam*np.maximum(times-period, 0)[:, None])


def fe_modal(mass, stiffness, forcing, times, period=8.):
    """Independent time integration only; accepts the same FE spatial matrices."""
    rates, vectors = eigh(stiffness.toarray(), mass.toarray())
    coordinates = modal_response(rates, vectors.T@forcing, times, period)
    return coordinates@vectors.T


def finite_volume(c, capacities, n, times, period=8.):
    """Cell-centered 1D conservation, no FE mesh/matrix/basis is accepted."""
    lengths = np.array([.04, .06])
    dx = np.repeat(lengths/n, n)
    k = np.repeat([c["k1"], c["k2"]], n)
    cv = np.repeat(capacities, n)
    # Per unit face area; C in J/(m2 K), f in W/m2.
    storage = cv*dx
    resistance = dx[:-1]/(2*k[:-1])+dx[1:]/(2*k[1:])
    resistance[n-1] += c["rc"]
    conductance = 1/resistance
    diagonal = np.zeros(2*n)
    diagonal[:-1] += conductance
    diagonal[1:] += conductance
    diagonal[0] += 2*k[0]/dx[0]
    diagonal[-1] += 1/(dx[-1]/(2*k[-1])+1/c["h"])
    root = np.sqrt(storage)
    rates, vectors = eigh_tridiagonal(diagonal/storage,
                                      -conductance/(root[:-1]*root[1:]))
    forcing = np.repeat([c["s1"], c["s2"]], n)*dx
    coordinates = modal_response(rates, vectors.T@(forcing/root), times, period)
    fields = (coordinates@vectors.T)/root
    xleft = (np.arange(n)+.5)*lengths[0]/n
    xright = lengths[0]+(np.arange(n)+.5)*lengths[1]/n
    q = (fields[:, n-1]-fields[:, n])/(dx[n-1]/(2*k[n-1])+c["rc"]+dx[n]/(2*k[n]))
    tl = fields[:, n-1]-q*dx[n-1]/(2*k[n-1])
    tr = fields[:, n]+q*dx[n]/(2*k[n])
    qr = fields[:, -1]/(dx[-1]/(2*k[-1])+1/c["h"])
    return dict(n=n, times=np.asarray(times), rates=rates,
                left_x=np.r_[0., xleft, .04], right_x=np.r_[.04, xright, .1],
                left=np.column_stack([np.zeros(len(times)), fields[:, :n], tl]),
                right=np.column_stack([tr, fields[:, n:], qr/c["h"]]))


def interpolate_reference(reference, x, region):
    side = "left" if region == 10 else "right"
    return np.array([np.interp(x, reference[side+"_x"], values)
                     for values in reference[side]])
