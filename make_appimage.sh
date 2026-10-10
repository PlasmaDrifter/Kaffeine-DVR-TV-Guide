#!/bin/bash
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

echo "=== 1. Building PyInstaller binary bundle ==="
pyinstaller --onedir --name kaffeine-dvr --windowed --add-data "assets:assets" kaffeine_dvr/gui.py --noconfirm

echo "=== 2. Setting up AppDir ==="
rm -rf AppDir
mkdir -p AppDir/usr/bin AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/scalable/apps

cp -r dist/kaffeine-dvr/* AppDir/usr/bin/

# Icons
cp /usr/share/icons/Papirus/48x48/apps/kaffeine.svg AppDir/kaffeine.svg
cp /usr/share/icons/Papirus/48x48/apps/kaffeine.svg AppDir/usr/share/icons/hicolor/scalable/apps/kaffeine.svg

# Desktop File with complete AppImage metadata recognized by AppManager
cat << 'DESK' > AppDir/kaffeine-dvr.desktop
[Desktop Entry]
Name=Kaffeine DVR & TV Guide
GenericName=TV Guide & Recording Manager
Comment=Modern TV Guide browser & Just-In-Time DVR daemon for Kaffeine
Exec=kaffeine-dvr %U
Icon=kaffeine
Terminal=false
Type=Application
Categories=AudioVideo;Video;TV;Recorder;
StartupNotify=true
StartupWMClass=kaffeine-dvr
X-AppImage-Name=Kaffeine DVR & TV Guide
X-AppImage-Version=0.8.4
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
OUTPUT_APPIMAGE="/home/jmc/Applications/KaffeineDVR/Kaffeine-DVR-TV-Guide-x86_64.AppImage"
mkdir -p "/home/jmc/Applications/KaffeineDVR"
ARCH=x86_64 NO_APPSTREAM=1 appimagetool AppDir "$OUTPUT_APPIMAGE"

rm -rf AppDir build dist

echo "=== AppImage created successfully at $OUTPUT_APPIMAGE ==="
