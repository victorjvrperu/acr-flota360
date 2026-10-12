from fastapi import APIRouter

from app.api.v1.flota_heavy import router as heavy_router
from app.api.v1.vehiculos import router as vehiculos_router
from app.api.v1.conductores import router as conductores_router
from app.api.v1.mantenimientos import router as mantenimientos_router
from app.api.v1.combustible import router as combustible_router
from app.api.v1.viajes import router as viajes_router
from app.api.v1.dashboard import router as dashboard_router

api_router = APIRouter()

# HeavyTrack Operations
api_router.include_router(heavy_router)

# Flota base routers
api_router.include_router(dashboard_router)
api_router.include_router(vehiculos_router)
api_router.include_router(conductores_router)
api_router.include_router(mantenimientos_router)
api_router.include_router(combustible_router)
api_router.include_router(viajes_router)
