from pydantic import BaseModel
from typing import List, Dict, Any, Optional


class AlertaItem(BaseModel):
    tipo: str  # "soat", "revision_tecnica", "licencia", "mantenimiento"
    nivel: str  # "urgente", "alerta", "informativo"
    titulo: str
    mensaje: str
    dias_restantes: Optional[int] = None
    referencia_id: int
    placa_o_nombre: str


class DashboardStats(BaseModel):
    total_vehiculos: int
    vehiculos_operativos: int
    vehiculos_en_ruta: int
    vehiculos_en_mantenimiento: int
    total_conductores: int
    conductores_activos: int
    mantenimientos_pendientes: int
    viajes_en_curso: int
    gasto_combustible_mes: float
    gasto_mantenimiento_mes: float
    alertas: List[AlertaItem]
