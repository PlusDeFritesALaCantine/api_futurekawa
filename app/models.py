from sqlalchemy import (
    Boolean, Column, DateTime, Date, Float, ForeignKey, Index, Integer, String, func, text,
)
from sqlalchemy.orm import relationship
from app.database import Base


class Batch(Base):
    __tablename__ = "batches"

    id = Column(String(50), primary_key=True)
    country = Column(String(50), nullable=False)
    farm = Column(String(100), nullable=False)
    warehouse_id = Column(String(50), nullable=False)
    storage_date = Column(Date, nullable=False)
    status = Column(String(20), default="compliant")

    measures = relationship("Measure", back_populates="batch", cascade="all, delete-orphan")


class Measure(Base):
    __tablename__ = "measures"

    id = Column(String(50), primary_key=True)
    warehouse_id = Column(String(50), nullable=False)
    temperature = Column(Float, nullable=False)
    humidity = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    batch_id = Column(String(50), ForeignKey("batches.id"), nullable=True)
    batch = relationship("Batch", back_populates="measures")


class Country(Base):
    """Per-country business settings: thresholds, shelf life, alert recipient.

    Replaces the three divergent copies of the thresholds (Python constants in
    services/alerts.py, config/seuils.ts on the front-end, seed.py of the MQTT
    broker). The primary key is the slug ('brazil') because it is already the
    public identifier used by the API, the front-end and MQTT topics: a technical
    key would force a translation on every call without adding anything here.
    """

    __tablename__ = "countries"

    slug = Column(String(20), primary_key=True)
    name = Column(String(60), nullable=False)

    ideal_temperature = Column(Float, nullable=False)
    temperature_tolerance = Column(Float, nullable=False)
    ideal_humidity = Column(Float, nullable=False)
    humidity_tolerance = Column(Float, nullable=False)

    shelf_life_days = Column(Integer, nullable=False, default=365)
    manager_email = Column(String(120), nullable=False)
    alerts_enabled = Column(Boolean, nullable=False, default=True)

    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Alert(Base):
    """Persisted alert, with its lifecycle: open -> acknowledged -> resolved.

    Alerts used to be recomputed on every read and e-mail deduplication lived in
    an in-memory dict, reset on every restart. `dedup_key` carries a partial
    unique index (limited to unresolved alerts): the database now guarantees that
    a given anomaly cannot open a second alert, and that survives restarts.

    `resolved_at` is set automatically when the anomaly disappears from the
    readings; `acknowledged_at` is set by a human from the site and does not
    close the alert — it only records that someone has taken it on.
    """

    __tablename__ = "alerts"

    id = Column(String(50), primary_key=True)
    country = Column(String(50), nullable=False, index=True)
    warehouse_id = Column(String(50), nullable=False)
    batch_id = Column(String(50), ForeignKey("batches.id"), nullable=True)
    measure_id = Column(String(50), ForeignKey("measures.id"), nullable=True)

    type = Column(String(20), nullable=False)
    severity = Column(String(20), nullable=False)
    message = Column(String(255), nullable=False)

    dedup_key = Column(String(200), nullable=False)

    triggered_at = Column(DateTime(timezone=True), server_default=func.now())
    emailed_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String(120), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "idx_alert_open_unique",
            "dedup_key",
            unique=True,
            sqlite_where=text("resolved_at IS NULL"),
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index("idx_alert_country_open", "country", "resolved_at"),
    )
