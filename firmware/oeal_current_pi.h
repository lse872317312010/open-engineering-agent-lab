#ifndef OEAL_CURRENT_PI_H
#define OEAL_CURRENT_PI_H

/* Units and order are fixed by docs/sil-contract.md.
 * p[7]: Kpd, Kid, Kpq, Kiq, Vmax, Imax, tracking_rate.
 * state[2]: integral_d, integral_q (V).
 * input[7]: id_ref, iq_ref, id_meas, iq_meas (A), Ts (s), fd, fq (V).
 * output[8]: vd, vq, limited_id_ref, limited_iq_ref, v_limited,
 *            ref_limited, next_integral_d, next_integral_q.
 * Returns 0 on success, 1 on invalid input/numeric overflow.
 * No mutation of p/state/input. Output is zeroed on errors when non-null.
 * No heap, hardware access, HAL, or hidden mutable state.
 */
int oeal_pi_step(const double p[7], const double state[2],
                 const double input[7], double output[8]);

#endif
