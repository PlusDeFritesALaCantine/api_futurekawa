"""Mises à jour de schéma légères pour les bases déjà créées.

`Base.metadata.create_all()` crée les tables manquantes mais ne touche jamais à
une table existante : une base créée avant l'ajout de `mesures.lot_id` reste donc
sans cette colonne et l'app plante au premier SELECT ("no such column: mesures.lot_id").
Le projet n'utilise pas Alembic ; on comble ici l'écart en ajoutant les colonnes
nullables absentes, ce qui suffit aux évolutions du modèle et fonctionne aussi
bien sur SQLite que sur PostgreSQL.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.models import Base

logger = logging.getLogger(__name__)


def synchroniser_schema(engine: Engine) -> None:
    """Ajoute aux tables existantes les colonnes nullables présentes dans les modèles."""
    inspecteur = inspect(engine)
    tables_existantes = set(inspecteur.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in tables_existantes:
            continue

        colonnes_en_base = {col["name"] for col in inspecteur.get_columns(table.name)}
        for colonne in table.columns:
            if colonne.name in colonnes_en_base:
                continue
            if not colonne.nullable or colonne.primary_key:
                logger.warning(
                    "Colonne %s.%s absente et non nullable : migration manuelle requise.",
                    table.name, colonne.name,
                )
                continue

            type_sql = colonne.type.compile(engine.dialect)
            ddl = f"ALTER TABLE {table.name} ADD COLUMN {colonne.name} {type_sql}"
            for fk in colonne.foreign_keys:
                ddl += f" REFERENCES {fk.column.table.name}({fk.column.name})"
            with engine.begin() as connexion:
                connexion.execute(text(ddl))
            logger.info("Colonne %s.%s ajoutée.", table.name, colonne.name)
