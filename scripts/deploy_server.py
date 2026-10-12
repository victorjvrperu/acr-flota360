#!/usr/bin/env python3
"""
Script de sincronización y despliegue automático de ACR Flota 360° al servidor Ubuntu (192.168.1.92).
"""
import os
import subprocess
import tempfile
import sys

SERVER_USER = "bodylab"
SERVER_IP = "192.168.1.92"
SERVER_DIR = "/home/bodylab/maquinaria"
SERVICE_NAME = "maquinaria.service"
SUDO_PASS = "Kamita12"

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

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write(f"#!/bin/sh\necho \"{SUDO_PASS}\"\n")
        askpass_path = f.name
    os.chmod(askpass_path, 0o755)

    env = os.environ.copy()
    env["SSH_ASKPASS"] = askpass_path
    env["SSH_ASKPASS_REQUIRE"] = "force"
    ssh_opts = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]

    try:
        print(f"🚀 Enviando a {SERVER_USER}@{SERVER_IP}...")
        subprocess.run(["scp"] + ssh_opts + [tar_path, f"{SERVER_USER}@{SERVER_IP}:/tmp/acr_flota360_deploy.tar.gz"], env=env, check=True)

        remote_cmds = f"""
set -e
cd {SERVER_DIR}
tar -xzf /tmp/acr_flota360_deploy.tar.gz -C {SERVER_DIR}
cat << 'EOF' > {SERVER_DIR}/main.py
from app.main import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
EOF
echo "{SUDO_PASS}" | sudo -S systemctl restart {SERVICE_NAME}
sleep 1
"""
        print("🔄 Aplicando cambios y reiniciando servicio systemd...")
        subprocess.run(["ssh"] + ssh_opts + [f"{SERVER_USER}@{SERVER_IP}", remote_cmds], env=env, check=True)
        print("🎉 ¡Despliegue exitoso en http://192.168.1.92:8000!")
    finally:
        if os.path.exists(askpass_path):
            os.unlink(askpass_path)
        if os.path.exists(tar_path):
            os.unlink(tar_path)

if __name__ == "__main__":
    main()
