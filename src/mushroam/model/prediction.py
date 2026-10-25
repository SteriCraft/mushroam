"""Combinaison finale par maille de 1 km : habitat × saison × météo.

- habitat : favorabilité (mushroam.model.habitat), 1 = moyenne des lieux prospectés ;
- saison : niveau normal de la cible pour les 14 prochains jours à cette
  altitude (1 = meilleure période de l'année, toutes altitudes confondues) ;
- météo : classe actuelle de la maille SIM2 (défavorable / normale /
  favorable) et son facteur validé (mushroam.model.meteo_classes).

potentiel = habitat × saison × facteur météo : sert à classer les secteurs,
pas une probabilité.

Sortie : data/processed/prediction_1km.parquet (date d'émission = dernier jour météo).

Usage : python -m mushroam.model.prediction
"""

from __future__ import annotations

import pandas as pd

from mushroam.config import PROCESSED_DIR, load_taxa, load_yaml
from mushroam.meteo.sim2 import zone_grid
from mushroam.model.analogues import select_obs, seasonal_level, window_mean
from mushroam.model.conditions import altitude_band
from mushroam.model.habitat import FAV_PATH
from mushroam.model.meteo_classes import FACTEUR_PATH, classify, factors

OUT_PATH = PROCESSED_DIR / "prediction_1km.parquet"


def build() -> pd.DataFrame:
    cfg, taxa = load_yaml("modele.yaml"), load_taxa()
    rules, act = cfg["classes_meteo"], cfg["niveau_activite"]
    feats = pd.read_parquet(PROCESSED_DIR / "meteo_features.parquet")
    last = feats["date"].max()
    today = feats[feats["date"] == last].copy()
    today["classe"] = classify(today, rules)
    fac = factors(pd.read_parquet(FACTEUR_PATH))
    today["facteur_meteo"] = today["classe"].map(fac)

    fav = pd.read_parquet(FAV_PATH)
    obs = pd.read_parquet(PROCESSED_DIR / "observations.parquet")
    effort = pd.read_parquet(PROCESSED_DIR / "inat_effort.parquet")
    s = select_obs(obs, zone_grid())
    base = fav.merge(today[["cellule", "classe", "facteur_meteo", "pluie_30j", "swi", "jours_depuis_20mm"]],
                     left_on="cellule_meteo", right_on="cellule", how="left").drop(columns="cellule")
    base["classe"] = base["classe"].fillna("normale")
    base["facteur_meteo"] = base["facteur_meteo"].fillna(1.0)
    bands = altitude_band(base["altitude_m"]).to_numpy().astype(int)
    dates = pd.Series(last, index=base.index)
    out = []
    for key in taxa["cibles"]:
        level = seasonal_level(s, effort, key, act["debut"], act["effort_min"])
        p = base.drop(columns=list(taxa["cibles"])).assign(cible=key, habitat=base[key])
        p["saison"] = window_mean(level, bands, dates, tuple(rules["horizon_jours"]))
        p["potentiel"] = p["habitat"] * p["saison"] * p["facteur_meteo"]
        out.append(p)
    df = pd.concat(out, ignore_index=True)
    df["date"] = last
    return df


def main() -> None:
    df = build()
    df.to_parquet(OUT_PATH, index=False)
    print(f"Écrit : {OUT_PATH} ({len(df)} lignes, émis le {df['date'].iloc[0]:%d/%m/%Y})")
    print(df.groupby("cible")[["habitat", "saison", "facteur_meteo", "potentiel"]].describe().T.round(2).to_string())


if __name__ == "__main__":
    main()
