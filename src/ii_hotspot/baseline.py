"""Dry-weather baseline and physics-residual computation for meter flows.

Interim empirical baseline until the SWMM input builder lands: dry-weather
flow is estimated as the median diurnal profile over dry days, split into
weekday and weekend patterns. The residual (observed minus baseline) is the
quantity Stage A unmixes. When the SWMM layer arrives it replaces
:func:`dry_weather_baseline` and the rest of the pipeline is unchanged.
"""

from __future__ import annotations

import pandas as pd

from .config import STEP_MIN


def resample_to_grid(flow: pd.Series, max_gap_steps: int = 6) -> pd.Series:
    """Resample a metered flow series onto the 5-min pipeline grid.

    Values are interpreted as m^3 per step. Gaps up to ``max_gap_steps``
    are linearly interpolated; longer gaps stay NaN so they can be
    excluded downstream rather than invented.
    """
    grid = flow.resample(f"{STEP_MIN}min").mean()
    return grid.interpolate(limit=max_gap_steps)


def wet_mask(
    rain_mean_mm: pd.Series,
    threshold_mm: float = 0.05,
    tail_h: float = 48.0,
) -> pd.Series:
    """True at steps with rain or within ``tail_h`` hours after rain.

    The tail covers the slow-infiltration recession (about
    ``horizon_factor * tau_slow_h`` hours), so steps marked dry carry no
    I&I signal and are safe to learn the dry-weather pattern from.
    """
    wet = (rain_mean_mm.fillna(0.0) > threshold_mm).astype(float)
    steps = int(tail_h * 60 / STEP_MIN)
    return wet.rolling(window=steps + 1, min_periods=1).max().astype(bool)


def dry_weather_baseline(flow: pd.Series, wet: pd.Series) -> pd.Series:
    """Median diurnal dry-weather flow, split weekday/weekend.

    Parameters
    ----------
    flow
        Flow in m^3 per 5-min step, on the pipeline grid.
    wet
        Boolean mask from :func:`wet_mask`, aligned or alignable to ``flow``.

    Returns
    -------
    Baseline series on ``flow.index``. Slots never observed dry (possible
    in short records) fall back to the all-days diurnal median.
    """
    wet_aligned = wet.reindex(flow.index, fill_value=True)
    dry_flow = flow[~wet_aligned].dropna()
    if dry_flow.empty:
        raise ValueError(
            "no dry steps in the record; extend the period or relax wet_mask"
        )

    dry_weekend = dry_flow.index.dayofweek >= 5
    dry_tod = dry_flow.index.hour * 60 + dry_flow.index.minute
    profile = dry_flow.groupby([dry_weekend, dry_tod]).median()

    idx_weekend = flow.index.dayofweek >= 5
    idx_tod = flow.index.hour * 60 + flow.index.minute
    keys = pd.MultiIndex.from_arrays([idx_weekend, idx_tod])
    base = pd.Series(profile.reindex(keys).to_numpy(), index=flow.index)

    if base.isna().any():
        fallback = dry_flow.groupby(dry_tod).median()
        base = base.fillna(
            pd.Series(fallback.reindex(idx_tod).to_numpy(), index=flow.index)
        )
    return base


def residual_series(flow: pd.Series, baseline: pd.Series) -> pd.Series:
    """Observed minus baseline, NaN-safe for Stage A stacking."""
    return (flow - baseline).fillna(0.0)


def meter_residual(flow_raw: pd.Series, rain_mean_mm: pd.Series) -> pd.Series:
    """Convenience wrapper: raw meter series to residual on the rain grid."""
    flow = resample_to_grid(flow_raw).reindex(rain_mean_mm.index)
    wet = wet_mask(rain_mean_mm)
    base = dry_weather_baseline(flow, wet)
    return residual_series(flow, base)


def dry_day_count(wet: pd.Series) -> int:
    """Number of whole days with no wet step -- a QC diagnostic."""
    by_day = wet.groupby(wet.index.floor("D")).any()
    return int((~by_day).sum())


def load_meter_csv(path: str) -> pd.Series:
    """Read a meter flow CSV with columns ``timestamp`` and ``flow_m3``.

    ``timestamp`` must parse as ISO 8601; ``flow_m3`` is the pumped or
    measured volume per record interval. See docs/deployment.md for the
    full input contract.
    """
    df = pd.read_csv(path, parse_dates=["timestamp"])
    if "flow_m3" not in df.columns:
        raise ValueError(f"{path}: expected columns 'timestamp' and 'flow_m3'")
    s = df.set_index("timestamp")["flow_m3"].sort_index()
    return s[~s.index.duplicated(keep="first")].astype(float)
