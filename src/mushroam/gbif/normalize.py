"""Mise à plat des occurrences GBIF en table pandas."""

from __future__ import annotations

import pandas as pd

LINEAGE_KEYS = ("kingdomKey", "phylumKey", "classKey", "orderKey", "familyKey",
                "genusKey", "speciesKey", "taxonKey", "acceptedTaxonKey")

# Rang GBIF -> champ donnant le nom canonique (sans auteur).
CANONICAL_FIELD = {"SPECIES": "species", "SUBSPECIES": "species", "VARIETY": "species",
                   "FORM": "species", "GENUS": "genus", "FAMILY": "family",
                   "ORDER": "order", "CLASS": "class", "PHYLUM": "phylum", "KINGDOM": "kingdom"}


def canonical_name(rec: dict) -> str | None:
    rank = rec.get("taxonRank")
    field = CANONICAL_FIELD.get(rank)
    if field and rec.get(field):
        return rec[field]
    name = rec.get("acceptedScientificName") or rec.get("scientificName")
    return " ".join(name.split()[:2]) if name else None


def exact_day(rec: dict) -> str | None:
    """Date au jour près, ou None si la date est imprécise (mois, année, intervalle)."""
    y, m, d = rec.get("year"), rec.get("month"), rec.get("day")
    if not (y and m and d):
        return None
    start, end = rec.get("startDayOfYear"), rec.get("endDayOfYear")
    if start is not None and end is not None and start != end:
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def flatten(rec: dict) -> dict:
    return {
        "gbif_id": rec["key"],
        "dataset_key": rec.get("datasetKey"),
        "dataset_name": rec.get("datasetName"),
        "publisher_key": rec.get("publishingOrgKey"),
        "basis_of_record": rec.get("basisOfRecord"),
        "event_date": rec.get("eventDate"),
        "observed_on": exact_day(rec),
        "lat": rec.get("decimalLatitude"),
        "lng": rec.get("decimalLongitude"),
        "coordinate_uncertainty_m": rec.get("coordinateUncertaintyInMeters"),
        "generalized": bool(rec.get("dataGeneralizations") or rec.get("informationWithheld")),
        "issues": rec.get("issues") or [],
        "taxon_name": canonical_name(rec),
        "taxon_rank": (rec.get("taxonRank") or "").lower() or None,
        "lineage": sorted({rec[k] for k in LINEAGE_KEYS if rec.get(k)}),
        "recorded_by": rec.get("recordedBy"),
        "is_in_cluster": bool(rec.get("isInCluster")),
    }


def to_dataframe(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([flatten(r) for r in records])
    if df.empty:
        return df
    df = df.drop_duplicates("gbif_id", keep="last").reset_index(drop=True)
    df["observed_on"] = pd.to_datetime(df["observed_on"], errors="coerce")
    return df
