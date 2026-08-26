from sqlalchemy import Column, String, Float, Date, DateTime, ForeignKey, func
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

    # Clé étrangère pointant sur la table lots
    lot_id = Column(String(50), ForeignKey("lots.id"), nullable=True)

    # Relation permettant de faire : my_mesure.lot
    lot = relationship("Lot", back_populates="mesures")