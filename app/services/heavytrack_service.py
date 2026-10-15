from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Tuple

from app.models.heavytrack import (
    Proyecto, Personal, MaquinariaEquipo, TurnoOperacion,
    ControlCombustible, IncidenteCheckpoint, OrdenMantenimiento,
    InventarioRepuesto, Proveedor, MantenimientoRepuesto,
    EstadoOperativo, SeveridadIncidente, EstadoSync,
    EstadoOrdenMantenimiento, AjusteSistema
)
from app.schemas.heavytrack import (
    BatchSyncRequest, BatchSyncResponse, BatchSyncItemStatus
)


class HeavyTrackService:

    @staticmethod
    def calcular_semaforo_equipo(equipo: MaquinariaEquipo) -> Tuple[str, float]:
        """
        Regla de negocio:
        - Para KILOMETRAJE:
            * km_restantes = odometro_proximo_servicio - odometro_actual
            * Rojo: km_restantes <= 0 (Llegó a mantenimiento o ya se pasó)
            * Amarillo: km_restantes <= 1500 km (Próximo a servicio)
            * Verde: km_restantes > 1500 km (Operativo)
        - Para HOROMETRO:
            * horas_restantes = horometro_proximo_servicio - horometro_actual
            * Rojo: horas_restantes <= 0 (Llegó a mantenimiento o ya se pasó)
            * Amarillo: horas_restantes <= 50.0 horas (Próximo a servicio)
            * Verde: horas_restantes > 50.0 horas (Operativo)
        """
        tipo_control = (equipo.tipo_control or "HOROMETRO").upper()

        if tipo_control == "KILOMETRAJE":
            actual = float(equipo.odometro_actual or 0.0)
            proximo = float(equipo.odometro_proximo_servicio or 0.0)
            if proximo <= 0:
                # Si no se configuró odometro_proximo_servicio, pero se especificó en horometro_proximo_servicio
                proximo = float(equipo.horometro_proximo_servicio or 0.0)
                if proximo <= 0:
                    proximo = actual + float(equipo.odometro_intervalo_servicio or 5000.0)
            restantes = round(proximo - actual, 1)

            if restantes <= 0:
                return "rojo", restantes
            elif restantes <= 1500.0:
                return "amarillo", restantes
            else:
                return "verde", restantes
        else:
            actual = float(equipo.horometro_actual or 0.0)
            proximo = float(equipo.horometro_proximo_servicio or 250.0)
            restantes = round(proximo - actual, 1)

            if restantes <= 0:
                return "rojo", restantes
            elif restantes <= 50.0:
                return "amarillo", restantes
            else:
                return "verde", restantes

    @staticmethod
    def verificar_licencia_operador(operador: Personal) -> Tuple[bool, str]:
        """
        Verifica el vencimiento de brevete del operador al momento de iniciar turno.
        """
        if not operador.brevete_vencimiento:
            return True, "Sin registro de brevete"
        
        hoy = date.today()
        dias = (operador.brevete_vencimiento - hoy).days

        if dias < 0:
            return False, f"⚠️ ALERTA CRÍTICA: Brevete vencido hace {abs(dias)} días ({operador.brevete_vencimiento.strftime('%d/%m/%Y')})"
        elif dias <= 15:
            return True, f"⚠️ ATENCIÓN: Brevete por vencer en {dias} días ({operador.brevete_vencimiento.strftime('%d/%m/%Y')})"
        
        return True, "Brevete vigente"

    @staticmethod
    def procesar_sync_batch(db: Session, batch: BatchSyncRequest) -> BatchSyncResponse:
        """
        Procesador Batch Idempotente para la cola offline acumulada en móviles.
        Usa uuid_local único para descartar duplicados y mantener consistencia.
        """
        detalles: List[BatchSyncItemStatus] = []
        procesados = 0
        duplicados = 0

        # 1. Procesar Turnos Check-In
        for turno_in in batch.turnos:
            existente = db.query(TurnoOperacion).filter(
                TurnoOperacion.uuid_local == turno_in.uuid_local
            ).first()

            if existente:
                duplicados += 1
                detalles.append(BatchSyncItemStatus(
                    uuid_local=turno_in.uuid_local,
                    tipo="turno_checkin",
                    status="duplicado_ignorado",
                    mensaje="Registro previo existente en base de datos"
                ))
                continue

            # Verificar operador y brevete
            operador = db.query(Personal).filter(Personal.id == turno_in.operador_id).first()
            alerta_lic = ""
            if operador:
                _, alerta_lic = HeavyTrackService.verificar_licencia_operador(operador)

            turno = TurnoOperacion(
                uuid_local=turno_in.uuid_local,
                equipo_id=turno_in.equipo_id,
                operador_id=turno_in.operador_id,
                proyecto_id=turno_in.proyecto_id,
                fecha=turno_in.fecha,
                horometro_inicio=turno_in.horometro_inicio,
                foto_horometro_inicio=turno_in.foto_horometro_inicio,
                kilometraje_inicio=getattr(turno_in, "kilometraje_inicio", 0.0) or 0.0,
                latitud_inicio=getattr(turno_in, "latitud_inicio", None),
                longitud_inicio=getattr(turno_in, "longitud_inicio", None),
                abastecio_combustible=getattr(turno_in, "abastecio_combustible", False),
                combustible_galones=getattr(turno_in, "combustible_galones", 0.0) or 0.0,
                combustible_precio_galon=getattr(turno_in, "combustible_precio_galon", 0.0) or 0.0,
                combustible_total_soles=getattr(turno_in, "combustible_total_soles", 0.0) or 0.0,
                foto_combustible=getattr(turno_in, "foto_combustible", None),
                observaciones_inicio=getattr(turno_in, "observaciones_inicio", None),
                foto_inicio_delantera=getattr(turno_in, "foto_inicio_delantera", None),
                foto_inicio_trasera=getattr(turno_in, "foto_inicio_trasera", None),
                foto_inicio_izquierda=getattr(turno_in, "foto_inicio_izquierda", None),
                foto_inicio_derecha=getattr(turno_in, "foto_inicio_derecha", None),
                estado_sync=EstadoSync.SINCRONIZADO.value
            )
            db.add(turno)

            # Si abasteció combustible en el check-in, registrar automáticamente en control_combustible
            galones_in = getattr(turno_in, "combustible_galones", 0.0) or 0.0
            abastecio = getattr(turno_in, "abastecio_combustible", False) or (galones_in > 0)
            if abastecio and galones_in > 0:
                precio_in = float(getattr(turno_in, "combustible_precio_galon", 0.0) or 0.0)
                if precio_in < 0:
                    precio_in = 0.0
                turno.combustible_galones = galones_in
                turno.combustible_precio_galon = precio_in
                total_in = getattr(turno_in, "combustible_total_soles", 0.0) or round(galones_in * precio_in, 2)
                turno.combustible_total_soles = total_in
                turno.abastecio_combustible = True

                uuid_c = f"comb-{turno_in.uuid_local}"
                comb_rec = db.query(ControlCombustible).filter(ControlCombustible.uuid_local == uuid_c).first()
                if not comb_rec:
                    eq_actual = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == turno_in.equipo_id).first()
                    lect_tanqueo = getattr(turno_in, "kilometraje_inicio", 0.0) if (eq_actual and (eq_actual.tipo_control or '').upper() == 'KILOMETRAJE') else (turno_in.horometro_inicio or 0.0)
                    comb_rec = ControlCombustible(
                        uuid_local=uuid_c,
                        equipo_id=turno_in.equipo_id,
                        operador_id=turno_in.operador_id,
                        proyecto_id=turno_in.proyecto_id,
                        horometro_tanqueo=lect_tanqueo,
                        galones_cargados=galones_in,
                        precio_por_galon=precio_in,
                        foto_comprobante=getattr(turno_in, "foto_combustible", None) or "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
                        costo_total=total_in,
                        estado_pago="pendiente",
                        estado_sync=EstadoSync.SINCRONIZADO.value,
                        fecha_hora=datetime.utcnow()
                    )
                    db.add(comb_rec)
                else:
                    comb_rec.galones_cargados = galones_in
                    comb_rec.precio_por_galon = precio_in
                    comb_rec.costo_total = total_in

            # Actualizar equipo y asignación dinámica de operador
            equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == turno_in.equipo_id).first()
            if equipo:
                equipo.operador_asignado_id = turno_in.operador_id
                equipo.proyecto_actual_id = turno_in.proyecto_id

                lat_ini = getattr(turno_in, "latitud_inicio", None)
                lng_ini = getattr(turno_in, "longitud_inicio", None)
                if lat_ini is not None and lng_ini is not None:
                    equipo.ultima_latitud = lat_ini
                    equipo.ultima_longitud = lng_ini
                    equipo.ultima_ubicacion_fecha = datetime.utcnow()

                if turno_in.horometro_inicio and turno_in.horometro_inicio > (equipo.horometro_actual or 0.0):
                    equipo.horometro_actual = turno_in.horometro_inicio
                    color, _ = HeavyTrackService.calcular_semaforo_equipo(equipo)
                    if color == "rojo" or color == "amarillo":
                        equipo.estado_operativo = EstadoOperativo.CRITICO.value
                km_ini = getattr(turno_in, "kilometraje_inicio", 0.0) or 0.0
                if km_ini > (equipo.odometro_actual or 0.0):
                    equipo.odometro_actual = km_ini

                # Detección de Incongruencias en Check-In
                lectura_actual = equipo.odometro_actual if equipo.tipo_control == "KILOMETRAJE" else (equipo.horometro_actual or 0.0)
                lectura_ingresada = km_ini if equipo.tipo_control == "KILOMETRAJE" else (turno_in.horometro_inicio or 0.0)
                if lectura_actual > 0 and lectura_ingresada < (lectura_actual - 0.1):
                    try:
                        from app.services.notification_service import NotificationService
                        NotificationService.notificar_incongruencia_datos(
                            db=db,
                            equipo=equipo,
                            operador=operador,
                            detalle_incongruencia=f"Lectura inicial ({lectura_ingresada}) es MENOR a la registrada previamente ({lectura_actual})",
                            lectura_anterior=lectura_actual,
                            lectura_nueva=lectura_ingresada
                        )
                    except Exception as ex:
                        print(f"[ALERTA INCONGRUENCIA ERROR]: {ex}")

            procesados += 1
            detalles.append(BatchSyncItemStatus(
                uuid_local=turno_in.uuid_local,
                tipo="turno_checkin",
                status="creado",
                mensaje=f"Turno check-in con inspección 360° registrado. {alerta_lic}".strip()
            ))

        db.flush()

        # 2. Procesar Turnos Check-Out
        for out in batch.turnos_checkout:
            turno = db.query(TurnoOperacion).filter(
                TurnoOperacion.uuid_local == out.uuid_local
            ).first()

            if not turno:
                detalles.append(BatchSyncItemStatus(
                    uuid_local=out.uuid_local,
                    tipo="turno_checkout",
                    status="error",
                    mensaje="Turno no encontrado para registrar check-out"
                ))
                continue

            turno.horometro_fin = out.horometro_fin
            turno.foto_horometro_fin = out.foto_horometro_fin
            turno.foto_fin_delantera = getattr(out, "foto_fin_delantera", None)
            turno.foto_fin_trasera = getattr(out, "foto_fin_trasera", None)
            turno.foto_fin_izquierda = getattr(out, "foto_fin_izquierda", None)
            turno.foto_fin_derecha = getattr(out, "foto_fin_derecha", None)
            turno.hubo_incidencia = getattr(out, "hubo_incidencia", False)
            turno.incidencia_descripcion = getattr(out, "incidencia_descripcion", None)
            turno.foto_incidencia = getattr(out, "foto_incidencia", None)

            # Si hubo incidencia al cierre, registrar en incidentes_checkpoint automáticamente
            if getattr(out, "hubo_incidencia", False) and getattr(out, "incidencia_descripcion", None):
                inc_rec = IncidenteCheckpoint(
                    uuid_local=f"inc-{out.uuid_local}",
                    equipo_id=turno.equipo_id,
                    operador_id=turno.operador_id,
                    tipo="Incidente Cierre Turno",
                    severidad="MEDIA",
                    descripcion=out.incidencia_descripcion,
                    foto_evidencia=getattr(out, "foto_incidencia", None) or out.foto_horometro_fin,
                    estado="abierto"
                )
                db.add(inc_rec)

            # Si se registró abastecimiento de combustible al cierre del turno
            gal_out = getattr(out, "combustible_galones", 0.0) or 0.0
            if gal_out > 0 or getattr(out, "abastecio_combustible", False):
                uuid_cout = f"comb-checkout-{out.uuid_local}"
                comb_rec = db.query(ControlCombustible).filter(ControlCombustible.uuid_local == uuid_cout).first()
                if not comb_rec:
                    precio_c = float(getattr(out, "combustible_precio_galon", 0.0) or 0.0)
                    if precio_c < 0:
                        precio_c = 0.0
                    costo_c = round(gal_out * precio_c, 2)
                    eq_act = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == turno.equipo_id).first()
                    lect_t = getattr(out, "kilometraje_fin", 0.0) if (eq_act and (eq_act.tipo_control or '').upper() == 'KILOMETRAJE') else (out.horometro_fin or 0.0)
                    comb_rec = ControlCombustible(
                        uuid_local=uuid_cout,
                        equipo_id=turno.equipo_id,
                        operador_id=turno.operador_id,
                        proyecto_id=turno.proyecto_id,
                        horometro_tanqueo=lect_t,
                        galones_cargados=gal_out,
                        precio_por_galon=precio_c,
                        foto_comprobante=getattr(out, "foto_combustible", None) or "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
                        costo_total=costo_c,
                        estado_pago="pendiente",
                        estado_sync=EstadoSync.SINCRONIZADO.value,
                        fecha_hora=datetime.utcnow()
                    )
                    db.add(comb_rec)

                # Notificar incidencia al Jefe de Área
                try:
                    from app.services.notification_service import NotificationService
                    op_inc = db.query(Personal).filter(Personal.id == turno.operador_id).first()
                    eq_inc = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == turno.equipo_id).first()
                    if eq_inc:
                        NotificationService.notificar_incidencia_operador(
                            db=db,
                            equipo=eq_inc,
                            operador=op_inc,
                            descripcion=out.incidencia_descripcion,
                            severidad="MEDIA"
                        )
                except Exception as ex:
                    print(f"[ALERTA INCIDENCIA ERROR]: {ex}")

            lat_fin = getattr(out, "latitud_fin", None)
            lng_fin = getattr(out, "longitud_fin", None)
            if lat_fin is not None and lng_fin is not None:
                turno.latitud_fin = lat_fin
                turno.longitud_fin = lng_fin
                if turno.equipo:
                    turno.equipo.ultima_latitud = lat_fin
                    turno.equipo.ultima_longitud = lng_fin
                    turno.equipo.ultima_ubicacion_fecha = datetime.utcnow()

            if out.horometro_fin is not None and turno.horometro_inicio is not None:
                if out.horometro_fin >= turno.horometro_inicio:
                    diff_motor = round(out.horometro_fin - turno.horometro_inicio, 2)
                    resma_calentamiento = 0.25  # 15 minutos asignados a calentamiento previo de motor
                    horas_efectivas = round(max(0.0, diff_motor - resma_calentamiento), 2)
                    turno.horas_motor_brutas = diff_motor
                    turno.horas_calentamiento = resma_calentamiento
                    turno.horas_trabajadas = horas_efectivas
                else:
                    # Incongruencia de horómetro menor al de inicio
                    try:
                        from app.services.notification_service import NotificationService
                        op_inc = db.query(Personal).filter(Personal.id == turno.operador_id).first()
                        eq_inc = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == turno.equipo_id).first()
                        if eq_inc:
                            NotificationService.notificar_incongruencia_datos(
                                db=db,
                                equipo=eq_inc,
                                operador=op_inc,
                                detalle_incongruencia=f"Horómetro de cierre ({out.horometro_fin}) es menor al horómetro de inicio del turno ({turno.horometro_inicio})",
                                lectura_anterior=turno.horometro_inicio,
                                lectura_nueva=out.horometro_fin
                            )
                    except Exception as ex:
                        print(f"[ALERTA INCONGRUENCIA CIERRE ERROR]: {ex}")

            km_fin = getattr(out, "kilometraje_fin", 0.0) or 0.0
            if km_fin > 0:
                turno.kilometraje_fin = km_fin
                if turno.kilometraje_inicio is not None and km_fin >= turno.kilometraje_inicio:
                    turno.km_recorridos = round(km_fin - turno.kilometraje_inicio, 1)

            # Actualización automática de horómetro y odómetro del equipo y semáforo
            equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == turno.equipo_id).first()
            if equipo:
                if out.horometro_fin is not None and out.horometro_fin > (equipo.horometro_actual or 0.0):
                    equipo.horometro_actual = out.horometro_fin
                    color, _ = HeavyTrackService.calcular_semaforo_equipo(equipo)
                    if color in ("rojo", "amarillo"):
                        equipo.estado_operativo = EstadoOperativo.CRITICO.value
                if km_fin > (equipo.odometro_actual or 0.0):
                    equipo.odometro_actual = km_fin

                # Alerta automática preventiva si el equipo entra a zona de servicio próximo (<25h o <500km)
                try:
                    tipo_c = equipo.tipo_control or "HOROMETRO"
                    act_val = equipo.odometro_actual if tipo_c == "KILOMETRAJE" else (equipo.horometro_actual or 0.0)
                    prox_val = equipo.horometro_proximo_servicio or (5000.0 if tipo_c == "KILOMETRAJE" else 250.0)
                    margen_val = round(prox_val - act_val, 1)
                    umbral_val = 500.0 if tipo_c == "KILOMETRAJE" else 25.0
                    if margen_val <= umbral_val:
                        from app.services.notification_service import NotificationService
                        NotificationService.notificar_proximo_mantenimiento(
                            db=db,
                            equipo=equipo,
                            margen_restante=margen_val,
                            es_vencido=(margen_val <= 0)
                        )
                except Exception as ex:
                    print(f"[ALERTA PREVENTIVO POST-TURNO ERROR]: {ex}")

            msg_resumen = f"Horas trabajadas: {turno.horas_trabajadas or 0}h" if (turno.horas_trabajadas and turno.horas_trabajadas > 0) else f"Km recorridos: {turno.km_recorridos or 0}km"
            procesados += 1
            detalles.append(BatchSyncItemStatus(
                uuid_local=out.uuid_local,
                tipo="turno_checkout",
                status="actualizado",
                mensaje=f"Check-out completado. {msg_resumen}"
            ))

        # 3. Procesar Cargas de Combustible
        for c in batch.combustibles:
            existente_comb = db.query(ControlCombustible).filter(
                ControlCombustible.uuid_local == c.uuid_local
            ).first()

            if existente_comb:
                duplicados += 1
                detalles.append(BatchSyncItemStatus(
                    uuid_local=c.uuid_local,
                    tipo="combustible",
                    status="duplicado_ignorado",
                    mensaje="Registro previo existente"
                ))
                continue

            precio_gal = float(getattr(c, "precio_por_galon", 0.0) or 0.0)
            if precio_gal < 0:
                precio_gal = 0.0

            total_comb = getattr(c, "costo_total", 0.0) or round((c.galones_cargados or 0.0) * precio_gal, 2)

            combustible = ControlCombustible(
                uuid_local=c.uuid_local,
                equipo_id=c.equipo_id,
                operador_id=c.operador_id,
                proyecto_id=c.proyecto_id,
                horometro_tanqueo=c.horometro_tanqueo,
                galones_cargados=c.galones_cargados,
                precio_por_galon=precio_gal,
                tipo_combustible=c.tipo_combustible,
                foto_comprobante=c.foto_comprobante,
                costo_total=total_comb,
                fecha_hora=c.fecha_hora or datetime.utcnow(),
                estado_sync=EstadoSync.SINCRONIZADO.value
            )
            db.add(combustible)

            procesados += 1
            detalles.append(BatchSyncItemStatus(
                uuid_local=c.uuid_local,
                tipo="combustible",
                status="creado",
                mensaje=f"Tanqueo registrado ({c.galones_cargados} galones)"
            ))

        # 4. Procesar Incidentes de Checkpoint
        for inc in batch.incidentes:
            existente_inc = db.query(IncidenteCheckpoint).filter(
                IncidenteCheckpoint.uuid_local == inc.uuid_local
            ).first()

            if existente_inc:
                duplicados += 1
                detalles.append(BatchSyncItemStatus(
                    uuid_local=inc.uuid_local,
                    tipo="incidente",
                    status="duplicado_ignorado",
                    mensaje="Incidente ya registrado"
                ))
                continue

            incidente = IncidenteCheckpoint(
                uuid_local=inc.uuid_local,
                equipo_id=inc.equipo_id,
                operador_id=inc.operador_id,
                tipo=inc.tipo,
                severidad=inc.severidad.value,
                descripcion=inc.descripcion,
                foto_evidencia=inc.foto_evidencia,
                fecha_hora=inc.fecha_hora or datetime.utcnow(),
                estado="abierto"
            )
            db.add(incidente)

            # Si el incidente detiene el equipo, pasar estado a CRÍTICO / TALLER
            if inc.severidad == SeveridadIncidente.DETIENE_EQUIPO:
                equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == inc.equipo_id).first()
                if equipo:
                    equipo.estado_operativo = EstadoOperativo.CRITICO.value

            procesados += 1
            detalles.append(BatchSyncItemStatus(
                uuid_local=inc.uuid_local,
                tipo="incidente",
                status="creado",
                mensaje=f"Incidente registrado (Severidad: {inc.severidad.value})"
            ))

        db.commit()

        total = len(batch.turnos) + len(batch.turnos_checkout) + len(batch.combustibles) + len(batch.incidentes)
        return BatchSyncResponse(
            success=True,
            total_recibidos=total,
            total_procesados=procesados,
            total_duplicados=duplicados,
            detalles=detalles,
            timestamp_servidor=datetime.utcnow()
        )

    @staticmethod
    def obtener_resumen_dashboard(db: Session) -> Dict[str, Any]:
        """
        Calcula KPIs industriales, semáforos, consumo de combustible y distribución por proyecto.
        """
        # Horas totales trabajadas
        horas_totales = db.query(func.coalesce(func.sum(TurnoOperacion.horas_trabajadas), 0.0)).scalar() or 0.0

        # Horas trabajadas hoy
        hoy = date.today()
        horas_hoy = db.query(func.coalesce(func.sum(TurnoOperacion.horas_trabajadas), 0.0)).filter(
            TurnoOperacion.fecha == hoy
        ).scalar() or 0.0

        # Equipos y estados
        equipos = db.query(MaquinariaEquipo).all()
        total_equipos = len(equipos)
        equipos_taller = sum(1 for e in equipos if e.estado_operativo == EstadoOperativo.TALLER.value)
        
        # Alertas y proximos mantenimientos por máquina
        alertas_servicio = 0
        semaforos = {"verde": 0, "amarillo": 0, "rojo": 0}
        equipos_alertas_txt = []
        proximos_mantenimientos = []
        alertas_documentos = []

        for e in equipos:
            color, horas_rest = HeavyTrackService.calcular_semaforo_equipo(e)
            semaforos[color] += 1
            if color in ["amarillo", "rojo"]:
                alertas_servicio += 1
                detalle_rest = f"({horas_rest}h)" if horas_rest > 0 else "(Vencido)"
                equipos_alertas_txt.append(f"{e.codigo_interno} {detalle_rest}")

            proximos_mantenimientos.append({
                "id": e.id,
                "codigo_interno": e.codigo_interno,
                "nombre": e.nombre or f"{e.marca} {e.modelo}",
                "placa": e.placa or "-",
                "tipo_control": e.tipo_control or "HOROMETRO",
                "horometro_actual": e.horometro_actual or 0.0,
                "odometro_actual": e.odometro_actual or 0.0,
                "horometro_proximo_servicio": e.horometro_proximo_servicio or 250.0,
                "intervalo_servicio": e.intervalo_servicio or 250.0,
                "horas_restantes": horas_rest,
                "semaforo": color,
                "proyecto_nombre": e.proyecto_actual.nombre if e.proyecto_actual else "En Base / Taller",
                "operador_nombre": f"{e.operador_asignado.nombres} {e.operador_asignado.apellidos}" if e.operador_asignado else "Sin Asignar"
            })

            # Control de SOAT y Revisión Técnica
            soat_dias = None
            soat_estado = "sin_registrar"
            if e.soat_vencimiento:
                dias_soat = (e.soat_vencimiento - hoy).days
                soat_dias = dias_soat
                if dias_soat < 0:
                    soat_estado = "vencido"
                elif dias_soat <= 30:
                    soat_estado = "por_vencer"
                else:
                    soat_estado = "vigente"

            rev_dias = None
            rev_estado = "sin_registrar"
            if getattr(e, "revision_tecnica_vencimiento", None):
                dias_rev = (e.revision_tecnica_vencimiento - hoy).days
                rev_dias = dias_rev
                if dias_rev < 0:
                    rev_estado = "vencido"
                elif dias_rev <= 30:
                    rev_estado = "por_vencer"
                else:
                    rev_estado = "vigente"

            alertas_documentos.append({
                "id": e.id,
                "codigo_interno": e.codigo_interno,
                "nombre": e.nombre or f"{e.marca} {e.modelo}",
                "placa": e.placa or "-",
                "soat_numero": e.soat_numero or "-",
                "soat_vencimiento": e.soat_vencimiento.strftime("%Y-%m-%d") if e.soat_vencimiento else None,
                "soat_dias": soat_dias,
                "soat_estado": soat_estado,
                "revision_tecnica_numero": getattr(e, "revision_tecnica_numero", None) or "-",
                "revision_tecnica_vencimiento": e.revision_tecnica_vencimiento.strftime("%Y-%m-%d") if getattr(e, "revision_tecnica_vencimiento", None) else None,
                "revision_dias": rev_dias,
                "revision_estado": rev_estado
            })

        # Ordenar próximos mantenimientos por urgencia (horas restantes menor primero)
        proximos_mantenimientos.sort(key=lambda x: (0 if x["semaforo"] == "rojo" else 1 if x["semaforo"] == "amarillo" else 2, x["horas_restantes"]))

        # Consumo de combustible del mes actual y desglose por máquina
        inicio_mes = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        consumo_mes = db.query(func.coalesce(func.sum(ControlCombustible.galones_cargados), 0.0)).filter(
            ControlCombustible.fecha_hora >= inicio_mes
        ).scalar() or 0.0

        gasto_combustible_mes = db.query(func.coalesce(func.sum(ControlCombustible.costo_total), 0.0)).filter(
            ControlCombustible.fecha_hora >= inicio_mes
        ).scalar() or 0.0

        # Horas trabajadas por máquina
        horas_por_maquina = []
        consumo_por_maquina = []
        for e in equipos:
            horas_eq = db.query(func.coalesce(func.sum(TurnoOperacion.horas_trabajadas), 0.0)).filter(
                TurnoOperacion.equipo_id == e.id
            ).scalar() or 0.0
            horas_por_maquina.append({
                "codigo": e.codigo_interno,
                "nombre": e.nombre or e.codigo_interno,
                "horas": round(float(horas_eq), 1)
            })

            gal_eq = db.query(func.coalesce(func.sum(ControlCombustible.galones_cargados), 0.0)).filter(
                ControlCombustible.equipo_id == e.id
            ).scalar() or 0.0
            soles_eq = db.query(func.coalesce(func.sum(ControlCombustible.costo_total), 0.0)).filter(
                ControlCombustible.equipo_id == e.id
            ).scalar() or 0.0
            consumo_por_maquina.append({
                "codigo": e.codigo_interno,
                "nombre": e.nombre or e.codigo_interno,
                "galones": round(float(gal_eq), 1),
                "soles": round(float(soles_eq), 2)
            })

        # Horas trabajadas por proyecto
        proyectos_stats = []
        proyectos = db.query(Proyecto).all()
        for p in proyectos:
            horas_p = db.query(func.coalesce(func.sum(TurnoOperacion.horas_trabajadas), 0.0)).filter(
                TurnoOperacion.proyecto_id == p.id
            ).scalar() or 0.0
            proyectos_stats.append({
                "proyecto_id": p.id,
                "codigo": p.codigo,
                "nombre": p.nombre,
                "horas": round(float(horas_p), 1)
            })

        return {
            "horas_totales_trabajadas": round(float(horas_totales), 1),
            "horas_hoy": round(float(horas_hoy), 1),
            "total_equipos": total_equipos,
            "equipos_en_taller": equipos_taller,
            "alertas_mantenimiento_25h": alertas_servicio,
            "alertas_detalle": ", ".join(equipos_alertas_txt[:2]) if alertas_servicio > 0 else "",
            "galones_combustible_mes": round(float(consumo_mes), 1),
            "costo_combustible_mes": round(float(gasto_combustible_mes), 2),
            "semaforo_flota": semaforos,
            "horas_por_proyecto": proyectos_stats,
            "horas_por_maquina": horas_por_maquina,
            "consumo_por_maquina": consumo_por_maquina,
            "proximos_mantenimientos": proximos_mantenimientos,
            "alertas_documentos": alertas_documentos
        }
