"""PDOK network fetcher: paging, retries, and failure modes (offline)."""

import pytest
import requests

from ii_hotspot.pdok import fetch_features

BBOX = (191000, 466000, 199000, 474000)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


def _page(n_features, next_href=None):
    payload = {"features": [{"geometry": {}, "properties": {}}] * n_features}
    if next_href:
        payload["links"] = [{"rel": "next", "href": next_href}]
    return FakeResponse(payload=payload)


def test_fetch_features_follows_next_links(monkeypatch):
    pages = iter([_page(2, "http://x/page2"), _page(1)])
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return next(pages)

    monkeypatch.setattr(requests, "get", fake_get)
    feats = fetch_features("beheerleiding", BBOX)
    assert len(feats) == 3
    assert calls[1] == "http://x/page2"


def test_fetch_features_retries_transient_failure(monkeypatch):
    responses = iter(
        [FakeResponse(status_code=503), _page(1)]
    )
    monkeypatch.setattr(requests, "get", lambda url, **kw: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    feats = fetch_features("beheerleiding", BBOX)
    assert len(feats) == 1


def test_fetch_features_client_error_fails_fast(monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda url, **kw: FakeResponse(status_code=404)
    )
    with pytest.raises(RuntimeError, match="rejected"):
        fetch_features("nonexistent", BBOX)


def test_fetch_features_gives_up_after_retries(monkeypatch):
    def fake_get(url, **kw):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="unreachable"):
        fetch_features("beheerleiding", BBOX)
