from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.database import get_db
from app.models.heavytrack import MaquinariaEquipo, Proyecto, Personal, EstadoOperativo
from app.schemas.heavytrack import BatchSyncRequest, BatchSyncResponse
from app.services.heavytrack_service import HeavyTrackService

router = APIRouter(prefix="", tags=["Sincronización Offline-First"])


@router.post("/api/sync/batch", response_model=BatchSyncResponse)
@router.post("/api/v1/sync/batch", response_model=BatchSyncResponse)
def sincronizar_cola_offline(
    batch: BatchSyncRequest,
    db: Session = Depends(get_db)
):
    """
    Endpoint principal para recibir y procesar en lote todos los turnos,
    abastecimientos de combustible e incidentes capturados sin conexión en campo.
    Garantiza idempotencia mediante `uuid_local`.
    """
    try:
        return HeavyTrackService.procesar_sync_batch(db, batch)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fallo en el procesamiento de lote: {str(e)}"
        )


@router.get("/api/sync/catalogos")
@router.get("/api/v1/sync/catalogos")
def descargar_catalogos_offline(db: Session = Depends(get_db)):
    """
    Descarga los catálogos base para sincronizar el almacén local IndexedDB
    en el móvil del operador y permitir la operación 100% sin señal.
    """
    equipos = db.query(MaquinariaEquipo).all()
    proyectos = db.query(Proyecto).filter(Proyecto.estado == "activo").all()
    operadores = db.query(Personal).filter(Personal.estado == "activo").all()

    equipos_payload = []
    for eq in equipos:
        color, horas_restantes = HeavyTrackService.calcular_semaforo_equipo(eq)
        proyecto_nom = eq.proyecto_actual.nombre if eq.proyecto_actual else "En Base / Taller"
        operador_nom = f"{eq.operador_asignado.nombres} {eq.operador_asignado.apellidos}" if eq.operador_asignado else "Sin Asignar"
        equipos_payload.append({
            "id": eq.id,
            "nombre": eq.nombre,
            "codigo_interno": eq.codigo_interno,
            "placa": eq.placa,
            "tipo": eq.tipo,
            "tipo_control": eq.tipo_control or "HOROMETRO",
            "marca": eq.marca,
            "modelo": eq.modelo,
            "horometro_actual": eq.horometro_actual or 0.0,
            "odometro_actual": eq.odometro_actual or 0.0,
            "horometro_proximo_servicio": eq.horometro_proximo_servicio,
            "horas_restantes": horas_restantes,
            "semaforo": color,
            "proyecto_id": eq.proyecto_actual_id,
            "proyecto_nombre": proyecto_nom,
            "operador_asignado_id": eq.operador_asignado_id,
            "operador_asignado_nombre": operador_nom,
            "estado_operativo": eq.estado_operativo
        })

    return {
        "timestamp": datetime.utcnow(),
        "equipos": equipos_payload,
        "proyectos": [
            {
                "id": p.id,
                "codigo": p.codigo,
                "nombre": p.nombre,
                "ubicacion": p.ubicacion,
                "equipos_count": len(p.equipos) if p.equipos else 0
            }
            for p in proyectos
        ],
        "operadores": [
            {
                "id": op.id,
                "dni": op.dni,
                "nombres": op.nombres,
                "apellidos": op.apellidos,
                "nombre_completo": f"{op.nombres} {op.apellidos}",
                "brevete_numero": op.brevete_numero,
                "brevete_categoria": op.brevete_categoria or "A-IIIc",
                "brevete_vencimiento": op.brevete_vencimiento.strftime("%Y-%m-%d") if op.brevete_vencimiento else None,
                "pin_acceso": op.pin_acceso or "1234",
                "rol": op.rol
            }
            for op in operadores
        ]
    }
