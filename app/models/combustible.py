from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class CargaCombustible(Base):
    __tablename__ = "cargas_combustible"

    id = Column(Integer, primary_key=True, index=True)
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id", ondelete="CASCADE"), nullable=False)
    conductor_id = Column(Integer, ForeignKey("conductores.id", ondelete="SET NULL"), nullable=True)
    
    fecha = Column(Date, nullable=False)
    cantidad = Column(Float, nullable=False)  # Litros o Galones
    unidad_medida = Column(String(10), default="galones", nullable=False)
    precio_unitario = Column(Float, nullable=False)
    costo_total = Column(Float, nullable=False)
    odometro = Column(Float, nullable=False)
    estacion = Column(String(100), nullable=True)
    rendimiento_km_unidad = Column(Float, nullable=True)  # km por galón o litro

    creado_en = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    vehiculo = relationship("Vehiculo", back_populates="cargas_combustible")
    conductor = relationship("Conductor", back_populates="cargas_combustible")
