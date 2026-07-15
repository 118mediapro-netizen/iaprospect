"""
Moteur de recherche modulaire (scraper générique).

Objectif : à partir d'un métier et d'une ville, récupérer une liste d'annonces
brutes sous la forme de dictionnaires ``{"titre", "description", "source_url"}``.

Deux modes sont disponibles :

1. **Scraping réel** (``scraper_url``) : télécharge une page/flux et l'analyse
   avec BeautifulSoup. Les sélecteurs CSS sont paramétrables, ce qui rend le
   module adaptable à n'importe quel site d'annonces ou flux RSS.

2. **Mode démonstration** (``_demo_html``) : génère un jeu d'annonces d'exemple
   contenant le métier et la ville recherchés — ainsi que quelques annonces
   « pièges » (mauvaise ville, hors sujet) — puis l'analyse avec le même parseur.
   La plateforme est donc immédiatement fonctionnelle, sans dépendre d'un site
   externe, tout en exerçant réellement la logique de scraping.

``rechercher_annonces`` orchestre le tout : si une URL source est fournie et
accessible, on scrappe réellement ; sinon on bascule automatiquement en démo.
"""

import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Sélecteur CSS par défaut d'un bloc « annonce ». À adapter selon le site cible.
SELECTEUR_ANNONCE = "article.annonce"


def parser_html_annonces(html: str, selecteur: str = SELECTEUR_ANNONCE) -> list[dict]:
    """
    Analyse une structure HTML générique d'annonces.

    Pour chaque bloc correspondant à ``selecteur``, on tente d'extraire :
      - un titre       (.titre / .title / h1-h3)
      - une description (.description / .desc / p)
      - un lien         (premier <a href>)

    Cette souplesse permet de couvrir la majorité des sites d'annonces sans
    réécrire le parseur : il suffit généralement d'ajuster le sélecteur.
    """
    soup = BeautifulSoup(html, "html.parser")
    resultats: list[dict] = []

    for bloc in soup.select(selecteur):
        titre_el = bloc.select_one(".titre, .title, h1, h2, h3")
        desc_el = bloc.select_one(".description, .desc, p")
        lien_el = bloc.select_one("a[href]")

        resultats.append(
            {
                "titre": titre_el.get_text(strip=True) if titre_el else "Sans titre",
                "description": desc_el.get_text(strip=True) if desc_el else "",
                "source_url": lien_el["href"] if lien_el else "",
            }
        )

    return resultats


def scraper_url(
    url: str,
    selecteur: str = SELECTEUR_ANNONCE,
    timeout: int = 15,
) -> list[dict]:
    """
    Télécharge une page/flux et renvoie les annonces qu'elle contient.

    Lève une exception (requests.RequestException) en cas d'échec réseau ;
    l'appelant (``rechercher_annonces``) gère le repli en mode démo.
    """
    headers = {"User-Agent": "IAProspectBot/1.0 (+https://exemple.test/bot)"}
    reponse = requests.get(url, headers=headers, timeout=timeout)
    reponse.raise_for_status()
    return parser_html_annonces(reponse.text, selecteur)


# ── Mode démonstration ──────────────────────────────────────────────────────
_GABARIT_ANNONCE = """
<article class="annonce">
  <h2 class="titre">{titre}</h2>
  <div class="description">{description}</div>
  <a class="lien" href="{url}">Voir l'annonce</a>
</article>
"""


def _demo_html(metier: str, ville: str) -> str:
    """
    Construit un document HTML d'exemple contenant un panel d'annonces :
    des opportunités réellement pertinentes, et quelques annonces « pièges »
    (autre ville, simple vente, stage non rémunéré) que l'IA devra écarter.
    """
    autre_ville = "Lyon" if ville.strip().lower() != "lyon" else "Marseille"

    annonces = [
        (
            f"Recherche {metier} pour un projet à {ville}",
            f"Un particulier recherche un professionnel « {metier} » disponible "
            f"rapidement à {ville}. Devis souhaité sous 15 jours, budget correct.",
            "https://exemple-annonces.test/annonce/1",
        ),
        (
            f"Appel d'offres : prestation {metier} — {ville}",
            f"Une entreprise locale de {ville} recherche un prestataire pour une "
            f"mission de {metier}. Démarrage prévu le mois prochain.",
            "https://exemple-annonces.test/annonce/2",
        ),
        (
            f"Mission ponctuelle {metier} ({ville} et alentours)",
            f"Besoin d'un intervenant {metier} pour une mission ponctuelle autour "
            f"de {ville}. Merci de nous contacter avec vos références et tarifs.",
            "https://exemple-annonces.test/annonce/3",
        ),
        (
            f"Recherche {metier} à {autre_ville}",
            f"Projet situé à {autre_ville}. Nous cherchons un professionnel "
            f"{metier}. (Attention : zone géographique différente de la cible.)",
            "https://exemple-annonces.test/annonce/4",
        ),
        (
            "Vente de matériel d'occasion entre particuliers",
            "Particulier vend divers outillages et matériels d'occasion. "
            "Aucune prestation recherchée, il s'agit d'une simple vente.",
            "https://exemple-annonces.test/annonce/5",
        ),
        (
            f"Étudiant cherche stage non rémunéré en {metier}",
            f"Étudiant motivé recherche un stage non rémunéré dans le domaine du "
            f"{metier} à {ville}. (Ce n'est pas une opportunité commerciale.)",
            "https://exemple-annonces.test/annonce/6",
        ),
    ]

    corps = "\n".join(
        _GABARIT_ANNONCE.format(titre=t, description=d, url=u)
        for t, d, u in annonces
    )
    return f"<html><body><main>{corps}</main></body></html>"


def rechercher_annonces(
    metier: str,
    ville: str,
    source_url: str | None = None,
    selecteur: str = SELECTEUR_ANNONCE,
) -> list[dict]:
    """
    Point d'entrée du moteur de recherche.

    - Si ``source_url`` est fournie et exploitable, on scrappe réellement le site.
    - Sinon (ou en cas d'échec), on bascule en mode démonstration.

    Renvoie une liste de dictionnaires ``{"titre", "description", "source_url"}``.
    """
    if source_url:
        try:
            annonces = scraper_url(source_url, selecteur)
            if annonces:
                return annonces
            logger.warning(
                "Aucune annonce trouvée sur %s — bascule en mode démonstration.",
                source_url,
            )
        except Exception as exc:  # réseau, HTTP, parsing…
            logger.warning(
                "Échec du scraping de %s (%s) — bascule en mode démonstration.",
                source_url,
                exc,
            )

    # Mode démonstration : on génère puis on parse un HTML d'exemple,
    # ce qui exerce réellement le parseur BeautifulSoup.
    return parser_html_annonces(_demo_html(metier, ville))
