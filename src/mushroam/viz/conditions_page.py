"""Section « Météo et poussées » (étape 4) de l'onglet Météo."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from mushroam.model import conditions as C
from mushroam.viz.explore import Report, html_table
from mushroam.viz.theme import COLORS, plotly_layout

FUNGI_COLOR = "#52514e"
FOND_COLOR = "#a3a29c"

# Variables analysées : (libellé, bornes fixes ou None pour des quintiles, décimales)
FEATURES = {
    "jours_depuis_20mm": ("Jours depuis une pluie ≥ 20 mm", [0, 3, 7, 14, 21, 35, 60, np.inf], 0),
    "pluie_30j": ("Pluie sur 30 jours (mm)", None, 0),
    "swi": ("Humidité des sols (SWI)", None, 2),
    "swi_tend_14j": ("Variation du SWI sur 14 jours", None, 2),
    "tmin_7j": ("Température minimale, moyenne 7 jours (°C)", None, 0),
    "tmax_7j": ("Température maximale, moyenne 7 jours (°C)", None, 0),
}


def edges_for(feature: str, values: pd.Series) -> np.ndarray:
    fixed = FEATURES[feature][1]
    if fixed:
        return np.array([-np.inf, *fixed[1:-1], np.inf])
    return C.quantile_bins(values, 5)


def ratio_trace(t: pd.DataFrame, name: str, color: str, visible: bool) -> go.Scatter:
    return go.Scatter(
        x=list(t.index.astype(str)), y=t["rapport"], name=name, visible=visible,
        mode="lines+markers", line=dict(color=color, width=2),
        marker=dict(size=8, color=color, line=dict(width=2, color="#fcfcfb")),
        error_y=dict(type="data", symmetric=False, array=t["haut"] - t["rapport"],
                     arrayminus=t["rapport"] - t["bas"], color=color, thickness=1.5, width=4),
        customdata=np.stack([t["observe"], t["attendu"]], axis=1),
        hovertemplate=name + " : %{y:.2f} (observé %{customdata[0]:.0f}, attendu %{customdata[1]:.0f})<extra></extra>",
    )


def dropdown_figure(traces_by_feature: dict[str, list[go.Scatter]], title: str, height: int = 380) -> go.Figure:
    """Un graphique, une variable affichée à la fois, choisie dans un menu."""
    feats = list(traces_by_feature)
    fig = go.Figure()
    for tr in (tr for f in feats for tr in traces_by_feature[f]):
        fig.add_trace(tr)
    sizes = [len(traces_by_feature[f]) for f in feats]
    buttons = []
    for i, f in enumerate(feats):
        vis = [j == i for j, n in enumerate(sizes) for _ in range(n)]
        buttons.append(dict(label=FEATURES[f][0], method="update",
                            args=[{"visible": vis}, {"xaxis.title.text": FEATURES[f][0]}]))
    fig.update_layout(plotly_layout(title, xtitle=FEATURES[feats[0]][0], ytitle="rapport observé / attendu",
                                    height=height), hovermode="x unified")
    fig.update_layout(margin=dict(t=88), updatemenus=[dict(
        buttons=buttons, direction="down", x=0, xanchor="left", y=1.18, yanchor="top",
        bgcolor="#fcfcfb", bordercolor="#e2e1dc", font=dict(size=12))])
    fig.add_hline(y=1, line=dict(color="#7a7973", width=1, dash="dot"))
    return fig


def conditions_section(obs: pd.DataFrame, feats: pd.DataFrame, effort: pd.DataFrame,
                       grid: pd.DataFrame, cibles: dict[str, str], zone_cells: list[str]) -> str:
    r = Report("cond")
    r.add('<p class="note">Toutes les comparaisons sont faites <b>à saison comparable</b> : pour chaque quinzaine '
          "de l'année (et chaque tranche d'altitude pour les cibles), on calcule la proportion habituelle, puis on "
          "regarde si elle est plus forte ou plus faible selon la météo. Un rapport de 1 = comme d'habitude à cette "
          "période ; 1,5 = une fois et demie plus fréquent. Barres : intervalle à 95 % approché, probablement trop "
          "étroit (les observations d'une même sortie ne sont pas indépendantes).</p>")

    # Niveau 1 : activité des champignons (zone, iNat, depuis 2019).
    w = C.zone_daily_weather(feats, zone_cells)
    e = effort[effort["date"] >= "2019-01-01"]
    lvl1, traces = {}, {}
    for f, (_, _, dec) in FEATURES.items():
        t = C.fungi_activity(e, w, f, edges_for(f, w.loc[w.index >= "2019-01-01", f]), dec)
        lvl1[f] = t
        traces[f] = [ratio_trace(t, "Fungi", FUNGI_COLOR, f == "jours_depuis_20mm")]
    r.add("<h3>1. Activité des champignons</h3>")
    r.add('<p class="note">Part des champignons (hors lichens) parmi <i>toutes</i> les observations iNaturalist de la '
          "zone, jour par jour, depuis 2019. Le dénominateur (plantes, oiseaux, insectes…) mesure la présence des "
          "observateurs sur le terrain : le rapport reflète donc l'activité des champignons, pas l'effort.</p>")
    r.fig(dropdown_figure(traces, "Activité des champignons selon la météo"),
          table=stack_tables({f: lvl1[f] for f in FEATURES}))

    # Niveau 2 : part des cibles parmi les champignons (maille, toutes sources).
    lvl2, traces = {}, {}
    for f, (_, _, dec) in FEATURES.items():
        edges = edges_for(f, obs[f])
        traces[f] = []
        for k, label in cibles.items():
            t = C.target_share(obs, k, f, edges, dec)
            lvl2[(f, k)] = t
            traces[f].append(ratio_trace(t, label, COLORS[k], f == "jours_depuis_20mm"))
    r.add("<h3>2. Part des cibles parmi les champignons</h3>")
    r.add('<p class="note">Proportion de la cible parmi les observations de champignons de la même maille SIM2, '
          "toutes sources, à quinzaine et tranche d'altitude égales. Mesure si la cible réagit plus tôt, plus tard, "
          "plus ou moins fort que les champignons en général.</p>")
    r.fig(dropdown_figure(traces, "Part des cibles selon la météo"),
          table=stack_tables({f"{f} · {cibles[k]}": t for (f, k), t in lvl2.items()}))

    # Trajectoires des 30 jours précédents.
    r.add("<h3>3. Les 30 jours avant une observation</h3>")
    r.add('<p class="note">Moyenne, jour par jour, des conditions dans la maille de l\'observation. Le fond est '
          "repondéré pour avoir la même répartition par quinzaine et altitude que la cible : l'écart entre les "
          "courbes ne vient pas de la saison.</p>")
    wide = {v: feats.pivot(index="date", columns="cellule", values=v) for v in ("pluie", "swi")}
    tr = C.trajectories(obs, wide, days=30)
    cum = np.nancumsum(tr["pluie"], axis=1)
    cum[np.isnan(tr["pluie"]).all(axis=1)] = np.nan
    x = np.arange(-30, 1)
    rows = {}
    for k, label in cibles.items():
        is_t = obs[f"cible_{k}"].to_numpy()
        wf = C.stratum_weights(obs, k).to_numpy()
        fig = go.Figure()
        traces_v = []
        for i, (var, vlabel, arr) in enumerate([("swi", "Humidité des sols (SWI)", tr["swi"]),
                                                ("pluie", "Pluie cumulée depuis J−30 (mm)", cum)]):
            tgt = C.weighted_mean_curve(arr[is_t], np.ones(is_t.sum()))
            fond = C.weighted_mean_curve(arr[~is_t], wf[~is_t])
            rows[(label, vlabel, "cible")] = tgt
            rows[(label, vlabel, "fond")] = fond
            dec = ".2f" if var == "swi" else ".0f"
            fig.add_trace(go.Scatter(x=x, y=fond, name="fond (même saison)", visible=i == 0, mode="lines",
                                     line=dict(color=FOND_COLOR, width=2, dash="dot"),
                                     hovertemplate="fond %{y:" + dec + "}<extra></extra>"))
            fig.add_trace(go.Scatter(x=x, y=tgt, name=label, visible=i == 0, mode="lines",
                                     line=dict(color=COLORS[k], width=2),
                                     hovertemplate=label + " %{y:" + dec + "}<extra></extra>"))
            traces_v.append(vlabel)
        buttons = [dict(label=v, method="update",
                        args=[{"visible": [j // 2 == i for j in range(4)]}, {"yaxis.title.text": v}])
                   for i, v in enumerate(traces_v)]
        fig.update_layout(plotly_layout(f"{label} : conditions avant l'observation",
                                        xtitle="jours avant l'observation", ytitle=traces_v[0], height=340),
                          margin=dict(t=88), updatemenus=[dict(buttons=buttons, direction="down", x=0, xanchor="left",
                                                                 y=1.2, yanchor="top", bgcolor="#fcfcfb",
                                                                 bordercolor="#e2e1dc", font=dict(size=12))])
        n = int(is_t.sum())
        r.fig(fig, f"{n} observations de la cible, {int((~is_t).sum())} du fond.")
    t = pd.DataFrame({" · ".join(k): v for k, v in rows.items()}, index=pd.Index(x, name="jour")).iloc[::5]
    r.add("<details><summary>Voir les données (tous les 5 jours)</summary>" + html_table(t.round(2).T) + "</details>")
    return "\n".join(r.parts)


def stack_tables(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    out = []
    for name, t in tables.items():
        x = t[["observe", "attendu", "rapport", "bas", "haut"]].copy()
        x.index = [f"{name} : {c}" for c in x.index.astype(str)]
        out.append(x)
    df = pd.concat(out).round(2)
    df.index.name = "variable : classe"
    return df
