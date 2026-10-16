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

        remote_sh_local = os.path.join(repo_root, "scripts", "remote_build.sh")
        print("🚀 Transfiriendo script de compilación y proyecto al servidor...")
        subprocess.run(
            ["scp", "-O"] + ssh_opts + [remote_sh_local, f"{SERVER_USER}@{server_ip}:/tmp/remote_build.sh"],
            env=env, stdin=subprocess.DEVNULL, check=True
        )

        print("🔨 Ejecutando compilación nativa en el servidor (esto toma ~2 minutos)...")
        subprocess.run(
            ["ssh"] + ssh_opts + [f"{SERVER_USER}@{server_ip}", f"chmod +x /tmp/remote_build.sh && /tmp/remote_build.sh '{SUDO_PASS}'"],
            env=env, stdin=subprocess.DEVNULL, check=True
        )

        local_apk = os.path.join(repo_root, "app", "static", "downloads", "acr-operadores.apk")
        local_apk_v2 = os.path.join(repo_root, "app", "static", "downloads", "acr-operadores-v2.apk")
        os.makedirs(os.path.dirname(local_apk), exist_ok=True)

        print("⬇️ Descargando APK generado a tu equipo local...")
        subprocess.run(
            ["scp", "-O"] + ssh_opts + [f"{SERVER_USER}@{server_ip}:/tmp/acr-operadores-v2.apk", local_apk_v2],
            env=env, stdin=subprocess.DEVNULL, check=True
        )
        import shutil
        shutil.copyfile(local_apk_v2, local_apk)

        size_mb = os.path.getsize(local_apk_v2) / (1024 * 1024)
        print("\n🎉 ¡COMPILACIÓN EXITOSA!")
        print(f"📦 Archivo local: {local_apk_v2} ({size_mb:.2f} MB)")
        print(f"🌐 Enlace oficial: https://flota.bodylab.net.pe/descargar-apk")
        print(f"🌐 Enlace directo v2: https://flota.bodylab.net.pe/static/downloads/acr-operadores-v2.apk")

    finally:
        if os.path.exists(askpass_path):
            os.unlink(askpass_path)
        if os.path.exists(tar_path):
            os.unlink(tar_path)


if __name__ == "__main__":
    main()
