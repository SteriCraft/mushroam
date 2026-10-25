"""Table unifiée des observations de champignons, toutes sources confondues.

Entrées : data/processed/inat.parquet et gbif.parquet (voir mushroam.inat.extract
et mushroam.gbif.extract). Règles de fusion : config/sources.yaml.

Sortie : data/processed/observations.parquet, une ligne par observation exploitable :
- date au jour près, position dans le rayon d'étude ;
- `lichen` : à exclure du fond de référence ;
- `cible_<clé>` / `membre_<clé>` : appartenance aux cibles de config/taxa.yaml ;
- `indic_<groupe>` : espèce témoin du groupe (config/taxa.yaml, section indicateurs) ;
- `precision_m` : incertitude de position (NaN si inconnue) ;
- `ok_habitat` / `ok_meteo` : précision suffisante pour chaque couche ;
- `doublon` : copie probable d'une autre ligne (même date, taxon, lieu à ~1 km près) ;
- `altitude_m` : altitude du point d'après le MNT Copernicus 90 m ;
- `bati` / `urbain` : part de bâti autour du point (WorldCover) et dépassement du seuil ;
- `point_repete` : point où le même observateur saisit à de nombreuses dates
  (bureau, laboratoire, domicile) ;
- `retenue` : ni doublon, ni urbaine, ni point répété. C'est le filtre à appliquer
  par défaut, au fond comme aux cibles (les lichens s'excluent en plus du fond) ;
- `cellule_meteo` : maille SAFRAN (SIM2) la plus proche, clé de jointure avec la météo.

Usage : python -m mushroam.observations
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mushroam.config import PROCESSED_DIR, load_taxa, load_yaml, load_zone
from mushroam.habitat.dem import build_dem, sample_altitude
from mushroam.habitat.landcover import build_built_fraction
from mushroam.habitat.landcover import sample as sample_raster
from mushroam.meteo.sim2 import cell_for_points

EARTH_RADIUS_KM = 6371.0088

COLUMNS = ["source", "source_id", "dataset", "basis_of_record", "observed_on", "lat", "lng",
           "precision_m", "obscured", "quality", "taxon_name", "taxon_rank", "lineage", "observer"]


def haversine_km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = (np.radians(np.asarray(x, float)) for x in (lat1, lng1, lat2, lng2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def species_level(name):
    """Ramène un nom infraspécifique au binôme, pour comparer iNat et GBIF."""
    if not isinstance(name, str):
        return name
    parts = name.split()
    return " ".join(parts[:2]) if len(parts) > 2 else name


def harmonize_inat(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    keep = df["quality_grade"].isin(rules["inat"]["quality_grades"]) & ~df["captive"]
    df = df[keep]
    precision = df["positional_accuracy"].astype(float)
    obscured_prec = np.fmax(df["public_positional_accuracy"].astype(float), rules["precision_floutee_m"])
    return pd.DataFrame({
        "source": "inat",
        "source_id": "inat:" + df["id"].astype(str),
        "dataset": "iNaturalist",
        "basis_of_record": "HUMAN_OBSERVATION",
        "observed_on": df["observed_on"],
        "lat": df["lat"],
        "lng": df["lng"],
        "precision_m": np.where(df["obscured"], obscured_prec, precision),
        "obscured": df["obscured"],
        "quality": df["quality_grade"],
        "taxon_name": df["taxon_name"].map(species_level),
        "taxon_rank": df["taxon_rank"],
        "lineage": df["lineage"],
        "observer": "inat:" + df["user_id"].astype("Int64").astype(str),
    })


def harmonize_gbif(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    g = rules["gbif"]
    keep = (~df["dataset_key"].isin(g["datasets_exclus"].keys())
            & df["basis_of_record"].isin(g["basis_of_record"]))
    df = df[keep]
    observer = df["recorded_by"].fillna("").str.strip().str.lower()
    return pd.DataFrame({
        "source": "gbif",
        "source_id": "gbif:" + df["gbif_id"].astype(str),
        "dataset": df["dataset_name"],
        "basis_of_record": df["basis_of_record"],
        "observed_on": df["observed_on"],
        "lat": df["lat"],
        "lng": df["lng"],
        "precision_m": df["coordinate_uncertainty_m"].astype(float),
        "obscured": df["generalized"],
        "quality": "gbif",
        "taxon_name": df["taxon_name"].map(species_level),
        "taxon_rank": df["taxon_rank"],
        "lineage": df["lineage"],
        "observer": np.where(observer == "", None, "gbif:" + observer),
    })


def flag_taxa(df: pd.DataFrame, taxa: dict) -> pd.DataFrame:
    """Ajoute lichen, cible_* et membre_*, en comparant la lignée de chaque ligne
    aux identifiants iNat ou GBIF selon la source."""
    id_field = {"inat": "inat_id", "gbif": "gbif_key"}
    lineages = [set(lin) for lin in df["lineage"]]
    sources = df["source"].tolist()

    def ids(entries, src):
        return {e[id_field[src]]: e["name"] for e in entries if e.get(id_field[src])}

    lichens = [e for group in taxa.get("exclusions_fond", {}).values() for e in group]
    lichen_ids = {s: set(ids(lichens, s)) for s in id_field}
    df["lichen"] = [bool(lin & lichen_ids[s]) for lin, s in zip(lineages, sources)]

    for key, cible in taxa["cibles"].items():
        members = {s: ids(cible["membres"], s) for s in id_field}
        names = [next((n for tid, n in members[s].items() if tid in lin), None)
                 for lin, s in zip(lineages, sources)]
        df[f"membre_{key}"] = names
        df[f"cible_{key}"] = [n is not None for n in names]

    # Espèces témoins : une colonne booléenne par groupe (indic_prairie, …).
    for key, groupe in taxa.get("indicateurs", {}).items():
        members = {s: set(ids(groupe["membres"], s)) for s in id_field}
        df[f"indic_{key}"] = [bool(lin & members[s]) for lin, s in zip(lineages, sources)]
    return df


def mark_duplicates(df: pd.DataFrame, step_deg: float) -> pd.Series:
    """Vrai pour les copies probables. On garde en priorité iNat, puis la position
    la plus précise."""
    key = pd.DataFrame({
        "d": df["observed_on"],
        "t": df["taxon_name"].str.lower(),
        "la": (df["lat"] / step_deg).round().astype("Int64"),
        "ln": (df["lng"] / step_deg).round().astype("Int64"),
    })
    order = (df.assign(_inat=df["source"].eq("inat"), _p=df["precision_m"].fillna(np.inf))
               .sort_values(["_inat", "_p"], ascending=[False, True]).index)
    return key.loc[order].duplicated().reindex(df.index)


def build() -> pd.DataFrame:
    rules, taxa, zone = load_yaml("sources.yaml"), load_taxa(), load_zone()
    inat = harmonize_inat(pd.read_parquet(PROCESSED_DIR / "inat.parquet"), rules)
    gbif = harmonize_gbif(pd.read_parquet(PROCESSED_DIR / "gbif.parquet"), rules)
    df = pd.concat([inat, gbif], ignore_index=True)[COLUMNS]
    n0 = len(df)

    c = zone["centre"]
    df["dist_km"] = haversine_km(c["lat"], c["lng"], df["lat"], df["lng"])
    df = df[df["observed_on"].notna() & df["lat"].notna() & (df["dist_km"] <= zone["rayon_km"])]
    df = df[df["observed_on"] <= pd.Timestamp.today()].reset_index(drop=True)
    print(f"Sans date au jour près, hors zone ou incohérentes : {n0 - len(df)} lignes écartées")

    df = flag_taxa(df, taxa)
    df["ok_habitat"] = df["precision_m"] <= rules["precision_max_habitat_m"]
    df["ok_meteo"] = df["precision_m"].isna() | (df["precision_m"] <= rules["precision_max_meteo_m"])
    df["doublon"] = mark_duplicates(df, rules["doublons_arrondi_deg"])
    df["altitude_m"] = sample_altitude(df["lat"], df["lng"], build_dem())

    urb = rules["filtre_urbain"]
    df["bati"] = sample_raster(build_built_fraction(urb["fenetre_m"]), df["lat"], df["lng"])
    df["urbain"] = df["bati"] >= urb["seuil_bati"]
    df["point_repete"] = mark_repeated_points(df, **rules["points_repetes"])
    df["retenue"] = ~(df["doublon"] | df["urbain"] | df["point_repete"])
    df["cellule_meteo"] = cell_for_points(df["lat"], df["lng"])
    return df


def mark_repeated_points(df: pd.DataFrame, sources: list[str], arrondi_deg: float,
                         min_dates: int) -> pd.Series:
    """Vrai pour les observations faites au même point (à `arrondi_deg` près) par un
    même observateur, à au moins `min_dates` dates distinctes."""
    pt = pd.DataFrame({
        "o": df["observer"],
        "la": (df["lat"] / arrondi_deg).round(),
        "ln": (df["lng"] / arrondi_deg).round(),
    })
    n_dates = df.groupby([pt["o"], pt["la"], pt["ln"]])["observed_on"].transform("nunique")
    return df["source"].isin(sources) & df["observer"].notna() & (n_dates >= min_dates)


def main() -> None:
    df = build()
    out = PROCESSED_DIR / "observations.parquet"
    df.to_parquet(out, index=False)
    print(f"Écrit : {out} ({len(df)} lignes, dont {df['doublon'].sum()} doublons probables)")
    print(df.groupby("source")[["lichen", "cible_coulemelle", "cible_bolets", "doublon",
                                "urbain", "point_repete", "retenue"]].sum())


if __name__ == "__main__":
    main()
