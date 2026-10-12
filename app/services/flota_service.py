from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime, timedelta
from typing import List, Dict, Any

from app.models.vehiculo import Vehiculo, EstadoVehiculo
from app.models.conductor import Conductor, EstadoConductor
from app.models.mantenimiento import Mantenimiento, EstadoMantenimiento
from app.models.combustible import CargaCombustible
from app.models.viaje import Viaje, EstadoViaje
from app.schemas.dashboard import DashboardStats, AlertaItem


class FlotaService:

    @staticmethod
    def obtener_alertas_flota(db: Session) -> List[AlertaItem]:
        alertas: List[AlertaItem] = []
        hoy = date.today()
        limite_proximo = hoy + timedelta(days=30)

        # 1. Alertas de SOAT
        vehiculos_soat = db.query(Vehiculo).filter(
            Vehiculo.soat_vencimiento.isnot(None),
            Vehiculo.soat_vencimiento <= limite_proximo
        ).all()

        for v in vehiculos_soat:
            dias = (v.soat_vencimiento - hoy).days
            nivel = "urgente" if dias <= 7 else "alerta"
            msg = f"SOAT vencido hace {abs(dias)} días" if dias < 0 else f"SOAT vence en {dias} días ({v.soat_vencimiento.strftime('%d/%m/%Y')})"
            alertas.append(AlertaItem(
                tipo="soat",
                nivel=nivel,
                titulo=f"SOAT - Unidad {v.placa}",
                mensaje=msg,
                dias_restantes=dias,
                referencia_id=v.id,
                placa_o_nombre=v.placa
            ))

        # 2. Alertas de Revisión Técnica
        vehiculos_rev = db.query(Vehiculo).filter(
            Vehiculo.revision_tecnica_vencimiento.isnot(None),
            Vehiculo.revision_tecnica_vencimiento <= limite_proximo
        ).all()

        for v in vehiculos_rev:
            dias = (v.revision_tecnica_vencimiento - hoy).days
            nivel = "urgente" if dias <= 7 else "alerta"
            msg = f"Revisión Técnica vencida hace {abs(dias)} días" if dias < 0 else f"Revisión Técnica vence en {dias} días ({v.revision_tecnica_vencimiento.strftime('%d/%m/%Y')})"
            alertas.append(AlertaItem(
                tipo="revision_tecnica",
                nivel=nivel,
                titulo=f"Revisión Técnica - {v.placa}",
                mensaje=msg,
                dias_restantes=dias,
                referencia_id=v.id,
                placa_o_nombre=v.placa
            ))

        # 3. Alertas de Licencias de Conducir
        conductores = db.query(Conductor).filter(
            Conductor.licencia_vencimiento <= limite_proximo
        ).all()

        for c in conductores:
            dias = (c.licencia_vencimiento - hoy).days
            nivel = "urgente" if dias <= 7 else "alerta"
            msg = f"Licencia vencida hace {abs(dias)} días" if dias < 0 else f"Licencia vence en {dias} días ({c.licencia_vencimiento.strftime('%d/%m/%Y')})"
            alertas.append(AlertaItem(
                tipo="licencia",
                nivel=nivel,
                titulo=f"Licencia - {c.nombres} {c.apellidos}",
                mensaje=msg,
                dias_restantes=dias,
                referencia_id=c.id,
                placa_o_nombre=f"{c.nombres} {c.apellidos}"
            ))

        # 4. Mantenimientos programados pendientes
        mants = db.query(Mantenimiento).join(Vehiculo).filter(
            Mantenimiento.estado.in_([EstadoMantenimiento.PROGRAMADO.value, EstadoMantenimiento.EN_TALLER.value]),
            Mantenimiento.fecha_programada <= limite_proximo
        ).all()

        for m in mants:
            dias = (m.fecha_programada - hoy).days
            nivel = "urgente" if dias < 0 else ("alerta" if dias <= 5 else "informativo")
            placa = m.vehiculo.placa if m.vehiculo else "N/A"
            alertas.append(AlertaItem(
                tipo="mantenimiento",
                nivel=nivel,
                titulo=f"Mantenimiento - {placa}",
                mensaje=f"{m.tipo.upper()}: {m.descripcion} ({'Vencido' if dias < 0 else f'en {dias} días'})",
                dias_restantes=dias,
                referencia_id=m.id,
                placa_o_nombre=placa
            ))

        # Ordenar: primero urgentes, luego alerta, luego informativo
        prioridad = {"urgente": 0, "alerta": 1, "informativo": 2}
        alertas.sort(key=lambda a: (prioridad.get(a.nivel, 99), a.dias_restantes if a.dias_restantes is not None else 999))
        return alertas

    @staticmethod
    def obtener_estadisticas_dashboard(db: Session) -> DashboardStats:
        total_vehiculos = db.query(Vehiculo).count()
        vehiculos_operativos = db.query(Vehiculo).filter(Vehiculo.estado == EstadoVehiculo.OPERATIVO.value).count()
        vehiculos_en_ruta = db.query(Vehiculo).filter(Vehiculo.estado == EstadoVehiculo.EN_RUTA.value).count()
        vehiculos_en_mantenimiento = db.query(Vehiculo).filter(Vehiculo.estado == EstadoVehiculo.MANTENIMIENTO.value).count()

        total_conductores = db.query(Conductor).count()
        conductores_activos = db.query(Conductor).filter(Conductor.estado == EstadoConductor.ACTIVO.value).count()

        mantenimientos_pendientes = db.query(Mantenimiento).filter(
            Mantenimiento.estado.in_([EstadoMantenimiento.PROGRAMADO.value, EstadoMantenimiento.EN_TALLER.value])
        ).count()

        viajes_en_curso = db.query(Viaje).filter(Viaje.estado == EstadoViaje.EN_CURSO.value).count()

        # Gastos mes corriente
        primer_dia_mes = date.today().replace(day=1)
        gasto_combustible = db.query(func.coalesce(func.sum(CargaCombustible.costo_total), 0.0)).filter(
            CargaCombustible.fecha >= primer_dia_mes
        ).scalar() or 0.0

        gasto_mantenimiento = db.query(func.coalesce(func.sum(Mantenimiento.costo), 0.0)).filter(
            Mantenimiento.fecha_programada >= primer_dia_mes
        ).scalar() or 0.0

        alertas = FlotaService.obtener_alertas_flota(db)

        return DashboardStats(
            total_vehiculos=total_vehiculos,
            vehiculos_operativos=vehiculos_operativos,
            vehiculos_en_ruta=vehiculos_en_ruta,
            vehiculos_en_mantenimiento=vehiculos_en_mantenimiento,
            total_conductores=total_conductores,
            conductores_activos=conductores_activos,
            mantenimientos_pendientes=mantenimientos_pendientes,
            viajes_en_curso=viajes_en_curso,
            gasto_combustible_mes=round(float(gasto_combustible), 2),
            gasto_mantenimiento_mes=round(float(gasto_mantenimiento), 2),
            alertas=alertas
        )

    @staticmethod
    def registrar_carga_combustible(db: Session, carga_data: dict) -> CargaCombustible:
        vehiculo = db.query(Vehiculo).filter(Vehiculo.id == carga_data["vehiculo_id"]).first()
        
        # Calcular rendimiento si hay una carga anterior
        rendimiento = None
        ultima_carga = db.query(CargaCombustible).filter(
            CargaCombustible.vehiculo_id == carga_data["vehiculo_id"],
            CargaCombustible.odometro < carga_data["odometro"]
        ).order_by(CargaCombustible.odometro.desc()).first()

        if ultima_carga and carga_data["cantidad"] > 0:
            km_recorridos = carga_data["odometro"] - ultima_carga.odometro
            if km_recorridos > 0:
                rendimiento = round(km_recorridos / carga_data["cantidad"], 2)

        carga = CargaCombustible(
            **carga_data,
            rendimiento_km_unidad=rendimiento
        )
        db.add(carga)

        # Actualizar odómetro del vehículo si es mayor
        if vehiculo and carga_data["odometro"] > vehiculo.odometro_actual:
            vehiculo.odometro_actual = carga_data["odometro"]

        db.commit()
        db.refresh(carga)
        return carga
