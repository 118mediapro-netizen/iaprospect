"""
Modèles de données (ORM SQLAlchemy).

Trois entités liées entre elles :

    User  1 ── n  SearchCriteria  1 ── n  Lead

- User            : l'utilisateur de la plateforme.
- SearchCriteria  : un jeu de critères de recherche (métier, ville, mots-clés).
- Lead            : une opportunité (« chantier ») trouvée puis analysée par l'IA.

La conception est volontairement générique : rien n'est spécifique à un secteur.
Les champs `metier` et `ville` sont de simples chaînes libres, ce qui permet
d'adapter la plateforme au BTP, au freelancing, aux services, etc.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    """Utilisateur de la plateforme."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)

    # Un utilisateur possède plusieurs jeux de critères de recherche.
    criteres = relationship(
        "SearchCriteria",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class SearchCriteria(Base):
    """
    Critères de recherche saisis par l'utilisateur.

    Ces critères pilotent à la fois le scraper (métier + ville) et l'agent IA
    (tous les champs, y compris les mots-clés inclus/exclus).
    """

    __tablename__ = "search_criteria"

    id = Column(Integer, primary_key=True, index=True)
    metier = Column(String, nullable=False)                 # ex. « maçon », « développeur web »
    ville = Column(String, nullable=False)                  # secteur géographique ciblé
    mots_cles_inclus = Column(Text, default="")             # liste séparée par des virgules
    mots_cles_exclus = Column(Text, default="")             # liste séparée par des virgules
    created_at = Column(DateTime, default=datetime.utcnow)

    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="criteres")

    # Un jeu de critères produit plusieurs opportunités (leads).
    leads = relationship(
        "Lead",
        back_populates="critere",
        cascade="all, delete-orphan",
    )


class Lead(Base):
    """
    Une opportunité commerciale (« chantier ») trouvée puis qualifiée par l'IA.

    Les champs `pertinence_ia`, `raison_ia` et `message_suggere` sont remplis
    par l'agent IA (voir app/ai_agent.py).
    """

    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    titre = Column(String, nullable=False)
    description = Column(Text, default="")
    source_url = Column(String, default="")

    # Résultats de l'analyse IA
    pertinence_ia = Column(Boolean, default=False)          # l'annonce est-elle pertinente ?
    raison_ia = Column(Text, default="")                    # justification de la décision
    message_suggere = Column(Text, default="")              # message d'approche prêt à l'emploi

    created_at = Column(DateTime, default=datetime.utcnow)

    criteria_id = Column(Integer, ForeignKey("search_criteria.id"))
    critere = relationship("SearchCriteria", back_populates="leads")
