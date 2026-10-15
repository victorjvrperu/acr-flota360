#!/usr/bin/env python3
"""
Script de compilación automática del APK Android para ACR Flota 360° Operadores.
Empaqueta la aplicación con Capacitor, compila con Gradle en el servidor y genera el APK.
"""
import os
import subprocess
import tempfile
import sys

SERVER_USER = "bodylab"
LAN_IP = "192.168.1.92"
TAILSCALE_IP = "100.84.247.4"
SUDO_PASS = "Kamita12"


def get_server_ip() -> str:
    try:
        ret = subprocess.run(
            ["ping", "-c", "1", "-W", "1000", LAN_IP],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if ret.returncode == 0:
            return LAN_IP
    except Exception:
        pass
    return TAILSCALE_IP


def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mobile_dir = os.path.join(repo_root, "mobile-app")
    server_ip = get_server_ip()

    print("📱 Iniciando compilación de APK Android (ACR Operadores)...")
    print(f"🌐 Servidor destino: {server_ip}")

    tar_path = "/tmp/acr_mobile_build.tar.gz"
    if os.path.exists(tar_path):
        os.remove(tar_path)

    print("📦 Empaquetando configuración de Capacitor y assets web...")
    subprocess.run([
        "tar",
        "--exclude=node_modules",
        "--exclude=android/app/build",
        "--exclude=android/.gradle",
        "-czf", tar_path,
        "-C", mobile_dir,
        "."
    ], check=True)

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write(f'#!/bin/sh\necho "{SUDO_PASS}"\n')
        askpass_path = f.name
    os.chmod(askpass_path, 0o755)

    env = os.environ.copy()
    env["SSH_ASKPASS"] = askpass_path
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["DISPLAY"] = ":0"
    ssh_opts = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR", "-o", "BatchMode=no"]

    try:
        print("🚀 Transfiriendo proyecto móvil al servidor...")
        subprocess.run(
            ["scp", "-O"] + ssh_opts + [tar_path, f"{SERVER_USER}@{server_ip}:/tmp/acr_mobile_build.tar.gz"],
            env=env, stdin=subprocess.DEVNULL, check=True
        )

        build_script = f"""
set -e
echo "🔧 Extrayendo proyecto móvil en servidor..."
mkdir -p /home/bodylab/acr-mobile-build
tar -xzf /tmp/acr_mobile_build.tar.gz -C /home/bodylab/acr-mobile-build

cd /home/bodylab/acr-mobile-build

export ANDROID_HOME=/home/bodylab/android-sdk
export PATH=$ANDROID_HOME/cmdline-tools/latest/bin:$PATH

echo "📦 Instalando dependencias de Capacitor..."
if [ ! -d "node_modules" ]; then
    npm install --silent
fi

echo "🤖 Agregando o sincronizando plataforma Android..."
if [ ! -d "android" ]; then
    npx cap add android
fi
npx cap sync android

echo "🎨 Copiando iconos oficiales con logo ACR 360 en todos los tamaños (mdpi, hdpi, xhdpi, xxhdpi, xxxhdpi)..."
cp -rf res/mipmap-* android/app/src/main/res/ 2>/dev/null || true

echo "🛡️ Configurando permisos de Cámara, GPS y Red en AndroidManifest.xml..."
MANIFEST="android/app/src/main/AndroidManifest.xml"
if [ -f "$MANIFEST" ]; then
    # Inyectar usesCleartextTraffic si no está
    if ! grep -q 'android:usesCleartextTraffic="true"' "$MANIFEST"; then
        sed -i 's/<application/<application android:usesCleartextTraffic="true"/g' "$MANIFEST"
    fi
    # Inyectar permisos esenciales
    for perm in "android.permission.INTERNET" "android.permission.ACCESS_NETWORK_STATE" "android.permission.CAMERA" "android.permission.ACCESS_FINE_LOCATION" "android.permission.ACCESS_COARSE_LOCATION"; do
        if ! grep -q "$perm" "$MANIFEST"; then
            sed -i "/<manifest/a \    <uses-permission android:name=\\"$perm\\" />" "$MANIFEST"
        fi
    done
fi

echo "⚙️ Compilando APK con Gradle (Debug Release)..."
cd android
chmod +x gradlew
./gradlew assembleDebug --no-daemon

APK_OUT="app/build/outputs/apk/debug/app-debug.apk"
if [ ! -f "$APK_OUT" ]; then
    echo "❌ Error: No se generó el archivo APK"
    exit 1
fi

echo "📥 Publicando APK en servidor web..."
echo "{SUDO_PASS}" | sudo -S mkdir -p /var/www/acr-flota360/app/static/downloads
echo "{SUDO_PASS}" | sudo -S cp -f "$APK_OUT" /var/www/acr-flota360/app/static/downloads/acr-operadores.apk
echo "{SUDO_PASS}" | sudo -S chmod 644 /var/www/acr-flota360/app/static/downloads/acr-operadores.apk

mkdir -p /home/bodylab/maquinaria/app/static/downloads 2>/dev/null || true
cp -f "$APK_OUT" /home/bodylab/maquinaria/app/static/downloads/acr-operadores.apk 2>/dev/null || true

cp "$APK_OUT" /tmp/acr-operadores.apk
echo "✅ APK Compilado y listo en /tmp/acr-operadores.apk"
"""
        print("🔨 Ejecutando compilación nativa en el servidor (esto toma ~2 minutos)...")
        subprocess.run(
            ["ssh"] + ssh_opts + [f"{SERVER_USER}@{server_ip}", build_script],
            env=env, stdin=subprocess.DEVNULL, check=True
        )

        local_apk = os.path.join(repo_root, "app", "static", "downloads", "acr-operadores.apk")
        os.makedirs(os.path.dirname(local_apk), exist_ok=True)

        print("⬇️ Descargando APK generado a tu equipo local...")
        subprocess.run(
            ["scp", "-O"] + ssh_opts + [f"{SERVER_USER}@{server_ip}:/tmp/acr-operadores.apk", local_apk],
            env=env, stdin=subprocess.DEVNULL, check=True
        )

        size_mb = os.path.getsize(local_apk) / (1024 * 1024)
        print("\n🎉 ¡COMPILACIÓN EXITOSA!")
        print(f"📦 Archivo local: {local_apk} ({size_mb:.2f} MB)")
        print(f"🌐 Enlace de descarga directa: http://{server_ip}:8001/static/downloads/acr-operadores.apk")

    finally:
        if os.path.exists(askpass_path):
            os.unlink(askpass_path)
        if os.path.exists(tar_path):
            os.unlink(tar_path)


if __name__ == "__main__":
    main()
