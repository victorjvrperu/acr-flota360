from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class EstadoVehiculo(str, enum.Enum):
    OPERATIVO = "operativo"
    EN_RUTA = "en_ruta"
    MANTENIMIENTO = "mantenimiento"
    FUERA_SERVICIO = "fuera_servicio"


class TipoVehiculo(str, enum.Enum):
    CAMION = "camion"
    CAMIONETA = "camioneta"
    FURGON = "furgon"
    SEDAN = "sedan"
    BUS = "bus"


class Vehiculo(Base):
    __tablename__ = "vehiculos"

    id = Column(Integer, primary_key=True, index=True)
    placa = Column(String(20), unique=True, index=True, nullable=False)
    marca = Column(String(50), nullable=False)
    modelo = Column(String(50), nullable=False)
    anio = Column(Integer, nullable=False)
    tipo = Column(String(30), default=TipoVehiculo.CAMIONETA.value, nullable=False)
    vin = Column(String(50), unique=True, nullable=True)
    odometro_actual = Column(Float, default=0.0, nullable=False)
    estado = Column(String(30), default=EstadoVehiculo.OPERATIVO.value, nullable=False)
    combustible_tipo = Column(String(30), default="diesel", nullable=False)
    soat_vencimiento = Column(Date, nullable=True)
    revision_tecnica_vencimiento = Column(Date, nullable=True)
    
    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    mantenimientos = relationship("Mantenimiento", back_populates="vehiculo", cascade="all, delete-orphan")
    cargas_combustible = relationship("CargaCombustible", back_populates="vehiculo", cascade="all, delete-orphan")
    viajes = relationship("Viaje", back_populates="vehiculo")
