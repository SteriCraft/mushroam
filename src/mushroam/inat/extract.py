"""Extraction de toutes les observations de Fungi dans le rayon d'étude.

Une seule extraction couvre à la fois le fond de référence (toutes les Fungi)
et les cibles, qui en sont des sous-ensembles. Tous les niveaux de qualité sont
conservés ; le filtrage (research / needs_id, précision, floutage) se fait en aval.

Pagination par identifiant croissant (id_above) pour contourner la limite de
10 000 résultats par jeu de paramètres. Seules les pages complètes sont mises
en cache : la dernière page est refaite à chaque exécution, ce qui permet de
récupérer les nouvelles observations.

Résultat : data/processed/inat.parquet (une ligne par observation, format iNat).

Usage : python -m mushroam.inat.extract [--refresh]
"""

from __future__ import annotations

import argparse

from mushroam.config import PROCESSED_DIR, load_taxa, load_zone
from mushroam.inat.client import INatClient
from mushroam.inat.normalize import to_dataframe

PER_PAGE = 200

# Champs demandés à l'API v2 (la v1 renvoie ~65 fois plus de données).
FIELDS = ",".join([
    "id", "uuid", "observed_on", "time_observed_at", "created_at",
    "location", "positional_accuracy", "public_positional_accuracy",
    "obscured", "geoprivacy", "taxon_geoprivacy",
    "quality_grade", "captive", "community_taxon_id",
    "identifications_count", "num_identification_agreements",
    "num_identification_disagreements",
    "taxon.id", "taxon.name", "taxon.rank", "taxon.ancestor_ids",
    "user.id",
])


def iter_observations(client: INatClient, taxon_id: int, lat: float, lng: float,
                      radius_km: float, refresh: bool = False):
    id_above = 0
    while True:
        params = {
            "taxon_id": taxon_id,
            "lat": lat,
            "lng": lng,
            "radius": radius_km,
            "order_by": "id",
            "order": "asc",
            "id_above": id_above,
            "per_page": PER_PAGE,
            "fields": FIELDS,
        }
        data = client.get(
            "/v2/observations", params, refresh=refresh,
            cache_if=lambda d: len(d["results"]) == PER_PAGE,
        )
        results = data["results"]
        yield from results
        if len(results) < PER_PAGE:
            return
        id_above = results[-1]["id"]


def extract(refresh: bool = False):
    zone = load_zone()
    taxa = load_taxa()
    client = INatClient()
    fungi_id = taxa["fond"]["inat_id"]
    observations = []
    for i, obs in enumerate(iter_observations(
        client, fungi_id, zone["centre"]["lat"], zone["centre"]["lng"],
        zone["rayon_km"], refresh=refresh,
    )):
        observations.append(obs)
        if i % 2000 == 0:
            print(f"  {i} observations... (HTTP {client.n_http}, cache {client.n_cache})", flush=True)
    print(f"Total : {len(observations)} observations (HTTP {client.n_http}, cache {client.n_cache})")

    df = to_dataframe(observations)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / "inat.parquet"
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
