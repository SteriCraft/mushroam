"""Mise à plat des observations iNaturalist (API v2) en table pandas."""

from __future__ import annotations

import pandas as pd


def parse_location(loc: str | None) -> tuple[float | None, float | None]:
    if not loc:
        return None, None
    lat, lng = loc.split(",")
    return float(lat), float(lng)


def flatten(obs: dict) -> dict:
    taxon = obs.get("taxon") or {}
    lat, lng = parse_location(obs.get("location"))
    ancestors = taxon.get("ancestor_ids") or []
    return {
        "id": obs["id"],
        "uuid": obs.get("uuid"),
        "observed_on": obs.get("observed_on"),
        "time_observed_at": obs.get("time_observed_at"),
        "created_at": obs.get("created_at"),
        "lat": lat,
        "lng": lng,
        "positional_accuracy": obs.get("positional_accuracy"),
        "public_positional_accuracy": obs.get("public_positional_accuracy"),
        "obscured": bool(obs.get("obscured")),
        "geoprivacy": obs.get("geoprivacy"),
        "taxon_geoprivacy": obs.get("taxon_geoprivacy"),
        "quality_grade": obs.get("quality_grade"),
        "captive": bool(obs.get("captive")),
        "taxon_id": taxon.get("id"),
        "taxon_name": taxon.get("name"),
        "taxon_rank": taxon.get("rank"),
        # Lignée complète (ancêtres + taxon) : sert à repérer cibles et exclusions.
        "lineage": sorted(set(ancestors) | ({taxon["id"]} if taxon.get("id") else set())),
        "community_taxon_id": obs.get("community_taxon_id"),
        "identifications_count": obs.get("identifications_count"),
        "num_identification_agreements": obs.get("num_identification_agreements"),
        "num_identification_disagreements": obs.get("num_identification_disagreements"),
        "user_id": (obs.get("user") or {}).get("id"),
    }


def to_dataframe(observations: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([flatten(o) for o in observations])
    if df.empty:
        return df
    # Une observation peut apparaître deux fois si elle a été modifiée entre deux pages.
    df = df.drop_duplicates("id", keep="last").reset_index(drop=True)
    df["observed_on"] = pd.to_datetime(df["observed_on"], errors="coerce")
    for col in ("time_observed_at", "created_at"):
        df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    return df
