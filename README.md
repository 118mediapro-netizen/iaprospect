# IAProspect — Plateforme SaaS de prospection automatisée

Plateforme web **100 % flexible** qui s'adapte à n'importe quel secteur (BTP,
freelance, services…). Vous saisissez des critères (métier, ville, mots-clés) ;
la plateforme explore les annonces, puis un **agent IA (Claude)** les filtre et
rédige un **message d'approche** personnalisé pour chaque opportunité pertinente.

## Architecture

```
iaprospect/
├── main.py                 # Application FastAPI : orchestration + routes
├── requirements.txt        # Dépendances Python
├── .env.example            # Modèle de configuration (clé API…)
├── app/
│   ├── database.py         # Connexion SQLite + SQLAlchemy
│   ├── models.py           # Modèles ORM : User, SearchCriteria, Lead
│   ├── crud.py             # Fonctions d'accès à la base de données
│   ├── scraper.py          # Moteur de recherche modulaire (BeautifulSoup)
│   └── ai_agent.py         # Agent IA (SDK anthropic) : filtrage + message
└── templates/              # Interface web (Jinja2 + Bootstrap 5 via CDN)
    ├── base.html
    ├── index.html          # Formulaire de critères
    └── dashboard.html      # Tableau de bord des opportunités
```

### Le flux

```
Formulaire de critères ─▶ Scraper (annonces brutes) ─▶ Agent IA (filtrage)
                                                              │
                                  Base de données ◀───────────┘
                                        │
                                  Tableau de bord (leads triés par pertinence)
```

## Composants

- **Base de données & modèles** — SQLite via SQLAlchemy. `User` (id, email),
  `SearchCriteria` (métier, ville, mots-clés inclus/exclus) et `Lead` (titre,
  description, source, pertinence IA, raison IA, message suggéré), reliés entre eux.
- **Interface web** — FastAPI + Jinja2, mise en forme avec Bootstrap 5 (CDN).
  Une page pour saisir les critères, un tableau de bord pour les opportunités.
- **Moteur de recherche** — scraper générique et modulaire (BeautifulSoup),
  paramétrable par le métier et la ville. Un mode démonstration intégré génère
  des annonces d'exemple pour que la plateforme fonctionne immédiatement.
- **Agent IA** — SDK officiel `anthropic`. Un prompt système **dynamique**
  (construit à partir des critères) demande à Claude de renvoyer, via les
  *structured outputs*, un JSON strict :
  `{"pertinent": bool, "raison": str, "message_approche_suggere": str}`.
  Gestion des erreurs (RateLimit, surcharge serveur, réseau) avec reprises à
  intervalle exponentiel.

## Installation

```bash
# 1. (Recommandé) créer un environnement virtuel
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Configurer la clé API
cp .env.example .env
#   puis éditez .env et renseignez ANTHROPIC_API_KEY
```

## Lancement

```bash
uvicorn main:app --reload
```

Puis ouvrez **http://127.0.0.1:8000**.

1. Créez un critère (ex. métier « maçon », ville « Bordeaux »).
2. Cliquez sur **Lancer** : le scraper récupère des annonces et l'IA les qualifie.
3. Consultez le **tableau de bord** : les opportunités pertinentes apparaissent en
   tête, avec un message d'approche prêt à copier.

> Sans clé API, le scraping et l'enregistrement fonctionnent quand même :
> l'analyse IA renvoie simplement un résultat de repli (non pertinent + raison).

## Personnalisation

- **Changer de modèle IA** : modifier `MODELE` dans `app/ai_agent.py`
  (`claude-opus-4-8` par défaut ; `claude-sonnet-5` ou `claude-haiku-4-5` pour
  réduire le coût).
- **Scraper un vrai site** : appeler `scraper.rechercher_annonces(metier, ville,
  source_url="https://…", selecteur="…")` en ajustant le sélecteur CSS des
  annonces dans `app/scraper.py`.
- **Base de données** : remplacer `DATABASE_URL` dans `app/database.py` pour
  passer par exemple à PostgreSQL.

## Déploiement en ligne (Render)

Le fichier `render.yaml` permet un déploiement quasi automatique sur
[Render](https://render.com) (offre gratuite) :

1. S'inscrire sur Render **avec GitHub** (autorise l'accès aux dépôts).
2. **New +** → **Blueprint** → choisir le dépôt `iaprospect`.
3. Render lit `render.yaml` → **Apply**.
4. Renseigner la variable `ANTHROPIC_API_KEY` lorsqu'elle est demandée.
5. Après le build, Render fournit une adresse publique
   (ex. `https://iaprospect.onrender.com`).

> L'offre gratuite met le service en veille après 15 min d'inactivité (le
> premier chargement suivant prend ~30 s) et le stockage est éphémère : la base
> SQLite peut se réinitialiser à un redéploiement. Pour des données durables,
> brancher une base PostgreSQL (Render Postgres, Neon, Supabase…) via `DATABASE_URL`.
