#!/usr/bin/env bash
set -e

# ==============================================================================
# Kaffeine DVR & TV Guide - Uninstaller
# ==============================================================================

PURGE_DATA=false

for arg in "$@"; do
    case "$arg" in
        --purge)
            PURGE_DATA=true
            ;;
        -h|--help)
            echo "Usage: ./uninstall.sh [options]"
            echo ""
            echo "Options:"
            echo "  --purge    Also delete all user configuration and guide database"
            echo "  -h, --help Show this help message"
            exit 0
            ;;
    esac
done

echo "============================================================"
echo "Uninstalling Kaffeine DVR & TV Guide"
echo "============================================================"

# 1. Stop and remove systemd background service
echo "Stopping background watcher service..."
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop kaffeine-dvr-watcher.service >/dev/null 2>&1 || true
    systemctl --user disable kaffeine-dvr-watcher.service >/dev/null 2>&1 || true
fi

USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
if [ -f "$USER_SYSTEMD_DIR/kaffeine-dvr-watcher.service" ]; then
    rm -f "$USER_SYSTEMD_DIR/kaffeine-dvr-watcher.service"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user daemon-reload || true
    fi
    echo "Removed systemd service."
fi

# 2. Remove desktop launcher
USER_APPS_DIR="$HOME/.local/share/applications"
if [ -f "$USER_APPS_DIR/kaffeine-dvr.desktop" ]; then
    rm -f "$USER_APPS_DIR/kaffeine-dvr.desktop"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$USER_APPS_DIR" >/dev/null 2>&1 || true
    fi
    echo "Removed desktop launcher."
fi

# 3. Uninstall Python package
echo "Removing Python package..."
PIP_FLAGS=""
if python3 -m pip install --help 2>&1 | grep -q -- '--break-system-packages'; then
    PIP_FLAGS="--break-system-packages"
fi
python3 -m pip uninstall -y $PIP_FLAGS kaffeine-dvr >/dev/null 2>&1 || true

# 4. Remove standalone binary if present
USER_BIN_DIR="$HOME/.local/bin"
if [ -f "$USER_BIN_DIR/kaffeine-dvr" ]; then
    rm -f "$USER_BIN_DIR/kaffeine-dvr"
    echo "Removed launcher binary: $USER_BIN_DIR/kaffeine-dvr"
fi

# 5. Handle user data/configuration
CONFIG_DIR="$HOME/.config/kaffeine-dvr"
DATA_DIR="$HOME/.local/share/kaffeine-dvr"

if [ "$PURGE_DATA" = true ]; then
    echo "Purging configuration and database directories..."
    rm -rf "$CONFIG_DIR" "$DATA_DIR"
    echo "Removed: $CONFIG_DIR and $DATA_DIR"
elif [ -t 0 ]; then
    read -p "Would you also like to delete your configuration and database ($CONFIG_DIR)? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$CONFIG_DIR" "$DATA_DIR"
        echo "Removed configuration and database."
    else
        echo "Preserved configuration and database at $CONFIG_DIR."
    fi
else
    echo "Preserved configuration and database at $CONFIG_DIR (use --purge to remove)."
fi

echo ""
echo "============================================================"
echo "Kaffeine DVR & TV Guide has been completely uninstalled."
echo "============================================================"
