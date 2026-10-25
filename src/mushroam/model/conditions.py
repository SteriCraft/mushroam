"""Conditions météo avant les observations (étape 4).

Toutes les comparaisons se font « à saison comparable » par standardisation
indirecte : on calcule une proportion attendue dans chaque strate (quinzaine de
l'année, et tranche d'altitude quand l'analyse est par maille), puis, pour
chaque classe d'une variable météo :

    rapport = observé / attendu

Un rapport de 1 signifie « pas plus fréquent que d'habitude à cette période ».

Deux niveaux, qui se multiplient :
1. activité des champignons : Fungi / toutes observations iNat (effort), au
   niveau de la zone et par jour ;
2. part de la cible parmi les champignons : cible / Fungi, par maille et par jour.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ALT_BANDS = [0, 400, 800, 1700]
STRATE_JOURS = 15
Z95 = 1.96


def season_stratum(dates: pd.Series) -> pd.Series:
    return ((dates.dt.day_of_year - 1) // STRATE_JOURS).clip(upper=24)


def altitude_band(alt: pd.Series) -> pd.Series:
    return pd.cut(alt.clip(lower=0), ALT_BANDS, labels=False, right=False).fillna(len(ALT_BANDS) - 2)


def quantile_bins(x: pd.Series, n: int = 5) -> np.ndarray:
    """Bornes de classes à effectifs égaux (valeurs dupliquées fusionnées)."""
    edges = np.unique(np.nanquantile(x, np.linspace(0, 1, n + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    return edges


def bin_labels(edges: np.ndarray, dec: int = 0) -> list[str]:
    f = (lambda v: f"{v:.{dec}f}".replace(".", ","))
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        if np.isinf(a):
            out.append(f"< {f(b)}")
        elif np.isinf(b):
            out.append(f"≥ {f(a)}")
        else:
            out.append(f"{f(a)} – {f(b)}")
    return out


def ratio_table(num: pd.Series, den: pd.Series, strata: pd.Series, feature: pd.Series,
                edges: np.ndarray, dec: int = 0) -> pd.DataFrame:
    """Rapport observé / attendu par classe de `feature`.

    num, den : comptes par ligne (ex. cible et fond, ou Fungi et toutes).
    La proportion attendue de chaque ligne est celle de sa strate, toutes classes
    confondues. Intervalle à 95 % approché (Poisson sur l'observé).
    """
    d = pd.DataFrame({"num": num.to_numpy(float), "den": den.to_numpy(float),
                      "s": strata.to_numpy(), "x": feature.to_numpy(float)}).dropna(subset=["x"])
    rate = d.groupby("s")["num"].sum() / d.groupby("s")["den"].sum()
    d["attendu"] = d["den"] * d["s"].map(rate).fillna(0)
    d["classe"] = pd.cut(d["x"], edges, labels=bin_labels(edges, dec), right=False)
    t = d.groupby("classe", observed=False).agg(observe=("num", "sum"), attendu=("attendu", "sum"),
                                                denominateur=("den", "sum"))
    t["rapport"] = t["observe"] / t["attendu"]
    err = Z95 * np.sqrt(t["observe"].clip(lower=1)) / t["attendu"]
    t["bas"], t["haut"] = (t["rapport"] - err).clip(lower=0), t["rapport"] + err
    return t


def zone_daily_weather(feats: pd.DataFrame, cells: list[str]) -> pd.DataFrame:
    """Moyenne quotidienne des variables sur les mailles données."""
    f = feats[feats["cellule"].isin(cells)]
    return f.drop(columns="cellule").groupby("date").mean()


def fungi_activity(effort: pd.DataFrame, weather: pd.DataFrame, feature: str, edges: np.ndarray,
                   dec: int = 0, min_effort: int = 50) -> pd.DataFrame:
    """Niveau 1 : Fungi / toutes observations iNat, par classe de `feature`."""
    d = effort.merge(weather[[feature]], left_on="date", right_index=True)
    d = d[d["toutes"] >= min_effort]
    return ratio_table(d["fungi"], d["toutes"], season_stratum(d["date"]), d[feature], edges, dec)


def target_share(obs: pd.DataFrame, target: str, feature: str, edges: np.ndarray,
                 dec: int = 0) -> pd.DataFrame:
    """Niveau 2 : cible / Fungi, par classe de `feature` (une ligne = une observation).
    Strates : quinzaine × tranche d'altitude de la maille."""
    strata = season_stratum(obs["observed_on"]).astype(str) + "_" + altitude_band(obs["altitude_maille"]).astype(str)
    return ratio_table(obs[f"cible_{target}"].astype(float), pd.Series(1.0, index=obs.index),
                       strata, obs[feature], edges, dec)


def stratum_weights(obs: pd.DataFrame, target: str) -> pd.Series:
    """Poids du fond pour reproduire la répartition saison × altitude de la cible."""
    s = season_stratum(obs["observed_on"]).astype(str) + "_" + altitude_band(obs["altitude_maille"]).astype(str)
    is_t = obs[f"cible_{target}"]
    w = s.map(s[is_t].value_counts() / s.value_counts()).fillna(0)
    return w / w[~is_t].sum() if w[~is_t].sum() else w


def trajectories(obs: pd.DataFrame, daily: dict[str, pd.DataFrame], days: int = 30) -> dict[str, np.ndarray]:
    """Séries des `days` jours précédant chaque observation (jour 0 inclus).

    daily : {variable: tableau large date × maille}. Renvoie {variable: (n_obs, days + 1)}.
    """
    out = {}
    for var, wide in daily.items():
        di = wide.index.get_indexer(obs["observed_on"])
        ci = wide.columns.get_indexer(obs["cellule_meteo"])
        arr = wide.to_numpy()
        offsets = np.arange(-days, 1)
        rows = di[:, None] + offsets[None, :]
        ok = (di[:, None] >= days) & (ci[:, None] >= 0)
        vals = np.where(ok, arr[np.clip(rows, 0, len(arr) - 1), np.clip(ci, 0, None)[:, None]], np.nan)
        out[var] = vals
    return out


def weighted_mean_curve(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    m = ~np.isnan(values)
    w = np.where(m, weights[:, None], 0)
    return np.nansum(np.where(m, values, 0) * w, axis=0) / w.sum(axis=0)
