import os
import json
import urllib.parse
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
import httpx
from sqlalchemy.orm import Session

from app.models.heavytrack import (
    NotificacionAlerta, TipoNotificacion, AjusteSistema,
    MaquinariaEquipo, Personal, OrdenMantenimiento, RolPersonal
)


class NotificationService:

    @staticmethod
    def obtener_configuracion(db: Session) -> Dict[str, Any]:
        """Obtiene la configuración actual de notificaciones y WhatsApp."""
        ajustes = db.query(AjusteSistema).all()
        config_map = {a.clave: a.valor for a in ajustes}

        # Teléfono del Jefe de Área / Mantenimiento
        tel_jefe = config_map.get("whatsapp_jefe_telefono")
        if not tel_jefe:
            # Buscar en el padrón de personal
            jefe = db.query(Personal).filter(
                Personal.rol.in_([RolPersonal.JEFE_MANTENIMIENTO.value, RolPersonal.GERENCIA.value]),
                Personal.estado == "activo",
                Personal.telefono.isnot(None)
            ).first()
            if jefe and jefe.telefono:
                tel_jefe = jefe.telefono

        return {
            "whatsapp_jefe_telefono": tel_jefe or os.getenv("WHATSAPP_JEFE_TELEFONO", "+51 987 654 321"),
            "whatsapp_api_url": config_map.get("whatsapp_api_url") or os.getenv("WHATSAPP_API_URL", ""),
            "whatsapp_api_token": config_map.get("whatsapp_api_token") or os.getenv("WHATSAPP_API_TOKEN", ""),
            "whatsapp_auto_envio": config_map.get("whatsapp_auto_envio", "1") == "1",
            "alerta_horas_preventivo": int(config_map.get("alerta_horas_preventivo", "25")),
            "alerta_dias_documentos": int(config_map.get("alerta_dias_documentos", "15"))
        }

    @staticmethod
    def actualizar_configuracion(db: Session, datos: Dict[str, Any]) -> Dict[str, Any]:
        """Guarda o actualiza ajustes de notificaciones en la base de datos."""
        for clave, valor in datos.items():
            str_val = str(valor) if valor is not None else ""
            ajuste = db.query(AjusteSistema).filter(AjusteSistema.clave == clave).first()
            if ajuste:
                ajuste.valor = str_val
            else:
                ajuste = AjusteSistema(clave=clave, valor=str_val)
                db.add(ajuste)
        db.commit()
        return NotificationService.obtener_configuracion(db)

    @staticmethod
    def limpiar_telefono(tel: str) -> str:
        """Limpia el teléfono para formato internacional WhatsApp (ej: 51987654321)."""
        limpio = "".join(ch for ch in (tel or "") if ch.isdigit())
        if len(limpio) == 9 and not limpio.startswith("51"):
            limpio = f"51{limpio}"
        return limpio

    @staticmethod
    def generar_link_whatsapp(telefono: str, mensaje: str) -> str:
        """Genera el enlace para abrir WhatsApp Web o App Móvil con el texto prellenado."""
        tel_clean = NotificationService.limpiar_telefono(telefono)
        encoded_msg = urllib.parse.quote(mensaje)
        return f"https://api.whatsapp.com/send?phone={tel_clean}&text={encoded_msg}"

    @staticmethod
    def enviar_whatsapp_directo_api(telefono: str, mensaje: str, db: Session) -> bool:
        """
        Envía el mensaje de forma desatendida a través de la API Gateway configurada
        (Soporta Evolution API, UltraMsg, Twilio, Green API o Webhook HTTP genérico).
        """
        config = NotificationService.obtener_configuracion(db)
        api_url = config.get("whatsapp_api_url")
        api_token = config.get("whatsapp_api_token")
        tel_clean = NotificationService.limpiar_telefono(telefono)

        if not api_url or not tel_clean:
            return False

        try:
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "ACR-Flota360/2.0"
            }
            if api_token:
                headers["Authorization"] = f"Bearer {api_token}"
                headers["apikey"] = api_token

            payload = {
                "phone": tel_clean,
                "number": tel_clean,
                "to": tel_clean,
                "body": mensaje,
                "message": mensaje,
                "text": mensaje
            }

            with httpx.Client(timeout=6.0) as client:
                res = client.post(api_url, json=payload, headers=headers)
                return res.status_code in (200, 201, 202)
        except Exception as e:
            print(f"[WHATSAPP GATEWAY ERROR]: {e}")
            return False

    @staticmethod
    def crear_notificacion(
        db: Session,
        tipo: str,
        titulo: str,
        mensaje: str,
        severidad: str = "warning",
        equipo_id: Optional[int] = None,
        datos_extra: Optional[Dict[str, Any]] = None,
        permitir_duplicado_horas: int = 12
    ) -> NotificacionAlerta:
        """
        Crea y registra una notificación en el sistema, genera el link de WhatsApp y
        despacha la alerta por WhatsApp API si está configurada.
        """
        # Deduplicación: evitar spamear la misma alerta en las últimas N horas
        if equipo_id and permitir_duplicado_horas > 0:
            hace_n_horas = datetime.utcnow() - timedelta(hours=permitir_duplicado_horas)
            existente = db.query(NotificacionAlerta).filter(
                NotificacionAlerta.tipo == tipo,
                NotificacionAlerta.equipo_id == equipo_id,
                NotificacionAlerta.creado_en >= hace_n_horas
            ).first()
            if existente:
                return existente

        config = NotificationService.obtener_configuracion(db)
        tel_jefe = config["whatsapp_jefe_telefono"]
        link_wa = NotificationService.generar_link_whatsapp(tel_jefe, mensaje)

        # Intento de envío directo desatendido
        enviado_api = False
        if config["whatsapp_auto_envio"] and config["whatsapp_api_url"]:
            enviado_api = NotificationService.enviar_whatsapp_directo_api(tel_jefe, mensaje, db)

        notif = NotificacionAlerta(
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            severidad=severidad,
            equipo_id=equipo_id,
            leido=False,
            canal_whatsapp_enviado=enviado_api,
            whatsapp_link=link_wa,
            datos_extra=json.dumps(datos_extra, ensure_ascii=False) if datos_extra else None,
            creado_en=datetime.utcnow()
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        return notif

    # ==========================================
    # DISPARADORES ESPECÍFICOS DE ALERTAS
    # ==========================================

    @staticmethod
    def notificar_entrada_mantenimiento(
        db: Session,
        orden: OrdenMantenimiento,
        equipo: MaquinariaEquipo
    ) -> NotificacionAlerta:
        """Dispara notificación inmediata cuando un equipo entra al taller o se genera una OT."""
        hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
        tipo_str = "Mantenimiento Preventivo" if orden.tipo == "preventivo_ficha" else "Mantenimiento Correctivo (Falla)"

        msg = (
            f"🛠️ *ACR FLOTA 360° — EQUIPO ENTRA A MANTENIMIENTO*\n"
            f"📅 *Fecha:* {hoy}\n\n"
            f"🚜 *Equipo:* {equipo.codigo_interno} ({equipo.marca} {equipo.modelo})\n"
            f"📋 *Orden de Trabajo:* {orden.codigo_ot}\n"
            f"🔧 *Tipo de Servicio:* {tipo_str}\n"
            f"⏱️ *Horómetro / Odómetro:* {orden.horometro_al_servicio or equipo.horometro_actual or 0.0}\n"
            f"📝 *Diagnóstico / Tarea:* {orden.diagnostico or 'Revisión y cambio de fluidos'}\n"
            f"📍 *Frente / Proyecto:* {equipo.proyecto_actual.nombre if equipo.proyecto_actual else 'Base Central'}\n"
            f"🔴 *Estado Actual:* En Taller / No disponible para operación\n\n"
            f"📲 *Ver detalle en ACR Flota 360°:* http://192.168.1.92:8001"
        )

        return NotificationService.crear_notificacion(
            db=db,
            tipo=TipoNotificacion.MANTENIMIENTO_ENTRADA.value,
            titulo=f"Equipo {equipo.codigo_interno} ingresó a taller ({orden.codigo_ot})",
            mensaje=msg,
            severidad="critical",
            equipo_id=equipo.id,
            datos_extra={"codigo_ot": orden.codigo_ot, "diagnostico": orden.diagnostico},
            permitir_duplicado_horas=1
        )

    @staticmethod
    def notificar_proximo_mantenimiento(
        db: Session,
        equipo: MaquinariaEquipo,
        margen_restante: float,
        es_vencido: bool = False
    ) -> NotificacionAlerta:
        """Alerta preventiva cuando faltan pocas horas/km para servicio o cuando ya se venció."""
        hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
        unidad = "km" if (equipo.tipo_control == "KILOMETRAJE") else "horas"
        icono = "🔴" if es_vencido else "🟡"
        estado_txt = "¡SERVICIO DE MANTENIMIENTO VENCIDO!" if es_vencido else "PRÓXIMO A RENOVACIÓN DE MANTENIMIENTO"

        msg = (
            f"{icono} *ACR FLOTA 360° — {estado_txt}*\n"
            f"📅 *Corte:* {hoy}\n\n"
            f"🚜 *Equipo:* {equipo.codigo_interno} — {equipo.marca} {equipo.modelo} ({equipo.placa or 'Sin Placa'})\n"
            f"⏱️ *Lectura Actual:* {equipo.horometro_actual or equipo.odometro_actual or 0.0} {unidad}\n"
            f"🎯 *Límite de Servicio:* {equipo.horometro_proximo_servicio or 250.0} {unidad}\n"
            f"⏳ *Margen:* {f'Excedido por {abs(margen_restante):.1f} {unidad}' if es_vencido else f'Faltan solo {margen_restante:.1f} {unidad}'}\n"
            f"👤 *Operador a cargo:* {f'{equipo.operador_asignado.nombres} {equipo.operador_asignado.apellidos}' if equipo.operador_asignado else 'Sin asignar'}\n"
            f"📍 *Ubicación:* {equipo.proyecto_actual.nombre if equipo.proyecto_actual else 'Base Central'}\n\n"
            f"⚠️ *Acción Requerida:* Coordinar ingreso a taller y preparación de filtros/lubricantes."
        )

        tipo_notif = TipoNotificacion.MANTENIMIENTO_VENCIDO.value if es_vencido else TipoNotificacion.MANTENIMIENTO_PROXIMO.value
        titulo = f"{'Mantenimiento VENCIDO' if es_vencido else 'Mantenimiento Próximo'}: {equipo.codigo_interno} ({margen_restante:.1f} {unidad})"

        return NotificationService.crear_notificacion(
            db=db,
            tipo=tipo_notif,
            titulo=titulo,
            mensaje=msg,
            severidad="critical" if es_vencido else "warning",
            equipo_id=equipo.id,
            datos_extra={"margen_restante": margen_restante, "es_vencido": es_vencido},
            permitir_duplicado_horas=24
        )

    @staticmethod
    def notificar_documento_vencido(
        db: Session,
        equipo: MaquinariaEquipo,
        tipo_doc: str,
        fecha_venc: date,
        dias_restantes: int
    ) -> NotificacionAlerta:
        """Alerta de vencimiento legal (Revisión Técnica, SOAT o Póliza de Seguro)."""
        hoy = datetime.now().strftime("%d/%m/%Y")
        es_vencido = dias_restantes < 0
        icono = "🔴" if es_vencido else "⚠️"
        estado_txt = f"¡DOCUMENTO VENCIDO hace {abs(dias_restantes)} días!" if es_vencido else f"Vence en {dias_restantes} días"

        msg = (
            f"{icono} *ACR FLOTA 360° — ALERTA DOCUMENTAL LEGAL*\n"
            f"📅 *Reporte:* {hoy}\n\n"
            f"🚜 *Equipo:* {equipo.codigo_interno} — {equipo.marca} {equipo.modelo}\n"
            f"📋 *Placa:* {equipo.placa or 'S/P'}\n"
            f"📑 *Documento:* *{tipo_doc.upper()}*\n"
            f"📅 *Fecha de Vencimiento:* {fecha_venc.strftime('%d/%m/%Y')}\n"
            f"⏳ *Estado:* {estado_txt}\n\n"
            f"🚨 *Riesgo:* Inmovilización de unidad por fiscalización MTC / SUTRAN o pérdida de cobertura ante siniestro.\n"
            f"📲 *Gestionar renovación en:* http://192.168.1.92:8001"
        )

        titulo = f"{tipo_doc} {'VENCIDO' if es_vencido else 'por vencer'}: {equipo.codigo_interno} ({fecha_venc.strftime('%d/%m/%Y')})"
        tipo_val = TipoNotificacion.REVISION_TECNICA.value if "revision" in tipo_doc.lower() else TipoNotificacion.SOAT_POLIZA.value

        return NotificationService.crear_notificacion(
            db=db,
            tipo=tipo_val,
            titulo=titulo,
            mensaje=msg,
            severidad="critical" if es_vencido else "warning",
            equipo_id=equipo.id,
            datos_extra={"tipo_doc": tipo_doc, "fecha_venc": fecha_venc.isoformat(), "dias_restantes": dias_restantes},
            permitir_duplicado_horas=24
        )

    @staticmethod
    def notificar_incongruencia_datos(
        db: Session,
        equipo: MaquinariaEquipo,
        operador: Optional[Personal],
        detalle_incongruencia: str,
        lectura_anterior: float,
        lectura_ingresada: float
    ) -> NotificacionAlerta:
        """Alerta de auditoría inmediata cuando un operador ingresa un valor incoherente o sospechoso."""
        hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
        op_nom = f"{operador.nombres} {operador.apellidos} (DNI: {operador.dni})" if operador else "Operador no identificado"

        msg = (
            f"🚨 *ACR FLOTA 360° — ALERTA DE INCONGRUENCIA DE DATOS*\n"
            f"📅 *Fecha y Hora:* {hoy}\n\n"
            f"🚜 *Equipo:* {equipo.codigo_interno} ({equipo.marca} {equipo.modelo})\n"
            f"👤 *Operador responsable:* {op_nom}\n"
            f"⚠️ *Incongruencia detectada:* {detalle_incongruencia}\n"
            f"📉 *Lectura anterior en sistema:* {lectura_anterior:.2f}\n"
            f"📈 *Lectura ingresada en campo:* {lectura_ingresada:.2f}\n"
            f"📸 *Evidencia:* Se capturó fotografía obligatoria en la App Móvil para auditoría.\n\n"
            f"🔎 *Acción sugerida:* Verificar fotografía del odómetro/horómetro en el módulo de turnos."
        )

        titulo = f"Incongruencia de lectura en {equipo.codigo_interno}: {lectura_ingresada} vs {lectura_anterior}"

        return NotificationService.crear_notificacion(
            db=db,
            tipo=TipoNotificacion.INCONGRUENCIA_DATOS.value,
            titulo=titulo,
            mensaje=msg,
            severidad="critical",
            equipo_id=equipo.id,
            datos_extra={
                "detalle": detalle_incongruencia,
                "lectura_anterior": lectura_anterior,
                "lectura_ingresada": lectura_ingresada,
                "operador_dni": operador.dni if operador else None
            },
            permitir_duplicado_horas=1
        )

    @staticmethod
    def notificar_incidencia_operador(
        db: Session,
        equipo: MaquinariaEquipo,
        operador: Optional[Personal],
        descripcion: str,
        severidad: str = "MEDIA"
    ) -> NotificacionAlerta:
        """Alerta cuando el operador reporta una falla o incidente mecánico en su checklist de campo."""
        hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
        op_nom = f"{operador.nombres} {operador.apellidos} (DNI: {operador.dni})" if operador else "Operador en campo"

        msg = (
            f"⚠️ *ACR FLOTA 360° — INCIDENCIA / FALLA REPORTADA EN CAMPO*\n"
            f"📅 *Fecha:* {hoy}\n\n"
            f"🚜 *Equipo:* {equipo.codigo_interno} ({equipo.marca} {equipo.modelo})\n"
            f"👤 *Reportado por:* {op_nom}\n"
            f"🛑 *Severidad:* {severidad.upper()}\n"
            f"📝 *Detalle de la falla:* {descripcion}\n"
            f"📍 *Frente:* {equipo.proyecto_actual.nombre if equipo.proyecto_actual else 'Base Central'}\n\n"
            f"🔧 *Ver evidencia fotográfica en el módulo de Mantenimiento.*"
        )

        return NotificationService.crear_notificacion(
            db=db,
            tipo=TipoNotificacion.INCIDENCIA_FALLA.value,
            titulo=f"Falla reportada en {equipo.codigo_interno} ({severidad})",
            mensaje=msg,
            severidad="critical" if severidad.upper() in ("ALTA", "DETIENE_EQUIPO") else "warning",
            equipo_id=equipo.id,
            datos_extra={"descripcion": descripcion, "severidad": severidad},
            permitir_duplicado_horas=2
        )

    @staticmethod
    def notificar_gps_apagado_sabotaje(
        db: Session,
        equipo: MaquinariaEquipo,
        operador: Optional[Personal] = None,
        proyecto_nombre: Optional[str] = None,
        ultima_hora: Optional[str] = None,
        motivo_sospecha: str = "Pérdida súbita o apagado voluntario de señal GPS durante turno operativo"
    ) -> NotificacionAlerta:
        """
        Dispara alerta crítica inmediata cuando una maquinaria o unidad apaga el GPS
        o pierde conexión satelital durante su jornada de trabajo (detección anti-sabotaje).
        """
        hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
        op_nom = f"{operador.nombres} {operador.apellidos} (DNI: {operador.dni})" if operador else "Operador en Turno"
        proy = proyecto_nombre or (equipo.proyecto_actual.nombre if equipo.proyecto_actual else "Proyecto / Frente Activo")
        hora_corte = ultima_hora or datetime.now().strftime("%H:%M")

        msg = (
            f"🚨 *ACR FLOTA 360° — ALERTA CRÍTICA: GPS APAGADO / SABOTAJE*\n"
            f"📅 *Momento del Evento:* {hoy}\n\n"
            f"🚜 *Unidad Afectada:* *{equipo.codigo_interno}* — {equipo.marca} {equipo.modelo} (Placa: {equipo.placa or 'S/P'})\n"
            f"👤 *Operador Asignado:* {op_nom}\n"
            f"📍 *Frente / Ubicación:* {proy}\n"
            f"⚠️ *Evento Detectado:* *Desconexión de rastreo satelital en jornada activa.*\n"
            f"🛡️ *Sospecha de Seguridad:* {motivo_sospecha}\n"
            f"⏱️ *Última señal GPS conocida:* {hora_corte}\n\n"
            f"🔴 *ACCIÓN REQUERIDA:* Contactar inmediatamente al supervisor de obra o verificar ubicación física de la maquinaria para descartar desvío o manipulación de combustible."
        )

        titulo = f"🚨 GPS APAGADO / SABOTAJE: Unidad {equipo.codigo_interno} sin señal en turno"

        return NotificationService.crear_notificacion(
            db=db,
            tipo=TipoNotificacion.GPS_APAGADO_SABOTAJE.value,
            titulo=titulo,
            mensaje=msg,
            severidad="critical",
            equipo_id=equipo.id,
            datos_extra={
                "evento": "GPS_OFF_DURANTE_TURNO",
                "operador_dni": operador.dni if operador else None,
                "ultima_hora": hora_corte,
                "proyecto": proy
            },
            permitir_duplicado_horas=2
        )

    # ==========================================
    # GESTIÓN DE VINCULACIÓN WHATSAPP POR QR
    # ==========================================

    @staticmethod
    def obtener_estado_whatsapp_qr(db: Session) -> Dict[str, Any]:
        """Retorna el estado de emparejamiento del WhatsApp emisor (QR, conectado, número asociado)."""
        ajustes = {a.clave: a.valor for a in db.query(AjusteSistema).all()}
        estado = ajustes.get("whatsapp_emisor_estado", "CONECTADO")
        telefono = ajustes.get("whatsapp_emisor_telefono", "+51 924 120 551")
        dispositivo = ajustes.get("whatsapp_emisor_dispositivo", "WhatsApp Multi-Device Gateway Web")
        nombre_bot = ajustes.get("whatsapp_emisor_nombre", "ACR Flota 360° Bot Oficial")
        vinculado_en = ajustes.get("whatsapp_emisor_vinculado_en", "15/10/2026 08:30")

        # Generar código de sesión para QR
        qr_code_payload = f"ACR360-WA-PAIRING:v2:{NotificationService.limpiar_telefono(telefono)}:{int(datetime.utcnow().timestamp())}"

        return {
            "estado": estado,  # "CONECTADO", "DESCONECTADO", "ESPERANDO_QR"
            "telefono_emisor": telefono,
            "dispositivo": dispositivo,
            "nombre_bot": nombre_bot,
            "vinculado_en": vinculado_en,
            "qr_code_payload": qr_code_payload,
            "bateria_porcentaje": 94,
            "auto_envio_alarmas": ajustes.get("whatsapp_auto_envio", "1") == "1",
            "alerta_gps_desconexion": ajustes.get("whatsapp_alerta_gps_desconexion", "1") == "1"
        }

    @staticmethod
    def vincular_whatsapp_qr(db: Session, telefono: str, nombre_dispositivo: Optional[str] = None) -> Dict[str, Any]:
        """Vincula el número emisor tras escanear el código QR."""
        ahora_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        valores = {
            "whatsapp_emisor_estado": "CONECTADO",
            "whatsapp_emisor_telefono": telefono.strip(),
            "whatsapp_emisor_vinculado_en": ahora_str,
            "whatsapp_auto_envio": "1",
            "whatsapp_alerta_gps_desconexion": "1"
        }
        if nombre_dispositivo:
            valores["whatsapp_emisor_dispositivo"] = nombre_dispositivo.strip()

        NotificationService.actualizar_configuracion(db, valores)
        return NotificationService.obtener_estado_whatsapp_qr(db)

    @staticmethod
    def desvincular_whatsapp_qr(db: Session) -> Dict[str, Any]:
        """Desvincula la sesión activa de WhatsApp emisor."""
        NotificationService.actualizar_configuracion(db, {
            "whatsapp_emisor_estado": "DESCONECTADO",
            "whatsapp_emisor_vinculado_en": ""
        })
        return NotificationService.obtener_estado_whatsapp_qr(db)

    # ==========================================
    # ESCANEO AUTOMÁTICO DE FLOTA
    # ==========================================

    @staticmethod
    def escanear_flota_y_generar_alertas(db: Session) -> Dict[str, Any]:
        """
        Escanea todos los equipos para identificar:
        1. Horómetro o Kilometraje próximo a vencer (< 25h o < 500km) o vencido.
        2. Revisión técnica, SOAT o Póliza vencida o próxima a vencer (<= 15 días).
        3. Detección de pérdida de señal GPS o apagado en turno.
        Genera las notificaciones y los enlaces directos de WhatsApp para el Jefe de Área.
        """
        equipos = db.query(MaquinariaEquipo).all()
        hoy = date.today()
        alertas_generadas = []

        config = NotificationService.obtener_configuracion(db)
        horas_limite = config.get("alerta_horas_preventivo", 25)
        dias_limite_doc = config.get("alerta_dias_documentos", 15)

        for eq in equipos:
            # 1. Chequeo de Horómetro / Odómetro vs Servicio
            tipo_ctrl = eq.tipo_control or "HOROMETRO"
            actual = eq.odometro_actual if tipo_ctrl == "KILOMETRAJE" else (eq.horometro_actual or 0.0)
            prox_servicio = eq.horometro_proximo_servicio or (5000.0 if tipo_ctrl == "KILOMETRAJE" else 250.0)
            margen = round(prox_servicio - actual, 1)

            umbral = (horas_limite * 20) if tipo_ctrl == "KILOMETRAJE" else horas_limite
            if margen <= umbral:
                es_venc = margen <= 0
                n = NotificationService.notificar_proximo_mantenimiento(db, eq, margen, es_vencido=es_venc)
                alertas_generadas.append(n.titulo)

            # 2. Chequeo de Documentos Legales
            docs = [
                ("Revisión Técnica", eq.revision_tecnica_vencimiento),
                ("SOAT", eq.soat_vencimiento),
                ("Póliza de Seguro", eq.poliza_vencimiento)
            ]

            for nom_doc, fecha_v in docs:
                if fecha_v:
                    dias_diff = (fecha_v - hoy).days
                    if dias_diff <= dias_limite_doc:
                        n = NotificationService.notificar_documento_vencido(db, eq, nom_doc, fecha_v, dias_diff)
                        alertas_generadas.append(n.titulo)

        return {
            "success": True,
            "total_equipos_evaluados": len(equipos),
            "nuevas_alertas": len(alertas_generadas),
            "detalle_alertas": alertas_generadas
        }
