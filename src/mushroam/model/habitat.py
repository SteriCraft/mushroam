"""Favorabilité d'habitat par maille de 1 km (étape 6, le « où »).

Méthode du fond de référence : parmi les observations précises de champignons
(position à 1 km près), on modélise la probabilité qu'une observation soit la
cible selon l'habitat de sa maille (régression logistique). Les sites très
prospectés pèsent autant au numérateur qu'au dénominateur : l'effort
d'observation se neutralise.

Variables d'habitat : parts de végétation (BD Forêt), groupes de sols (INRAE),
cultures et prairies (WorldCover), altitude (et son carré), relief.
Variables de nuisance, retirées de la carte : saison (jour de l'année) et source.

Favorabilité = exp(partie habitat du score), ramenée à 1 pour la maille
moyenne des lieux prospectés : 2 = cible deux fois plus fréquente parmi les
champignons qu'en moyenne. Elle est bornée à la plage des lieux prospectés
(1er et 99e centiles) : pas d'extrapolation vers des milieux jamais observés.

Validation : blocs géographiques de 20 km × 20 km répartis en 5 plis ; chaque
pli est prédit par un modèle ajusté sans lui. Comparaison à l'altitude seule.

Sortie : data/processed/habitat_favorabilite.parquet (une ligne par maille de 1 km)
et data/processed/habitat_validation.parquet.

Usage : python -m mushroam.model.habitat
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from mushroam.config import PROCESSED_DIR, load_taxa
from mushroam.habitat.grille import OUT_PATH as GRID_PATH, cells_for_points
from mushroam.habitat.vecteurs import FOREST_CLASSES, SOIL_CLASSES

FAV_PATH = PROCESSED_DIR / "habitat_favorabilite.parquet"
VALID_PATH = PROCESSED_DIR / "habitat_validation.parquet"
COEF_PATH = PROCESSED_DIR / "habitat_coefficients.parquet"
BLOC_KM = 20
N_PLIS = 5
C_REG = 0.5  # régularisation (plus petit = coefficients plus prudents)

HABITAT_VARS = ([f"foret_{n}" for n in FOREST_CLASSES.values()]
                + [f"sol_{n}" for n in SOIL_CLASSES.values() if n != "autre"]
                + ["wc_cultures", "wc_prairies", "alt_km", "alt_km2", "relief_hm"])
NUISANCE_VARS = ["doy_sin", "doy_cos", "doy_sin2", "doy_cos2", "gbif"]


def habitat_matrix(h: pd.DataFrame) -> pd.DataFrame:
    x = h[[v for v in HABITAT_VARS if v in h.columns]].copy()
    for n in SOIL_CLASSES.values():
        if f"sol_{n}" in x:
            x[f"sol_{n}"] = x[f"sol_{n}"].fillna(h[f"sol_{n}"].mean())
    x["alt_km"] = h["altitude_m"].clip(lower=0) / 1000
    x["alt_km2"] = x["alt_km"] ** 2
    x["relief_hm"] = h["relief_m"] / 100
    return x[HABITAT_VARS]


def training_table(obs: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    s = obs[obs["retenue"] & ~obs["lichen"] & ~obs["doublon"] & obs["ok_habitat"]].copy()
    s["maille"] = cells_for_points(s["lat"], s["lng"])
    s = s.merge(grid, on="maille", how="inner", suffixes=("_obs", ""))
    doy = 2 * np.pi * s["observed_on"].dt.day_of_year / 365.25
    s["doy_sin"], s["doy_cos"] = np.sin(doy), np.cos(doy)
    s["doy_sin2"], s["doy_cos2"] = np.sin(2 * doy), np.cos(2 * doy)
    s["gbif"] = (s["source"] == "gbif").astype(float)
    s["pli"] = block_folds(s, grid)
    return s.reset_index(drop=True)


def block_folds(df: pd.DataFrame, grid: pd.DataFrame) -> np.ndarray:
    """Pli de chaque ligne (colonnes x, y en Lambert-93) : blocs de BLOC_KM km de la
    grille répartis au hasard (graine fixe) entre N_PLIS plis."""
    def key(d):
        return ((d["x"] // (BLOC_KM * 1000)).astype(int).astype(str) + "_"
                + (d["y"] // (BLOC_KM * 1000)).astype(int).astype(str))
    ub = np.sort(key(grid).unique())
    perm = np.random.default_rng(0).permutation(len(ub)) % N_PLIS
    return key(df).map(dict(zip(ub, perm))).to_numpy()


class Model:
    """Régression logistique sur variables standardisées."""

    def __init__(self, cols: list[str]):
        self.cols = cols

    def fit(self, x: pd.DataFrame, y: np.ndarray) -> "Model":
        self.mu, self.sd = x[self.cols].mean(), x[self.cols].std().replace(0, 1)
        self.lr = LogisticRegression(C=C_REG, max_iter=2000)
        self.lr.fit((x[self.cols] - self.mu) / self.sd, y)
        return self

    def score(self, x: pd.DataFrame) -> np.ndarray:
        return self.lr.decision_function((x[self.cols] - self.mu) / self.sd)

    def partial(self, x: pd.DataFrame, cols: list[str]) -> np.ndarray:
        """Partie du score due aux seules colonnes `cols` (centrée sur la moyenne d'ajustement)."""
        coef = pd.Series(self.lr.coef_[0], index=self.cols)
        return (((x[cols] - self.mu[cols]) / self.sd[cols]) * coef[cols]).sum(axis=1).to_numpy()

    def raw_coefficients(self) -> pd.Series:
        return pd.Series(self.lr.coef_[0], index=self.cols) / self.sd


def cross_validate(t: pd.DataFrame, y: np.ndarray, cols: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Score, probabilité et partie habitat du score, chacun prédit sans le pli de la ligne."""
    score, prob, hab = (np.full(len(t), np.nan) for _ in range(3))
    for f in range(N_PLIS):
        test = (t["pli"] == f).to_numpy()
        if y[~test].sum() == 0:
            continue
        m = Model(cols).fit(t[~test], y[~test])
        score[test] = m.score(t[test])
        prob[test] = m.lr.predict_proba((t.loc[test, cols] - m.mu) / m.sd)[:, 1]
        hcols = [c for c in cols if c in HABITAT_VARS]
        if hcols:
            hab[test] = m.partial(t[test], hcols)
    return score, prob, hab


def evaluate(t: pd.DataFrame, y: np.ndarray) -> dict:
    """AUC hors bloc (habitat complet, altitude seule, saison et source seules) et
    gain par quintile de la partie habitat : cibles observées / attendues d'après
    la saison et la source seules."""
    full, _, hab = cross_validate(t, y, HABITAT_VARS + NUISANCE_VARS)
    alt, _, _ = cross_validate(t, y, ["alt_km", "alt_km2"] + NUISANCE_VARS)
    base, p_base, _ = cross_validate(t, y, NUISANCE_VARS)
    ok = ~np.isnan(full) & ~np.isnan(alt) & ~np.isnan(base)
    res = {"observations": int(len(t)), "cibles": int(y.sum()),
           "auc_habitat": roc_auc_score(y[ok], full[ok]), "auc_altitude": roc_auc_score(y[ok], alt[ok]),
           "auc_saison_source": roc_auc_score(y[ok], base[ok])}
    q = pd.qcut(pd.Series(hab[ok]).rank(method="first"), 5, labels=False).to_numpy()
    yy, pb = y[ok], p_base[ok]
    for i in range(5):
        res[f"q{i + 1}"] = float(yy[q == i].sum() / pb[q == i].sum())
    return res


def favorability(m: Model, t: pd.DataFrame, cells: pd.DataFrame) -> np.ndarray:
    """exp(partie habitat), 1 = moyenne des lieux prospectés, bornée à leur plage
    (1er et 99e centiles) : pas d'extrapolation vers des milieux jamais observés."""
    seen = m.partial(t, HABITAT_VARS)
    lo, hi = np.quantile(seen, [0.01, 0.99])
    return np.exp(np.clip(m.partial(cells, HABITAT_VARS), lo, hi)) / np.exp(seen).mean()


def build() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    taxa = load_taxa()
    grid = pd.read_parquet(GRID_PATH)
    obs = pd.read_parquet(PROCESSED_DIR / "observations.parquet")
    hab_grid = habitat_matrix(grid)
    t = training_table(obs, grid)
    t = pd.concat([t.drop(columns=[c for c in HABITAT_VARS if c in t.columns]), habitat_matrix(t)], axis=1)
    fav = grid[["maille", "x", "y", "lat", "lng", "altitude_m", "cellule_meteo"]].copy()
    fav["pli"] = block_folds(grid, grid)
    valid, coefs = [], []
    for key, c in taxa["cibles"].items():
        y = t[f"cible_{key}"].to_numpy().astype(int)
        res = evaluate(t, y)
        valid.append({"cible": key, **res})
        print(f"{key:16s} obs={res['observations']} cibles={res['cibles']} AUC habitat={res['auc_habitat']:.3f} "
              f"altitude={res['auc_altitude']:.3f} saison+source={res['auc_saison_source']:.3f} "
              "quintiles=" + " ".join(f"{res[f'q{i}']:.2f}" for i in range(1, 6)))
        m = Model(HABITAT_VARS + NUISANCE_VARS).fit(t, y)
        fav[key] = favorability(m, t, hab_grid)
        # Version « hors bloc » : chaque maille prédite par un modèle ajusté sans son bloc
        # (sert à valider honnêtement les modèles qui l'utilisent, comme les listes de sortie).
        oof = np.full(len(grid), np.nan)
        for f in range(N_PLIS):
            train, cells = (t["pli"] != f).to_numpy(), fav["pli"].to_numpy() == f
            mf = Model(HABITAT_VARS + NUISANCE_VARS).fit(t[train], y[train])
            oof[cells] = favorability(mf, t[train], hab_grid[cells])
        fav[f"{key}_hors_bloc"] = oof
        rc = m.raw_coefficients()[HABITAT_VARS]
        coefs.append(pd.DataFrame({"cible": key, "variable": rc.index, "coef": rc.to_numpy()}))
    return fav, pd.DataFrame(valid), pd.concat(coefs, ignore_index=True)


def main() -> None:
    fav, valid, coefs = build()
    fav.to_parquet(FAV_PATH, index=False)
    valid.to_parquet(VALID_PATH, index=False)
    coefs.to_parquet(COEF_PATH, index=False)
    print(f"Écrit : {FAV_PATH}, {VALID_PATH}, {COEF_PATH}")


if __name__ == "__main__":
    main()
