from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime
from app.models.vehiculo import EstadoVehiculo, TipoVehiculo


class VehiculoBase(BaseModel):
    placa: str = Field(..., example="ABC-123")
    marca: str = Field(..., example="Toyota")
    modelo: str = Field(..., example="Hilux 4x4")
    anio: int = Field(..., example=2023)
    tipo: TipoVehiculo = Field(default=TipoVehiculo.CAMIONETA)
    vin: Optional[str] = Field(None, example="9BRBA3BB1K0123456")
    odometro_actual: float = Field(default=0.0, example=45200.5)
    estado: EstadoVehiculo = Field(default=EstadoVehiculo.OPERATIVO)
    combustible_tipo: str = Field(default="diesel", example="diesel")
    soat_vencimiento: Optional[date] = None
    revision_tecnica_vencimiento: Optional[date] = None


class VehiculoCreate(VehiculoBase):
    pass


class VehiculoUpdate(BaseModel):
    placa: Optional[str] = None
    marca: Optional[str] = None
    modelo: Optional[str] = None
    anio: Optional[int] = None
    tipo: Optional[TipoVehiculo] = None
    vin: Optional[str] = None
    odometro_actual: Optional[float] = None
    estado: Optional[EstadoVehiculo] = None
    combustible_tipo: Optional[str] = None
    soat_vencimiento: Optional[date] = None
    revision_tecnica_vencimiento: Optional[date] = None


class VehiculoResponse(VehiculoBase):
    id: int
    creado_en: datetime
    actualizado_en: Optional[datetime] = None

    class Config:
        from_attributes = True
