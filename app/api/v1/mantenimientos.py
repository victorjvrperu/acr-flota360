from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.models.mantenimiento import Mantenimiento, EstadoMantenimiento
from app.models.vehiculo import Vehiculo, EstadoVehiculo
from app.schemas.mantenimiento import MantenimientoCreate, MantenimientoUpdate, MantenimientoResponse

router = APIRouter(prefix="/mantenimientos", tags=["Mantenimientos"])


@router.get("", response_model=List[MantenimientoResponse])
def listar_mantenimientos(
    estado: Optional[str] = None,
    vehiculo_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Mantenimiento)
    if estado:
        query = query.filter(Mantenimiento.estado == estado)
    if vehiculo_id:
        query = query.filter(Mantenimiento.vehiculo_id == vehiculo_id)
    return query.order_by(Mantenimiento.fecha_programada.desc()).all()


@router.post("", response_model=MantenimientoResponse, status_code=status.HTTP_201_CREATED)
def crear_mantenimiento(mant_in: MantenimientoCreate, db: Session = Depends(get_db)):
    vehiculo = db.query(Vehiculo).filter(Vehiculo.id == mant_in.vehiculo_id).first()
    if not vehiculo:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    mant = Mantenimiento(**mant_in.model_dump())
    db.add(mant)

    # Si pasa a taller, actualizar estado del vehículo
    if mant.estado == EstadoMantenimiento.EN_TALLER.value:
        vehiculo.estado = EstadoVehiculo.MANTENIMIENTO.value

    db.commit()
    db.refresh(mant)
    return mant


@router.get("/{mantenimiento_id}", response_model=MantenimientoResponse)
def obtener_mantenimiento(mantenimiento_id: int, db: Session = Depends(get_db)):
    mant = db.query(Mantenimiento).filter(Mantenimiento.id == mantenimiento_id).first()
    if not mant:
        raise HTTPException(status_code=404, detail="Mantenimiento no encontrado")
    return mant


@router.put("/{mantenimiento_id}", response_model=MantenimientoResponse)
def actualizar_mantenimiento(mantenimiento_id: int, mant_in: MantenimientoUpdate, db: Session = Depends(get_db)):
    mant = db.query(Mantenimiento).filter(Mantenimiento.id == mantenimiento_id).first()
    if not mant:
        raise HTTPException(status_code=404, detail="Mantenimiento no encontrado")

    update_data = mant_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(mant, field, value)

    # Si se completó, retornar vehículo a operativo si estaba en mantenimiento
    if mant.estado == EstadoMantenimiento.COMPLETADO.value:
        vehiculo = db.query(Vehiculo).filter(Vehiculo.id == mant.vehiculo_id).first()
        if vehiculo and vehiculo.estado == EstadoVehiculo.MANTENIMIENTO.value:
            vehiculo.estado = EstadoVehiculo.OPERATIVO.value

    db.commit()
    db.refresh(mant)
    return mant


@router.delete("/{mantenimiento_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_mantenimiento(mantenimiento_id: int, db: Session = Depends(get_db)):
    mant = db.query(Mantenimiento).filter(Mantenimiento.id == mantenimiento_id).first()
    if not mant:
        raise HTTPException(status_code=404, detail="Mantenimiento no encontrado")

    db.delete(mant)
    db.commit()
    return None
