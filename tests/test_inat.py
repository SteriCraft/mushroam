import pandas as pd
import pytest

from mushroam import http as client_mod
from mushroam.http import cache_key
from mushroam.inat.client import INatClient
from mushroam.inat.extract import PER_PAGE, iter_observations
from mushroam.inat.normalize import to_dataframe

class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        raise RuntimeError(self.status_code)


class FakeSession:
    """Simule l'API : n observations d'id 1..n, paginées par id_above."""

    def __init__(self, n):
        self.n, self.calls, self.headers = n, [], {}

    def get(self, url, params, timeout):
        self.calls.append(dict(params))
        start = params["id_above"] + 1
        ids = range(start, min(start + params["per_page"], self.n + 1))
        return FakeResponse({"results": [{"id": i} for i in ids]})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)


def test_cache_key_ignore_ordre_des_parametres():
    assert cache_key("/a", {"x": 1, "y": 2}) == cache_key("/a", {"y": 2, "x": 1})
    assert cache_key("/a", {"x": 1}) != cache_key("/a", {"x": 2})


def test_pagination_et_cache_des_pages_completes(tmp_path):
    n = 2 * PER_PAGE + 17
    session = FakeSession(n)
    c = INatClient(cache_dir=tmp_path, session=session)
    ids = [o["id"] for o in iter_observations(c, 47170, 43.6, 3.9, 100)]
    assert ids == list(range(1, n + 1))
    assert len(session.calls) == 3

    # Deuxième passage : les 2 pages complètes viennent du cache, seule la dernière est refaite.
    session2 = FakeSession(n + 5)
    c2 = INatClient(cache_dir=tmp_path, session=session2)
    ids2 = [o["id"] for o in iter_observations(c2, 47170, 43.6, 3.9, 100)]
    assert ids2 == list(range(1, n + 6))
    assert len(session2.calls) == 1
    assert c2.n_cache == 2


def test_reprise_sur_429(tmp_path):
    class Flaky(FakeSession):
        def get(self, url, params, timeout):
            self.calls.append(params)
            if len(self.calls) == 1:
                return FakeResponse({}, status=429)
            return FakeResponse({"results": []})

    s = Flaky(0)
    c = INatClient(cache_dir=tmp_path, session=s)
    assert c.get("/v2/observations", {"a": 1}) == {"results": []}
    assert len(s.calls) == 2


def test_normalisation_inat():
    obs = [
        {"id": 1, "observed_on": "2023-10-12", "location": "43.9,3.6", "quality_grade": "research",
         "taxon": {"id": 350216, "name": "Boletus reticulatus", "rank": "species",
                   "ancestor_ids": [48460, 47170, 48427, 48702]}, "user": {"id": 9}},
        {"id": 2, "observed_on": None, "location": None, "taxon": None},
    ]
    df = to_dataframe(obs).set_index("id")
    assert df.loc[1, "lineage"] == [47170, 48427, 48460, 48702, 350216]
    assert df.loc[1, "lat"] == 43.9
    assert pd.isna(df.loc[2, "observed_on"]) and df.loc[2, "lineage"] == []
