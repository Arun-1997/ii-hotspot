"""Tests for ``ii_hotspot.kernels``."""

import numpy as np

from ii_hotspot.kernels import exp_kernel, zone_response_columns


def test_kernel_sums_to_one():
    h = exp_kernel(1.0)
    assert np.isclose(h.sum(), 1.0)


def test_kernel_is_monotone_decreasing():
    h = exp_kernel(2.0)
    assert np.all(np.diff(h) <= 0)


def test_design_matrix_shape():
    rain = np.zeros((100, 5))
    areas = np.ones(5) * 1e4
    kernels = [exp_kernel(1.0), exp_kernel(24.0)]
    X = zone_response_columns(rain, areas, kernels)
    assert X.shape == (100, 10)


def test_design_matrix_responds_to_rain():
    rain = np.zeros((50, 3))
    rain[10, 1] = 5.0  # mm pulse on zone 1 at t=10
    areas = np.array([1e4, 1e4, 1e4])
    X = zone_response_columns(rain, areas, [exp_kernel(1.0)])
    # Column for zone 1 should be nonzero from t=10 onward, others zero.
    assert np.all(X[:10, 1] == 0)
    assert X[10, 1] > 0
    assert np.all(X[:, 0] == 0)
    assert np.all(X[:, 2] == 0)
