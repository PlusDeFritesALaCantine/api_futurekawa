# api_futurekawa

API REST FastAPI pour le pays Brésil — expose les lots de café, les mesures IoT et les alertes.

## Fonctionnalités

- **Lots** (`app/routers/lots.py`) : création, liste (filtrable par pays, triée FIFO par
  date de stockage) et détail d'un lot ; statut (`conforme`/`perime`) recalculé à la volée
  (`app/services/alertes.py::calculer_statut_lot`, péremption à 365 jours).
- **Mesures** (`app/routers/mesures.py`) : historique (filtrable par `entrepot_id`) et
  dernier relevé par entrepôt (filtrable par pays). Les lignes de `mesures` sont insérées
  par les scripts de `MQTT_Broker/` (`subscriber.py` pour le pipeline MQTT temps réel,
  `session_lot.py` pour les sessions de capture live), pas par cette API — elle est
  consommatrice (lecture) de ces données.
- **Alertes & emails** (`app/routers/alertes.py`, `app/services/`) : détecte les lots
  périmés et les mesures hors seuil pays, et envoie un récapitulatif email au responsable
  d'exploitation concerné (voir [Dispositif d'alertes email](#dispositif-dalertes-email-cahier-des-charges-iii4)).
- **Deux modes de base de données** : PostgreSQL (pipeline temps réel partagé avec
  `MQTT_Broker`, `DB_URL`/`DATABASE_URL` sur le port `5433`) ou SQLite locale
  (`futurekawa.db`, utilisée par `start_all.sh` pour la démo front-end et alimentée par
  `seed_sqlite.py` ainsi que par les sessions live `session_lot.py`).

## Prérequis

- Docker & Docker Compose (démarrage via `MQTT_Broker/`)
- **ou** Python 3.12+ avec PostgreSQL local pour le développement

## Lancement (via MQTT_Broker)

```bash
cd ../MQTT_Broker
docker compose up --build
```

L'API démarre sur `http://localhost:8001`.

## Développement local

```bash
pip install -r requirements.txt
cp .env.example .env   # adapter DATABASE_URL si besoin
uvicorn app.main:app --reload --port 8001
```

## Endpoints

| Méthode | Route                  | Description                                      |
|---------|------------------------|--------------------------------------------------|
| GET     | `/health`              | Healthcheck                                      |
| POST    | `/lots`                | Créer un lot                                     |
| GET     | `/lots`                | Lister les lots (`?pays=` optionnel), triés FIFO date ASC |
| GET     | `/lots/{id}`           | Détail d'un lot                                  |
| GET     | `/mesures`             | Historique des mesures (`?entrepot_id=` optionnel) |
| GET     | `/mesures/latest`      | Dernière mesure par entrepôt (`?pays=` optionnel) |
| GET     | `/alertes`             | Lots périmés + mesures hors seuil                |
| POST    | `/alertes/notifier`    | Déclenche immédiatement une vérification + envoi des emails en attente |

## Variables d'environnement

| Variable                  | Description                                  | Défaut                                                         |
|----------------------------|-----------------------------------------------|------------------------------------------------------------------|
| `DATABASE_URL`             | URL PostgreSQL                                | `postgresql://futurekawa:futurekawa@postgres:5432/futurekawa`   |
| `API_PORT`                 | Port d'écoute                                 | `8001`                                                          |
| `SMTP_HOST` / `SMTP_PORT`  | Serveur SMTP pour les emails d'alerte         | `localhost` / `1025` (Mailpit, voir ci-dessous)                 |
| `SMTP_FROM`                | Adresse expéditeur des emails d'alerte        | `alertes@futurekawa.local`                                      |
| `{PAYS}_MANAGER_EMAIL`     | Email du responsable d'exploitation par pays  | `responsable.{pays}@futurekawa.local`                            |
| `ALERT_CHECK_INTERVAL_SECONDS` | Fréquence de vérification périodique      | `60`                                                             |

## Seuils métier (Brésil)

- Température : 29°C ±3°C → alerte si <26°C ou >32°C
- Humidité : 55% ±2% → alerte si <53% ou >57%
- Lot périmé si > 365 jours de stockage

## Dispositif d'alertes email (cahier des charges III.4)

**Règles.** Une alerte est levée dans deux cas, et un email est envoyé au responsable
d'exploitation du pays concerné (`{PAYS}_MANAGER_EMAIL`) pour chacune :
- un lot dépasse 365 jours de stockage (péremption) ;
- une mesure température/humidité sort de la plage acceptable du pays (seuils ci-dessus,
  par pays dans `app/services/alertes.py::SEUILS_PAYS`).

**Fréquence de vérification.** La boucle (`app/main.py`) tourne au démarrage de l'API
puis toutes les `ALERT_CHECK_INTERVAL_SECONDS` secondes (60s par défaut). `POST
/alertes/notifier` permet de forcer une vérification immédiate (utile en démo).

**Déduplication.** Chaque alerte n'est notifiée qu'une fois : une clé (`lot-{pays}-{id}`
ou `mesure-{pays}-{id}`) est gardée en mémoire du process (`app/services/notifier.py`).
Limite connue de ce prototype : non persisté, donc remis à zéro si l'API redémarre — un
déploiement réel le stockerait en base (cf. le champ `email_sent` du modèle `Alerte` de
MQTT_Broker).

**Contenu des emails** (`app/services/email.py`) :
- *Lot périmé* — objet `[FutureKawa] Alerte lot {id} ({pays}) — lot périmé`, corps avec
  exploitation, entrepôt, date de stockage et raison (nombre de jours).
- *Mesure hors seuil* — objet `[FutureKawa] Alerte conditions de stockage — {entrepot} ({pays})`,
  corps avec température, humidité, date du relevé et raison (seuil dépassé).

**Voir le fonctionnement en local (sans vrai serveur mail).** Le projet utilise
[Mailpit](https://github.com/axllent/mailpit) comme faux serveur SMTP (service `mailpit`
dans `MQTT_Broker/docker-compose.yml`, démarré par `start_all.sh`) : les emails n'existent
jamais réellement, ils sont visibles dans son interface web.

```bash
# Démarrer Mailpit (ou ./start_all.sh qui le fait déjà)
cd ../MQTT_Broker && podman-compose up -d mailpit

# Déclencher une vérification immédiate
curl -X POST http://localhost:8001/alertes/notifier

# Ouvrir http://localhost:8025 : les emails envoyés y apparaissent.
```

## Tests

```bash
pip install -r requirements.txt
pytest
```

## Seed (données de test)

```bash
# Contre PostgreSQL (schéma en syntaxe Postgres : INTERVAL, NOW())
psql $DATABASE_URL -f seed.sql

# Contre la base SQLite locale utilisée par start_all.sh (sqlite:///./futurekawa.db) :
# volume et profils réalistes différents par pays/lot (via les modèles SQLAlchemy)
.venv/bin/python seed_sqlite.py
```
