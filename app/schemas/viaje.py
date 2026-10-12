from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.models.viaje import EstadoViaje


class ViajeBase(BaseModel):
    codigo: str = Field(..., example="VIA-2026-001")
    vehiculo_id: int
    conductor_id: int
    origen: str = Field(..., example="Almacén Central Lima")
    destino: str = Field(..., example="Sede Operativa Callao")
    fecha_salida: datetime
    fecha_llegada: Optional[datetime] = None
    odometro_salida: float = Field(..., ge=0, example=45200.0)
    odometro_llegada: Optional[float] = None
    distancia_recorrida: Optional[float] = 0.0
    estado: EstadoViaje = Field(default=EstadoViaje.PROGRAMADO)
    observaciones: Optional[str] = None


class ViajeCreate(ViajeBase):
    pass


class ViajeUpdate(BaseModel):
    vehiculo_id: Optional[int] = None
    conductor_id: Optional[int] = None
    origen: Optional[str] = None
    destino: Optional[str] = None
    fecha_salida: Optional[datetime] = None
    fecha_llegada: Optional[datetime] = None
    odometro_salida: Optional[float] = None
    odometro_llegada: Optional[float] = None
    distancia_recorrida: Optional[float] = None
    estado: Optional[EstadoViaje] = None
    observaciones: Optional[str] = None


class ViajeResponse(ViajeBase):
    id: int
    creado_en: datetime

    class Config:
        from_attributes = True
