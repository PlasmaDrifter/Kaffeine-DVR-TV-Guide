#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

APP_VERSION=$(python3 -c "import kaffeine_dvr; print(kaffeine_dvr.__version__)")
PKG_NAME="TV.Guide.DVR.Kaffeine"
OUTPUT_DIR="$REPO_DIR/build-rpm"
RPMBUILD_DIR="$OUTPUT_DIR/rpmbuild"

echo "=== Building PyInstaller standalone bundle ==="
pyinstaller --onedir --name kaffeine-dvr --windowed --add-data "assets:assets" --add-data "RELEASE_NOTES.md:." kaffeine_dvr/gui.py --noconfirm

echo "=== Assembling RPM Build Structure ==="
rm -rf "$RPMBUILD_DIR"
mkdir -p "$RPMBUILD_DIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS,BUILDROOT}

# Create staging structure in SOURCES
STAGE_DIR="$RPMBUILD_DIR/SOURCES/${PKG_NAME}-${APP_VERSION}"
mkdir -p "$STAGE_DIR/opt/TV.Guide.DVR.Kaffeine"
mkdir -p "$STAGE_DIR/usr/bin"
mkdir -p "$STAGE_DIR/usr/share/applications"
mkdir -p "$STAGE_DIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$STAGE_DIR/usr/lib/systemd/user"

cp -r dist/kaffeine-dvr/* "$STAGE_DIR/opt/TV.Guide.DVR.Kaffeine/"

# Remove bundled libfontconfig to prevent conflicts
rm -f "$STAGE_DIR/opt/TV.Guide.DVR.Kaffeine/libfontconfig.so"*
rm -f "$STAGE_DIR/opt/TV.Guide.DVR.Kaffeine/_internal/libfontconfig.so"*

if [ -f "assets/cacert.pem" ]; then
    cp assets/cacert.pem "$STAGE_DIR/opt/TV.Guide.DVR.Kaffeine/"
    [ -d "$STAGE_DIR/opt/TV.Guide.DVR.Kaffeine/_internal" ] && cp assets/cacert.pem "$STAGE_DIR/opt/TV.Guide.DVR.Kaffeine/_internal/"
fi

# Launcher script in /usr/bin/kaffeine-dvr
cat << 'EOF' > "$STAGE_DIR/usr/bin/kaffeine-dvr"
#!/bin/bash
OPT_DIR="/opt/TV.Guide.DVR.Kaffeine"
export PATH="${OPT_DIR}:${PATH}"
export LD_LIBRARY_PATH="${OPT_DIR}/_internal:${OPT_DIR}:${LD_LIBRARY_PATH}"

if [ -z "$SSL_CERT_FILE" ] || [ ! -f "$SSL_CERT_FILE" ]; then
    for cert_path in \
        /etc/pki/tls/certs/ca-bundle.crt \
        /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
        /etc/ssl/certs/ca-certificates.crt \
        /etc/ssl/ca-bundle.pem \
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
chmod +x "$STAGE_DIR/usr/bin/kaffeine-dvr"

# Desktop launcher
cat << 'EOF' > "$STAGE_DIR/usr/share/applications/kaffeine-dvr.desktop"
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
cp assets/kaffeine-dvr.svg "$STAGE_DIR/usr/share/icons/hicolor/scalable/apps/kaffeine-dvr.svg"
for sz in 16 24 32 48 64 128 256 512; do
    if [ -f "assets/icons/kaffeine-dvr-${sz}.png" ]; then
        mkdir -p "$STAGE_DIR/usr/share/icons/hicolor/${sz}x${sz}/apps"
        cp "assets/icons/kaffeine-dvr-${sz}.png" "$STAGE_DIR/usr/share/icons/hicolor/${sz}x${sz}/apps/kaffeine-dvr.png"
    fi
done

# Systemd user service unit
cat << 'EOF' > "$STAGE_DIR/usr/lib/systemd/user/kaffeine-dvr-watcher.service"
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

# Create tarball for rpmbuild
tar -czf "$RPMBUILD_DIR/SOURCES/${PKG_NAME}-${APP_VERSION}.tar.gz" -C "$RPMBUILD_DIR/SOURCES" "${PKG_NAME}-${APP_VERSION}"
rm -rf "$STAGE_DIR"

# Write RPM Spec file (with debuginfo disabled)
cat << EOF > "$RPMBUILD_DIR/SPECS/${PKG_NAME}.spec"
%define _topdir $RPMBUILD_DIR
%global debug_package %{nil}
%global __os_install_post %{nil}
%global __requires_exclude ^lib.*$
%global __provides_exclude ^lib.*$
AutoReqProv: no

Name:           ${PKG_NAME}
Version:        ${APP_VERSION}
Release:        1%{?dist}
Summary:        Modern TV Guide & Just-In-Time DVR daemon for Kaffeine
License:        MIT
URL:            https://github.com/PlasmaDrifter/TV.Guide.DVR.Kaffeine
Source0:        %{name}-%{version}.tar.gz

Requires:       kaffeine
Recommends:     mpv

%description
Modern TV Guide browser, series auto-record rules scheduler,
and background Just-In-Time recording daemon for Kaffeine.

%prep
%setup -q

%build

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}
cp -r opt usr %{buildroot}/

%post
if [ -x /usr/bin/update-desktop-database ]; then
    /usr/bin/update-desktop-database -q /usr/share/applications || true
fi
if [ -x /usr/bin/gtk-update-icon-cache ]; then
    /usr/bin/gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi

%postun
if [ -x /usr/bin/update-desktop-database ]; then
    /usr/bin/update-desktop-database -q /usr/share/applications || true
fi
if [ -x /usr/bin/gtk-update-icon-cache ]; then
    /usr/bin/gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi

%files
/opt/TV.Guide.DVR.Kaffeine
/usr/bin/kaffeine-dvr
/usr/share/applications/kaffeine-dvr.desktop
/usr/share/icons/hicolor/*/apps/kaffeine-dvr.*
/usr/lib/systemd/user/kaffeine-dvr-watcher.service

%changelog
* Fri Oct 16 2026 PlasmaDrifter <https://github.com/PlasmaDrifter/TV.Guide.DVR.Kaffeine> - ${APP_VERSION}-1
- Packaged release for TV.Guide.DVR.Kaffeine
EOF

echo "=== Building .rpm package ==="
rpmbuild -bb --define "_topdir $RPMBUILD_DIR" "$RPMBUILD_DIR/SPECS/${PKG_NAME}.spec"

RPM_FILE=$(find "$RPMBUILD_DIR/RPMS" -name "*.rpm" | head -n 1)
RPM_FILENAME=$(basename "$RPM_FILE")
cp "$RPM_FILE" "$OUTPUT_DIR/"
rm -rf "$RPMBUILD_DIR" build dist

echo "=== RPM created successfully: $OUTPUT_DIR/$RPM_FILENAME ==="
