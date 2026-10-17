#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

APP_VERSION=$(python3 -c "import kaffeine_dvr; print(kaffeine_dvr.__version__)")
PKG_NAME="tv-guide-dvr-kaffeine"
OUTPUT_DIR="$REPO_DIR/build-deb"
DEB_ROOT="$OUTPUT_DIR/deb_root"

echo "=== Building PyInstaller standalone bundle ==="
pyinstaller --onedir --name kaffeine-dvr --windowed --add-data "assets:assets" --add-data "RELEASE_NOTES.md:." kaffeine_dvr/gui.py --noconfirm

echo "=== Assembling Debian Package Directory Structure ==="
rm -rf "$DEB_ROOT"
mkdir -p "$DEB_ROOT/DEBIAN"
mkdir -p "$DEB_ROOT/opt/TV.Guide.DVR.Kaffeine"
mkdir -p "$DEB_ROOT/usr/bin"
mkdir -p "$DEB_ROOT/usr/share/applications"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$DEB_ROOT/usr/lib/systemd/user"

# Copy binary bundle
cp -r dist/kaffeine-dvr/* "$DEB_ROOT/opt/TV.Guide.DVR.Kaffeine/"

# Remove bundled libfontconfig to avoid conflicts on host distributions
rm -f "$DEB_ROOT/opt/TV.Guide.DVR.Kaffeine/libfontconfig.so"*
rm -f "$DEB_ROOT/opt/TV.Guide.DVR.Kaffeine/_internal/libfontconfig.so"*

# Bundle CA certificate fallback if available
if [ -f "assets/cacert.pem" ]; then
    cp assets/cacert.pem "$DEB_ROOT/opt/TV.Guide.DVR.Kaffeine/"
    [ -d "$DEB_ROOT/opt/TV.Guide.DVR.Kaffeine/_internal" ] && cp assets/cacert.pem "$DEB_ROOT/opt/TV.Guide.DVR.Kaffeine/_internal/"
fi

# Launcher script in /usr/bin/kaffeine-dvr
cat << 'EOF' > "$DEB_ROOT/usr/bin/kaffeine-dvr"
#!/bin/bash
OPT_DIR="/opt/TV.Guide.DVR.Kaffeine"
export PATH="${OPT_DIR}:${PATH}"
export LD_LIBRARY_PATH="${OPT_DIR}/_internal:${OPT_DIR}:${LD_LIBRARY_PATH}"

if [ -z "$SSL_CERT_FILE" ] || [ ! -f "$SSL_CERT_FILE" ]; then
    for cert_path in \
        /etc/ssl/certs/ca-certificates.crt \
        /etc/pki/tls/certs/ca-bundle.crt \
        /etc/ssl/ca-bundle.pem \
        /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
        /etc/ca-certificates/extracted/tls-ca-bundle.pem \
        /etc/ssl/cert.pem \
        "${OPT_DIR}/cacert.pem" \
        "${OPT_DIR}/assets/cacert.pem"
    do
        if [ -f "$cert_path" ]; then
            export SSL_CERT_FILE="$cert_path"
            break
        fi
    done
fi

exec "${OPT_DIR}/kaffeine-dvr" "$@"
EOF
chmod +x "$DEB_ROOT/usr/bin/kaffeine-dvr"

# Desktop launcher
cat << 'EOF' > "$DEB_ROOT/usr/share/applications/kaffeine-dvr.desktop"
[Desktop Entry]
Categories=AudioVideo;TV;Recorder;
Comment=Modern TV Guide & DVR Recording Manager for Kaffeine
Exec=kaffeine-dvr
GenericName=TV Guide & Recording Manager
Icon=kaffeine-dvr
Keywords=tv;dvr;kaffeine;record;guide;epg;
Name=Kaffeine TV Guide
StartupNotify=true
StartupWMClass=kaffeine-dvr
Terminal=false
Type=Application
EOF

# Icons
cp assets/kaffeine-dvr.svg "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps/kaffeine-dvr.svg"
for sz in 16 24 32 48 64 128 256 512; do
    if [ -f "assets/icons/kaffeine-dvr-${sz}.png" ]; then
        mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/${sz}x${sz}/apps"
        cp "assets/icons/kaffeine-dvr-${sz}.png" "$DEB_ROOT/usr/share/icons/hicolor/${sz}x${sz}/apps/kaffeine-dvr.png"
    fi
done

# Systemd user service unit
cat << 'EOF' > "$DEB_ROOT/usr/lib/systemd/user/kaffeine-dvr-watcher.service"
[Unit]
Description=Kaffeine DVR Background Watcher (Just-In-Time Dispatcher)
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/kaffeine-dvr --watch
Restart=on-failure
RestartSec=10
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"
Environment="XDG_CURRENT_DESKTOP=KDE"
Environment="KDE_FULL_SESSION=true"
Environment="KDE_SESSION_VERSION=6"
Environment="DESKTOP_SESSION=plasma.desktop"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

# Installed-Size calculation (in kilobytes)
INSTALLED_SIZE=$(du -sk "$DEB_ROOT" | cut -f1)

# Control file
cat << EOF > "$DEB_ROOT/DEBIAN/control"
Package: ${PKG_NAME}
Version: ${APP_VERSION}
Section: video
Priority: optional
Architecture: amd64
Installed-Size: ${INSTALLED_SIZE}
Maintainer: PlasmaDrifter <https://github.com/PlasmaDrifter/TV.Guide.DVR.Kaffeine>
Depends: kaffeine
Recommends: mpv, libnotify-bin
Homepage: https://github.com/PlasmaDrifter/TV.Guide.DVR.Kaffeine
Description: Modern TV Guide & Just-In-Time DVR daemon for Kaffeine
 Standalone packaged desktop TV Guide, series auto-record rules scheduler,
 and background Just-In-Time recording daemon for Kaffeine on Linux.
EOF

# Post-install & Post-remove hooks
cat << 'EOF' > "$DEB_ROOT/DEBIAN/postinst"
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF
chmod 755 "$DEB_ROOT/DEBIAN/postinst"

cat << 'EOF' > "$DEB_ROOT/DEBIAN/postrm"
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF
chmod 755 "$DEB_ROOT/DEBIAN/postrm"

# Build DEB
DEB_PACKAGE_NAME="TV.Guide.DVR.Kaffeine-v${APP_VERSION}-amd64.deb"
OUTPUT_DEB="$OUTPUT_DIR/$DEB_PACKAGE_NAME"

echo "=== Building .deb package ==="
dpkg-deb --build --root-owner-group "$DEB_ROOT" "$OUTPUT_DEB"
rm -rf "$DEB_ROOT" build dist

echo "=== DEB created successfully: $OUTPUT_DEB ==="
