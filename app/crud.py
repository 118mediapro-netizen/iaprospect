"""
Fonctions d'accès à la base de données (CRUD).

Regrouper la logique de persistance ici garde les routes (main.py) lisibles
et facilite les tests.
"""

from sqlalchemy.orm import Session

from . import models
from .ai_agent import AnalyseLead


# ── Utilisateurs ────────────────────────────────────────────────────────────
def get_or_create_user(db: Session, email: str) -> models.User:
    """Renvoie l'utilisateur correspondant à l'e-mail, en le créant si besoin."""
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        user = models.User(email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ── Critères de recherche ───────────────────────────────────────────────────
def creer_critere(
    db: Session,
    user: models.User,
    metier: str,
    ville: str,
    mots_cles_inclus: str,
    mots_cles_exclus: str,
) -> models.SearchCriteria:
    """Crée et enregistre un nouveau jeu de critères pour un utilisateur."""
    critere = models.SearchCriteria(
        metier=metier,
        ville=ville,
        mots_cles_inclus=mots_cles_inclus,
        mots_cles_exclus=mots_cles_exclus,
        user=user,
    )
    db.add(critere)
    db.commit()
    db.refresh(critere)
    return critere


def lister_criteres(db: Session) -> list[models.SearchCriteria]:
    """Renvoie tous les critères, les plus récents d'abord."""
    return (
        db.query(models.SearchCriteria)
        .order_by(models.SearchCriteria.created_at.desc())
        .all()
    )


def get_critere(db: Session, critere_id: int) -> models.SearchCriteria | None:
    """Renvoie un critère par son identifiant (ou None)."""
    return (
        db.query(models.SearchCriteria)
        .filter(models.SearchCriteria.id == critere_id)
        .first()
    )


def supprimer_critere(db: Session, critere: models.SearchCriteria) -> None:
    """Supprime un critère (et ses leads, via la cascade)."""
    db.delete(critere)
    db.commit()


# ── Opportunités (leads) ────────────────────────────────────────────────────
def creer_lead(
    db: Session,
    critere: models.SearchCriteria,
    titre: str,
    description: str,
    source_url: str,
    analyse: AnalyseLead,
) -> models.Lead:
    """Crée un lead à partir d'une annonce et du résultat d'analyse IA."""
    lead = models.Lead(
        titre=titre,
        description=description,
        source_url=source_url,
        pertinence_ia=analyse.pertinent,
        raison_ia=analyse.raison,
        message_suggere=analyse.message_approche_suggere,
        critere=critere,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def lister_leads(db: Session) -> list[models.Lead]:
    """
    Renvoie tous les leads triés par pertinence (pertinents d'abord),
    puis du plus récent au plus ancien.
    """
    return (
        db.query(models.Lead)
        .order_by(
            models.Lead.pertinence_ia.desc(),
            models.Lead.created_at.desc(),
        )
        .all()
    )


def supprimer_tous_leads(db: Session) -> int:
    """Vide la table des leads. Renvoie le nombre de lignes supprimées."""
    nb = db.query(models.Lead).delete()
    db.commit()
    return nb
