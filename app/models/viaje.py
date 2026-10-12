from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class EstadoViaje(str, enum.Enum):
    PROGRAMADO = "programado"
    EN_CURSO = "en_curso"
    FINALIZADO = "finalizado"
    CANCELADO = "cancelado"


class Viaje(Base):
    __tablename__ = "viajes"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(30), unique=True, index=True, nullable=False)
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id", ondelete="RESTRICT"), nullable=False)
    conductor_id = Column(Integer, ForeignKey("conductores.id", ondelete="RESTRICT"), nullable=False)

    origen = Column(String(100), nullable=False)
    destino = Column(String(100), nullable=False)
    
    fecha_salida = Column(DateTime, nullable=False)
    fecha_llegada = Column(DateTime, nullable=True)

    odometro_salida = Column(Float, nullable=False)
    odometro_llegada = Column(Float, nullable=True)
    distancia_recorrida = Column(Float, default=0.0, nullable=True)

    estado = Column(String(30), default=EstadoViaje.PROGRAMADO.value, nullable=False)
    observaciones = Column(Text, nullable=True)
    
    creado_en = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    vehiculo = relationship("Vehiculo", back_populates="viajes")
    conductor = relationship("Conductor", back_populates="viajes")
