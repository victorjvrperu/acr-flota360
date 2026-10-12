from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Tuple

from app.models.heavytrack import (
    Proyecto, Personal, MaquinariaEquipo, TurnoOperacion,
    ControlCombustible, IncidenteCheckpoint, OrdenMantenimiento,
    InventarioRepuesto, Proveedor, MantenimientoRepuesto,
    EstadoOperativo, SeveridadIncidente, EstadoSync,
    EstadoOrdenMantenimiento
)
from app.schemas.heavytrack import (
    BatchSyncRequest, BatchSyncResponse, BatchSyncItemStatus
)


class HeavyTrackService:

    @staticmethod
    def calcular_semaforo_equipo(equipo: MaquinariaEquipo) -> Tuple[str, float]:
        """
        Regla de negocio:
        - Si horometro_actual >= (horometro_proximo_servicio - 25): Alerta Amarilla ("Próximo a servicio").
        - Si horometro_actual >= horometro_proximo_servicio: Alerta Roja ("Mantenimiento Vencido").
        - Si está por debajo: Verde ("Operativo").
        """
        horas_restantes = round(equipo.horometro_proximo_servicio - equipo.horometro_actual, 1)

        if equipo.horometro_actual >= equipo.horometro_proximo_servicio:
            return "rojo", horas_restantes
        elif equipo.horometro_actual >= (equipo.horometro_proximo_servicio - 25.0):
            return "amarillo", horas_restantes
        else:
            return "verde", horas_restantes

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
                foto_combustible=getattr(turno_in, "foto_combustible", None),
                foto_inicio_delantera=getattr(turno_in, "foto_inicio_delantera", None),
                foto_inicio_trasera=getattr(turno_in, "foto_inicio_trasera", None),
                foto_inicio_izquierda=getattr(turno_in, "foto_inicio_izquierda", None),
                foto_inicio_derecha=getattr(turno_in, "foto_inicio_derecha", None),
                estado_sync=EstadoSync.SINCRONIZADO.value
            )
            db.add(turno)

            # Si abasteció combustible en el check-in, registrar automáticamente en control_combustible
            if getattr(turno_in, "abastecio_combustible", False) and getattr(turno_in, "foto_combustible", None):
                comb_rec = ControlCombustible(
                    uuid_local=f"comb-{turno_in.uuid_local}",
                    equipo_id=turno_in.equipo_id,
                    operador_id=turno_in.operador_id,
                    proyecto_id=turno_in.proyecto_id,
                    horometro_tanqueo=turno_in.horometro_inicio,
                    galones_cargados=getattr(turno_in, "combustible_galones", 0.0) or 0.0,
                    foto_comprobante=turno_in.foto_combustible,
                    costo_total=(getattr(turno_in, "combustible_galones", 0.0) or 0.0) * 18.5,
                    estado_sync=EstadoSync.SINCRONIZADO.value
                )
                db.add(comb_rec)

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

                if turno_in.horometro_inicio > equipo.horometro_actual:
                    equipo.horometro_actual = turno_in.horometro_inicio
                    color, _ = HeavyTrackService.calcular_semaforo_equipo(equipo)
                    if color == "rojo" or color == "amarillo":
                        equipo.estado_operativo = EstadoOperativo.CRITICO.value
                km_ini = getattr(turno_in, "kilometraje_inicio", 0.0) or 0.0
                if km_ini > (equipo.odometro_actual or 0.0):
                    equipo.odometro_actual = km_ini

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

            lat_fin = getattr(out, "latitud_fin", None)
            lng_fin = getattr(out, "longitud_fin", None)
            if lat_fin is not None and lng_fin is not None:
                turno.latitud_fin = lat_fin
                turno.longitud_fin = lng_fin
                if turno.equipo:
                    turno.equipo.ultima_latitud = lat_fin
                    turno.equipo.ultima_longitud = lng_fin
                    turno.equipo.ultima_ubicacion_fecha = datetime.utcnow()

            if turno.horometro_fin and turno.horometro_inicio:
                turno.horas_trabajadas = round(max(0.0, turno.horometro_fin - turno.horometro_inicio), 1)

            km_fin = getattr(out, "kilometraje_fin", 0.0) or 0.0
            if km_fin > 0:
                turno.kilometraje_fin = km_fin
                if turno.kilometraje_inicio and km_fin >= turno.kilometraje_inicio:
                    turno.km_recorridos = round(km_fin - turno.kilometraje_inicio, 1)

            # Actualización automática de horómetro y odómetro del equipo y semáforo
            equipo = db.query(MaquinariaEquipo).filter(MaquinariaEquipo.id == turno.equipo_id).first()
            if equipo:
                if out.horometro_fin > equipo.horometro_actual:
                    equipo.horometro_actual = out.horometro_fin
                    color, _ = HeavyTrackService.calcular_semaforo_equipo(equipo)
                    if color == "rojo" or color == "amarillo":
                        equipo.estado_operativo = EstadoOperativo.CRITICO.value
                if km_fin > (equipo.odometro_actual or 0.0):
                    equipo.odometro_actual = km_fin
                    equipo.estado_operativo = EstadoOperativo.CRITICO.value

            procesados += 1
            detalles.append(BatchSyncItemStatus(
                uuid_local=out.uuid_local,
                tipo="turno_checkout",
                status="actualizado",
                mensaje=f"Check-out completado. Horas trabajadas: {turno.horas_trabajadas or 0}h"
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

            combustible = ControlCombustible(
                uuid_local=c.uuid_local,
                equipo_id=c.equipo_id,
                operador_id=c.operador_id,
                proyecto_id=c.proyecto_id,
                horometro_tanqueo=c.horometro_tanqueo,
                galones_cargados=c.galones_cargados,
                tipo_combustible=c.tipo_combustible,
                foto_comprobante=c.foto_comprobante,
                costo_total=c.costo_total,
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

        # Equipos y estados
        equipos = db.query(MaquinariaEquipo).all()
        total_equipos = len(equipos)
        equipos_taller = sum(1 for e in equipos if e.estado_operativo == EstadoOperativo.TALLER.value)
        
        # Alertas < 25h de servicio
        alertas_servicio = 0
        semaforos = {"verde": 0, "amarillo": 0, "rojo": 0}
        for e in equipos:
            color, _ = HeavyTrackService.calcular_semaforo_equipo(e)
            semaforos[color] += 1
            if color in ["amarillo", "rojo"]:
                alertas_servicio += 1

        # Consumo de combustible del mes actual
        inicio_mes = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        consumo_mes = db.query(func.coalesce(func.sum(ControlCombustible.galones_cargados), 0.0)).filter(
            ControlCombustible.fecha_hora >= inicio_mes
        ).scalar() or 0.0

        gasto_combustible_mes = db.query(func.coalesce(func.sum(ControlCombustible.costo_total), 0.0)).filter(
            ControlCombustible.fecha_hora >= inicio_mes
        ).scalar() or 0.0

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
            "total_equipos": total_equipos,
            "equipos_en_taller": equipos_taller,
            "alertas_mantenimiento_25h": alertas_servicio,
            "galones_combustible_mes": round(float(consumo_mes), 1),
            "costo_combustible_mes": round(float(gasto_combustible_mes), 2),
            "semaforo_flota": semaforos,
            "horas_por_proyecto": proyectos_stats
        }
