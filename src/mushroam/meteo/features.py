"""Variables météo décalées, par maille et par jour (approche par analogues).

Pour chaque maille SAFRAN et chaque date d, les fenêtres se terminent le jour d
inclus (« ce qui s'est passé jusqu'à aujourd'hui ») :
- pluie_7j, pluie_14j, pluie_21j, pluie_30j : cumuls de précipitations (mm) ;
- bilan_30j : cumul de (précipitations - ETP) sur 30 jours (mm) ;
- swi, swi_moy_7j : indice d'humidité des sols du jour et moyenne sur 7 jours ;
- swi_tend_7j, swi_tend_14j : variation du SWI sur 7 et 14 jours ;
- tmin_7j, tmin_14j, tmax_7j, tmax_14j : moyennes des températures min et max (°C) ;
- gel_7j, gel_14j : nombre de jours de gel (tmin < 0 °C) ;
- jours_depuis_20mm : jours écoulés depuis la dernière journée à 20 mm ou plus ;
- doy_sin, doy_cos : jour de l'année encodé sur le cercle.

Entrée : data/raw/sim2/zone/ (voir mushroam.meteo.sim2).
Sortie : data/processed/meteo_features.parquet

Usage : python -m mushroam.meteo.features
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mushroam.config import PROCESSED_DIR
from mushroam.meteo.sim2 import load_daily

OUT_PATH = PROCESSED_DIR / "meteo_features.parquet"
SEUIL_FORTE_PLUIE_MM = 20
MAX_JOURS_DEPUIS = 365
WARMUP_DAYS = 30


def days_since(event: np.ndarray, cap: int = MAX_JOURS_DEPUIS) -> np.ndarray:
    """event : tableau (jours × mailles) de booléens. Renvoie le nombre de jours
    depuis le dernier événement (0 le jour même), plafonné à `cap`."""
    out = np.empty(event.shape, dtype=np.float32)
    counter = np.full(event.shape[1], cap, dtype=np.float32)
    for t in range(event.shape[0]):
        counter = np.where(event[t], 0, np.minimum(counter + 1, cap))
        out[t] = counter
    return out


def compute(daily: pd.DataFrame) -> pd.DataFrame:
    """daily : colonnes cellule, date, pluie_liquide, neige, tmin, tmax, etp, swi."""
    d = daily.copy()
    d["pluie"] = d["pluie_liquide"] + d["neige"]
    wide = {v: d.pivot(index="date", columns="cellule", values=v)
            for v in ("pluie", "etp", "swi", "tmin", "tmax")}
    # Calendrier complet (au cas où un jour manquerait).
    idx = pd.date_range(wide["pluie"].index.min(), wide["pluie"].index.max(), freq="D")
    wide = {k: w.reindex(idx) for k, w in wide.items()}
    p, swi = wide["pluie"], wide["swi"]

    feats = {
        "pluie": p,
        **{f"pluie_{n}j": p.rolling(n, min_periods=n).sum() for n in (7, 14, 21, 30)},
        "bilan_30j": (p - wide["etp"]).rolling(30, min_periods=30).sum(),
        "swi": swi,
        "swi_moy_7j": swi.rolling(7, min_periods=7).mean(),
        "swi_tend_7j": swi - swi.shift(7),
        "swi_tend_14j": swi - swi.shift(14),
        **{f"{v}_{n}j": wide[v].rolling(n, min_periods=n).mean() for v in ("tmin", "tmax") for n in (7, 14)},
        **{f"gel_{n}j": (wide["tmin"] < 0).astype("float32").rolling(n, min_periods=n).sum() for n in (7, 14)},
        "jours_depuis_20mm": pd.DataFrame(days_since((p >= SEUIL_FORTE_PLUIE_MM).to_numpy()),
                                          index=p.index, columns=p.columns),
    }
    long = pd.concat({k: v.stack(future_stack=True) for k, v in feats.items()}, axis=1)
    long.index.names = ["date", "cellule"]
    long = long.reset_index()

    doy = long["date"].dt.day_of_year
    long["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    long["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

    # Les premiers jours n'ont pas d'historique complet.
    long = long[long["date"] >= idx[0] + pd.Timedelta(days=WARMUP_DAYS)]
    cols = [c for c in long.columns if c not in ("date", "cellule")]
    long[cols] = long[cols].astype("float32")
    return long[["cellule", "date", *cols]].sort_values(["cellule", "date"]).reset_index(drop=True)


def main() -> None:
    daily = load_daily()
    feats = compute(daily)
    feats.to_parquet(OUT_PATH, index=False)
    print(f"Écrit : {OUT_PATH} ({len(feats):,} lignes, {feats['cellule'].nunique()} mailles, "
          f"du {feats['date'].min():%d/%m/%Y} au {feats['date'].max():%d/%m/%Y})".replace(",", " "))


if __name__ == "__main__":
    main()
