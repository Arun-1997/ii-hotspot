"""Automated GWSW network download from the PDOK national OGC API.

Replaces the manual per-municipality GeoPackage download: given the pilot
bounding box, fetches sewer pipes from the national "Beheer Stedelijk
Watersystemen (GWSW)" service published by Stichting RIONED on PDOK and
writes a GeoPackage that ``gwsw.load_sewer_network`` reads directly.
The service is open data (no API key) and natively serves EPSG:28992.
"""

from __future__ import annotations

import os
import time

PDOK_GWSW_BASE = "https://api.pdok.nl/rioned/beheer-stedelijk-watersystemen-gwsw/ogc/v1"
CRS_RD = "http://www.opengis.net/def/crs/EPSG/0/28992"
PAGE_LIMIT = 1000


def _get_json(
    url: str,
    params: dict | None,
    timeout: int = 60,
    attempts: int = 3,
    wait_s: float = 5.0,
) -> dict:
    """GET with retries on transient failures; clear errors otherwise."""
    import requests

    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if 400 <= r.status_code < 500:
                raise RuntimeError(
                    f"pdok: request rejected ({r.status_code}) for {url}; "
                    "check the collection name and bbox (must be EPSG:28992)"
                )
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if attempt == attempts:
                raise RuntimeError(
                    f"pdok: service unreachable after {attempts} attempts: {e}"
                ) from e
            print(f"pdok: attempt {attempt} failed ({e}); retrying in {wait_s:.0f}s")
            time.sleep(wait_s)
    raise AssertionError("unreachable")


def fetch_features(
    collection: str,
    bbox_rd: tuple[float, float, float, float],
    base: str = PDOK_GWSW_BASE,
    page_limit: int = PAGE_LIMIT,
    max_pages: int = 500,
) -> list[dict]:
    """All features of one collection inside the RD bounding box.

    Pages through the OGC API by following ``rel=next`` links, retrying
    transient failures, and printing progress as it goes.
    """
    url = f"{base}/collections/{collection}/items"
    params: dict | None = {
        "f": "json",
        "limit": page_limit,
        "bbox": ",".join(str(v) for v in bbox_rd),
        "bbox-crs": CRS_RD,
        "crs": CRS_RD,
    }
    features: list[dict] = []
    for page in range(1, max_pages + 1):
        data = _get_json(url, params)
        batch = data.get("features", [])
        features.extend(batch)
        print(f"pdok: {collection} page {page}: +{len(batch)} (total {len(features)})")
        nxt = next(
            (lk["href"] for lk in data.get("links", []) if lk.get("rel") == "next"),
            None,
        )
        if not nxt:
            return features
        url, params = nxt, None  # the next href carries all query params
    raise RuntimeError(
        f"pdok: {collection} exceeded {max_pages} pages; narrow the bbox"
    )


def fetch_network_gpkg(
    bbox_rd: tuple[float, float, float, float],
    dest_path: str,
    collections: tuple[str, ...] = ("beheerleiding",),
    base: str = PDOK_GWSW_BASE,
) -> str:
    """Download the sewer network for ``bbox_rd`` into a GeoPackage.

    The default ``beheerleiding`` (pipes) collection is all the pipeline
    needs: graph nodes are derived from pipe endpoints. Pass extra
    collections (e.g. ``"beheerput"``) to bundle more layers.
    """
    import geopandas as gpd

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    total = 0
    for layer in collections:
        feats = fetch_features(layer, bbox_rd, base=base)
        feats = [f for f in feats if f.get("geometry")]
        if not feats:
            raise RuntimeError(
                f"pdok: no {layer} features in bbox {bbox_rd}; check that the "
                "bounding box is xmin,ymin,xmax,ymax in EPSG:28992"
            )
        gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:28992")
        gdf.to_file(dest_path, layer=layer, driver="GPKG")
        total += len(gdf)
    print(f"pdok: wrote {total} features to {dest_path}")
    return dest_path
