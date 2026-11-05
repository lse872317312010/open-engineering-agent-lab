"""Periodic zero-current coenergy coupled to a dq electrical and mechanical plant."""
import math

import numpy as np

PERIOD = math.pi/4
JROT = np.array([[0., -1.], [1., 0.]])


class FourierSeries:
    def __init__(self, a, b):
        self.a = np.asarray(a, dtype=float).copy()
        self.b = np.asarray(b, dtype=float).copy()
        if (self.a.ndim != 2 or self.a.shape != self.b.shape or self.a.shape[0] != 7
                or not np.isfinite(self.a).all() or not np.isfinite(self.b).all()
                or np.any(self.b[0] != 0)):
            raise ValueError("finite 7 by N Fourier coefficients required")
        self.a.flags.writeable = False
        self.b.flags.writeable = False

    @classmethod
    def fit(cls, values, zero_mean=False):
        values = np.asarray(values, dtype=float)
        if values.ndim != 2 or values.shape[0] != 16 or not np.isfinite(values).all():
            raise ValueError("16 finite periodic training samples required")
        transform = np.fft.rfft(values, axis=0)/16
        a, b = 2*transform[:7].real, -2*transform[:7].imag
        a[0] = 0 if zero_mean else transform[0].real
        b[0] = 0
        return cls(a, b)

    @staticmethod
    def angle(theta):
        if not math.isfinite(theta):
            raise ValueError("finite angle required")
        return theta % PERIOD

    def value(self, theta):
        angle = self.angle(theta)
        harmonic = np.arange(7)*8
        return np.cos(harmonic*angle)@self.a+np.sin(harmonic*angle)@self.b

    def derivative(self, theta):
        angle = self.angle(theta)
        harmonic = np.arange(7)*8
        return (-harmonic*np.sin(harmonic*angle))@self.a+(
            harmonic*np.cos(harmonic*angle))@self.b

    def integral(self, theta):
        angle = self.angle(theta)
        harmonic = np.arange(1, 7)*8
        return self.a[0]*angle+(np.sin(harmonic*angle)/harmonic)@self.a[1:]+(
            (1-np.cos(harmonic*angle))/harmonic)@self.b[1:]


class CoggingMotor:
    def __init__(self, psi, torque, inductance, resistance=.3, inertia=.01, friction=.002):
        self.psi, self.cog = psi, torque
        self.inductance = np.asarray(inductance, dtype=float).copy()
        if (self.psi.a.shape[1] != 2 or self.cog.a.shape[1] != 1
                or abs(float(self.cog.a[0, 0])) > 1e-14
                or self.inductance.shape != (2, 2)
                or not np.isfinite(self.inductance).all()
                or not np.allclose(self.inductance, self.inductance.T, atol=1e-14, rtol=0)
                or np.min(np.linalg.eigvalsh(self.inductance)) <= 0
                or not all(math.isfinite(v) for v in (resistance, inertia, friction))
                or resistance < 0 or inertia <= 0 or friction < 0):
            raise ValueError("valid motor, positive L/inertia and nonnegative R/B required")
        self.resistance, self.inertia, self.friction = resistance, inertia, friction

    @staticmethod
    def current(value):
        i = np.asarray(value, dtype=float)
        if i.shape != (2,) or not np.isfinite(i).all() or np.sum(abs(i)) > 2:
            raise ValueError("current must be finite and satisfy abs(id)+abs(iq)<=2")
        return i

    def flux(self, theta, current):
        i = self.current(current)
        return self.psi.value(theta)+self.inductance@i

    def torque(self, theta, current):
        i = self.current(current)
        flux = self.flux(theta, i)
        increment = 1.5*np.dot(i, self.psi.derivative(theta)+4*JROT@flux)
        cog = float(self.cog.value(theta)[0])
        return cog+float(increment), cog, float(increment)

    def stored(self, theta, current):
        i = self.current(current)
        return float(.75*i@self.inductance@i-self.cog.integral(theta)[0])

    def rhs(self, theta, omega, current, voltage, load):
        i = self.current(current)
        v = np.asarray(voltage, dtype=float)
        if (v.shape != (2,) or not np.isfinite(v).all()
                or not math.isfinite(omega) or not math.isfinite(load)):
            raise ValueError("finite speed, voltage and load required")
        flux = self.flux(theta, i)
        electrical = np.linalg.solve(self.inductance, v-self.resistance*i
                                     -omega*(self.psi.derivative(theta)+4*JROT@flux))
        torque, _, _ = self.torque(theta, i)
        acceleration = (torque-self.friction*omega-load)/self.inertia
        return electrical, float(omega), float(acceleration)

    def powers(self, theta, omega, current, voltage, load):
        i = self.current(current)
        return np.array([1.5*np.dot(voltage, i), 1.5*self.resistance*np.dot(i, i),
                         self.friction*omega*omega, load*omega])
