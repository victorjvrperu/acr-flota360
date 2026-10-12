from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.models.combustible import CargaCombustible
from app.models.vehiculo import Vehiculo
from app.schemas.combustible import CargaCombustibleCreate, CargaCombustibleResponse
from app.services.flota_service import FlotaService

router = APIRouter(prefix="/combustible", tags=["Combustible"])


@router.get("", response_model=List[CargaCombustibleResponse])
def listar_cargas_combustible(
    vehiculo_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(CargaCombustible)
    if vehiculo_id:
        query = query.filter(CargaCombustible.vehiculo_id == vehiculo_id)
    return query.order_by(CargaCombustible.fecha.desc(), CargaCombustible.id.desc()).all()


@router.post("", response_model=CargaCombustibleResponse, status_code=status.HTTP_201_CREATED)
def registrar_carga(carga_in: CargaCombustibleCreate, db: Session = Depends(get_db)):
    vehiculo = db.query(Vehiculo).filter(Vehiculo.id == carga_in.vehiculo_id).first()
    if not vehiculo:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    carga = FlotaService.registrar_carga_combustible(db, carga_in.model_dump())
    return carga


@router.delete("/{carga_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_carga(carga_id: int, db: Session = Depends(get_db)):
    carga = db.query(CargaCombustible).filter(CargaCombustible.id == carga_id).first()
    if not carga:
        raise HTTPException(status_code=404, detail="Registro de combustible no encontrado")

    db.delete(carga)
    db.commit()
    return None
