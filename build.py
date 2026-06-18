"""
Génère docs/index.html depuis data/odds.csv.

- Heatmap : couleur HSL en échelle log10 de la cote.
- Lignes triées par cote actuelle (favoris en haut).
- Colonne pays sticky à gauche, dernière colonne mise en évidence.
- Légère animation au survol pour repérer le pays.
- Aucune dépendance JS, ~10 Ko de HTML autonome.
"""
import csv
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CSV_PATH = Path("data/odds.csv")
OUT_PATH = Path("docs/index.html")
PARIS = ZoneInfo("Europe/Paris")

# Bornes fixes de l'échelle log. Cotes <= 1 = vert pur, >= 500 = rouge pur.
# Tout pays encore en course tombe dans cette plage ; les pays éliminés (cotes
# qui explosent à 5000+) clip simplement sur la borne rouge.
LOG_MIN = math.log10(1)
LOG_MAX = math.log10(500)


def color_for(odd: float | None) -> str:
    if odd is None:
        return "transparent"
    t = (math.log10(odd) - LOG_MIN) / (LOG_MAX - LOG_MIN)
    t = max(0.0, min(1.0, t))
    hue = 120 * (1 - t)  # 120 = vert, 0 = rouge, passe par 60 = jaune
    return f"hsl({hue:.0f} 82% 62%)"


def fmt_odd(odd: float | None) -> str:
    if odd is None:
        return ""
    return f"{odd:.0f}" if odd >= 100 else f"{odd:.2f}".rstrip("0").rstrip(".")


def fmt_date(iso: str) -> str:
    dt = datetime.strptime(iso, "%Y-%m-%d")
    return dt.strftime("%d/%m")


def main() -> None:
    with CSV_PATH.open(encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [r for r in reader if r[0]]

    dates = header[1:]

    # Parse en float (vide -> None)
    data = []
    for r in rows:
        values = [float(v) if v else None for v in r[1:]]
        data.append((r[0], values))

    # Tri par cote du dernier jour disponible (favoris en haut).
    # Si pas de cote pour le dernier jour, on retombe sur le dernier connu.
    def last_known(values: list[float | None]) -> float:
        for v in reversed(values):
            if v is not None:
                return v
        return float("inf")

    data.sort(key=lambda x: last_known(x[1]))

    # Génère le HTML
    cells = []
    for country, values in data:
        tds = [f'<th scope="row">{country}</th>']
        for i, v in enumerate(values):
            is_last = i == len(values) - 1
            klass = " class=\"last\"" if is_last else ""
            bg = color_for(v)
            tds.append(
                f'<td{klass} style="background:{bg}">{fmt_odd(v)}</td>'
            )
        cells.append("<tr>" + "".join(tds) + "</tr>")

    head_cells = ['<th scope="col" class="country-col">Pays</th>'] + [
        f'<th scope="col"{" class=\"last\"" if i == len(dates) - 1 else ""}>{fmt_date(d)}</th>'
        for i, d in enumerate(dates)
    ]

    now = datetime.now(PARIS).strftime("%d/%m/%Y à %H:%M")

    # Légende : 5 paliers représentatifs
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
  h1 {{
    margin: 0 0 4px;
    font-size: 18px;
    font-weight: 600;
  }}
  .meta {{
    color: var(--muted);
    font-size: 12px;
  }}
  .legend {{
    margin-top: 10px;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }}
  .legend-label {{
    color: var(--muted);
    font-size: 11px;
  }}
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
  .scroll {{
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }}
  table {{
    border-collapse: separate;
    border-spacing: 0;
    white-space: nowrap;
    margin: 0;
  }}
  th, td {{
    padding: 6px 10px;
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
    min-width: 160px;
    border-right: 2px solid var(--border);
  }}
  thead .country-col {{
    z-index: 3;
    left: 0;
    text-align: left;
  }}
  td {{
    color: #111;
    font-weight: 600;
    min-width: 52px;
  }}
  .last {{
    box-shadow: inset 2px 0 0 var(--accent);
  }}
  tbody tr:hover th,
  tbody tr:hover td {{
    filter: brightness(1.1);
  }}
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
