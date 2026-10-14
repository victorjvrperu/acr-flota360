from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel

from app.core.database import get_db
from app.models.heavytrack import NotificacionAlerta
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones y Alertas WhatsApp"])


class ConfigNotificacionesRequest(BaseModel):
    whatsapp_jefe_telefono: Optional[str] = None
    whatsapp_api_url: Optional[str] = None
    whatsapp_api_token: Optional[str] = None
    whatsapp_auto_envio: Optional[bool] = None
    alerta_horas_preventivo: Optional[int] = None
    alerta_dias_documentos: Optional[int] = None


@router.get("")
def listar_notificaciones(
    solo_no_leidas: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Retorna el listado de alertas y notificaciones del sistema con conteo de no leídas
    y enlaces directos de WhatsApp para el Jefe de Área.
    """
    # Ejecutar escaneo automático previo si es necesario
    query = db.query(NotificacionAlerta)
    if solo_no_leidas:
        query = query.filter(NotificacionAlerta.leido == False)

    total_no_leidas = db.query(NotificacionAlerta).filter(NotificacionAlerta.leido == False).count()
    items = query.order_by(NotificacionAlerta.creado_en.desc()).limit(limit).all()

    config = NotificationService.obtener_configuracion(db)

    resultado = []
    for n in items:
        resultado.append({
            "id": n.id,
            "tipo": n.tipo,
            "titulo": n.titulo,
            "mensaje": n.mensaje,
            "severidad": n.severidad,
            "equipo_id": n.equipo_id,
            "equipo_codigo": n.equipo.codigo_interno if n.equipo else None,
            "leido": n.leido,
            "canal_whatsapp_enviado": n.canal_whatsapp_enviado,
            "whatsapp_link": n.whatsapp_link,
            "datos_extra": n.datos_extra,
            "fecha": n.creado_en.strftime("%d/%m/%Y %H:%M") if n.creado_en else "-",
            "hace_minutos": int((datetime.utcnow() - n.creado_en).total_seconds() / 60) if n.creado_en else 0
        })

    return {
        "success": True,
        "total_no_leidas": total_no_leidas,
        "notificaciones": resultado,
        "config": config
    }


@router.put("/{notificacion_id}/leida")
def marcar_notificacion_leida(notificacion_id: int, db: Session = Depends(get_db)):
    """Marca una notificación específica como leída."""
    n = db.query(NotificacionAlerta).filter(NotificacionAlerta.id == notificacion_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    n.leido = True
    db.commit()
    return {"success": True, "id": notificacion_id, "leido": True}


@router.put("/marcar-todas")
def marcar_todas_como_leidas(db: Session = Depends(get_db)):
    """Marca todas las notificaciones pendientes como leídas."""
    db.query(NotificacionAlerta).filter(NotificacionAlerta.leido == False).update({"leido": True})
    db.commit()
    return {"success": True, "mensaje": "Todas las notificaciones han sido marcadas como leídas"}


@router.post("/escanear")
def escanear_alertas_sistema(db: Session = Depends(get_db)):
    """
    Ejecuta el barrido preventivo de flota:
    - Próximos mantenimientos preventivos y vencidos.
    - Revisión técnica, SOAT y póliza por vencer o vencidos.
    """
    return NotificationService.escanear_flota_y_generar_alertas(db)


@router.get("/config")
def obtener_configuracion_notificaciones(db: Session = Depends(get_db)):
    """Retorna los datos del teléfono del Jefe de Área y estado del Gateway WhatsApp."""
    return NotificationService.obtener_configuracion(db)


@router.post("/config")
def guardar_configuracion_notificaciones(
    req: ConfigNotificacionesRequest,
    db: Session = Depends(get_db)
):
    """Actualiza el teléfono del Jefe de Área o parámetros del API Gateway WhatsApp."""
    datos = req.model_dump(exclude_unset=True)
    return NotificationService.actualizar_configuracion(db, datos)


@router.post("/test-whatsapp")
def enviar_whatsapp_prueba(db: Session = Depends(get_db)):
    """Envía un mensaje de prueba al celular del Jefe de Área."""
    config = NotificationService.obtener_configuracion(db)
    tel_jefe = config["whatsapp_jefe_telefono"]
    hoy = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    mensaje = (
        f"✅ *ACR FLOTA 360° — MENSAJE DE PRUEBA EXITOSO*\n"
        f"📅 *Fecha:* {hoy}\n\n"
        f"El canal de alertas automáticas para el *Jefe de Área / Mantenimiento* se encuentra activo.\n"
        f"Recibirá avisos inmediatos ante:\n"
        f"• Ingreso de equipos a taller\n"
        f"• Vencimiento de mantenimientos (< 25h)\n"
        f"• Revisiones técnicas y SOAT por vencer\n"
        f"• Incongruencias o fallas reportadas en campo\n\n"
        f"🚜 *ACR Flota 360° Enterprise*"
    )

    enviado_api = False
    if config["whatsapp_api_url"]:
        enviado_api = NotificationService.enviar_whatsapp_directo_api(tel_jefe, mensaje, db)

    link = NotificationService.generar_link_whatsapp(tel_jefe, mensaje)

    return {
        "success": True,
        "telefono": tel_jefe,
        "enviado_por_api": enviado_api,
        "whatsapp_link": link,
        "mensaje": "Mensaje de prueba generado correctamente."
    }
