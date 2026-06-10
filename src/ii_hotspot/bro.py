"""BRO groundwater monitoring loaders (public REST services).

The REST services at ``publiek.broservices.nl`` are designed for incidental
lookups, not bulk pulls. For a full-municipality history, download the GLD
dataset via PDOK / Nationaal Georegister and load it locally; keep these
helpers for spot checks and demos.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

GMW_BASE = "https://publiek.broservices.nl/gm/gmw/v1"
GLD_BASE = "https://publiek.broservices.nl/gm/gld/v1"


def fetch_gmw_wells(bbox_wgs84: tuple[float, float, float, float]) -> pd.DataFrame:
    """Monitoring wells inside ``(lat_min, lon_min, lat_max, lon_max)``.

    Consult ``{GMW_BASE}/swagger-ui`` for the exact request schema of the
    deployed API version; the body below matches the bounding-box variant
    of the characteristics search.
    """
    import requests

    body = {
        "area": {
            "boundingBox": {
                "lowerCorner": {"lat": bbox_wgs84[0], "lon": bbox_wgs84[1]},
                "upperCorner": {"lat": bbox_wgs84[2], "lon": bbox_wgs84[3]},
            }
        }
    }
    r = requests.post(f"{GMW_BASE}/characteristics/searches", json=body, timeout=60)
    r.raise_for_status()
    docs = r.json().get("characteristics", r.json())
    return pd.json_normalize(docs)


def idw_groundwater_to_zones(
    wells_xy: np.ndarray,
    well_levels: np.ndarray,
    zone_centroids: np.ndarray,
    power: float = 2.0,
) -> np.ndarray:
    """Inverse-distance interpolation of groundwater head (m NAP) to zones.

    Combine the result with pipe invert levels to derive the
    "fraction of network length below the water table" feature, which is the
    strongest single static predictor of slow infiltration.
    """
    d = np.linalg.norm(zone_centroids[:, None, :] - wells_xy[None, :, :], axis=2)
    w = 1.0 / np.maximum(d, 1.0) ** power
    return (w * well_levels[None, :]).sum(1) / w.sum(1)
