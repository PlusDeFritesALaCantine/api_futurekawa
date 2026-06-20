"""Construction et envoi des emails d'alerte (cahier des charges III.4).

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


def construire_email_lot(pays: str, lot: Lot, raison: str) -> tuple[str, str]:
    sujet = f"[FutureKawa] Alerte lot {lot.id} ({pays}) — lot périmé"
    corps = (
        "Bonjour,\n\n"
        f"Le lot {lot.id} nécessite votre attention :\n"
        f"  - Raison : {raison}\n"
        f"  - Exploitation : {lot.exploitation}\n"
        f"  - Entrepôt : {lot.entrepot_id}\n"
        f"  - Date de stockage : {lot.date_stockage}\n"
        f"  - Statut actuel : {lot.statut}\n\n"
        "Merci de vérifier ce lot et de statuer sur son expédition ou son déclassement.\n\n"
        "-- Plateforme de suivi FutureKawa (alerte automatique)"
    )
    return sujet, corps


def construire_email_mesure(pays: str, mesure: Mesure, raison: str) -> tuple[str, str]:
    sujet = f"[FutureKawa] Alerte conditions de stockage — {mesure.entrepot_id} ({pays})"
    corps = (
        "Bonjour,\n\n"
        f"Une mesure hors seuil a été relevée dans l'entrepôt {mesure.entrepot_id} :\n"
        f"  - Raison : {raison}\n"
        f"  - Température : {mesure.temperature}°C\n"
        f"  - Humidité : {mesure.humidity}%\n"
        f"  - Relevé le : {mesure.timestamp}\n\n"
        "Merci de vérifier les conditions de cet entrepôt dès que possible.\n\n"
        "-- Plateforme de suivi FutureKawa (alerte automatique)"
    )
    return sujet, corps


def envoyer_email(destinataire: str, sujet: str, corps: str) -> None:
    message = EmailMessage()
    message["Subject"] = sujet
    message["From"] = SMTP_FROM
    message["To"] = destinataire
    message.set_content(corps)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as smtp:
        smtp.send_message(message)
