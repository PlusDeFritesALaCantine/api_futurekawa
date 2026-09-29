"""Lightweight schema updates for already-created databases.

`Base.metadata.create_all()` creates the missing tables but never touches an
existing table: a database created before `measures.batch_id` was added therefore
stays without that column and the app crashes on the first SELECT ("no such
column: measures.batch_id"). The project does not use Alembic; we close the gap
here by adding the missing nullable columns, which is enough for the model
evolutions and works just as well on SQLite as on PostgreSQL.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.models import Base

logger = logging.getLogger(__name__)


def sync_schema(engine: Engine) -> None:
    """Adds to the existing tables the nullable columns present in the models."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue

        columns_in_db = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in columns_in_db:
                continue
            if not column.nullable or column.primary_key:
                logger.warning(
                    "Column %s.%s is missing and not nullable: manual migration required.",
                    table.name, column.name,
                )
                continue

            type_sql = column.type.compile(engine.dialect)
            ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {type_sql}"
            for fk in column.foreign_keys:
                ddl += f" REFERENCES {fk.column.table.name}({fk.column.name})"
            with engine.begin() as connection:
                connection.execute(text(ddl))
            logger.info("Column %s.%s added.", table.name, column.name)
