"""Synthetic meter generation: output contract and recoverability."""

import numpy as np
import pandas as pd

from ii_hotspot.config import STEPS_PER_DAY, Config
from ii_hotspot.pipeline import MeterSpec, RunConfig
from ii_hotspot.simulate import simulate_meter_csvs


def _fake_net(n_zones=6):
    return {
        "n_zones": n_zones,
        "areas_m2": np.full(n_zones, 9.0e4),
        "centroids": np.zeros((n_zones, 2)),
        "meter_zones": {0: set(range(n_zones))},  # one meter sees everything
    }


def _rain(n_days=20, n_zones=6, seed=0):
    rng = np.random.default_rng(seed)
    n_t = n_days * STEPS_PER_DAY
    idx = pd.date_range("2024-09-01", periods=n_t, freq="5min")
    rain = np.zeros((n_t, n_zones))
    for _ in range(8):  # a handful of patchy storms
        s = rng.integers(0, n_t - 200)
        footprint = rng.uniform(0, 1, n_zones)
        rain[s : s + 60] += np.outer(rng.gamma(2.0, 1.0, 60), footprint)
    return pd.DataFrame(rain, index=idx)


def _run(tmp_path, n_meters=1):
    meters = [
        MeterSpec(meter_id=i, flow_csv=str(tmp_path / f"m{i}.csv"), x_rd=0.0, y_rd=0.0)
        for i in range(n_meters)
    ]
    return RunConfig(cfg=Config(), meters=meters, name="sim-test")


def test_simulate_writes_valid_contract(tmp_path):
    rain = _rain()
    run = _run(tmp_path)
    written, info = simulate_meter_csvs(run, rain, _fake_net(), seed=1)

    assert set(written) == {0}
    df = pd.read_csv(written[0], parse_dates=["timestamp"])
    assert list(df.columns) == ["timestamp", "flow_m3"]
    assert len(df) == len(rain)
    assert (df["flow_m3"] >= 0).all()
    assert df["flow_m3"].notna().all()
    assert info["hot_fast_zones"] and info["hot_slow_zones"]


def test_simulated_meters_feed_pipeline_recovery(tmp_path):
    # End-to-end on the synthetic-meter path: the injected hotspots should
    # come back near the top of the Stage A ranking.
    from ii_hotspot.baseline import meter_residual
    from ii_hotspot.report import rank_hotspots
    from ii_hotspot.stage_a import stage_a_unmix

    rain = _rain(n_days=25)
    net = _fake_net()
    run = _run(tmp_path)
    written, info = simulate_meter_csvs(run, rain, net, seed=2)

    rain_mean = rain.mean(axis=1)
    flow = pd.read_csv(written[0], parse_dates=["timestamp"]).set_index("timestamp")[
        "flow_m3"
    ]
    residuals = {0: meter_residual(flow, rain_mean).to_numpy()}
    est = stage_a_unmix(
        rain.to_numpy(), net["areas_m2"], residuals, net["meter_zones"],
        net["n_zones"], run.cfg,
    )
    ranked = rank_hotspots(est)
    truth_hot = set(info["hot_fast_zones"]) | set(info["hot_slow_zones"])
    top = set(ranked.head(len(truth_hot) + 1).index)
    # At least one injected hotspot lands at the very top of the ranking.
    assert truth_hot & top
