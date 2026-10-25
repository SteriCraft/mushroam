"""Modèle numérique de terrain : Copernicus DEM GLO-90 (résolution ~90 m).

Tuiles COG de 1°×1° en accès libre (bucket AWS public, sans compte). Une tuile
absente (404) correspond à la mer. Les tuiles sont assemblées en une seule
image GeoTIFF couvrant l'emprise de la zone.

Usage : python -m mushroam.habitat.dem
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.merge import merge

from mushroam.config import PROCESSED_DIR, RAW_DIR, load_zone
from mushroam.http import USER_AGENT

TILE_URL = ("https://copernicus-dem-90m.s3.amazonaws.com/"
            "Copernicus_DSM_COG_30_{tile}_DEM/Copernicus_DSM_COG_30_{tile}_DEM.tif")
DEM_PATH = PROCESSED_DIR / "dem_90m.tif"
KM_PER_DEG_LAT = 111.32


def zone_bbox(zone: dict, margin_km: float = 5) -> tuple[float, float, float, float]:
    """(lng_min, lat_min, lng_max, lat_max) englobant le cercle de la zone."""
    lat, lng = zone["centre"]["lat"], zone["centre"]["lng"]
    r = zone["rayon_km"] + margin_km
    dlat = r / KM_PER_DEG_LAT
    dlng = r / (KM_PER_DEG_LAT * math.cos(math.radians(lat)))
    return lng - dlng, lat - dlat, lng + dlng, lat + dlat


def tile_name(lat: int, lng: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lng >= 0 else "W"
    return f"{ns}{abs(lat):02d}_00_{ew}{abs(lng):03d}_00"


def tiles_for_bbox(bbox) -> list[str]:
    lng0, lat0, lng1, lat1 = bbox
    return [tile_name(la, ln)
            for la in range(math.floor(lat0), math.floor(lat1) + 1)
            for ln in range(math.floor(lng0), math.floor(lng1) + 1)]


def download_tiles(tiles: list[str], dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in tiles:
        p, sea = dest / f"{t}.tif", dest / f"{t}.absent"
        if sea.exists():
            continue
        if not p.exists():
            r = requests.get(TILE_URL.format(tile=t), headers={"User-Agent": USER_AGENT}, timeout=300)
            if r.status_code == 404:  # tuile entièrement en mer
                sea.touch()
                continue
            r.raise_for_status()
            p.write_bytes(r.content)
            print(f"  tuile {t} : {len(r.content) / 1e6:.1f} Mo")
        paths.append(p)
    return paths


def build_dem(force: bool = False) -> Path:
    if DEM_PATH.exists() and not force:
        return DEM_PATH
    bbox = zone_bbox(load_zone())
    paths = download_tiles(tiles_for_bbox(bbox), RAW_DIR / "dem")
    sources = [rasterio.open(p) for p in paths]
    try:
        mosaic, transform = merge(sources, bounds=bbox)
        profile = sources[0].profile.copy()
    finally:
        for s in sources:
            s.close()
    profile.update(driver="GTiff", height=mosaic.shape[1], width=mosaic.shape[2],
                   transform=transform, compress="deflate", tiled=True)
    profile.pop("blockxsize", None), profile.pop("blockysize", None)
    DEM_PATH.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(DEM_PATH, "w", **profile) as dst:
        dst.write(mosaic)
    print(f"Écrit : {DEM_PATH} ({mosaic.shape[2]}×{mosaic.shape[1]} px)")
    return DEM_PATH


def sample_altitude(lats, lngs, dem_path: Path = DEM_PATH) -> np.ndarray:
    """Altitude (m) aux points donnés ; NaN hors emprise ou en mer."""
    lats, lngs = np.asarray(lats, float), np.asarray(lngs, float)
    out = np.full(len(lats), np.nan)
    with rasterio.open(dem_path) as src:
        ok = ~(np.isnan(lats) | np.isnan(lngs))
        vals = np.array([v[0] for v in src.sample(zip(lngs[ok], lats[ok]))], dtype=float)
        if src.nodata is not None:
            vals[vals == src.nodata] = np.nan
        out[ok] = vals
    return out


def main() -> None:
    build_dem(force=True)


if __name__ == "__main__":
    main()
