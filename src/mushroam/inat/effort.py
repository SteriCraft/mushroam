"""Effort d'observation iNaturalist : comptes quotidiens dans la zone.

Deux séries, par jour d'observation, dans le rayon d'étude (observations
« vérifiables » = research + needs_id) :
- toutes : tous groupes confondus (plantes, oiseaux, insectes…) = effort ;
- fungi : Fungi hors lichens.

La part fungi / toutes mesure l'activité des champignons indépendamment du
nombre de personnes sur le terrain. Elle neutralise les effets de calendrier
(week-end, vacances, croissance d'iNat) qui touchent tous les groupes.

Sortie : data/processed/inat_effort.parquet (date, toutes, fungi)

Usage : python -m mushroam.inat.effort
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from mushroam.config import PROCESSED_DIR, load_taxa, load_zone
from mushroam.inat.client import INatClient

FIRST_YEAR = 2008
OUT_PATH = PROCESSED_DIR / "inat_effort.parquet"


def daily_counts(client: INatClient, year: int, extra: dict, cacheable: bool) -> pd.Series:
    z = load_zone()
    params = {
        "lat": z["centre"]["lat"], "lng": z["centre"]["lng"], "radius": z["rayon_km"],
        "verifiable": "true", "date_field": "observed", "interval": "day",
        "d1": f"{year}-01-01", "d2": f"{year}-12-31", **extra,
    }
    data = client.get("/v1/observations/histogram", params, cache_if=lambda _: cacheable)
    s = pd.Series(data["results"]["day"], dtype="float64")
    s.index = pd.to_datetime(s.index)
    return s


def build() -> pd.DataFrame:
    taxa = load_taxa()
    lichens = [e["inat_id"] for g in taxa.get("exclusions_fond", {}).values() for e in g if e.get("inat_id")]
    fungi = {"taxon_id": taxa["fond"]["inat_id"], "without_taxon_id": ",".join(map(str, lichens))}
    client = INatClient()
    current = date.today().year
    parts = []
    for y in range(FIRST_YEAR, current + 1):
        cacheable = y < current
        parts.append(pd.DataFrame({
            "toutes": daily_counts(client, y, {}, cacheable),
            "fungi": daily_counts(client, y, fungi, cacheable),
        }))
    df = pd.concat(parts).fillna(0).rename_axis("date").reset_index()
    df = df[df["date"] <= pd.Timestamp.today()]
    df.to_parquet(OUT_PATH, index=False)
    return df


def main() -> None:
    df = build()
    y = df.groupby(df["date"].dt.year)[["toutes", "fungi"]].sum()
    print(y.astype(int).to_string())
    print(f"Écrit : {OUT_PATH}")


if __name__ == "__main__":
    main()
