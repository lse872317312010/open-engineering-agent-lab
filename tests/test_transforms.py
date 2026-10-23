import math
from unittest import TestCase

from oeal.transforms import clarke, inverse_clarke, inverse_park, park


class TransformTests(TestCase):
    def assertVectorAlmostEqual(self, actual, expected):
        for value, reference in zip(actual, expected, strict=True):
            self.assertAlmostEqual(value, reference, places=12)

    def test_known_phase_axes_and_zero_sequence(self):
        self.assertVectorAlmostEqual(clarke(1.0, -0.5, -0.5), (1.0, 0.0, 0.0))
        root = math.sqrt(3.0) / 2.0
        self.assertVectorAlmostEqual(clarke(0.0, root, -root), (0.0, 1.0, 0.0))
        self.assertVectorAlmostEqual(clarke(4.0, 4.0, 4.0), (0.0, 0.0, 4.0))

    def test_balanced_sinusoid_aligns_with_rotor_d_axis(self):
        for angle in (-2.3, 0.0, 0.7, math.pi / 2, 7.0):
            phases = tuple(
                3.0 * math.cos(angle + offset)
                for offset in (0.0, -2.0 * math.pi / 3.0, 2.0 * math.pi / 3.0)
            )
            alpha, beta, zero = clarke(*phases)
            self.assertVectorAlmostEqual(park(alpha, beta, angle), (3.0, 0.0))
            self.assertAlmostEqual(zero, 0.0)

    def test_positive_q_axis_and_electrical_angle_sign(self):
        self.assertVectorAlmostEqual(park(0.0, 2.0, 0.0), (0.0, 2.0))
        self.assertVectorAlmostEqual(park(2.0, 0.0, math.pi / 2.0), (0.0, -2.0))
        self.assertVectorAlmostEqual(inverse_park(0.0, 2.0, math.pi / 2.0), (-2.0, 0.0))

    def test_unbalanced_round_trip_preserves_zero_sequence(self):
        for phases in ((2.0, -3.0, 5.0), (0.0, 0.0, 0.0), (-7.0, 2.0, 1.0)):
            self.assertVectorAlmostEqual(inverse_clarke(*clarke(*phases)), phases)
        self.assertVectorAlmostEqual(inverse_clarke(1.0, 0.0), (1.0, -0.5, -0.5))

    def test_rotation_round_trip_and_norm(self):
        for angle in (-8.0, 0.0, 1.2, 2.0 * math.pi):
            d, q = park(2.0, -3.0, angle)
            self.assertVectorAlmostEqual(inverse_park(d, q, angle), (2.0, -3.0))
            self.assertAlmostEqual(d * d + q * q, 13.0)

    def test_instantaneous_power_includes_zero_sequence(self):
        voltage = (4.0, -2.0, 7.0)
        current = (-1.0, 3.0, 2.0)
        va, vb, v0 = clarke(*voltage)
        ia, ib, i0 = clarke(*current)
        vd, vq = park(va, vb, 0.73)
        id_a, iq_a = park(ia, ib, 0.73)
        abc_power = sum(v * i for v, i in zip(voltage, current, strict=True))
        self.assertAlmostEqual(abc_power, 1.5 * (vd * id_a + vq * iq_a) + 3.0 * v0 * i0)

    def test_nonfinite_inputs_are_rejected_at_every_position(self):
        for function, arity in (
            (clarke, 3), (inverse_clarke, 3), (park, 3), (inverse_park, 3)
        ):
            for index in range(arity):
                for invalid in (math.nan, math.inf, -math.inf):
                    values = [0.0] * arity
                    values[index] = invalid
                    with self.subTest(function=function.__name__, index=index, invalid=invalid):
                        with self.assertRaisesRegex(ValueError, "finite"):
                            function(*values)
