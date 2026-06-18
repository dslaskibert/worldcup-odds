"""
Scrape les cotes "Vainqueur Coupe du Monde 2026" sur Winamax.

Navigation :
1. Playwright charge la SPA (Twitch et tracking bloqués).
2. Clique sur l'onglet "Compétition" puis le sous-onglet "Vainqueur (N)".
3. Clique sur "Plus de sélections" pour déplier la liste outright complète
   (Winamax n'affiche que les 2 favoris par défaut).
4. Isole la section "Vainqueur" (heading, pas le sous-onglet) et extrait
   chaque cote au format X,YY.

Seuil : au moins MIN_COUNTRIES pays trouvés. Winamax ne propose pas toujours
de cote outright pour les 48 pays (certains sont jugés sans chance ou en
cours d'élimination) — les cellules manquantes restent vides dans le CSV.
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

# Si on trouve moins que ça, c'est qu'on s'est planté de section.
MIN_COUNTRIES = 20

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
    "Tchéquie": ["Tchéquie", "République Tchèque"],
}


def load_countries() -> list[str]:
    with CSV_PATH.open(encoding="utf-8") as f:
        return [row["country"] for row in csv.DictReader(f)]


def fetch_page_text() -> str:
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

        BLOCK = ("twitch.tv", "ttvnw.net", "sentry.io", "doubleclick.net",
                 "googletagmanager.com", "google-analytics.com")
        page.route(
            "**/*",
            lambda route: route.abort()
            if any(d in route.request.url for d in BLOCK)
            else route.continue_(),
        )

        page.goto(URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3000)

        # 1. Onglet "Compétition"
        try:
            page.get_by_text("Compétition", exact=True).first.click(timeout=10_000)
            print("✅ Onglet 'Compétition' cliqué")
        except Exception as e:
            print(f"⚠️  Compétition : {e}")
        page.wait_for_timeout(1500)

        # 2. Sous-onglet "Vainqueur (N)"
        try:
            page.get_by_text(
                re.compile(r"^Vainqueur\s*\(\d+\)")
            ).first.click(timeout=10_000)
            print("✅ Sous-onglet 'Vainqueur' cliqué")
        except Exception as e:
            print(f"⚠️  Vainqueur : {e}")
        page.wait_for_timeout(2000)

        # 3. Click "Plus de sélections" pour déplier la liste outright.
        # Le premier dans le DOM est celui du marché "Vainqueur" (premier
        # marché affiché).
        def count_odds() -> int:
            return page.evaluate(
                "() => (document.body.innerText.match(/\\d+,\\d{2}/g) || []).length"
            )

        before = count_odds()
        try:
            page.get_by_text("Plus de sélections").first.click(timeout=10_000)
            print("✅ 'Plus de sélections' cliqué")
            # Attend que le nombre de cotes augmente significativement.
            for _ in range(20):
                page.wait_for_timeout(500)
                if count_odds() > before + 5:
                    break
            print(f"   Cotes visibles : {before} → {count_odds()}")
        except Exception as e:
            print(f"⚠️  'Plus de sélections' : {e}")

        page.wait_for_timeout(1500)

        text = page.evaluate("() => document.body.innerText")
        DEBUG_DIR.mkdir(exist_ok=True)
        (DEBUG_DIR / "page.txt").write_text(text, encoding="utf-8")
        page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)
        browser.close()
        return text


def scope_to_outright(text: str) -> str:
    """
    Isole le bloc de la section "Vainqueur" (heading, pas le sous-onglet).

    Sur Winamax, "Vainqueur" apparaît plusieurs fois :
    - sous-onglet : "Vainqueur\\n(28)"
    - heading de section : "Vainqueur\\nFrance\\n34%\\n4,75\\n..."
    - autres marchés : "Double chance Vainqueur", "Groupe A - Vainqueur" etc.

    On veut le HEADING de la section principale : c'est l'occurrence isolée
    (pas précédée de "Groupe X -" ni "Double chance", pas suivie de "(").
    """
    for m in re.finditer(r"\bVainqueur\b", text):
        before = text[max(0, m.start() - 25):m.start()]
        after = text[m.end():m.end() + 5]
        if after.lstrip().startswith("("):
            continue  # sous-onglet
        if re.search(r"Groupe\s+[A-L]\s*-\s*$", before):
            continue  # marché "Groupe X - Vainqueur"
        if "Double chance" in before:
            continue  # marché "Double chance Vainqueur"
        # Bingo : c'est le heading de la section principale.
        rest = text[m.start():]
        end = re.search(
            r"\n\s*(Double chance Vainqueur"
            r"|Groupe\s+[A-L]\s*-\s*(Vainqueur|Qualification)"
            r"|Buteurs\s*\(\d+\)"
            r"|Top\s*X\s*\(\d+\))",
            rest,
        )
        return rest[: end.start()] if end else rest
    return text


def extract_odd(text: str, country: str) -> float | None:
    """
    Cherche la cote outright. Format attendu sur la page Winamax :
        Pays
        XX%
        Y,YY
    Donc on cherche le nom de pays suivi (dans 200 chars) d'un nombre
    avec exactement 2 décimales. Exclut les pourcentages (entiers nus).
    """
    names = ALIASES.get(country, [country])
    odds_re = r"(\d{1,5}[.,]\d{2})"
    for name in names:
        pattern = re.compile(
            r"\b" + re.escape(name) + r"\b[\s\S]{0,200}?" + odds_re,
            re.IGNORECASE,
        )
        m = pattern.search(text)
        if m:
            value = float(m.group(1).replace(",", "."))
            if 1.01 <= value <= 99999:
                return value
    return None


def update_csv(odds: dict[str, float], today: str) -> tuple[int, int]:
    with CSV_PATH.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header, *body = rows

    if today in header:
        col = header.index(today)
    else:
        header.append(today)
        col = len(header) - 1
        for r in body:
            r.append("")

    for r in body:
        r[col] = ""  # reset

    filled = 0
    for r in body:
        if r[0] in odds:
            r[col] = str(odds[r[0]])
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
    outright = scope_to_outright(text)
    print(
        f"📄 {len(text)} chars total → "
        f"{len(outright)} chars dans la section Vainqueur"
    )
    DEBUG_DIR.mkdir(exist_ok=True)
    (DEBUG_DIR / "outright.txt").write_text(outright, encoding="utf-8")

    odds: dict[str, float] = {}
    missing: list[str] = []
    for c in countries:
        v = extract_odd(outright, c)
        if v is None:
            missing.append(c)
        else:
            odds[c] = v

    print(f"✅ {len(odds)}/{len(countries)} pays trouvés")
    if missing:
        print(f"ℹ️  Sans cote sur Winamax aujourd'hui ({len(missing)}) : "
              f"{', '.join(missing)}")

    if len(odds) < MIN_COUNTRIES:
        print(f"❌ Moins de {MIN_COUNTRIES} pays trouvés, abandon "
              "(probable bug d'extraction, CSV non modifié).")
        print(f"   Artefacts debug dans {DEBUG_DIR}/")
        return 1

    today = datetime.now(PARIS).strftime("%Y-%m-%d")
    filled, total = update_csv(odds, today)
    print(f"💾 CSV mis à jour : {filled}/{total} cellules pour {today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())