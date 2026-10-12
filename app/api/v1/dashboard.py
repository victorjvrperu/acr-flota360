from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.schemas.dashboard import DashboardStats, AlertaItem
from app.services.flota_service import FlotaService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats", response_model=DashboardStats)
def obtener_metricas_dashboard(db: Session = Depends(get_db)):
    return FlotaService.obtener_estadisticas_dashboard(db)


@router.get("/alertas", response_model=List[AlertaItem])
def obtener_alertas_sistema(db: Session = Depends(get_db)):
    return FlotaService.obtener_alertas_flota(db)
