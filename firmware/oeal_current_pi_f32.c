#include "oeal_current_pi_f32.h"

#include <float.h>
#include <math.h>
#include <stddef.h>

_Static_assert(FLT_RADIX == 2 && FLT_MANT_DIG == 24 && sizeof(float) == 4,
               "IEEE754 binary32 float is required");

static void limit_vector(float d, float q, float limit, float result[2])
{
    const float scale = fmaxf(fabsf(d), fabsf(q));
    if (scale == 0.0f) {
        result[0] = d;
        result[1] = q;
        return;
    }
    const float nd = d / scale;
    const float nq = q / scale;
    const float norm = hypotf(nd, nq);
    if (scale <= limit / norm) {
        result[0] = d;
        result[1] = q;
    } else {
        result[0] = (nd / norm) * limit;
        result[1] = (nq / norm) * limit;
    }
}

int oeal_pi_step_f32(const float p[7], const float state[2],
                 const float input[7], float output[8])
{
    if (output == NULL) {
        return 1;
    }
    for (size_t i = 0; i < 8; ++i) {
        output[i] = 0.0f;
    }
    if (p == NULL || state == NULL || input == NULL) {
        return 1;
    }
    for (size_t i = 0; i < 7; ++i) {
        if (!isfinite(p[i]) || !isfinite(input[i])) {
            return 1;
        }
        if ((i < 4 && p[i] < 0.0f) || (i >= 4 && p[i] <= 0.0f)) {
            return 1;
        }
    }
    if (!isfinite(state[0]) || !isfinite(state[1]) || input[4] <= 0.0f
        || (p[1] == 0.0f && state[0] != 0.0f)
        || (p[3] == 0.0f && state[1] != 0.0f)) {
        return 1;
    }
    float reference[2];
    limit_vector(input[0], input[1], p[5], reference);
    const float ed = reference[0] - input[2];
    const float eq = reference[1] - input[3];
    const float zd = state[0] + p[1] * input[4] * ed;
    const float zq = state[1] + p[3] * input[4] * eq;
    const float ud = p[0] * ed + zd + input[5];
    const float uq = p[2] * eq + zq + input[6];
    if (!isfinite(ed) || !isfinite(eq) || !isfinite(zd)
        || !isfinite(zq) || !isfinite(ud) || !isfinite(uq)) {
        return 1;
    }
    float voltage[2];
    limit_vector(ud, uq, p[4], voltage);
    const float beta = -expm1f(-p[6] * input[4]);
    const float next_d = p[1] > 0.0f ? zd + beta * (voltage[0] - ud) : 0.0f;
    const float next_q = p[3] > 0.0f ? zq + beta * (voltage[1] - uq) : 0.0f;
    if (!isfinite(next_d) || !isfinite(next_q)) {
        return 1;
    }
    output[0] = voltage[0];
    output[1] = voltage[1];
    output[2] = reference[0];
    output[3] = reference[1];
    output[4] = (voltage[0] != ud || voltage[1] != uq) ? 1.0f : 0.0f;
    output[5] = (reference[0] != input[0] || reference[1] != input[1]) ? 1.0f : 0.0f;
    output[6] = next_d;
    output[7] = next_q;
    return 0;
}
