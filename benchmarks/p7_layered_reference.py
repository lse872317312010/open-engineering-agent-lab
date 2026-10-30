"""Independent piecewise-quadratic layered slab reference; no FE dependencies."""
import numpy as np

L = .1
A = .04
HEIGHT = .1
THICKNESS = .01
CASES = [
    dict(id="layered", k1=2., k2=.2, h=10., left_c=50., ambient_c=25., s1=1000., s2=2000.),
    dict(id="uniform-k", k1=2., k2=2., h=10., left_c=50., ambient_c=25., s1=1000., s2=2000.),
    dict(id="hot-ambient", k1=2., k2=.2, h=10., left_c=25., ambient_c=60.,
         s1=1000., s2=2000.),
]
PATCH = dict(id="zero-source", k1=2., k2=.2, h=10., left_c=50., ambient_c=25., s1=0., s2=0.)


def constants(case):
    b = L-A
    resistance = A/case["k1"]+b/case["k2"]
    source_offset = (case["s1"]*A*A/(2*case["k1"])
                     +case["s1"]*A*b/case["k2"]+case["s2"]*b*b/(2*case["k2"]))
    source_integral = case["s1"]*A+case["s2"]*b
    flux0 = (case["h"]*(case["left_c"]-case["ambient_c"]-source_offset)
             -source_integral)/(1+case["h"]*resistance)
    interface_c = case["left_c"]-(flux0*A+case["s1"]*A*A/2)/case["k1"]
    return flux0, interface_c


def temperature(x, case):
    x = np.asarray(x)
    f0, ti = constants(case)
    z = x-A
    left = case["left_c"]-(f0*x+case["s1"]*x*x/2)/case["k1"]
    right = ti-((f0+case["s1"]*A)*z+case["s2"]*z*z/2)/case["k2"]
    return np.where(x <= A, left, right)


def flux_density(x, case):
    x = np.asarray(x)
    f0, _ = constants(case)
    return f0+case["s1"]*np.minimum(x,A)+case["s2"]*np.maximum(x-A,0.)


def gradient_x(x, case):
    return -flux_density(x,case)/np.where(np.asarray(x) <= A,case["k1"],case["k2"])


def powers(case):
    scale = HEIGHT*THICKNESS
    f0, _ = constants(case)
    return dict(source_w=(case["s1"]*A+case["s2"]*(L-A))*scale,
                left_out_w=-f0*scale, right_out_w=float(flux_density(L,case))*scale,
                interface_right_w=float(flux_density(A,case))*scale)


def norms(case):
    f0, ti = constants(case)
    polynomials = [
        (A,[case["left_c"]-case["ambient_c"],-f0/case["k1"],-case["s1"]/(2*case["k1"])]),
        (L-A,[ti-case["ambient_c"],-(f0+case["s1"]*A)/case["k2"],
              -case["s2"]/(2*case["k2"])]),
    ]
    totals = np.zeros(2)
    for length, coefficients in polynomials:
        derivative = [coefficients[1],2*coefficients[2]]
        for i, poly in enumerate((coefficients,derivative)):
            squared = np.polynomial.polynomial.polymul(poly,poly)
            totals[i] += HEIGHT*sum(v*length**(j+1)/(j+1) for j,v in enumerate(squared))
    return np.sqrt(totals)
