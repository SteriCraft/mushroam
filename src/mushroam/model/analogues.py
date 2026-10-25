"""Indice de déclenchement par analogues (étape 5, couche temporelle seule).

Pour une maille et un jour d, on cherche les k situations passées les plus
proches (variables météo standardisées, même période de l'année à ± 30 jours),
puis on regarde ce qui a été observé dans la fenêtre de poussée de la cible
[d + a, d + b] qui a suivi chacune d'elles.

Deux niveaux, qui se multiplient (voir l'étape 4) :
1. activité des champignons : Fungi / toutes observations iNat, au niveau de la
   zone, rapportée à la normale de la quinzaine ;
2. part de la cible : cible / Fungi dans la maille SIM2, rapportée à la normale
   de la strate (quinzaine × tranche d'altitude × source).

Chaque niveau donne un rapport « observé / attendu » cumulé sur les k analogues :
1 = comme d'habitude à cette période, 2 = deux fois plus.

Validation : chaque situation d'un pli (bloc d'années) est prédite avec des
analogues pris uniquement dans les autres plis, et comparée à la phénologie
seule (rapport constant égal à 1).

Sorties : data/processed/analogues_prediction.parquet (90 derniers jours, toutes les
mailles) et data/processed/analogues_validation.parquet.

Usage : python -m mushroam.model.analogues
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mushroam.config import PROCESSED_DIR, load_taxa, load_yaml, load_zone
from mushroam.meteo.sim2 import zone_grid
from mushroam.model.conditions import altitude_band, season_stratum
from mushroam.observations import haversine_km

PRED_PATH = PROCESSED_DIR / "analogues_prediction.parquet"
VALID_PATH = PROCESSED_DIR / "analogues_validation.parquet"
PRED_DAYS = 90
SHRINK = 20  # poids (en observations) de la proportion de niveau supérieur dans le lissage des strates
CELL_PRIOR = 10  # poids (en cibles attendues) de « maille ordinaire » dans le facteur de maille


# ---------------------------------------------------------------- variables

def transform(df: pd.DataFrame, spec: dict[str, str]) -> np.ndarray:
    cols = []
    for v, how in spec.items():
        x = df[v].to_numpy(float)
        if how == "racine":
            x = np.sqrt(np.clip(x, 0, None))
        elif how == "log":
            x = np.log1p(np.clip(x, 0, None))
        cols.append(x)
    return np.stack(cols, axis=1)


class Scaler:
    """Standardisation commune à toutes les mailles et à tous les niveaux."""

    def __init__(self, feats: pd.DataFrame, spec: dict[str, str]):
        self.spec = spec
        x = transform(feats, spec)
        self.mean, self.std = np.nanmean(x, axis=0), np.nanstd(x, axis=0)

    def __call__(self, df: pd.DataFrame) -> np.ndarray:
        return ((transform(df, self.spec) - self.mean) / self.std).astype(np.float32)


# ---------------------------------------------------------------- analogues

def doy_distance(a: np.ndarray, b: int) -> np.ndarray:
    d = np.abs(a - b)
    return np.minimum(d, 365 - d)


def knn_sums(qx: np.ndarray, qdoy: np.ndarray, qfold: np.ndarray,
             cx: np.ndarray, cdoy: np.ndarray, cfold: np.ndarray,
             cn: np.ndarray, ce: np.ndarray, k: int, half: int, chunk: int = 512):
    """Pour chaque requête, sommes de `cn` (observé) et `ce` (attendu) sur ses k
    plus proches candidats, parmi ceux à ± `half` jours de l'année et d'un autre
    pli (qfold = -1 : aucun pli exclu)."""
    n_out = np.full(len(qx), np.nan)
    e_out = np.full(len(qx), np.nan)
    c2 = (cx ** 2).sum(axis=1)
    for doy in np.unique(qdoy):
        cand = np.flatnonzero(doy_distance(cdoy, doy) <= half)
        if len(cand) == 0:
            continue
        for q in np.array_split(np.flatnonzero(qdoy == doy), max(1, (qdoy == doy).sum() // chunk + 1)):
            if len(q) == 0:
                continue
            d2 = (qx[q] ** 2).sum(axis=1)[:, None] + c2[cand][None, :] - 2 * qx[q] @ cx[cand].T
            d2[qfold[q][:, None] == cfold[cand][None, :]] = np.inf
            kk = min(k, len(cand))
            idx = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
            ok = np.isfinite(np.take_along_axis(d2, idx, axis=1))
            n_out[q] = np.where(ok, cn[cand][idx], 0).sum(axis=1)
            e_out[q] = np.where(ok, ce[cand][idx], 0).sum(axis=1)
    return n_out, e_out


def ratio(n: np.ndarray, e: np.ndarray, prior: float) -> np.ndarray:
    return (n + prior) / (e + prior)


# ---------------------------------------------------------------- taux attendus

def smoothed_rates(num: pd.Series, den: pd.Series, levels: list[pd.Series]) -> pd.Series:
    """Proportion num/den par strate fine, lissée vers les strates plus grossières.

    levels : clés de la plus grossière à la plus fine. À chaque niveau,
    taux = (num + SHRINK × taux parent) / (den + SHRINK).
    Renvoie le taux de la strate la plus fine pour chaque ligne.
    """
    rate = pd.Series(num.sum() / den.sum(), index=num.index)
    for key in levels:
        g = pd.DataFrame({"n": num, "d": den, "k": key, "p": rate})
        s = g.groupby("k").agg(n=("n", "sum"), d=("d", "sum"), p=("p", "first"))
        r = (s["n"] + SHRINK * s["p"]) / (s["d"] + SHRINK)
        rate = key.map(r)
    return rate


def fitted_rates(num: pd.Series, den: pd.Series, levels: list[pd.Series], train: pd.Series) -> pd.Series:
    """Taux lissés estimés sur les lignes `train`, appliqués à toutes les lignes."""
    r = smoothed_rates(num[train], den[train], [lv[train] for lv in levels])
    table = pd.DataFrame({"k": levels[-1][train], "r": r}).drop_duplicates("k").set_index("k")["r"]
    return levels[-1].map(table).fillna(num[train].sum() / den[train].sum())


def factor(num: pd.Series, expected: pd.Series, key: pd.Series, train: pd.Series, prior: float) -> pd.Series:
    """Facteur multiplicatif par groupe : (observé + prior) / (attendu + prior), estimé sur `train`."""
    g = pd.DataFrame({"n": num[train], "e": expected[train], "k": key[train]}).groupby("k")[["n", "e"]].sum()
    return key.map((g["n"] + prior) / (g["e"] + prior)).fillna(1.0)


def expected_and_loo(fit, fold: pd.Series) -> tuple[pd.Series, pd.Series]:
    """fit(train) -> attendu pour toutes les lignes. Renvoie l'attendu estimé sur
    tout, puis celui où chaque ligne est estimée sans son pli."""
    full = fit(pd.Series(True, index=fold.index))
    loo = pd.Series(np.nan, index=fold.index)
    for f in fold.unique():
        loo[fold == f] = fit(fold != f)[fold == f]
    return full, loo


def fold_of(years: pd.Series | np.ndarray, per_fold: int) -> np.ndarray:
    return (np.asarray(years) - 1999) // per_fold


# ---------------------------------------------------------------- niveau 2 : part de la cible

def select_obs(obs: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    """Observations de Fungi utilisables : retenues, hors lichens et doublons, avec maille météo."""
    s = obs[obs["retenue"] & ~obs["lichen"] & ~obs["doublon"] & obs["ok_meteo"] & obs["cellule_meteo"].notna()]
    s = s.merge(grid[["cellule", "altitude_m"]].rename(columns={"cellule": "cellule_meteo",
                                                                "altitude_m": "altitude_maille"}),
                on="cellule_meteo", how="left")
    s["quinzaine"] = season_stratum(s["observed_on"]).astype(int)
    s["bande"] = altitude_band(s["altitude_maille"]).astype(int)
    return s.reset_index(drop=True)


def share_strata(s: pd.DataFrame) -> list[pd.Series]:
    src = s["source"].astype(str)
    return [src, src + "_" + s["quinzaine"].astype(str),
            src + "_" + s["quinzaine"].astype(str) + "_" + s["bande"].astype(str)]


def share_pool(s: pd.DataFrame, target: str, window: tuple[int, int], per_fold: int,
               feats: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par (maille, jour d) dont la fenêtre [d + a, d + b] contient au moins
    une observation de Fungi : n = cibles observées, e = cibles attendues (tout
    l'historique), e_loo = attendues avec des taux estimés sans le pli de l'observation.

    Attendu = taux de la strate (source × quinzaine × altitude) × facteur de la
    maille : chaque maille est rapportée à sa propre normale. L'indice ne mesure
    donc que l'écart dû à la météo (le « où » relève de la couche habitat)."""
    is_t = s[f"cible_{target}"].astype(float)
    one = pd.Series(1.0, index=s.index)
    levels = share_strata(s)
    obs_fold = pd.Series(fold_of(s["observed_on"].dt.year, per_fold), index=s.index)

    def fit(train):
        r = fitted_rates(is_t, one, levels, train)
        return r * factor(is_t, r, s["cellule_meteo"], train, CELL_PRIOR)

    e, e_loo = expected_and_loo(fit, obs_fold)
    s = s.assign(n=is_t, e=e, e_loo=e_loo)
    by_day = s.groupby(["cellule_meteo", "observed_on"])[["n", "e", "e_loo"]].sum().reset_index()
    a, b = window
    parts = [by_day.assign(date=by_day["observed_on"] - pd.Timedelta(days=lag)) for lag in range(a, b + 1)]
    pool = (pd.concat(parts).groupby(["cellule_meteo", "date"])[["n", "e", "e_loo"]].sum().reset_index()
            .rename(columns={"cellule_meteo": "cellule"}))
    pool = pool.merge(feats, on=["cellule", "date"], how="inner")
    pool["fold"] = fold_of(pool["date"].dt.year, per_fold)
    return pool


# ---------------------------------------------------------------- niveau 1 : activité des champignons

def activity_pool(effort: pd.DataFrame, zone_weather: pd.DataFrame, window: tuple[int, int],
                  per_fold: int, start: str, min_effort: int) -> pd.DataFrame:
    """Une ligne par jour d (zone) : n = Fungi observées dans [d + a, d + b],
    e = attendues d'après l'effort total, le taux habituel de la quinzaine et le
    niveau de l'année (la part des champignons sur iNat varie d'une année à
    l'autre avec la communauté d'observateurs, indépendamment de la météo)."""
    e = effort[(effort["date"] >= start) & (effort["toutes"] >= min_effort)].reset_index(drop=True)
    q = season_stratum(e["date"]).astype(str)
    year = e["date"].dt.year
    fold = pd.Series(fold_of(year, per_fold), index=e.index)
    num, den = e["fungi"].astype(float), e["toutes"].astype(float)

    def fit(train):
        base = den * fitted_rates(num, den, [q], train)
        # Le niveau de l'année est un réglage d'échelle commun au modèle et à la
        # référence : il est estimé sur l'année elle-même, y compris en validation.
        return base * factor(num, base, year, pd.Series(True, index=e.index), 0.0)

    exp_, exp_loo = expected_and_loo(fit, fold)
    e = e.assign(n=num, e=exp_, e_loo=exp_loo)
    a, b = window
    parts = [e[["date", "n", "e", "e_loo"]].assign(date=e["date"] - pd.Timedelta(days=lag))
             for lag in range(a, b + 1)]
    pool = pd.concat(parts).groupby("date")[["n", "e", "e_loo"]].sum().reset_index()
    pool = pool.merge(zone_weather.reset_index(), on="date", how="inner")
    pool["fold"] = fold_of(pool["date"].dt.year, per_fold)
    return pool


# ---------------------------------------------------------------- validation

def poisson_deviance(n: np.ndarray, mu: np.ndarray) -> float:
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(n > 0, n * np.log(n / mu), 0.0)
    return float(2 * np.sum(t - (n - mu)))


def cross_validate(pool: pd.DataFrame, scaler: Scaler, k: int, half: int, prior: float) -> pd.DataFrame:
    """Prédit chaque ligne du réservoir sans son pli. Renvoie le réservoir avec la colonne `indice`."""
    x = scaler(pool)
    doy = pool["date"].dt.day_of_year.to_numpy()
    fold = pool["fold"].to_numpy()
    n, e = knn_sums(x, doy, fold, x, doy, fold, pool["n"].to_numpy(float), pool["e"].to_numpy(float), k, half)
    return pool.assign(indice=ratio(n, e, prior))


def scores(cv: pd.DataFrame) -> dict:
    """Comparaison à la phénologie seule (indice = 1) sur les situations mises de côté."""
    n, e = cv["n"].to_numpy(float), cv["e_loo"].to_numpy(float)
    d0, d1 = poisson_deviance(n, e), poisson_deviance(n, e * cv["indice"].to_numpy())
    q = pd.qcut(cv["indice"].rank(method="first"), 5, labels=False)
    lift = cv.groupby(q).apply(lambda g: g["n"].sum() / g["e_loo"].sum(), include_groups=False)
    bounds = cv.groupby(q)["indice"].agg(["min", "max"])
    return {"situations": len(cv), "observees": float(n.sum()), "attendues": float(e.sum()),
            "gain_deviance": 1 - d1 / d0,
            **{f"q{i + 1}": float(lift.iloc[i]) for i in range(5)},
            **{f"q{i + 1}_borne": float(bounds["max"].iloc[i]) for i in range(5)}}


def scores_by_fold(cv: pd.DataFrame, per_fold: int) -> pd.DataFrame:
    rows = []
    for f, g in cv.groupby("fold"):
        n, e = g["n"].to_numpy(float), g["e_loo"].to_numpy(float)
        d0, d1 = poisson_deviance(n, e), poisson_deviance(n, e * g["indice"].to_numpy())
        rows.append({"debut": 1999 + f * per_fold, "fin": 1999 + f * per_fold + per_fold - 1,
                     "observees": n.sum(), "gain_deviance": 1 - d1 / d0 if d0 > 0 else np.nan})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- saison normale

def seasonal_level(s: pd.DataFrame, effort: pd.DataFrame, target: str, start: str, min_effort: int) -> pd.DataFrame:
    """Niveau normal attendu par quinzaine et tranche d'altitude :
    taux Fungi / toutes (iNat) × part de la cible (toutes sources), lissé sur
    3 quinzaines, puis ramené à 1 pour le meilleur couple quinzaine × tranche."""
    e = effort[(effort["date"] >= start) & (effort["toutes"] >= min_effort)]
    fq = e.groupby(season_stratum(e["date"]))[["fungi", "toutes"]].sum()
    fungi_rate = (fq["fungi"] / fq["toutes"]).reindex(range(25)).interpolate(limit_direction="both")
    t = s.groupby(["bande", "quinzaine"])[f"cible_{target}"].agg(["sum", "size"]).unstack("quinzaine", fill_value=0)
    n = t["sum"].reindex(columns=range(25), fill_value=0)
    d = t["size"].reindex(columns=range(25), fill_value=0)

    def circ_smooth(df):
        w = pd.concat([df.iloc[:, -1:], df, df.iloc[:, :1]], axis=1)
        return (w.T.rolling(3, center=True).sum().T).iloc[:, 1:-1]

    overall = s[f"cible_{target}"].mean()
    share = (circ_smooth(n) + SHRINK * overall) / (circ_smooth(d) + SHRINK)
    share.columns = range(25)
    level = share * fungi_rate.to_numpy()[None, :]
    return level / level.to_numpy().max()


def window_mean(level: pd.DataFrame, bands: np.ndarray, dates: pd.Series, window: tuple[int, int]) -> np.ndarray:
    a, b = window
    out = np.zeros(len(dates))
    for lag in range(a, b + 1):
        q = season_stratum(dates + pd.Timedelta(days=lag)).to_numpy().astype(int)
        out += level.to_numpy()[bands, q]
    return out / (b - a + 1)


# ---------------------------------------------------------------- chaîne complète

def zone_cells(grid: pd.DataFrame) -> list[str]:
    z = load_zone()
    d = haversine_km(z["centre"]["lat"], z["centre"]["lng"], grid["lat"], grid["lng"])
    return grid.loc[d <= z["rayon_km"], "cellule"].tolist()


def run(verbose: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg, taxa = load_yaml("modele.yaml"), load_taxa()
    grid = zone_grid()
    feats = pd.read_parquet(PROCESSED_DIR / "meteo_features.parquet")
    obs = pd.read_parquet(PROCESSED_DIR / "observations.parquet")
    effort = pd.read_parquet(PROCESSED_DIR / "inat_effort.parquet")
    spec, half, prior = cfg["variables"], cfg["demi_fenetre_saison_j"], cfg["a_priori"]
    act = cfg["niveau_activite"]
    scaler = Scaler(feats, spec)
    cols = ["cellule", "date", *spec]
    zone_w = feats[feats["cellule"].isin(zone_cells(grid))].groupby("date")[list(spec)].mean()
    s = select_obs(obs, grid)

    last = feats["date"].max()
    recent = feats.loc[feats["date"] > last - pd.Timedelta(days=PRED_DAYS), cols].reset_index(drop=True)
    recent = recent.merge(grid[["cellule", "altitude_m"]], on="cellule")
    rx, rdoy = scaler(recent), recent["date"].dt.day_of_year.to_numpy()
    no_fold = np.full(len(recent), -1)
    bands = altitude_band(recent["altitude_m"]).to_numpy().astype(int)

    preds, valid = [], []
    for key, c in taxa["cibles"].items():
        window = tuple(c["fenetre_jours"])
        per_fold = cfg["annees_par_pli"].get(key, cfg["annees_par_pli"]["defaut"])
        pools = {
            "activite": (activity_pool(effort, zone_w, window, per_fold, act["debut"], act["effort_min"]),
                         cfg["k_activite"]),
            "part": (share_pool(s, key, window, per_fold, feats[cols]), cfg["k"]),
        }
        pred = recent[["cellule", "date"]].assign(cible=key)
        for level, (pool, k) in pools.items():
            cv = cross_validate(pool, scaler, k, half, prior)
            sc = scores(cv)
            valid.append({"cible": key, "niveau": level, "k": k, "annees_par_pli": per_fold,
                          "plis": int(pool["fold"].nunique()), **sc})
            if verbose:
                print(f"{key:16s} {level:9s} k={k:4d} situations={sc['situations']:7d} "
                      f"gain={sc['gain_deviance']:+.3f} quintiles="
                      + " ".join(f"{sc[f'q{i}']:.2f}" for i in range(1, 6)))
            n, e = knn_sums(rx, rdoy, no_fold, scaler(pool), pool["date"].dt.day_of_year.to_numpy(),
                            pool["fold"].to_numpy(), pool["n"].to_numpy(float), pool["e"].to_numpy(float),
                            k, half)
            pred[level] = ratio(n, e, prior)
        pred["indice"] = pred["activite"] * pred["part"]
        level_tab = seasonal_level(s, effort, key, act["debut"], act["effort_min"])
        pred["saison"] = window_mean(level_tab, bands, recent["date"], window)
        pred["potentiel"] = pred["saison"] * pred["indice"]
        pred["debut_fenetre"] = pred["date"] + pd.Timedelta(days=window[0])
        pred["fin_fenetre"] = pred["date"] + pd.Timedelta(days=window[1])
        preds.append(pred)
    return pd.concat(preds, ignore_index=True), pd.DataFrame(valid)


def main() -> None:
    pred, valid = run()
    pred.to_parquet(PRED_PATH, index=False)
    valid.to_parquet(VALID_PATH, index=False)
    print(f"Écrit : {PRED_PATH} ({len(pred)} lignes), {VALID_PATH}")


if __name__ == "__main__":
    main()
