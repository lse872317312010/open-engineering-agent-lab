"""Frozen pointwise budgets for angular support; failures remain data, not exceptions."""
import numpy as np


def evaluate(actual_flux, predicted_flux, actual_torque, predicted_torque):
    actual = np.asarray(actual_flux, dtype=float)
    predicted = np.asarray(predicted_flux, dtype=float)
    torque = np.asarray(actual_torque, dtype=float)
    estimate = np.asarray(predicted_torque, dtype=float)
    if (actual.ndim != 2 or actual.shape[1] != 2 or len(actual) == 0
            or predicted.shape != actual.shape or torque.shape != (len(actual),)
            or estimate.shape != torque.shape
            or not all(np.isfinite(v).all() for v in (actual, predicted, torque, estimate))):
        raise ValueError("finite Nx2 flux and matching torque vectors required")
    flux_error = np.linalg.norm(actual-predicted, axis=1)/.05
    torque_error = abs(torque-estimate)
    supported = (flux_error <= .02) & (torque_error <= .10)
    return dict(model_supported=bool(np.all(supported)), flux_error=flux_error.tolist(),
                torque_error=torque_error.tolist(), supported=supported.tolist(),
                failed_indices=np.flatnonzero(~supported).tolist())
