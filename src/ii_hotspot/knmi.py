"""KNMI Open Data Platform radar loader (5-min, 1-km, gauge-adjusted)."""

from __future__ import annotations

import os
import re
import tempfile
import time
import zipfile

import numpy as np
import pandas as pd

from .config import STEP_MIN, Config

# KNMI radar grids use a polar-stereographic CRS whose ellipsoid is given
# in kilometres; modern PROJ otherwise refuses to mix it with an Earth CRS
# ("non-Earth body"). The transform is correct because the grid is in km too.
os.environ.setdefault("PROJ_IGNORE_CELESTIAL_BODY", "YES")

KNMI_BASE = "https://api.dataplatform.knmi.nl/open-data/v1"

# Radar filenames embed times as YYYYMMDD[T]hhmm or YYYYMMDD[T]hhmmss.
# Per-slot files carry one timestamp; the climatological product ships
# yearly ZIP archives whose names carry a begin and an end timestamp.
# Match anywhere rather than relying on a fixed split position.
_TS_RE = re.compile(r"(\d{8})T?(\d{6}|\d{4})")


def _to_ts(date: str, clock: str) -> pd.Timestamp:
    if len(clock) == 4:
        clock += "00"
    return pd.to_datetime(date + clock, format="%Y%m%d%H%M%S", errors="coerce")


def parse_filename_timestamp(filename: str) -> pd.Timestamp:
    """Extract the (first) slot timestamp from a radar filename, or NaT."""
    m = _TS_RE.search(filename)
    return _to_ts(m.group(1), m.group(2)) if m else pd.NaT


def _all_timestamps(filename: str) -> list[pd.Timestamp]:
    """Every timestamp in a filename (archives carry begin and end)."""
    return [_to_ts(d, c) for d, c in _TS_RE.findall(filename)]


def _is_archive(filename: str) -> bool:
    return filename.lower().endswith(".zip")


def _seed_filename(sample: str, ts: pd.Timestamp) -> str | None:
    """A filename like ``sample`` but with its timestamp set to ``ts``.

    Used as ``startAfterFilename`` so listing of per-slot datasets jumps
    straight to the run window instead of scanning from the archive start.
    """
    m = _TS_RE.search(sample)
    if not m:
        return None
    has_t = "T" in m.group(0)
    secs = len(m.group(2)) == 6
    fmt = "%Y%m%d" + ("T" if has_t else "") + ("%H%M%S" if secs else "%H%M")
    return sample[: m.start()] + ts.strftime(fmt) + sample[m.end() :]


def _archives_in_window(cfg: Config, start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    """Yearly archives whose covered span (begin, end] overlaps the window."""
    wanted: list[str] = []
    after: str | None = None
    while True:
        page = list_files(cfg, start_after=after)
        if not page:
            break
        for fn in page:
            stamps = _all_timestamps(fn)
            if not stamps:
                continue
            begin, finish = stamps[0], stamps[-1]
            if finish >= start and begin < end:
                wanted.append(fn)
        last = _all_timestamps(page[-1])
        if last and last[0] >= end:  # archives are sorted by begin time
            break
        after = page[-1]
    return wanted


def files_in_window(cfg: Config, start, end) -> list[str]:
    """Dataset entries covering ``[start, end)``.

    Detects the delivery format from the first listed name: per-slot
    datasets return one filename per 5-min step (seeking to the window);
    the climatological product returns the yearly ZIP archives that
    contain the window.
    """
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)

    first = list_files(cfg, max_keys=1)
    if not first:
        return []
    if _is_archive(first[0]):
        return _archives_in_window(cfg, start, end)

    after = _seed_filename(first[0], start - pd.Timedelta(minutes=STEP_MIN))
    wanted: list[str] = []
    while True:
        page = list_files(cfg, start_after=after)
        if not page:
            break
        passed_window = False
        for fn in page:
            ts = parse_filename_timestamp(fn)
            if ts is pd.NaT:
                continue
            if ts >= end:
                passed_window = True
                break
            if ts >= start:
                wanted.append(fn)
        if passed_window:
            break
        after = page[-1]
    return wanted


def _get(
    url: str,
    headers: dict | None = None,
    params: dict | None = None,
    timeout: int = 60,
    attempts: int = 3,
    wait_s: float = 5.0,
):
    """GET with retries on transient failures; clear errors otherwise."""
    import requests  # local import keeps the package importable without it

    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            if 400 <= r.status_code < 500:
                raise RuntimeError(
                    f"KNMI request rejected ({r.status_code}); check KNMI_API_KEY "
                    "and the dataset name/version in the config"
                )
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if attempt == attempts:
                raise RuntimeError(
                    f"KNMI unreachable after {attempts} attempts: {e}"
                ) from e
            print(f"knmi: attempt {attempt} failed ({e}); retrying in {wait_s:.0f}s")
            time.sleep(wait_s)
    raise AssertionError("unreachable")


def list_files(
    cfg: Config,
    max_keys: int = 500,
    start_after: str | None = None,
) -> list[str]:
    """List filenames in the configured KNMI dataset (single page)."""
    url = f"{KNMI_BASE}/datasets/{cfg.knmi_dataset}/versions/{cfg.knmi_version}/files"
    params = {"maxKeys": max_keys}
    if start_after:
        params["startAfterFilename"] = start_after
    r = _get(url, headers={"Authorization": cfg.knmi_api_key}, params=params)
    return [f["filename"] for f in r.json().get("files", [])]


def download_file(cfg: Config, filename: str, dest_dir: str = "data/radar") -> str:
    """Resolve the temporary download URL for one file and fetch it."""
    os.makedirs(dest_dir, exist_ok=True)
    url = (
        f"{KNMI_BASE}/datasets/{cfg.knmi_dataset}/versions/{cfg.knmi_version}"
        f"/files/{filename}/url"
    )
    r = _get(url, headers={"Authorization": cfg.knmi_api_key})
    dl = _get(r.json()["temporaryDownloadUrl"], timeout=120)
    path = os.path.join(dest_dir, filename)
    with open(path, "wb") as fh:
        fh.write(dl.content)
    return path


def _attr_str(value) -> str:
    """Decode an HDF5 attribute to str.

    KNMI stores these inconsistently: a bare byte string, a numpy str,
    or a length-1 numpy array wrapping a byte string. Normalize all of
    them to a plain Python string.
    """
    if isinstance(value, np.ndarray):
        value = value.flat[0] if value.size else b""
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode()
    return str(value)


def grid_mapping(
    h5_path: str, points_rd: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map RD New points to radar pixel (row, col) and an in-bounds mask.

    The projection metadata is identical across every slot of a dataset
    version, so this is computed once and reused for all slots rather than
    rebuilding the (expensive) pyproj transformer per file.
    """
    import h5py
    from pyproj import Transformer

    with h5py.File(h5_path, "r") as f:
        shape = f["image1"]["image_data"].shape
        geo = f["geographic"]
        col_off = float(geo.attrs["geo_column_offset"][0])
        row_off = float(geo.attrs["geo_row_offset"][0])
        psx = float(geo.attrs["geo_pixel_size_x"][0])
        psy = float(geo.attrs["geo_pixel_size_y"][0])
        proj4 = _attr_str(geo["map_projection"].attrs["projection_proj4_params"])

    tf = Transformer.from_crs("EPSG:28992", proj4, always_xy=True)
    x_km, y_km = tf.transform(points_rd[:, 0], points_rd[:, 1])
    cols = np.round(np.asarray(x_km) / psx - col_off).astype(int)
    rows = np.round(np.asarray(y_km) / psy - row_off).astype(int)
    ok = (rows >= 0) & (rows < shape[0]) & (cols >= 0) & (cols < shape[1])
    return rows, cols, ok


def _read_calibrated_image(h5_path: str) -> tuple[np.ndarray, float, float]:
    """Image array plus the file's own gain/offset calibration."""
    import h5py

    with h5py.File(h5_path, "r") as f:
        img = f["image1"]["image_data"][:].astype(float)
        calib = _attr_str(
            f["image1"]["calibration"].attrs.get(
                "calibration_formulas", b"GEO = 0.010000 * PV + 0.000000"
            )
        )
    gain = float(calib.split("=")[1].split("*")[0])
    offset = float(calib.split("+")[1])
    return img, gain, offset


def _sample(
    img: np.ndarray,
    gain: float,
    offset: float,
    rows: np.ndarray,
    cols: np.ndarray,
    ok: np.ndarray,
) -> np.ndarray:
    """Apply a precomputed pixel mapping and calibration to one image."""
    vals = np.full(len(rows), np.nan)
    raw = img[rows[ok], cols[ok]]
    raw[raw == 65535] = np.nan
    vals[ok] = raw * gain + offset
    return vals


def rain_at_points(h5_path: str, points_rd: np.ndarray) -> np.ndarray:
    """mm of rain in this 5-min file at N points given in RD New (EPSG:28992).

    Reads the calibration formula and projection metadata from the HDF5 file
    rather than hardcoding them, so it survives the algorithm-revision dates
    documented at the KNMI Data Platform.
    """
    rows, cols, ok = grid_mapping(h5_path, points_rd)
    img, gain, offset = _read_calibrated_image(h5_path)
    return _sample(img, gain, offset, rows, cols, ok)


def _rain_from_archive(
    zip_path: str,
    points_rd: np.ndarray,
    start: pd.Timestamp,
    end: pd.Timestamp,
    mapping: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> tuple[list[np.ndarray], list[pd.Timestamp], tuple | None]:
    """Extract the in-window 5-min slots from one yearly ZIP archive.

    Members are read and written to a temp file one at a time (h5py needs
    a real path), so the whole archive is never expanded to disk at once.
    The pixel ``mapping`` is computed from the first slot and reused (and
    returned) so multi-archive windows share one transform.
    """
    rows, idx = [], []
    with zipfile.ZipFile(zip_path) as zf:
        members = sorted(n for n in zf.namelist() if not n.endswith("/"))
        for name in members:
            ts = parse_filename_timestamp(name)
            if ts is pd.NaT or not (start <= ts < end):
                continue
            with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
                tmp.write(zf.read(name))
                tmp_path = tmp.name
            try:
                if mapping is None:
                    mapping = grid_mapping(tmp_path, points_rd)
                img, gain, offset = _read_calibrated_image(tmp_path)
                rows.append(_sample(img, gain, offset, *mapping))
                idx.append(ts)
            finally:
                os.remove(tmp_path)
    return rows, idx, mapping


def build_zone_rain_series(
    cfg: Config,
    zone_centroids_rd: np.ndarray,
    start,
    end,
) -> pd.DataFrame:
    """Assemble the (time x zone) rain matrix for ``[start, end)``.

    Resolves the dataset entries covering the window and handles both
    delivery formats: per-slot HDF5 files, or yearly ZIP archives that
    are downloaded, streamed slot-by-slot, then deleted to free disk.
    """
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    names = files_in_window(cfg, start, end)
    if not names:
        return pd.DataFrame()

    rows: list[np.ndarray] = []
    idx: list[pd.Timestamp] = []
    mapping: tuple | None = None
    if _is_archive(names[0]):
        for i, fn in enumerate(names, 1):
            print(f"knmi: archive {i}/{len(names)}: {fn}")
            path = download_file(cfg, fn)
            try:
                r, ix, mapping = _rain_from_archive(
                    path, zone_centroids_rd, start, end, mapping
                )
            finally:
                os.remove(path)  # yearly archives are large; don't keep them
            rows += r
            idx += ix
            print(f"knmi: extracted {len(ix)} slots from archive {i}")
    else:
        for i, fn in enumerate(names, 1):
            path = download_file(cfg, fn)
            if mapping is None:
                mapping = grid_mapping(path, zone_centroids_rd)
            img, gain, offset = _read_calibrated_image(path)
            rows.append(_sample(img, gain, offset, *mapping))
            idx.append(parse_filename_timestamp(fn))
            if i % 500 == 0 or i == len(names):
                print(f"knmi: {i}/{len(names)} files")
    return pd.DataFrame(rows, index=idx).sort_index()
