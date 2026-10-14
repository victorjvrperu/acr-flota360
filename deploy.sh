#!/usr/bin/env bash
# Script de despliegue automático en tu propio servidor Linux
set -e

echo "🚜 [ACR Flota 360°] Iniciando actualización en servidor propio..."

APP_DIR="/var/www/acr-flota360"

if [ ! -d "$APP_DIR" ]; then
    echo "📦 Clonando repositorio desde GitHub..."
    git clone https://github.com/victorjvrperu/acr-flota360.git "$APP_DIR"
fi

cd "$APP_DIR"
echo "🔄 Descargando últimos cambios de GitHub..."
git pull origin main

if [ ! -f ".env" ]; then
    echo "⚙️ Configurando archivo .env para producción..."
    cp .env.example .env
    sed -i 's|APP_ENV=.*|APP_ENV=production|' .env || true
    sed -i 's|DEBUG=.*|DEBUG=False|' .env || true
    sed -i 's|PORT=.*|PORT=8001|' .env || true
    if [ -n "$1" ]; then
        sed -i "s|GEMINI_API_KEY=.*|GEMINI_API_KEY=$1|" .env || true
    fi
fi

if [ ! -d ".venv" ]; then
    echo "🐍 Creando entorno virtual Python (.venv)..."
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Configurar Nginx si está disponible
if [ -d "/etc/nginx/sites-available" ] && [ ! -f "/etc/nginx/sites-available/acr-flota360" ]; then
    echo "🌐 Configurando VirtualHost en Nginx..."
    cp "$APP_DIR/nginx-flota.conf" /etc/nginx/sites-available/acr-flota360
    ln -sf /etc/nginx/sites-available/acr-flota360 /etc/nginx/sites-enabled/
    nginx -t && systemctl reload nginx || echo "⚠️ Revisa la configuración de Nginx"
fi

# Instalar o actualizar servicio Systemd
echo "⚙️ Configurando servicio Systemd 24/7 (puerto 8001)..."
cp "$APP_DIR/acr-flota360.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable acr-flota360

# Reiniciar servicio
systemctl restart acr-flota360
echo "✅ ¡ACR Flota 360° está corriendo con éxito en el puerto 8001!"
systemctl status acr-flota360 --no-pager
