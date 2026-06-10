"""Stage A: ridge-regularized NNLS unmixing of the per-meter residual."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from .config import Config
from .kernels import exp_kernel, zone_response_columns


def stage_a_unmix(
    rain_mm: np.ndarray,
    areas_m2: np.ndarray,
    residuals: dict[int, np.ndarray],
    meter_zones: dict[int, set[int]],
    n_zones: int,
    cfg: Config,
) -> pd.DataFrame:
    """Recover per-zone fast/slow capture fractions from meter residuals.

    Solves ``a >= 0`` in ``residual_m(t) = X_m a`` jointly over all meters,
    zeroing the columns of zones that are not upstream of meter ``m``.
    Ridge regularization via row augmentation stabilizes the fit when
    neighbouring zones receive the same rain.

    Parameters
    ----------
    rain_mm
        ``(n_t, n_zones)`` rainfall in mm per 5-min step.
    areas_m2
        ``(n_zones,)`` drained area in m^2 per zone.
    residuals
        ``{meter_id: array(n_t,)}`` of observed minus SWMM-expected flow,
        in m^3 per 5-min step.
    meter_zones
        ``{meter_id: set_of_upstream_zone_indices}``.
    n_zones
        Total number of zones.
    cfg
        Configuration (uses ``tau_fast_h``, ``tau_slow_h``, ``ridge``).

    Returns
    -------
    DataFrame with one row per zone and two columns: ``a_fast`` (direct
    inflow capture fraction) and ``a_slow`` (groundwater infiltration
    capture fraction). Both are dimensionless and non-negative.
    """
    kernels = [exp_kernel(cfg.tau_fast_h), exp_kernel(cfg.tau_slow_h)]
    X_full = zone_response_columns(rain_mm, areas_m2, kernels)

    blocks_X, blocks_r = [], []
    for m, resid in residuals.items():
        Xm = X_full.copy()
        mask = np.zeros(n_zones, dtype=bool)
        mask[list(meter_zones[m])] = True
        keep = np.concatenate([mask, mask])  # fast block then slow block
        Xm[:, ~keep] = 0.0
        blocks_X.append(Xm)
        blocks_r.append(resid)

    X = np.vstack(blocks_X)
    r = np.concatenate(blocks_r)

    # Column-scale before NNLS so the ridge penalty is comparable across columns.
    scale = np.linalg.norm(X, axis=0)
    scale[scale == 0] = 1.0
    X_aug = np.vstack([X / scale, cfg.ridge * np.eye(X.shape[1])])
    r_aug = np.concatenate([r, np.zeros(X.shape[1])])

    coef, _ = nnls(X_aug, r_aug, maxiter=10 * X.shape[1])
    coef = coef / scale
    return pd.DataFrame({"a_fast": coef[:n_zones], "a_slow": coef[n_zones:]})
