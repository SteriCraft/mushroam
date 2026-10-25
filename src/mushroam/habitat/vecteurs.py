"""Couches vectorielles IGN / INRAE (WFS Géoplateforme) converties en grilles.

- BD Forêt v2 (IGN) : formations végétales et essences dominantes ;
- carte des sols (INRAE, Référentiels régionaux pédologiques au 1/250 000) :
  type de sol dominant de chaque unité.

Les polygones sont lus page par page (5 000 au plus par requête) et
rasterisés aussitôt sur une grille Lambert-93 de 50 m. On ne garde en cache que
le résultat de chaque page (pixels touchés et classe), pas les polygones
bruts : environ 2 Go de GeoJSON pour la BD Forêt.

Sorties : data/processed/foret_50m.tif, data/processed/sols_50m.tif
(une classe par pixel, 0 = sans donnée ; codes dans FOREST_CLASSES et SOIL_CLASSES),
et data/processed/communes.geojson (limites communales simplifiées, ADMIN EXPRESS
de l'IGN, pour nommer les mailles).

Usage : python -m mushroam.habitat.vecteurs [--refresh]
"""

from __future__ import annotations

import json
import sys
import time

import numpy as np
import rasterio
import requests
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_origin

from mushroam.config import PROCESSED_DIR, RAW_DIR, load_zone
from mushroam.habitat.dem import zone_bbox
from mushroam.http import USER_AGENT

WFS = "https://data.geopf.fr/wfs/ows"
PAGE = 5000
RES_M = 50
CACHE = RAW_DIR / "wfs"

FOREST_LAYER = "LANDCOVER.FORESTINVENTORY.V2:formation_vegetale"
SOIL_LAYER = "INRA.CARTE.SOLS:geoportail_vf"
COMMUNE_LAYER = "ADMINEXPRESS-COG-CARTO.LATEST:commune"
FOREST_PATH = PROCESSED_DIR / "foret_50m.tif"
COMMUNES_PATH = PROCESSED_DIR / "communes.geojson"
SOIL_PATH = PROCESSED_DIR / "sols_50m.tif"

# Classes de végétation (0 = hors BD Forêt : cultures, prairies, bâti, eau…)
FOREST_CLASSES = {
    1: "chenes_verts",        # chênes sempervirents (chêne vert, chêne-liège)
    2: "feuillus",            # feuillus mélangés, chênes décidus, robinier, peuplier
    3: "chataignier_hetre",   # châtaignier, hêtre (sols acides, étage montagnard)
    4: "pins",                # toutes les essences de pins
    5: "autres_coniferes",    # sapin, épicéa, douglas, mélèze, conifères non précisés
    6: "mixte",               # feuillus et conifères mêlés
    7: "lande",               # landes, formations herbacées, coupes rases
}

# Groupes de sols (type dominant de l'unité cartographique)
SOIL_CLASSES = {1: "calcaire", 2: "acide", 3: "autre"}
CALCAIRES = ("CALCOSOL", "CALCISOL", "RENDOSOL", "RENDISOL", "DOLOMITOSOL", "CALCARISOL")
ACIDES = ("ALOCRISOL", "PODZOSOL", "RANKOSOL", "BRUNISOL", "VERACRISOL", "UMBRISOL", "ORGANOSOL")


def forest_class(props: dict) -> int:
    g, e = props.get("tfv_g11") or "", props.get("essence") or ""
    if e == "Chênes sempervirents":
        return 1
    if e in ("Châtaignier", "Hêtre"):
        return 3
    if e.startswith("Pin"):
        return 4
    if "conifères" in g:
        return 5
    if "mixte" in g:
        return 6
    if "feuillus" in g or g == "Peupleraie":
        return 2
    if g in ("Lande", "Formation herbacée") or "sans couvert" in g:
        return 7
    return 0


def soil_class(props: dict) -> int:
    name = (props.get("ger_nom") or "").split("(")[0].strip().upper()
    if name.startswith(CALCAIRES):
        return 1
    if name.startswith(ACIDES):
        return 2
    return 3 if name else 0


def grid_l93() -> tuple[rasterio.Affine, int, int, tuple[float, float, float, float]]:
    """Grille Lambert-93 de RES_M mètres couvrant l'emprise de la zone (bornes au km)."""
    lng0, lat0, lng1, lat1 = zone_bbox(load_zone())
    tr = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    xs, ys = tr.transform([lng0, lng0, lng1, lng1], [lat0, lat1, lat0, lat1])
    x0, y0 = np.floor(min(xs) / 1000) * 1000, np.floor(min(ys) / 1000) * 1000
    x1, y1 = np.ceil(max(xs) / 1000) * 1000, np.ceil(max(ys) / 1000) * 1000
    w, h = int((x1 - x0) / RES_M), int((y1 - y0) / RES_M)
    return from_origin(x0, y1, RES_M, RES_M), w, h, (x0, y0, x1, y1)


def fetch_page(layer: str, props: str, bbox, start: int, sort: str | None) -> dict:
    params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": layer,
              "OUTPUTFORMAT": "application/json", "COUNT": PAGE, "STARTINDEX": start,
              "BBOX": ",".join(str(int(v)) for v in bbox) + ",EPSG:2154", "PROPERTYNAME": props}
    if sort:
        params["SORTBY"] = sort
    for attempt in range(5):
        try:
            r = requests.get(WFS, params=params, headers={"User-Agent": USER_AGENT}, timeout=600)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == 4:
                raise
            time.sleep(10 * (attempt + 1))


def build_layer(layer: str, props: str, sort: str | None, classify, out_path, name: str,
                refresh: bool = False) -> None:
    transform, w, h, bbox = grid_l93()
    cache = CACHE / name
    cache.mkdir(parents=True, exist_ok=True)
    out = np.zeros((h, w), dtype=np.uint8)
    start, total = 0, None
    while total is None or start < total:
        page = cache / f"{start:07d}.npz"
        if page.exists() and not refresh:
            z = np.load(page)
            total = int(z["total"])
        else:
            d = fetch_page(layer, props, bbox, start, sort)
            total = int(d["numberMatched"])
            shapes = [(f["geometry"], classify(f["properties"])) for f in d["features"] if f["geometry"]]
            shapes = [(g, c) for g, c in shapes if c > 0]
            tmp = rasterize(shapes, out_shape=(h, w), transform=transform, fill=0, dtype="uint8") \
                if shapes else np.zeros((h, w), np.uint8)
            idx = np.flatnonzero(tmp)
            z = {"idx": idx.astype(np.int64), "val": tmp.ravel()[idx], "total": total}
            np.savez_compressed(page, **z)
            print(f"  {name} : {min(start + PAGE, total)} / {total} polygones", flush=True)
        out.ravel()[z["idx"]] = z["val"]
        start += PAGE
    with rasterio.open(out_path, "w", driver="GTiff", width=w, height=h, count=1, dtype="uint8",
                       crs="EPSG:2154", transform=transform, compress="deflate", nodata=0) as dst:
        dst.write(out, 1)
    counts = np.bincount(out.ravel(), minlength=8) / out.size
    print(f"Écrit : {out_path} ; part des pixels par classe : "
          + ", ".join(f"{c}={p:.1%}" for c, p in enumerate(counts) if p > 0))


def build_communes(refresh: bool = False) -> None:
    """Communes de l'emprise (géométries simplifiées « CARTO », quelques Mo)."""
    if COMMUNES_PATH.exists() and not refresh:
        return
    _, _, _, bbox = grid_l93()
    feats, start, total = [], 0, None
    while total is None or start < total:
        d = fetch_page(COMMUNE_LAYER, "geometrie,nom_officiel,code_insee,code_insee_du_departement", bbox, start,
                       "code_insee")
        total = int(d["numberMatched"])
        feats += d["features"]
        start += PAGE
    # Le service renvoie cette couche en WGS84 (longitude, latitude).
    out = {"type": "FeatureCollection",
           "features": [{"type": "Feature", "geometry": f["geometry"],
                         "properties": {"nom": f["properties"]["nom_officiel"],
                                        "dep": f["properties"]["code_insee_du_departement"]}} for f in feats]}
    COMMUNES_PATH.write_text(json.dumps(out), encoding="utf-8")
    print(f"Écrit : {COMMUNES_PATH} ({len(feats)} communes)")


def main() -> None:
    refresh = "--refresh" in sys.argv
    build_layer(FOREST_LAYER, "geom,code_tfv,tfv_g11,essence", "id", forest_class, FOREST_PATH, "bdforet_v2", refresh)
    build_layer(SOIL_LAYER, "geom,ger_nom,id_ucs", None, soil_class, SOIL_PATH, "sols_inrae", refresh)
    build_communes(refresh)


if __name__ == "__main__":
    main()
