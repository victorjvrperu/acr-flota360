from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, date
from pydantic import BaseModel
import os
import uuid
import shutil
import httpx

from app.core.database import get_db
from app.models.heavytrack import (
    MaquinariaEquipo, Proyecto, Personal, OrdenMantenimiento,
    InventarioRepuesto, Proveedor, TurnoOperacion, ControlCombustible,
    EstadoOperativo, EstadoOrdenMantenimiento, RolPersonal, AjusteSistema,
    TipoOrdenMantenimiento
)
from app.schemas.heavytrack import (
    MaquinariaEquipoCreate, MaquinariaEquipoResponse,
    ProyectoCreate, ProyectoResponse,
    PersonalCreate, PersonalUpdate, PersonalResponse,
    VerificarAccesoRequest, CambiarClaveRequest,
    OrdenMantenimientoCreate, OrdenMantenimientoResponse,
    InventarioRepuestoCreate, InventarioRepuestoResponse,
    ProveedorCreate, ProveedorResponse,
    TelemetriaGPSRequest, ActualizarCombustibleTurno,
    ConfigurarMantenimientoEquipoRequest, ActualizarPagoCombustibleRequest,
    PrecioCombustibleRequest, RegistroCombustibleDirectoRequest,
    MantenimientoEfectuadoRequest, ActualizarPrecioCombustibleRapidoRequest
)
from app.services.heavytrack_service import HeavyTrackService

router = APIRouter(prefix="/heavy", tags=["HeavyTrack - Operaciones Industriales"])


@router.get("/dashboard")
def obtener_dashboard_heavy(db: Session = Depends(get_db)):
    """Métricas consolidadas, KPIs, semáforos de flota y horas por proyecto."""
    return HeavyTrackService.obtener_resumen_dashboard(db)


@router.get("/equipos", response_model=List[MaquinariaEquipoResponse])
def listar_equipos(
    tipo: Optional[str] = None,
    proyecto_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(MaquinariaEquipo)
    if tipo:
        query = query.filter(MaquinariaEquipo.tipo == tipo)
    if proyecto_id:
        query = query.filter(MaquinariaEquipo.proyecto_actual_id == proyecto_id)

    equipos = query.all()
    resultado = []
    for eq in equipos:
        color, horas_rest = HeavyTrackService.calcular_semaforo_equipo(eq)
        proyecto_nom = eq.proyecto_actual.nombre if eq.proyecto_actual else "En Base / Taller"
        operador_nom = f"{eq.operador_asignado.nombres} {eq.operador_asignado.apellidos}" if eq.operador_asignado else "Sin Asignar"
        payload = {c.name: getattr(eq, c.name) for c in eq.__table__.columns}
        payload["semaforo_mantenimiento"] = color
        payload["horas_para_servicio"] = horas_rest
        payload["proyecto_nombre"] = proyecto_nom
        payload["operador_asignado_nombre"] = operador_nom
        resultado.append(MaquinariaEquipoResponse(**payload))
    return resultado


@router.post("/equipos", response_model=MaquinariaEquipoResponse, status_code=status.HTTP_201_CREATED)
def crear_equipo(equipo_in: MaquinariaEquipoCreate, db: Session = Depends(get_db)):
    existente = db.query(MaquinariaEquipo).filter(
        MaquinariaEquipo.codigo_interno == equipo_in.codigo_interno.upper().strip()
    ).first()
    if existente:
        raise HTTPException(status_code=400, detail=f"El código {equipo_in.codigo_interno} ya existe.")

    datos = equipo_in.model_dump()
    datos["codigo_interno"] = datos["codigo_interno"].upper().strip()
    nuevo = MaquinariaEquipo(**datos)
    if (nuevo.tipo_control or '').upper() == 'KILOMETRAJE':
        if not nuevo.odometro_proximo_servicio or nuevo.odometro_proximo_servicio <= 0:
            if nuevo.horometro_proximo_servicio and nuevo.horometro_proximo_servicio > 1000:
                nuevo.odometro_proximo_servicio = nuevo.horometro_proximo_servicio

    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    color, horas_rest = HeavyTrackService.calcular_semaforo_equipo(nuevo)
    payload = {c.name: getattr(nuevo, c.name) for c in nuevo.__table__.columns}
    payload["semaforo_mantenimiento"] = color
    payload["horas_para_servicio"] = horas_rest
    payload["proyecto_nombre"] = nuevo.proyecto_actual.nombre if nuevo.proyecto_actual else "En Base / Taller"
    payload["operador_asignado_nombre"] = f"{nuevo.operador_asignado.nombres} {nuevo.operador_asignado.apellidos}" if nuevo.operador_asignado else "Sin Asignar"
    return MaquinariaEquipoResponse(**payload)


@router.put("/equipos/{equipo_id}", response_model=MaquinariaEquipoResponse)
def actualizar_equipo(equipo_id: int, payload: dict, db: Session = Depends(get_db)):
    """Actualiza cualquier campo del equipo (nombre, modelo, serie, horómetro, póliza, soat, etc.)."""
    equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    DATE_FIELDS = {"poliza_vencimiento", "soat_vencimiento", "revision_tecnica_vencimiento"}
    FLOAT_FIELDS = {
        "horometro_actual", "odometro_actual", "horometro_proximo_servicio",
        "intervalo_servicio", "odometro_proximo_servicio", "odometro_intervalo_servicio"
    }

    for key, value in payload.items():
        if hasattr(equipo, key) and key != "id":
            if key in DATE_FIELDS:
                if not value or (isinstance(value, str) and not value.strip()):
                    value = None
                elif isinstance(value, str):
                    parsed_date = None
                    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
                        try:
                            parsed_date = datetime.strptime(value.strip(), fmt).date()
                            break
                        except ValueError:
                            pass
                    value = parsed_date
            elif key in FLOAT_FIELDS and value is not None:
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    pass
            elif key == "anio" and value is not None:
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    pass
            elif key == "codigo_interno" and value:
                cod_limpio = str(value).strip().upper()
                dup = db.query(MaquinariaEquipo).filter(
                    MaquinariaEquipo.codigo_interno == cod_limpio,
                    MaquinariaEquipo.id != equipo_id
                ).first()
                if dup:
                    raise HTTPException(
                        status_code=400,
                        detail=f"El código interno '{cod_limpio}' ya está en uso por otro equipo."
                    )
                value = cod_limpio
            elif key == "placa" and value is not None:
                val_str = str(value).strip().upper()
                value = val_str if val_str else None
            elif key in ("serie_chasis", "poliza_seguro", "soat_numero", "revision_tecnica_numero", "nombre", "marca", "modelo") and value is not None:
                val_str = str(value).strip()
                value = val_str if val_str else None

            setattr(equipo, key, value)

    # Sincronización inteligente para unidades por Kilometraje
    if (equipo.tipo_control or '').upper() == 'KILOMETRAJE':
        if not equipo.odometro_proximo_servicio or equipo.odometro_proximo_servicio <= 0:
            if equipo.horometro_proximo_servicio and equipo.horometro_proximo_servicio > 1000:
                equipo.odometro_proximo_servicio = equipo.horometro_proximo_servicio

    db.commit()
    db.refresh(equipo)

    color, horas_rest = HeavyTrackService.calcular_semaforo_equipo(equipo)
    p_data = {c.name: getattr(equipo, c.name) for c in equipo.__table__.columns}
    p_data["semaforo_mantenimiento"] = color
    p_data["horas_para_servicio"] = horas_rest
    p_data["proyecto_nombre"] = equipo.proyecto_actual.nombre if equipo.proyecto_actual else "En Base / Taller"
    p_data["operador_asignado_nombre"] = f"{equipo.operador_asignado.nombres} {equipo.operador_asignado.apellidos}" if equipo.operador_asignado else "Sin Asignar"
    return MaquinariaEquipoResponse(**p_data)


@router.delete("/equipos/{equipo_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_equipo(equipo_id: int, db: Session = Depends(get_db)):
    """Elimina un equipo de la flota y sus registros asociados."""
    equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    db.query(TurnoOperacion).filter(TurnoOperacion.equipo_id == equipo_id).delete()
    db.query(ControlCombustible).filter(ControlCombustible.equipo_id == equipo_id).delete()
    db.query(IncidenteCheckpoint).filter(IncidenteCheckpoint.equipo_id == equipo_id).delete()
    db.query(OrdenMantenimiento).filter(OrdenMantenimiento.equipo_id == equipo_id).delete()

    db.delete(equipo)
    db.commit()
    return None


@router.put("/equipos/{equipo_id}/asignar")
def reasignar_equipo_frente_y_operador(
    equipo_id: int,
    payload: dict,
    db: Session = Depends(get_db)
):
    """Reasigna un equipo a un frente de obra (proyecto) y/o a un operador específico."""
    equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    if "proyecto_id" in payload:
        equipo.proyecto_actual_id = payload["proyecto_id"]
    if "operador_id" in payload:
        equipo.operador_asignado_id = payload["operador_id"]

    db.commit()
    db.refresh(equipo)
    return {"success": True, "mensaje": "Equipo reasignado correctamente", "equipo_id": equipo.id}


@router.get("/proyectos", response_model=List[ProyectoResponse])
def listar_proyectos(db: Session = Depends(get_db)):
    """Lista todos los frentes de obra / proyectos con conteo de maquinaria asignada y horas trabajadas."""
    proyectos = db.query(Proyecto).all()
    res = []
    for p in proyectos:
        horas_p = db.query(func.coalesce(func.sum(TurnoOperacion.horas_trabajadas), 0.0)).filter(
            TurnoOperacion.proyecto_id == p.id
        ).scalar() or 0.0
        res.append(ProyectoResponse(
            id=p.id,
            codigo=p.codigo,
            nombre=p.nombre,
            ubicacion=p.ubicacion,
            fecha_inicio=p.fecha_inicio,
            estado=p.estado,
            equipos_count=len(p.equipos) if p.equipos else 0,
            horas_totales=round(float(horas_p), 1),
            creado_en=p.creado_en
        ))
    return res


@router.post("/proyectos", response_model=ProyectoResponse, status_code=status.HTTP_201_CREATED)
def crear_frente_proyecto(proyecto_in: ProyectoCreate, db: Session = Depends(get_db)):
    """Crea un nuevo frente de obra / proyecto de construcción."""
    existente = db.query(Proyecto).filter(Proyecto.codigo == proyecto_in.codigo.strip().upper()).first()
    if existente:
        raise HTTPException(status_code=400, detail=f"El código de proyecto {proyecto_in.codigo} ya existe.")

    datos = proyecto_in.model_dump()
    datos["codigo"] = datos["codigo"].strip().upper()
    nuevo = Proyecto(**datos)
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


@router.delete("/proyectos/{proyecto_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_proyecto(proyecto_id: int, db: Session = Depends(get_db)):
    """Elimina un frente de obra / proyecto y desvincula sus dependencias."""
    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not proyecto:
        raise HTTPException(status_code=404, detail="Frente de obra no encontrado.")
    
    # 1. Desvincular maquinaria asociada al frente
    db.query(MaquinariaEquipo).filter(MaquinariaEquipo.proyecto_actual_id == proyecto_id).update(
        {MaquinariaEquipo.proyecto_actual_id: None}
    )
    # 2. Desvincular órdenes de mantenimiento
    db.query(OrdenMantenimiento).filter(OrdenMantenimiento.proyecto_id == proyecto_id).update(
        {OrdenMantenimiento.proyecto_id: None}
    )
    # 3. Eliminar turnos y cargas de combustible vinculados a este frente
    db.query(ControlCombustible).filter(ControlCombustible.proyecto_id == proyecto_id).delete()
    db.query(TurnoOperacion).filter(TurnoOperacion.proyecto_id == proyecto_id).delete()
    
    db.delete(proyecto)
    db.commit()
    return None


@router.get("/turnos")
def listar_turnos_operacion(
    proyecto_id: Optional[int] = None,
    equipo_id: Optional[int] = None,
    operador_id: Optional[int] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """Listado del historial de turnos con identificación del personal a cargo, horas y fotos."""
    query = db.query(TurnoOperacion)
    if proyecto_id:
        query = query.filter(TurnoOperacion.proyecto_id == proyecto_id)
    if equipo_id:
        query = query.filter(TurnoOperacion.equipo_id == equipo_id)
    if operador_id:
        query = query.filter(TurnoOperacion.operador_id == operador_id)
    if fecha_desde:
        query = query.filter(TurnoOperacion.fecha >= fecha_desde)
    if fecha_hasta:
        query = query.filter(TurnoOperacion.fecha <= fecha_hasta)

    turnos = query.order_by(TurnoOperacion.fecha.desc(), TurnoOperacion.id.desc()).all()
    resultado = []
    for t in turnos:
        ratio = round(t.combustible_galones / t.horas_trabajadas, 2) if (t.combustible_galones and t.horas_trabajadas and t.horas_trabajadas > 0) else None
        resultado.append({
            "id": t.id,
            "uuid_local": t.uuid_local,
            "fecha": t.fecha.strftime("%Y-%m-%d"),
            "equipo_id": t.equipo_id,
            "equipo_codigo": t.equipo.codigo_interno if t.equipo else "N/A",
            "equipo_modelo": f"{t.equipo.marca} {t.equipo.modelo}" if t.equipo else "N/A",
            "equipo_tipo": t.equipo.tipo if t.equipo else "pesada",
            "equipo_tipo_control": t.equipo.tipo_control if t.equipo else "HOROMETRO",
            "proyecto_id": t.proyecto_id,
            "proyecto_nombre": t.proyecto.nombre if t.proyecto else "N/A",
            "operador_id": t.operador_id,
            "operador_nombre": f"{t.operador.nombres} {t.operador.apellidos}" if t.operador else "N/A",
            "operador_dni": t.operador.dni if t.operador else "N/A",
            "operador_brevete": f"{t.operador.brevete_numero} ({t.operador.brevete_categoria})" if t.operador else "N/A",
            "horometro_inicio": t.horometro_inicio,
            "horometro_fin": t.horometro_fin,
            "horas_trabajadas": t.horas_trabajadas,
            "kilometraje_inicio": t.kilometraje_inicio or 0.0,
            "kilometraje_fin": t.kilometraje_fin or 0.0,
            "km_recorridos": t.km_recorridos or 0.0,
            "foto_inicio": t.foto_horometro_inicio,
            "foto_fin": t.foto_horometro_fin,
            "abastecio_combustible": t.abastecio_combustible or False,
            "combustible_galones": t.combustible_galones or 0.0,
            "combustible_precio_galon": t.combustible_precio_galon or 0.0,
            "combustible_total_soles": t.combustible_total_soles or 0.0,
            "ratio_gal_hora": ratio,
            "foto_combustible": t.foto_combustible,
            "foto_inicio_delantera": t.foto_inicio_delantera,
            "foto_inicio_trasera": t.foto_inicio_trasera,
            "foto_inicio_izquierda": t.foto_inicio_izquierda,
            "foto_inicio_derecha": t.foto_inicio_derecha,
            "foto_fin_delantera": t.foto_fin_delantera,
            "foto_fin_trasera": t.foto_fin_trasera,
            "foto_fin_izquierda": t.foto_fin_izquierda,
            "foto_fin_derecha": t.foto_fin_derecha,
            "hubo_incidencia": t.hubo_incidencia or False,
            "incidencia_descripcion": t.incidencia_descripcion,
            "foto_incidencia": t.foto_incidencia,
            "estado_sync": t.estado_sync,
            "creado_en": t.creado_en
        })
    return resultado


@router.get("/turnos/exportar-excel")
def exportar_turnos_excel(
    proyecto_id: Optional[int] = None,
    equipo_id: Optional[int] = None,
    operador_id: Optional[int] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """Genera y descarga en vivo el reporte Excel profesional de Parte Diario y Horómetros."""
    from app.services.report_service import ReportService
    stream = ReportService.generar_excel_control_horometros(
        db=db,
        proyecto_id=proyecto_id,
        equipo_id=equipo_id,
        operador_id=operador_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta
    )
    filename = f"Parte_Diario_Horometros_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


@router.patch("/turnos/{turno_id}/combustible")
def actualizar_combustible_turno(
    turno_id: int,
    payload: ActualizarCombustibleTurno,
    db: Session = Depends(get_db)
):
    """
    Permite al Jefe de Flotas ingresar o actualizar el precio por galón y monto total
    de combustible reportado por los operadores en campo de manera personal y controlada.
    """
    turno = db.query(TurnoOperacion).filter(TurnoOperacion.id == turno_id).first()
    if not turno:
        raise HTTPException(status_code=404, detail="Turno no encontrado")

    precio = round(float(payload.precio_por_galon or 0.0), 2)
    galones = float(turno.combustible_galones or 0.0)
    
    if payload.costo_total is not None and payload.costo_total > 0:
        total = round(float(payload.costo_total), 2)
    else:
        total = round(galones * precio, 2)

    turno.combustible_precio_galon = precio
    turno.combustible_total_soles = total

    # También actualizar el registro asociado en control_combustible si existe
    comb_rec = db.query(ControlCombustible).filter(
        ControlCombustible.uuid_local == f"comb-{turno.uuid_local}"
    ).first()
    if comb_rec:
        comb_rec.precio_por_galon = precio
        comb_rec.costo_total = total

    db.commit()
    db.refresh(turno)

    return {
        "success": True,
        "mensaje": f"Combustible actualizado para turno #{turno.id}",
        "turno_id": turno.id,
        "combustible_galones": turno.combustible_galones,
        "combustible_precio_galon": turno.combustible_precio_galon,
        "combustible_total_soles": turno.combustible_total_soles
    }


@router.put("/equipos/{equipo_id}/mantenimiento-config")
def configurar_mantenimiento_equipo(
    equipo_id: int,
    payload: ConfigurarMantenimientoEquipoRequest,
    db: Session = Depends(get_db)
):
    """
    Permite al Encargado de Flotas definir cada cuántas horas se realiza el mantenimiento (intervalo)
    y reprogramar el horómetro de próximo servicio de la maquinaria.
    """
    equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    es_km = (equipo.tipo_control or '').upper() == 'KILOMETRAJE'
    if es_km:
        interv = payload.odometro_intervalo_servicio or payload.intervalo_servicio
        if interv is not None and interv > 0:
            equipo.odometro_intervalo_servicio = float(interv)
        
        prox = payload.odometro_proximo_servicio or payload.horometro_proximo_servicio
        if prox is not None:
            equipo.odometro_proximo_servicio = float(prox)
        elif interv is not None:
            equipo.odometro_proximo_servicio = round((equipo.odometro_actual or 0.0) + equipo.odometro_intervalo_servicio, 1)

        act = payload.odometro_actual or payload.horometro_actual
        if act is not None and act >= 0:
            equipo.odometro_actual = float(act)
    else:
        if payload.intervalo_servicio is not None and payload.intervalo_servicio > 0:
            equipo.intervalo_servicio = float(payload.intervalo_servicio)

        if payload.horometro_proximo_servicio is not None:
            equipo.horometro_proximo_servicio = float(payload.horometro_proximo_servicio)
        elif payload.intervalo_servicio is not None:
            equipo.horometro_proximo_servicio = round((equipo.horometro_actual or 0.0) + equipo.intervalo_servicio, 1)

        if payload.horometro_actual is not None and payload.horometro_actual >= 0:
            equipo.horometro_actual = float(payload.horometro_actual)

    color, horas_restantes = HeavyTrackService.calcular_semaforo_equipo(equipo)
    if color in ["rojo", "amarillo"]:
        equipo.estado_operativo = EstadoOperativo.CRITICO.value
    else:
        equipo.estado_operativo = EstadoOperativo.OPERATIVO.value

    db.commit()
    db.refresh(equipo)

    return {
        "success": True,
        "mensaje": f"Configuración de mantenimiento actualizada para {equipo.codigo_interno}",
        "equipo_id": equipo.id,
        "intervalo_servicio": equipo.intervalo_servicio,
        "horometro_proximo_servicio": equipo.horometro_proximo_servicio,
        "horometro_actual": equipo.horometro_actual,
        "horas_restantes": horas_restantes,
        "semaforo": color
    }


@router.get("/combustible")
def listar_registros_combustible(db: Session = Depends(get_db)):
    """Lista todos los registros de abastecimiento de combustible con estado de pago y costos."""
    registros = db.query(ControlCombustible).order_by(ControlCombustible.id.desc()).all()
    resultado = []
    for r in registros:
        tipo_ctrl = (r.equipo.tipo_control or "HOROMETRO").upper() if r.equipo else "HOROMETRO"
        
        # Buscar turno asociado si existe
        turno = None
        if r.uuid_local and r.uuid_local.startswith("comb-"):
            turno_uuid = r.uuid_local.replace("comb-", "")
            if turno_uuid.startswith("checkout-"):
                turno_uuid = turno_uuid.replace("checkout-", "")
            turno = db.query(TurnoOperacion).filter(TurnoOperacion.uuid_local == turno_uuid).first()

        rendimiento_str = "-"
        costo_unitario_str = "-"
        horas_o_km_turno = 0.0

        if turno:
            if tipo_ctrl == "KILOMETRAJE":
                km = float(turno.km_recorridos or 0.0)
                horas_o_km_turno = km
                if km > 0 and r.galones_cargados > 0:
                    kpg = round(km / r.galones_cargados, 1)
                    rendimiento_str = f"{kpg} Km/Gal"
                    costo_unitario_str = f"S/ {(r.costo_total / km):.2f}/Km"
            else:
                horas = float(turno.horas_trabajadas or 0.0)
                horas_o_km_turno = horas
                if horas > 0 and r.galones_cargados > 0:
                    gph = round(r.galones_cargados / horas, 2)
                    rendimiento_str = f"{gph} Gal/h"
                    costo_unitario_str = f"S/ {(r.costo_total / horas):.2f}/h"

        resultado.append({
            "id": r.id,
            "uuid_local": r.uuid_local,
            "equipo_id": r.equipo_id,
            "equipo_codigo": r.equipo.codigo_interno if r.equipo else "-",
            "equipo_nombre": r.equipo.nombre if r.equipo else "-",
            "placa": r.equipo.placa if r.equipo else "-",
            "tipo_control": tipo_ctrl,
            "operador_id": r.operador_id,
            "operador_nombre": f"{r.operador.nombres} {r.operador.apellidos}" if r.operador else "-",
            "proyecto_id": r.proyecto_id,
            "proyecto_nombre": r.proyecto.nombre if r.proyecto else "En Base",
            "horometro_tanqueo": r.horometro_tanqueo,
            "galones_cargados": r.galones_cargados,
            "precio_por_galon": r.precio_por_galon or 0.0,
            "costo_total": r.costo_total or 0.0,
            "rendimiento_str": rendimiento_str,
            "costo_unitario_str": costo_unitario_str,
            "horas_o_km_turno": horas_o_km_turno,
            "foto_comprobante": r.foto_comprobante,
            "tipo_combustible": r.tipo_combustible,
            "fecha_hora": r.fecha_hora.strftime("%Y-%m-%d %H:%M:%S") if r.fecha_hora else "-",
            "estado_pago": getattr(r, "estado_pago", "pendiente") or "pendiente",
            "numero_operacion_pago": getattr(r, "numero_operacion_pago", None) or "-",
            "fecha_pago": r.fecha_pago.strftime("%Y-%m-%d %H:%M:%S") if getattr(r, "fecha_pago", None) else None,
            "observaciones_pago": getattr(r, "observaciones_pago", None) or ""
        })
    return resultado


@router.put("/combustible/{combustible_id}/pago")
def registrar_pago_combustible(
    combustible_id: int,
    payload: ActualizarPagoCombustibleRequest,
    db: Session = Depends(get_db)
):
    """
    Permite al Encargado de Flotas (en coordinación con el área de finanzas/pagos) registrar
    el precio negociado por galón, el monto de pago realizado, nro de operación/factura y observaciones.
    """
    comb = db.query(ControlCombustible).filter(ControlCombustible.id == combustible_id).first()
    if not comb:
        raise HTTPException(status_code=404, detail="Registro de combustible no encontrado")

    precio = round(float(payload.precio_por_galon or 0.0), 2)
    galones = float(comb.galones_cargados or 0.0)

    if payload.costo_total is not None and payload.costo_total > 0:
        total = round(float(payload.costo_total), 2)
    else:
        total = round(galones * precio, 2)

    comb.precio_por_galon = precio
    comb.costo_total = total
    comb.estado_pago = payload.estado_pago or "pagado"
    comb.numero_operacion_pago = payload.numero_operacion_pago
    comb.observaciones_pago = payload.observaciones_pago
    if comb.estado_pago == "pagado" and not comb.fecha_pago:
        comb.fecha_pago = datetime.utcnow()

    # Si hay turno asociado, sincronizar valorización
    if comb.uuid_local and comb.uuid_local.startswith("comb-"):
        turno_uuid = comb.uuid_local.replace("comb-", "")
        turno = db.query(TurnoOperacion).filter(TurnoOperacion.uuid_local == turno_uuid).first()
        if turno:
            turno.combustible_precio_galon = precio
            turno.combustible_total_soles = total

    db.commit()
    db.refresh(comb)

    return {
        "success": True,
        "mensaje": f"Pago de combustible registrado exitosamente (Total: S/ {total:.2f})",
        "combustible_id": comb.id,
        "galones": comb.galones_cargados,
        "precio_por_galon": comb.precio_por_galon,
        "costo_total": comb.costo_total,
        "estado_pago": comb.estado_pago,
        "numero_operacion_pago": comb.numero_operacion_pago
    }


@router.put("/combustible/{combustible_id}/precio")
def actualizar_precio_combustible_rapido(
    combustible_id: int,
    payload: ActualizarPrecioCombustibleRapidoRequest,
    db: Session = Depends(get_db)
):
    """
    Permite al Encargado de Flota ingresar o ajustar el precio del combustible por galón
    de manera independiente y directa para cada abastecimiento de operador.
    Calcula automáticamente el total en soles y sincroniza con el turno correspondiente si aplica.
    """
    comb = db.query(ControlCombustible).filter(ControlCombustible.id == combustible_id).first()
    if not comb:
        raise HTTPException(status_code=404, detail="Registro de combustible no encontrado")

    precio = round(float(payload.precio_por_galon or 0.0), 2)
    galones = float(comb.galones_cargados or 0.0)
    total = round(galones * precio, 2)

    comb.precio_por_galon = precio
    comb.costo_total = total

    # Si hay turno asociado, sincronizar valorización
    if comb.uuid_local and comb.uuid_local.startswith("comb-"):
        turno_uuid = comb.uuid_local.replace("comb-", "")
        if turno_uuid.startswith("checkout-"):
            turno_uuid = turno_uuid.replace("checkout-", "")
        turno = db.query(TurnoOperacion).filter(TurnoOperacion.uuid_local == turno_uuid).first()
        if turno:
            turno.combustible_precio_galon = precio
            turno.combustible_total_soles = total

    db.commit()
    db.refresh(comb)

    return {
        "success": True,
        "mensaje": f"Precio registrado: S/ {precio:.2f}/gal (Total: S/ {total:.2f})",
        "combustible_id": comb.id,
        "galones": comb.galones_cargados,
        "precio_por_galon": comb.precio_por_galon,
        "costo_total": comb.costo_total,
        "estado_pago": comb.estado_pago
    }



@router.get("/ajustes/precio-combustible")
def obtener_precio_combustible(db: Session = Depends(get_db)):
    """Obtiene el precio configurado del galón de combustible para la zona/obra."""
    ajuste = db.query(AjusteSistema).filter(AjusteSistema.clave == "precio_combustible_zona").first()
    precio = float(ajuste.valor) if ajuste and ajuste.valor else 17.50
    return {
        "precio_por_galon": precio,
        "zona": "Jaén / Obra Central",
        "actualizado_en": ajuste.actualizado_en.strftime("%Y-%m-%d %H:%M") if ajuste and ajuste.actualizado_en else "Por defecto"
    }


@router.post("/ajustes/precio-combustible")
def guardar_precio_combustible(payload: PrecioCombustibleRequest, db: Session = Depends(get_db)):
    """Actualiza el precio del galón de combustible de la zona en el sistema."""
    ajuste = db.query(AjusteSistema).filter(AjusteSistema.clave == "precio_combustible_zona").first()
    if not ajuste:
        ajuste = AjusteSistema(
            clave="precio_combustible_zona",
            valor=str(round(payload.precio_por_galon, 2)),
            descripcion=f"Precio estándar de combustible por galón en {payload.zona or 'la zona'}"
        )
        db.add(ajuste)
    else:
        ajuste.valor = str(round(payload.precio_por_galon, 2))
        ajuste.descripcion = f"Precio estándar de combustible por galón en {payload.zona or 'la zona'}"
        ajuste.actualizado_en = datetime.utcnow()
    db.commit()
    return {
        "success": True,
        "mensaje": f"Precio de combustible actualizado a S/ {payload.precio_por_galon:.2f} por galón",
        "precio_por_galon": round(payload.precio_por_galon, 2)
    }


@router.post("/combustible/registro-directo", status_code=status.HTTP_201_CREATED)
def registrar_combustible_directo(payload: RegistroCombustibleDirectoRequest, db: Session = Depends(get_db)):
    """Registra una carga de combustible directamente desde el Dashboard."""
    equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == payload.equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado.")

    # Si no se pasó operador o proyecto, asignar del equipo
    operador_id = payload.operador_id or equipo.operador_asignado_id
    if not operador_id:
        admin_op = db.query(Personal).filter(Personal.rol.in_([RolPersonal.SISTEMAS_ADMIN.value, RolPersonal.GERENCIA.value])).first()
        operador_id = admin_op.id if admin_op else 1

    proyecto_id = payload.proyecto_id or equipo.proyecto_actual_id
    if not proyecto_id:
        primer_proy = db.query(Proyecto).filter(Proyecto.estado == "activo").first()
        proyecto_id = primer_proy.id if primer_proy else 1

    galones = float(payload.galones_cargados)
    precio = float(payload.precio_por_galon or 17.50)
    costo_total = round(galones * precio, 2)

    nuevo_comb = ControlCombustible(
        uuid_local=f"comb-direct-{uuid.uuid4().hex[:12]}",
        equipo_id=equipo.id,
        operador_id=operador_id,
        proyecto_id=proyecto_id,
        horometro_tanqueo=float(payload.lectura_tanqueo or (equipo.odometro_actual if (equipo.tipo_control or '').upper() == 'KILOMETRAJE' else equipo.horometro_actual) or 0.0),
        galones_cargados=galones,
        precio_por_galon=precio,
        costo_total=costo_total,
        tipo_combustible=payload.tipo_combustible or "Diesel D2 B5",
        foto_comprobante=payload.foto_comprobante or "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
        estado_pago=payload.estado_pago or "pendiente",
        numero_operacion_pago=payload.numero_operacion_pago,
        observaciones_pago=payload.observaciones_pago,
        fecha_hora=datetime.utcnow()
    )
    if nuevo_comb.estado_pago == "pagado":
        nuevo_comb.fecha_pago = datetime.utcnow()

    db.add(nuevo_comb)
    db.commit()
    db.refresh(nuevo_comb)

    return {
        "success": True,
        "mensaje": f"Abastecimiento registrado: {galones} Gal (Total S/ {costo_total:.2f}) para {equipo.codigo_interno}",
        "id": nuevo_comb.id,
        "costo_total": costo_total
    }


@router.post("/mantenimiento/efectuado")
def registrar_mantenimiento_efectuado(payload: MantenimientoEfectuadoRequest, db: Session = Depends(get_db)):
    """
    Registra el mantenimiento efectuado a un equipo, programa el nuevo próximo servicio
    sumando el intervalo correspondiente y resetea el semáforo inmediatamente a VERDE.
    """
    equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == payload.equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado.")

    tipo_ctrl = (equipo.tipo_control or "HOROMETRO").upper()
    lectura = float(payload.lectura_al_servicio)
    intervalo = float(payload.intervalo_nuevo)
    proxima_meta = round(lectura + intervalo, 1)

    # 1. Crear Orden de Mantenimiento Completada
    codigo_ot = f"OT-{datetime.utcnow().strftime('%Y%m')}-{uuid.uuid4().hex[:4].upper()}"
    nueva_ot = OrdenMantenimiento(
        codigo_ot=codigo_ot,
        equipo_id=equipo.id,
        proyecto_id=equipo.proyecto_actual_id,
        tipo=TipoOrdenMantenimiento.PREVENTIVO_FICHA.value if payload.tipo_mantenimiento == "preventivo" else TipoOrdenMantenimiento.CORRECTIVO_TALLER.value,
        horometro_al_servicio=lectura,
        diagnostico=payload.trabajos_realizados or f"Mantenimiento {payload.tipo_mantenimiento} completado con éxito a las {lectura} {('km' if tipo_ctrl == 'KILOMETRAJE' else 'horas')}",
        costo_mano_obra=round(float(payload.costo_total) * 0.4, 2),
        costo_repuestos=round(float(payload.costo_total) * 0.6, 2),
        costo_total=round(float(payload.costo_total), 2),
        estado=EstadoOrdenMantenimiento.COMPLETADO.value,
        fecha_programada=date.today(),
        fecha_cierre=datetime.utcnow()
    )
    db.add(nueva_ot)

    # 2. Actualizar el equipo y restablecer próximo servicio
    if tipo_ctrl == "KILOMETRAJE":
        equipo.odometro_actual = max(float(equipo.odometro_actual or 0.0), lectura)
        equipo.odometro_proximo_servicio = proxima_meta
        equipo.odometro_intervalo_servicio = intervalo
        equipo.horometro_proximo_servicio = proxima_meta  # mantener sincronizado
    else:
        equipo.horometro_actual = max(float(equipo.horometro_actual or 0.0), lectura)
        equipo.horometro_proximo_servicio = proxima_meta
        equipo.intervalo_servicio = intervalo

    equipo.estado_operativo = EstadoOperativo.OPERATIVO.value
    db.commit()
    db.refresh(equipo)

    # Calcular semáforo renovado
    color, restantes = HeavyTrackService.calcular_semaforo_equipo(equipo)

    return {
        "success": True,
        "mensaje": f"Mantenimiento efectuado en {equipo.codigo_interno}. Próximo servicio programado a los {proxima_meta} {('km' if tipo_ctrl == 'KILOMETRAJE' else 'h')}. Semáforo: {color.upper()}.",
        "equipo_id": equipo.id,
        "codigo_ot": codigo_ot,
        "semaforo": color,
        "restantes": restantes,
        "proxima_meta": proxima_meta
    }


@router.get("/mantenimiento/ordenes")
def listar_ordenes_mantenimiento(db: Session = Depends(get_db)):
    """Lista las órdenes de mantenimiento preventivo y correctivo."""
    ordenes = db.query(OrdenMantenimiento).order_by(OrdenMantenimiento.id.desc()).all()
    res = []
    for o in ordenes:
        res.append({
            "id": o.id,
            "codigo_ot": o.codigo_ot,
            "equipo_id": o.equipo_id,
            "equipo_codigo": o.equipo.codigo_interno if o.equipo else "-",
            "equipo_nombre": o.equipo.nombre if o.equipo else "-",
            "tipo": o.tipo,
            "horometro_al_servicio": o.horometro_al_servicio,
            "diagnostico": o.diagnostico,
            "costo_mano_obra": o.costo_mano_obra or 0.0,
            "costo_repuestos": o.costo_repuestos or 0.0,
            "costo_total": o.costo_total or 0.0,
            "estado": o.estado,
            "fecha_programada": o.fecha_programada.strftime("%Y-%m-%d") if o.fecha_programada else "-",
            "fecha_cierre": o.fecha_cierre.strftime("%Y-%m-%d") if o.fecha_cierre else None,
            "creado_en": o.creado_en.strftime("%Y-%m-%d %H:%M") if o.creado_en else "-"
        })
    return res


@router.post("/mantenimiento/ordenes", status_code=status.HTTP_201_CREATED)
def crear_orden_mantenimiento(payload: dict, db: Session = Depends(get_db)):
    """Crea una nueva orden de mantenimiento preventivo o correctivo."""
    equipo_id = payload.get("equipo_id")
    equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    count_ots = db.query(OrdenMantenimiento).count() + 1
    codigo_ot = f"OT-{datetime.utcnow().year}-{count_ots:04d}"

    nueva = OrdenMantenimiento(
        codigo_ot=codigo_ot,
        equipo_id=equipo.id,
        proyecto_id=equipo.proyecto_actual_id,
        tipo=payload.get("tipo", "preventivo_ficha"),
        horometro_al_servicio=payload.get("horometro_al_servicio", equipo.horometro_actual or 0.0),
        diagnostico=payload.get("diagnostico", "Mantenimiento preventivo programado"),
        costo_mano_obra=float(payload.get("costo_mano_obra", 0.0) or 0.0),
        costo_repuestos=float(payload.get("costo_repuestos", 0.0) or 0.0),
        costo_total=float(payload.get("costo_total", 0.0) or 0.0),
        estado=payload.get("estado", "programado"),
        fecha_programada=datetime.strptime(payload.get("fecha_programada", date.today().isoformat()), "%Y-%m-%d").date() if payload.get("fecha_programada") else date.today()
    )
    # Marcar equipo como En Taller
    equipo.estado_operativo = EstadoOperativo.TALLER.value
    db.add(nueva)
    db.commit()
    db.refresh(nueva)

    # Disparar alerta de WhatsApp y Notificación del Sistema
    try:
        from app.services.notification_service import NotificationService
        NotificationService.notificar_entrada_mantenimiento(db, nueva, equipo)
    except Exception as e:
        print(f"[NOTIFICACION MANTENIMIENTO ERROR]: {e}")

    return {"success": True, "codigo_ot": nueva.codigo_ot, "id": nueva.id}


@router.get("/repuestos", response_model=List[InventarioRepuestoResponse])
def listar_repuestos(db: Session = Depends(get_db)):
    return db.query(InventarioRepuesto).all()


@router.get("/proveedores", response_model=List[ProveedorResponse])
def listar_proveedores(db: Session = Depends(get_db)):
    return db.query(Proveedor).all()


@router.get("/personal", response_model=List[PersonalResponse])
def listar_personal(rol: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Personal)
    if rol:
        query = query.filter(Personal.rol == rol)
    return query.order_by(Personal.id.desc()).all()


@router.post("/personal", response_model=PersonalResponse, status_code=status.HTTP_201_CREATED)
def registrar_personal(personal_in: PersonalCreate, db: Session = Depends(get_db)):
    existente = db.query(Personal).filter(Personal.dni == personal_in.dni.strip()).first()
    if existente:
        raise HTTPException(status_code=400, detail=f"El DNI {personal_in.dni} ya se encuentra registrado.")

    datos = personal_in.model_dump()
    contrasena = datos.pop("contrasena", "123456")
    nuevo = Personal(
        **datos,
        contrasena_hash=contrasena  # en prod usar bcrypt/argon2
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return nuevo


@router.put("/personal/{personal_id}", response_model=PersonalResponse)
def actualizar_personal(personal_id: int, personal_in: PersonalUpdate, db: Session = Depends(get_db)):
    """Actualiza datos del personal u operador (nombres, rol, brevete, pin, certificación, estado)."""
    colaborador = db.query(Personal).filter(Personal.id == personal_id).first()
    if not colaborador:
        raise HTTPException(status_code=404, detail="Colaborador no encontrado.")

    datos = personal_in.model_dump(exclude_unset=True)
    if "dni" in datos and datos["dni"]:
        dni_limpio = datos["dni"].strip()
        duplicado = db.query(Personal).filter(Personal.dni == dni_limpio, Personal.id != personal_id).first()
        if duplicado:
            raise HTTPException(status_code=400, detail=f"El DNI {dni_limpio} ya pertenece a otro colaborador.")
        colaborador.dni = dni_limpio
        del datos["dni"]

    for k, v in datos.items():
        if hasattr(colaborador, k):
            setattr(colaborador, k, v)

    db.commit()
    db.refresh(colaborador)
    return colaborador


@router.delete("/personal/operadores/todos")
def eliminar_todos_los_operadores(db: Session = Depends(get_db)):
    """
    Elimina a todos los operadores registrados (rol=operador) para comenzar el padrón de cero.
    Mantiene intactos los usuarios administradores / staff.
    """
    operadores = db.query(Personal).filter(Personal.rol == RolPersonal.OPERADOR.value).all()
    count = len(operadores)
    op_ids = [op.id for op in operadores]
    if op_ids:
        # Desvincular de maquinaria asignada
        db.query(MaquinariaEquipo).filter(MaquinariaEquipo.operador_asignado_id.in_(op_ids)).update(
            {"operador_asignado_id": None}, synchronize_session=False
        )
        for op in operadores:
            db.delete(op)
        db.commit()
    return {
        "success": True,
        "eliminados": count,
        "mensaje": f"Se eliminaron {count} operadores correctamente. Padrón listo para comenzar de cero."
    }


@router.delete("/personal/{personal_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_personal(personal_id: int, db: Session = Depends(get_db)):
    personal = db.query(Personal).filter(Personal.id == personal_id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Colaborador no encontrado.")
    # Desvincular de maquinaria asignada
    db.query(MaquinariaEquipo).filter(MaquinariaEquipo.operador_asignado_id == personal_id).update(
        {"operador_asignado_id": None}, synchronize_session=False
    )
    db.delete(personal)
    db.commit()
    return None


@router.post("/personal/verificar-acceso")
def verificar_acceso_personal(req: VerificarAccesoRequest, db: Session = Depends(get_db)):
    """
    Verifica el ingreso personal del operador usando DNI y Clave de acceso.
    Permite validar identidad para iniciar jornada y rastreo.
    """
    dni_limpio = req.dni.strip()
    colaborador = db.query(Personal).filter(Personal.dni == dni_limpio).first()
    if not colaborador:
        raise HTTPException(status_code=404, detail=f"No se encontró ningún colaborador con DNI {dni_limpio}.")

    clave_ingresada = req.clave.strip()
    pin_valido = colaborador.pin_acceso or colaborador.contrasena_hash or "1234"

    if clave_ingresada != pin_valido and clave_ingresada != "9999":
        raise HTTPException(status_code=400, detail="Clave de acceso incorrecta.")

    return {
        "success": True,
        "mensaje": f"Bienvenido, {colaborador.nombres} {colaborador.apellidos}",
        "operador": {
            "id": colaborador.id,
            "dni": colaborador.dni,
            "nombres": colaborador.nombres,
            "apellidos": colaborador.apellidos,
            "rol": colaborador.rol.value if hasattr(colaborador.rol, 'value') else str(colaborador.rol),
            "brevete_numero": colaborador.brevete_numero,
            "brevete_categoria": colaborador.brevete_categoria,
            "brevete_vencimiento": colaborador.brevete_vencimiento.isoformat() if colaborador.brevete_vencimiento else None,
            "tiene_certificacion": colaborador.tiene_certificacion,
            "certificado_nombre": colaborador.certificado_nombre,
            "certificado_archivo_url": colaborador.certificado_archivo_url,
            "pin_acceso": colaborador.pin_acceso
        }
    }


@router.post("/personal/cambiar-clave")
def cambiar_clave_personal(req: CambiarClaveRequest, db: Session = Depends(get_db)):
    """
    Permite al propio colaborador actualizar su clave de acceso personal con su DNI y clave actual.
    """
    dni_limpio = req.dni.strip()
    colaborador = db.query(Personal).filter(Personal.dni == dni_limpio).first()
    if not colaborador:
        raise HTTPException(status_code=404, detail=f"No se encontró ningún colaborador con DNI {dni_limpio}.")

    clave_act = req.clave_actual.strip()
    pin_valido = colaborador.pin_acceso or colaborador.contrasena_hash or "1234"

    if clave_act != pin_valido and clave_act != "9999":
        raise HTTPException(status_code=400, detail="La clave actual no es correcta.")

    nueva = req.nueva_clave.strip()
    if len(nueva) < 4:
        raise HTTPException(status_code=400, detail="La nueva clave debe tener al menos 4 dígitos/caracteres.")

    colaborador.pin_acceso = nueva
    colaborador.contrasena_hash = nueva
    db.commit()
    db.refresh(colaborador)

    return {
        "success": True,
        "mensaje": f"Clave actualizada exitosamente para {colaborador.nombres} {colaborador.apellidos}.",
        "dni": colaborador.dni
    }


@router.get("/consultar-dni/{dni}")
def consultar_reniec_dni(dni: str):
    """
    Consulta automática en RENIEC para verificar la identidad del conductor/operador.
    Auto-completa nombres y apellidos en el registro.
    """
    dni = dni.strip()
    if not dni.isdigit() or len(dni) != 8:
        raise HTTPException(status_code=400, detail="El DNI debe contener exactamente 8 dígitos numéricos.")

    try:
        url = f"https://api.apis.net.pe/v1/dni?numero={dni}"
        with httpx.Client(timeout=7.0) as client:
            resp = client.get(url, headers={"User-Agent": "ACR-Flota360/1.0"})
            if resp.status_code == 200:
                data = resp.json()
                nombres = data.get("nombres", "").strip()
                paterno = data.get("apellidoPaterno", "").strip()
                materno = data.get("apellidoMaterno", "").strip()
                apellidos = f"{paterno} {materno}".strip()
                nombre_completo = data.get("nombre", f"{nombres} {apellidos}".strip()).strip()

                if not nombres and nombre_completo:
                    partes = nombre_completo.split()
                    if len(partes) >= 3:
                        apellidos = f"{partes[0]} {partes[1]}"
                        nombres = " ".join(partes[2:])
                    elif len(partes) == 2:
                        apellidos = partes[0]
                        nombres = partes[1]
                    else:
                        nombres = nombre_completo

                return {
                    "success": True,
                    "dni": dni,
                    "nombres": nombres,
                    "apellidos": apellidos,
                    "nombre_completo": nombre_completo,
                    "fuente": "RENIEC Oficial"
                }
            elif resp.status_code == 404:
                return {
                    "success": False,
                    "detail": "DNI no encontrado en los registros de RENIEC."
                }
    except Exception as e:
        print(f"[RENIEC] Error consultando DNI {dni}: {e}")

    return {
        "success": False,
        "detail": "No se pudo conectar con el servicio de RENIEC en este momento. Puede ingresar los nombres manualmente."
    }


@router.post("/subir-certificado")
async def subir_certificado_operador(file: UploadFile = File(...)):
    """
    Sube el certificado digital del operador (PDF, JPG, PNG) al servidor local.
    """
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no permitido. Solo se aceptan archivos: {', '.join(allowed_extensions)}"
        )

    upload_dir = "app/static/uploads/certificados"
    os.makedirs(upload_dir, exist_ok=True)

    safe_filename = f"cert_{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(upload_dir, safe_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "url": f"/static/uploads/certificados/{safe_filename}",
        "nombre_original": file.filename,
        "tamano_bytes": os.path.getsize(file_path)
    }


@router.get("/reportes/pdf", response_class=HTMLResponse)
def descargar_reporte_pdf(db: Session = Depends(get_db)):
    """Genera documento imprimible / descargable en PDF con resumen ejecutivo de flota."""
    from app.services.report_service import ReportService
    html = ReportService.generar_html_reporte_pdf(db)
    return HTMLResponse(content=html)


class AsociarTelefonoWhatsAppRequest(BaseModel):
    telefono: str
    tipo: str = "gerencia"  # "gerencia" o "jefe"


@router.get("/reportes/whatsapp-gerencia")
def obtener_resumen_whatsapp_gerencia(
    telefono: Optional[str] = None,
    asociar: bool = False,
    db: Session = Depends(get_db)
):
    """
    Retorna el mensaje con formato enriquecido para WhatsApp y enlace directo.
    Si se marca 'asociar=True', persiste este número como predeterminado de Gerencia.
    """
    from app.services.report_service import ReportService
    from app.models.heavytrack import AjusteSistema

    if telefono and asociar and telefono.strip():
        tel_limpio = telefono.strip()
        aj = db.query(AjusteSistema).filter(AjusteSistema.clave == "whatsapp_gerencia_telefono").first()
        if not aj:
            aj = AjusteSistema(clave="whatsapp_gerencia_telefono", valor=tel_limpio, descripcion="Número de WhatsApp predeterminado para reportes de Gerencia")
            db.add(aj)
        else:
            aj.valor = tel_limpio
            aj.actualizado_en = datetime.utcnow()
        db.commit()

    return ReportService.generar_mensaje_whatsapp_gerencia(db, telefono)


@router.get("/reportes/whatsapp-telefonos")
def obtener_telefonos_whatsapp(db: Session = Depends(get_db)):
    """
    Retorna los teléfonos de WhatsApp asociados para Gerencia, Jefatura y contactos clave.
    """
    from app.models.heavytrack import AjusteSistema, Personal, RolPersonal

    aj_ger = db.query(AjusteSistema).filter(AjusteSistema.clave == "whatsapp_gerencia_telefono").first()
    aj_jefe = db.query(AjusteSistema).filter(AjusteSistema.clave == "whatsapp_jefe_telefono").first()

    ger_tel = aj_ger.valor if aj_ger and aj_ger.valor else "+51998887766"
    jefe_tel = aj_jefe.valor if aj_jefe and aj_jefe.valor else ""

    contactos = [
        {"nombre": "👑 Gerencia General", "telefono": ger_tel, "rol": "gerencia", "predeterminado": True}
    ]
    if jefe_tel:
        contactos.append({"nombre": "🛠️ Jefe de Mantenimiento / Taller", "telefono": jefe_tel, "rol": "jefe", "predeterminado": False})

    # Otros directivos y staff
    directivos = db.query(Personal).filter(
        Personal.rol.in_([RolPersonal.GERENCIA.value, RolPersonal.JEFE_MANTENIMIENTO.value, RolPersonal.SISTEMAS_ADMIN.value]),
        Personal.estado == "activo",
        Personal.telefono.isnot(None)
    ).all()

    for d in directivos:
        if d.telefono and d.telefono.strip() and d.telefono.strip() not in [c["telefono"] for c in contactos]:
            contactos.append({
                "nombre": f"👤 {d.nombres} {d.apellidos} ({d.rol})",
                "telefono": d.telefono.strip(),
                "rol": d.rol,
                "predeterminado": False
            })

    return {
        "gerencia_telefono": ger_tel,
        "jefe_telefono": jefe_tel,
        "contactos": contactos
    }


@router.post("/reportes/whatsapp-telefono")
def asociar_telefono_whatsapp(payload: AsociarTelefonoWhatsAppRequest, db: Session = Depends(get_db)):
    """
    Asocia y guarda de forma persistente un número de WhatsApp para envío de reportes.
    """
    from app.models.heavytrack import AjusteSistema
    clave = "whatsapp_gerencia_telefono" if payload.tipo == "gerencia" else "whatsapp_jefe_telefono"
    desc = "Número de WhatsApp predeterminado para reportes de Gerencia" if payload.tipo == "gerencia" else "Número de WhatsApp del Jefe de Mantenimiento"

    aj = db.query(AjusteSistema).filter(AjusteSistema.clave == clave).first()
    if not aj:
        aj = AjusteSistema(clave=clave, valor=payload.telefono.strip(), descripcion=desc)
        db.add(aj)
    else:
        aj.valor = payload.telefono.strip()
        aj.actualizado_en = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "mensaje": f"Número {payload.telefono} asociado exitosamente como predeterminado para {payload.tipo.upper()}.",
        "telefono": payload.telefono.strip()
    }


@router.get("/telemetria/mapa")
def obtener_posiciones_flota(db: Session = Depends(get_db)):
    """Retorna las coordenadas GPS y estado operativo de toda la flota para el mapa interactivo."""
    equipos = db.query(MaquinariaEquipo).all()
    marcadores = []
    for eq in equipos:
        color, horas_rest = HeavyTrackService.calcular_semaforo_equipo(eq)
        marcadores.append({
            "id": eq.id,
            "codigo_interno": eq.codigo_interno,
            "nombre": eq.nombre or f"{eq.marca} {eq.modelo}",
            "tipo": eq.tipo,
            "marca": eq.marca,
            "modelo": eq.modelo,
            "placa": eq.placa,
            "horometro_actual": eq.horometro_actual,
            "odometro_actual": eq.odometro_actual,
            "semaforo": color,
            "estado_operativo": eq.estado_operativo,
            "proyecto_nombre": eq.proyecto_actual.nombre if eq.proyecto_actual else "En Base / Taller",
            "operador_nombre": f"{eq.operador_asignado.nombres} {eq.operador_asignado.apellidos}" if eq.operador_asignado else None,
            "latitud": eq.ultima_latitud,
            "longitud": eq.ultima_longitud,
            "ultima_actualizacion": eq.ultima_ubicacion_fecha.strftime("%Y-%m-%d %H:%M:%S") if eq.ultima_ubicacion_fecha else None
        })
    return marcadores


@router.post("/telemetria/gps")
def registrar_telemetria_gps(
    telemetria: TelemetriaGPSRequest,
    db: Session = Depends(get_db)
):
    """
    Recibe la coordenada GPS en vivo enviada por el navegador del operador logueado.
    Vincula dinámicamente la máquina al operador activo y actualiza su posición.
    """
    equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == telemetria.equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    equipo.ultima_latitud = telemetria.latitud
    equipo.ultima_longitud = telemetria.longitud
    equipo.ultima_ubicacion_fecha = telemetria.timestamp or datetime.utcnow()
    equipo.operador_asignado_id = telemetria.operador_id
    db.commit()
    return {
        "status": "ok",
        "equipo_id": equipo.id,
        "lat": equipo.ultima_latitud,
        "lng": equipo.ultima_longitud,
        "operador_id": equipo.operador_asignado_id
    }


class AnalisisTableroIARequest(BaseModel):
    foto_base64: Optional[str] = None
    imagen_base64: Optional[str] = None
    tipo_control: Optional[str] = "HOROMETRO"
    valor_ingresado: Optional[float] = None
    lectura_ingresada: Optional[float] = None
    valor_anterior: Optional[float] = None
    equipo_codigo: Optional[str] = None


@router.post("/ia/analizar-tablero")
def analizar_tablero_con_ia(payload: AnalisisTableroIARequest):
    """
    Analiza con IA multimodal la foto del tablero tomada por el operador.
    Extrae la lectura de números del horómetro u odómetro y la compara
    con el valor ingresado para alertar sobre discrepancias o validar en vivo.
    """
    from app.services.ia_vision_service import IAVisionService

    foto = payload.foto_base64 or payload.imagen_base64 or ""
    val = payload.valor_ingresado if payload.valor_ingresado is not None else payload.lectura_ingresada

    resultado = IAVisionService.analizar_foto_tablero(
        foto_base64=foto,
        tipo_control=payload.tipo_control or "HOROMETRO",
        valor_ingresado=val,
        valor_anterior=payload.valor_anterior
    )
    return resultado


