"""Pipeline plumbing: config parsing, gates, and the demo deliverable path."""

import json

from ii_hotspot.pipeline import (
    load_run_config,
    run_demo_deliverables,
    selftest,
)

PILOT_TOML = """
[run]
name = "unit-pilot"
start = "2024-09-01"
end = "2024-10-01"
out_root = "out"
rain_cache = "cache.csv"

[config]
bbox_rd = [1, 2, 3, 4]
gwsw_gpkg = "net.gpkg"
gwsw_auto_fetch = false
ridge = 5e-4

[[meters]]
id = 0
flow_csv = "m0.csv"
x_rd = 100.0
y_rd = 200.0
"""


def test_load_run_config(tmp_path):
    p = tmp_path / "pilot.toml"
    p.write_text(PILOT_TOML)
    run = load_run_config(str(p))
    assert run.name == "unit-pilot"
    assert run.cfg.bbox_rd == (1, 2, 3, 4)
    assert run.cfg.ridge == 5e-4
    assert run.cfg.gwsw_auto_fetch is False
    assert run.cfg.tau_slow_h == 36.0  # untouched default survives
    assert len(run.meters) == 1
    assert run.meters[0].x_rd == 100.0


def test_load_run_config_rejects_unknown_key(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("[config]\nnot_a_field = 1\n")
    try:
        load_run_config(str(p))
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "not_a_field" in str(e)


def test_selftest_gate_passes_on_default_seed():
    ok, metrics = selftest(seed=42)
    assert ok, metrics
    assert metrics["selftest_top10_overlap"] >= 8


def test_demo_deliverables_full_contract(tmp_path):
    paths = run_demo_deliverables(str(tmp_path / "demo"), seed=42)
    with open(paths["manifest"], encoding="utf-8") as fh:
        m = json.load(fh)
    assert m["run_name"] == "synthetic-demo"
    assert m["metrics"]["top10_overlap"] >= 8
    # Ground truth ships with the demo artifact for verification.
    header = open(paths["csv"], encoding="utf-8").readline()
    assert "true_a_fast" in header
