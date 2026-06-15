"""Generate synthetic meter telemetry for a real network and real rain.

Bridges a pilot that has the open data (PDOK network, KNMI rain) but not
yet a meter-data-sharing agreement with the water authority. It injects
known hotspots into the *real* zone topology, pushes the *real* rain
through the forward model, adds a dry-weather diurnal and noise, and
writes per-meter flow CSVs in the standard input format. The full
pipeline then produces a deliverable on real geography.

The output is SYNTHETIC and must never be presented as measured data.
Its purpose is integration testing and demonstration, and -- because the
injected hotspots are known -- validating recovery on the real network.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .kernels import exp_kernel, zone_response_columns


def simulate_meter_csvs(
    run,
    rain: pd.DataFrame,
    net: dict,
    seed: int = 42,
    noise_frac: float = 0.05,
) -> tuple[dict[int, str], dict]:
    """Write synthetic meter CSVs for ``run.meters``; return paths + truth.

    Parameters
    ----------
    run
        The loaded :class:`~ii_hotspot.pipeline.RunConfig`.
    rain
        The (time x zone) rain matrix from the rain stage.
    net
        The dict returned by ``network_stage`` (zones, areas, meter_zones).
    """
    cfg = run.cfg
    rng = np.random.default_rng(seed)
    n_zones = net["n_zones"]
    areas = net["areas_m2"]
    meter_zones = net["meter_zones"]

    covered = sorted(set().union(*meter_zones.values())) if meter_zones else []
    if not covered:
        raise ValueError(
            "no zones lie upstream of any meter; check meter coordinates and bbox"
        )

    kernels = [exp_kernel(cfg.tau_fast_h), exp_kernel(cfg.tau_slow_h)]
    X = zone_response_columns(rain.to_numpy(), areas, kernels)

    # Sparse hotspots over a small background, restricted to observable zones.
    a_fast = np.full(n_zones, 0.002)
    a_slow = np.full(n_zones, 0.001)
    n_hot = max(1, len(covered) // 3)
    hot_fast = rng.choice(covered, size=n_hot, replace=False)
    hot_slow = rng.choice(covered, size=n_hot, replace=False)
    a_fast[hot_fast] = rng.uniform(0.02, 0.08, n_hot)
    a_slow[hot_slow] = rng.uniform(0.01, 0.05, n_hot)
    truth = np.concatenate([a_fast, a_slow])

    idx = rain.index
    tod = np.asarray(idx.hour) * 60 + np.asarray(idx.minute)
    weekend = (np.asarray(idx.dayofweek) >= 5).astype(float)

    written: dict[int, str] = {}
    for m in run.meters:
        mask = np.zeros(n_zones, dtype=bool)
        mask[list(meter_zones[m.meter_id])] = True
        keep = np.concatenate([mask, mask])
        signal = X[:, keep] @ truth[keep]  # m^3/step of injected I&I

        scale = max(float(signal.std()), 1.0)
        diurnal = 8.0 * scale * (1.0 + 0.3 * np.sin(2 * np.pi * tod / 1440) - 0.15 * weekend)
        noise = rng.normal(0.0, noise_frac * scale, len(idx))
        flow = np.clip(diurnal + signal + noise, 0.0, None)

        os.makedirs(os.path.dirname(m.flow_csv) or ".", exist_ok=True)
        pd.DataFrame({"timestamp": idx, "flow_m3": flow}).to_csv(m.flow_csv, index=False)
        written[m.meter_id] = m.flow_csv

    truth_df = pd.DataFrame({"a_fast": a_fast, "a_slow": a_slow})
    return written, {
        "hot_fast_zones": sorted(int(z) for z in hot_fast),
        "hot_slow_zones": sorted(int(z) for z in hot_slow),
        "truth": truth_df,
    }
