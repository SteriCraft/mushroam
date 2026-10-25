"""Site local : onglets Observations, Météo et Prédiction.

Chaque onglet montre d'abord une carte, puis les données. Le site est un dossier
de fichiers statiques à ouvrir dans un navigateur :
data/outputs/site/index.html

Usage : python -m mushroam.viz.site
"""

from __future__ import annotations

import json
import shutil

import pandas as pd

from mushroam.config import DATA_DIR, PROCESSED_DIR, load_taxa, load_yaml, load_zone
from mushroam.meteo.sim2 import zone_grid
from mushroam.observations import haversine_km
from mushroam.viz.conditions_page import conditions_section
from mushroam.viz.explore import observations_section
from mushroam.viz.map import build_map
from mushroam.viz.prediction_page import prediction_map_html, prediction_section
from mushroam.viz.meteo_page import meteo_map_html, meteo_section, normals, with_anomalies
from mushroam.viz.theme import CSS, LIGHT_TO_DARK, THEME_JS

OUT_DIR = DATA_DIR / "outputs" / "site"

TABS_CSS = """
header.site { border-bottom: 1px solid var(--border); background: var(--surface-2); }
header.site .in { max-width: 1100px; margin: 0 auto; padding: 16px 16px 0; }
header.site h1 { margin: 0; font-size: 1.4rem; }
header.site p { margin: 2px 0 12px; color: var(--muted); font-size: .9rem; }
nav.tabs { display: flex; gap: 4px; overflow-x: auto; }
nav.tabs a { padding: 8px 14px; border: 1px solid transparent; border-bottom: none;
  border-radius: 8px 8px 0 0; color: var(--text-2); text-decoration: none; white-space: nowrap; }
nav.tabs a[aria-selected="true"] { background: var(--surface); border-color: var(--border);
  color: var(--text); font-weight: 600; margin-bottom: -1px; }
section.tab[hidden] { display: none; }
.placeholder { padding: 32px; border: 1px dashed var(--border); border-radius: 8px; color: var(--muted); }
"""

TABS_JS = """
<script>
(function () {
  const tabs = ['observations', 'meteo', 'prediction'];
  function show(name) {
    if (!tabs.includes(name)) name = tabs[0];
    tabs.forEach(function (t) {
      document.getElementById('tab-' + t).hidden = (t !== name);
      document.getElementById('link-' + t).setAttribute('aria-selected', t === name);
    });
    // Les graphiques d'un onglet masqué n'ont pas de largeur : on les redimensionne à l'affichage.
    window.dispatchEvent(new Event('resize'));
  }
  window.addEventListener('hashchange', function () { show(location.hash.slice(1)); });
  show(location.hash.slice(1));
})();
</script>
"""


def page(obs_html: str, met_html: str, cond_html: str, pred_html: str, generated: pd.Timestamp, last_meteo: pd.Timestamp) -> str:
    def tab(name, label):
        return f'<a id="link-{name}" href="#{name}" role="tab">{label}</a>'

    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mushroam</title>
<style>{CSS}{TABS_CSS}</style><script src="plotly.min.js"></script></head>
<body>
<header class="site"><div class="in">
<h1>Mushroam</h1>
<p>Champignons à 100 km autour de Montpellier · généré le {generated:%d/%m/%Y} · météo jusqu'au {last_meteo:%d/%m/%Y}</p>
<nav class="tabs" role="tablist">{tab("observations", "Observations")}{tab("meteo", "Météo")}{tab("prediction", "Prédiction")}</nav>
</div></header>
<main>
<section class="tab" id="tab-observations" role="tabpanel">
<h2 style="border:0;margin-top:8px">Carte des observations</h2>
<p class="note">Fond OpenTopoMap (relief) ou satellite ; couches activables en haut à droite. Cercles pleins : position précise à 1 km près ;
cercles vides : position imprécise. Une couche masquée montre les cibles exclues (zone urbaine, point répété).
<a href="carte_observations.html" target="_blank">Plein écran</a>.</p>
<iframe class="mapframe" src="carte_observations.html" title="Carte des observations"></iframe>
<h2>Données</h2>
{obs_html}
</section>
<section class="tab" id="tab-meteo" role="tabpanel" hidden>
<h2 style="border:0;margin-top:8px">Carte météo</h2>
<p class="note">Une case = une maille SIM2 de 8 km. Choisir la variable et la date (90 derniers jours).
Échelle de couleur fixe sur la période, pour comparer les dates. <a href="carte_meteo.html" target="_blank">Plein écran</a>.</p>
<iframe class="mapframe" src="carte_meteo.html" title="Carte météo"></iframe>
<h2>Données</h2>
{met_html}
<h2>Météo et poussées</h2>
{cond_html}
</section>
<section class="tab" id="tab-prediction" role="tabpanel" hidden>
<h2 style="border:0;margin-top:8px">Prédiction</h2>
<p class="note">Une case = une maille de 1 km. Potentiel = favorabilité de l'habitat × saison normale à cette altitude
pour les 14 prochains jours × facteur de la météo actuelle. Sert à <b>classer</b> les secteurs, pas à donner une probabilité.
<a href="carte_prediction.html" target="_blank">Plein écran</a>.</p>
<iframe class="mapframe" src="carte_prediction.html" title="Carte de prédiction"></iframe>
<h2>Données</h2>
{pred_html}
</section>
</main>
{THEME_JS % json.dumps(LIGHT_TO_DARK)}{TABS_JS}
</body></html>"""


def build() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    js = OUT_DIR / "plotly.min.js"
    if not js.exists():
        from plotly.offline import get_plotlyjs
        js.write_text(get_plotlyjs(), encoding="utf-8")

    taxa, rules = load_taxa(), load_yaml("sources.yaml")
    obs = pd.read_parquet(PROCESSED_DIR / "observations.parquet")
    feats = pd.read_parquet(PROCESSED_DIR / "meteo_features.parquet")
    grid = zone_grid()
    last = feats["date"].max()

    # Météo du jour de chaque observation (fenêtres de la carte, analyse de l'étape 4).
    obs_w = obs.merge(feats, left_on=["cellule_meteo", "observed_on"], right_on=["cellule", "date"], how="left")
    obs_w = obs_w.merge(grid[["cellule", "altitude_m"]].rename(columns={"altitude_m": "altitude_maille"}),
                        on="cellule", how="left")
    build_map(obs_w, taxa, rules).save(str(OUT_DIR / "carte_observations.html"))
    obs_html = observations_section(obs, taxa, rules)

    sel = obs_w[obs_w["retenue"] & ~obs_w["lichen"] & obs_w["ok_meteo"] & obs_w["pluie_30j"].notna()].reset_index(drop=True)
    z = load_zone()
    zone_cells = grid.loc[haversine_km(z["centre"]["lat"], z["centre"]["lng"], grid["lat"], grid["lng"])
                          <= z["rayon_km"], "cellule"].tolist()
    effort = pd.read_parquet(PROCESSED_DIR / "inat_effort.parquet")
    cibles = {k: v["label"] for k, v in taxa["cibles"].items()}
    cond_html = conditions_section(sel, feats, effort, grid, cibles, zone_cells)

    f = with_anomalies(feats[feats["date"] > last - pd.Timedelta(days=400)], normals(feats, last.year))
    (OUT_DIR / "carte_meteo.html").write_text(meteo_map_html(f, grid), encoding="utf-8")
    met_html = meteo_section(f, grid)

    # Prédiction (étapes 5 et 6).
    pred = pd.read_parquet(PROCESSED_DIR / "prediction_1km.parquet")
    hgrid = pd.read_parquet(PROCESSED_DIR / "habitat_1km.parquet")
    (OUT_DIR / "carte_prediction.html").write_text(prediction_map_html(pred, hgrid, cibles), encoding="utf-8")
    analog = PROCESSED_DIR / "analogues_validation.parquet"
    pred_html = prediction_section(pred, hgrid, cibles, pd.read_parquet(PROCESSED_DIR / "classes_meteo_validation.parquet"),
                                   pd.read_parquet(PROCESSED_DIR / "habitat_validation.parquet"),
                                   pd.read_parquet(PROCESSED_DIR / "habitat_coefficients.parquet"),
                                   pd.read_parquet(analog) if analog.exists() else None)

    (OUT_DIR / "index.html").write_text(page(obs_html, met_html, cond_html, pred_html, pd.Timestamp.today(), last), encoding="utf-8")
    old = DATA_DIR / "outputs" / "exploration"
    if old.exists():
        shutil.rmtree(old)  # ancien rapport, remplacé par le site
    print(f"Écrit : {OUT_DIR / 'index.html'}")


def main() -> None:
    build()


if __name__ == "__main__":
    main()
