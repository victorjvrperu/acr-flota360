from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.core.database import Base


class TipoMantenimiento(str, enum.Enum):
    PREVENTIVO = "preventivo"
    CORRECTIVO = "correctivo"
    INSPECCION = "inspeccion"


class EstadoMantenimiento(str, enum.Enum):
    PROGRAMADO = "programado"
    EN_TALLER = "en_taller"
    COMPLETADO = "completado"
    CANCELADO = "cancelado"


class Mantenimiento(Base):
    __tablename__ = "mantenimientos"

    id = Column(Integer, primary_key=True, index=True)
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id", ondelete="CASCADE"), nullable=False)
    tipo = Column(String(30), default=TipoMantenimiento.PREVENTIVO.value, nullable=False)
    descripcion = Column(Text, nullable=False)
    taller = Column(String(100), nullable=True)
    costo = Column(Float, default=0.0, nullable=False)
    odometro_servicio = Column(Float, nullable=True)
    fecha_programada = Column(Date, nullable=False)
    fecha_completada = Column(Date, nullable=True)
    estado = Column(String(30), default=EstadoMantenimiento.PROGRAMADO.value, nullable=False)

    creado_en = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    vehiculo = relationship("Vehiculo", back_populates="mantenimientos")
