# 🚛 ACR Flota360

Sistema integral para el control y administración de flota vehicular desarrollado en **Python (FastAPI)**.

## 🚀 Características Principales

- **Gestión de Vehículos**: Control de unidades, odómetro, VIN, placas, tipo de vehículo y estados (operativo, mantenimiento, fuera de servicio).
- **Gestión de Conductores**: Ficha del conductor, categoría y vigencia de licencias de conducir, asignación de unidades.
- **Mantenimientos Preventivos y Correctivos**: Programación de servicios por kilometraje o fecha, registro de talleres, repuestos y costos.
- **Control de Combustible**: Registro de cargas, costos, estaciones de servicio y cálculo de rendimiento (km/galón o km/litro).
- **Viajes y Rutas**: Asignación de viajes, odómetro de salida/llegada, control de kilometraje recorrido y bitácora de novedades.
- **Alertas 360**: Detección automática de SOAT por vencer, revisiones técnicas y alertas de kilometraje para mantenimiento.
- **Dashboard & API REST**: Métricas clave en tiempo real y documentación interactiva con OpenAPI / Swagger.

---

## 🛠️ Requisitos Previos

- Python 3.10+ (probado con Python 3.14)
- Pip

---

## 💻 Instalación y Puesta en Marcha

1. **Crear y activar el entorno virtual:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configurar variables de entorno:**
   ```bash
   cp .env.example .env
   ```

4. **Iniciar la aplicación:**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

5. **Acceder al sistema:**
   - **Dashboard Web**: [http://localhost:8000](http://localhost:8000)
   - **Documentación Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Documentación ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 📄 Licencia

Este proyecto está bajo la Licencia de Código Abierto **MIT**. Consulta el archivo [LICENSE](LICENSE) para más detalles.
