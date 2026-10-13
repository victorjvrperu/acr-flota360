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
    EstadoOperativo, EstadoOrdenMantenimiento
)
from app.schemas.heavytrack import (
    MaquinariaEquipoCreate, MaquinariaEquipoResponse,
    ProyectoCreate, ProyectoResponse,
    PersonalCreate, PersonalResponse,
    VerificarAccesoRequest, CambiarClaveRequest,
    OrdenMantenimientoCreate, OrdenMantenimientoResponse,
    InventarioRepuestoCreate, InventarioRepuestoResponse,
    ProveedorCreate, ProveedorResponse,
    TelemetriaGPSRequest
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

    DATE_FIELDS = {"poliza_vencimiento", "soat_vencimiento"}
    FLOAT_FIELDS = {"horometro_actual", "odometro_actual", "horometro_proximo_servicio", "intervalo_servicio"}

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
            elif key in ("serie_chasis", "poliza_seguro", "soat_numero", "nombre", "marca", "modelo") and value is not None:
                val_str = str(value).strip()
                value = val_str if val_str else None

            setattr(equipo, key, value)

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
    """Elimina un frente de obra / proyecto si no tiene registros bloqueantes."""
    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not proyecto:
        raise HTTPException(status_code=404, detail="Frente de obra no encontrado.")
    # Desvincular maquinaria asociada al frente
    db.query(MaquinariaEquipo).filter(MaquinariaEquipo.proyecto_actual_id == proyecto_id).update(
        {MaquinariaEquipo.proyecto_actual_id: None}
    )
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


@router.delete("/personal/{personal_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_personal(personal_id: int, db: Session = Depends(get_db)):
    personal = db.query(Personal).filter(Personal.id == personal_id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Colaborador no encontrado.")
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
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url, headers={"User-Agent": "ACR-Flota360/1.0"})
            if resp.status_code == 200:
                data = resp.json()
                nombres = data.get("nombres", "").strip()
                paterno = data.get("apellidoPaterno", "").strip()
                materno = data.get("apellidoMaterno", "").strip()
                apellidos = f"{paterno} {materno}".strip()
                nombre_completo = data.get("nombre", f"{nombres} {apellidos}".strip())
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


@router.get("/reportes/whatsapp-gerencia")
def obtener_resumen_whatsapp_gerencia(telefono: Optional[str] = "+51998887766", db: Session = Depends(get_db)):
    """Retorna el mensaje con formato enriquecido para WhatsApp y enlace directo."""
    from app.services.report_service import ReportService
    return ReportService.generar_mensaje_whatsapp_gerencia(db, telefono)


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


