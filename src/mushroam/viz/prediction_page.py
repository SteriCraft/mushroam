"""Onglet Prédiction : carte à 1 km (habitat × saison × météo) et validations."""

from __future__ import annotations

import base64
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from pyproj import Transformer

from mushroam.config import load_zone
from mushroam.habitat.grille import cells_for_points
from mushroam.model.sorties import VALID_PATH as LIST_VALID_PATH
from mushroam.viz.explore import Report, html_table
from mushroam.viz.meteo_page import MAP_HEAD
from mushroam.viz.theme import COLORS, plotly_layout

PIXEL_M = 400  # taille d'un pixel de l'image, en mètres de la projection web (≈ 290 m au sol)
TO_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
FROM_3857 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

LAYERS = {
    "potentiel": ("Potentiel (habitat × saison × météo)", "seq"),
    "probabilite": ("Probabilité pour une sortie type (météo ordinaire)", "prob"),
    "habitat": ("Habitat (× la moyenne des lieux prospectés)", "ratio"),
    "saison": ("Saison normale, 14 prochains jours (1 = meilleure période)", "seq"),
    "classe": ("Météo actuelle", "cat"),
}
CLASS_CODES = {"defavorable": 0, "normale": 1, "favorable": 2}
FOREST_LABELS = {"chenes_verts": "chênes verts", "feuillus": "feuillus", "chataignier_hetre": "châtaignier, hêtre",
                 "pins": "pins", "autres_coniferes": "autres conifères", "mixte": "forêt mixte", "lande": "lande"}


def index_raster(cells: pd.Series, zone_bounds) -> tuple[np.ndarray, list]:
    """Image en projection web : chaque pixel porte l'indice de sa maille de 1 km (-1 = aucune)."""
    lng0, lat0, lng1, lat1 = zone_bounds
    (x0, x1), (y0, y1) = TO_3857.transform([lng0, lng1], [lat0, lat1])
    w, h = int(np.ceil((x1 - x0) / PIXEL_M)), int(np.ceil((y1 - y0) / PIXEL_M))
    px = x0 + PIXEL_M * (np.arange(w) + 0.5)
    py = y1 - PIXEL_M * (np.arange(h) + 0.5)
    gx, gy = np.meshgrid(px, py)
    lng, lat = FROM_3857.transform(gx.ravel(), gy.ravel())
    idx = pd.Index(cells).get_indexer(cells_for_points(lat, lng)).astype(np.int16).reshape(h, w)
    blng, blat = FROM_3857.transform([x0, x0 + w * PIXEL_M], [y1 - h * PIXEL_M, y1])
    return idx, [[blat[0], blng[0]], [blat[1], blng[1]]]


def dominant_forest(row) -> str:
    vals = {k: row[f"foret_{k}"] for k in FOREST_LABELS}
    k, v = max(vals.items(), key=lambda kv: kv[1])
    return f"{FOREST_LABELS[k]} {v:.0%}" if v >= 0.1 else "peu boisé"


def prediction_map_html(pred: pd.DataFrame, grid: pd.DataFrame, cibles: dict[str, str]) -> str:
    from mushroam.habitat.dem import zone_bbox
    cells = grid["maille"]
    idx, bounds = index_raster(cells, zone_bbox(load_zone(), margin_km=2))
    g = grid.set_index("maille")
    info = {
        "alt": g["altitude_m"].round().astype(int).tolist(),
        "commune": [f"{c} ({d})" if c else "" for c, d in zip(g["commune"], g["departement"])],
        "foret": [dominant_forest(r) for _, r in g.iterrows()],
        "sol": [("calcaire" if r.sol_calcaire >= 0.5 else "acide" if r.sol_acide >= 0.5 else "mixte ou autre")
                if not np.isnan(r.sol_calcaire) else "sans donnée" for r in g.itertuples()],
    }
    data = {}
    for key in cibles:
        p = pred[pred["cible"] == key].set_index("maille").reindex(cells)
        data[key] = {
            "potentiel": p["potentiel"].round(3).fillna(-1).tolist(),
            "habitat": p["habitat"].round(3).fillna(-1).tolist(),
            "saison": p["saison"].round(3).fillna(-1).tolist(),
            "probabilite": p["probabilite"].round(3).fillna(-1).tolist(),
        }
    p0 = pred[pred["cible"] == next(iter(cibles))].set_index("maille").reindex(cells)
    z = load_zone()
    payload = {
        "date": pd.Timestamp(pred["date"].iloc[0]).strftime("%d/%m/%Y"), "taille": round(float(pd.read_parquet(LIST_VALID_PATH)["taille_reference"].iloc[0])),
        "cibles": cibles, "layers": {k: {"label": a, "scale": b} for k, (a, b) in LAYERS.items()},
        "data": data, "classe": p0["classe"].map(CLASS_CODES).fillna(1).astype(int).tolist(),
        "facteurs": p0.groupby("classe")["facteur_meteo"].first().to_dict(),
        "pluie30": p0["pluie_30j"].round().fillna(-1).tolist(),
        "info": info, "w": int(idx.shape[1]), "h": int(idx.shape[0]), "bounds": bounds,
        "idx": base64.b64encode(idx.astype("<i2").tobytes()).decode(),
        "centre": [z["centre"]["lat"], z["centre"]["lng"]], "rayon_m": z["rayon_km"] * 1000,
    }
    return PRED_TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":")))


def top_sectors(pred: pd.DataFrame, grid: pd.DataFrame, key: str, n: int = 10) -> pd.DataFrame:
    p = pred[pred["cible"] == key].merge(grid, on=["maille"], suffixes=("", "_g"))
    # Meilleure maille de chaque commune : des secteurs distincts plutôt que des mailles voisines
    # (beaucoup de mailles sont ex æquo au plafond de favorabilité).
    p = (p[p["classe"] != "defavorable"].sort_values(["potentiel", "probabilite"], ascending=False)
         .drop_duplicates("commune").head(n))
    return pd.DataFrame({
        "position": [f"{a:.4f}, {b:.4f}" for a, b in zip(p["lat"], p["lng"])],
        "commune": [f"{c} ({d})" for c, d in zip(p["commune"], p["departement"])],
        "altitude (m)": p["altitude_m"].round().astype(int).to_numpy(),
        "végétation": [dominant_forest(r) for _, r in p.iterrows()],
        "habitat": p["habitat"].round(2).to_numpy(), "saison": p["saison"].round(2).to_numpy(),
        "météo": p["classe"].map({"normale": "normale", "favorable": "favorable"}).to_numpy(),
        "potentiel": p["potentiel"].round(2).to_numpy(),
        "probabilité": (100 * p["probabilite"]).round().astype(int).astype(str).to_numpy() + " %",
    }).set_index("position")


def prediction_section(pred: pd.DataFrame, grid: pd.DataFrame, cibles: dict[str, str],
                       meteo_valid: pd.DataFrame, hab_valid: pd.DataFrame, coefs: pd.DataFrame,
                       analog_valid: pd.DataFrame | None, list_valid: pd.DataFrame) -> str:
    r = Report("pred")
    date = pd.Timestamp(pred["date"].iloc[0])
    p0 = pred[pred["cible"] == next(iter(cibles))]
    share = p0["classe"].value_counts(normalize=True)
    r.add('<div class="kpis">' + "".join(
        f'<div class="kpi"><b>{share.get(c, 0):.0%}</b><span>de la zone en météo {lab}</span></div>'
        for c, lab in [("favorable", "favorable"), ("normale", "normale"), ("defavorable", "défavorable")]) + "</div>")

    r.add(f"<h3>Meilleurs secteurs au {date:%d/%m/%Y} (14 prochains jours)</h3>")
    taille = int(round(list_valid["taille_reference"].iloc[0]))
    r.add('<p class="note">Meilleure maille de 1 km de chaque commune, classées par potentiel, hors météo défavorable. Position : latitude / '
          "longitude du centre de la maille (à coller dans un outil de carte). Probabilité : chance qu'une sortie "
          f"type (liste de {taille} espèces, comme celles des mycologues de la base) note la cible, par météo "
          "ordinaire pour la période.</p>")
    for key, label in cibles.items():
        r.add(f"<h4>{label}</h4>" + html_table(top_sectors(pred, grid, key)))

    # Listes de sortie : probabilité.
    r.add("<h3>Probabilité : validation sur les listes de sortie</h3>")
    r.add('<p class="note">Une liste de sortie = les espèces notées le même jour, au même endroit (à 1 km près), par '
          "le même observateur ou le même jeu de données (sociétés mycologiques, ONF, CBN…), avec au moins 5 espèces. "
          "Une liste sans la cible compte comme une absence. Modèle : habitat (hors bloc), saison et taille de la liste ; "
          "validé par blocs géographiques de 20 km. Calibration : probabilité prédite et fréquence observée, pour "
          "le tiers des listes le moins favorable, le tiers moyen et le tiers le plus favorable. La météo du jour "
          "n'améliore pas ce modèle (la poussée des bolets suit la pluie de plusieurs semaines) : la probabilité "
          "vaut pour une météo ordinaire.</p>")
    lv = list_valid.assign(cible=list_valid["cible"].map(cibles)).set_index("cible")
    pct = lambda x: f"{100 * x:.0f} %"
    tab = pd.DataFrame({
        "listes": lv["listes"], "avec la cible": lv["avec_cible"],
        "AUC saison + taille": lv["auc_saison_taille"].round(3), "AUC + habitat": lv["auc_complet"].round(3),
        **{f"tiers {i} : prédit / observé": lv[f"t{i}_predit"].map(pct) + " / " + lv[f"t{i}_observe"].map(pct)
           for i in (1, 2, 3)}})
    r.add(html_table(tab))

    # Météo : validation des classes.
    r.add("<h3>Classe météo : contrôle année par année</h3>")
    r.add('<p class="note">Activité des champignons dans les 14 jours suivant un jour classé, rapportée à la normale '
          "de la période calculée <b>sans l'année testée</b> (Fungi parmi toutes les observations iNaturalist, "
          "zone entière). Défavorable : moins de 40 mm en 30 jours, ou maximales ≥ 27 °C, ou minimales &lt; 3 °C "
          "(moyennes sur 7 jours). Favorable : au moins 100 mm en 30 jours ou une pluie ≥ 20 mm depuis 14 jours "
          "au plus.</p>")
    t = meteo_valid.pivot(index="classe", columns="annee", values="rapport").reindex(
        ["defavorable", "normale", "favorable"]).round(2)
    t.index = ["défavorable", "normale", "favorable"]
    r.add(html_table(t))

    # Habitat : validation spatiale et effets.
    r.add("<h3>Habitat : validation par blocs géographiques</h3>")
    r.add('<p class="note">La zone est découpée en blocs de 20 km répartis en 5 groupes ; chaque groupe est prédit '
          "par un modèle ajusté sans lui. AUC : probabilité qu'une observation de la cible tirée au hasard ait un "
          "score plus haut qu'une autre observation de champignon (0,5 = hasard, 1 = parfait). Les deux références "
          "n'utilisent que la saison et la source, ou y ajoutent l'altitude.</p>")
    fig = go.Figure()
    for row in hab_valid.itertuples():
        fig.add_trace(go.Bar(x=[f"Q{i}" for i in range(1, 6)], y=[getattr(row, f"q{i}") for i in range(1, 6)],
                             name=cibles[row.cible], marker=dict(color=COLORS[row.cible], line=dict(width=0)),
                             hovertemplate=cibles[row.cible] + " · %{x} : × %{y:.2f}<extra></extra>"))
    fig.add_hline(y=1, line=dict(color="#7a7973", width=1, dash="dot"))
    fig.update_layout(plotly_layout("Part de la cible selon la favorabilité prédite (hors bloc)",
                                    xtitle="groupe de favorabilité (Q1 = la plus basse)",
                                    ytitle="part / part moyenne", height=320),
                      barmode="group", bargap=0.25, bargroupgap=0.08)
    v = hab_valid.assign(cible=hab_valid["cible"].map(cibles)).set_index("cible")
    v = v[["observations", "cibles", "auc_saison_source", "auc_altitude", "auc_habitat", "q1", "q5"]].round(3)
    v.columns = ["observations", "dont cible", "AUC saison + source", "AUC + altitude", "AUC + habitat",
                 "Q1", "Q5"]
    r.fig(fig)
    r.add(html_table(v))

    eff = coefs.pivot(index="variable", columns="cible", values="coef")
    eff = eff[[k for k in cibles if k in eff.columns]]
    frac = [i for i in eff.index if i.startswith(("foret_", "sol_", "wc_"))]
    e = np.exp(eff.loc[frac] * 0.5).round(2)  # passage de 0 à 50 % de la surface
    names = {**{f"foret_{k}": f"forêt : {v}" for k, v in FOREST_LABELS.items()},
             "sol_calcaire": "sol calcaire", "sol_acide": "sol acide",
             "wc_cultures": "cultures", "wc_prairies": "prairies"}
    e.index = [names.get(i, i) for i in e.index]
    e.columns = [cibles[c] for c in e.columns]
    r.add("<h4>Effet de chaque milieu</h4>")
    r.add('<p class="note">Facteur sur la part de la cible quand le milieu passe de 0 à 50 % de la maille, à '
          "altitude et autres milieux égaux. Au-dessus de 1 : favorable. Les milieux corrélés entre eux "
          "(pins et sols calcaires, par exemple) se partagent l'effet : à lire avec prudence.</p>")
    r.add(html_table(e))

    if analog_valid is not None and len(analog_valid):
        g = analog_valid.groupby("niveau")["gain_deviance"].agg(["min", "max"])
        r.add("<h3>Piste écartée pour l'instant : prévision par analogues</h3>")
        r.add('<p class="note">Chercher les situations météo passées les plus proches et regarder les poussées '
              "des semaines suivantes ne fait pas mieux que la phénologie seule sur les saisons mises de côté "
              f"(gain de {100 * g['min'].min():+.0f} % à {100 * g['max'].max():+.0f} %). Le module reste dans le dépôt "
              "(<code>mushroam.model.analogues</code>) pour une version plus simple plus tard.</p>")
    return "\n".join(r.parts)


PRED_TEMPLATE = MAP_HEAD.replace("__TITLE__", "Carte de prédiction") + r"""
#date { font-weight:600; }
.legend .cats span { display:inline-flex; align-items:center; gap:4px; margin-right:8px; }
.legend .cats i { width:12px; height:12px; border-radius:3px; display:inline-block; }
#tip { position:absolute; z-index:1000; pointer-events:none; background:var(--surface); color:var(--text);
  border:1px solid var(--border); border-radius:6px; padding:6px 8px; font-size:12px; display:none;
  font-variant-numeric:tabular-nums; box-shadow:0 2px 6px rgba(0,0,0,.15); }
</style></head>
<body><div id="wrap">
<div id="ctrl">
  <label>Cible <select id="cible"></select></label>
  <label>Couche <select id="layer"></select></label>
  <label>Transparence <input id="opacity" type="range" min="0" max="100" step="5" value="45" style="width:110px"></label>
  <span>Avis du <span id="date"></span> pour les 14 jours suivants</span>
</div>
<div id="map" style="position:relative"><div id="tip"></div></div></div>
<script>
const D = __DATA__;
const SEQ = ["#cde2fb","#9ec5f4","#6da7ec","#3987e5","#256abf","#184f95","#0d366b"];
const DIV = ["#b42c2c","#d65a52","#ec9a8c","#f0efec","#9ec5f4","#3987e5","#184f95"];
const CAT = ["#d65a52", "#c3c2b7", "#3987e5"], CATL = ["défavorable", "normale", "favorable"];
const map = L.map("map", {zoomControl:true}).setView(D.centre, 8);
const ATTRIB = " · BD Forêt IGN, sols INRAE, SIM2 Météo-France, iNaturalist, GBIF";
// Fonds sans clé, utilisables depuis un fichier local (jamais tile.openstreetmap.org, qui refuse file://).
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
const bases = {
  "Plan routier (Esri)": L.tileLayer(ESRI + "World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    {maxZoom:19, attribution:"Fond © Esri, HERE, Garmin, © OpenStreetMap" + ATTRIB}),
  "Topographie (OpenTopoMap)": L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    {maxZoom:17, attribution:"© OpenStreetMap, SRTM, © OpenTopoMap (CC-BY-SA)" + ATTRIB}),
  "Satellite (Esri)": L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {maxZoom:19, attribution:"Fond © Esri, Maxar, Earthstar Geographics" + ATTRIB}),
};
bases["Plan routier (Esri)"].addTo(map);
L.control.layers(bases, null, {position:"topright", collapsed:true}).addTo(map);
L.circle(D.centre, {radius:D.rayon_m, color:"#52514e", weight:1.5, fill:false, dashArray:"6 6", interactive:false}).addTo(map);
const raw = atob(D.idx), buf = new ArrayBuffer(raw.length), u8 = new Uint8Array(buf);
for (let i = 0; i < raw.length; i++) u8[i] = raw.charCodeAt(i);
const IDX = new Int16Array(buf);
let c = Object.keys(D.cibles)[0], layer = "potentiel", lo = 0, hi = 1, breaks = [];
function fill(sel, entries, val){ for (const [k, l] of entries) { const o=document.createElement("option"); o.value=k; o.textContent=l; sel.appendChild(o); } sel.value = val; }
const selC = document.getElementById("cible"), selL = document.getElementById("layer");
fill(selC, Object.entries(D.cibles), c);
fill(selL, Object.entries(D.layers).map(([k, v]) => [k, v.label]), layer);
document.getElementById("date").textContent = D.date;
const scale = () => D.layers[layer].scale;
const values = () => layer === "classe" ? D.classe : D.data[c][layer];
function range(){
  if (scale() === "cat") return;
  // Probabilité : paliers fixes, pour lire une valeur absolue.
  if (scale() === "prob") { breaks = [0.05, 0.1, 0.2, 0.3, 0.4, 0.5]; return; }
  const v = values().filter(x => x >= 0).map(x => scale() === "ratio" ? Math.log(Math.max(x, 1e-3)) : x).sort((a,b)=>a-b);
  const q = p => v[Math.min(v.length-1, Math.floor(p*(v.length-1)))];
  if (scale() === "ratio") { const r = Math.max(Math.abs(q(0.02)), Math.abs(q(0.98)), Math.log(1.5)); lo=-r; hi=r; }
  // Séquentiel : paliers à effectifs égaux (chaque couleur = 1/7 des mailles), pour classer les secteurs.
  else breaks = SEQ.slice(1).map((_, k) => q((k + 1) / SEQ.length));
}
function hex(h){ return [parseInt(h.slice(1,3),16), parseInt(h.slice(3,5),16), parseInt(h.slice(5,7),16)]; }
function rgb(x){
  if (scale() === "cat") return hex(CAT[x]);
  if (x < 0) return null;
  if (scale() === "seq" || scale() === "prob") { let k = 0; while (k < breaks.length && x >= breaks[k]) k++; return hex(SEQ[k]); }
  const t = Math.log(Math.max(x, 1e-3));
  return hex(DIV[Math.floor(Math.max(0, Math.min(0.9999, (t-lo)/(hi-lo))) * DIV.length)]);
}
const canvas = document.createElement("canvas"); canvas.width = D.w; canvas.height = D.h;
const ctx = canvas.getContext("2d");
let overlay = null;
function draw(){
  const img = ctx.createImageData(D.w, D.h), vals = values();
  const cache = new Map();
  for (let p = 0; p < IDX.length; p++) {
    const i = IDX[p]; if (i < 0) continue;
    const col = rgb(vals[i]); if (!col) continue;
    img.data[4*p] = col[0]; img.data[4*p+1] = col[1]; img.data[4*p+2] = col[2]; img.data[4*p+3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  if (overlay) map.removeLayer(overlay);
  overlay = L.imageOverlay(canvas.toDataURL(), D.bounds, {interactive:false, opacity:opacity()}).addTo(map);
  overlay.getElement().style.imageRendering = "pixelated";
  legend();
}
function f2(x){ return x.toFixed(2).replace(".", ","); }
function legend(){
  const el = document.getElementById("legend"), m = D.layers[layer];
  if (scale() === "cat") {
    el.innerHTML = "<div>"+m.label+"</div><div class='cats'>" + CATL.map((l,i)=>"<span><i style='background:"+CAT[i]+"'></i>"+l+"</span>").join("") + "</div>";
    return;
  }
  if (scale() === "prob") {
    el.innerHTML = "<div>"+m.label+"</div>"
      + '<div class="bar" style="background:linear-gradient(90deg,'+SEQ.join(",")+')"></div>'
      + '<div class="ticks">' + ["", ...breaks].map((b, k) => "<span>" + (k ? Math.round(100*b) : "0") + "</span>").join("") + '</div>'
      + '<div style="color:var(--muted);margin-top:2px">en %, liste de ' + D.taille + ' espèces</div>';
    return;
  }
  if (scale() === "seq") {
    el.innerHTML = "<div>"+m.label+"</div>"
      + '<div class="bar" style="background:linear-gradient(90deg,'+SEQ.join(",")+')"></div>'
      + '<div class="ticks"><span>plus bas</span><span>plus hauts</span></div>'
      + '<div class="ticks"><span>&lt; '+f2(breaks[0])+'</span><span>≥ '+f2(breaks[breaks.length-1])+'</span></div>'
      + '<div style="color:var(--muted);margin-top:2px">chaque couleur = 1/7 des mailles</div>';
    return;
  }
  const f = x => "× " + f2(Math.exp(x));
  el.innerHTML = "<div>"+m.label+"</div>"
    + '<div class="bar" style="background:linear-gradient(90deg,'+DIV.join(",")+')"></div>'
    + '<div class="ticks"><span>'+f(lo)+'</span><span>× 1</span><span>'+f(hi)+'</span></div>';
}
const lg = L.control({position:"bottomright"});
lg.onAdd = () => { const d = L.DomUtil.create("div","legend"); d.id="legend"; return d; };
lg.addTo(map);
map.fitBounds(D.bounds, {padding:[8, 8]});
// Survol : maille sous la souris, retrouvée à partir de la position en projection web.
const tip = document.getElementById("tip");
const [[s0, w0], [n0, e0]] = D.bounds;
const P0 = L.CRS.EPSG3857.project(L.latLng(n0, w0)), P1 = L.CRS.EPSG3857.project(L.latLng(s0, e0));
map.on("mousemove", e => {
  const p = L.CRS.EPSG3857.project(e.latlng);
  const col = Math.floor((p.x - P0.x) / (P1.x - P0.x) * D.w), row = Math.floor((P0.y - p.y) / (P0.y - P1.y) * D.h);
  const i = (col >= 0 && col < D.w && row >= 0 && row < D.h) ? IDX[row * D.w + col] : -1;
  if (i < 0) { tip.style.display = "none"; return; }
  const d = D.data[c];
  tip.innerHTML = (D.info.commune[i] ? "<b>" + D.info.commune[i] + "</b><br>" : "")
    + D.cibles[c] + " · potentiel <b>" + f2(d.potentiel[i]) + "</b>"
    + " · probabilité <b>" + Math.round(100 * d.probabilite[i]) + " %</b>"
    + "<br>habitat × " + f2(d.habitat[i]) + " · saison " + f2(d.saison[i])
    + "<br>météo " + CATL[D.classe[i]] + " (pluie 30 j : " + D.pluie30[i] + " mm)"
    + "<br>" + D.info.alt[i] + " m · " + D.info.foret[i] + " · sol " + D.info.sol[i];
  tip.style.left = (e.containerPoint.x + 14) + "px"; tip.style.top = (e.containerPoint.y + 14) + "px";
  tip.style.display = "block";
});
map.on("mouseout", () => { tip.style.display = "none"; });
const opacityInput = document.getElementById("opacity");
function opacity(){ return 1 - opacityInput.value / 100; }
opacityInput.oninput = () => { if (overlay) overlay.setOpacity(opacity()); };
selC.onchange = () => { c = selC.value; range(); draw(); };
selL.onchange = () => { layer = selL.value; range(); draw(); };
range(); draw();
</script></body></html>
"""
