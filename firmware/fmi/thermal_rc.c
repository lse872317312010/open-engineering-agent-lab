/* Original OEAL FMI 2.0 Co-Simulation RC model. FMI header notices in resources. */
#include "fmi2Functions.h"

#include <math.h>
#include <string.h>

typedef struct {
    double value[5]; /* temperature, power, R, C, ambient */
    double time;
    int running;
} Model;

const char *fmi2GetTypesPlatform(void) { return "default"; }
const char *fmi2GetVersion(void) { return "2.0"; }

fmi2Component fmi2Instantiate(fmi2String name, fmi2Type type, fmi2String guid,
    fmi2String resources, const fmi2CallbackFunctions *callbacks,
    fmi2Boolean visible, fmi2Boolean logging)
{
    (void)name; (void)resources; (void)callbacks; (void)visible; (void)logging;
    if (type != fmi2CoSimulation || guid == NULL
        || strcmp(guid, "{a5505b9e-0ea1-4060-b701-000000000006}") != 0) return NULL;
    Model *m = calloc(1, sizeof(Model));
    if (m) {
        m->value[0] = 25; m->value[2] = 1.5; m->value[3] = 80; m->value[4] = 25;
    }
    return m;
}
void fmi2FreeInstance(fmi2Component c) { free(c); }
fmi2Status fmi2SetDebugLogging(fmi2Component c, fmi2Boolean on, size_t n,
    const fmi2String categories[])
{ (void)on; (void)n; (void)categories; return c ? fmi2OK : fmi2Error; }
fmi2Status fmi2SetupExperiment(fmi2Component c, fmi2Boolean td, fmi2Real tol,
    fmi2Real start, fmi2Boolean sd, fmi2Real stop)
{
    (void)td; (void)tol; (void)sd; (void)stop;
    if (!c || !isfinite(start)) return fmi2Error;
    ((Model *)c)->time = start;
    return fmi2OK;
}
fmi2Status fmi2EnterInitializationMode(fmi2Component c)
{ if (!c) return fmi2Error; ((Model *)c)->running = 0; return fmi2OK; }
fmi2Status fmi2ExitInitializationMode(fmi2Component c)
{ if (!c) return fmi2Error; ((Model *)c)->running = 1; return fmi2OK; }
fmi2Status fmi2Terminate(fmi2Component c)
{ if (!c) return fmi2Error; ((Model *)c)->running = 2; return fmi2OK; }
fmi2Status fmi2Reset(fmi2Component c)
{
    if (!c) return fmi2Error;
    Model *m = c;
    const double initial[5] = {25, 0, 1.5, 80, 25};
    memcpy(m->value, initial, sizeof(initial));
    m->time = 0; m->running = 0;
    return fmi2OK;
}
fmi2Status fmi2GetReal(fmi2Component c, const fmi2ValueReference vr[], size_t n,
    fmi2Real values[])
{
    if (!c || !vr || !values) return fmi2Error;
    for (size_t i = 0; i < n; ++i) if (vr[i] > 4) return fmi2Error;
    for (size_t i = 0; i < n; ++i) values[i] = ((Model *)c)->value[vr[i]];
    return fmi2OK;
}
fmi2Status fmi2SetReal(fmi2Component c, const fmi2ValueReference vr[], size_t n,
    const fmi2Real values[])
{
    if (!c || !vr || !values || ((Model *)c)->running == 2) return fmi2Error;
    Model *m = c;
    double trial[5];
    memcpy(trial, m->value, sizeof(trial));
    for (size_t i = 0; i < n; ++i) {
        if (vr[i] > 4 || !isfinite(values[i])
            || (m->running == 1 && vr[i] != 1)) return fmi2Error;
        trial[vr[i]] = values[i];
    }
    if (trial[2] <= 0 || trial[3] <= 0 || trial[0] <= -273.15 || trial[4] <= -273.15)
        return fmi2Error;
    memcpy(m->value, trial, sizeof(trial));
    return fmi2OK;
}
fmi2Status fmi2DoStep(fmi2Component c, fmi2Real t, fmi2Real dt, fmi2Boolean no_rollback)
{
    (void)no_rollback;
    if (!c || !isfinite(t) || !isfinite(dt) || dt <= 0) return fmi2Error;
    Model *m = c;
    if (m->running != 1 || fabs(t - m->time) > 1e-8) return fmi2Error;
    const double decay = exp(-dt / (m->value[2] * m->value[3]));
    const double equilibrium = m->value[4] + m->value[2] * m->value[1];
    const double next = equilibrium + (m->value[0] - equilibrium) * decay;
    if (!isfinite(next) || !isfinite(t + dt)) return fmi2Error;
    m->value[0] = next; m->time = t + dt;
    return fmi2OK;
}
/* No integer/boolean/string variables; no non-zero-order input interpolation. */
#define EMPTY_ACCESS(Suffix, Type) \
fmi2Status fmi2Get##Suffix(fmi2Component c, const fmi2ValueReference vr[], size_t n, Type v[]) \
{ (void)vr; (void)v; return c && n == 0 ? fmi2OK : fmi2Error; } \
fmi2Status fmi2Set##Suffix(fmi2Component c, const fmi2ValueReference vr[], size_t n, const Type v[]) \
{ (void)vr; (void)v; return c && n == 0 ? fmi2OK : fmi2Error; }
EMPTY_ACCESS(Integer, fmi2Integer)
EMPTY_ACCESS(Boolean, fmi2Boolean)
EMPTY_ACCESS(String, fmi2String)
fmi2Status fmi2SetRealInputDerivatives(fmi2Component c, const fmi2ValueReference vr[],
    size_t n, const fmi2Integer order[], const fmi2Real value[])
{ (void)c; (void)vr; (void)n; (void)order; (void)value; return fmi2Error; }
fmi2Status fmi2GetRealOutputDerivatives(fmi2Component c, const fmi2ValueReference vr[],
    size_t n, const fmi2Integer order[], fmi2Real value[])
{ (void)c; (void)vr; (void)n; (void)order; (void)value; return fmi2Error; }
fmi2Status fmi2CancelStep(fmi2Component c) { (void)c; return fmi2Error; }
fmi2Status fmi2GetStatus(fmi2Component c, const fmi2StatusKind kind, fmi2Status *v)
{ (void)kind; if (!c || !v) return fmi2Error; *v = fmi2OK; return fmi2OK; }
fmi2Status fmi2GetRealStatus(fmi2Component c, const fmi2StatusKind kind, fmi2Real *v)
{ if (!c || !v || kind != fmi2LastSuccessfulTime) return fmi2Error;
  *v = ((Model *)c)->time; return fmi2OK; }
fmi2Status fmi2GetIntegerStatus(fmi2Component c, const fmi2StatusKind k, fmi2Integer *v)
{ (void)c; (void)k; (void)v; return fmi2Error; }
fmi2Status fmi2GetBooleanStatus(fmi2Component c, const fmi2StatusKind k, fmi2Boolean *v)
{ if (!c || !v || k != fmi2Terminated) return fmi2Error;
  *v = ((Model *)c)->running == 2; return fmi2OK; }
fmi2Status fmi2GetStringStatus(fmi2Component c, const fmi2StatusKind k, fmi2String *v)
{ (void)c; (void)k; (void)v; return fmi2Error; }

fmi2Status fmi2GetFMUstate(fmi2Component c, fmi2FMUstate *s)
{ (void)c; (void)s; return fmi2Error; }
fmi2Status fmi2SetFMUstate(fmi2Component c, fmi2FMUstate s)
{ (void)c; (void)s; return fmi2Error; }
fmi2Status fmi2FreeFMUstate(fmi2Component c, fmi2FMUstate *s)
{ (void)c; (void)s; return fmi2Error; }
fmi2Status fmi2SerializedFMUstateSize(fmi2Component c, fmi2FMUstate s, size_t *n)
{ (void)c; (void)s; (void)n; return fmi2Error; }
fmi2Status fmi2SerializeFMUstate(fmi2Component c, fmi2FMUstate s, fmi2Byte data[], size_t n)
{ (void)c; (void)s; (void)data; (void)n; return fmi2Error; }
fmi2Status fmi2DeSerializeFMUstate(fmi2Component c, const fmi2Byte data[], size_t n, fmi2FMUstate *s)
{ (void)c; (void)data; (void)n; (void)s; return fmi2Error; }
fmi2Status fmi2GetDirectionalDerivative(fmi2Component c, const fmi2ValueReference u[], size_t nu,
    const fmi2ValueReference k[], size_t nk, const fmi2Real dv[], fmi2Real out[])
{ (void)c; (void)u; (void)nu; (void)k; (void)nk; (void)dv; (void)out; return fmi2Error; }
