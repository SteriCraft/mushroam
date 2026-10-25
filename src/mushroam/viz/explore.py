"""Analyse exploratoire des observations (étape 2) : partie « données » de
l'onglet Observations du site (voir mushroam.viz.site).

Entrée : data/processed/observations.parquet (voir mushroam.observations).
"""

from __future__ import annotations

import html

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from mushroam.viz.theme import COLORS, NEUTRAL_LIGHT, SEQ_LIGHT, plotly_layout

SOURCES = {"inat": "iNaturalist", "gbif": "GBIF (hors iNat)"}
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
ALT_BANDS = [0, 200, 400, 600, 800, 1000, 1200, 1700]


def fmt(n) -> str:
    return f"{n:,.0f}".replace(",", " ")


def pct(x) -> str:
    return f"{100 * x:.1f} %".replace(".", ",")


class Report:
    """Accumule du HTML (texte, graphiques Plotly, tableaux) pour une section du site."""

    def __init__(self, prefix: str = "fig"):
        self.parts: list[str] = []
        self.prefix = prefix
        self.n_fig = 0

    def add(self, s: str):
        self.parts.append(s)

    def fig(self, fig: go.Figure, note: str = "", table: pd.DataFrame | None = None):
        self.n_fig += 1
        self.add('<div class="fig">' + pio.to_html(
            fig, full_html=False, include_plotlyjs=False, div_id=f"{self.prefix}{self.n_fig}",
            config={"displaylogo": False, "responsive": True,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"]}) + "</div>")
        if note:
            self.add(f'<p class="note">{note}</p>')
        if table is not None:
            self.add("<details><summary>Voir les données</summary>" + html_table(table) + "</details>")


def html_table(df: pd.DataFrame) -> str:
    def cell(v):
        if isinstance(v, (int, np.integer)):
            return fmt(v)
        if isinstance(v, (float, np.floating)):
            if np.isnan(v):
                return ""
            if float(v).is_integer() or abs(v) >= 100:
                return fmt(v)
            return (f"{v:.2f}" if abs(v) < 1 else f"{v:.1f}").replace(".", ",")
        return html.escape(str(v))

    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in [df.index.name or ""] + list(df.columns))
    rows = "".join(
        "<tr>" + f"<td>{cell(i)}</td>" + "".join(f"<td>{cell(v)}</td>" for v in r) + "</tr>"
        for i, r in zip(df.index, df.itertuples(index=False))
    )
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'


def bar(x, y, name, color, **kw):
    return go.Bar(x=x, y=y, name=name, marker=dict(color=color, line=dict(width=1, color="#fcfcfb")), **kw)


def line(x, y, name, color, **kw):
    return go.Scatter(x=x, y=y, name=name, mode="lines+markers", line=dict(color=color, width=2),
                      marker=dict(size=8, color=color, line=dict(width=2, color="#fcfcfb")), **kw)


def precision_class(p: pd.Series) -> pd.Series:
    c = pd.cut(p, [-1, 100, 1000, np.inf], labels=["≤ 100 m", "100 m – 1 km", "> 1 km"])
    return c.cat.add_categories("inconnue").fillna("inconnue")


def observations_section(df: pd.DataFrame, taxa: dict, rules: dict) -> str:
    cibles = {k: v["label"] for k, v in taxa["cibles"].items()}
    n_dup = int(df["doublon"].sum())
    n_loc = int((~df["doublon"] & (df["urbain"] | df["point_repete"])).sum())
    df = df[df["retenue"]].copy()
    n_lichen = int(df["lichen"].sum())
    fond = df[~df["lichen"]].copy()
    fond["annee"] = fond["observed_on"].dt.year
    fond["mois"] = fond["observed_on"].dt.month
    tgt = {k: fond[fond[f"cible_{k}"]] for k in cibles}

    r = Report("obs")

    r.add('<div class="kpis">'
          f'<div class="kpi"><b>{fmt(len(fond))}</b><span>observations du fond (Fungi hors lichens, retenues)</span></div>'
          + "".join(f'<div class="kpi"><b>{fmt(len(t))}</b><span>{cibles[k]}</span></div>' for k, t in tgt.items())
          + f'<div class="kpi"><b>{fmt(n_dup)}</b><span>doublons probables écartés</span></div>'
          f'<div class="kpi"><b>{fmt(n_loc)}</b><span>en zone urbaine ou à un point répété (bureau, labo)</span></div>'
          f'<div class="kpi"><b>{fmt(n_lichen)}</b><span>lichens exclus du fond</span></div>'
          "</div>")

    # --- Sources
    r.add("<h2>Sources</h2>")
    src = pd.DataFrame({
        "fond": fond.groupby("source").size(),
        **{cibles[k]: t.groupby("source").size() for k, t in tgt.items()},
        "observateurs": fond.groupby("source")["observer"].nunique(),
    }).fillna(0).astype(int).rename(index=SOURCES)
    src.index.name = "source"
    r.add(html_table(src))
    qual = pd.crosstab(pd.concat([t.assign(cible=cibles[k]) for k, t in tgt.items()])["cible"],
                       pd.concat([t for t in tgt.values()])["quality"].map(
                           {"research": "iNat confirmée", "needs_id": "iNat à confirmer", "gbif": "GBIF"}))
    qual.index.name = "cible"
    r.add("<h3>Statut des observations cibles</h3>" + html_table(qual))
    top = (fond.groupby("dataset").agg(
        fond=("source_id", "size"),
        **{cibles[k]: (f"cible_{k}", "sum") for k in cibles},
        points=("lat", lambda la: la.round(4).astype(str).add(fond.loc[la.index, "lng"].round(4).astype(str)).nunique()),
        precision_1km=("ok_habitat", "mean"),
        premiere=("annee", "min"), derniere=("annee", "max"),
    ).sort_values("fond", ascending=False).head(20))
    top["precision_1km"] = (100 * top["precision_1km"]).round(0).astype(int)
    top = top.rename(columns={"points": "points distincts", "precision_1km": "% précision ≤ 1 km",
                              "premiere": "de", "derniere": "à"})
    r.add("<h3>Principaux jeux de données</h3>" + html_table(top))
    r.add('<p class="note">« Points distincts » faible = observations ramenées à quelques sites ou communes. '
          "Une précision inconnue est comptée comme imprécise. Ces observations servent pour la météo "
          f"(précision ≤ {fmt(rules['precision_max_meteo_m'] / 1000)} km ou inconnue), pas pour l'habitat.</p>")
    use = pd.DataFrame({
        "habitat (≤ 1 km)": [int(t["ok_habitat"].sum()) for t in tgt.values()],
        "météo": [int(t["ok_meteo"].sum()) for t in tgt.values()],
        "total": [len(t) for t in tgt.values()],
    }, index=[cibles[k] for k in tgt])
    use.index.name = "cible"
    r.add("<h3>Observations utilisables par couche</h3>" + html_table(use))

    # --- Années
    r.add("<h2>Effectifs par année</h2>")
    years = list(range(1990, pd.Timestamp.today().year + 1))
    for label, d in [("Fond de référence", fond)] + [(cibles[k], t) for k, t in tgt.items()]:
        d = d[d["annee"] >= 1990]
        tab = pd.crosstab(d["annee"], d["source"]).reindex(years, fill_value=0)
        f = go.Figure([bar(tab.index, tab[s], SOURCES[s], COLORS[s])
                       for i, s in enumerate(SOURCES) if s in tab])
        f.update_layout(plotly_layout(label, ytitle="observations", height=300), barmode="stack")
        r.fig(f)
    before = int((fond["annee"] < 1990).sum())
    r.add(f'<p class="note">Avant 1990 : {fmt(before)} observations du fond, non représentées.</p>')

    # --- Saison
    r.add("<h2>Saisonnalité</h2>")
    r.add('<p class="note">Proportion = observations de la cible / observations de toutes les Fungi '
          "(hors lichens) du même mois, toutes années confondues. C'est la mesure corrigée de l'effort "
          "d'observation, contrairement aux effectifs bruts. Un graphique par cible : les échelles diffèrent.</p>")
    m_fond = fond.groupby("mois").size().reindex(range(1, 13), fill_value=0)
    for k, t in tgt.items():
        m = t.groupby("mois").size().reindex(range(1, 13), fill_value=0)
        prop = 100 * m / m_fond
        f = go.Figure([line(MOIS, prop, cibles[k], COLORS[k], customdata=m,
                            hovertemplate="%{y:.2f} % (%{customdata} obs.)<extra></extra>")])
        f.update_layout(plotly_layout(f"{cibles[k]} : part du fond par mois", ytitle="% du fond", height=300),
                        showlegend=False)
        tab = pd.DataFrame({"fond": m_fond.values, cibles[k]: m.values, "% du fond": prop.round(2).values},
                           index=pd.Index(MOIS, name="mois"))
        r.fig(f, table=tab)

    # --- Jour de la semaine
    r.add("<h2>Effort d'observation</h2>")
    wd = pd.crosstab(fond["observed_on"].dt.day_of_week, fond["source"], normalize="columns") * 100
    f = go.Figure([bar(JOURS, wd[s], SOURCES[s], COLORS[s],
                       hovertemplate="%{y:.1f} %<extra>" + SOURCES[s] + "</extra>")
                   for i, s in enumerate(SOURCES) if s in wd])
    f.update_layout(plotly_layout("Répartition des observations par jour de la semaine", ytitle="% des observations"),
                    barmode="group")
    wd.index = JOURS
    wd.index.name = "jour"
    r.fig(f, "Sans biais d'effort, chaque jour pèserait 14,3 %.", wd.round(1).rename(columns=SOURCES))

    obs_counts = {k: t["observer"].value_counts() for k, t in tgt.items()}
    rows = []
    for k, vc in obs_counts.items():
        rows.append({"cible": cibles[k], "observateurs": len(vc),
                     "part des 5 premiers (%)": round(100 * vc.head(5).sum() / max(vc.sum(), 1), 1),
                     "part du 1er (%)": round(100 * vc.head(1).sum() / max(vc.sum(), 1), 1)})
    r.add("<h3>Concentration par observateur</h3>" + html_table(pd.DataFrame(rows).set_index("cible")))

    # --- Précision
    r.add("<h2>Précision des positions</h2>")
    groups = {"iNaturalist": fond[fond["source"] == "inat"], "GBIF": fond[fond["source"] == "gbif"],
              **{cibles[k]: t for k, t in tgt.items()}}
    cls = ["≤ 100 m", "100 m – 1 km", "> 1 km", "inconnue"]
    colors = SEQ_LIGHT[:3] + [NEUTRAL_LIGHT]
    ptab = pd.DataFrame({g: precision_class(d["precision_m"]).value_counts(normalize=True)
                         for g, d in groups.items()}).reindex(cls).fillna(0).T * 100
    f = go.Figure([go.Bar(y=ptab.index, x=ptab[c], name=c, orientation="h",
                          marker=dict(color=colors[i], line=dict(width=1, color="#fcfcfb")),
                          hovertemplate="%{x:.1f} %<extra>" + c + "</extra>")
                   for i, c in enumerate(cls)])
    f.update_layout(plotly_layout("Précision de position", xtitle="% des observations", height=280),
                    barmode="stack", hovermode="y unified")
    f.update_yaxes(autorange="reversed")
    ptab.index.name = "groupe"
    r.fig(f, f"Seuils retenus : {fmt(rules['precision_max_habitat_m'])} m pour la couche habitat ; "
             f"{fmt(rules['precision_max_meteo_m'] / 1000)} km (ou précision inconnue) pour la couche météo. "
             f"Observations floutées : {fmt(fond['obscured'].sum())} ({pct(fond['obscured'].mean())}).",
          ptab.round(1))

    # --- Altitude
    r.add("<h2>Gradient d'altitude</h2>")
    # Seules les positions précises à 1 km près donnent une altitude fiable.
    alt = fond[fond["altitude_m"].notna() & fond["ok_habitat"]].copy()
    labels = [f"{a}–{b}" for a, b in zip(ALT_BANDS[:-1], ALT_BANDS[1:])]
    alt["bande"] = pd.cut(alt["altitude_m"].clip(lower=0), ALT_BANDS, labels=labels, right=False)
    a_fond = alt.groupby("bande", observed=False).size()
    r.add('<p class="note">Même mesure corrigée de l\'effort, par tranche d\'altitude du point '
          "d'observation (MNT Copernicus 90 m). Seules les positions précises à 1 km près sont retenues.</p>")
    for k in cibles:
        a = alt[alt[f"cible_{k}"]].groupby("bande", observed=False).size()
        prop = 100 * a / a_fond
        f = go.Figure([line(labels, prop, cibles[k], COLORS[k], customdata=a,
                            hovertemplate="%{y:.2f} % (%{customdata} obs.)<extra></extra>")])
        f.update_layout(plotly_layout(f"{cibles[k]} : part du fond selon l'altitude", xtitle="altitude (m)",
                                      ytitle="% du fond", height=300), showlegend=False)
        atab = pd.DataFrame({"fond": a_fond.values, cibles[k]: a.values, "% du fond": prop.round(2).values},
                            index=pd.Index(labels, name="altitude (m)"))
        r.fig(f, table=atab)

    # Phénologie selon l'altitude : saison d'automne seulement (août à décembre).
    aut = alt[alt["mois"].between(8, 12)].copy()
    aut["jour"] = aut["observed_on"].dt.day_of_year
    f = go.Figure()
    ptab2 = {}
    for i, k in enumerate(cibles):
        d = aut[aut[f"cible_{k}"]]
        f.add_trace(go.Box(x=d["bande"].astype(str), y=pd.to_datetime("2001-01-01") + pd.to_timedelta(d["jour"] - 1, "D"),
                           name=cibles[k], marker=dict(color=COLORS[k], size=8),
                           line=dict(color=COLORS[k], width=2), boxpoints=False))
        med = d.groupby("bande", observed=False)["jour"].agg(["median", "size"])
        ptab2[(cibles[k], "jour médian")] = med["median"].map(
            lambda j: "" if np.isnan(j) else (pd.Timestamp("2001-01-01") + pd.Timedelta(days=j - 1)).strftime("%d/%m"))
        ptab2[(cibles[k], "n")] = med["size"]
    f.update_layout(plotly_layout("Date d'observation en automne selon l'altitude", xtitle="altitude (m)", height=400),
                    boxmode="group", hovermode="closest")
    f.update_xaxes(categoryorder="array", categoryarray=labels)
    f.update_yaxes(tickformat="%d %b")
    t2 = pd.DataFrame(ptab2)
    t2.columns = [" – ".join(c) for c in t2.columns]
    t2.index.name = "altitude (m)"
    r.fig(f, "Observations d'août à décembre. Boîtes : 25 %, médiane, 75 % ; moustaches : étendue hors valeurs extrêmes.",
          t2)

    return "\n".join(r.parts)
