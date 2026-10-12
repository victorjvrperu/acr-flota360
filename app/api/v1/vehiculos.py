from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.models.vehiculo import Vehiculo, EstadoVehiculo
from app.schemas.vehiculo import VehiculoCreate, VehiculoUpdate, VehiculoResponse

router = APIRouter(prefix="/vehiculos", tags=["Vehículos"])


@router.get("", response_model=List[VehiculoResponse])
def listar_vehiculos(
    estado: Optional[str] = None,
    tipo: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Vehiculo)
    if estado:
        query = query.filter(Vehiculo.estado == estado)
    if tipo:
        query = query.filter(Vehiculo.tipo == tipo)
    return query.order_by(Vehiculo.id.desc()).all()


@router.post("", response_model=VehiculoResponse, status_code=status.HTTP_201_CREATED)
def crear_vehiculo(vehiculo_in: VehiculoCreate, db: Session = Depends(get_db)):
    # Verificar placa única
    existente = db.query(Vehiculo).filter(Vehiculo.placa == vehiculo_in.placa.upper().strip()).first()
    if existente:
        raise HTTPException(status_code=400, detail=f"Ya existe un vehículo con la placa {vehiculo_in.placa}")

    datos = vehiculo_in.model_dump()
    datos["placa"] = datos["placa"].upper().strip()
    vehiculo = Vehiculo(**datos)
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo


@router.get("/{vehiculo_id}", response_model=VehiculoResponse)
def obtener_vehiculo(vehiculo_id: int, db: Session = Depends(get_db)):
    vehiculo = db.query(Vehiculo).filter(Vehiculo.id == vehiculo_id).first()
    if not vehiculo:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    return vehiculo


@router.put("/{vehiculo_id}", response_model=VehiculoResponse)
def actualizar_vehiculo(vehiculo_id: int, vehiculo_in: VehiculoUpdate, db: Session = Depends(get_db)):
    vehiculo = db.query(Vehiculo).filter(Vehiculo.id == vehiculo_id).first()
    if not vehiculo:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    update_data = vehiculo_in.model_dump(exclude_unset=True)
    if "placa" in update_data and update_data["placa"]:
        update_data["placa"] = update_data["placa"].upper().strip()

    for field, value in update_data.items():
        setattr(vehiculo, field, value)

    db.commit()
    db.refresh(vehiculo)
    return vehiculo


@router.delete("/{vehiculo_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_vehiculo(vehiculo_id: int, db: Session = Depends(get_db)):
    vehiculo = db.query(Vehiculo).filter(Vehiculo.id == vehiculo_id).first()
    if not vehiculo:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    db.delete(vehiculo)
    db.commit()
    return None
