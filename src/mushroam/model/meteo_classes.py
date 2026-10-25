"""Classe météo actuelle par maille SIM2 : défavorable, normale ou favorable.

Règles simples (seuils dans config/modele.yaml), contrôlées hors échantillon :
pour chaque année, l'activité des champignons des jours classés est comparée
à la normale de la quinzaine estimée **sans cette année** (niveau 1 de
l'étape 4 : Fungi / toutes observations iNat, au niveau de la zone).

Limite : le contrôle se fait sur la météo moyenne de la zone (l'effort iNat
n'est connu qu'à cette échelle) ; les règles sont ensuite appliquées maille
par maille.

Usage : python -m mushroam.model.meteo_classes
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mushroam.config import PROCESSED_DIR, load_yaml
from mushroam.meteo.sim2 import zone_grid
from mushroam.model.analogues import activity_pool, zone_cells

CLASSES = ["defavorable", "normale", "favorable"]
LABELS = {"defavorable": "défavorable", "normale": "normale", "favorable": "favorable"}
FACTEUR_PATH = PROCESSED_DIR / "classes_meteo_validation.parquet"


def classify(df: pd.DataFrame, rules: dict) -> np.ndarray:
    d, f = rules["defavorable"], rules["favorable"]
    bad = (df["pluie_30j"] < d["pluie_30j_max"]) | (df["tmax_7j"] >= d["tmax_7j_min"]) | \
          (df["tmin_7j"] < d["tmin_7j_max"])
    good = ~bad & ((df["pluie_30j"] >= f["pluie_30j_min"]) | (df["jours_depuis_20mm"] <= f["jours_depuis_20mm_max"]))
    return np.select([bad, good], ["defavorable", "favorable"], "normale")


def validate(feats: pd.DataFrame, effort: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Rapport observé / attendu de l'activité des champignons par classe et par année."""
    rules, act = cfg["classes_meteo"], cfg["niveau_activite"]
    grid = zone_grid()
    zone_w = feats[feats["cellule"].isin(zone_cells(grid))].groupby("date")[
        ["pluie_30j", "tmax_7j", "tmin_7j", "jours_depuis_20mm"]].mean()
    pool = activity_pool(effort, zone_w, tuple(rules["horizon_jours"]), 1, act["debut"], act["effort_min"])
    pool["classe"] = classify(pool, rules)
    pool["annee"] = pool["date"].dt.year
    rows = []
    for (c, y), g in pool.groupby(["classe", "annee"]):
        rows.append({"classe": c, "annee": str(y), "jours": len(g), "observees": g["n"].sum(),
                     "attendues": g["e_loo"].sum()})
    for c, g in pool.groupby("classe"):
        rows.append({"classe": c, "annee": "toutes", "jours": len(g), "observees": g["n"].sum(),
                     "attendues": g["e_loo"].sum()})
    t = pd.DataFrame(rows)
    t["rapport"] = t["observees"] / t["attendues"]
    return t


def factors(valid: pd.DataFrame) -> dict[str, float]:
    """Facteur multiplicatif de chaque classe (toutes années)."""
    v = valid[valid["annee"] == "toutes"].set_index("classe")["rapport"]
    return {c: float(v.get(c, 1.0)) for c in CLASSES}


def main() -> None:
    cfg = load_yaml("modele.yaml")
    feats = pd.read_parquet(PROCESSED_DIR / "meteo_features.parquet")
    effort = pd.read_parquet(PROCESSED_DIR / "inat_effort.parquet")
    v = validate(feats, effort, cfg)
    v.to_parquet(FACTEUR_PATH, index=False)
    print(v.pivot(index="classe", columns="annee", values="rapport").round(2).to_string())
    print(f"Écrit : {FACTEUR_PATH}")


if __name__ == "__main__":
    main()
