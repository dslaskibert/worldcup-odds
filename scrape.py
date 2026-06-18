"""
Scrape les cotes "Vainqueur Coupe du Monde 2026" sur Winamax.

Stratégie :
- Playwright headless charge la SPA Winamax (les cotes sont rendues en JS).
- On extrait tout le texte de la page.
- Pour chaque pays connu, on cherche la première occurrence suivie d'un nombre
  décimal (la cote). Insensible aux changements de classes CSS.
- On met à jour data/odds.csv en ajoutant une colonne pour aujourd'hui.

Si <90% des pays sont trouvés, on échoue bruyamment (artifact debug
sauvegardé). Évite d'écraser le CSV avec des données partielles.
"""
import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

URL = "https://www.winamax.fr/paris-sportifs/sports/1/4/900001750"
CSV_PATH = Path("data/odds.csv")
DEBUG_DIR = Path("debug")
PARIS = ZoneInfo("Europe/Paris")

# Certains noms apparaissent ailleurs sur la page (matchs en cours, etc.).
# Pour rester robustes, on liste des alias possibles. Le premier qui matche
# avec une cote plausible (>= 1.01) gagne.
ALIASES = {
    "République de Corée": ["République de Corée", "Corée du Sud", "Corée"],
    "République d'Iran": ["République d'Iran", "Iran"],
    "États-Unis": ["États-Unis", "USA", "Etats-Unis"],
    "RD Congo": ["RD Congo", "République Démocratique du Congo", "Congo RD"],
    "Côte d'Ivoire": ["Côte d'Ivoire", "Cote d'Ivoire"],
    "Bosnie-Herzégovine": ["Bosnie-Herzégovine", "Bosnie"],
    "Cap-Vert": ["Cap-Vert", "Cap Vert"],
    "Afrique du Sud": ["Afrique du Sud"],
    "Arabie Saoudite": ["Arabie Saoudite", "Arabie saoudite"],
    "Nouvelle-Zélande": ["Nouvelle-Zélande", "Nouvelle Zélande"],
}


def load_countries() -> list[str]:
    """Lit la liste des pays depuis le CSV existant (ordre conservé)."""
    with CSV_PATH.open(encoding="utf-8") as f:
        return [row["country"] for row in csv.DictReader(f)]


def fetch_page_text() -> str:
    """Charge la page Winamax et renvoie tout le texte rendu."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="fr-FR",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        # Bloque les ressources lourdes/inutiles : player Twitch live (qui
        # fait que networkidle ne se déclenche jamais), tracking, pubs.
        BLOCK = ("twitch.tv", "ttvnw.net", "sentry.io", "doubleclick.net",
                 "googletagmanager.com", "google-analytics.com")
        page.route(
            "**/*",
            lambda route: route.abort()
            if any(d in route.request.url for d in BLOCK)
            else route.continue_(),
        )

        page.goto(URL, wait_until="domcontentloaded", timeout=30_000)

        # Attend que des cotes apparaissent vraiment dans le DOM.
        try:
            page.wait_for_function(
                "() => /Espagne|France|Brésil/.test(document.body.innerText) "
                "&& /\\d+[.,]\\d{2}/.test(document.body.innerText)",
                timeout=30_000,
            )
        except Exception as e:
            print(f"⚠️  Timeout d'attente du contenu : {e}")

        # Petit délai supplémentaire pour les rendus JS tardifs.
        page.wait_for_timeout(2000)

        text = page.evaluate("() => document.body.innerText")

        DEBUG_DIR.mkdir(exist_ok=True)
        (DEBUG_DIR / "page.txt").write_text(text, encoding="utf-8")
        page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)

        browser.close()
        return text


def extract_odd(text: str, country: str) -> float | None:
    """Cherche la cote associée au pays dans le texte."""
    names = ALIASES.get(country, [country])
    # Une cote est un nombre décimal entre 1.01 et 99999 avec . ou ,
    odds_re = r"(\d{1,5}(?:[.,]\d{1,2})?)"
    for name in names:
        # Le pays peut être suivi de la cote sur la même ligne ou la suivante.
        pattern = re.compile(
            r"\b" + re.escape(name) + r"\b\s*\n?\s*" + odds_re,
            re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            value = float(m.group(1).replace(",", "."))
            if 1.01 <= value <= 99999:
                return value
    return None


def update_csv(odds: dict[str, float], today: str) -> tuple[int, int]:
    """Ajoute une colonne au CSV pour `today`. Renvoie (ajoutés, remplacés)."""
    with CSV_PATH.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header, *body = rows

    if today in header:
        col = header.index(today)
        action = "remplacés"
    else:
        header.append(today)
        col = len(header) - 1
        for r in body:
            r.append("")
        action = "ajoutés"

    filled = 0
    for r in body:
        country = r[0]
        if country in odds:
            r[col] = str(odds[country])
            filled += 1

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(body)

    return filled, len(body)


def main() -> int:
    countries = load_countries()
    print(f"📋 {len(countries)} pays à récupérer")

    text = fetch_page_text()
    print(f"📄 {len(text)} caractères extraits de la page")

    odds = {}
    missing = []
    for c in countries:
        v = extract_odd(text, c)
        if v is None:
            missing.append(c)
        else:
            odds[c] = v

    coverage = len(odds) / len(countries)
    print(f"✅ {len(odds)}/{len(countries)} pays trouvés ({coverage:.0%})")
    if missing:
        print(f"⚠️  Manquants : {', '.join(missing)}")

    if coverage < 0.9:
        print("❌ Couverture < 90%, abandon (CSV non modifié).")
        print(f"   Artefacts debug dans {DEBUG_DIR}/")
        return 1

    today = datetime.now(PARIS).strftime("%Y-%m-%d")
    filled, total = update_csv(odds, today)
    print(f"💾 CSV mis à jour : {filled}/{total} cellules pour {today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
