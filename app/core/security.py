import hmac
import hashlib
import base64
import json
import time
from typing import Optional, Dict, Any

from app.core.config import settings

SECRET_KEY = settings.SECRET_KEY.encode("utf-8")


def hash_password(password: str) -> str:
    """Genera hash SHA256 con salt seguro basado en SECRET_KEY."""
    salt = settings.SECRET_KEY[:16]
    return hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si la contraseña coincide con el hash o claves de inicialización."""
    if not hashed_password:
        return False
    # Si la contraseña en DB es texto plano (por compatibilidad en setup inicial) o hash
    if plain_password == hashed_password:
        return True
    return hash_password(plain_password) == hashed_password


def create_session_token(payload: Dict[str, Any], expires_in_seconds: int = 86400 * 7) -> str:
    """Crea un token firmado HMAC-SHA256 para la sesión de administrador."""
    data = dict(payload)
    data["exp"] = int(time.time()) + expires_in_seconds
    raw_json = json.dumps(data, separators=(",", ":")).encode("utf-8")
    b64_data = base64.urlsafe_b64encode(raw_json).decode("utf-8").rstrip("=")
    
    signature = hmac.new(SECRET_KEY, b64_data.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{b64_data}.{signature}"


def verify_session_token(token: str) -> Optional[Dict[str, Any]]:
    """Valida la firma y expiración del token de sesión."""
    if not token or "." not in token:
        return None
    try:
        b64_data, signature = token.split(".", 1)
        expected_sig = hmac.new(SECRET_KEY, b64_data.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        
        # Padding base64
        padding = 4 - (len(b64_data) % 4)
        if padding != 4:
            b64_data += "=" * padding
            
        raw_json = base64.urlsafe_b64decode(b64_data.encode("utf-8"))
        data = json.loads(raw_json.decode("utf-8"))
        
        if data.get("exp", 0) < int(time.time()):
            return None  # Token expirado
            
        return data
    except Exception:
        return None
