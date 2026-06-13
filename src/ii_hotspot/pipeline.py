"""Batch pipeline: open data in, ranked hotspot deliverables out.

Stages (see docs/deployment.md for the operational runbook):

1. **network**   GWSW GeoPackage -> directed graph -> zones -> upstream sets
2. **rain**      KNMI radar files -> (time x zone) rain matrix, cached on disk
3. **residuals** meter CSVs -> dry-weather baseline -> physics residuals
4. **unmix**     Stage A ridge-NNLS -> per-zone ``a_fast`` / ``a_slow``
5. **deliver**   ranked CSV + GeoJSON + HTML report + manifest

Each stage is a plain function so it can be run, cached, and tested in
isolation; :func:`run_pipeline` strings them together.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .baseline import dry_day_count, load_meter_csv, meter_residual, wet_mask
from .config import Config
from .events import segment_events
from .report import build_manifest, rank_hotspots, write_deliverables
from .stage_a import stage_a_unmix

# Publication gate: a build must reproduce at least this much of the
# synthetic ground truth before it is allowed to ship real deliverables.
SELFTEST_MIN_RHO = 0.6
SELFTEST_MIN_OVERLAP = 8
MIN_USABLE_EVENTS = 5


@dataclass
class MeterSpec:
    """One flow meter: its series on disk and its position in the network."""

    meter_id: int
    flow_csv: str
    x_rd: float
    y_rd: float


@dataclass
class RunConfig:
    """Everything a pilot run needs, loadable from one TOML file."""

    cfg: Config = field(default_factory=Config)
    meters: list[MeterSpec] = field(default_factory=list)
    name: str = "pilot"
    start: str = ""  # ISO date, inclusive
    end: str = ""    # ISO date, exclusive
    out_root: str = "outputs"
    rain_cache: str = "data/rain_zone_series.csv"


def load_run_config(path: str) -> RunConfig:
    """Parse a pilot TOML file (see configs/pilot.example.toml)."""
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover - exercised only on 3.10
        import tomli as tomllib

    with open(path, "rb") as fh:
        raw = tomllib.load(fh)

    cfg = Config()
    for key, value in raw.get("config", {}).items():
        if not hasattr(cfg, key):
            raise ValueError(f"{path}: unknown [config] key '{key}'")
        if key == "bbox_rd":
            value = tuple(value)
        setattr(cfg, key, value)

    meters = [
        MeterSpec(
            meter_id=int(m["id"]),
            flow_csv=m["flow_csv"],
            x_rd=float(m["x_rd"]),
            y_rd=float(m["y_rd"]),
        )
        for m in raw.get("meters", [])
    ]

    run = raw.get("run", {})
    return RunConfig(
        cfg=cfg,
        meters=meters,
        name=run.get("name", "pilot"),
        start=run.get("start", ""),
        end=run.get("end", ""),
        out_root=run.get("out_root", "outputs"),
        rain_cache=run.get("rain_cache", "data/rain_zone_series.csv"),
    )


# ---------------------------------------------------------------- stage 1


def network_stage(run: RunConfig) -> dict:
    """Load the GWSW network and derive zones, areas, and upstream sets.

    Zone areas are approximated by the convex hull of each zone's manholes
    (floored at 1 ha) until the BGT surface-topography join lands.
    """
    import networkx as nx
    from shapely.geometry import MultiPoint

    from .gwsw import build_graph, load_sewer_network, make_zones

    if not os.path.exists(run.cfg.gwsw_gpkg):
        if not run.cfg.gwsw_auto_fetch:
            raise FileNotFoundError(
                f"{run.cfg.gwsw_gpkg} not found and gwsw_auto_fetch is off"
            )
        from .pdok import fetch_network_gpkg

        print("network: GeoPackage missing; fetching from PDOK")
        fetch_network_gpkg(run.cfg.bbox_rd, run.cfg.gwsw_gpkg)

    pipes = load_sewer_network(run.cfg.gwsw_gpkg)
    G = build_graph(pipes)
    nodes = list(G.nodes)
    node_xy = np.array(nodes)

    labels = make_zones(node_xy)
    # DBSCAN noise points (-1) join their nearest real zone so every
    # manhole stays attributable.
    zone_ids = sorted(set(labels) - {-1})
    if not zone_ids:
        raise ValueError("zoning produced no clusters; check the GeoPackage CRS")
    remap = {z: i for i, z in enumerate(zone_ids)}
    centroids = np.array(
        [node_xy[labels == z].mean(axis=0) for z in zone_ids]
    )
    zone_of = np.array(
        [
            remap[lab]
            if lab != -1
            else int(np.argmin(np.linalg.norm(centroids - xy, axis=1)))
            for lab, xy in zip(labels, node_xy, strict=True)
        ]
    )
    n_zones = len(zone_ids)

    areas = np.empty(n_zones)
    hulls = []
    for z in range(n_zones):
        hull = MultiPoint([tuple(p) for p in node_xy[zone_of == z]]).convex_hull
        hulls.append(hull)
        areas[z] = max(hull.area, 1.0e4)

    node_to_zone = {n: int(z) for n, z in zip(nodes, zone_of, strict=True)}
    meter_zones: dict[int, set[int]] = {}
    for m in run.meters:
        nearest = nodes[
            int(np.argmin(np.linalg.norm(node_xy - [m.x_rd, m.y_rd], axis=1)))
        ]
        upstream = nx.ancestors(G, nearest) | {nearest}
        meter_zones[m.meter_id] = {node_to_zone[n] for n in upstream}

    return {
        "pipes": pipes,
        "graph": G,
        "n_zones": n_zones,
        "centroids": centroids,
        "areas_m2": areas,
        "hulls": hulls,
        "meter_zones": meter_zones,
    }


def zone_geometry_frame(net: dict):
    """Zone hulls as a GeoDataFrame for the GeoJSON deliverable."""
    import geopandas as gpd

    gdf = gpd.GeoDataFrame(
        {"zone": range(net["n_zones"])}, geometry=net["hulls"], crs="EPSG:28992"
    )
    return gdf.set_index("zone").to_crs("EPSG:4326")


# ---------------------------------------------------------------- stage 2


def rain_stage(run: RunConfig, centroids: np.ndarray) -> pd.DataFrame:
    """Build (or reload) the (time x zone) rain matrix for the run window.

    Downloads every 5-min radar file in ``[start, end)`` on first use --
    roughly 288 files per day -- then caches the extracted zone series as
    CSV so reruns are instant.
    """
    if os.path.exists(run.rain_cache):
        rain = pd.read_csv(run.rain_cache, index_col=0, parse_dates=True)
        if rain.shape[1] != len(centroids):
            raise ValueError(
                f"{run.rain_cache}: cached zone count {rain.shape[1]} does not "
                f"match the network's {len(centroids)}; delete the cache to refetch"
            )
        return rain

    from .knmi import build_zone_rain_series

    if not run.cfg.knmi_api_key:
        raise ValueError("KNMI_API_KEY is not set and no rain cache exists")

    rain = build_zone_rain_series(run.cfg, centroids, run.start, run.end)
    if rain.empty:
        raise ValueError(
            f"no KNMI data found in [{run.start}, {run.end}); the window may "
            "be ahead of the dataset's monthly publication lag, or the dataset "
            f"name/version ({run.cfg.knmi_dataset} v{run.cfg.knmi_version}) is wrong"
        )
    rain = rain.clip(lower=0.0).fillna(0.0)
    os.makedirs(os.path.dirname(run.rain_cache) or ".", exist_ok=True)
    rain.to_csv(run.rain_cache)
    return rain


# ---------------------------------------------------------------- stage 3


def residual_stage(run: RunConfig, rain: pd.DataFrame) -> dict[int, np.ndarray]:
    """Meter CSVs to physics residuals on the rain grid."""
    rain_mean = rain.mean(axis=1)
    residuals: dict[int, np.ndarray] = {}
    for m in run.meters:
        flow = load_meter_csv(m.flow_csv)
        resid = meter_residual(flow, rain_mean)
        residuals[m.meter_id] = resid.to_numpy()
    return residuals


# ---------------------------------------------------------------- gates


def selftest(seed: int = 42) -> tuple[bool, dict]:
    """Synthetic recoverability gate; must pass before real deliverables ship."""
    from .synthetic import run_synthetic

    res = run_synthetic(seed=seed)
    metrics = {
        "selftest_rho_fast": round(res.rho_fast, 3),
        "selftest_rho_slow": round(res.rho_slow, 3),
        "selftest_top10_overlap": res.top10_overlap,
    }
    ok = (
        res.rho_fast >= SELFTEST_MIN_RHO
        and res.rho_slow >= SELFTEST_MIN_RHO
        and res.top10_overlap >= SELFTEST_MIN_OVERLAP
    )
    return ok, metrics


# ------------------------------------------------------------ entry points


def run_pipeline(run: RunConfig, skip_selftest: bool = False) -> dict[str, str]:
    """Execute all stages and write the deliverable set. Returns paths."""
    metrics: dict = {}
    if not skip_selftest:
        ok, metrics = selftest()
        if not ok:
            raise RuntimeError(f"selftest gate failed: {metrics}")
        print(f"selftest gate passed: {metrics}")

    print("network: loading GWSW GeoPackage")
    net = network_stage(run)
    print(f"network: {net['n_zones']} zones from {len(net['pipes'])} pipes")

    rain = rain_stage(run, net["centroids"])
    events = segment_events(rain)
    metrics["n_events"] = len(events)
    metrics["n_dry_days"] = dry_day_count(wet_mask(rain.mean(axis=1)))
    print(f"rain: {len(rain)} steps, {len(events)} usable events")
    if len(events) < MIN_USABLE_EVENTS:
        print(
            f"WARNING: only {len(events)} events (< {MIN_USABLE_EVENTS}); "
            "identifiability will be poor -- extend the run window"
        )

    residuals = residual_stage(run, rain)
    covered = sorted(set().union(*net["meter_zones"].values()))
    metrics["n_zones"] = net["n_zones"]
    metrics["n_zones_covered"] = len(covered)

    print("unmix: solving Stage A")
    estimate = stage_a_unmix(
        rain.to_numpy(),
        net["areas_m2"],
        residuals,
        net["meter_zones"],
        net["n_zones"],
        run.cfg,
    )
    hotspots = rank_hotspots(estimate)
    hotspots["metered"] = hotspots.index.isin(covered)

    out_dir = os.path.join(
        run.out_root,
        f"{run.name}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    )
    manifest = build_manifest(
        run_name=run.name,
        config={**asdict(run.cfg), "knmi_api_key": "<redacted>"},
        metrics=metrics,
        inputs={
            "gwsw_gpkg": run.cfg.gwsw_gpkg,
            "rain_cache": run.rain_cache,
            "rain_steps": len(rain),
            "meters": {m.meter_id: m.flow_csv for m in run.meters},
            "window": [run.start, run.end],
        },
    )
    try:
        geometry = zone_geometry_frame(net)
    except ImportError:
        geometry = None
    paths = write_deliverables(out_dir, hotspots, manifest, zone_geometry=geometry)
    print(f"deliverables written to {out_dir}")
    return paths


def run_demo_deliverables(out_dir: str, seed: int = 42) -> dict[str, str]:
    """Produce a full deliverable set from the synthetic harness.

    This is the staging deployment: identical output contract to a real
    run, no external data needed, with ground-truth columns added so the
    artifact doubles as a validation record.
    """
    from .synthetic import run_synthetic

    res = run_synthetic(seed=seed)
    hotspots = rank_hotspots(res.estimate)
    hotspots["true_a_fast"] = res.truth_fast[hotspots.index]
    hotspots["true_a_slow"] = res.truth_slow[hotspots.index]
    manifest = build_manifest(
        run_name="synthetic-demo",
        config={"seed": seed},
        metrics={
            "rho_fast": round(res.rho_fast, 3),
            "rho_slow": round(res.rho_slow, 3),
            "top10_overlap": res.top10_overlap,
        },
        inputs={"source": "ii_hotspot.synthetic.run_synthetic"},
    )
    return write_deliverables(out_dir, hotspots, manifest)
