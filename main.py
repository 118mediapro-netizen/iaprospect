"""
IAProspect — Plateforme SaaS de prospection automatisée.

Point d'entrée FastAPI qui orchestre l'ensemble :

    Formulaire de critères ─▶ Scraper (annonces brutes) ─▶ Agent IA (filtrage)
                                                                │
                                    Base de données ◀───────────┘
                                          │
                                    Tableau de bord (leads triés par pertinence)

Lancement :  uvicorn main:app --reload
Puis ouvrir :  http://127.0.0.1:8000
"""

import logging
import os

# Chargement optionnel d'un fichier .env (pour ANTHROPIC_API_KEY notamment).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv non installé : on continue sans.
    pass

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import crud, models, scraper
from app.ai_agent import analyser_annonce
from app.database import Base, engine, get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("iaprospect")

# Création automatique des tables au démarrage.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="IAProspect", description="Prospection automatisée par IA")

# Moteur de templates Jinja2 (dossier « templates/ »).
templates = Jinja2Templates(directory="templates")

# E-mail utilisateur par défaut (mono-utilisateur pour ce prototype).
EMAIL_DEFAUT = os.getenv("IAPROSPECT_USER_EMAIL", "demo@iaprospect.local")


def cle_api_presente() -> bool:
    """Indique si une clé API Anthropic est configurée (pour l'affichage UI)."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


# ── Accueil : formulaire de critères + liste des critères existants ──────────
@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    criteres = crud.lister_criteres(db)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "criteres": criteres,
            "email_defaut": EMAIL_DEFAUT,
            "cle_api": cle_api_presente(),
        },
    )


# ── Ajout d'un nouveau jeu de critères ───────────────────────────────────────
@app.post("/criteres")
def ajouter_critere(
    email: str = Form(...),
    metier: str = Form(...),
    ville: str = Form(...),
    mots_cles_inclus: str = Form(""),
    mots_cles_exclus: str = Form(""),
    db: Session = Depends(get_db),
):
    email = (email or "").strip() or EMAIL_DEFAUT
    user = crud.get_or_create_user(db, email)
    crud.creer_critere(
        db,
        user=user,
        metier=metier.strip(),
        ville=ville.strip(),
        mots_cles_inclus=mots_cles_inclus.strip(),
        mots_cles_exclus=mots_cles_exclus.strip(),
    )
    # Redirection PRG (Post/Redirect/Get) pour éviter les re-soumissions.
    return RedirectResponse("/", status_code=303)


# ── Lancement de la prospection pour un jeu de critères ──────────────────────
@app.post("/criteres/{critere_id}/lancer")
def lancer_prospection(critere_id: int, db: Session = Depends(get_db)):
    """
    Exécute la chaîne complète pour un jeu de critères :
    scraping des annonces ─▶ analyse IA de chacune ─▶ enregistrement des leads.
    """
    critere = crud.get_critere(db, critere_id)
    if critere is None:
        return RedirectResponse("/", status_code=303)

    annonces = scraper.rechercher_annonces(critere.metier, critere.ville)
    logger.info("%d annonce(s) récupérée(s) pour le critère #%d.", len(annonces), critere_id)

    for annonce in annonces:
        # On assemble un texte brut représentatif de l'annonce pour l'IA.
        texte = (
            f"Titre : {annonce['titre']}\n"
            f"Description : {annonce['description']}\n"
            f"Source : {annonce['source_url']}"
        )
        analyse = analyser_annonce(texte, critere)
        crud.creer_lead(
            db,
            critere=critere,
            titre=annonce["titre"],
            description=annonce["description"],
            source_url=annonce["source_url"],
            analyse=analyse,
        )

    return RedirectResponse("/dashboard", status_code=303)


# ── Suppression d'un jeu de critères ─────────────────────────────────────────
@app.post("/criteres/{critere_id}/supprimer")
def supprimer_critere(critere_id: int, db: Session = Depends(get_db)):
    critere = crud.get_critere(db, critere_id)
    if critere is not None:
        crud.supprimer_critere(db, critere)
    return RedirectResponse("/", status_code=303)


# ── Tableau de bord : opportunités triées par pertinence ─────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    leads = crud.lister_leads(db)
    nb_pertinents = sum(1 for lead in leads if lead.pertinence_ia)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "leads": leads,
            "nb_total": len(leads),
            "nb_pertinents": nb_pertinents,
            "cle_api": cle_api_presente(),
        },
    )


# ── Vider toutes les opportunités ────────────────────────────────────────────
@app.post("/leads/vider")
def vider_leads(db: Session = Depends(get_db)):
    crud.supprimer_tous_leads(db)
    return RedirectResponse("/dashboard", status_code=303)


# ── Sonde de santé (utile pour la supervision) ───────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "cle_api_configuree": cle_api_presente()}
