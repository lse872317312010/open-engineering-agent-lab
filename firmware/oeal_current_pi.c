#include "oeal_current_pi.h"

#include <math.h>
#include <stddef.h>

static void limit_vector(double d, double q, double limit, double result[2])
{
    const double scale = fmax(fabs(d), fabs(q));
    if (scale == 0.0) {
        result[0] = d;
        result[1] = q;
        return;
    }
    const double nd = d / scale;
    const double nq = q / scale;
    const double norm = hypot(nd, nq);
    if (scale <= limit / norm) {
        result[0] = d;
        result[1] = q;
    } else {
        result[0] = (nd / norm) * limit;
        result[1] = (nq / norm) * limit;
    }
}

int oeal_pi_step(const double p[7], const double state[2],
                 const double input[7], double output[8])
{
    if (output == NULL) {
        return 1;
    }
    for (size_t i = 0; i < 8; ++i) {
        output[i] = 0.0;
    }
    if (p == NULL || state == NULL || input == NULL) {
        return 1;
    }
    for (size_t i = 0; i < 7; ++i) {
        if (!isfinite(p[i]) || !isfinite(input[i])) {
            return 1;
        }
        if ((i < 4 && p[i] < 0.0) || (i >= 4 && p[i] <= 0.0)) {
            return 1;
        }
    }
    if (!isfinite(state[0]) || !isfinite(state[1]) || input[4] <= 0.0
        || (p[1] == 0.0 && state[0] != 0.0)
        || (p[3] == 0.0 && state[1] != 0.0)) {
        return 1;
    }
    double reference[2];
    limit_vector(input[0], input[1], p[5], reference);
    const double ed = reference[0] - input[2];
    const double eq = reference[1] - input[3];
    const double zd = state[0] + p[1] * input[4] * ed;
    const double zq = state[1] + p[3] * input[4] * eq;
    const double ud = p[0] * ed + zd + input[5];
    const double uq = p[2] * eq + zq + input[6];
    if (!isfinite(ed) || !isfinite(eq) || !isfinite(zd)
        || !isfinite(zq) || !isfinite(ud) || !isfinite(uq)) {
        return 1;
    }
    double voltage[2];
    limit_vector(ud, uq, p[4], voltage);
    const double beta = -expm1(-p[6] * input[4]);
    const double next_d = p[1] > 0.0 ? zd + beta * (voltage[0] - ud) : 0.0;
    const double next_q = p[3] > 0.0 ? zq + beta * (voltage[1] - uq) : 0.0;
    if (!isfinite(next_d) || !isfinite(next_q)) {
        return 1;
    }
    output[0] = voltage[0];
    output[1] = voltage[1];
    output[2] = reference[0];
    output[3] = reference[1];
    output[4] = (voltage[0] != ud || voltage[1] != uq) ? 1.0 : 0.0;
    output[5] = (reference[0] != input[0] || reference[1] != input[1]) ? 1.0 : 0.0;
    output[6] = next_d;
    output[7] = next_q;
    return 0;
}
