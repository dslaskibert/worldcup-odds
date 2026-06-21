"""
Scrape les cotes "Vainqueur Coupe du Monde 2026" sur Winamax.

Navigation :
1. Playwright charge la SPA (Twitch et tracking bloqués).
2. Clique sur l'onglet "Compétition" puis le sous-onglet "Vainqueur (N)".
3. Clique sur "Plus de sélections" pour déplier la liste outright complète
   (Winamax n'affiche que les 2 favoris par défaut).
4. Isole la section "Vainqueur" (heading, pas le sous-onglet) et extrait
   chaque cote au pattern strict : "Pays\\nXX%\\nCote".

Format des cotes Winamax :
- Décimal : "4,75", "7,00"
- Entier : "11", "40", "200"
- Milliers : "1 000", "5 000" (espace insécable parfois)

Seuil : au moins MIN_COUNTRIES pays trouvés. Si Winamax retire des pays
éliminés, leur cellule reste vide dans le CSV (heatmap = case transparente).
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
MIN_COUNTRIES = 20

# Pour chaque pays du CSV, alias possibles affichés par Winamax.
# Ordre = priorité de recherche.
ALIASES = {
    "République de Corée": ["République de Corée", "Corée du Sud", "Corée"],
    "République d'Iran": ["République d'Iran", "Iran"],
    "États-Unis": ["États-Unis", "Etats-Unis", "USA"],
    "RD Congo": ["République Démocratique du Congo", "RD Congo", "Congo RD"],
    "Côte d'Ivoire": ["Côte d'Ivoire", "Cote d'Ivoire"],
    "Bosnie-Herzégovine": ["Bosnie-Herzégovine", "Bosnie"],
    "Cap-Vert": ["Cap-Vert", "Cap Vert"],
    "Afrique du Sud": ["Afrique du Sud"],
    "Arabie Saoudite": ["Arabie Saoudite", "Arabie saoudite"],
    "Nouvelle-Zélande": ["Nouvelle-Zélande", "Nouvelle Zélande"],
    "Tchéquie": ["République Tchèque", "Tchéquie"],
    "Équateur": ["Équateur", "Equateur"],
    "Égypte": ["Égypte", "Egypte"],
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

        # Ferme le bandeau cookies (tarteaucitron) en cliquant directement en
        # JS sur le bouton, sans passer par les vérifications de visibilité
        # de Playwright (le bandeau est souvent encore en animation d'entrée
        # au moment où Playwright essaie de cliquer, ce qui le fait échouer
        # à tort).
        try:
            clicked = page.evaluate(
                """() => {
                    const btn = document.getElementById('tarteaucitronAllAllowed');
                    if (btn) { btn.click(); return true; }
                    return false;
                }"""
            )
            print(f"✅ Bandeau cookies cliqué via JS : {clicked}")
        except Exception as e:
            print(f"⚠️  Click JS bandeau : {e}")

        # Filet de sécurité : supprime complètement le bandeau du DOM pour
        # qu'il ne puisse plus jamais intercepter de clics, peu importe son
        # état d'affichage.
        try:
            page.evaluate(
                """() => {
                    const el = document.getElementById('tarteaucitronRoot');
                    if (el) el.remove();
                }"""
            )
            print("✅ Bandeau cookies supprimé du DOM")
        except Exception as e:
            print(f"⚠️  Suppression DOM bandeau : {e}")

        page.wait_for_timeout(500)

        # 1. Onglet "Compétition"
        try:
            clicked = page.evaluate(
                """() => {
                    // Cherche un conteneur compact qui contient à la fois
                    // "Matchs" et "Compétition" -- c'est la barre d'onglets
                    // de la Coupe du Monde, pas un autre menu Winamax qui
                    // contient le mot "Compétition" tout seul.
                    const all = document.querySelectorAll('div, ul, nav');
                    for (const container of all) {
                        const txt = container.textContent || '';
                        if (txt.length > 0 && txt.length < 400
                            && txt.includes('Matchs')
                            && txt.includes('Compétition')) {
                            const target = [...container.querySelectorAll('*')]
                                .find(el => el.textContent.trim() === 'Compétition');
                            if (target) {
                                (target.closest('button, a, [role="tab"]') || target).click();
                                return true;
                            }
                        }
                    }
                    return false;
                }"""
            )
            print(f"✅ Onglet 'Compétition' cliqué via JS : {clicked}")
        except Exception as e:
            print(f"⚠️  Compétition : {e}")
        page.wait_for_timeout(2500)

        try:
            clicked = page.evaluate(
                """() => {
                    // Cherche la barre de sous-onglets qui contient Vainqueur
                    // ET Buteurs côte à côte -- pas le heading de section
                    // "Vainqueur" plus bas dans la page.
                    const all = document.querySelectorAll('div, ul, nav');
                    for (const container of all) {
                        const txt = container.textContent || '';
                        if (txt.length > 0 && txt.length < 600
                            && txt.includes('Vainqueur')
                            && txt.includes('Buteurs')) {
                            const target = [...container.querySelectorAll('*')]
                                .find(el => {
                                    const t = el.textContent.trim();
                                    return t === 'Vainqueur'
                                        || /^Vainqueur\\s*\\(\\d+\\)$/.test(t);
                                });
                            if (target) {
                                (target.closest('button, a, [role="tab"]') || target).click();
                                return true;
                            }
                        }
                    }
                    return false;
                }"""
            )
            print(f"✅ Sous-onglet 'Vainqueur' cliqué via JS : {clicked}")
        except Exception as e:
            print(f"⚠️  Vainqueur : {e}")
        page.wait_for_timeout(2500)

        # Click "Plus de sélections" puis attend la stabilité du DOM
        # (le count peut monter ou descendre, on attend juste que ça arrête
        # de bouger pendant 1s).
        try:
            clicked = page.evaluate(
                """() => {
                    const nodes = document.querySelectorAll('span, div, button, a');
                    for (const n of nodes) {
                        if (n.textContent.trim() === 'Plus de sélections') {
                            n.click();  // clic direct, pas de closest()
                            return true;
                        }
                    }
                    return false;
                }"""
            )
            print(f"✅ 'Plus de sélections' cliqué via JS : {clicked}")
        except Exception as e:
            print(f"⚠️  'Plus de sélections' : {e}")
        page.wait_for_timeout(1000)

        # Vérification : si la section Vainqueur ne s'est pas vraiment
        # étendue (toujours 2 pays seulement), on retente une fois avec un
        # second clic -- certains événements React ratent le premier essai
        # si le DOM était encore en train de se stabiliser.
        count_pct = page.evaluate(
            "() => (document.body.innerText.match(/%/g) || []).length"
        )
        if count_pct < 15:
            print(f"⚠️  Seulement {count_pct} '%' trouvés, second essai de clic")
            page.evaluate(
                """() => {
                    const nodes = document.querySelectorAll('span, div, button, a');
                    for (const n of nodes) {
                        if (n.textContent.trim() === 'Plus de sélections') {
                            n.click();
                            return true;
                        }
                    }
                    return false;
                }"""
            )
            page.wait_for_timeout(1500)

        last_len = -1
        stable = 0
        for _ in range(30):
            page.wait_for_timeout(500)
            cur = page.evaluate("() => document.body.innerText.length")
            if cur == last_len:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
                last_len = cur

        text = page.evaluate("() => document.body.innerText")
        DEBUG_DIR.mkdir(exist_ok=True)
        (DEBUG_DIR / "page.txt").write_text(text, encoding="utf-8")
        page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)
        browser.close()
        return text


def scope_to_outright(text: str) -> str:
    for m in re.finditer(r"\bVainqueur\b", text):
        before = text[max(0, m.start() - 25):m.start()]
        after = text[m.end():m.end() + 5]
        if after.lstrip().startswith("("):
            continue
        if re.search(r"Groupe\s+[A-L]\s*-\s*$", before):
            continue
        if "Double chance" in before:
            continue
        rest = text[m.start():]
        end = re.search(
            r"\n\s*(Double chance Vainqueur"
            r"|Moins de sélections"
            r"|Groupe\s+[A-L]\s*-\s*(Vainqueur|Qualification)"
            r"|Buteurs\s*\(\d+\)"
            r"|Top\s*X\s*\(\d+\))",
            rest,
        )
        return rest[: end.start()] if end else rest
    return text


def extract_odd(text: str, country: str) -> float | None:
    """
    Format Winamax dans la section Vainqueur :
        Pays
        XX%
        Cote      ← entier (40), décimal (4,75), ou entier+espace (1 000)

    Le pattern strict <Pays>\\n<pct>%\\n<cote> élimine toute ambiguïté avec
    les pourcentages ou nombres parasites.
    """
    names = ALIASES.get(country, [country])
    cote_re = r"(\d{1,3}(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?)"
    for name in names:
        pattern = re.compile(
            r"\b" + re.escape(name) + r"\b\s*\n"
            r"\s*\d+\s*%\s*\n"
            r"(?:\s*\d{1,4}\s*\n)?"   # badge parieurs optionnel (ex: "31\n")
            r"\s*" + cote_re,
            re.IGNORECASE,
        )
        m = pattern.search(text)
        if m:
            raw = (
                m.group(1)
                .replace("\u00a0", "")
                .replace(" ", "")
                .replace(",", ".")
            )
            try:
                value = float(raw)
            except ValueError:
                continue
            if 1.01 <= value <= 99999:
                return value
    return None


def update_csv(odds: dict[str, float], today: str) -> tuple[int, int]:
    with CSV_PATH.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header, *body = rows

    if today not in header:
        header.append(today)

    # Normalise toutes les lignes à la longueur du header. Robuste contre
    # un CSV dont certaines lignes ont moins de cellules (héritage de
    # nettoyage manuel ou de runs précédents).
    n = len(header)
    for r in body:
        while len(r) < n:
            r.append("")

    col = header.index(today)

    # Reset de la colonne du jour avant écriture.
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
        print(f"❌ Moins de {MIN_COUNTRIES} pays, abandon (CSV non modifié).")
        print(f"   Artefacts debug dans {DEBUG_DIR}/")
        return 1

    today = datetime.now(PARIS).strftime("%Y-%m-%d")
    filled, total = update_csv(odds, today)
    print(f"💾 CSV mis à jour : {filled}/{total} cellules pour {today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())