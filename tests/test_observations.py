import numpy as np
import pandas as pd
import pytest

from mushroam.gbif.extract import year_chunks
from mushroam.gbif.normalize import canonical_name, exact_day
from mushroam.observations import (flag_taxa, haversine_km, mark_duplicates, mark_repeated_points,
                                   species_level)

TAXA = {
    "fond": {"name": "Fungi", "inat_id": 47170, "gbif_key": 5},
    "cibles": {
        "coulemelle": {"membres": [{"name": "Macrolepiota procera", "inat_id": 63401, "gbif_key": 8914748}]},
        "bolets": {"membres": [
            {"name": "Boletaceae", "inat_id": 48702, "gbif_key": 8789},
            {"name": "Suillaceae", "inat_id": 53489, "gbif_key": 8455},
        ]},
    },
    "exclusions_fond": {"lichens": [
        {"name": "Lecanoromycetes", "inat_id": 54743, "gbif_key": 180},
        {"name": "Candelariomycetes", "inat_id": None, "gbif_key": 10792796},
    ]},
}


def test_haversine():
    # Montpellier -> Nîmes : environ 45 km
    assert haversine_km(43.6108, 3.8767, 43.8367, 4.3601) == pytest.approx(45, abs=2)


def test_exact_day():
    assert exact_day({"year": 2020, "month": 10, "day": 3}) == "2020-10-03"
    assert exact_day({"year": 2020, "month": 10, "day": None}) is None
    # Intervalle de dates : rejeté
    assert exact_day({"year": 2020, "month": 10, "day": 1,
                      "startDayOfYear": 275, "endDayOfYear": 305}) is None


def test_canonical_name():
    assert canonical_name({"taxonRank": "SPECIES", "species": "Boletus edulis",
                           "scientificName": "Boletus edulis Bull."}) == "Boletus edulis"
    assert canonical_name({"taxonRank": "GENUS", "genus": "Suillus"}) == "Suillus"


def test_species_level():
    assert species_level("Macrolepiota procera pseudo-olivascens") == "Macrolepiota procera"
    assert species_level("Suillus") == "Suillus"


def test_flag_taxa_selon_la_source():
    df = pd.DataFrame({
        "source": ["inat", "gbif", "gbif", "inat"],
        # Le même identifiant numérique n'a pas le même sens d'une source à l'autre.
        "lineage": [[47170, 48702], [5, 8789], [5, 180], [47170, 8789]],
    })
    df = flag_taxa(df, TAXA)
    assert df["cible_bolets"].tolist() == [True, True, False, False]
    assert df["membre_bolets"].tolist()[:2] == ["Boletaceae", "Boletaceae"]
    assert df["lichen"].tolist() == [False, False, True, False]


def test_doublons_priorite_inat():
    d = pd.Timestamp("2022-10-10")
    df = pd.DataFrame({
        "source": ["gbif", "inat", "gbif"],
        "observed_on": [d, d, d],
        "taxon_name": ["Boletus edulis", "Boletus edulis", "Boletus edulis"],
        "lat": [44.001, 44.002, 44.2],
        "lng": [3.501, 3.502, 3.5],
        "precision_m": [10.0, np.nan, 10.0],
    })
    assert mark_duplicates(df, 0.01).tolist() == [True, False, False]


def test_year_chunks():
    ch = year_chunks(2026)
    assert ch[0] == "1600,1989" and ch[1] == "1990" and ch[-1] == "2026"


def test_points_repetes():
    dates = pd.date_range("2022-01-01", periods=12, freq="7D")
    df = pd.DataFrame({
        "source": ["inat"] * 12 + ["inat"] * 3 + ["gbif"] * 12,
        "observer": ["inat:1"] * 12 + ["inat:2"] * 3 + ["gbif:x"] * 12,
        "lat": [43.63881] * 12 + [43.63881] * 3 + [44.0] * 12,
        "lng": [3.86390] * 12 + [3.86390] * 3 + [3.5] * 12,
        "observed_on": list(dates) + list(dates[:3]) + list(dates),
    })
    out = mark_repeated_points(df, sources=["inat"], arrondi_deg=0.0005, min_dates=10)
    # L'observateur 1 (12 dates) est marqué ; l'observateur 2 (3 dates) et GBIF ne le sont pas.
    assert out.tolist() == [True] * 12 + [False] * 3 + [False] * 12
