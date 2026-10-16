#!/bin/bash
set -e

SUDO_PASS="$1"

echo "🔧 Extrayendo proyecto móvil en servidor..."
mkdir -p /home/bodylab/acr-mobile-build
tar -xzf /tmp/acr_mobile_build.tar.gz -C /home/bodylab/acr-mobile-build

cd /home/bodylab/acr-mobile-build

export ANDROID_HOME=/home/bodylab/android-sdk
export PATH=$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH

echo "📦 Instalando dependencias de Capacitor..."
if [ ! -d "node_modules" ]; then
    npm install --silent
fi

echo "🤖 Agregando o sincronizando plataforma Android..."
if [ ! -d "android" ]; then
    npx cap add android
fi
npx cap sync android

echo "🎨 Copiando recursos oficiales con logo ACR 360 (adaptive icons, drawable, values, mipmaps)..."
cp -rf res/* android/app/src/main/res/ 2>/dev/null || true

echo "🛡️ Configurando permisos de Cámara, GPS y Red en AndroidManifest.xml..."
MANIFEST="android/app/src/main/AndroidManifest.xml"
if [ -f "$MANIFEST" ]; then
    if ! grep -q 'android:usesCleartextTraffic="true"' "$MANIFEST"; then
        sed -i 's/<application/<application android:usesCleartextTraffic="true"/g' "$MANIFEST"
    fi
    for perm in "android.permission.INTERNET" "android.permission.ACCESS_NETWORK_STATE" "android.permission.CAMERA" "android.permission.ACCESS_FINE_LOCATION" "android.permission.ACCESS_COARSE_LOCATION"; do
        if ! grep -q "$perm" "$MANIFEST"; then
            sed -i "/<manifest/a \\    <uses-permission android:name=\"$perm\" />" "$MANIFEST"
        fi
    done
fi

echo "🔐 Preparando certificado y clave de firma ACR Flota 360..."
KEYSTORE="/home/bodylab/acr-mobile-build/acr-release.keystore"
if [ ! -f "$KEYSTORE" ]; then
    keytool -genkeypair -v -keystore "$KEYSTORE" -alias acrkey -keyalg RSA -keysize 2048 -validity 10000 -storepass acrflota360 -keypass acrflota360 -dname "CN=ACR Operadores, OU=Operaciones, O=ACR Flota 360, L=Lima, ST=Lima, C=PE"
fi

GRADLE_APP="android/app/build.gradle"
echo "⚙️ Configurando firma corporativa ACR Flota 360 en build.gradle..."
python3 - << 'EOF'
import re

with open("android/app/build.gradle", "r") as f:
    text = f.read()

# Limpiar cualquier bloque previo de signingConfigs si existiese
text = re.sub(r'signingConfigs\s*\{[\s\S]*?\}\s*\}\s*', '', text)
text = text.replace("signingConfig signingConfigs.release", "")
text = text.replace("signingConfig signingConfigs.acrRelease", "")
text = re.sub(r'versionCode\s+\d+', 'versionCode 2', text)
text = re.sub(r'versionName\s+"[^"]+"', 'versionName "1.1"', text)

signing = """
    signingConfigs {
        acrRelease {
            storeFile file("/home/bodylab/acr-mobile-build/acr-release.keystore")
            storePassword "acrflota360"
            keyAlias "acrkey"
            keyPassword "acrflota360"
            v1SigningEnabled true
            v2SigningEnabled true
        }
    }
"""
text = text.replace("buildTypes {", signing + "\n    buildTypes {")
text = text.replace("release {", "release {\n            signingConfig signingConfigs.acrRelease")

with open("android/app/build.gradle", "w") as f:
    f.write(text)
EOF

echo "⚙️ Compilando APK Release firmado nativamente con Gradle..."
cd android
chmod +x gradlew
./gradlew clean assembleRelease --no-daemon

APK_OUT="app/build/outputs/apk/release/app-release.apk"
if [ ! -f "$APK_OUT" ]; then
    echo "⚠️ Probando con assembleDebug..."
    ./gradlew assembleDebug --no-daemon
    APK_OUT="app/build/outputs/apk/debug/app-debug.apk"
fi

if [ ! -f "$APK_OUT" ]; then
    echo "❌ Error: No se generó el archivo APK"
    exit 1
fi

APKSIGNER=$(find $ANDROID_HOME/build-tools -name apksigner 2>/dev/null | head -n 1)
if [ -n "$APKSIGNER" ]; then
    echo "🔍 Verificando integridad del APK con apksigner:"
    $APKSIGNER verify --verbose "$APK_OUT" || true
fi

echo "📥 Publicando APK en servidor web..."
echo "$SUDO_PASS" | sudo -S mkdir -p /var/www/acr-flota360/app/static/downloads
echo "$SUDO_PASS" | sudo -S cp -f "$APK_OUT" /var/www/acr-flota360/app/static/downloads/acr-operadores.apk
echo "$SUDO_PASS" | sudo -S cp -f "$APK_OUT" /var/www/acr-flota360/app/static/downloads/acr-operadores-v2.apk
echo "$SUDO_PASS" | sudo -S chmod 644 /var/www/acr-flota360/app/static/downloads/*.apk

mkdir -p /home/bodylab/maquinaria/app/static/downloads 2>/dev/null || true
cp -f "$APK_OUT" /home/bodylab/maquinaria/app/static/downloads/acr-operadores.apk 2>/dev/null || true
cp -f "$APK_OUT" /home/bodylab/maquinaria/app/static/downloads/acr-operadores-v2.apk 2>/dev/null || true

cp "$APK_OUT" /tmp/acr-operadores.apk
cp "$APK_OUT" /tmp/acr-operadores-v2.apk
echo "✅ APK Compilado y listo en /tmp/acr-operadores-v2.apk"
