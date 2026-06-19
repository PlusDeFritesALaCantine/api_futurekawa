# api_futurekawa

API REST FastAPI pour le pays Brésil — expose les lots de café, les mesures IoT et les alertes.

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
| GET     | `/lots`                | Lister tous les lots (triés FIFO date ASC)       |
| GET     | `/lots/{id}`           | Détail d'un lot                                  |
| GET     | `/mesures`             | Historique des mesures (`?entrepot_id=` optionnel) |
| GET     | `/mesures/latest`      | Dernière mesure par entrepôt                     |
| GET     | `/alertes`             | Lots périmés + mesures hors seuil                |

## Variables d'environnement

| Variable       | Description                      | Défaut                                                    |
|----------------|----------------------------------|-----------------------------------------------------------|
| `DATABASE_URL` | URL PostgreSQL                   | `postgresql://futurekawa:futurekawa@postgres:5432/futurekawa` |
| `API_PORT`     | Port d'écoute                    | `8001`                                                    |

## Seuils métier (Brésil)

- Température : 29°C ±3°C → alerte si <26°C ou >32°C
- Humidité : 55% ±2% → alerte si <53% ou >57%
- Lot périmé si > 365 jours de stockage

## Tests

```bash
pip install -r requirements.txt
pytest
```

## Seed (données de test)

```bash
psql $DATABASE_URL -f seed.sql
```
