"""Grille d'habitat de 1 km (Lambert-93) sur la zone.

Pour chaque maille de 1 km dans le rayon :
- part de chaque classe de végétation de la BD Forêt v2 (`foret_<classe>`) ;
- part de chaque groupe de sols INRAE (`sol_<groupe>`) ;
- part de cultures, prairies et bâti d'après ESA WorldCover (`wc_<classe>`) ;
- altitude moyenne et relief (écart type de l'altitude) ;
- maille SIM2 correspondante (`cellule_meteo`).

Entrées : foret_50m.tif, sols_50m.tif (mushroam.habitat.vecteurs),
dem_90m.tif, worldcover_40m.tif.
Sortie : data/processed/habitat_1km.parquet

Usage : python -m mushroam.habitat.grille
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.warp import Resampling, reproject

from mushroam.config import PROCESSED_DIR, load_zone
from mushroam.habitat.dem import DEM_PATH
from mushroam.habitat.landcover import LANDCOVER_PATH
from mushroam.habitat.vecteurs import FOREST_CLASSES, FOREST_PATH, RES_M, SOIL_CLASSES, SOIL_PATH, grid_l93
from mushroam.meteo.sim2 import cell_for_points
from mushroam.observations import haversine_km

OUT_PATH = PROCESSED_DIR / "habitat_1km.parquet"
CELL_M = 1000
BLOCK = CELL_M // RES_M
WORLDCOVER = {40: "cultures", 30: "prairies", 50: "bati", 10: "arbres", 20: "arbustes"}

TO_L93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
TO_WGS = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)


def cell_id(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Identifiant « x_y » (coin sud-ouest en km Lambert-93) de la maille de 1 km."""
    return np.char.add(np.char.add((np.floor(x / CELL_M)).astype(int).astype(str), "_"),
                       (np.floor(y / CELL_M)).astype(int).astype(str))


def cells_for_points(lats, lngs) -> np.ndarray:
    x, y = TO_L93.transform(np.asarray(lngs, float), np.asarray(lats, float))
    return cell_id(np.asarray(x), np.asarray(y))


def blocks(a: np.ndarray) -> np.ndarray:
    """(h, w) -> (h/BLOCK, w/BLOCK, BLOCK*BLOCK)."""
    h, w = a.shape
    return a.reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK).swapaxes(1, 2).reshape(h // BLOCK, w // BLOCK, -1)


def class_fractions(a: np.ndarray, codes) -> dict[int, np.ndarray]:
    b = blocks(a)
    return {c: (b == c).mean(axis=2) for c in codes}


def warp_to_grid(path, transform, w, h, resampling) -> np.ndarray:
    out = np.zeros((h, w), dtype=np.float32)
    with rasterio.open(path) as src:
        reproject(rasterio.band(src, 1), out, dst_transform=transform, dst_crs="EPSG:2154",
                  resampling=resampling, dst_nodata=np.nan if resampling != Resampling.nearest else 0)
    return out


def build() -> pd.DataFrame:
    transform, w, h, (x0, y0, x1, y1) = grid_l93()
    with rasterio.open(FOREST_PATH) as r:
        forest = r.read(1)
    with rasterio.open(SOIL_PATH) as r:
        soil = r.read(1)
    wc = warp_to_grid(LANDCOVER_PATH, transform, w, h, Resampling.nearest).astype(np.uint8)
    dem = warp_to_grid(DEM_PATH, transform, w, h, Resampling.bilinear)

    nh, nw = h // BLOCK, w // BLOCK
    xs = x0 + CELL_M * (np.arange(nw) + 0.5)
    ys = y1 - CELL_M * (np.arange(nh) + 0.5)
    gx, gy = np.meshgrid(xs, ys)
    df = pd.DataFrame({"x": gx.ravel(), "y": gy.ravel()})
    for c, f in class_fractions(forest, FOREST_CLASSES).items():
        df[f"foret_{FOREST_CLASSES[c]}"] = f.ravel()
    df["foret_total"] = df[[f"foret_{n}" for n in FOREST_CLASSES.values() if n != "lande"]].sum(axis=1)
    sol = class_fractions(soil, [0, *SOIL_CLASSES])
    known = 1 - sol[0].ravel()
    for c, n in SOIL_CLASSES.items():
        # Part parmi la surface cartographiée (la mer et les trous de la carte sont exclus).
        df[f"sol_{n}"] = np.where(known > 0, sol[c].ravel() / np.where(known > 0, known, 1), np.nan)
    for c, f in class_fractions(wc, WORLDCOVER).items():
        df[f"wc_{WORLDCOVER[c]}"] = f.ravel()
    db = blocks(dem)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # mailles en mer : pas d'altitude
        df["altitude_m"] = np.nan_to_num(np.nanmean(db, axis=2).ravel())
        df["relief_m"] = np.nan_to_num(np.nanstd(db, axis=2).ravel())
    wb = blocks(wc)
    df["mer"] = ((wb == 80) | (wb == 0)).mean(axis=2).ravel()  # 80 = eau permanente, 0 = hors terres (mer)

    lng, lat = TO_WGS.transform(df["x"].to_numpy(), df["y"].to_numpy())
    df["lat"], df["lng"] = lat, lng
    z = load_zone()
    df["dist_km"] = haversine_km(z["centre"]["lat"], z["centre"]["lng"], df["lat"], df["lng"])
    df = df[(df["dist_km"] <= z["rayon_km"]) & (df["mer"] < 0.5)].reset_index(drop=True)
    df.insert(0, "maille", cell_id(df["x"].to_numpy() - CELL_M / 2 + 1, df["y"].to_numpy() - CELL_M / 2 + 1))
    df["cellule_meteo"] = cell_for_points(df["lat"], df["lng"])
    return df


def main() -> None:
    df = build()
    df.to_parquet(OUT_PATH, index=False)
    print(f"Écrit : {OUT_PATH} ({len(df)} mailles de 1 km)")
    print(df.describe().T[["mean", "min", "max"]].round(3).to_string())


if __name__ == "__main__":
    main()
