from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date
import urllib.parse

from app.models.heavytrack import (
    Proyecto, Personal, MaquinariaEquipo, TurnoOperacion,
    ControlCombustible, OrdenMantenimiento, InventarioRepuesto
)
from app.services.heavytrack_service import HeavyTrackService


class ReportService:

    @staticmethod
    def generar_mensaje_whatsapp_gerencia(db: Session, telefono_destino: str = "+51998887766") -> dict:
        """
        Construye el resumen ejecutivo formateado para envío por WhatsApp a Gerencia
        con enlaces al reporte detallado y KPIs clave.
        """
        resumen = HeavyTrackService.obtener_resumen_dashboard(db)
        hoy_str = datetime.utcnow().strftime("%d/%m/%Y %H:%M")

        # Equipos con alertas < 25h
        equipos = db.query(MaquinariaEquipo).all()
        alertas_txt = []
        for eq in equipos:
            color, horas_rest = HeavyTrackService.calcular_semaforo_equipo(eq)
            if color == "rojo":
                alertas_txt.append(f"  🔴 *{eq.codigo_interno}* ({eq.marca} {eq.modelo}): Mantenimiento VENCIDO hace {abs(horas_rest)}h.")
            elif color == "amarillo":
                alertas_txt.append(f"  🟡 *{eq.codigo_interno}* ({eq.marca} {eq.modelo}): Faltan *{horas_rest}h* para servicio de 250h.")

        alertas_str = "\n".join(alertas_txt) if alertas_txt else "  ✅ Ninguna alerta crítica. Flota 100% al día."

        # Proyectos
        proyectos_txt = []
        for p in resumen["horas_por_proyecto"]:
            proyectos_txt.append(f"  • *{p['codigo']}* ({p['nombre']}): {p['horas']} horas.")
        proyectos_str = "\n".join(proyectos_txt)

        mensaje = (
            f"🚜 *HEAVYTRACK ENTERPRISE — REPORTE EJECUTIVO A GERENCIA*\n"
            f"📅 *Corte:* {hoy_str}\n\n"
            f"📊 *KPIs GLOBALES DE FLOTA:*\n"
            f"• *Horas Totales Trabajadas:* {resumen['horas_totales_trabajadas']} h\n"
            f"• *Equipos Operativos:* {resumen['semaforo_flota']['verde']} de {resumen['total_equipos']}\n"
            f"• *Equipos en Taller / Críticos:* {resumen['equipos_en_taller']} unidades\n"
            f"• *Combustible Mes:* {resumen['galones_combustible_mes']} Gal (S/ {resumen['costo_combustible_mes']:,.2f})\n\n"
            f"⚠️ *ALERTAS DE MANTENIMIENTO PREVENTIVO (< 25h):*\n"
            f"{alertas_str}\n\n"
            f"🏗️ *AVANCE POR FRENTE DE OBRA:*\n"
            f"{proyectos_str}\n\n"
            f"📄 *Reporte Completo en PDF:* http://localhost:8000/api/v1/heavy/reportes/pdf\n"
            f"🔒 *Acceso Gerencial:* http://localhost:8000"
        )

        # Enlace directo de WhatsApp Web / App
        encoded_msg = urllib.parse.quote(mensaje)
        whatsapp_url = f"https://api.whatsapp.com/send?phone={telefono_destino.replace('+', '').replace(' ', '')}&text={encoded_msg}"

        return {
            "mensaje_texto": mensaje,
            "telefono_destino": telefono_destino,
            "whatsapp_link": whatsapp_url,
            "timestamp": hoy_str
        }

    @staticmethod
    def generar_html_reporte_pdf(db: Session) -> str:
        """
        Genera el documento imprimible/PDF para entrega a Encargados de Área y Gerencia.
        """
        resumen = HeavyTrackService.obtener_resumen_dashboard(db)
        equipos = db.query(MaquinariaEquipo).all()
        proyectos = db.query(Proyecto).all()
        repuestos_bajos = db.query(InventarioRepuesto).filter(
            InventarioRepuesto.stock_actual <= InventarioRepuesto.stock_minimo
        ).all()

        fecha_str = datetime.utcnow().strftime("%d/%m/%Y")

        filas_equipos = ""
        for eq in equipos:
            color, horas_rest = HeavyTrackService.calcular_semaforo_equipo(eq)
            color_badge = "#10B981" if color == "verde" else ("#F59E0B" if color == "amarillo" else "#EF4444")
            estado_txt = "OPERATIVO" if color == "verde" else ("<25h PRÓX" if color == "amarillo" else "VENCIDO")

            filas_equipos += f"""
            <tr>
              <td style="font-weight:bold; color:#FFB800;">{eq.codigo_interno}</td>
              <td>{eq.marca} {eq.modelo}</td>
              <td>{eq.tipo.upper()}</td>
              <td style="text-align:right;">{eq.horometro_actual:.1f} h</td>
              <td style="text-align:right;">{eq.horometro_proximo_servicio:.1f} h</td>
              <td style="text-align:right; font-weight:bold; color:{color_badge};">{horas_rest:.1f} h</td>
              <td style="text-align:center;"><span style="background:{color_badge}; color:#000; padding:2px 8px; border-radius:4px; font-weight:bold; font-size:10px;">{estado_txt}</span></td>
            </tr>
            """

        filas_repuestos = ""
        for r in repuestos_bajos:
            filas_repuestos += f"""
            <tr>
              <td><strong>{r.codigo_parte}</strong></td>
              <td>{r.nombre}</td>
              <td style="text-align:center; color:#EF4444; font-weight:bold;">{r.stock_actual} (Mín: {r.stock_minimo})</td>
              <td style="text-align:right;">S/ {r.precio_unitario:.2f}</td>
              <td>{r.ubicacion_almacen or 'Almacén Central'}</td>
            </tr>
            """

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <title>Reporte Ejecutivo HeavyTrack - {fecha_str}</title>
          <style>
            body {{ font-family: Arial, sans-serif; background: #fff; color: #111; margin: 30px; font-size: 12px; }}
            .header {{ border-bottom: 2px solid #FFB800; padding-bottom: 15px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }}
            .title {{ font-size: 20px; font-weight: bold; color: #121417; }}
            .badge-brand {{ background: #FFB800; color: #121417; padding: 4px 10px; font-weight: bold; border-radius: 4px; display: inline-block; }}
            .kpi-box {{ display: inline-block; width: 23%; background: #f4f4f5; padding: 12px; border-radius: 6px; margin-right: 1.5%; box-sizing: border-box; }}
            .kpi-val {{ font-size: 18px; font-weight: bold; color: #121417; margin-top: 4px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th {{ background: #1E2228; color: #fff; text-align: left; padding: 8px; font-size: 11px; text-transform: uppercase; }}
            td {{ padding: 8px; border-bottom: 1px solid #e5e7eb; }}
            .section-title {{ font-size: 14px; font-weight: bold; margin-top: 25px; color: #1E2228; border-left: 4px solid #FFB800; padding-left: 8px; }}
            .footer {{ margin-top: 40px; font-size: 10px; color: #6b7280; text-align: center; border-top: 1px solid #e5e7eb; padding-top: 10px; }}
            @media print {{ body {{ margin: 0; }} }}
          </style>
        </head>
        <body>
          <div class="header">
            <div>
              <div class="badge-brand">HEAVYTRACK ENTERPRISE</div>
              <div class="title" style="margin-top:6px;">REPORTE INTEGRAL DE FLOTA Y OPERACIONES</div>
              <div style="color: #6b7280; font-size: 11px;">Documento Oficial para Gerencia y Jefaturas de Obra</div>
            </div>
            <div style="text-align: right; font-size: 11px;">
              <strong>Fecha de Emisión:</strong> {fecha_str}<br>
              <strong>Sistema:</strong> HeavyTrack On-Premise v2.0
            </div>
          </div>

          <!-- KPIs -->
          <div style="margin-bottom: 20px;">
            <div class="kpi-box">
              <span style="color:#6b7280; font-size:10px; font-weight:bold;">HORAS TRABAJADAS</span>
              <div class="kpi-val">{resumen['horas_totales_trabajadas']:.1f} h</div>
            </div>
            <div class="kpi-box">
              <span style="color:#6b7280; font-size:10px; font-weight:bold;">EQUIPOS OPERATIVOS</span>
              <div class="kpi-val" style="color:#10B981;">{resumen['semaforo_flota']['verde']} / {resumen['total_equipos']}</div>
            </div>
            <div class="kpi-box">
              <span style="color:#6b7280; font-size:10px; font-weight:bold;">ALERTAS &lt; 25h</span>
              <div class="kpi-val" style="color:#EF4444;">{resumen['alertas_mantenimiento_25h']} Críticas</div>
            </div>
            <div class="kpi-box" style="margin-right:0;">
              <span style="color:#6b7280; font-size:10px; font-weight:bold;">COMBUSTIBLE MES</span>
              <div class="kpi-val">{resumen['galones_combustible_mes']:.1f} Gal</div>
            </div>
          </div>

          <!-- Tabla Maquinaria -->
          <div class="section-title">ESTADO DE MAQUINARIA PESADA Y HORÓMETROS (INTERVALO 250H)</div>
          <table>
            <thead>
              <tr>
                <th>Código</th>
                <th>Equipo / Modelo</th>
                <th>Tipo</th>
                <th style="text-align:right;">Horómetro</th>
                <th style="text-align:right;">Próx. Servicio</th>
                <th style="text-align:right;">Horas Restantes</th>
                <th style="text-align:center;">Semáforo</th>
              </tr>
            </thead>
            <tbody>
              {filas_equipos}
            </tbody>
          </table>

          <!-- Repuestos Críticos -->
          <div class="section-title">REPUESTOS CRÍTICOS POR REABASTECER (STOCK &le; MÍNIMO)</div>
          <table>
            <thead>
              <tr>
                <th>Código Parte</th>
                <th>Descripción</th>
                <th style="text-align:center;">Stock Actual / Mínimo</th>
                <th style="text-align:right;">Precio Unit.</th>
                <th>Ubicación</th>
              </tr>
            </thead>
            <tbody>
              {filas_repuestos if filas_repuestos else '<tr><td colspan="5" style="text-align:center; color:#10B981;">Stock en niveles óptimos.</td></tr>'}
            </tbody>
          </table>

          <div class="footer">
            HeavyTrack Enterprise © 2026 — Generado automáticamente con FastAPI y SQLAlchemy. Firma y sello de supervisión de área.
          </div>
        </body>
        </html>
        """
        return html
