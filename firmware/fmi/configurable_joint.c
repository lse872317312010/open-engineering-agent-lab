/* Original MIT OEAL configurable joint FMI 2.0 plant; see docs/fmi-servo-contract.md. */
#include "fmi2Functions.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

#define GUID "{a5505b9e-0ea1-4060-b701-000000000020}"
typedef struct {
    double value[25]; /* 12 states/ledgers, 4 held inputs, internal maximum step */
    double time, stop;
    int running, has_stop; /* instantiated=0, setup=1, init=2, run=3, terminated=4 */
} Model;

static void defaults(Model *m) {
    memset(m, 0, sizeof(*m));
    m->value[6] = m->value[7] = m->value[8] = 25;
    m->value[16] = 5e-6;
    const double p[7]={.3,.0008,.0008,.03,7,5e-5,1e-5};
    memcpy(m->value+18,p,sizeof(p));
}
static double shaft(const double *x) {
    return 80 * (x[2]/10-x[4]) + .15 * (x[3]/10-x[5]);
}
static int derivative(const double *x, const double *u, const double *p, double *f) {
    double d=x[0], q=x[1], wm=x[3], wl=x[5], tw=x[6], tc=x[7], tb=x[8];
    double r=p[0]*(1+.00393*(tw-25)), we=p[4]*wm, rate=wm/10-wl;
    double ld=p[1], lq=p[2], psi=p[3];
    double te=1.5*p[4]*(psi*q+(ld-lq)*d*q);
    double copper=1.5*r*(d*d+q*q);
    double friction=p[6]*wm*wm+.02*wl*wl+.15*rate*rate;
    double wc=(tw-tc)/.8, bc=(tb-tc)/1.2, ca=(tc-25)/2, ba=(tb-25)/4;
    if (r <= 0 || tw <= -273.15 || tc <= -273.15 || tb <= -273.15) return 0;
    f[0]=(u[0]-r*d+we*lq*q)/ld;
    f[1]=(u[1]-r*q-we*(ld*d+psi))/lq;
    f[2]=wm; f[3]=(te-shaft(x)/10-p[6]*wm)/p[5];
    f[4]=wl; f[5]=(shaft(x)-u[2]-.02*wl)/.02;
    f[6]=(copper-wc)/60; f[7]=(wc+bc+friction-ca)/200; f[8]=(u[3]-bc-ba)/25;
    f[9]=1.5*(u[0]*d+u[1]*q)+u[3]; f[10]=u[2]*wl; f[11]=ca+ba;
    for (int i=0;i<12;++i) if (!isfinite(f[i])) return 0;
    return 1;
}
static int integrate(double *x, const double *u, const double *p, double h) {
    double k[4][12], trial[12];
    if (!derivative(x,u,p,k[0])) return 0;
    for (int j=1;j<4;++j) {
        double fraction=j==3 ? 1 : .5;
        for (int i=0;i<12;++i) trial[i]=x[i]+fraction*h*k[j-1][i];
        if (!derivative(trial,u,p,k[j])) return 0;
    }
    for (int i=0;i<12;++i) {
        x[i]+=h*(k[0][i]+2*k[1][i]+2*k[2][i]+k[3][i])/6;
        if (!isfinite(x[i])) return 0;
    }
    return derivative(x,u,p,trial);
}
const char *fmi2GetTypesPlatform(void) { return "default"; }
const char *fmi2GetVersion(void) { return "2.0"; }
fmi2Component fmi2Instantiate(fmi2String name, fmi2Type type, fmi2String guid,
    fmi2String resources, const fmi2CallbackFunctions *callbacks,
    fmi2Boolean visible, fmi2Boolean logging) {
    (void)name; (void)resources; (void)callbacks; (void)visible; (void)logging;
    if (type!=fmi2CoSimulation || !guid || strcmp(guid,GUID)!=0) return NULL;
    Model *m=calloc(1,sizeof(Model));
    if (m) defaults(m);
    return m;
}
void fmi2FreeInstance(fmi2Component c) { free(c); }
fmi2Status fmi2SetDebugLogging(fmi2Component c, fmi2Boolean on, size_t n,
    const fmi2String categories[]) {
    (void)on; (void)n; (void)categories; return c ? fmi2OK : fmi2Error;
}
fmi2Status fmi2SetupExperiment(fmi2Component c, fmi2Boolean td, fmi2Real tol,
    fmi2Real start, fmi2Boolean sd, fmi2Real stop) {
    (void)td; (void)tol;
    if (!c || ((Model*)c)->running!=0 || !isfinite(start)
        || (sd && (!isfinite(stop) || stop<=start))) return fmi2Error;
    Model *m=c; m->time=start; m->stop=stop; m->has_stop=sd; m->running=1;
    return fmi2OK;
}
fmi2Status fmi2EnterInitializationMode(fmi2Component c) {
    if (!c || ((Model*)c)->running!=1) return fmi2Error;
    ((Model*)c)->running=2; return fmi2OK;
}
fmi2Status fmi2ExitInitializationMode(fmi2Component c) {
    if (!c || ((Model*)c)->running!=2) return fmi2Error;
    ((Model*)c)->running=3; return fmi2OK;
}
fmi2Status fmi2Terminate(fmi2Component c) {
    if (!c || ((Model*)c)->running!=3) return fmi2Error;
    ((Model*)c)->running=4; return fmi2OK;
}
fmi2Status fmi2Reset(fmi2Component c) {
    if (!c) return fmi2Error;
    defaults((Model*)c); return fmi2OK;
}
fmi2Status fmi2GetReal(fmi2Component c, const fmi2ValueReference vr[], size_t n,
    fmi2Real values[]) {
    if (!c || (n && (!vr || !values))) return fmi2Error;
    for (size_t i=0;i<n;++i) if (vr[i]>24) return fmi2Error;
    Model *m=c;
    for (size_t i=0;i<n;++i) values[i]=vr[i]==17 ? shaft(m->value) : m->value[vr[i]];
    return fmi2OK;
}
fmi2Status fmi2SetReal(fmi2Component c, const fmi2ValueReference vr[], size_t n,
    const fmi2Real values[]) {
    if (!c || (n && (!vr || !values))) return fmi2Error;
    Model *m=c; double trial[25];
    if (m->running==4) return fmi2Error;
    memcpy(trial,m->value,sizeof(trial));
    for (size_t i=0;i<n;++i) {
        if (vr[i]<12 || vr[i]>24 || vr[i]==17 || !isfinite(values[i])
            || ((vr[i]==16 || vr[i]>=18) && m->running==3)) return fmi2Error;
        trial[vr[i]]=values[i];
    }
    if (hypot(trial[12],trial[13])>48/sqrt(3.) || fabs(trial[14])>10
        || trial[15]<0 || trial[15]>1000 || trial[16]<1e-8 || trial[16]>5e-6)
        return fmi2Error;
    const double low[7]={.15,.0004,.0004,.015,1,2.5e-5,0};
    const double high[7]={.6,.0016,.0016,.045,14,2e-4,5e-5};
    for (int i=0;i<7;++i)
        if (trial[18+i]<low[i] || trial[18+i]>high[i]) return fmi2Error;
    if (trial[22]!=floor(trial[22])) return fmi2Error;
    memcpy(m->value,trial,sizeof(trial)); return fmi2OK;
}
fmi2Status fmi2DoStep(fmi2Component c, fmi2Real t, fmi2Real h,
    fmi2Boolean no_rollback) {
    (void)no_rollback;
    if (!c || !isfinite(t) || !isfinite(h) || h<=0 || h>.001) return fmi2Error;
    Model *m=c; double eps=1e-12+1e-10*fabs(m->time);
    if (m->running!=3 || fabs(t-m->time)>eps || !isfinite(t+h)
        || t+h<=t || (m->has_stop && t+h>m->stop+eps)) return fmi2Error;
    Model trial=*m;
    int n=(int)ceil(h/trial.value[16]);
    for (int j=0;j<n;++j) {
        if (!integrate(trial.value,trial.value+12,trial.value+18,h/n)) return fmi2Error;
    }
    trial.time=t+h; *m=trial; return fmi2OK;
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
  *v = ((Model *)c)->running == 4; return fmi2OK; }
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
