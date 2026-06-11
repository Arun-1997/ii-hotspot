"""GWSW sewer network loader: GeoPackage to GeoDataFrame and to a DAG."""

from __future__ import annotations

# Column-name aliases differ per GWSW Geo-theme and per municipality.
# Inspect a real file first with ``gpd.read_file(path).columns`` and extend
# this map if your dataset uses different keys.
RENAMES: dict[str, str] = {
    "jaar_van_aanleg": "year_built",
    "aanlegjaar": "year_built",
    "materiaal": "material",
    "materiaal_leiding": "material",
    "breedte_diameter": "diameter_mm",
    "breedte_leiding": "diameter_mm",
    "diameter": "diameter_mm",
    "type_stelsel": "system_type",
    "stelseltype": "system_type",
    "bob_beginpunt": "invert_start_nap",
    "bob_eindpunt": "invert_end_nap",
}


def load_sewer_network(gpkg_path: str, layer: str | None = None):
    """Load pipes from a GWSW GeoPackage and normalize column names."""
    import geopandas as gpd

    pipes = gpd.read_file(gpkg_path, layer=layer)
    pipes = pipes.rename(
        columns={k: v for k, v in RENAMES.items() if k in pipes.columns}
    )
    if pipes.crs is None:
        pipes = pipes.set_crs("EPSG:28992")
    # PDOK serves MultiLineString; build_graph needs single-part coords.
    pipes = pipes.explode(index_parts=False, ignore_index=True)
    return pipes.to_crs("EPSG:28992")


def build_graph(pipes, snap_m: float = 0.05):
    """Directed sewer graph; flow follows falling invert levels when known."""
    import networkx as nx

    G = nx.DiGraph()
    for i, row in pipes.iterrows():
        a, b = row.geometry.coords[0], row.geometry.coords[-1]
        na = (round(a[0] / snap_m) * snap_m, round(a[1] / snap_m) * snap_m)
        nb = (round(b[0] / snap_m) * snap_m, round(b[1] / snap_m) * snap_m)
        s, e = na, nb
        if (
            row.get("invert_start_nap") is not None
            and row.get("invert_end_nap") is not None
            and row["invert_start_nap"] < row["invert_end_nap"]
        ):
            s, e = nb, na
        G.add_edge(s, e, pipe_id=i, length=row.geometry.length)
    return G


def upstream_zone_ids(G, meter_node, node_to_zone: dict) -> set:
    """Zone ids whose flow passes the meter -- ancestors in the sewer DAG."""
    import networkx as nx

    nodes = nx.ancestors(G, meter_node) | {meter_node}
    return {node_to_zone[n] for n in nodes if n in node_to_zone}


def make_zones(node_coords, eps_m: float = 150, min_samples: int = 5):
    """Cluster manholes into zones with DBSCAN.

    If your GWSW dataset already carries a ``rioleringsgebied`` attribute,
    prefer that partition -- it reflects the operator's own catchment model.
    """
    from sklearn.cluster import DBSCAN

    return DBSCAN(eps=eps_m, min_samples=min_samples).fit_predict(node_coords)
