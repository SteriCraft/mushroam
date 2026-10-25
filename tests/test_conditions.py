import numpy as np
import pandas as pd
import pytest

from mushroam.model.conditions import (bin_labels, quantile_bins, ratio_table, stratum_weights,
                                       trajectories, weighted_mean_curve)


def test_ratio_sans_effet_vaut_un():
    # La cible représente 10 % partout : rapport de 1 dans chaque classe.
    n = 1000
    x = pd.Series(np.tile([1.0, 2.0], n // 2))
    num = pd.Series(np.tile([1, 1] + [0] * 18, n // 20), dtype=float)  # une cible par classe tous les 20
    t = ratio_table(num, pd.Series(1.0, index=x.index), pd.Series(0, index=x.index), x,
                    np.array([-np.inf, 1.5, np.inf]))
    assert t["rapport"].tolist() == pytest.approx([1, 1])


def test_ratio_corrige_la_saison():
    # Strate A : 20 % de cibles ; strate B : 0 %. La variable x vaut 1 en A, 2 en B.
    # Sans standardisation, x=1 semblerait favorable ; standardisé, le rapport vaut 1.
    s = pd.Series(["A"] * 10 + ["B"] * 10)
    x = pd.Series([1.0] * 10 + [2.0] * 10)
    num = pd.Series([1, 1] + [0] * 18, dtype=float)
    t = ratio_table(num, pd.Series(1.0, index=s.index), s, x, np.array([-np.inf, 1.5, np.inf]))
    assert t["rapport"].iloc[0] == pytest.approx(1.0)
    assert np.isnan(t["rapport"].iloc[1])  # attendu nul en strate B


def test_ratio_detecte_un_effet():
    # Même strate ; la cible est 3 fois plus fréquente quand x est élevé.
    x = pd.Series([0.0] * 100 + [1.0] * 100)
    num = pd.Series([1] * 5 + [0] * 95 + [1] * 15 + [0] * 85, dtype=float)
    t = ratio_table(num, pd.Series(1.0, index=x.index), pd.Series(0, index=x.index), x,
                    np.array([-np.inf, 0.5, np.inf]))
    assert t["rapport"].tolist() == pytest.approx([0.5, 1.5])


def test_bins():
    e = quantile_bins(pd.Series(range(100)), 4)
    assert len(e) == 5 and np.isinf(e[0]) and np.isinf(e[-1])
    assert bin_labels(np.array([-np.inf, 10, np.inf])) == ["< 10", "≥ 10"]


def test_trajectoires():
    dates = pd.date_range("2020-01-01", periods=40, freq="D")
    wide = pd.DataFrame({"A": np.arange(40.0), "B": np.arange(40.0) * 10}, index=dates)
    obs = pd.DataFrame({"observed_on": [dates[35], dates[5]], "cellule_meteo": ["B", "A"]})
    tr = trajectories(obs, {"v": wide}, days=30)["v"]
    assert tr.shape == (2, 31)
    assert tr[0, -1] == 350 and tr[0, 0] == 50
    assert np.isnan(tr[1]).all()  # historique insuffisant


def test_poids_et_moyenne():
    obs = pd.DataFrame({
        "observed_on": pd.to_datetime(["2020-10-01"] * 4 + ["2020-06-01"] * 4),
        "altitude_maille": [100.0] * 8,
        "cible_x": [True, False, False, False, False, False, False, False],
    })
    w = stratum_weights(obs, "x")
    # Le fond de juin (strate sans cible) ne compte pas.
    assert w[4:].sum() == 0 and w[1:4].sum() == pytest.approx(1)
    assert weighted_mean_curve(np.array([[1.0, np.nan], [3.0, 5.0]]), np.array([1.0, 1.0])).tolist() == [2.0, 5.0]
