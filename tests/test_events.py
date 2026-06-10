"""Tests for ``ii_hotspot.events``."""

import numpy as np
import pandas as pd

from ii_hotspot.events import segment_events


def test_segments_two_storms_separated_by_dry_gap():
    idx = pd.date_range("2025-01-01", periods=600, freq="5min")  # ~2 days
    rain = np.zeros((600, 2))
    rain[10:40] = 1.5    # storm 1
    rain[400:430] = 2.0  # storm 2 -- well past a 6h gap (72 steps)
    df = pd.DataFrame(rain, index=idx)
    events = segment_events(df, min_depth_mm=2.0, gap_h=6.0)
    assert len(events) == 2
    assert events[0]["start"] < events[1]["start"]


def test_skips_events_below_min_depth():
    idx = pd.date_range("2025-01-01", periods=200, freq="5min")
    rain = np.zeros((200, 1))
    rain[10:15] = 0.1  # total = 0.5 mm
    df = pd.DataFrame(rain, index=idx)
    assert segment_events(df, min_depth_mm=2.0) == []
