"""Carte interactive (folium / Leaflet) des observations."""

from __future__ import annotations

import html

import folium
import pandas as pd
from folium.plugins import HeatMap

from mushroam.config import load_zone
from mushroam.viz.theme import COLORS

HEAT_GRADIENT = {0.2: "#cde2fb", 0.45: "#86b6ef", 0.7: "#3987e5", 1.0: "#104281"}


def popup(row) -> str:
    prec = "inconnue" if pd.isna(row.precision_m) else f"{row.precision_m:,.0f} m".replace(",", " ")
    alt = "" if pd.isna(row.altitude_m) else f"{row.altitude_m:.0f} m"
    src = "iNaturalist" if row.source == "inat" else html.escape(str(row.dataset))
    link = ""
    if row.source == "inat":
        link = f'<br><a href="https://www.inaturalist.org/observations/{row.source_id[5:]}" target="_blank">voir</a>'
    elif row.source == "gbif":
        link = f'<br><a href="https://www.gbif.org/occurrence/{row.source_id[5:]}" target="_blank">voir</a>'
    meteo = ""
    if pd.notna(getattr(row, "pluie_30j", None)):
        meteo = (f"<br>Météo du jour (maille 8 km) : pluie 30 j {row.pluie_30j:.0f} mm · "
                 f"SWI {row.swi:.2f} · {row.jours_depuis_20mm:.0f} j depuis une pluie ≥ 20 mm").replace(".", ",")
    return (f"<b><i>{html.escape(str(row.taxon_name))}</i></b><br>{row.observed_on:%d/%m/%Y}"
            f"<br>altitude {alt} · précision {prec}{meteo}<br><small>{src} · {row.quality}</small>{link}")


def build_map(df: pd.DataFrame, taxa: dict, rules: dict) -> folium.Map:
    zone = load_zone()
    c = zone["centre"]
    m = folium.Map(location=[c["lat"], c["lng"]], zoom_start=9, tiles=None, control_scale=True)
    folium.TileLayer("OpenTopoMap", name="Relief (OpenTopoMap)").add_to(m)
    # Pas de tuiles OpenStreetMap : leurs serveurs refusent les pages ouvertes en file://.
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Imagerie © Esri, Maxar, Earthstar Geographics", name="Satellite (Esri)", show=False,
    ).add_to(m)
    folium.Circle([c["lat"], c["lng"]], radius=zone["rayon_km"] * 1000, color="#52514e",
                  weight=1.5, fill=False, dash_array="6 6", interactive=False).add_to(m)

    excl = df[~df["doublon"] & ~df["retenue"] & ~df["lichen"]]
    df = df[df["retenue"]]
    fond = df[~df["lichen"]]
    heat = folium.FeatureGroup(name="Densité de toutes les observations (effort)", show=False)
    HeatMap(fond[["lat", "lng"]].values.tolist(), radius=9, blur=12, min_opacity=0.25,
            gradient=HEAT_GRADIENT).add_to(heat)
    heat.add_to(m)

    for key, cible in taxa["cibles"].items():
        color = COLORS.get(key, "#2a78d6")
        layer = folium.FeatureGroup(name=f"{cible['label']}", show=True)
        for row in fond[fond[f"cible_{key}"]].itertuples():
            precise = row.ok_habitat
            folium.CircleMarker(
                [row.lat, row.lng], radius=5, color=color, weight=2,
                fill=precise, fill_color=color, fill_opacity=0.85,
                popup=folium.Popup(popup(row), max_width=280),
                tooltip=f"{row.taxon_name} · {row.observed_on:%d/%m/%Y}",
            ).add_to(layer)
        layer.add_to(m)

    # Contrôle : cibles exclues pour localisation douteuse (zone urbaine, point répété).
    cible_cols = [f"cible_{k}" for k in taxa["cibles"]]
    excl = excl[excl[cible_cols].any(axis=1)]
    layer = folium.FeatureGroup(name="Cibles exclues (urbain, point répété)", show=False)
    for row in excl.itertuples():
        why = "point répété" if row.point_repete else f"urbain ({100 * row.bati:.0f} % de bâti)"
        folium.CircleMarker(
            [row.lat, row.lng], radius=4, color="#52514e", weight=1.5, fill=True,
            fill_color="#a3a29c", fill_opacity=0.8,
            popup=folium.Popup(popup(row) + f"<br><b>Exclue</b> : {why}", max_width=280),
            tooltip=f"{row.taxon_name} · exclue ({why})",
        ).add_to(layer)
    layer.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m
