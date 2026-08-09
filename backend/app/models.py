"""
RotaHub - Modelos do banco de dados
Modelo normalizado: Route -> Stop -> Package
Um Stop representa um LOCAL físico real (agrupado por coordenada, com tolerância),
não o campo "Stop" da planilha da Shopee (que provamos ser inconsistente).
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=False)


class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    source_at_id = Column(String, nullable=True)       # AT ID original da planilha
    source_format = Column(String, nullable=True)       # "shopee_raw" | "circuit_processed"
    status = Column(String, default="draft")            # draft | optimized | in_progress | finished
    origin_lat = Column(Float, nullable=True)           # ponto de partida (linha '-' do Shopee, se houver)
    origin_lng = Column(Float, nullable=True)
    distance_source = Column(String, nullable=True)     # "osrm" | "haversine"
    total_distance_km = Column(Float, nullable=True)
    total_duration_min = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    stops = relationship("Stop", back_populates="route", cascade="all, delete-orphan",
                          order_by="Stop.sequence")


class Stop(Base):
    __tablename__ = "stops"

    id = Column(Integer, primary_key=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)

    address = Column(String, nullable=False)
    complement = Column(String, nullable=True)     # observação/complemento (ex: "portão azul")
    neighborhood = Column(String, nullable=True)
    city = Column(String, nullable=True)
    zipcode = Column(String, nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    geocode_source = Column(String, default="import")   # "import" | "nominatim" | "manual"
    needs_review = Column(Boolean, default=False)        # endereço não localizado / ambíguo

    custom_label = Column(String, nullable=True)   # apelido opcional (substitui "nome do cliente")

    sequence = Column(Integer, nullable=True)       # ordem final otimizada (1..N)
    cluster_group = Column(Integer, nullable=True)   # id do agrupamento por proximidade real

    status = Column(String, default="pending")       # pending | delivered | skipped
    delivered_at = Column(DateTime, nullable=True)
    skip_reason = Column(String, nullable=True)

    route = relationship("Route", back_populates="stops")
    packages = relationship("Package", back_populates="stop", cascade="all, delete-orphan")


class Package(Base):
    __tablename__ = "packages"

    id = Column(Integer, primary_key=True)
    stop_id = Column(Integer, ForeignKey("stops.id"), nullable=False)
    tracking_number = Column(String, nullable=True)   # SPX TN, quando existir

    stop = relationship("Stop", back_populates="packages")
