from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import date, datetime
from app.models.conductor import EstadoConductor


class ConductorBase(BaseModel):
    nombres: str = Field(..., example="Carlos Alberto")
    apellidos: str = Field(..., example="Ramírez Paredes")
    dni: str = Field(..., example="45892147")
    licencia_numero: str = Field(..., example="Q45892147")
    licencia_categoria: str = Field(default="A-IIb", example="A-IIb")
    licencia_vencimiento: date
    telefono: Optional[str] = Field(None, example="+51 987 654 321")
    email: Optional[str] = Field(None, example="carlos.ramirez@acrflota.com")
    estado: EstadoConductor = Field(default=EstadoConductor.ACTIVO)


class ConductorCreate(ConductorBase):
    pass


class ConductorUpdate(BaseModel):
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    dni: Optional[str] = None
    licencia_numero: Optional[str] = None
    licencia_categoria: Optional[str] = None
    licencia_vencimiento: Optional[date] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    estado: Optional[EstadoConductor] = None


class ConductorResponse(ConductorBase):
    id: int
    creado_en: datetime

    class Config:
        from_attributes = True
