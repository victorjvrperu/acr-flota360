#!/usr/bin/env bash
# Script de despliegue automático en tu propio servidor Linux
set -e

echo "🚜 [ACR Flota 360°] Iniciando actualización en servidor propio..."

APP_DIR="/var/www/acr-flota360"

if [ ! -d "$APP_DIR" ]; then
    echo "📦 Clonando repositorio desde GitHub..."
    git clone https://github.com/victorjvrperu/acr-flota360.git "$APP_DIR"
    cd "$APP_DIR"
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    cd "$APP_DIR"
    echo "🔄 Descargando últimos cambios de GitHub..."
    git pull origin main
    source .venv/bin/activate
    pip install -r requirements.txt
fi

# Instalar servicio Systemd si no existe
if [ ! -f "/etc/systemd/system/acr-flota360.service" ]; then
    echo "⚙️ Configurando servicio Systemd 24/7..."
    cp "$APP_DIR/acr-flota360.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable acr-flota360
fi

# Reiniciar servicio
systemctl restart acr-flota360
echo "✅ ACR Flota 360° está corriendo activamente en el puerto 8001!"
systemctl status acr-flota360 --no-pager
