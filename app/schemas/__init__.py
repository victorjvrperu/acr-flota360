from app.schemas.vehiculo import VehiculoBase, VehiculoCreate, VehiculoUpdate, VehiculoResponse
from app.schemas.conductor import ConductorBase, ConductorCreate, ConductorUpdate, ConductorResponse
from app.schemas.mantenimiento import MantenimientoBase, MantenimientoCreate, MantenimientoUpdate, MantenimientoResponse
from app.schemas.combustible import CargaCombustibleBase, CargaCombustibleCreate, CargaCombustibleResponse
from app.schemas.viaje import ViajeBase, ViajeCreate, ViajeUpdate, ViajeResponse
from app.schemas.dashboard import DashboardStats, AlertaItem

__all__ = [
    "VehiculoBase", "VehiculoCreate", "VehiculoUpdate", "VehiculoResponse",
    "ConductorBase", "ConductorCreate", "ConductorUpdate", "ConductorResponse",
    "MantenimientoBase", "MantenimientoCreate", "MantenimientoUpdate", "MantenimientoResponse",
    "CargaCombustibleBase", "CargaCombustibleCreate", "CargaCombustibleResponse",
    "ViajeBase", "ViajeCreate", "ViajeUpdate", "ViajeResponse",
    "DashboardStats", "AlertaItem"
]
