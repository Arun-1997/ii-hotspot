"""KNMI filename parsing, window seeking, and archive selection (offline)."""

import numpy as np
import pandas as pd

import ii_hotspot.knmi as knmi
from ii_hotspot.config import Config
from ii_hotspot.knmi import (
    _all_timestamps,
    _attr_str,
    _sample,
    _seed_filename,
    files_in_window,
    parse_filename_timestamp,
)

PREFIX = "RAD_NL25_RAC_MFBS_EM_5min_"
# Yearly climatological archive: begin and end timestamp, .zip
ARCHIVE = "RADNL_CLIM_EM_MFBSNL25_05m_{0}T235500_{1}T235500_0002.zip"


def test_parse_plain_timestamp():
    assert parse_filename_timestamp(f"{PREFIX}202409010005.h5") == pd.Timestamp(
        "2024-09-01 00:05"
    )


def test_parse_t_separated_timestamp():
    assert parse_filename_timestamp(f"{PREFIX}20240901T0005.h5") == pd.Timestamp(
        "2024-09-01 00:05"
    )


def test_parse_with_seconds():
    assert parse_filename_timestamp("x_20071231T235500_y.zip") == pd.Timestamp(
        "2007-12-31 23:55:00"
    )


def test_parse_unparseable_is_nat():
    assert parse_filename_timestamp("no_timestamp_here.h5") is pd.NaT


def test_attr_str_handles_knmi_variants():
    formula = "GEO = 0.010000 * PV + 0.000000"
    # bare bytes, numpy str, and the length-1 byte array KNMI actually uses
    assert _attr_str(formula.encode()) == formula
    assert _attr_str(np.str_(formula)) == formula
    assert _attr_str(np.array([formula.encode()])) == formula


def test_sample_applies_calibration_and_masks_nodata():
    img = np.array([[10.0, 65535.0], [20.0, 30.0]])  # (1,1) is the no-data flag
    rows = np.array([0, 0, 1])
    cols = np.array([0, 1, 0])
    ok = np.array([True, True, True])
    out = _sample(img, gain=0.01, offset=0.0, rows=rows, cols=cols, ok=ok)
    assert out[0] == 0.1          # 10 * 0.01
    assert np.isnan(out[1])       # 65535 -> NaN
    assert out[2] == 0.2          # 20 * 0.01


def test_sample_out_of_bounds_points_are_nan():
    img = np.array([[5.0]])
    out = _sample(
        img, 1.0, 0.0,
        rows=np.array([0, 0]), cols=np.array([0, 0]),
        ok=np.array([True, False]),  # second point fell outside the grid
    )
    assert out[0] == 5.0
    assert np.isnan(out[1])


def test_all_timestamps_reads_archive_span():
    stamps = _all_timestamps(ARCHIVE.format("20231231", "20241231"))
    assert stamps == [pd.Timestamp("2023-12-31 23:55"), pd.Timestamp("2024-12-31 23:55")]


def test_seed_filename_preserves_shape():
    seed = _seed_filename(f"{PREFIX}202409010000.h5", pd.Timestamp("2024-08-31 23:55"))
    assert seed == f"{PREFIX}202408312355.h5"


def test_files_in_window_per_slot(monkeypatch):
    all_files = [f"{PREFIX}2024090100{mm:02d}.h5" for mm in (0, 5, 10, 15, 20, 25)]

    def fake_list_files(cfg, max_keys=500, start_after=None):
        if max_keys == 1:
            return [all_files[0]]
        items = all_files
        if start_after is not None:
            items = [f for f in all_files if f > start_after]
        return items[:max_keys]

    monkeypatch.setattr(knmi, "list_files", fake_list_files)
    got = files_in_window(Config(), "2024-09-01 00:05", "2024-09-01 00:20")
    assert got == [
        f"{PREFIX}202409010005.h5",
        f"{PREFIX}202409010010.h5",
        f"{PREFIX}202409010015.h5",
    ]


def test_files_in_window_selects_overlapping_archive(monkeypatch):
    archives = [
        ARCHIVE.format("20221231", "20231231"),  # covers 2023
        ARCHIVE.format("20231231", "20241231"),  # covers 2024  <- want this
        ARCHIVE.format("20241231", "20251231"),  # covers 2025
    ]

    def fake_list_files(cfg, max_keys=500, start_after=None):
        if max_keys == 1:
            return [archives[0]]
        items = archives
        if start_after is not None:
            items = [f for f in archives if f > start_after]
        return items[:max_keys]

    monkeypatch.setattr(knmi, "list_files", fake_list_files)
    got = files_in_window(Config(), "2024-09-01", "2024-12-01")
    assert got == [ARCHIVE.format("20231231", "20241231")]
