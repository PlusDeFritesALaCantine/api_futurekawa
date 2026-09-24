from sqlalchemy import (
    Boolean, Column, DateTime, Date, Float, ForeignKey, Index, Integer, String, func, text,
)
from sqlalchemy.orm import relationship
from app.database import Base


class Lot(Base):
    __tablename__ = "lots"

    id = Column(String(50), primary_key=True)
    pays = Column(String(50), nullable=False)
    exploitation = Column(String(100), nullable=False)
    entrepot_id = Column(String(50), nullable=False)
    date_stockage = Column(Date, nullable=False)
    statut = Column(String(20), default="conforme")

    mesures = relationship("Mesure", back_populates="lot", cascade="all, delete-orphan")


class Mesure(Base):
    __tablename__ = "mesures"

    id = Column(String(50), primary_key=True)
    entrepot_id = Column(String(50), nullable=False)
    temperature = Column(Float, nullable=False)
    humidity = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    lot_id = Column(String(50), ForeignKey("lots.id"), nullable=True)
    lot = relationship("Lot", back_populates="mesures")


class Pays(Base):
    """Paramétrage métier d'un pays : seuils, péremption, destinataire des alertes.

    Remplace les trois copies divergentes des seuils (constantes Python dans
    services/alertes.py, config/seuils.ts côté front, seed.py du broker MQTT).
    La clé primaire est le slug ('bresil') parce que c'est déjà l'identifiant
    public utilisé par l'API, le front et les topics MQTT : une clé technique
    obligerait à traduire à chaque appel sans rien apporter ici.
    """

    __tablename__ = "pays"

    slug = Column(String(20), primary_key=True)
    nom = Column(String(60), nullable=False)

    temperature_ideale = Column(Float, nullable=False)
    temperature_tolerance = Column(Float, nullable=False)
    humidite_ideale = Column(Float, nullable=False)
    humidite_tolerance = Column(Float, nullable=False)

    peremption_jours = Column(Integer, nullable=False, default=365)
    email_responsable = Column(String(120), nullable=False)
    alertes_actives = Column(Boolean, nullable=False, default=True)

    maj_le = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Alerte(Base):
    """Alerte persistée, avec son cycle de vie : ouverte -> acquittée -> résolue.

    Avant, les alertes étaient recalculées à chaque lecture et la déduplication
    des e-mails vivait dans un dict en mémoire, remis à zéro à chaque
    redémarrage. `cle_dedup` porte un index unique partiel (limité aux alertes
    non résolues) : c'est la base qui garantit désormais qu'une même anomalie
    ne rouvre pas une seconde alerte, et ça survit au redémarrage.

    `resolue_le` est posée automatiquement quand l'anomalie disparaît des
    relevés ; `acquittee_le` est posée par un humain depuis le site et ne
    ferme pas l'alerte — elle dit seulement que quelqu'un l'a prise en charge.
    """

    __tablename__ = "alertes"

    id = Column(String(50), primary_key=True)
    pays = Column(String(50), nullable=False, index=True)
    entrepot_id = Column(String(50), nullable=False)
    lot_id = Column(String(50), ForeignKey("lots.id"), nullable=True)
    mesure_id = Column(String(50), ForeignKey("mesures.id"), nullable=True)

    type = Column(String(20), nullable=False)
    severite = Column(String(20), nullable=False)
    message = Column(String(255), nullable=False)

    cle_dedup = Column(String(200), nullable=False)

    declenchee_le = Column(DateTime(timezone=True), server_default=func.now())
    email_envoye_le = Column(DateTime(timezone=True), nullable=True)
    acquittee_le = Column(DateTime(timezone=True), nullable=True)
    acquittee_par = Column(String(120), nullable=True)
    resolue_le = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "idx_alerte_ouverte_unique",
            "cle_dedup",
            unique=True,
            sqlite_where=text("resolue_le IS NULL"),
            postgresql_where=text("resolue_le IS NULL"),
        ),
        Index("idx_alerte_pays_ouverte", "pays", "resolue_le"),
    )
