"""Unit hydrographs and the convolutional design matrix used by Stage A."""

from __future__ import annotations

import numpy as np

from .config import STEP_MIN


def exp_kernel(tau_h: float, horizon_factor: float = 5.0) -> np.ndarray:
    """Discrete exponential unit hydrograph on the 5-min grid, sums to 1.

    Parameters
    ----------
    tau_h
        Response time constant in hours.
    horizon_factor
        Truncate the kernel after ``horizon_factor * tau_h`` hours.
    """
    n = int(tau_h * horizon_factor * 60 / STEP_MIN)
    t = np.arange(n) * STEP_MIN / 60.0
    h = np.exp(-t / tau_h)
    return h / h.sum()


def zone_response_columns(
    rain_mm: np.ndarray,
    areas_m2: np.ndarray,
    kernels: list[np.ndarray],
) -> np.ndarray:
    """Build the Stage A design matrix.

    For every zone and every kernel, convolves zone rainfall with the kernel
    and scales by zone area, giving cubic-metres-per-step per unit of capture
    fraction ``a``.

    Parameters
    ----------
    rain_mm
        Shape ``(n_t, n_zones)``. Rainfall in millimetres per 5-min step.
    areas_m2
        Shape ``(n_zones,)``. Drained area per zone in square metres.
    kernels
        List of 1-D kernels, e.g. ``[exp_kernel(1.0), exp_kernel(36.0)]``.

    Returns
    -------
    Shape ``(n_t, n_kernels * n_zones)``. Block layout: all zones for the
    first kernel, then all zones for the second kernel, and so on.
    """
    n_t, n_z = rain_mm.shape
    cols = []
    for h in kernels:
        for z in range(n_z):
            conv = np.convolve(rain_mm[:, z], h)[:n_t]
            cols.append(conv * 1e-3 * areas_m2[z])
    return np.column_stack(cols)
