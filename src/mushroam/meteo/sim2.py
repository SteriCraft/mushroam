"""Réanalyse SIM2 de Météo-France (SAFRAN-ISBA-MODCOU) : météo et humidité des sols.

Grille de 8 km, quotidienne depuis 1958, mise à jour chaque jour. Données
ouvertes, sans compte (meteo.data.gouv.fr, jeu « SIM quotidienne »). Un fichier
par année pour toute la France (~140 Mo), plus un fichier « latest » pour les
derniers jours.

On ne garde que les mailles de la zone d'étude : data/raw/sim2/zone/sim2_<année>.parquet.
Les années passées sont téléchargées une seule fois ; l'année en cours et
« latest » sont refaites à chaque exécution. Les fichiers France entière ne
sont pas conservés (sauf --keep-raw).

Usage : python -m mushroam.meteo.sim2 [--debut 1999] [--keep-raw]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from pyproj import Transformer

from mushroam.config import PROCESSED_DIR, RAW_DIR, load_zone
from mushroam.http import USER_AGENT

BASE_URL = "https://meteofrance.s3.sbg.io.cloud.ovh.net/data/REF_CC/SIM"
GRID_URL = f"{BASE_URL}/coordonnees_grille_safran_lambert-2-etendu.csv"
RAW = RAW_DIR / "sim2"
ZONE_DIR = RAW / "zone"
GRID_PATH = PROCESSED_DIR / "sim2_grille.parquet"
MARGE_KM = 10  # mailles retenues au-delà du rayon, pour les bords de zone
CELL_HM = 80  # pas de la grille SAFRAN (hectomètres)

# Variables conservées (voir le PDF « SIM_QUOTIDIENNE_parametres » du jeu de données).
COLUMNS = {
    "PRELIQ": "pluie_liquide",  # précipitations liquides (mm)
    "PRENEI": "neige",          # précipitations solides (mm)
    "T": "tmoy",                # température moyenne (°C)
    "TINF_H": "tmin",           # température minimale (°C)
    "TSUP_H": "tmax",           # température maximale (°C)
    "HU": "humidite_air",       # humidité relative (%)
    "ETP": "etp",               # évapotranspiration potentielle (mm)
    "EVAP": "evap",             # évapotranspiration réelle (mm)
    "SWI": "swi",               # indice d'humidité des sols (0 = point de flétrissement, 1 = capacité au champ)
    "WG_RACINE": "eau_racinaire",  # contenu en eau de la zone racinaire (m3/m3)
}

# Lambert II étendu (coordonnées SAFRAN) <-> WGS84
TO_L2E = Transformer.from_crs("EPSG:4326", "EPSG:27572", always_xy=True)


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return dest


def zone_grid(force: bool = False) -> pd.DataFrame:
    """Mailles SAFRAN dont le centre est à moins de rayon + marge du centre de zone."""
    if GRID_PATH.exists() and not force:
        return pd.read_parquet(GRID_PATH)
    path = RAW / "coordonnees_grille.csv"
    if not path.exists():
        download(GRID_URL, path)
    g = pd.read_csv(path, sep=";", decimal=",")
    g.columns = ["lambx", "lamby", "lat", "lng"]
    zone = load_zone()
    from mushroam.observations import haversine_km  # import local : évite un cycle
    d = haversine_km(zone["centre"]["lat"], zone["centre"]["lng"], g["lat"], g["lng"])
    g = g[d <= zone["rayon_km"] + MARGE_KM].copy()
    g["cellule"] = g["lambx"].astype(str) + "_" + g["lamby"].astype(str)
    from mushroam.habitat.dem import build_dem, sample_altitude
    g["altitude_m"] = sample_altitude(g["lat"], g["lng"], build_dem())
    g = g.reset_index(drop=True)
    g.to_parquet(GRID_PATH, index=False)
    return g


def extract_year(name: str, grid: pd.DataFrame, refresh: bool, keep_raw: bool) -> Path:
    out = ZONE_DIR / f"sim2_{name}.parquet"
    if out.exists() and not refresh:
        return out
    gz = RAW / f"QUOT_SIM2_{name}.csv.gz"
    if not gz.exists() or refresh:
        download(f"{BASE_URL}/QUOT_SIM2_{name}.csv.gz", gz)
    keys = set(zip(grid["lambx"], grid["lamby"]))
    parts = []
    for chunk in pd.read_csv(gz, sep=";", usecols=["LAMBX", "LAMBY", "DATE", *COLUMNS],
                             chunksize=1_000_000):
        mask = [k in keys for k in zip(chunk["LAMBX"], chunk["LAMBY"])]
        parts.append(chunk[mask])
    df = pd.concat(parts, ignore_index=True)
    df = pd.DataFrame({
        "cellule": df["LAMBX"].astype(str) + "_" + df["LAMBY"].astype(str),
        "date": pd.to_datetime(df["DATE"].astype(str), format="%Y%m%d"),
        **{new: df[old].astype("float32") for old, new in COLUMNS.items()},
    })
    ZONE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    if not keep_raw:
        gz.unlink()
    print(f"  {name} : {len(df):,} lignes, {df['cellule'].nunique()} mailles".replace(",", " "), flush=True)
    return out


def extract(debut: int = 1999, keep_raw: bool = False) -> pd.DataFrame:
    grid = zone_grid()
    current = date.today().year
    for year in range(debut, current + 1):
        extract_year(str(year), grid, refresh=(year == current), keep_raw=keep_raw)
    extract_year("latest", grid, refresh=True, keep_raw=keep_raw)
    return load_daily(debut)


def load_daily(debut: int = 1999) -> pd.DataFrame:
    """Données quotidiennes de la zone ; « latest » complète l'année en cours."""
    files = sorted(ZONE_DIR.glob("sim2_*.parquet"))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df[df["date"].dt.year >= debut]
    df = df.drop_duplicates(["cellule", "date"], keep="last")
    return df.sort_values(["cellule", "date"]).reset_index(drop=True)


def cell_for_points(lats, lngs, grid: pd.DataFrame | None = None) -> np.ndarray:
    """Maille SAFRAN la plus proche de chaque point (None hors de la grille de zone)."""
    grid = zone_grid() if grid is None else grid
    x, y = TO_L2E.transform(np.asarray(lngs, float), np.asarray(lats, float))
    x, y = x / 100, y / 100  # m -> hm
    gx, gy = grid["lambx"].to_numpy(float), grid["lamby"].to_numpy(float)
    out = np.empty(len(x), dtype=object)
    for i in range(0, len(x), 5000):
        dx = x[i:i + 5000, None] - gx[None, :]
        dy = y[i:i + 5000, None] - gy[None, :]
        d2 = dx * dx + dy * dy
        j = d2.argmin(axis=1)
        ok = d2[np.arange(len(j)), j] <= (CELL_HM * 0.75) ** 2
        out[i:i + 5000] = np.where(ok, grid["cellule"].to_numpy()[j], None)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debut", type=int, default=1999)
    parser.add_argument("--keep-raw", action="store_true", help="conserver les fichiers France entière")
    args = parser.parse_args()
    grid = zone_grid(force=True)
    print(f"Grille : {len(grid)} mailles SAFRAN dans la zone (+{MARGE_KM} km)")
    df = extract(args.debut, args.keep_raw)
    print(f"Total : {len(df):,} lignes, du {df['date'].min():%d/%m/%Y} au {df['date'].max():%d/%m/%Y}"
          .replace(",", " "))


if __name__ == "__main__":
    main()
