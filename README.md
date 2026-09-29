# api_futurekawa

FastAPI REST API for the Brazil country — exposes the coffee batches, IoT
measurements, alerts and business settings.

## Features

- **Batches** (`app/routers/batches.py`): creation, listing (filterable by
  country, FIFO-sorted by storage date) and detail of one batch; status
  (`compliant`/`expired`) recomputed on the fly
  (`app/services/alerts.py::compute_batch_status`, shelf life configurable per
  country).
- **Measurements** (`app/routers/measures.py`): **paginated and filterable**
  history (warehouse, batch, country, date range) and latest reading per
  warehouse. Rows in `measures` are inserted by the `MQTT_Broker/` scripts
  (`subscriber.py` for the real-time MQTT pipeline, `session_lot.py` for live
  capture sessions), not by this API — it is a read-only consumer of that data.
- **Alerts & e-mails** (`app/routers/alerts.py`, `app/services/`): detects expired
  batches and out-of-range measurements per country, and sends a summary e-mail
  to the operations manager concerned (see [Alert e-mail device](#alert-e-mail-device-specification-iii4)).
- **Alert management** (`app/services/alert_lifecycle.py`): alerts are **persisted**
  in the `alerts` table with an open → acknowledged → resolved lifecycle.
  Resolution is automatic when the anomaly disappears from the readings; the
  uniqueness of an open alert is guaranteed by a partial unique index, not by an
  in-memory structure.
- **Settings** (`app/routers/parameters.py`, `app/services/parameters.py`):
  thresholds, shelf life duration and alert recipients are stored in the
  `countries` table and editable from the site. A change takes effect **without a
  restart**.
- **Two database modes**: PostgreSQL (real-time pipeline shared with
  `MQTT_Broker`, `DB_URL`/`DATABASE_URL` on port `5433`) or local SQLite
  (`futurekawa.db`, used by `start_all.sh` for the front-end demo and filled by
  the live `session_lot.py` sessions).

## Requirements

- Docker & Docker Compose (startup via `MQTT_Broker/`)
- **or** Python 3.12+ with a local PostgreSQL for development

## Run (via MQTT_Broker)

```bash
cd ../MQTT_Broker
docker compose up --build
```

The API starts on `http://localhost:8001`.

## Local development

```bash
pip install -r requirements.txt
cp .env.example .env   # adjust DATABASE_URL if needed
uvicorn app.main:app --reload --port 8001
```

## Endpoints

| Method | Route                  | Description                                      |
|--------|------------------------|--------------------------------------------------|
| GET     | `/health`              | Healthcheck                                      |
| POST    | `/batches`             | Create a batch                                   |
| GET     | `/batches`             | List batches (`?country=` optional), FIFO date ASC |
| GET     | `/batches/{id}`        | Batch detail                                     |
| PATCH   | `/batches/{id}`        | Partial update (merge: absent fields are not blanked) |
| DELETE  | `/batches/{id}`        | Delete a batch and its measurements (cascade)    |
| GET     | `/measures`            | **Paginated** measurements: `?warehouse_id=&batch_id=&country=&start=&end=&limit=&offset=`. Response `{items, total, limit, offset}`, `limit` defaults to 100 and is capped at 1000 |
| GET     | `/measures/latest`     | Latest measurement per warehouse (`?country=` optional) |
| GET     | `/alerts`              | Computed current state: expired batches + out-of-range measurements |
| GET     | `/alerts/journal`      | Persisted alerts, paginated (`?country=&status=open\|acknowledged\|resolved`) |
| POST    | `/alerts/sync`         | Aligns the alerts table with the current state (idempotent) |
| PATCH   | `/alerts/{id}/acknowledge` | Acknowledgement — the alert **stays open**  |
| PATCH   | `/alerts/{id}/resolve`  | Manual closure                            |
| POST    | `/alerts/notify`       | Triggers an immediate check + send of pending e-mails |
| GET     | `/parameters/country`  | Settings of the three countries                       |
| GET     | `/parameters/country/{slug}` | Settings of one country                         |
| PATCH   | `/parameters/country/{slug}` | Update thresholds / shelf life / recipient (partial merge) |

## Environment variables

| Variable                  | Description                                  | Default                                                         |
|----------------------------|-----------------------------------------------|------------------------------------------------------------------|
| `DATABASE_URL`             | PostgreSQL URL                                | `postgresql://futurekawa:futurekawa@postgres:5432/futurekawa`   |
| `API_PORT`                 | Listening port                                | `8001`                                                          |
| `SMTP_HOST` / `SMTP_PORT`  | SMTP server for alert e-mails                  | `localhost` / `1025` (Mailpit, see below)                        |
| `SMTP_FROM`                | Sender address for alert e-mails               | `alerts@futurekawa.local`                                       |
| `{COUNTRY}_MANAGER_EMAIL`  | **Read-only fallback** recipient, used only when the country has no row in the `countries` table. The application never creates that row; once a row exists, the database value wins | `manager.{country}@futurekawa.local` |
| `ALERT_CHECK_INTERVAL_SECONDS` | Periodic check frequency                    | `60`                                                             |
| `ALERT_LOOP_ENABLED`       | Enables the background loop (alert sync + e-mails). `0` to turn it off — read-only replica, or tests | `1` |

## Business thresholds

The values below come from the specification and live in the `DEFAULTS` constant of
`app/services/parameters.py`. They are **never written to the database**: the API
only reads and updates existing rows in `countries`, and a country with no row
falls back to these constants. Populating that table is a deployment step (the
seed scripts below, or your own provisioning).

| Country | Temperature | Humidity | Shelf life |
|---|---|---|---|
| Brazil | 29 °C ± 3 → alert outside 26–32 °C | 55 % ± 2 → alert outside 53–57 % | 365 days |
| Ecuador | 31 °C ± 3 | 60 % ± 2 | 365 days |
| Colombia | 26 °C ± 3 | 80 % ± 2 | 365 days |

Beyond **double** the tolerance, the alert goes from `low` to `critical`.

Empty until the table is populated — the API does not create the rows for you:

```bash
# Read and update the settings
curl -s http://localhost:8001/parameters/country | python3 -m json.tool
curl -X PATCH http://localhost:8001/parameters/country/brazil \
     -H 'Content-Type: application/json' -d '{"shelf_life_days":120}'
```

## Alert e-mail device (specification III.4)

**Rules.** An alert is raised in two cases, and a summary e-mail is sent to the
country's operations manager (`{COUNTRY}_MANAGER_EMAIL`) for each:
- a batch exceeds 365 days of storage (shelf life);
- a temperature/humidity measurement falls outside the acceptable range of the
  country (thresholds above, per country in the `countries` table, cf.
  `app/services/parameters.py`).

**Check frequency.** The loop (`app/main.py`) runs at API startup then every
`ALERT_CHECK_INTERVAL_SECONDS` seconds (60 by default). `POST /alerts/notify`
forces an immediate check (useful in a demo).

**Deduplication.** Carried by the `alerts.emailed_at` column. A summary only goes
out if there is at least one open alert whose e-mail has not been sent yet; the
send timestamps all of them. **This state is in the database, so it survives a
restart** — the previous version kept a dictionary in memory, reset on every
restart, which caused already-notified summaries to be re-sent.

`countries.alerts_enabled = false` cuts the e-mails of a country without blinding
the Alerts page: alert synchronisation continues, only sending is suspended.

**Content** (`app/services/email.py`): **a single summary per country**, not one
e-mail per alert. Subject
`[FutureKawa] Alert summary {country} — N expired batch(es), M threshold(s) exceeded`;
the body lists each expired batch (farm, warehouse, reason) then the state of
the thresholds per warehouse from the latest reading.

**See it working locally (without a real mail server).** The project uses
[Mailpit](https://github.com/axllent/mailpit) as a fake SMTP server (`mailpit`
service in `MQTT_Broker/docker-compose.yml`, started by `start_all.sh`):
e-mails never actually exist, they are visible in its web interface.

```bash
# Start Mailpit (or ./start_all.sh which already does)
cd ../MQTT_Broker && podman-compose up -d mailpit

# Trigger an immediate check
curl -X POST http://localhost:8001/alerts/notify

# Open http://localhost:8025: the sent e-mails appear there.
```

## Tests

97 tests: business rules, endpoints, settings, alert lifecycle, e-mails.

```bash
pip install -r requirements.txt
pytest -q
```

## Test data

The repository ships no seed script: the application never populates the database
with hardcoded rows. Batches and measures enter through `POST /batches` and
`POST /measures`, and the `countries` rows are a deployment decision (provision
them yourself, or use the fixtures in `tests/conftest.py` under pytest).
