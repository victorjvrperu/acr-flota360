#!/usr/bin/env python3
"""
Script de sincronización y despliegue automático de ACR Flota 360° al servidor Ubuntu (192.168.1.92).
Despliega en AMBOS directorios:
  - /home/bodylab/maquinaria  -> maquinaria.service (puerto 8000)
  - /var/www/acr-flota360    -> acr-flota360.service (puerto 8001, producción pública)
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
    """Detecta automáticamente si el servidor responde por LAN o por Tailscale."""
    # Verificar LAN rápido (1 segundo)
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

# Ambos servicios y directorios
DEPLOY_TARGETS = [
    {
        "dir": "/home/bodylab/maquinaria",
        "service": "maquinaria.service",
        "port": 8000,
    },
    {
        "dir": "/var/www/acr-flota360",
        "service": "acr-flota360.service",
        "port": 8001,
    },
]


def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"📦 Empaquetando ACR Flota 360° desde: {repo_root}")

    tar_path = "/tmp/acr_flota360_deploy.tar.gz"
    if os.path.exists(tar_path):
        os.remove(tar_path)

    tar_cmd = [
        "tar",
        "--exclude=.git",
        "--exclude=.venv",
        "--exclude=*.db",
        "--exclude=*.db-journal",
        "--exclude=*.db-wal",
        "--exclude=*.db-shm",
        "--exclude=*.sqlite*",
        "--exclude=*.db.backup",
        "--exclude=*.backup",
        "--exclude=*.bak",
        "--exclude=__pycache__",
        "--exclude=app/static/uploads/*",
        "-czf", tar_path,
        "-C", repo_root,
        "."
    ]
    subprocess.run(tar_cmd, check=True)
    print(f"✅ Archivo creado ({os.path.getsize(tar_path) // 1024} KB)")

    server_ip = get_server_ip()
    print(f"🌐 Servidor destino detectado: {server_ip}")

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write(f"#!/bin/sh\necho \"{SUDO_PASS}\"\n")
        askpass_path = f.name
    os.chmod(askpass_path, 0o755)

    env = os.environ.copy()
    env["SSH_ASKPASS"] = askpass_path
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["DISPLAY"] = ":0"
    ssh_opts = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR", "-o", "BatchMode=no"]

    try:
        print(f"🚀 Enviando a {SERVER_USER}@{server_ip}...")
        subprocess.run(
            ["scp", "-O"] + ssh_opts + [tar_path, f"{SERVER_USER}@{server_ip}:/tmp/acr_flota360_deploy.tar.gz"],
            env=env, stdin=subprocess.DEVNULL, check=True
        )

        for target in DEPLOY_TARGETS:
            server_dir = target["dir"]
            service_name = target["service"]
            port = target["port"]
            print(f"🔄 Desplegando en {server_dir} ({service_name} puerto {port})...")

            remote_cmds = f"""
set -e
echo "{SUDO_PASS}" | sudo -S tar -xzf /tmp/acr_flota360_deploy.tar.gz -C {server_dir} --exclude="*.db*" --exclude="*.sqlite*" --no-overwrite-dir 2>/dev/null || true
echo "{SUDO_PASS}" | sudo -S tar -xzf /tmp/acr_flota360_deploy.tar.gz -C {server_dir} --exclude="*.db*" --exclude="*.sqlite*"
echo "{SUDO_PASS}" | sudo -S chown -R bodylab:bodylab {server_dir} 2>/dev/null || true
echo "{SUDO_PASS}" | sudo -S chmod 666 /var/www/acr-flota360/acr_flota360.db 2>/dev/null || true
echo "{SUDO_PASS}" | sudo -S systemctl restart {service_name}
sleep 2
echo "✅ {service_name} reiniciado"
"""
            subprocess.run(
                ["ssh"] + ssh_opts + [f"{SERVER_USER}@{server_ip}", remote_cmds],
                env=env, stdin=subprocess.DEVNULL, check=True
            )
            print(f"   ✅ http://{server_ip}:{port} actualizado")

        print(f"\n🎉 ¡Despliegue exitoso en ambos servicios!")
        print(f"   • Puerto 8000 (maquinaria.service): http://{server_ip}:8000")
        print(f"   • Puerto 8001 (acr-flota360.service / producción): http://{server_ip}:8001")
    finally:
        if os.path.exists(askpass_path):
            os.unlink(askpass_path)
        if os.path.exists(tar_path):
            os.unlink(tar_path)


if __name__ == "__main__":
    main()
