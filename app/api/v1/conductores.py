from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.models.conductor import Conductor, EstadoConductor
from app.schemas.conductor import ConductorCreate, ConductorUpdate, ConductorResponse

router = APIRouter(prefix="/conductores", tags=["Conductores"])


@router.get("", response_model=List[ConductorResponse])
def listar_conductores(estado: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Conductor)
    if estado:
        query = query.filter(Conductor.estado == estado)
    return query.order_by(Conductor.id.desc()).all()


@router.post("", response_model=ConductorResponse, status_code=status.HTTP_201_CREATED)
def crear_conductor(conductor_in: ConductorCreate, db: Session = Depends(get_db)):
    existente_dni = db.query(Conductor).filter(Conductor.dni == conductor_in.dni.strip()).first()
    if existente_dni:
        raise HTTPException(status_code=400, detail=f"Ya existe un conductor con DNI {conductor_in.dni}")

    conductor = Conductor(**conductor_in.model_dump())
    db.add(conductor)
    db.commit()
    db.refresh(conductor)
    return conductor


@router.get("/{conductor_id}", response_model=ConductorResponse)
def obtener_conductor(conductor_id: int, db: Session = Depends(get_db)):
    conductor = db.query(Conductor).filter(Conductor.id == conductor_id).first()
    if not conductor:
        raise HTTPException(status_code=404, detail="Conductor no encontrado")
    return conductor


@router.put("/{conductor_id}", response_model=ConductorResponse)
def actualizar_conductor(conductor_id: int, conductor_in: ConductorUpdate, db: Session = Depends(get_db)):
    conductor = db.query(Conductor).filter(Conductor.id == conductor_id).first()
    if not conductor:
        raise HTTPException(status_code=404, detail="Conductor no encontrado")

    update_data = conductor_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(conductor, field, value)

    db.commit()
    db.refresh(conductor)
    return conductor


@router.delete("/{conductor_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_conductor(conductor_id: int, db: Session = Depends(get_db)):
    conductor = db.query(Conductor).filter(Conductor.id == conductor_id).first()
    if not conductor:
        raise HTTPException(status_code=404, detail="Conductor no encontrado")

    db.delete(conductor)
    db.commit()
    return None
