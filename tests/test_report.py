"""Deliverable writers: ranking, file contract, manifest integrity."""

import json

import pandas as pd

from ii_hotspot.report import build_manifest, rank_hotspots, write_deliverables


def _estimate() -> pd.DataFrame:
    return pd.DataFrame(
        {"a_fast": [0.01, 0.08, 0.0], "a_slow": [0.0, 0.02, 0.04]}
    )


def test_rank_hotspots_orders_by_combined_score():
    ranked = rank_hotspots(_estimate())
    assert list(ranked.index) == [1, 2, 0]
    assert list(ranked["rank"]) == [1, 2, 3]


def test_write_deliverables_contract(tmp_path):
    ranked = rank_hotspots(_estimate())
    manifest = build_manifest(
        run_name="test-run",
        config={"ridge": 1e-3},
        metrics={"n_events": 7},
        inputs={"source": "unit-test"},
    )
    paths = write_deliverables(str(tmp_path), ranked, manifest)

    assert set(paths) == {"csv", "html", "manifest"}
    back = pd.read_csv(paths["csv"], index_col="zone")
    assert back.loc[1, "rank"] == 1

    with open(paths["manifest"], encoding="utf-8") as fh:
        m = json.load(fh)
    assert m["run_name"] == "test-run"
    assert m["metrics"]["n_events"] == 7
    assert "deliverables" in m

    html = open(paths["html"], encoding="utf-8").read()
    assert "test-run" in html and "a_fast" in html
