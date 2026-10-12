from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.core.database import get_db
from app.models.viaje import Viaje, EstadoViaje
from app.models.vehiculo import Vehiculo, EstadoVehiculo
from app.models.conductor import Conductor, EstadoConductor
from app.schemas.viaje import ViajeCreate, ViajeUpdate, ViajeResponse

router = APIRouter(prefix="/viajes", tags=["Viajes y Rutas"])


@router.get("", response_model=List[ViajeResponse])
def listar_viajes(
    estado: Optional[str] = None,
    vehiculo_id: Optional[int] = None,
    conductor_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Viaje)
    if estado:
        query = query.filter(Viaje.estado == estado)
    if vehiculo_id:
        query = query.filter(Viaje.vehiculo_id == vehiculo_id)
    if conductor_id:
        query = query.filter(Viaje.conductor_id == conductor_id)
    return query.order_by(Viaje.fecha_salida.desc()).all()


@router.post("", response_model=ViajeResponse, status_code=status.HTTP_201_CREATED)
def crear_viaje(viaje_in: ViajeCreate, db: Session = Depends(get_db)):
    # Validar vehículo y conductor
    vehiculo = db.query(Vehiculo).filter(Vehiculo.id == viaje_in.vehiculo_id).first()
    if not vehiculo:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    conductor = db.query(Conductor).filter(Conductor.id == viaje_in.conductor_id).first()
    if not conductor:
        raise HTTPException(status_code=404, detail="Conductor no encontrado")

    # Validar código único
    existente = db.query(Viaje).filter(Viaje.codigo == viaje_in.codigo).first()
    if existente:
        raise HTTPException(status_code=400, detail=f"Ya existe un viaje con código {viaje_in.codigo}")

    viaje = Viaje(**viaje_in.model_dump())
    db.add(viaje)

    # Si se inicia directamente en curso
    if viaje.estado == EstadoViaje.EN_CURSO.value:
        vehiculo.estado = EstadoVehiculo.EN_RUTA.value
        conductor.estado = EstadoConductor.EN_RUTA.value

    db.commit()
    db.refresh(viaje)
    return viaje


@router.get("/{viaje_id}", response_model=ViajeResponse)
def obtener_viaje(viaje_id: int, db: Session = Depends(get_db)):
    viaje = db.query(Viaje).filter(Viaje.id == viaje_id).first()
    if not viaje:
        raise HTTPException(status_code=404, detail="Viaje no encontrado")
    return viaje


@router.put("/{viaje_id}", response_model=ViajeResponse)
def actualizar_viaje(viaje_id: int, viaje_in: ViajeUpdate, db: Session = Depends(get_db)):
    viaje = db.query(Viaje).filter(Viaje.id == viaje_id).first()
    if not viaje:
        raise HTTPException(status_code=404, detail="Viaje no encontrado")

    update_data = viaje_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(viaje, field, value)

    # Si finaliza el viaje, calcular distancia y actualizar odómetro del vehículo
    if viaje.estado == EstadoViaje.FINALIZADO.value:
        if not viaje.fecha_llegada:
            viaje.fecha_llegada = datetime.utcnow()
        if viaje.odometro_llegada and viaje.odometro_salida:
            viaje.distancia_recorrida = max(0.0, viaje.odometro_llegada - viaje.odometro_salida)

        # Liberar vehículo y conductor
        vehiculo = db.query(Vehiculo).filter(Vehiculo.id == viaje.vehiculo_id).first()
        if vehiculo:
            if viaje.odometro_llegada and viaje.odometro_llegada > vehiculo.odometro_actual:
                vehiculo.odometro_actual = viaje.odometro_llegada
            if vehiculo.estado == EstadoVehiculo.EN_RUTA.value:
                vehiculo.estado = EstadoVehiculo.OPERATIVO.value

        conductor = db.query(Conductor).filter(Conductor.id == viaje.conductor_id).first()
        if conductor and conductor.estado == EstadoConductor.EN_RUTA.value:
            conductor.estado = EstadoConductor.ACTIVO.value

    db.commit()
    db.refresh(viaje)
    return viaje


@router.delete("/{viaje_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_viaje(viaje_id: int, db: Session = Depends(get_db)):
    viaje = db.query(Viaje).filter(Viaje.id == viaje_id).first()
    if not viaje:
        raise HTTPException(status_code=404, detail="Viaje no encontrado")

    db.delete(viaje)
    db.commit()
    return None
