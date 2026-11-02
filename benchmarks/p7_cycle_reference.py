"""Frozen integer-tick duty cycle; SI units, external mechanical brake."""
DT_S = 50e-6
TOTAL_TICKS = 40_000
START_TICK = 223
LOAD_CHANGE_TICK = 8003
BRAKE_TICK = 16_000
SETTLED_TICK = 20_000
CHUNK_TICKS = (8753, 18_077)


def cycle_command(tick):
    if type(tick) is not int or not 0 <= tick <= TOTAL_TICKS:
        raise ValueError("integer cycle tick out of range")
    if tick < START_TICK:
        return dict(phase=0, iq_a=0., load_nm=0., brake_nms=1e-5)
    if tick < LOAD_CHANGE_TICK:
        return dict(phase=1, iq_a=.20, load_nm=.015, brake_nms=1e-5)
    if tick < BRAKE_TICK:
        return dict(phase=2, iq_a=.28, load_nm=.035, brake_nms=1e-5)
    return dict(phase=3, iq_a=0., load_nm=0., brake_nms=.04)
