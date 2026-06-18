# worldcup-odds

Heatmap quotidienne des cotes Winamax pour le vainqueur de la Coupe du Monde 2026.

👉 **Page publique :** https://dslaskibert.github.io/worldcup-odds/

## Comment ça marche

1. Chaque jour à **9h Paris**, GitHub Actions lance `scrape.py`.
2. Le script charge la page Winamax dans un Chromium headless (Playwright) et
   extrait les cotes des 48 pays qualifiés.
3. Une colonne du jour est ajoutée à `data/odds.csv`.
4. `build.py` régénère `docs/index.html` avec une heatmap en échelle **log10**
   (vert = favori, rouge = outsider).
5. L'Action commit `data/odds.csv` + `docs/index.html` sur `main`.
6. GitHub Pages republie la page automatiquement.

## Setup (une seule fois)

### 1. Repo

```bash
git init
git add .
git commit -m "init: repo + seed jusqu'au 18/06"
git branch -M main
git remote add origin git@github.com:dslaskibert/worldcup-odds.git
git push -u origin main
```

### 2. GitHub Pages

Dans **Settings → Pages** du repo :

- **Source :** Deploy from a branch
- **Branch :** `main` / `/docs`
- Save

La page sera disponible sous ~1 min à l'URL ci-dessus.

### 3. Permissions Actions

Dans **Settings → Actions → General → Workflow permissions** :

- Cocher **Read and write permissions**

Sans ça, l'Action ne pourra pas push le CSV mis à jour.

### 4. Premier run

Onglet **Actions** → "Daily odds update" → **Run workflow**.
Vérifie que le commit `data: cotes du …` apparaît et que la page se met à jour.

## En local

```bash
pip install -r requirements.txt
playwright install chromium
python scrape.py    # met à jour data/odds.csv pour aujourd'hui
python build.py     # régénère docs/index.html
```

Ouvre `docs/index.html` dans un navigateur pour prévisualiser.

## Structure

```
.
├── .github/workflows/daily.yml   # cron + commit auto
├── data/odds.csv                 # historique (source de vérité)
├── docs/index.html               # page publiée (générée)
├── scrape.py                     # scraping Winamax via Playwright
├── build.py                      # CSV → HTML heatmap
└── requirements.txt
```

## Si le scraping casse

Winamax peut changer ses sélecteurs ou son DOM. Le script extrait les cotes par
**texte brut** (regex sur `document.body.innerText`), donc il résiste aux
changements de classes CSS — mais pas à un changement de format d'affichage des
cotes (ex. `5.50` → `5,50` ou `5 50`).

En cas d'échec (couverture < 90 %), l'Action :

- ne modifie pas le CSV (pas de données partielles),
- upload `debug/page.png` + `debug/page.txt` en artefact du run.

Télécharge l'artefact, regarde ce qu'a vu Playwright, et ajuste `extract_odd()`
ou `ALIASES` dans `scrape.py`.
