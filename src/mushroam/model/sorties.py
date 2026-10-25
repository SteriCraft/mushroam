"""Probabilité de rencontrer la cible lors d'une sortie, à partir des listes de sortie.

Une liste de sortie regroupe les espèces notées le même jour, au même endroit
(à ~1 km près), par le même observateur (iNat) ou le même jeu de données (GBIF) :
sorties de sociétés mycologiques, inventaires ONF, CBN, etc. Une liste où la
cible manque compte comme une absence. On peut alors estimer une probabilité,
ce que les observations seules ne permettent pas.

Modèle (régression logistique, une par cible) :
    logit p = a + b1 log(habitat) + b2 log(saison) + b3 log(taille de la liste)

La classe météo du jour n'est pas retenue : elle n'améliore pas la prédiction
hors bloc, et son effet n'est pas monotone (bolets des feuillus notés dans 45 %
des listes par météo normale, 35 % par météo favorable : la poussée arrive 3 à 5
semaines après la pluie, quand le cumul sur 30 jours est souvent retombé).
La probabilité vaut donc pour une météo ordinaire à cette période.

Validation par blocs géographiques de 20 km (mêmes plis que l'habitat), avec
la favorabilité d'habitat « hors bloc ». Référence : saison et taille de liste
seules.

La probabilité affichée est celle d'une **sortie type** (liste de taille
médiane) : « une sortie comme celles de la base, dans cette maille, a X % de
chances de noter la cible ».

Sorties : data/processed/listes_sortie.parquet, sorties_validation.parquet,
sorties_coefficients.parquet ; la colonne `probabilite` est ajoutée par
mushroam.model.prediction.

Usage : python -m mushroam.model.sorties
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from mushroam.config import PROCESSED_DIR, load_taxa, load_yaml
from mushroam.habitat.grille import cells_for_points
from mushroam.meteo.sim2 import zone_grid
from mushroam.model.analogues import select_obs, seasonal_level, window_mean
from mushroam.model.conditions import altitude_band
from mushroam.model.habitat import FAV_PATH, N_PLIS
from mushroam.model.meteo_classes import classify

LISTS_PATH = PROCESSED_DIR / "listes_sortie.parquet"
VALID_PATH = PROCESSED_DIR / "sorties_validation.parquet"
COEF_PATH = PROCESSED_DIR / "sorties_coefficients.parquet"
C_REG = 1.0
FULL = ["log_habitat", "log_saison", "log_taille"]
BASE = ["log_saison", "log_taille"]


def build_lists(obs: pd.DataFrame, cibles: list[str], cfg: dict) -> pd.DataFrame:
    s = obs[obs["retenue"] & ~obs["lichen"] & ~obs["doublon"] & obs["ok_habitat"]
            & (obs["observed_on"] >= cfg["debut"])].copy()
    s["qui"] = s["dataset"].where(s["source"] == "gbif", s["observer"].astype(str))
    r = cfg["arrondi_deg"]
    s["lieu"] = ((s["lat"] / r).round().astype(int).astype(str) + "_"
                 + (s["lng"] / r).round().astype(int).astype(str))
    agg = {"taille": ("taxon_name", "nunique"), "lat": ("lat", "mean"), "lng": ("lng", "mean")}
    agg |= {f"vu_{k}": (f"cible_{k}", "any") for k in cibles}
    g = s.groupby(["source", "qui", "observed_on", "lieu"]).agg(**agg).reset_index()
    g = g[g["taille"] >= cfg["especes_min"]].reset_index(drop=True)
    g["maille"] = cells_for_points(g["lat"], g["lng"])
    return g


def features(lists: pd.DataFrame, fav: pd.DataFrame, feats: pd.DataFrame, rules: dict,
             level: pd.DataFrame, hab_col: str) -> pd.DataFrame:
    d = lists.merge(fav[["maille", "pli", "altitude_m", "cellule_meteo", hab_col]], on="maille", how="inner")
    w = feats[["cellule", "date", "pluie_30j", "tmax_7j", "tmin_7j", "jours_depuis_20mm"]]
    d = d.merge(w, left_on=["cellule_meteo", "observed_on"], right_on=["cellule", "date"], how="inner")
    d = d.reset_index(drop=True)
    classe = classify(d, rules)
    bands = altitude_band(d["altitude_m"]).to_numpy().astype(int)
    d["log_habitat"] = np.log(d[hab_col])
    d["log_saison"] = np.log(window_mean(level, bands, d["observed_on"], (0, 0)))
    d["defavorable"] = (classe == "defavorable").astype(float)
    d["favorable"] = (classe == "favorable").astype(float)
    d["log_taille"] = np.log(d["taille"])
    return d


def fit(d: pd.DataFrame, y: np.ndarray, cols: list[str]) -> LogisticRegression:
    return LogisticRegression(C=C_REG, max_iter=2000).fit(d[cols], y)


def validate(d: pd.DataFrame, y: np.ndarray) -> dict:
    p_full, p_base = np.full(len(d), np.nan), np.full(len(d), np.nan)
    for f in range(N_PLIS):
        test = (d["pli"] == f).to_numpy()
        if y[~test].sum() < 2 or test.sum() == 0:
            continue
        p_full[test] = fit(d[~test], y[~test], FULL).predict_proba(d.loc[test, FULL])[:, 1]
        p_base[test] = fit(d[~test], y[~test], BASE).predict_proba(d.loc[test, BASE])[:, 1]
    ok = ~np.isnan(p_full)
    res = {"listes": int(len(d)), "avec_cible": int(y.sum()),
           "auc_complet": roc_auc_score(y[ok], p_full[ok]),
           "auc_saison_taille": roc_auc_score(y[ok], p_base[ok]),
           "brier_complet": float(np.mean((p_full[ok] - y[ok]) ** 2)),
           "brier_saison_taille": float(np.mean((p_base[ok] - y[ok]) ** 2))}
    # Calibration : probabilité prédite moyenne et fréquence observée, par tiers.
    q = pd.qcut(pd.Series(p_full[ok]).rank(method="first"), 3, labels=False).to_numpy()
    for i in range(3):
        res[f"t{i + 1}_predit"] = float(p_full[ok][q == i].mean())
        res[f"t{i + 1}_observe"] = float(y[ok][q == i].mean())
    return res


def build() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, float]:
    cfg, taxa = load_yaml("modele.yaml"), load_taxa()
    lcfg, rules, act = cfg["listes_sortie"], cfg["classes_meteo"], cfg["niveau_activite"]
    cibles = list(taxa["cibles"])
    obs = pd.read_parquet(PROCESSED_DIR / "observations.parquet")
    feats = pd.read_parquet(PROCESSED_DIR / "meteo_features.parquet")
    effort = pd.read_parquet(PROCESSED_DIR / "inat_effort.parquet")
    fav = pd.read_parquet(FAV_PATH)
    s = select_obs(obs, zone_grid())
    lists = build_lists(obs, cibles, lcfg)
    valid, coefs = [], []
    for key in cibles:
        level = seasonal_level(s, effort, key, act["debut"], act["effort_min"])
        d = features(lists, fav, feats, rules, level, f"{key}_hors_bloc")
        y = d[f"vu_{key}"].to_numpy().astype(int)
        res = validate(d, y)
        valid.append({"cible": key, **res})
        print(f"{key:16s} listes={res['listes']} avec cible={res['avec_cible']} "
              f"AUC={res['auc_complet']:.3f} (saison+taille {res['auc_saison_taille']:.3f}) "
              "calibration prédit/observé " + " ".join(
                  f"{res[f't{i}_predit']:.2f}/{res[f't{i}_observe']:.2f}" for i in (1, 2, 3)))
        # Modèle final : favorabilité ajustée sur toute la zone.
        d_all = features(lists, fav, feats, rules, level, key)
        m = fit(d_all, d_all[f"vu_{key}"].to_numpy().astype(int), FULL)
        coefs.append(pd.DataFrame({"cible": key, "variable": ["constante", *FULL],
                                   "coef": [m.intercept_[0], *m.coef_[0]]}))
    return lists, pd.DataFrame(valid), pd.concat(coefs, ignore_index=True), float(lists["taille"].median())


def probability(coefs: pd.DataFrame, key: str, habitat, saison, taille: float) -> np.ndarray:
    """Probabilité qu'une liste de `taille` espèces contienne la cible."""
    c = coefs[coefs["cible"] == key].set_index("variable")["coef"]
    z = (c["constante"] + c["log_habitat"] * np.log(habitat) + c["log_saison"] * np.log(saison)
         + c["log_taille"] * np.log(taille))
    return 1 / (1 + np.exp(-z))


def main() -> None:
    lists, valid, coefs, taille = build()
    lists.to_parquet(LISTS_PATH, index=False)
    valid.assign(taille_reference=taille).to_parquet(VALID_PATH, index=False)
    coefs.to_parquet(COEF_PATH, index=False)
    print(coefs.pivot(index="variable", columns="cible", values="coef").round(2).to_string())
    print(f"Taille de liste de référence (médiane) : {taille:.0f} espèces")
    print(f"Écrit : {LISTS_PATH}, {VALID_PATH}, {COEF_PATH}")


if __name__ == "__main__":
    main()
