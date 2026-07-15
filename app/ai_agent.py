"""
Agent IA — le « cerveau » du filtrage.

Ce module intègre le SDK officiel `anthropic` pour qualifier chaque annonce.
La fonction principale, ``analyser_annonce``, prend en entrée :

    - le texte brut d'une annonce scrappée ;
    - les critères de l'utilisateur (objet SearchCriteria) ;

et renvoie une décision structurée sous la forme d'un objet ``AnalyseLead`` :

    {
        "pertinent": bool,
        "raison": str,
        "message_approche_suggere": str
    }

Points clés :
    - On force le format de sortie JSON via les *structured outputs*
      (`output_config.format`) : le modèle est contraint de respecter
      exactement le schéma demandé.
    - La gestion d'erreurs couvre les cas RateLimit (429), surcharge/erreurs
      serveur (5xx), problèmes réseau et réponses malformées, avec des
      nouvelles tentatives à intervalle exponentiel (2s, 4s, 8s, 16s).
    - En cas d'échec définitif (ou d'absence de clé API), on renvoie une
      analyse de repli non bloquante : l'annonce est tout de même enregistrée.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass

import anthropic

logger = logging.getLogger(__name__)

# Modèle utilisé. Opus 4.8 est le modèle le plus performant ; on peut le
# remplacer par « claude-sonnet-5 » ou « claude-haiku-4-5 » pour réduire le coût.
MODELE = "claude-opus-4-8"

# Schéma JSON imposé à la réponse du modèle (structured outputs).
# `additionalProperties: false` garantit qu'aucun champ superflu n'est renvoyé.
SCHEMA_REPONSE = {
    "type": "object",
    "properties": {
        "pertinent": {
            "type": "boolean",
            "description": "L'annonce correspond-elle réellement aux critères ?",
        },
        "raison": {
            "type": "string",
            "description": "Explication concise de la décision (1 à 2 phrases).",
        },
        "message_approche_suggere": {
            "type": "string",
            "description": (
                "Si pertinent : message d'approche commercial personnalisé, "
                "prêt à l'envoi. Sinon : chaîne vide."
            ),
        },
    },
    "required": ["pertinent", "raison", "message_approche_suggere"],
    "additionalProperties": False,
}

# Délais (en secondes) entre les tentatives — backoff exponentiel.
DELAIS_BACKOFF = [2, 4, 8, 16]


@dataclass
class AnalyseLead:
    """Résultat structuré de l'analyse d'une annonce par l'IA."""

    pertinent: bool
    raison: str
    message_approche_suggere: str


# Client Anthropic mis en cache (créé une seule fois, à la demande).
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """
    Renvoie un client Anthropic partagé.

    La clé API est lue depuis la variable d'environnement ANTHROPIC_API_KEY.
    La construction lève une exception si aucune clé n'est disponible : elle
    est interceptée plus haut pour produire une analyse de repli.
    """
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _repli(raison: str) -> AnalyseLead:
    """Analyse par défaut lorsque l'IA est indisponible ou en erreur."""
    return AnalyseLead(pertinent=False, raison=raison, message_approche_suggere="")


def construire_prompt_systeme(critere) -> str:
    """
    Construit dynamiquement le prompt système à partir des critères utilisateur.

    Ce prompt est le cœur de la flexibilité de la plateforme : il s'adapte
    automatiquement au secteur (BTP, freelance, services…) puisqu'il est
    entièrement paramétré par les champs saisis.
    """
    inclus = critere.mots_cles_inclus.strip() or "(aucun précisé)"
    exclus = critere.mots_cles_exclus.strip() or "(aucun précisé)"

    return (
        "Tu es un assistant expert en prospection commerciale B2B. "
        "Ta mission : analyser une annonce/opportunité brute et déterminer si "
        "elle constitue une véritable opportunité correspondant aux critères "
        "de recherche de l'utilisateur.\n\n"
        "Critères de l'utilisateur :\n"
        f"- Métier / activité recherchée : {critere.metier}\n"
        f"- Zone géographique ciblée : {critere.ville}\n"
        f"- Mots-clés à privilégier : {inclus}\n"
        f"- Mots-clés rédhibitoires (à exclure) : {exclus}\n\n"
        "Règles d'analyse :\n"
        "1. L'annonce doit concerner l'activité recherchée et représenter une "
        "opportunité commerciale réelle (un besoin, un projet, un appel d'offres).\n"
        "2. Elle doit correspondre à la zone géographique ciblée.\n"
        "3. Si un mot-clé rédhibitoire est présent, l'annonce n'est PAS pertinente.\n"
        "4. En cas de doute sérieux (zone incertaine, hors sujet, simple vente, "
        "offre non commerciale), considère l'annonce comme non pertinente.\n\n"
        "Tu dois répondre en renseignant :\n"
        "- pertinent : true/false selon les règles ci-dessus.\n"
        "- raison : une explication concise (1 à 2 phrases) de ta décision.\n"
        "- message_approche_suggere : si pertinent, un message d'approche "
        "commercial personnalisé, professionnel et prêt à l'envoi (2 à 4 phrases), "
        "adressé au prospect et faisant référence au besoin exprimé. "
        "Si non pertinent, renvoie une chaîne vide."
    )


def _extraire_json(texte: str) -> dict:
    """
    Convertit la réponse textuelle du modèle en dictionnaire.

    Avec les structured outputs, le texte est déjà un JSON valide. On prévoit
    tout de même un repli robuste (retrait d'éventuelles balises Markdown,
    extraction du premier objet ``{...}``) au cas où le modèle renverrait du
    texte libre (SDK ancien sans `output_config`).
    """
    texte = texte.strip()
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        # Extraire le premier objet JSON rencontré dans le texte.
        correspondance = re.search(r"\{.*\}", texte, re.DOTALL)
        if correspondance:
            return json.loads(correspondance.group(0))
        raise


def _appel_api(client: anthropic.Anthropic, systeme: str, contenu: str):
    """
    Effectue un unique appel à l'API Messages.

    On tente d'abord les *structured outputs* (`output_config.format`) qui
    garantissent la conformité au schéma. Si le SDK installé est trop ancien
    pour connaître ce paramètre, on retombe sur une consigne JSON stricte.
    """
    parametres = dict(
        model=MODELE,
        max_tokens=1024,
        system=systeme,
        messages=[{"role": "user", "content": contenu}],
    )
    try:
        return client.messages.create(
            **parametres,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA_REPONSE}},
        )
    except TypeError as exc:
        # On ne gère ici QUE le cas d'un SDK trop ancien pour connaître le
        # paramètre « output_config ». Toute autre TypeError (par ex. une erreur
        # d'authentification levée par le SDK) est relancée pour être traitée
        # par l'appelant — sinon on la confondrait avec un souci de compatibilité.
        if "output_config" not in str(exc):
            raise
        parametres["system"] = (
            systeme
            + "\n\nIMPORTANT : réponds UNIQUEMENT avec un objet JSON valide "
            'respectant exactement ce schéma : '
            '{"pertinent": bool, "raison": str, "message_approche_suggere": str}. '
            "Aucun texte avant ou après."
        )
        return client.messages.create(**parametres)


def analyser_annonce(texte_annonce: str, critere) -> AnalyseLead:
    """
    Analyse une annonce brute au regard des critères, via l'IA Claude.

    Renvoie toujours un ``AnalyseLead`` : en cas d'erreur irrécupérable, il
    s'agit d'une analyse de repli (pertinent=False) afin de ne jamais bloquer
    l'enregistrement du lead.
    """
    # Court-circuit : sans aucune clé API configurée, le SDK lèverait une erreur
    # interne au moment de l'appel. On renvoie plutôt un repli clair et immédiat.
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        return _repli("Analyse IA indisponible : aucune clé API configurée (ANTHROPIC_API_KEY).")

    # Construction du client (peut échouer selon la configuration).
    try:
        client = _get_client()
    except Exception as exc:  # noqa: BLE001 — on veut un repli quel que soit l'échec
        logger.warning("Client IA indisponible : %s", exc)
        return _repli(f"Analyse IA indisponible ({exc}).")

    systeme = construire_prompt_systeme(critere)
    contenu = f"Voici l'annonce brute à analyser :\n\n{texte_annonce}"

    derniere_erreur: Exception | None = None

    # Boucle de tentatives : 1 essai initial + len(DELAIS_BACKOFF) reprises.
    for tentative in range(len(DELAIS_BACKOFF) + 1):
        try:
            reponse = _appel_api(client, systeme, contenu)

            # Le modèle peut refuser une requête pour raisons de sécurité.
            if reponse.stop_reason == "refusal":
                return _repli("L'IA a refusé d'analyser cette annonce.")

            # Récupère le premier bloc de texte (JSON) de la réponse.
            texte = next(
                (b.text for b in reponse.content if b.type == "text"),
                "",
            )
            donnees = _extraire_json(texte)

            # On ne conserve que les champs attendus, en sécurisant les types.
            return AnalyseLead(
                pertinent=bool(donnees.get("pertinent", False)),
                raison=str(donnees.get("raison", "")).strip(),
                message_approche_suggere=str(
                    donnees.get("message_approche_suggere", "")
                ).strip(),
            )

        except anthropic.RateLimitError as exc:
            # 429 : trop de requêtes — on respecte au mieux l'en-tête retry-after.
            derniere_erreur = exc
            logger.warning("Limite de débit atteinte (tentative %d).", tentative + 1)

        except anthropic.APIStatusError as exc:
            # Erreurs HTTP renvoyées par l'API.
            derniere_erreur = exc
            if exc.status_code and exc.status_code >= 500:
                # Erreur serveur / surcharge (500, 529) : on réessaie.
                logger.warning("Erreur serveur %s (tentative %d).", exc.status_code, tentative + 1)
            else:
                # Erreur client (400, 401, 403, 404…) : inutile de réessayer.
                logger.error("Erreur API non récupérable : %s", exc)
                return _repli(f"Erreur API ({exc.status_code}).")

        except anthropic.APIConnectionError as exc:
            # Problème réseau : on réessaie.
            derniere_erreur = exc
            logger.warning("Erreur de connexion (tentative %d).", tentative + 1)

        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            # Réponse illisible / mal formée : on tente une nouvelle fois.
            derniere_erreur = exc
            logger.warning("Réponse IA mal formée (tentative %d) : %s", tentative + 1, exc)

        except Exception as exc:  # noqa: BLE001 — filet de sécurité : jamais bloquant
            # Erreur inattendue (ex. authentification, configuration) : on n'insiste
            # pas et on renvoie un repli propre plutôt que de planter la requête.
            logger.warning("Erreur inattendue lors de l'analyse IA : %s", exc)
            return _repli("Analyse IA indisponible (erreur inattendue).")

        # Attente avant la prochaine tentative (sauf après la dernière).
        if tentative < len(DELAIS_BACKOFF):
            time.sleep(DELAIS_BACKOFF[tentative])

    logger.error("Analyse IA échouée après plusieurs tentatives : %s", derniere_erreur)
    return _repli(f"Analyse IA échouée après plusieurs tentatives ({derniere_erreur}).")
