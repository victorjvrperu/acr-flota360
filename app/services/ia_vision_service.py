import os
import re
import json
import base64
import logging
from typing import Optional, Dict, Any

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

logger = logging.getLogger(__name__)


class IAVisionService:

    @classmethod
    def analizar_foto_tablero(
        cls,
        foto_base64: str,
        tipo_control: str = "HOROMETRO",
        valor_ingresado: Optional[float] = None,
        valor_anterior: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Analiza la foto del tablero / medidor usando Gemini Vision Multimodal.
        Lee los dígitos del horómetro (h) u odómetro (km), evalúa confianza
        y realiza la comparación contra el valor ingresado por el operador.
        """
        from app.core.config import settings
        api_key = (settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")).strip()
        unidad = "km" if (tipo_control or "").upper() == "KILOMETRAJE" else "h"

        # Limpiar prefijo data:image/...;base64,
        clean_base64 = re.sub(r"^data:image/[a-zA-Z0-9\+\-]+;base64,", "", foto_base64.strip())
        try:
            image_bytes = base64.b64decode(clean_base64)
        except Exception as e:
            return {
                "exito": False,
                "mensaje": f"Error al decodificar la imagen: {str(e)}",
                "lectura_detectada": None,
                "coincide": False,
                "alerta_discrepancia": False
            }

        # Si hay GEMINI_API_KEY y la librería está disponible, invocar Gemini Vision
        if api_key and GENAI_AVAILABLE:
            try:
                client = genai.Client(api_key=api_key)
                part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")

                prompt = f"""
Eres un auditor experto en control de flotas industriales y maquinaria pesada.
Analiza con estricto rigor la imagen adjunta.

REGLAS DE AUDITORÍA:
1. DETERMINACIÓN DE AUTENTICIDAD DEL TABLERO:
   - Determina si la foto muestra efectivamente el tablero de instrumentos, velocímetro, odómetro (cuentakilómetros en km) u horómetro (contador de horas en maquinaria) de un vehículo o máquina física real.
   - Si la foto es de una pantalla de computadora, monitor, celular, una persona, paisaje, teclado, chat, documento o cualquier objeto que NO sea un tablero físico de vehículo/maquinaria:
     Debes responder con:
     "es_tablero_valido": false,
     "es_legible": false,
     "lectura_detectada": null,
     "observacion": "La imagen no corresponde a un tablero o medidor físico de vehículo/maquinaria."

2. LECTURA NUMÉRICA EXACTA:
   - Si SÍ es un tablero o medidor válido ("es_tablero_valido": true):
     * Ubica el display que mide {tipo_control} (odómetro para km en vehículos, horómetro para horas en maquinaria).
     * Lee con total precisión los números mostrados en pantalla.
     * En odómetros mecánicos de rodillos, el último dígito con fondo de color diferente suele ser décimas (0.1).
     * Si los números están borrosos, tapados o ilegibles: coloca "es_legible": false y "lectura_detectada": null.
     * Si son legibles: coloca "es_legible": true y "lectura_detectada": el número float exacto (ejemplo: 57000.0 o 4520.5).

Contexto referencial:
- Tipo de control: {tipo_control} ({unidad})
- Última lectura previa registrada: {valor_anterior if valor_anterior is not None else 'no especificada'} {unidad}
- Valor ingresado manualmente por el operador: {valor_ingresado if valor_ingresado is not None else 'no ingresado aún'} {unidad}

Responde ÚNICAMENTE en formato JSON plano:
{{
  "es_tablero_valido": true o false,
  "es_legible": true o false,
  "lectura_detectada": float o null,
  "unidad": "{unidad}",
  "confianza": float entre 0.0 y 1.0,
  "tipo_pantalla": "digital_lcd" o "analogico_rodillos" o "desconocido",
  "observacion": "descripción concisa de lo observado en la foto",
  "detalles_visuales": "detalles breves de nitidez o iluminación"
}}
"""
                config = types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json"
                )

                response = None
                modelo_usado = None
                # Modelos en orden de preferencia — nombres confirmados por la API de Google
                modelos_candidatos = [
                    "gemini-3.8-flash",       # Principal: más reciente y capaz para visión
                    "gemini-3.5-flash-lite",  # Fallback económico
                    "gemini-3.6-flash",       # Alternativo estable
                ]

                for modelo in modelos_candidatos:
                    try:
                        response = client.models.generate_content(
                            model=modelo,
                            contents=[part, prompt],
                            config=config
                        )
                        if response and response.text:
                            modelo_usado = modelo
                            break
                    except Exception as model_err:
                        logger.warning(f"Intento con modelo {modelo} no exitoso: {model_err}")

                if not response or not response.text:
                    raise RuntimeError("Ningún modelo de Gemini respondió satisfactoriamente")

                texto_resp = response.text.strip()
                data = json.loads(texto_resp)

                es_tablero_valido = bool(data.get("es_tablero_valido", False))
                es_legible = bool(data.get("es_legible", False))
                lectura_detectada = data.get("lectura_detectada")
                if lectura_detectada is not None:
                    try:
                        lectura_detectada = float(lectura_detectada)
                    except (ValueError, TypeError):
                        lectura_detectada = None

                confianza = float(data.get("confianza", 0.90))
                tipo_pantalla = data.get("tipo_pantalla", "digital_lcd")
                observacion = data.get("observacion", "")

                coincide = None
                diferencia = None
                alerta_discrepancia = False

                if not es_tablero_valido:
                    return {
                        "exito": True,
                        "modo": "IA_GEMINI_MULTIMODAL",
                        "motor": modelo_usado or "gemini-3.5-flash",
                        "es_tablero_valido": False,
                        "es_legible": False,
                        "lectura_detectada": None,
                        "unidad": unidad,
                        "confianza": 0.0,
                        "tipo_pantalla": tipo_pantalla,
                        "valor_ingresado": valor_ingresado,
                        "coincide": False,
                        "diferencia": None,
                        "alerta_discrepancia": True,
                        "observacion": observacion or "La foto no muestra un tablero o medidor de vehículo/maquinaria.",
                        "mensaje": "🚫 FOTO RECHAZADA: La IA detectó que la imagen no corresponde a un tablero o velocímetro/odómetro de vehículo."
                    }

                if valor_ingresado is not None and lectura_detectada is not None:
                    diferencia = round(abs(float(valor_ingresado) - float(lectura_detectada)), 2)
                    coincide = diferencia <= 0.05
                    alerta_discrepancia = not coincide

                return {
                    "exito": True,
                    "modo": "IA_GEMINI_MULTIMODAL",
                    "motor": modelo_usado or "gemini-2.5-flash",
                    "es_tablero_valido": True,
                    "es_legible": es_legible,
                    "lectura_detectada": lectura_detectada,
                    "unidad": unidad,
                    "confianza": confianza,
                    "tipo_pantalla": tipo_pantalla,
                    "valor_ingresado": valor_ingresado,
                    "coincide": coincide,
                    "diferencia": diferencia,
                    "alerta_discrepancia": alerta_discrepancia,
                    "observacion": observacion,
                    "mensaje": (
                        f"✅ Lectura verificada en foto ({lectura_detectada} {unidad}): Coincide con lo ingresado."
                        if coincide is True else
                        f"⚠️ Discrepancia detectada: La IA detectó {lectura_detectada} {unidad} en la foto, pero ingresaste {valor_ingresado} {unidad}."
                        if alerta_discrepancia else
                        f"✨ IA detectó {lectura_detectada} {unidad} en el tablero."
                        if lectura_detectada is not None else
                        "📸 La foto no muestra claramente los números del medidor."
                    )
                }

            except Exception as e:
                logger.error(f"Error al invocar Gemini API: {e}")
                return cls._procesar_simulado_o_offline(valor_ingresado, valor_anterior, unidad, error_msg=str(e))

        # Si no hay API key configurada todavía, proveer respuesta de desarrollo / asistente local
        return cls._procesar_simulado_o_offline(valor_ingresado, valor_anterior, unidad, sin_clave=True)

    @classmethod
    def _procesar_simulado_o_offline(
        cls,
        valor_ingresado: Optional[float],
        valor_anterior: Optional[float],
        unidad: str,
        sin_clave: bool = False,
        error_msg: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Modo resiliente offline: nunca inventa coincidencias falsas.
        """
        msg_detalle = (
            "💡 Modo sin conexión: Configure GEMINI_API_KEY en .env para análisis en vivo con Gemini 3.8 Flash."
            if sin_clave else f"⚠️ Servicio de IA en modo sin conexión ({error_msg or 'red no disponible'})."
        )

        return {
            "exito": True,
            "modo": "ASISTIDO_OFFLINE",
            "motor": "vision_asistida",
            "es_tablero_valido": None,
            "es_legible": False,
            "lectura_detectada": None,
            "unidad": unidad,
            "confianza": 0.0,
            "tipo_pantalla": "desconocido",
            "valor_ingresado": valor_ingresado,
            "coincide": None,
            "diferencia": None,
            "alerta_discrepancia": False,
            "observacion": msg_detalle,
            "mensaje": f"📸 Foto sellada y guardada para auditoría manual (modo sin conexión)."
        }
