"""
Génère docs/index.html depuis data/odds.csv.

- Heatmap : couleur HSL en échelle log10 (gamma 0.6) de la cote.
- Flèche de tendance J vs J-1 dans la dernière cellule.
- Sparkline SVG inline par ligne (courbe log de la cote sur toute la période).
- Lignes triées par cote actuelle (favoris en haut).
- Colonne pays + sparkline stickies, dernière colonne mise en évidence.
"""
import csv
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CSV_PATH = Path("data/odds.csv")
OUT_PATH = Path("docs/index.html")
PARIS = ZoneInfo("Europe/Paris")

LOG_MIN = math.log10(2)
LOG_MAX = math.log10(2000)
GAMMA = 0.6

SPARK_W = 72
SPARK_H = 22
SPARK_PAD = 2


def log_t(odd: float) -> float:
    """Valeur normalisée [0,1] en log-gamma pour la heatmap et les sparklines."""
    t = (math.log10(odd) - LOG_MIN) / (LOG_MAX - LOG_MIN)
    return max(0.0, min(1.0, t)) ** GAMMA


def color_for(odd: float | None) -> str:
    if odd is None:
        return "transparent"
    hue = 120 * (1 - log_t(odd))
    return f"hsl({hue:.0f} 82% 62%)"


def fmt_odd(odd: float | None) -> str:
    if odd is None:
        return ""
    return f"{odd:.0f}" if odd >= 100 else f"{odd:.2f}".rstrip("0").rstrip(".")


def fmt_date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m")


def trend_arrow(values: list[float | None]) -> str:
    """↓ favorable (cote baisse), ↑ défavorable, → stable, vide si données insuf."""
    knowns = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(knowns) < 2:
        return ""
    _, prev = knowns[-2]
    _, last = knowns[-1]
    ratio = last / prev
    if ratio < 0.97:
        return '<span class="arr down" title="Cote en baisse (favori)">↓</span>'
    if ratio > 1.03:
        return '<span class="arr up" title="Cote en hausse">↑</span>'
    return '<span class="arr flat" title="Stable">→</span>'


def sparkline(values: list[float | None]) -> str:
    """SVG inline représentant la courbe log de la cote dans le temps."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return '<svg width="{}" height="{}"></svg>'.format(SPARK_W, SPARK_H)

    n = len(values)
    # X : position proportionnelle à l'index dans la timeline complète
    def x(i):
        return SPARK_PAD + (i / (n - 1)) * (SPARK_W - 2 * SPARK_PAD)

    # Y : haut = favorable (cote basse), bas = défavorable (cote haute)
    def y(v):
        t = log_t(v)
        return SPARK_PAD + (1 - t) * (SPARK_H - 2 * SPARK_PAD)

    coords = [(x(i), y(v)) for i, v in pts]
    path = "M " + " L ".join(f"{cx:.1f},{cy:.1f}" for cx, cy in coords)

    # Couleur de la sparkline = couleur du dernier point connu
    last_v = pts[-1][1]
    stroke = color_for(last_v)

    # Aire sous la courbe pour le remplissage
    fill_pts = coords + [(coords[-1][0], SPARK_H - SPARK_PAD), (coords[0][0], SPARK_H - SPARK_PAD)]
    fill_path = "M " + " L ".join(f"{cx:.1f},{cy:.1f}" for cx, cy in fill_pts) + " Z"

    return (
        f'<svg width="{SPARK_W}" height="{SPARK_H}" viewBox="0 0 {SPARK_W} {SPARK_H}">'
        f'<path d="{fill_path}" fill="{stroke}" fill-opacity="0.15" stroke="none"/>'
        f'<path d="{path}" fill="none" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'</svg>'
    )


def main() -> None:
    with CSV_PATH.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [r for r in reader if r[0]]

    dates = header[1:]

    data = []
    for r in rows:
        values = [float(v) if v else None for v in r[1:]]
        data.append((r[0], values))

    def last_known(values):
        for v in reversed(values):
            if v is not None:
                return v
        return float("inf")

    data.sort(key=lambda x: last_known(x[1]))

    cells = []
    for country, values in data:
        spark = sparkline(values)
        arrow = trend_arrow(values)
        tds = [
            f'<th scope="row"><span class="cname">{country}</span>'
            f'<span class="spark">{spark}</span></th>'
        ]
        for i, v in enumerate(values):
            is_last = i == len(values) - 1
            klass = ' class="last"' if is_last else ""
            bg = color_for(v)
            inner = fmt_odd(v)
            if is_last and arrow:
                inner = f'{inner}<br>{arrow}'
            tds.append(f'<td{klass} style="background:{bg}">{inner}</td>')
        cells.append("<tr>" + "".join(tds) + "</tr>")

    head_cells = ['<th scope="col" class="country-col">Pays</th>'] + [
        f'<th scope="col"{" class=\"last\"" if i == len(dates) - 1 else ""}>{fmt_date(d)}</th>'
        for i, d in enumerate(dates)
    ]

    now = datetime.now(PARIS).strftime("%d/%m/%Y à %H:%M")

    legend_values = [2, 5, 10, 50, 500, 5000]
    legend_html = "".join(
        f'<span class="chip" style="background:{color_for(v)}">{v}</span>'
        for v in legend_values
    )

    html = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cotes Winamax — Coupe du Monde 2026</title>
<style>
  :root {{
    --bg: #0f1216;
    --fg: #e8eaed;
    --muted: #8a93a0;
    --border: #232830;
    --accent: #4a9eff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg);
    color: var(--fg);
    font-size: 14px;
    line-height: 1.4;
  }}
  header {{
    padding: 20px 16px 12px;
    border-bottom: 1px solid var(--border);
  }}
  h1 {{ margin: 0 0 4px; font-size: 18px; font-weight: 600; }}
  .meta {{ color: var(--muted); font-size: 12px; }}
  .legend {{
    margin-top: 10px;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }}
  .legend-label {{ color: var(--muted); font-size: 11px; }}
  .chip {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    color: #111;
    font-weight: 600;
    font-size: 11px;
    min-width: 28px;
    text-align: center;
  }}
  .scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  table {{
    border-collapse: separate;
    border-spacing: 0;
    white-space: nowrap;
    margin: 0;
  }}
  th, td {{
    padding: 5px 10px;
    text-align: center;
    border-right: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    font-variant-numeric: tabular-nums;
  }}
  thead th {{
    background: var(--bg);
    font-weight: 500;
    color: var(--muted);
    font-size: 11px;
    position: sticky;
    top: 0;
    z-index: 2;
  }}
  tbody th {{
    background: var(--bg);
    text-align: left;
    font-weight: 500;
    position: sticky;
    left: 0;
    z-index: 1;
    min-width: 200px;
    border-right: 2px solid var(--border);
    vertical-align: middle;
  }}
  .cname {{
    display: block;
    font-size: 13px;
    line-height: 1.2;
  }}
  .spark {{
    display: block;
    margin-top: 2px;
    opacity: 0.9;
  }}
  thead .country-col {{ z-index: 3; left: 0; text-align: left; }}
  td {{
    color: #111;
    font-weight: 600;
    min-width: 54px;
    font-size: 13px;
    line-height: 1.1;
  }}
  .last {{ box-shadow: inset 2px 0 0 var(--accent); }}
  /* Flèches de tendance */
  .arr {{ display: block; font-size: 11px; font-weight: 700; line-height: 1; }}
  .arr.down {{ color: #22c55e; }}   /* vert = favori, cote baisse */
  .arr.up   {{ color: #ef4444; }}   /* rouge = cote monte */
  .arr.flat {{ color: var(--muted); }}
  tbody tr:hover th,
  tbody tr:hover td {{ filter: brightness(1.12); }}
  footer {{
    padding: 12px 16px 24px;
    color: var(--muted);
    font-size: 11px;
  }}
  footer a {{ color: var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>Cotes Winamax — Vainqueur Coupe du Monde 2026</h1>
  <div class="meta">Mis à jour le {now} (heure de Paris)</div>
  <div class="legend">
    <span class="legend-label">Échelle (log) :</span>
    {legend_html}
    <span class="legend-label" style="margin-left:12px">Tendance J-1 :</span>
    <span class="arr down" style="font-size:13px">↓</span><span style="font-size:11px;color:var(--muted)">favori</span>
    <span class="arr up" style="font-size:13px;margin-left:8px">↑</span><span style="font-size:11px;color:var(--muted)">outsider</span>
  </div>
</header>
<div class="scroll">
<table>
<thead><tr>{"".join(head_cells)}</tr></thead>
<tbody>
{chr(10).join(cells)}
</tbody>
</table>
</div>
<footer>
  Source : <a href="https://www.winamax.fr/paris-sportifs/sports/1/4/900001750">winamax.fr</a> ·
  Mise à jour quotidienne automatique à 9h ·
  Données ouvertes : <a href="https://github.com/dslaskibert/worldcup-odds/blob/main/data/odds.csv">odds.csv</a>
</footer>
</body>
</html>
"""
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"✅ Page générée : {OUT_PATH} ({len(html)} caractères)")


if __name__ == "__main__":
    main()