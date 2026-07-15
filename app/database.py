"""
Configuration de la base de données.

On utilise SQLite (fichier local `iaprospect.db`) via SQLAlchemy.
SQLite convient parfaitement pour un prototype / une petite application ;
on pourra passer à PostgreSQL en production en changeant simplement `DATABASE_URL`.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# URL de connexion. Le fichier est créé automatiquement au premier lancement.
DATABASE_URL = "sqlite:///./iaprospect.db"

# `check_same_thread=False` est requis avec SQLite lorsqu'il est utilisé
# depuis plusieurs threads (ce que fait FastAPI/uvicorn).
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Fabrique de sessions : chaque requête HTTP obtiendra sa propre session.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Classe de base dont hériteront tous les modèles ORM.
Base = declarative_base()


def get_db():
    """
    Dépendance FastAPI : fournit une session de base de données et
    garantit sa fermeture à la fin de la requête.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
