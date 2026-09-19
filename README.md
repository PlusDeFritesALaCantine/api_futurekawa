# api_futurekawa

API REST FastAPI pour le pays Brésil — expose les lots de café, les mesures IoT, les alertes
et le paramétrage métier.

## Fonctionnalités

- **Lots** (`app/routers/lots.py`) : création, liste (filtrable par pays, triée FIFO par
  date de stockage) et détail d'un lot ; statut (`conforme`/`perime`) recalculé à la volée
  (`app/services/alertes.py::calculer_statut_lot`, péremption paramétrable par pays).
- **Mesures** (`app/routers/mesures.py`) : historique **paginé et filtrable** (entrepôt, lot,
  pays, plage de dates) et dernier relevé par entrepôt. Les lignes de `mesures` sont insérées
  par les scripts de `MQTT_Broker/` (`subscriber.py` pour le pipeline MQTT temps réel,
  `session_lot.py` pour les sessions de capture live), pas par cette API — elle est
  consommatrice (lecture) de ces données.
- **Alertes & emails** (`app/routers/alertes.py`, `app/services/`) : détecte les lots
  périmés et les mesures hors seuil pays, et envoie un récapitulatif email au responsable
  d'exploitation concerné (voir [Dispositif d'alertes email](#dispositif-dalertes-email-cahier-des-charges-iii4)).
- **Gestion des alertes** (`app/services/gestion_alertes.py`) : les alertes sont **persistées**
  dans la table `alertes` avec un cycle de vie ouverte → prise en charge → résolue. La
  résolution est automatique quand l'anomalie disparaît des relevés ; l'unicité d'une alerte
  ouverte est garantie par un index unique partiel, pas par une structure en mémoire.
- **Paramétrage** (`app/routers/parametres.py`, `app/services/parametres.py`) : seuils,
  durée de péremption et destinataire des alertes sont stockés dans la table `pays` et
  modifiables depuis le site. Une modification s'applique **sans redémarrage**.
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
| PATCH   | `/lots/{id}`           | Mise à jour partielle (fusion : les champs absents ne sont pas vidés) |
| DELETE  | `/lots/{id}`           | Supprimer un lot et ses mesures (cascade)        |
| GET     | `/mesures`             | Mesures **paginées** : `?entrepot_id=&lot_id=&pays=&debut=&fin=&limit=&offset=`. Réponse `{items, total, limit, offset}`, `limit` par défaut 100 et plafonnée à 1000 |
| GET     | `/mesures/latest`      | Dernière mesure par entrepôt (`?pays=` optionnel) |
| GET     | `/alertes`             | État courant calculé : lots périmés + mesures hors seuil |
| GET     | `/alertes/journal`     | Alertes persistées, paginées (`?pays=&statut=ouverte\|acquittee\|resolue`) |
| POST    | `/alertes/synchroniser`| Aligne la table des alertes sur l'état courant (idempotent) |
| PATCH   | `/alertes/{id}/acquitter` | Prise en charge — l'alerte **reste ouverte**  |
| PATCH   | `/alertes/{id}/resoudre`  | Clôture manuelle                            |
| POST    | `/alertes/notifier`    | Déclenche immédiatement une vérification + envoi des emails en attente |
| GET     | `/parametres/pays`     | Paramétrage des trois pays                       |
| GET     | `/parametres/pays/{slug}` | Paramétrage d'un pays                         |
| PATCH   | `/parametres/pays/{slug}` | Modifier seuils / péremption / destinataire (fusion partielle) |

## Variables d'environnement

| Variable                  | Description                                  | Défaut                                                         |
|----------------------------|-----------------------------------------------|------------------------------------------------------------------|
| `DATABASE_URL`             | URL PostgreSQL                                | `postgresql://futurekawa:futurekawa@postgres:5432/futurekawa`   |
| `API_PORT`                 | Port d'écoute                                 | `8001`                                                          |
| `SMTP_HOST` / `SMTP_PORT`  | Serveur SMTP pour les emails d'alerte         | `localhost` / `1025` (Mailpit, voir ci-dessous)                 |
| `SMTP_FROM`                | Adresse expéditeur des emails d'alerte        | `alertes@futurekawa.local`                                      |
| `{PAYS}_MANAGER_EMAIL`     | Destinataire initial des alertes. **Sert uniquement à amorcer la table `pays` au premier démarrage** ; ensuite la valeur en base fait foi | `responsable.{pays}@futurekawa.local` |
| `ALERT_CHECK_INTERVAL_SECONDS` | Fréquence de vérification périodique      | `60`                                                             |
| `ALERT_LOOP_ENABLED`       | Active la boucle de fond (synchro des alertes + e-mails). `0` pour la couper — réplica en lecture seule, ou tests | `1` |

## Seuils métier

Les valeurs ci-dessous sont celles du cahier des charges. Elles **amorcent** la table `pays`
au premier démarrage puis deviennent modifiables depuis le site ; elles servent aussi de repli
lorsque le code est appelé hors contexte base (tests des fonctions pures).

| Pays | Température | Humidité | Péremption |
|---|---|---|---|
| Brésil | 29 °C ± 3 → alerte hors 26–32 °C | 55 % ± 2 → alerte hors 53–57 % | 365 jours |
| Équateur | 31 °C ± 3 | 60 % ± 2 | 365 jours |
| Colombie | 26 °C ± 3 | 80 % ± 2 | 365 jours |

Au-delà du **double** de la tolérance, l'alerte passe de `bas` à `critique`.

```bash
# Lire et modifier le paramétrage
curl -s http://localhost:8001/parametres/pays | python3 -m json.tool
curl -X PATCH http://localhost:8001/parametres/pays/bresil \
     -H 'Content-Type: application/json' -d '{"peremption_jours":120}'
```

## Dispositif d'alertes email (cahier des charges III.4)

**Règles.** Une alerte est levée dans deux cas, et un email est envoyé au responsable
d'exploitation du pays concerné (`{PAYS}_MANAGER_EMAIL`) pour chacune :
- un lot dépasse 365 jours de stockage (péremption) ;
- une mesure température/humidité sort de la plage acceptable du pays (seuils ci-dessus,
  par pays dans la table `pays`, cf. `app/services/parametres.py`).

**Fréquence de vérification.** La boucle (`app/main.py`) tourne au démarrage de l'API
puis toutes les `ALERT_CHECK_INTERVAL_SECONDS` secondes (60s par défaut). `POST
/alertes/notifier` permet de forcer une vérification immédiate (utile en démo).

**Déduplication.** Portée par la colonne `alertes.email_envoye_le`. Un récapitulatif ne part
que s'il existe au moins une alerte ouverte dont l'e-mail n'est pas encore parti ; l'envoi
horodate toutes celles du lot. **Cet état est en base, donc il survit au redémarrage** — la
version précédente gardait un dictionnaire en mémoire, remis à zéro à chaque redémarrage, ce
qui provoquait le renvoi de récapitulatifs déjà notifiés.

`pays.alertes_actives = false` coupe les e-mails d'un pays sans aveugler la page Alertes :
la synchronisation des alertes continue, seul l'envoi est suspendu.

**Contenu des e-mails** (`app/services/email.py`) : **un seul récapitulatif par pays**, pas un
e-mail par alerte. Objet `[FutureKawa] Récapitulatif alertes {pays} — N lot(s) périmé(s),
M seuil(s) dépassé(s)` ; le corps liste chaque lot périmé (exploitation, entrepôt, raison) puis
l'état des seuils par entrepôt à partir du dernier relevé.

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

97 tests : règles métier, endpoints, paramétrage, cycle de vie des alertes, e-mails.

```bash
pip install -r requirements.txt
pytest -q
```

## Seed (données de test)

```bash
# Contre PostgreSQL (schéma en syntaxe Postgres : INTERVAL, NOW())
psql $DATABASE_URL -f seed.sql

# Contre la base SQLite locale utilisée par start_all.sh (sqlite:///./futurekawa.db) :
# volume et profils réalistes différents par pays/lot (via les modèles SQLAlchemy)
.venv/bin/python seed_sqlite.py
```
