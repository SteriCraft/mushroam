"""Onglet Météo du site : carte des conditions par maille SAFRAN et synthèse.

Les « normales » sont les médianes 1999 à l'année précédente, pour la même
maille et le même jour de l'année (lissées sur ±7 jours).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from pyproj import Transformer

from mushroam.config import load_zone
from mushroam.viz.explore import Report, fmt, html_table
from mushroam.viz.theme import COLORS, plotly_layout

NORMAL_VARS = ["pluie_30j", "swi", "tmin_7j", "tmax_7j"]
ALT_BANDS = [0, 400, 800, 1200, 1700]
MAP_DAYS = 90

# Variables proposées sur la carte : (libellé, unité, type d'échelle, décimales)
MAP_VARS = {
    "pluie_7j": ("Pluie sur 7 jours", "mm", "seq", 0),
    "pluie_30j": ("Pluie sur 30 jours", "mm", "seq", 0),
    "pluie_30j_ecart": ("Pluie sur 30 jours, écart à la normale", "mm", "div", 0),
    "swi": ("Humidité des sols (SWI)", "", "seq", 2),
    "swi_ecart": ("Humidité des sols, écart à la normale", "", "div", 2),
    "swi_tend_14j": ("Humidité des sols, variation sur 14 jours", "", "div", 2),
    "jours_depuis_20mm": ("Jours depuis une pluie ≥ 20 mm", "j", "seq", 0),
    "tmin_7j": ("Température minimale, moyenne 7 jours", "°C", "seq", 1),
    "tmax_7j": ("Température maximale, moyenne 7 jours", "°C", "seq", 1),
    "gel_7j": ("Jours de gel sur 7 jours", "j", "seq", 0),
}

FROM_L2E = Transformer.from_crs("EPSG:27572", "EPSG:4326", always_xy=True)


def normals(feats: pd.DataFrame, until_year: int) -> pd.DataFrame:
    """Médianes par maille et jour de l'année (1..366), lissées sur ±7 jours."""
    hist = feats[feats["date"].dt.year < until_year]
    doy = hist["date"].dt.day_of_year
    out = []
    for v in NORMAL_VARS:
        med = hist.assign(doy=doy).pivot_table(index="doy", columns="cellule", values=v, aggfunc="median")
        med = med.reindex(range(1, 367)).interpolate(limit_direction="both")
        wrapped = pd.concat([med.iloc[-7:], med, med.iloc[:7]])
        smooth = wrapped.rolling(15, center=True).mean().iloc[7:-7]
        out.append(smooth.stack().rename(v))
    n = pd.concat(out, axis=1)
    n.index.names = ["doy", "cellule"]
    return n.reset_index()


def with_anomalies(feats: pd.DataFrame, norms: pd.DataFrame) -> pd.DataFrame:
    f = feats.assign(doy=feats["date"].dt.day_of_year)
    f = f.merge(norms.rename(columns={v: f"{v}_normale" for v in NORMAL_VARS}), on=["doy", "cellule"], how="left")
    f["pluie_30j_ecart"] = f["pluie_30j"] - f["pluie_30j_normale"]
    f["swi_ecart"] = f["swi"] - f["swi_normale"]
    return f


def cell_polygons(grid: pd.DataFrame) -> dict:
    """Carrés de 8 km (Lambert II étendu) convertis en GeoJSON WGS84."""
    feats = []
    for row in grid.itertuples():
        x0, y0 = (row.lambx - 40) * 100, (row.lamby - 40) * 100
        x1, y1 = (row.lambx + 40) * 100, (row.lamby + 40) * 100
        xs, ys = FROM_L2E.transform([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0])
        feats.append({"type": "Feature",
                      "properties": {"cellule": row.cellule, "altitude": round(float(row.altitude_m))},
                      "geometry": {"type": "Polygon",
                                   "coordinates": [[[round(a, 5), round(b, 5)] for a, b in zip(xs, ys)]]}})
    return {"type": "FeatureCollection", "features": feats}


def meteo_map_html(f: pd.DataFrame, grid: pd.DataFrame) -> str:
    last = f["date"].max()
    recent = f[f["date"] > last - pd.Timedelta(days=MAP_DAYS)]
    dates = sorted(recent["date"].unique())
    cells = grid["cellule"].tolist()
    data = {}
    for v, (_, _, _, dec) in MAP_VARS.items():
        wide = recent.pivot(index="date", columns="cellule", values=v).reindex(index=dates, columns=cells)
        data[v] = [[None if pd.isna(x) else round(float(x), dec) for x in row] for row in wide.to_numpy()]
    payload = {
        "dates": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates],
        "cells": cells,
        "vars": {k: {"label": a, "unit": b, "scale": c, "dec": d} for k, (a, b, c, d) in MAP_VARS.items()},
        "data": data,
        "geo": cell_polygons(grid),
        "centre": [load_zone()["centre"]["lat"], load_zone()["centre"]["lng"]],
        "rayon_m": load_zone()["rayon_km"] * 1000,
    }
    return MAP_TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":")))


def dec2(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def meteo_section(f: pd.DataFrame, grid: pd.DataFrame) -> str:
    r = Report("met")
    last = f["date"].max()
    today = f[f["date"] == last].merge(grid[["cellule", "altitude_m"]], on="cellule")
    zone_mean = today[["pluie_7j", "pluie_30j", "pluie_30j_normale", "swi", "swi_normale"]].mean()
    r.add(f'<p class="note">Données SIM2 Météo-France (maille de 8 km), jusqu\'au {last:%d/%m/%Y}. '
          "Normales : médiane 1999 à l'année précédente, même maille, même période de l'année.</p>")
    r.add('<div class="kpis">'
          f'<div class="kpi"><b>{fmt(zone_mean["pluie_7j"])} mm</b><span>pluie sur 7 jours (moyenne de la zone)</span></div>'
          f'<div class="kpi"><b>{fmt(zone_mean["pluie_30j"])} mm</b><span>pluie sur 30 jours · normale {fmt(zone_mean["pluie_30j_normale"])} mm</span></div>'
          f'<div class="kpi"><b>{dec2(zone_mean["swi"])}</b><span>humidité des sols (SWI) · normale {dec2(zone_mean["swi_normale"])}</span></div>'
          "</div>")

    # Pluie quotidienne moyenne sur la zone, 120 derniers jours.
    z = f[f["date"] > last - pd.Timedelta(days=120)].groupby("date")[["pluie", "swi", "swi_normale"]].mean()
    fig = go.Figure([go.Bar(x=z.index, y=z["pluie"], name="pluie",
                            marker=dict(color=COLORS["inat"], line=dict(width=0)),
                            hovertemplate="%{x|%d/%m/%Y} : %{y:.1f} mm<extra></extra>")])
    fig.update_layout(plotly_layout("Pluie quotidienne, moyenne de la zone (120 derniers jours)",
                                    ytitle="mm", height=300), showlegend=False, bargap=0.1)
    fig.update_xaxes(tickformat="%d/%m")
    r.fig(fig)

    # Humidité des sols : année en cours contre la normale.
    fig = go.Figure([
        go.Scatter(x=z.index, y=z["swi_normale"], name="normale", mode="lines",
                   line=dict(color="#a3a29c", width=2, dash="dot"),
                   hovertemplate="normale %{y:.2f}<extra></extra>"),
        go.Scatter(x=z.index, y=z["swi"], name="observé", mode="lines",
                   line=dict(color=COLORS["inat"], width=2),
                   hovertemplate="observé %{y:.2f}<extra></extra>"),
    ])
    fig.update_layout(plotly_layout("Humidité des sols (SWI), moyenne de la zone", ytitle="SWI", height=300))
    fig.update_xaxes(tickformat="%d/%m")
    fig.update_traces(xhoverformat="%d/%m/%Y")
    r.fig(fig, "SWI : 0 = sol au point de flétrissement, 1 = sol à la capacité au champ (au-delà : saturé).")

    # Conditions actuelles par tranche d'altitude.
    labels = [f"{a}–{b}" for a, b in zip(ALT_BANDS[:-1], ALT_BANDS[1:])]
    today["bande"] = pd.cut(today["altitude_m"].clip(lower=0), ALT_BANDS, labels=labels, right=False)
    t = today.groupby("bande", observed=False).agg(
        mailles=("cellule", "size"),
        pluie_7j=("pluie_7j", "mean"), pluie_30j=("pluie_30j", "mean"),
        pluie_30j_normale=("pluie_30j_normale", "mean"),
        swi=("swi", "mean"), swi_normale=("swi_normale", "mean"),
        tmin_7j=("tmin_7j", "mean"), tmax_7j=("tmax_7j", "mean"),
        jours_depuis_20mm=("jours_depuis_20mm", "median"),
    ).round(2)
    t.columns = ["mailles", "pluie 7 j (mm)", "pluie 30 j (mm)", "normale 30 j (mm)", "SWI", "SWI normal",
                 "Tmin 7 j (°C)", "Tmax 7 j (°C)", "jours depuis ≥ 20 mm"]
    t.index.name = "altitude (m)"
    r.add(f"<h3>Conditions au {last:%d/%m/%Y} par tranche d'altitude</h3>" + html_table(t))
    return "\n".join(r.parts)


MAP_TEMPLATE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Carte météo</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root { --surface:#fcfcfb; --surface-2:#f3f2ef; --border:#e2e1dc; --text:#0b0b0b; --text-2:#52514e; --muted:#7a7973; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --surface:#1a1a19; --surface-2:#232321; --border:#383835; --text:#f0efec; --text-2:#c3c2b7; --muted:#94938b; } }
:root[data-theme="dark"] { --surface:#1a1a19; --surface-2:#232321; --border:#383835; --text:#f0efec; --text-2:#c3c2b7; --muted:#94938b; }
html, body { margin:0; height:100%; background:var(--surface); color:var(--text);
  font:14px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
#wrap { display:flex; flex-direction:column; height:100%; }
#ctrl { display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; padding:8px 12px;
  border-bottom:1px solid var(--border); background:var(--surface-2); }
#ctrl label { color:var(--text-2); }
select, input[type=range] { font:inherit; }
select { padding:3px 6px; background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:6px; }
#date { font-variant-numeric:tabular-nums; min-width:9ch; font-weight:600; }
#slider { width:min(320px, 60vw); }
#map { flex:1; }
.legend { background:var(--surface); color:var(--text); padding:8px 10px; border-radius:8px;
  border:1px solid var(--border); font-size:12px; min-width:180px; }
.legend .bar { height:10px; border-radius:3px; margin:6px 0 2px; }
.legend .ticks { display:flex; justify-content:space-between; color:var(--text-2); font-variant-numeric:tabular-nums; }
.leaflet-tooltip { font-variant-numeric:tabular-nums; }

</style></head>
<body><div id="wrap">
<div id="ctrl">
  <label>Variable <select id="var"></select></label>
  <label>Date <input id="slider" type="range" min="0" step="1"></label>
  <span id="date"></span>
</div>
<div id="map"></div></div>
<script>
const D = __DATA__;
// Rampe séquentielle bleue et rampe divergente rouge (sec) <-> bleu (humide), milieu gris neutre.
const SEQ = ["#cde2fb","#9ec5f4","#6da7ec","#3987e5","#256abf","#184f95","#0d366b"];
const DIV = ["#b42c2c","#d65a52","#ec9a8c","#f0efec","#9ec5f4","#3987e5","#184f95"];
const map = L.map("map", {zoomControl:true}).setView(D.centre, 8);
// Fond neutre Esri (gris clair ou foncé selon le thème), sans clé et utilisable depuis un fichier local.
// Les serveurs OpenStreetMap refusent les pages ouvertes en file:// (pas d'en-tête Referer).
const dark = matchMedia("(prefers-color-scheme: dark)").matches && document.documentElement.dataset.theme !== "light";
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_" + (dark ? "Dark" : "Light")
  + "_Gray_Base/MapServer/tile/{z}/{y}/{x}", {maxZoom:16,
  attribution:'Fond © Esri, HERE, Garmin, © OpenStreetMap · météo SIM2 Météo-France'}).addTo(map);
// Noms de lieux au-dessus des mailles, sans capter la souris.
map.createPane("labels"); map.getPane("labels").style.zIndex = 650; map.getPane("labels").style.pointerEvents = "none";
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_" + (dark ? "Dark" : "Light")
  + "_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {maxZoom:16, pane:"labels"}).addTo(map);
L.circle(D.centre, {radius:D.rayon_m, color:"#52514e", weight:1.5, fill:false, dashArray:"6 6", interactive:false}).addTo(map);
const index = Object.fromEntries(D.cells.map((c,i)=>[c,i]));
let v = "swi", t = D.dates.length - 1, lo = 0, hi = 1;
const sel = document.getElementById("var");
for (const [k, m] of Object.entries(D.vars)) { const o = document.createElement("option"); o.value=k; o.textContent=m.label; sel.appendChild(o); }
sel.value = v;
const slider = document.getElementById("slider");
slider.max = D.dates.length - 1; slider.value = t;
function fmtDate(s){ const [y,m,d]=s.split("-"); return d+"/"+m+"/"+y; }
function fmtVal(x){ if (x===null||x===undefined) return "–"; const m=D.vars[v];
  return x.toFixed(m.dec).replace(".", ",") + (m.unit ? " " + m.unit : ""); }
function range(){
  // Bornes fixes sur toute la période affichée, pour comparer les dates entre elles.
  const all = D.data[v].flat().filter(x=>x!==null).sort((a,b)=>a-b);
  const q = p => all[Math.min(all.length-1, Math.floor(p*(all.length-1)))];
  if (D.vars[v].scale === "div") { const m = Math.max(Math.abs(q(0.02)), Math.abs(q(0.98))) || 1; lo=-m; hi=m; }
  else { lo = q(0.02); hi = q(0.98); if (hi===lo) hi = lo + 1; }
}
function color(x){
  if (x===null||x===undefined) return "transparent";
  const r = D.vars[v].scale === "div" ? DIV : SEQ;
  const u = Math.max(0, Math.min(0.9999, (x-lo)/(hi-lo)));
  return r[Math.floor(u * r.length)];
}
const layer = L.geoJSON(D.geo, {style: ()=>({weight:0.4, color:"#ffffff", fillOpacity:0.72})}).addTo(map);
layer.eachLayer(l => {
  l.bindTooltip(()=>{ const p=l.feature.properties; const x=D.data[v][t][index[p.cellule]];
    return "<b>"+fmtVal(x)+"</b><br>"+D.vars[v].label+"<br>maille "+p.cellule+" · "+p.altitude+" m"; }, {sticky:true});
});
const legend = L.control({position:"bottomright"});
legend.onAdd = () => { const d = L.DomUtil.create("div","legend"); d.id="legend"; return d; };
legend.addTo(map);
map.fitBounds(layer.getBounds(), {padding:[8, 8]});
function draw(){
  document.getElementById("date").textContent = fmtDate(D.dates[t]);
  layer.eachLayer(l => l.setStyle({fillColor: color(D.data[v][t][index[l.feature.properties.cellule]])}));
  const r = D.vars[v].scale === "div" ? DIV : SEQ, m = D.vars[v];
  const f = x => x.toFixed(m.dec).replace(".", ",");
  document.getElementById("legend").innerHTML = "<div>"+m.label+(m.unit?" ("+m.unit+")":"")+"</div>"
    + '<div class="bar" style="background:linear-gradient(90deg,'+r.join(",")+')"></div>'
    + '<div class="ticks"><span>'+f(lo)+'</span><span>'+(m.scale==="div"?"0":"")+'</span><span>'+f(hi)+'</span></div>';
}
sel.onchange = () => { v = sel.value; range(); draw(); };
slider.oninput = () => { t = +slider.value; draw(); };
range(); draw();
</script></body></html>
"""
