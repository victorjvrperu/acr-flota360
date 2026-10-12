from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime


class CargaCombustibleBase(BaseModel):
    vehiculo_id: int
    conductor_id: Optional[int] = None
    fecha: date
    cantidad: float = Field(..., gt=0, example=15.5)
    unidad_medida: str = Field(default="galones", example="galones")
    precio_unitario: float = Field(..., gt=0, example=18.50)
    costo_total: float = Field(..., gt=0, example=286.75)
    odometro: float = Field(..., ge=0, example=45200.0)
    estacion: Optional[str] = Field(None, example="Repsol San Isidro")
    rendimiento_km_unidad: Optional[float] = None


class CargaCombustibleCreate(CargaCombustibleBase):
    pass


class CargaCombustibleResponse(CargaCombustibleBase):
    id: int
    creado_en: datetime

    class Config:
        from_attributes = True
