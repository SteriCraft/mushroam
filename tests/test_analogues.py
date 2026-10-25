import numpy as np
import pandas as pd
import pytest

from mushroam.model.analogues import (doy_distance, expected_and_loo, factor, knn_sums, poisson_deviance,
                                      ratio, smoothed_rates)


def test_doy_distance_circulaire():
    assert doy_distance(np.array([1, 360, 100]), 5).tolist() == [4, 10, 95]


def test_knn_exclut_le_pli_et_la_saison():
    # Candidats : même position, plis 0 et 1 ; un candidat hors saison (jour 200).
    cx = np.zeros((4, 1), np.float32)
    cx[1] = 0.1
    cdoy = np.array([100, 100, 100, 200])
    cfold = np.array([0, 1, 1, 1])
    cn = np.array([10.0, 1.0, 2.0, 100.0])
    ce = np.ones(4)
    qx = np.zeros((1, 1), np.float32)
    n, e = knn_sums(qx, np.array([100]), np.array([0]), cx, cdoy, cfold, cn, ce, k=5, half=30)
    # Pli 0 exclu, jour 200 hors fenêtre : restent les candidats 1 et 2.
    assert n[0] == 3 and e[0] == 2
    n, _ = knn_sums(qx, np.array([100]), np.array([-1]), cx, cdoy, cfold, cn, ce, k=2, half=30)
    assert n[0] == 12  # les deux plus proches : candidats 0 et 2 (distance nulle)


def test_ratio_retrecit_vers_un():
    assert ratio(np.array([0.0]), np.array([0.0]), 5)[0] == 1
    assert ratio(np.array([30.0]), np.array([10.0]), 5)[0] == pytest.approx(35 / 15)


def test_taux_lisses():
    num = pd.Series([1.0, 0, 0, 0, 1, 1, 1, 1])
    den = pd.Series(1.0, index=num.index)
    key = pd.Series(list("AAAABBBB"))
    r = smoothed_rates(num, den, [key])
    # Global 5/8 ; A : (1 + 20 × 0,625) / 24 ; B : (4 + 20 × 0,625) / 24.
    assert r.iloc[0] == pytest.approx((1 + 20 * 0.625) / 24)
    assert r.iloc[4] == pytest.approx((4 + 20 * 0.625) / 24)


def test_facteur_et_validation_sans_le_pli():
    num = pd.Series([2.0, 0.0, 4.0, 0.0])
    exp_ = pd.Series(1.0, index=num.index)
    key = pd.Series(["a", "b", "a", "b"])
    fold = pd.Series([0, 0, 1, 1])
    assert factor(num, exp_, key, fold == 0, 0.0).tolist() == [2, 0, 2, 0]
    full, loo = expected_and_loo(lambda train: exp_ * factor(num, exp_, key, train, 0.0), fold)
    assert full.tolist() == [3, 0, 3, 0]
    assert loo.tolist() == [4, 0, 2, 0]  # chaque pli estimé sur l'autre


def test_deviance():
    assert poisson_deviance(np.array([2.0, 0.0]), np.array([2.0, 1e-9])) == pytest.approx(0, abs=1e-6)
    assert poisson_deviance(np.array([4.0]), np.array([2.0])) > 0
