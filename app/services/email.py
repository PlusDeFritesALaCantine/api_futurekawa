"""Construction et envoi de l'email récapitulatif d'alertes (cahier des charges III.4).

Un seul email par pays et par cycle de vérification (pas un email par alerte
individuelle) : il liste chaque lot périmé, puis l'état des seuils température
/humidité par entrepôt (trop élevé / trop bas) à partir du dernier relevé.

En local/démo, le serveur SMTP cible est Mailpit (voir MQTT_Broker/docker-compose.yml) :
les emails ne partent jamais vers de vraies adresses, ils sont visibles dans l'UI web
de Mailpit (http://localhost:8025). Il suffit de changer SMTP_HOST/SMTP_PORT pour
pointer vers un vrai relais SMTP en production.
"""

import os
import smtplib
from email.message import EmailMessage

from app.models import Lot, Mesure

SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
SMTP_FROM = os.getenv("SMTP_FROM", "alertes@futurekawa.local")

# Responsable d'exploitation par pays — destinataire des alertes (cahier des charges III.4).
MANAGER_EMAILS: dict[str, str] = {
    "bresil": os.getenv("BRESIL_MANAGER_EMAIL", "responsable.bresil@futurekawa.local"),
    "equateur": os.getenv("EQUATEUR_MANAGER_EMAIL", "responsable.equateur@futurekawa.local"),
    "colombie": os.getenv("COLOMBIE_MANAGER_EMAIL", "responsable.colombie@futurekawa.local"),
}


def construire_email_recap(
    pays: str,
    lots_problematiques: list[tuple[Lot, str]],
    anomalies_seuils: list[tuple[Mesure, dict]],
) -> tuple[str, str]:
    nb_lots = len(lots_problematiques)
    nb_seuils = len(anomalies_seuils)

    sujet = f"[FutureKawa] Récapitulatif alertes {pays} — {nb_lots} lot(s) périmé(s), {nb_seuils} seuil(s) dépassé(s)"

    lignes = [
        "Bonjour,",
        "",
        f"Récapitulatif des alertes actives pour {pays} :",
        "",
        f"Lots périmés ({nb_lots}) :",
    ]
    if not lots_problematiques:
        lignes.append("  - Aucun.")
    else:
        for lot, raison in lots_problematiques:
            lignes.append(f"  - {lot.id} ({lot.exploitation}, entrepôt {lot.entrepot_id}) : {raison}")

    lignes += ["", f"Seuils de conservation dépassés ({nb_seuils}) :"]
    if not anomalies_seuils:
        lignes.append("  - Aucun.")
    else:
        for mesure, anomalie in anomalies_seuils:
            lignes.append(
                f"  - Entrepôt {mesure.entrepot_id} : {anomalie['raison']} "
                f"(relevé le {mesure.timestamp})"
            )

    lignes += [
        "",
        "Merci de vérifier ces éléments dès que possible.",
        "",
        "-- Plateforme de suivi FutureKawa (récapitulatif périodique)",
    ]
    return sujet, "\n".join(lignes)


def envoyer_email(destinataire: str, sujet: str, corps: str) -> None:
    message = EmailMessage()
    message["Subject"] = sujet
    message["From"] = SMTP_FROM
    message["To"] = destinataire
    message.set_content(corps)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as smtp:
        smtp.send_message(message)
