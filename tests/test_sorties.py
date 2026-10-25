import numpy as np
import pandas as pd
import pytest

from mushroam.model.sorties import build_lists, probability

CFG = {"especes_min": 3, "debut": "1999-03-01", "arrondi_deg": 0.01}


def obs_frame():
    base = dict(retenue=True, lichen=False, doublon=False, ok_habitat=True, source="gbif", dataset="SM",
                observer=None, lat=43.700, lng=3.800, observed_on=pd.Timestamp("2020-10-10"), cible_x=False)
    rows = [dict(base, taxon_name=n) for n in ["a", "b", "c"]]           # liste de 3 espèces, sans la cible
    rows += [dict(base, taxon_name=n, observed_on=pd.Timestamp("2020-10-11"), cible_x=n == "Boletus")
             for n in ["a", "b", "Boletus"]]                             # autre jour : cible présente
    rows += [dict(base, taxon_name="a", observed_on=pd.Timestamp("2020-10-12"))]  # trop courte
    return pd.DataFrame(rows)


def test_listes_de_sortie():
    g = build_lists(obs_frame(), ["x"], CFG).sort_values("observed_on")
    assert len(g) == 2
    assert g["taille"].tolist() == [3, 3]
    assert g["vu_x"].tolist() == [False, True]


def test_probabilite():
    coefs = pd.DataFrame({"cible": "x", "variable": ["constante", "log_habitat", "log_saison", "log_taille"],
                          "coef": [0.0, 1.0, 1.0, 0.0]})
    p = probability(coefs, "x", np.array([1.0, 3.0]), np.array([1.0, 1.0]), 8)
    assert p[0] == pytest.approx(0.5) and p[1] == pytest.approx(0.75)
