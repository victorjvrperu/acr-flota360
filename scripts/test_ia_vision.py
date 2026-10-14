#!/usr/bin/env python3
"""
Script de diagnóstico para probar IAVisionService.
Uso: python3 scripts/test_ia_vision.py [ruta_imagen] [HOROMETRO|KILOMETRAJE]
"""
import sys, os, base64, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

def test_con_imagen(ruta_imagen=None, tipo="HOROMETRO"):
    from app.services.ia_vision_service import IAVisionService

    if ruta_imagen and os.path.exists(ruta_imagen):
        print(f"📷 Usando imagen: {ruta_imagen}")
        with open(ruta_imagen, "rb") as f:
            img_bytes = f.read()
        ext = ruta_imagen.split(".")[-1].lower()
        mime = "image/jpeg" if ext in ("jpg","jpeg") else f"image/{ext}"
        foto_b64 = f"data:{mime};base64," + base64.b64encode(img_bytes).decode()
    else:
        print("⚠️  Sin imagen. Usando imagen de prueba mínima (esperar modo OFFLINE si API key inválida).")
        FAKE = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAARCAABAAEDASIAAhEBAxEB/8QAFgABAQEAAAAAAAAAAAAAAAAABgUE/8QAFhABAQEAAAAAAAAAAAAAAAAAABEB/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AKtpuqW+4SpVoaQ6hBKW1rSSFd9jv9qUp//Z"
        foto_b64 = "data:image/jpeg;base64," + FAKE

    print(f"\n🔍 Analizando (tipo={tipo})...\n")
    r = IAVisionService.analizar_foto_tablero(
        foto_base64=foto_b64, tipo_control=tipo,
        valor_ingresado=4500.0, valor_anterior=4200.0
    )
    print("=" * 60)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print("=" * 60)
    print(f"\n✅ Modo:    {r.get('modo')}")
    print(f"🤖 Motor:  {r.get('motor')}")
    print(f"📊 Lectura: {r.get('lectura_detectada')} {r.get('unidad','')}")
    print(f"🎯 Confianza: {r.get('confianza', 0)*100:.0f}%")
    print(f"💬 {r.get('mensaje')}")

if __name__ == "__main__":
    test_con_imagen(
        sys.argv[1] if len(sys.argv) > 1 else None,
        sys.argv[2] if len(sys.argv) > 2 else "HOROMETRO"
    )
