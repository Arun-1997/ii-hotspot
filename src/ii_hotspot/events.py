"""Segment a continuous rain time series into discrete events for Stage A."""

from __future__ import annotations

import pandas as pd

from .config import STEP_MIN


def segment_events(
    rain: pd.DataFrame,
    min_depth_mm: float = 2.0,
    gap_h: float = 6.0,
) -> list[dict]:
    """Split a ``(time x zone)`` rain matrix into events.

    A wet spell ends when at least ``gap_h`` dry hours pass. Events whose
    maximum zone depth is below ``min_depth_mm`` are discarded.

    Returns a list of dicts with ``start``, ``end``, and ``depth_mm``
    (a Series of per-zone depths).
    """
    mean_rain = rain.mean(axis=1).fillna(0.0)
    wet = mean_rain > 0.05
    gap_steps = int(gap_h * 60 / STEP_MIN)

    events: list[dict] = []
    start: int | None = None
    dry = 0
    for t, w in enumerate(wet.values):
        if w:
            if start is None:
                start = t
            dry = 0
        elif start is not None:
            dry += 1
            if dry >= gap_steps:
                end = t - dry
                depth = rain.iloc[start : end + 1].sum()
                if depth.max() >= min_depth_mm:
                    events.append(
                        {
                            "start": rain.index[start],
                            "end": rain.index[end],
                            "depth_mm": depth,
                        }
                    )
                start, dry = None, 0
    return events
