"""Palette et mise en forme communes aux graphiques (clair / sombre).

Une couleur par entité, identique dans tout le rapport et sur la carte :
sources (iNat bleu, GBIF jaune) et cibles (coulemelle aqua, bolets des feuillus
orange, bolets des pins violet).
Validé pour la vision des couleurs altérée, en clair et en sombre (les trois
couleurs de cibles deux à deux).
"""

COLORS = {"inat": "#2a78d6", "gbif": "#eda100", "coulemelle": "#1baf7a",
          "bolets_feuillus": "#eb6834", "bolets_pins": "#6250d6"}
COLORS_DARK = {"inat": "#3987e5", "gbif": "#c98500", "coulemelle": "#199e70",
               "bolets_feuillus": "#d95926", "bolets_pins": "#9085e9"}
SEQ_LIGHT = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]  # rampe ordinale bleue
SEQ_DARK = ["#184f95", "#256abf", "#5598e7", "#9ec5f4"]
NEUTRAL_LIGHT, NEUTRAL_DARK = "#a3a29c", "#6b6a64"

LIGHT_TO_DARK = {**{COLORS[k]: COLORS_DARK[k] for k in COLORS},
                 **dict(zip(SEQ_LIGHT + [NEUTRAL_LIGHT], SEQ_DARK + [NEUTRAL_DARK]))}

FONT = "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"

CSS = """
:root {
  color-scheme: light;
  --surface: #fcfcfb; --surface-2: #f3f2ef; --border: #e2e1dc;
  --text: #0b0b0b; --text-2: #52514e; --muted: #7a7973; --accent: #2a78d6;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface: #1a1a19; --surface-2: #232321; --border: #383835;
    --text: #f0efec; --text-2: #c3c2b7; --muted: #94938b; --accent: #3987e5;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface: #1a1a19; --surface-2: #232321; --border: #383835;
  --text: #f0efec; --text-2: #c3c2b7; --muted: #94938b; --accent: #3987e5;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface); color: var(--text);
       font: 15px/1.55 FONT; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 1.6rem; margin: 0 0 4px; }
h2 { font-size: 1.2rem; margin: 40px 0 8px; padding-top: 16px; border-top: 1px solid var(--border); }
h3 { font-size: 1rem; margin: 20px 0 4px; }
p, li { color: var(--text-2); max-width: 75ch; }
.sub { color: var(--muted); margin: 0 0 24px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 16px 0; }
.kpi { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.kpi b { display: block; font-size: 1.5rem; font-variant-numeric: tabular-nums; color: var(--text); }
.kpi span { color: var(--muted); font-size: .85rem; }
.fig { margin: 8px 0 4px; }
.note { font-size: .9rem; color: var(--muted); }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; font-size: .9rem; font-variant-numeric: tabular-nums; margin: 8px 0; }
th, td { padding: 4px 10px; border-bottom: 1px solid var(--border); text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--text-2); font-weight: 600; }
details { margin: 4px 0 12px; } summary { cursor: pointer; color: var(--muted); font-size: .9rem; }
a { color: var(--accent); }
.mapframe { width: 100%; height: 640px; border: 1px solid var(--border); border-radius: 8px; }
""".replace("FONT", FONT)

# Bascule clair/sombre des graphiques Plotly : mêmes rampes, pas d'inversion automatique.
THEME_JS = """
<script>
(function () {
  const L2D = %s;
  function dark() {
    const t = document.documentElement.dataset.theme;
    if (t) return t === 'dark';
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function swap(c) { return (typeof c === 'string' && L2D[c]) ? L2D[c] : c; }
  function apply() {
    if (!dark()) return;
    document.querySelectorAll('.js-plotly-plot').forEach(function (gd) {
      Plotly.relayout(gd, {
        'font.color': '#c3c2b7', 'title.font.color': '#f0efec',
        'xaxis.gridcolor': '#383835', 'yaxis.gridcolor': '#383835',
        'xaxis.linecolor': '#6b6a64', 'yaxis.linecolor': '#6b6a64',
        'legend.font.color': '#c3c2b7', 'hoverlabel.bgcolor': '#232321',
        'hoverlabel.font.color': '#f0efec'
      });
      gd.data.forEach(function (tr, i) {
        const upd = {};
        if (tr.marker && tr.marker.color !== undefined) {
          upd['marker.color'] = [Array.isArray(tr.marker.color) ? tr.marker.color.map(swap) : swap(tr.marker.color)];
        }
        if (tr.line && tr.line.color) upd['line.color'] = swap(tr.line.color);
        if (tr.marker && tr.marker.line) upd['marker.line.color'] = '#1a1a19';
        Plotly.restyle(gd, upd, [i]);
      });
    });
  }
  window.addEventListener('load', apply);
})();
</script>
"""


def plotly_layout(title: str, xtitle: str = "", ytitle: str = "", height: int = 360) -> dict:
    axis = dict(gridcolor="#e2e1dc", linecolor="#a3a29c", zeroline=False, ticks="")
    return dict(
        title=dict(text=title, font=dict(size=15, color="#0b0b0b"), x=0, xanchor="left"),
        font=dict(family=FONT, size=12, color="#52514e"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=height, margin=dict(l=56, r=16, t=48, b=44),
        xaxis=dict(axis, title=xtitle), yaxis=dict(axis, title=ytitle),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, traceorder="normal"),
        hovermode="x unified", bargap=0.15, barcornerradius=4,
        hoverlabel=dict(bgcolor="#fcfcfb", font=dict(color="#0b0b0b")),
    )
