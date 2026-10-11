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
cp /usr/share/icons/Papirus/48x48/apps/kaffeine.svg AppDir/kaffeine.svg
cp /usr/share/icons/Papirus/48x48/apps/kaffeine.svg AppDir/usr/share/icons/hicolor/scalable/apps/kaffeine.svg

# Detect version dynamically from kaffeine_dvr/__init__.py
APP_VERSION=$(python3 -c "import kaffeine_dvr; print(kaffeine_dvr.__version__)")

# Desktop File with complete AppImage metadata recognized by AppManager
cat << DESK > AppDir/kaffeine-dvr.desktop
[Desktop Entry]
Name=Kaffeine DVR and TV Guide
GenericName=TV Guide and Recording Manager
Comment=Modern TV Guide browser & Just-In-Time DVR daemon for Kaffeine
Exec=kaffeine-dvr %U
Icon=kaffeine
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

# AppRun launcher
cat << 'APPRUN' > AppDir/AppRun
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/bin/_internal:${HERE}/usr/lib:${LD_LIBRARY_PATH}"
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

