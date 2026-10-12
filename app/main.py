from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
import os

from app.core.config import settings
from app.core.database import engine, Base, SessionLocal
from app.api.v1.api import api_router
from app.services.seed import seed_flota_inicial

# 1. Crear tablas en la base de datos
Base.metadata.create_all(bind=engine)

# 2. Inicializar seeder de datos iniciales
with SessionLocal() as db_session:
    seed_flota_inicial(db_session)

# 3. Crear aplicación FastAPI
app = FastAPI(
    title="ACR Flota 360°",
    description="Sistema Integral de Control de Flotas de Maquinaria Pesada, Vehículos, Proyectos, Combustible, Almacén y Mantenimientos.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 4. Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 5. Montar archivos estáticos y plantillas
base_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(base_dir, "static")
templates_dir = os.path.join(base_dir, "templates")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates = Jinja2Templates(directory=templates_dir)

from app.api.v1.sync import router as sync_router

# 6. Incluir API Routers
app.include_router(sync_router)
app.include_router(api_router, prefix="/api/v1")


# 7. Rutas Web Frontend (PC y Móvil PWA)
@app.get("/", response_class=HTMLResponse, tags=["Frontend PC"])
@app.get("/pc", response_class=HTMLResponse, tags=["Frontend PC"])
def vista_escritorio(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard_pc.html", context={"app_name": "ACR Flota 360°"})


@app.get("/mobile", response_class=HTMLResponse, tags=["Frontend Móvil PWA"])
@app.get("/app/operador", response_class=HTMLResponse, tags=["Frontend Móvil PWA"])
@app.get("/operador", response_class=HTMLResponse, tags=["Frontend Móvil PWA"])
def vista_movil(request: Request):
    return templates.TemplateResponse(request=request, name="operador_mobile.html", context={"app_name": "ACR Flota 360° Móvil"})


@app.get("/sw.js", tags=["PWA Service Worker"])
def serve_service_worker():
    sw_path = os.path.join(static_dir, "sw.js")
    return FileResponse(sw_path, media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})


@app.get("/manifest.json", tags=["PWA Manifest"])
def serve_manifest():
    manifest_path = os.path.join(static_dir, "manifest.json")
    return FileResponse(manifest_path, media_type="application/json")


@app.get("/health", tags=["Salud"])
def health_check():
    return {"status": "ok", "app": "ACR Flota 360°", "version": "2.0.0", "env": settings.APP_ENV}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
