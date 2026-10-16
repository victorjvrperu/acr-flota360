from fastapi import FastAPI, Request, Form, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional
import os

from app.core.config import settings
from app.core.database import engine, Base, SessionLocal, get_db
from app.core.security import verify_password, hash_password, create_session_token, verify_session_token
from app.models.heavytrack import Personal, RolPersonal
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


# Helper de sesión administrativa
def obtener_admin_sesion(request: Request, db: Session) -> Optional[Personal]:
    token = request.cookies.get("acr_admin_session")
    if not token:
        return None
    data = verify_session_token(token)
    if not data or not data.get("user_id"):
        return None
    user = db.query(Personal).filter(Personal.id == data["user_id"]).first()
    if not user or user.estado != "activo":
        return None
    # Los operadores tienen restringido el panel administrativo
    if user.rol == RolPersonal.OPERADOR.value:
        return None
    return user


# 7. Autenticación Administrativa
@app.get("/login", response_class=HTMLResponse, tags=["Autenticación Administrativa"])
def login_page(request: Request, error: Optional[str] = None, db: Session = Depends(get_db)):
    admin = obtener_admin_sesion(request, db)
    if admin:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="login_admin.html",
        context={"error": error, "usuario": ""}
    )


@app.post("/login", response_class=HTMLResponse, tags=["Autenticación Administrativa"])
def login_post(
    request: Request,
    usuario: str = Form(...),
    contrasena: str = Form(...),
    db: Session = Depends(get_db)
):
    usuario_clean = (usuario or "").strip()
    clave_clean = (contrasena or "").strip()

    # Acceso administrativo directo garantizado para "admin"
    if usuario_clean.lower() == "admin" and clave_clean in ["admin360", "1234"]:
        admin_user = db.query(Personal).filter(Personal.dni.ilike("admin")).first()
        if not admin_user:
            admin_user = Personal(
                dni="admin",
                nombres="Administrador",
                apellidos="ACR Flota 360",
                telefono="+51 900 000 000",
                rol=RolPersonal.SISTEMAS_ADMIN.value,
                contrasena_hash=hash_password("admin360"),
                pin_acceso="1234",
                estado="activo"
            )
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)
        user = admin_user
    else:
        # Buscar usuario por DNI o código
        user = db.query(Personal).filter(
            (Personal.dni == usuario_clean) | (Personal.dni.ilike(usuario_clean))
        ).first()

        if not user or user.estado != "activo":
            return templates.TemplateResponse(
                request=request,
                name="login_admin.html",
                context={"error": "credenciales_invalidas", "usuario": usuario_clean},
                status_code=status.HTTP_401_UNAUTHORIZED
            )

        # Validar contraseña por hash, texto plano o PIN
        clave_valida = (
            verify_password(clave_clean, user.contrasena_hash or "")
            or (user.pin_acceso and clave_clean == user.pin_acceso)
            or (user.contrasena_hash and clave_clean == user.contrasena_hash)
            or (user.dni.lower() == "admin" and clave_clean in ["admin360", "1234"])
        )
        if not clave_valida:
            return templates.TemplateResponse(
                request=request,
                name="login_admin.html",
                context={"error": "credenciales_invalidas", "usuario": usuario_clean},
                status_code=status.HTTP_401_UNAUTHORIZED
            )

    # RESTRICCIÓN: Operadores NO pueden ingresar al Dashboard
    if user.rol == RolPersonal.OPERADOR.value:
        return templates.TemplateResponse(
            request=request,
            name="login_admin.html",
            context={"error": "operador_restringido", "usuario": usuario_clean},
            status_code=status.HTTP_403_FORBIDDEN
        )

    # Crear token firmado y setear cookie segura
    token = create_session_token({
        "user_id": user.id,
        "dni": user.dni,
        "rol": user.rol,
        "nombre": f"{user.nombres} {user.apellidos}"
    })

    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="acr_admin_session",
        value=token,
        max_age=86400 * 7,  # 7 días de duración
        httponly=True,
        samesite="lax",
        secure=False
    )
    return response


@app.get("/logout", tags=["Autenticación Administrativa"])
def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="acr_admin_session")
    return response


# 8. Rutas Web Frontend (PC Escritorio Protegido)
@app.get("/", response_class=HTMLResponse, tags=["Frontend PC"])
@app.get("/pc", response_class=HTMLResponse, tags=["Frontend PC"])
@app.get("/dashboard-pc", response_class=HTMLResponse, tags=["Frontend PC"])
@app.get("/horometros", response_class=HTMLResponse, tags=["Frontend PC"])
def vista_escritorio(request: Request, db: Session = Depends(get_db)):
    admin = obtener_admin_sesion(request, db)
    if not admin:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request=request,
        name="dashboard_pc.html",
        context={"app_name": "ACR Flota 360°", "admin_user": admin}
    )


@app.get("/mobile", response_class=HTMLResponse, tags=["Frontend Móvil PWA"])
@app.get("/app/operador", response_class=HTMLResponse, tags=["Frontend Móvil PWA"])
@app.get("/operador", response_class=HTMLResponse, tags=["Frontend Móvil PWA"])
def vista_movil(request: Request):
    return templates.TemplateResponse(request=request, name="operador_mobile.html", context={"app_name": "ACR Flota 360° Móvil"})


@app.get("/sw.js", tags=["PWA Service Worker"])
def serve_service_worker():
    sw_path = os.path.join(static_dir, "sw.js")
    return FileResponse(sw_path, media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})


@app.get("/descargar-apk", tags=["Descargas"])
@app.get("/apk", tags=["Descargas"])
def descargar_apk():
    apk_path = os.path.join(static_dir, "downloads", "acr-operadores-v2.apk")
    if not os.path.exists(apk_path):
        apk_path = os.path.join(static_dir, "downloads", "acr-operadores.apk")
    return FileResponse(
        apk_path,
        media_type="application/vnd.android.package-archive",
        filename="acr-operadores-v2.apk",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


@app.get("/manifest.json", tags=["PWA Manifest"])
def serve_manifest():
    manifest_path = os.path.join(static_dir, "manifest.json")
    return FileResponse(manifest_path, media_type="application/json")


@app.get("/health", tags=["Salud"])
def health_check():
    return {"status": "ok", "app": "ACR Flota 360°", "version": "2.0.0", "env": settings.APP_ENV}


@app.api_route("/pub/chat", methods=["GET", "POST", "OPTIONS"], include_in_schema=False)
async def siskote_fallback():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
