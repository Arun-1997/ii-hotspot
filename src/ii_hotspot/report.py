"""Deliverable writers: ranked hotspot table, map layer, HTML report, manifest.

Every pipeline run produces a self-contained, versioned output directory:

- ``hotspots.csv``        -- one row per zone, ranked by combined score
- ``hotspots.geojson``    -- the same table joined to zone geometry (when
  geometry is available), ready for QGIS or a web map
- ``report.html``         -- human-readable summary for the asset manager
- ``run_manifest.json``   -- config, code version, inputs, and QC metrics,
  so any deliverable can be reproduced or audited later
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

import pandas as pd


def rank_hotspots(estimate: pd.DataFrame) -> pd.DataFrame:
    """Rank zones by combined capture fraction.

    ``estimate`` is the Stage A output (columns ``a_fast``, ``a_slow``,
    one row per zone). The combined score is their sum -- the same ranking
    statistic the synthetic harness validates against.
    """
    out = estimate.copy()
    out.index.name = "zone"
    out["score"] = out["a_fast"] + out["a_slow"]
    out["rank"] = out["score"].rank(ascending=False, method="first").astype(int)
    return out.sort_values("rank")


def git_revision() -> str:
    """Current commit hash, or 'unknown' outside a git checkout."""
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return rev.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build_manifest(
    run_name: str,
    config: dict,
    metrics: dict,
    inputs: dict,
) -> dict:
    """Assemble the reproducibility manifest written next to deliverables."""
    try:
        from importlib.metadata import version

        pkg_version = version("ii-hotspot")
    except Exception:
        pkg_version = "unknown"
    return {
        "run_name": run_name,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "package_version": pkg_version,
        "git_revision": git_revision(),
        "config": config,
        "metrics": metrics,
        "inputs": inputs,
    }


def _report_html(run_name: str, hotspots: pd.DataFrame, manifest: dict, top_n: int) -> str:
    top = hotspots.head(top_n)
    max_score = float(top["score"].max()) or 1.0
    rows = []
    for zone, r in top.iterrows():
        width = 100.0 * r["score"] / max_score
        rows.append(
            f"<tr><td>{int(r['rank'])}</td><td>{zone}</td>"
            f"<td>{r['a_fast']:.4f}</td><td>{r['a_slow']:.4f}</td>"
            f"<td>{r['score']:.4f}</td>"
            f"<td><div style='background:#1f6feb;height:12px;width:{width:.1f}%'></div></td></tr>"
        )
    metrics = "".join(
        f"<li><b>{k}</b>: {v}</li>" for k, v in manifest.get("metrics", {}).items()
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>I&amp;I hotspot report -- {run_name}</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 880px; margin: 2rem auto; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 4px 8px; text-align: left; }}
th {{ background: #f3f4f6; }}
td:last-child {{ width: 30%; }}
</style></head><body>
<h1>I&amp;I hotspot report</h1>
<p>Run <b>{run_name}</b>, generated {manifest['created_utc']}
(code {manifest['git_revision'][:12]}, package {manifest['package_version']}).</p>
<p>Zones ranked by combined capture fraction <code>a_fast + a_slow</code> --
the estimated fraction of rain on the zone that reaches the foul sewer.
Inspect from the top of this list. Fast-dominant zones suggest direct
inflow (lids, cross-connections); slow-dominant zones suggest groundwater
infiltration through defects.</p>
<h2>Top {len(top)} zones for CCTV inspection</h2>
<table>
<tr><th>Rank</th><th>Zone</th><th>a_fast</th><th>a_slow</th><th>Score</th><th></th></tr>
{''.join(rows)}
</table>
<h2>Run quality</h2>
<ul>{metrics}</ul>
<p>Full table in <code>hotspots.csv</code>; provenance in
<code>run_manifest.json</code>.</p>
</body></html>
"""


def write_deliverables(
    out_dir: str,
    hotspots: pd.DataFrame,
    manifest: dict,
    zone_geometry=None,
    top_n: int = 25,
) -> dict[str, str]:
    """Write all deliverables into ``out_dir`` and return their paths.

    Parameters
    ----------
    out_dir
        Destination directory; created if missing.
    hotspots
        Output of :func:`rank_hotspots`.
    manifest
        Output of :func:`build_manifest`.
    zone_geometry
        Optional GeoDataFrame indexed like ``hotspots`` with a geometry
        column; when given, a GeoJSON map layer is written too.
    """
    os.makedirs(out_dir, exist_ok=True)
    paths = {"csv": os.path.join(out_dir, "hotspots.csv")}
    hotspots.to_csv(paths["csv"])

    if zone_geometry is not None:
        paths["geojson"] = os.path.join(out_dir, "hotspots.geojson")
        joined = zone_geometry.join(hotspots, how="left")
        joined.to_file(paths["geojson"], driver="GeoJSON")

    paths["html"] = os.path.join(out_dir, "report.html")
    with open(paths["html"], "w", encoding="utf-8") as fh:
        fh.write(_report_html(manifest["run_name"], hotspots, manifest, top_n))

    manifest = dict(manifest, deliverables=paths)
    paths["manifest"] = os.path.join(out_dir, "run_manifest.json")
    with open(paths["manifest"], "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, default=str)
    return paths
