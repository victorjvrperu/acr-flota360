from sqlalchemy import Column, Integer, String, Date, DateTime, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class EstadoConductor(str, enum.Enum):
    ACTIVO = "activo"
    EN_RUTA = "en_ruta"
    DE_VACACIONES = "de_vacaciones"
    SUSPENDIDO = "suspendido"


class Conductor(Base):
    __tablename__ = "conductores"

    id = Column(Integer, primary_key=True, index=True)
    nombres = Column(String(100), nullable=False)
    apellidos = Column(String(100), nullable=False)
    dni = Column(String(20), unique=True, index=True, nullable=False)
    licencia_numero = Column(String(30), unique=True, nullable=False)
    licencia_categoria = Column(String(10), default="A-IIb", nullable=False)
    licencia_vencimiento = Column(Date, nullable=False)
    telefono = Column(String(30), nullable=True)
    email = Column(String(100), nullable=True)
    estado = Column(String(30), default=EstadoConductor.ACTIVO.value, nullable=False)

    creado_en = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    viajes = relationship("Viaje", back_populates="conductor")
    cargas_combustible = relationship("CargaCombustible", back_populates="conductor")
