import numpy as np
import pandas as pd
import pytest

from mushroam.meteo.features import compute, days_since
from mushroam.meteo.sim2 import cell_for_points


def test_days_since():
    ev = np.array([[False], [True], [False], [False], [True], [False]])
    assert days_since(ev, cap=50)[:, 0].tolist() == [50, 0, 1, 2, 0, 1]


def daily_frame(n_days=60, cells=("A", "B")):
    dates = pd.date_range("2020-09-01", periods=n_days, freq="D")
    rows = []
    for c in cells:
        for i, d in enumerate(dates):
            rows.append({"cellule": c, "date": d,
                         "pluie_liquide": 25.0 if i == 40 else 1.0, "neige": 0.0,
                         "tmin": -1.0 if i >= 50 else 5.0, "tmax": 15.0,
                         "etp": 2.0, "swi": i / 100})
    return pd.DataFrame(rows)


def test_compute_cumuls_et_tendances():
    f = compute(daily_frame()).set_index(["cellule", "date"])
    row = f.loc[("A", pd.Timestamp("2020-09-01") + pd.Timedelta(days=45))]
    # Fenêtre de 7 jours finissant au jour 45 : jours 39 à 45, dont 25 mm au jour 40.
    assert row["pluie_7j"] == pytest.approx(6 * 1 + 25)
    assert row["pluie_30j"] == pytest.approx(29 + 25)
    assert row["bilan_30j"] == pytest.approx(29 + 25 - 60)
    assert row["swi_tend_7j"] == pytest.approx(0.07, abs=1e-5)
    assert row["jours_depuis_20mm"] == 5
    assert row["gel_7j"] == 0
    last = f.loc[("A", pd.Timestamp("2020-09-01") + pd.Timedelta(days=59))]
    assert last["gel_7j"] == 7 and last["tmin_7j"] == pytest.approx(-1)


def test_compute_ecarte_le_rodage():
    f = compute(daily_frame())
    assert f["date"].min() == pd.Timestamp("2020-10-01")
    assert f[["pluie_30j", "tmin_14j"]].notna().all().all()


def test_cell_for_points():
    grid = pd.DataFrame({"lambx": [7240, 7320], "lamby": [18490, 18490],
                         "cellule": ["7240_18490", "7320_18490"]})
    # Montpellier tombe dans la première maille ; un point très loin, dans aucune.
    out = cell_for_points([43.6108, 48.85], [3.8767, 2.35], grid)
    assert out[0] == "7240_18490" and out[1] is None
