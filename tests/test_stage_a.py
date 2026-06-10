"""End-to-end recoverability test using the synthetic harness."""

from ii_hotspot.synthetic import run_synthetic


def test_synthetic_recovers_hotspots():
    res = run_synthetic(seed=42)
    # With the default 3 meters / 12 events / 30 days, all 10 ground-truth
    # hotspots should land in the top-10 ranking.
    assert res.top10_overlap == 10
    # Rank-correlations are dominated by the many true zeros that get tied,
    # so they should be positive but we don't assert a strict threshold.
    assert res.rho_fast > 0.4
    assert res.rho_slow > 0.4


def test_synthetic_degrades_with_fewer_events():
    rich = run_synthetic(n_events=20, seed=1)
    sparse = run_synthetic(n_events=4, seed=1)
    # More events should not hurt recovery on the top-10 metric.
    assert rich.top10_overlap >= sparse.top10_overlap
