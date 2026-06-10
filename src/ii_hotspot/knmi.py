"""KNMI Open Data Platform radar loader (5-min, 1-km, gauge-adjusted)."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .config import Config

KNMI_BASE = "https://api.dataplatform.knmi.nl/open-data/v1"


def list_files(
    cfg: Config,
    max_keys: int = 500,
    start_after: str | None = None,
) -> list[str]:
    """List filenames in the configured KNMI dataset (single page)."""
    import requests  # local import keeps the package importable without it

    url = f"{KNMI_BASE}/datasets/{cfg.knmi_dataset}/versions/{cfg.knmi_version}/files"
    params = {"maxKeys": max_keys}
    if start_after:
        params["startAfterFilename"] = start_after
    r = requests.get(
        url, headers={"Authorization": cfg.knmi_api_key}, params=params, timeout=60
    )
    r.raise_for_status()
    return [f["filename"] for f in r.json().get("files", [])]


def download_file(cfg: Config, filename: str, dest_dir: str = "data/radar") -> str:
    """Resolve the temporary download URL for one file and fetch it."""
    import requests

    os.makedirs(dest_dir, exist_ok=True)
    url = (
        f"{KNMI_BASE}/datasets/{cfg.knmi_dataset}/versions/{cfg.knmi_version}"
        f"/files/{filename}/url"
    )
    r = requests.get(url, headers={"Authorization": cfg.knmi_api_key}, timeout=60)
    r.raise_for_status()
    dl = requests.get(r.json()["temporaryDownloadUrl"], timeout=120)
    dl.raise_for_status()
    path = os.path.join(dest_dir, filename)
    with open(path, "wb") as fh:
        fh.write(dl.content)
    return path


def rain_at_points(h5_path: str, points_rd: np.ndarray) -> np.ndarray:
    """mm of rain in this 5-min file at N points given in RD New (EPSG:28992).

    Reads the calibration formula and projection metadata from the HDF5 file
    rather than hardcoding them, so it survives the algorithm-revision dates
    documented at the KNMI Data Platform.
    """
    import h5py
    from pyproj import Transformer

    with h5py.File(h5_path, "r") as f:
        img = f["image1"]["image_data"][:].astype(float)
        calib = f["image1"]["calibration"].attrs.get(
            "calibration_formulas", b"GEO = 0.010000 * PV + 0.000000"
        )
        if isinstance(calib, (bytes, np.bytes_)):
            calib = calib.decode()
        gain = float(calib.split("=")[1].split("*")[0])
        offset = float(calib.split("+")[1])
        geo = f["geographic"]
        col_off = float(geo.attrs["geo_column_offset"][0])
        row_off = float(geo.attrs["geo_row_offset"][0])
        psx = float(geo.attrs["geo_pixel_size_x"][0])
        psy = float(geo.attrs["geo_pixel_size_y"][0])
        proj4 = geo["map_projection"].attrs["projection_proj4_params"]
        if isinstance(proj4, (bytes, np.bytes_)):
            proj4 = proj4.decode()

    tf = Transformer.from_crs("EPSG:28992", proj4, always_xy=True)
    x_km, y_km = tf.transform(points_rd[:, 0], points_rd[:, 1])
    cols = np.round(np.asarray(x_km) / psx - col_off).astype(int)
    rows = np.round(np.asarray(y_km) / psy - row_off).astype(int)
    vals = np.full(len(points_rd), np.nan)
    ok = (rows >= 0) & (rows < img.shape[0]) & (cols >= 0) & (cols < img.shape[1])
    raw = img[rows[ok], cols[ok]]
    raw[raw == 65535] = np.nan
    vals[ok] = raw * gain + offset
    return vals


def build_zone_rain_series(
    cfg: Config,
    zone_centroids_rd: np.ndarray,
    filenames: list[str],
) -> pd.DataFrame:
    """Download a list of radar files and assemble a (time x zone) rain matrix."""
    rows, idx = [], []
    for fn in filenames:
        path = download_file(cfg, fn)
        rows.append(rain_at_points(path, zone_centroids_rd))
        idx.append(
            pd.to_datetime(
                fn.split("_")[-1].split(".")[0], format="%Y%m%d%H%M", errors="coerce"
            )
        )
    return pd.DataFrame(rows, index=idx).sort_index()
