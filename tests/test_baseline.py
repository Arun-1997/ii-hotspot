"""Dry-weather baseline: does residual extraction isolate the wet response?"""

import numpy as np
import pandas as pd

from ii_hotspot.baseline import (
    dry_day_count,
    dry_weather_baseline,
    load_meter_csv,
    meter_residual,
    resample_to_grid,
    wet_mask,
)
from ii_hotspot.config import STEPS_PER_DAY


def _diurnal_flow(index: pd.DatetimeIndex) -> pd.Series:
    """Synthetic dry-weather flow: sinusoidal diurnal cycle, weekend dip."""
    tod = index.hour * 60 + index.minute
    base = 10.0 + 3.0 * np.sin(2 * np.pi * tod / (24 * 60))
    weekend = (index.dayofweek >= 5).astype(float)
    return pd.Series(base * (1.0 - 0.2 * weekend), index=index)


def test_baseline_recovers_diurnal_pattern():
    idx = pd.date_range("2024-01-01", periods=21 * STEPS_PER_DAY, freq="5min")
    flow = _diurnal_flow(idx)
    rain = pd.Series(0.0, index=idx)
    rain.iloc[1000:1050] = 1.0  # one storm

    base = dry_weather_baseline(flow, wet_mask(rain))
    # Away from the storm the baseline should match the true pattern closely.
    err = (flow - base).iloc[3000:].abs().max()
    assert err < 1e-6


def test_residual_isolates_storm_response():
    idx = pd.date_range("2024-01-01", periods=21 * STEPS_PER_DAY, freq="5min")
    flow = _diurnal_flow(idx)
    rain = pd.Series(0.0, index=idx)
    rain.iloc[1000:1050] = 1.0
    spike = np.zeros(len(idx))
    spike[1000:1200] = 5.0  # injected I&I response during/after the storm

    resid = meter_residual(flow + spike, rain)
    assert resid.iloc[1000:1200].mean() > 4.0
    assert abs(resid.iloc[4000:].mean()) < 0.1


def test_wet_mask_extends_past_rain():
    idx = pd.date_range("2024-01-01", periods=5 * STEPS_PER_DAY, freq="5min")
    rain = pd.Series(0.0, index=idx)
    rain.iloc[10] = 2.0
    wet = wet_mask(rain, tail_h=48.0)
    assert bool(wet.iloc[10])
    assert bool(wet.iloc[10 + 12 * 24])       # still wet 24 h later
    assert not bool(wet.iloc[10 + 12 * 49])   # dry again after the 48 h tail
    assert dry_day_count(wet) == 2


def test_resample_leaves_long_gaps_nan():
    idx = pd.date_range("2024-01-01", periods=200, freq="5min")
    flow = pd.Series(1.0, index=idx)
    flow.iloc[50:80] = np.nan  # 150-min gap > 30-min interpolation limit
    grid = resample_to_grid(flow)
    assert grid.isna().any()


def test_load_meter_csv_roundtrip(tmp_path):
    p = tmp_path / "meter.csv"
    p.write_text(
        "timestamp,flow_m3\n2024-01-01T00:00:00,1.5\n2024-01-01T00:05:00,2.0\n"
    )
    s = load_meter_csv(str(p))
    assert len(s) == 2
    assert s.iloc[1] == 2.0
