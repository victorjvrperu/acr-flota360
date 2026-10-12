# ACR Flota360 - Sistema de Gestión Integral de Flotas

Aplicación backend y plataforma web construida en **Python** con **FastAPI**, **SQLAlchemy** y **Pydantic**.

## Estructura del Proyecto

```text
acr-flota360/
├── app/
│   ├── api/             # Endpoints y routers de la API (v1)
│   ├── core/            # Configuración, base de datos y utilidades base
│   ├── models/          # Modelos de base de datos SQLAlchemy
│   ├── schemas/         # Esquemas de validación Pydantic
│   ├── services/        # Lógica de negocio y servicios
│   ├── static/          # Archivos estáticos (CSS, JS, imágenes)
│   ├── templates/       # Vistas HTML / Dashboard con Jinja2
│   └── main.py          # Punto de entrada de la aplicación FastAPI
├── .env                 # Variables de entorno
├── requirements.txt     # Dependencias de Python
└── README.md
```

## Entorno de Desarrollo

Para ejecutar el servidor de desarrollo:

```bash
# Activar entorno virtual
source .venv/bin/activate

# Ejecutar el servidor con recarga en vivo
uvicorn app.main:app --reload --port 8000
```

Documentación interactiva disponible en:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
