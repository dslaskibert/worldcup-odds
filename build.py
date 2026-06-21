"""
Génère docs/index.html depuis data/odds.csv.

- Heatmap : couleur HSL en échelle log10 (gamma 0.6) de la cote.
- Sparkline SVG par ligne, normalisée sur le min/max propre à chaque pays
  (la variation 4.85→7 pour la France occupe toute la hauteur).
- Colonne Δ dédiée, collée à droite de la dernière colonne : flèche + diff %.
"""
import csv
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CSV_PATH = Path("data/odds.csv")
OUT_PATH = Path("docs/index.html")
PARIS = ZoneInfo("Europe/Paris")

LOG_MIN = math.log10(4)
LOG_MAX = math.log10(2000)
GAMMA   = 0.6

SPARK_W = 72
SPARK_H = 24
SPARK_PAD = 2


def log_t(odd: float) -> float:
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


def trend_cell(values: list[float | None]) -> str:
    """Retourne le HTML de la cellule Δ (flèche + pourcentage)."""
    knowns = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(knowns) < 2:
        return '<td class="delta"></td>'
    _, prev = knowns[-2]
    _, last = knowns[-1]
    pct = (last - prev) / prev * 100
    if pct < -3:
        sym   = "↓"
        klass = "down"
        label = f"{pct:.0f}%"
    elif pct > 3:
        sym   = "↑"
        klass = "up"
        label = f"+{pct:.0f}%"
    else:
        sym   = "→"
        klass = "flat"
        label = "~"
    return (
        f'<td class="delta">'
        f'<span class="arr {klass}">{sym}</span>'
        f'<span class="dpct {klass}">{label}</span>'
        f'</td>'
    )


def sparkline(values: list[float | None]) -> str:
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return f'<svg width="{SPARK_W}" height="{SPARK_H}"></svg>'

    n  = len(values)
    lv = [math.log10(v) for _, v in pts]
    lo, hi = min(lv), max(lv)
    # Plage minimum de 0.3 unités log (≈ facteur 2×) pour ne pas
    # exagérer les micro-fluctuations type 5.5→5.6.
    span = max(hi - lo, 0.3)
    mid  = (lo + hi) / 2
    lo   = mid - span / 2
    hi   = mid + span / 2

    def x(i):
        return SPARK_PAD + (i / (n - 1)) * (SPARK_W - 2 * SPARK_PAD)

    def y(log_val):
        t = (log_val - lo) / span
        return SPARK_PAD + (1 - t) * (SPARK_H - 2 * SPARK_PAD)

    coords = [(x(i), y(math.log10(v))) for i, v in pts]

    # Courbe de Bézier lissée : passage par les midpoints entre chaque paire
    # de points, avec une courbe quadratique — aucune oscillation parasite.
    def smooth_path(cs):
        if len(cs) == 2:
            return f"M{cs[0][0]:.1f},{cs[0][1]:.1f} L{cs[1][0]:.1f},{cs[1][1]:.1f}"
        d = [f"M{cs[0][0]:.1f},{cs[0][1]:.1f}"]
        for i in range(len(cs) - 1):
            mx = (cs[i][0] + cs[i+1][0]) / 2
            my = (cs[i][1] + cs[i+1][1]) / 2
            d.append(f"Q{cs[i][0]:.1f},{cs[i][1]:.1f} {mx:.1f},{my:.1f}")
        d.append(f"L{cs[-1][0]:.1f},{cs[-1][1]:.1f}")
        return " ".join(d)

    path = smooth_path(coords)
    fill_pts  = (coords
                 + [(coords[-1][0], SPARK_H - SPARK_PAD),
                    (coords[0][0],  SPARK_H - SPARK_PAD)])
    fill_path = smooth_path(fill_pts)

    stroke = color_for(pts[-1][1])
    return (
        f'<svg width="{SPARK_W}" height="{SPARK_H}" '
        f'viewBox="0 0 {SPARK_W} {SPARK_H}">'
        f'<path d="{fill_path}" fill="{stroke}" fill-opacity="0.18" stroke="none"/>'
        f'<path d="{path}" fill="none" stroke="{stroke}" '
        f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>'
        f'</svg>'
    )


def main() -> None:
    with CSV_PATH.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows   = [r for r in reader if r[0]]

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

    def sort_key(item):
        _, values = item
        has_today = values[-1] is not None
        # Groupe 0 = encore coté aujourd'hui (trié par cote croissante).
        # Groupe 1 = plus coté du tout (éliminé / retiré), en bas, trié par
        # dernière cote connue pour garder un ordre cohérent entre eux.
        return (0 if has_today else 1, last_known(values))

    data.sort(key=sort_key)

    cells = []
    for country, values in data:
        spark = sparkline(values)
        tds   = [
            f'<th scope="row">'
            f'<span class="cname">{country}</span>'
            f'<span class="spark">{spark}</span>'
            f'</th>'
        ]
        for i, v in enumerate(values):
            is_last = i == len(values) - 1
            klass   = ' class="last"' if is_last else ""
            tds.append(f'<td{klass} style="background:{color_for(v)}">{fmt_odd(v)}</td>')
        tds.append(trend_cell(values))
        cells.append("<tr>" + "".join(tds) + "</tr>")

    head_cells = (
        ['<th scope="col" class="country-col">Pays</th>']
        + [
            f'<th scope="col"{" class=\"last\"" if i == len(dates)-1 else ""}>'
            f'{fmt_date(d)}</th>'
            for i, d in enumerate(dates)
        ]
        + ['<th scope="col" class="delta-head">Δ J-1</th>']
    )

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
    --bg: #0f1216; --fg: #e8eaed; --muted: #8a93a0;
    --border: #232830; --accent: #4a9eff;
    --green: #22c55e; --red: #ef4444;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--fg);
    font-size: 14px; line-height: 1.4;
  }}
  header {{ padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }}
  h1 {{ margin: 0 0 4px; font-size: 18px; font-weight: 600; }}
  .meta {{ color: var(--muted); font-size: 12px; }}
  .legend {{
    margin-top: 10px; display: flex; align-items: center;
    gap: 6px; flex-wrap: wrap;
  }}
  .legend-label {{ color: var(--muted); font-size: 11px; }}
  .chip {{
    display: inline-block; padding: 2px 8px; border-radius: 3px;
    color: #111; font-weight: 600; font-size: 11px;
    min-width: 28px; text-align: center;
  }}
  .scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  table {{ border-collapse: separate; border-spacing: 0; white-space: nowrap; margin: 0; }}
  th, td {{
    padding: 5px 10px; text-align: center;
    border-right: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    font-variant-numeric: tabular-nums;
  }}
  thead th {{
    background: var(--bg); font-weight: 500; color: var(--muted);
    font-size: 11px; position: sticky; top: 0; z-index: 2;
  }}
  tbody th {{
    background: var(--bg); text-align: left; font-weight: 500;
    position: sticky; left: 0; z-index: 1;
    min-width: 200px; border-right: 2px solid var(--border);
    vertical-align: middle;
  }}
  .cname {{ display: block; font-size: 13px; line-height: 1.2; }}
  .spark  {{ display: block; margin-top: 3px; }}
  thead .country-col {{ z-index: 3; left: 0; text-align: left; }}
  td {{ color: #111; font-weight: 600; min-width: 54px; font-size: 13px; }}
  .last {{ box-shadow: inset 2px 0 0 var(--accent); }}

  /* Colonne Δ */
  td.delta, th.delta-head {{
    min-width: 58px; background: var(--bg);
    border-left: 2px solid var(--border);
    position: sticky; right: 0;
  }}
  td.delta {{ display: flex; flex-direction: column; align-items: center;
              justify-content: center; gap: 1px; padding: 4px 6px; }}
  .arr      {{ font-size: 16px; font-weight: 800; line-height: 1; }}
  .dpct     {{ font-size: 10px; font-weight: 600; line-height: 1; }}
  .down     {{ color: var(--green); }}
  .up       {{ color: var(--red);   }}
  .flat     {{ color: var(--muted); }}
  th.delta-head {{ color: var(--muted); font-size: 11px; }}

  tbody tr:hover th,
  tbody tr:hover td {{ filter: brightness(1.12); }}
  footer {{ padding: 12px 16px 24px; color: var(--muted); font-size: 11px; }}
  footer a {{ color: var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>Cotes Winamax — Vainqueur Coupe du Monde 2026</h1>
  <div class="meta">Mis à jour le {now} (heure de Paris)</div>
  <div class="legend">
    <span class="legend-label">Échelle :</span>
    {legend_html}
    <span class="legend-label" style="margin-left:10px">Δ J-1 :</span>
    <span class="arr down" style="font-size:13px">↓</span>
    <span style="font-size:11px;color:var(--muted)">favori</span>
    <span class="arr up"   style="font-size:13px;margin-left:6px">↑</span>
    <span style="font-size:11px;color:var(--muted)">outsider</span>
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