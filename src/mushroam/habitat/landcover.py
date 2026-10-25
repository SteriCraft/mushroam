"""Occupation du sol : ESA WorldCover 2021 (10 m, lu ici à 40 m via ses aperçus).

Accès libre (bucket AWS public). Classes : 10 arbres, 20 arbustes, 30 prairies,
40 cultures, 50 bâti, 60 sol nu, 70 neige, 80 eau, 90 zones humides, 95 mangroves,
100 mousses et lichens.

Produit :
- data/processed/worldcover_40m.tif : classes d'occupation du sol ;
- data/processed/bati_fraction.tif : part de bâti dans une fenêtre carrée
  centrée sur chaque pixel (côté réglable, 600 m par défaut).

Usage : python -m mushroam.habitat.landcover
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge

from mushroam.config import PROCESSED_DIR, load_zone
from mushroam.habitat.dem import zone_bbox

TILE_URL = ("/vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
            "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")
OVERVIEW_LEVEL = 1  # 0 = 20 m, 1 = 40 m
LANDCOVER_PATH = PROCESSED_DIR / "worldcover_40m.tif"
BUILT_PATH = PROCESSED_DIR / "bati_fraction.tif"
BUILT_CLASS = 50
CLASSES = {10: "arbres", 20: "arbustes", 30: "prairies", 40: "cultures", 50: "bâti",
           60: "sol nu", 70: "neige", 80: "eau", 90: "zones humides", 95: "mangroves",
           100: "mousses et lichens"}


def tiles_for_bbox(bbox) -> list[str]:
    """Tuiles WorldCover de 3°×3°, nommées par leur coin sud-ouest."""
    lng0, lat0, lng1, lat1 = bbox
    tiles = []
    for la in range(math.floor(lat0 / 3) * 3, math.floor(lat1 / 3) * 3 + 1, 3):
        for ln in range(math.floor(lng0 / 3) * 3, math.floor(lng1 / 3) * 3 + 1, 3):
            ns, ew = ("N" if la >= 0 else "S"), ("E" if ln >= 0 else "W")
            tiles.append(f"{ns}{abs(la):02d}{ew}{abs(ln):03d}")
    return tiles


def box_mean(a: np.ndarray, half: int) -> np.ndarray:
    """Moyenne glissante sur une fenêtre carrée de (2*half+1) pixels (image intégrale)."""
    p = np.pad(a.astype(np.float64), half + 1, mode="edge")
    c = p.cumsum(0).cumsum(1)
    k = 2 * half + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return (s / (k * k))[: a.shape[0], : a.shape[1]]


def build_landcover(force: bool = False) -> Path:
    if LANDCOVER_PATH.exists() and not force:
        return LANDCOVER_PATH
    bbox = zone_bbox(load_zone())
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES"):
        sources = [rasterio.open(TILE_URL.format(tile=t), overview_level=OVERVIEW_LEVEL)
                   for t in tiles_for_bbox(bbox)]
        try:
            mosaic, transform = merge(sources, bounds=bbox)
            profile = sources[0].profile.copy()
        finally:
            for s in sources:
                s.close()
    profile.update(driver="GTiff", height=mosaic.shape[1], width=mosaic.shape[2],
                   transform=transform, compress="deflate", tiled=True, blockxsize=512, blockysize=512)
    LANDCOVER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(LANDCOVER_PATH, "w", **profile) as dst:
        dst.write(mosaic)
    print(f"Écrit : {LANDCOVER_PATH} ({mosaic.shape[2]}×{mosaic.shape[1]} px)")
    return LANDCOVER_PATH


def build_built_fraction(window_m: float = 600, force: bool = False) -> Path:
    if BUILT_PATH.exists() and not force:
        return BUILT_PATH
    with rasterio.open(build_landcover()) as src:
        lc = src.read(1)
        profile = src.profile.copy()
        # Taille d'un pixel en mètres (degrés -> mètres à la latitude de la zone).
        lat = load_zone()["centre"]["lat"]
        px_m = src.res[1] * 111_320 * (1 + math.cos(math.radians(lat))) / 2
    half = max(1, round(window_m / px_m / 2))
    frac = box_mean(lc == BUILT_CLASS, half).astype(np.float32)
    profile.update(dtype="float32", nodata=None)
    with rasterio.open(BUILT_PATH, "w", **profile) as dst:
        dst.write(frac, 1)
    print(f"Écrit : {BUILT_PATH} (fenêtre {2 * half + 1} px ≈ {(2 * half + 1) * px_m:.0f} m)")
    return BUILT_PATH


def sample(path: Path, lats, lngs) -> np.ndarray:
    lats, lngs = np.asarray(lats, float), np.asarray(lngs, float)
    out = np.full(len(lats), np.nan)
    ok = ~(np.isnan(lats) | np.isnan(lngs))
    with rasterio.open(path) as src:
        out[ok] = [v[0] for v in src.sample(zip(lngs[ok], lats[ok]))]
    return out


def main() -> None:
    build_landcover(force=True)
    build_built_fraction(force=True)


if __name__ == "__main__":
    main()
