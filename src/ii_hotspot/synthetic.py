"""Synthetic validation harness: does Stage A recover injected hotspots?"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import STEPS_PER_DAY, Config
from .kernels import exp_kernel, zone_response_columns
from .stage_a import stage_a_unmix

RNG_DEFAULT_SEED = 42


@dataclass
class SyntheticResult:
    rho_fast: float
    rho_slow: float
    top10_overlap: int
    estimate: pd.DataFrame
    truth_fast: np.ndarray
    truth_slow: np.ndarray


def run_synthetic(
    cfg: Config | None = None,
    n_days: int = 30,
    grid: int = 6,
    n_meters: int = 3,
    noise_frac: float = 0.05,
    n_events: int = 12,
    seed: int = RNG_DEFAULT_SEED,
) -> SyntheticResult:
    """Inject known I&I sources on a synthetic grid and check recovery."""
    cfg = cfg or Config()
    rng = np.random.default_rng(seed)

    n_zones = grid * grid
    n_t = n_days * STEPS_PER_DAY
    centroids = np.array(
        [(1000.0 * (i % grid) + 500, 1000.0 * (i // grid) + 500) for i in range(n_zones)]
    )
    areas = np.full(n_zones, 9.0e4)  # 9 hectares per zone

    # Spatially patchy storms (Gaussian footprints, gamma-shaped intensity).
    rain = np.zeros((n_t, n_zones))
    starts = np.sort(rng.choice(np.arange(n_t - 8 * 12), n_events, replace=False))
    for s in starts:
        centre = rng.uniform(0, grid * 1000.0, 2)
        sigma = rng.uniform(900, 1800)
        footprint = np.exp(
            -np.linalg.norm(centroids - centre, axis=1) ** 2 / (2 * sigma**2)
        )
        dur = rng.integers(12, 60)
        profile = rng.gamma(2.0, 1.0, dur)
        profile *= rng.uniform(4, 22) / profile.sum()  # event depth in mm
        rain[s : s + dur] += np.outer(profile, footprint)

    # Sparse hotspots over a small uniform background.
    a_fast_true = np.full(n_zones, 0.002)
    a_slow_true = np.full(n_zones, 0.001)
    hot_fast = rng.choice(n_zones, 7, replace=False)
    hot_slow = rng.choice(n_zones, 8, replace=False)
    a_fast_true[hot_fast] = rng.uniform(0.02, 0.08, 7)
    a_slow_true[hot_slow] = rng.uniform(0.01, 0.05, 8)

    meter_zones = {
        m: {z for z in range(n_zones) if (z % grid) // (grid // n_meters) == m}
        for m in range(n_meters)
    }

    kernels = [exp_kernel(cfg.tau_fast_h), exp_kernel(cfg.tau_slow_h)]
    X = zone_response_columns(rain, areas, kernels)
    truth = np.concatenate([a_fast_true, a_slow_true])

    residuals = {}
    for m, zs in meter_zones.items():
        mask = np.zeros(n_zones, dtype=bool)
        mask[list(zs)] = True
        keep = np.concatenate([mask, mask])
        signal = X[:, keep] @ truth[keep]
        residuals[m] = signal + rng.normal(0, noise_frac * signal.std(), n_t)

    est = stage_a_unmix(rain, areas, residuals, meter_zones, n_zones, cfg)

    rho_f = float(spearmanr(a_fast_true, est["a_fast"]).statistic)
    rho_s = float(spearmanr(a_slow_true, est["a_slow"]).statistic)
    top_true = set(np.argsort(a_fast_true + a_slow_true)[-10:])
    top_est = set(np.argsort((est["a_fast"] + est["a_slow"]).values)[-10:])

    return SyntheticResult(
        rho_fast=rho_f,
        rho_slow=rho_s,
        top10_overlap=len(top_true & top_est),
        estimate=est,
        truth_fast=a_fast_true,
        truth_slow=a_slow_true,
    )
