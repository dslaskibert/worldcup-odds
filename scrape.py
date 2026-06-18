"""
Scrape les cotes "Vainqueur Coupe du Monde 2026" sur Winamax.

Étapes :
1. Playwright charge la SPA (Twitch et tracking bloqués).
2. Clique sur l'onglet "Compétition" puis le sous-onglet "Vainqueur (N)".
3. Attend que la liste des cotes outright soit rendue.
4. Extrait le texte, isole la section "Vainqueur" et cherche chaque pays.
5. Met à jour data/odds.csv en ajoutant (ou écrasant) la colonne du jour.

Si <90% des pays sont trouvés, on échoue bruyamment (artefacts debug
sauvegardés). Évite d'écraser le CSV avec des données partielles.
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
    with CSV_PATH.open(encoding="utf-8") as f:
        return [row["country"] for row in csv.DictReader(f)]


def fetch_page_text() -> str:
    """Charge la page, navigue jusqu'à l'onglet Vainqueur, renvoie le texte."""
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
        page.wait_for_timeout(3000)  # laisse le shell se construire

        # 1. Onglet "Compétition"
        try:
            page.get_by_text("Compétition", exact=True).first.click(timeout=10_000)
            print("✅ Onglet 'Compétition' cliqué")
        except Exception as e:
            print(f"⚠️  Impossible de cliquer 'Compétition' : {e}")

        page.wait_for_timeout(1500)

        # 2. Sous-onglet "Vainqueur (N)"
        try:
            page.get_by_text(
                re.compile(r"^Vainqueur\s*\(\d+\)")
            ).first.click(timeout=10_000)
            print("✅ Sous-onglet 'Vainqueur' cliqué")
        except Exception as e:
            print(f"⚠️  Impossible de cliquer 'Vainqueur' : {e}")

        # 3. Attend que la liste outright soit peuplée :
        #    >= 20 cotes au format X,YY dans le texte de la page.
        try:
            page.wait_for_function(
                "() => (document.body.innerText.match(/\\d+,\\d{2}/g) || []).length >= 20",
                timeout=20_000,
            )
            print("✅ Liste des cotes chargée")
        except Exception as e:
            print(f"⚠️  Timeout d'attente des cotes : {e}")

        page.wait_for_timeout(1500)  # rendu final

        text = page.evaluate("() => document.body.innerText")

        DEBUG_DIR.mkdir(exist_ok=True)
        (DEBUG_DIR / "page.txt").write_text(text, encoding="utf-8")
        page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)

        browser.close()
        return text


def scope_to_outright(text: str) -> str:
    """
    Restreint au bloc qui suit le sous-onglet 'Vainqueur (N)'.
    Coupe avant les sous-onglets suivants (Buteurs, Top X, Stats).
    """
    m = re.search(r"Vainqueur\s*\(\d+\)", text)
    if not m:
        return text
    rest = text[m.start():]
    end = re.search(
        r"\n\s*(Buteurs\s*\(\d+\)|Top\s*X\s*\(\d+\)|Stats\s+joueurs|Stats\s+équipes)",
        rest,
    )
    return rest[: end.start()] if end else rest


def extract_odd(text: str, country: str) -> float | None:
    """
    Cherche la cote outright pour `country`. Les cotes Winamax outright sont
    TOUJOURS affichées avec exactement 2 décimales (ex : 4,75 — 120,00 —
    5000,00). On exige ce format pour exclure les pourcentages (34%) et les
    IDs internes (5630, 2287, etc.) qui apparaissent comme entiers nus.
    """
    names = ALIASES.get(country, [country])
    odds_re = r"(\d{1,5}[.,]\d{2})"
    for name in names:
        # Entre le nom du pays et sa cote outright : drapeau, %, barre.
        # Fenêtre de 200 caractères pour rester local.
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
    """Ajoute (ou écrase) la colonne `today` dans le CSV."""
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

    # Reset la colonne du jour avant de réécrire, pour qu'un rerun parte propre.
    for r in body:
        r[col] = ""

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

    odds = {}
    missing = []
    for c in countries:
        v = extract_odd(outright, c)
        if v is None:
            missing.append(c)
        else:
            odds[c] = v

    coverage = len(odds) / len(countries)
    print(f"✅ {len(odds)}/{len(countries)} pays trouvés ({coverage:.0%})")
    if missing:
        print(f"⚠️  Manquants : {', '.join(missing)}")

    if coverage < 0.9:
        print("❌ Couverture < 90 %, abandon (CSV non modifié).")
        print(f"   Artefacts debug dans {DEBUG_DIR}/")
        return 1

    today = datetime.now(PARIS).strftime("%Y-%m-%d")
    filled, total = update_csv(odds, today)
    print(f"💾 CSV mis à jour : {filled}/{total} cellules pour {today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
    