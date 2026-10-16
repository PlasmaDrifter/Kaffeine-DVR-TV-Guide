#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

echo "=== 1. Building PyInstaller binary bundle ==="
pyinstaller --onedir --name kaffeine-dvr --windowed --add-data "assets:assets" --add-data "RELEASE_NOTES.md:." kaffeine_dvr/gui.py --noconfirm

echo "=== 2. Setting up AppDir ==="
rm -rf AppDir
mkdir -p AppDir/usr/bin AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/scalable/apps

cp -r dist/kaffeine-dvr/* AppDir/usr/bin/

# Ensure assets are present in multiple discoverable AppDir locations
mkdir -p AppDir/usr/bin/assets AppDir/usr/share/kaffeine-dvr/assets
cp -r assets/* AppDir/usr/bin/assets/ 2>/dev/null || true
cp -r assets/* AppDir/usr/share/kaffeine-dvr/assets/ 2>/dev/null || true
cp RELEASE_NOTES.md AppDir/usr/bin/ 2>/dev/null || true
cp RELEASE_NOTES.md AppDir/usr/share/kaffeine-dvr/ 2>/dev/null || true
if [ -d AppDir/usr/bin/_internal ]; then
    mkdir -p AppDir/usr/bin/_internal/assets
    cp -r assets/* AppDir/usr/bin/_internal/assets/ 2>/dev/null || true
    cp RELEASE_NOTES.md AppDir/usr/bin/_internal/ 2>/dev/null || true
    # Remove bundled libfontconfig to prevent SIGSEGV on Debian/Ubuntu/Kubuntu due to cache format mismatches
    rm -f AppDir/usr/bin/_internal/libfontconfig.so*
fi
rm -f AppDir/usr/bin/libfontconfig.so*

# Icons
cp assets/kaffeine-dvr.svg AppDir/kaffeine-dvr.svg
cp assets/kaffeine-dvr.svg AppDir/.DirIcon
cp assets/kaffeine-dvr.svg AppDir/usr/share/icons/hicolor/scalable/apps/kaffeine-dvr.svg
for sz in 16 24 32 48 64 128 256 512; do
    if [ -f "assets/icons/kaffeine-dvr-${sz}.png" ]; then
        mkdir -p AppDir/usr/share/icons/hicolor/${sz}x${sz}/apps
        cp "assets/icons/kaffeine-dvr-${sz}.png" "AppDir/usr/share/icons/hicolor/${sz}x${sz}/apps/kaffeine-dvr.png"
    fi
done

# Detect version dynamically from kaffeine_dvr/__init__.py
APP_VERSION=$(python3 -c "import kaffeine_dvr; print(kaffeine_dvr.__version__)")

# Desktop File with complete AppImage metadata recognized by AppManager
cat << DESK > AppDir/kaffeine-dvr.desktop
[Desktop Entry]
Name=Kaffeine DVR and TV Guide
GenericName=TV Guide and Recording Manager
Comment=Modern TV Guide browser & Just-In-Time DVR daemon for Kaffeine
Exec=kaffeine-dvr %U
Icon=kaffeine-dvr
Terminal=false
Type=Application
Categories=AudioVideo;Video;TV;Recorder;
StartupNotify=true
StartupWMClass=kaffeine-dvr
X-AppImage-Name=Kaffeine DVR and TV Guide
X-AppImage-Version=${APP_VERSION}
X-AppImage-Arch=x86_64
DESK

cp AppDir/kaffeine-dvr.desktop AppDir/usr/share/applications/kaffeine-dvr.desktop

# Bundle CA certificate fallback directly in AppDir
if [ -f "assets/cacert.pem" ]; then
    cp assets/cacert.pem AppDir/usr/share/kaffeine-dvr/cacert.pem
    cp assets/cacert.pem AppDir/usr/bin/cacert.pem
    [ -d AppDir/usr/bin/_internal ] && cp assets/cacert.pem AppDir/usr/bin/_internal/cacert.pem
fi

# AppRun launcher
cat << 'APPRUN' > AppDir/AppRun
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/bin/_internal:${HERE}/usr/lib:${LD_LIBRARY_PATH}"

# Ensure SSL CA certificates are found across all Linux distributions (Ubuntu, Debian, Fedora, Arch, etc.)
if [ -z "$SSL_CERT_FILE" ] || [ ! -f "$SSL_CERT_FILE" ]; then
    for cert_path in \
        /etc/ssl/certs/ca-certificates.crt \
        /etc/pki/tls/certs/ca-bundle.crt \
        /etc/ssl/ca-bundle.pem \
        /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
        /etc/ca-certificates/extracted/tls-ca-bundle.pem \
        /etc/ssl/cert.pem \
        "${HERE}/usr/share/kaffeine-dvr/cacert.pem" \
        "${HERE}/usr/bin/cacert.pem" \
        "${HERE}/usr/bin/assets/cacert.pem"
    do
        if [ -f "$cert_path" ]; then
            export SSL_CERT_FILE="$cert_path"
            break
        fi
    done
fi

if [ -z "$SSL_CERT_DIR" ] || [ ! -d "$SSL_CERT_DIR" ]; then
    for cert_dir in \
        /etc/ssl/certs \
        /etc/pki/tls/certs \
        /system/etc/security/cacerts
    do
        if [ -d "$cert_dir" ]; then
            export SSL_CERT_DIR="$cert_dir"
            break
        fi
    done
fi

exec "${HERE}/usr/bin/kaffeine-dvr" "$@"
APPRUN
chmod +x AppDir/AppRun

echo "=== 3. Packaging AppImage ==="
OUTPUT_APPIMAGE="$SCRIPT_DIR/Kaffeine-DVR-TV-Guide-v${APP_VERSION}-x86_64.AppImage"
mkdir -p "$SCRIPT_DIR"
ARCH=x86_64 NO_APPSTREAM=1 appimagetool AppDir "$OUTPUT_APPIMAGE"

# Create/update unversioned symlink for convenient launcher scripts or generic paths
ln -sf "Kaffeine-DVR-TV-Guide-v${APP_VERSION}-x86_64.AppImage" "$SCRIPT_DIR/Kaffeine-DVR-TV-Guide-x86_64.AppImage"

rm -rf AppDir build dist

echo "=== AppImage created successfully at $OUTPUT_APPIMAGE ==="

