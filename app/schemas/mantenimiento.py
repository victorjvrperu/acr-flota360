from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime
from app.models.mantenimiento import TipoMantenimiento, EstadoMantenimiento


class MantenimientoBase(BaseModel):
    vehiculo_id: int
    tipo: TipoMantenimiento = Field(default=TipoMantenimiento.PREVENTIVO)
    descripcion: str = Field(..., example="Cambio de aceite, filtro de combustible y revisión de frenos")
    taller: Optional[str] = Field(None, example="Taller Central ACR")
    costo: float = Field(default=0.0, example=450.0)
    odometro_servicio: Optional[float] = Field(None, example=50000.0)
    fecha_programada: date
    fecha_completada: Optional[date] = None
    estado: EstadoMantenimiento = Field(default=EstadoMantenimiento.PROGRAMADO)


class MantenimientoCreate(MantenimientoBase):
    pass


class MantenimientoUpdate(BaseModel):
    vehiculo_id: Optional[int] = None
    tipo: Optional[TipoMantenimiento] = None
    descripcion: Optional[str] = None
    taller: Optional[str] = None
    costo: Optional[float] = None
    odometro_servicio: Optional[float] = None
    fecha_programada: Optional[date] = None
    fecha_completada: Optional[date] = None
    estado: Optional[EstadoMantenimiento] = None


class MantenimientoResponse(MantenimientoBase):
    id: int
    creado_en: datetime

    class Config:
        from_attributes = True
