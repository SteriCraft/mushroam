"""Extraction des occurrences de Fungi GBIF dans le rayon d'étude.

GBIF agrège notamment les données du SINP / INPN (Parcs nationaux, Conservatoires
botaniques, ONF, inventaires ZNIEFF…), Observation.org, des herbiers et des
données mycologiques d'associations. Le jeu « iNaturalist Research-grade
Observations » est exclu à la fusion : iNaturalist est extrait directement.

L'API de recherche limite la pagination à 100 000 résultats par requête : on
découpe donc par année. Les années passées sont figées en cache (instantané) ;
l'année en cours est refaite à chaque exécution.

Résultat : data/processed/gbif.parquet (une ligne par occurrence, format GBIF).

Usage : python -m mushroam.gbif.extract [--refresh]
"""

from __future__ import annotations

import argparse
from datetime import date

from mushroam.config import PROCESSED_DIR, load_taxa, load_zone
from mushroam.gbif.client import GBIFClient
from mushroam.gbif.normalize import to_dataframe

PAGE_SIZE = 300
MAX_OFFSET = 100_000
FIRST_YEAR = 1990  # avant : regroupé en un seul bloc


def year_chunks(current_year: int) -> list[str]:
    return [f"1600,{FIRST_YEAR - 1}"] + [str(y) for y in range(FIRST_YEAR, current_year + 1)]


def iter_occurrences(client: GBIFClient, kingdom_key: int, lat: float, lng: float,
                     radius_km: float, year: str, cacheable: bool, refresh: bool = False):
    offset = 0
    while True:
        params = {
            "kingdomKey": kingdom_key,
            "geoDistance": f"{lat},{lng},{radius_km}km",
            "occurrenceStatus": "PRESENT",
            "hasCoordinate": "true",
            "hasGeospatialIssue": "false",
            "year": year,
            "limit": PAGE_SIZE,
            "offset": offset,
        }
        data = client.get("/occurrence/search", params, refresh=refresh,
                          cache_if=lambda _: cacheable)
        if data["count"] > MAX_OFFSET:
            raise RuntimeError(f"Bloc {year} trop gros ({data['count']}), le découper davantage")
        yield from data["results"]
        offset += PAGE_SIZE
        if data.get("endOfRecords", True) or offset >= data["count"]:
            return


def dataset_titles(client: GBIFClient, keys) -> dict[str, str]:
    """Titre de chaque jeu de données (absent de la plupart des réponses de recherche)."""
    titles = {}
    for key in sorted(k for k in keys if k):
        titles[key] = client.get(f"/dataset/{key}", {}).get("title")
    return titles


def extract(refresh: bool = False):
    zone = load_zone()
    taxa = load_taxa()
    client = GBIFClient()
    current = date.today().year
    records = []
    for chunk in year_chunks(current):
        last_year = int(chunk.split(",")[-1])
        n0 = len(records)
        records.extend(iter_occurrences(
            client, taxa["fond"]["gbif_key"], zone["centre"]["lat"], zone["centre"]["lng"],
            zone["rayon_km"], chunk, cacheable=last_year < current, refresh=refresh,
        ))
        print(f"  {chunk:>10s} : {len(records) - n0:6d} (HTTP {client.n_http}, cache {client.n_cache})",
              flush=True)
    print(f"Total : {len(records)} occurrences")

    df = to_dataframe(records)
    titles = dataset_titles(client, df["dataset_key"].unique())
    print(f"Jeux de données : {len(titles)}")
    df["dataset_name"] = df["dataset_key"].map(titles).fillna(df["dataset_name"])
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / "gbif.parquet"
    df.to_parquet(out, index=False)
    print(f"Écrit : {out}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="ignorer le cache et tout retélécharger")
    args = parser.parse_args()
    extract(refresh=args.refresh)


if __name__ == "__main__":
    main()
