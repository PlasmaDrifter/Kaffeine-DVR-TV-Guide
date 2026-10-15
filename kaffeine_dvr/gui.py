"""
PyQt6 Graphical User Interface for Kaffeine DVR & TV Guide.

Provides 24-hour single-day grid and list guide views, automated rule creation,
recording schedule management, timeshift playback, custom frameless window styling,
and real-time guide synchronization with antenna channel mapping.
"""

import html
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import (
    QByteArray,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QPolygon,
    QPolygonF,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QProxyStyle,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QStyleFactory,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QStylePainter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

try:
    from .config import (
        APP_THEMES,
        DEFAULT_CATEGORY_COLORS,
        THEME_PRESETS,
        ConfigManager,
    )
    from .dbus_client import KaffeineDbusClient
    from .guide_service import GuideService
    from .queue_manager import QueueManager
    from .rules_engine import RulesEngine
    from .signal_scanner import ChannelSignalScanWorker, DvbSignalReader
    from .storage_manager import StorageManager
    from .watcher import Watcher
except (ImportError, ValueError):
    from kaffeine_dvr.config import (
        APP_THEMES,
        DEFAULT_CATEGORY_COLORS,
        THEME_PRESETS,
        ConfigManager,
    )
    from kaffeine_dvr.dbus_client import KaffeineDbusClient
    from kaffeine_dvr.guide_service import GuideService
    from kaffeine_dvr.queue_manager import QueueManager
    from kaffeine_dvr.rules_engine import RulesEngine
    from kaffeine_dvr.signal_scanner import ChannelSignalScanWorker, DvbSignalReader
    from kaffeine_dvr.storage_manager import StorageManager
    from kaffeine_dvr.watcher import Watcher


def _get_checkmark_icon_path() -> str:
    # 1. Check PyInstaller bundle directory (sys._MEIPASS)
    if hasattr(sys, "_MEIPASS"):
        meipass_asset = Path(sys._MEIPASS) / "assets" / "checkmark.png"
        if meipass_asset.is_file():
            return str(meipass_asset).replace("\\", "/")

    # 2. Check relative to executable (AppDir/usr/bin/_internal/assets/checkmark.png or similar)
    try:
        exe_dir = Path(sys.executable).resolve().parent
        for cand in [
            exe_dir / "assets" / "checkmark.png",
            exe_dir / "_internal" / "assets" / "checkmark.png",
            exe_dir.parent / "share" / "kaffeine-dvr" / "assets" / "checkmark.png",
        ]:
            if cand.is_file():
                return str(cand).replace("\\", "/")
    except Exception:
        pass

    # 3. Check relative to this source tree
    try:
        base_dir = Path(__file__).resolve().parent.parent
        asset_path = base_dir / "assets" / "checkmark.png"
        if asset_path.is_file():
            return str(asset_path).replace("\\", "/")
    except Exception:
        pass

    # 4. Fallback to writable user config directory (~/.config/kaffeine-dvr/assets/checkmark.png)
    fallback_dir = Path.home() / ".config" / "kaffeine-dvr" / "assets"
    try:
        fallback_dir.mkdir(parents=True, exist_ok=True)
        user_asset = fallback_dir / "checkmark.png"
        if not user_asset.is_file():
            pix = QPixmap(14, 14)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor('#ffffff'), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawLine(2, 7, 5, 11)
            p.drawLine(5, 11, 12, 3)
            p.end()
            pix.save(str(user_asset), 'PNG')
        if user_asset.is_file():
            return str(user_asset).replace("\\", "/")
    except Exception:
        pass

    return ""


_CACHED_CHECKMARK_PATH: Optional[str] = None


def get_checkmark_icon_path() -> str:
    global _CACHED_CHECKMARK_PATH
    if _CACHED_CHECKMARK_PATH is None:
        _CACHED_CHECKMARK_PATH = _get_checkmark_icon_path()
    return _CACHED_CHECKMARK_PATH or ""


def _get_app_icon_asset_path() -> str:
    # 1. Check PyInstaller bundle directory (sys._MEIPASS)
    if hasattr(sys, "_MEIPASS"):
        for name in ["kaffeine-dvr.svg", "kaffeine-dvr.png", "kaffeine-dvr-512.png"]:
            cand = Path(sys._MEIPASS) / "assets" / name
            if cand.is_file():
                return str(cand)

    # 2. Check relative to executable
    try:
        exe_dir = Path(sys.executable).resolve().parent
        for root in [exe_dir / "assets", exe_dir / "_internal" / "assets", exe_dir.parent / "share" / "kaffeine-dvr" / "assets"]:
            for name in ["kaffeine-dvr.svg", "kaffeine-dvr.png", "kaffeine-dvr-512.png"]:
                cand = root / name
                if cand.is_file():
                    return str(cand)
    except Exception:
        pass

    # 3. Check relative to source tree
    try:
        base_dir = Path(__file__).resolve().parent.parent
        for name in ["kaffeine-dvr.svg", "kaffeine-dvr.png", "kaffeine-dvr-512.png"]:
            cand = base_dir / "assets" / name
            if cand.is_file():
                return str(cand)
    except Exception:
        pass

    return ""


def make_status_dot_icon(color_hex: str, size: int = 12) -> QIcon:
    """Generate a crisp, anti-aliased circular indicator icon with a subtle dark border."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color_hex))
    p.setPen(QPen(QColor(0, 0, 0, 100), 1.0))
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pix)


class SyncWorker(QThread):
    progress = pyqtSignal(str)
    progress_val = pyqtSignal(int)
    finished = pyqtSignal(int, str)

    def __init__(self, guide_service: GuideService, days: int):
        super().__init__()
        self.guide_service = guide_service
        self.days = days

    def _on_progress(self, msg: str):
        self.progress.emit(msg)
        # Check if message contains step indicators like "(6/15)"
        import re
        m = re.search(r"\((\d+)/(\d+)\)", msg)
        if m:
            cur, total = int(m.group(1)), int(m.group(2))
            if total > 0:
                pct = int((cur / total) * 100)
                self.progress_val.emit(max(5, min(95, pct)))

    def run(self):
        try:
            count = self.guide_service.sync_guide(
                days=self.days,
                progress_callback=self._on_progress
            )
            self.progress_val.emit(100)
            self.finished.emit(count, "")
        except Exception as e:
            self.finished.emit(0, str(e))


class RulesWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(list, str)

    def __init__(self, rules_engine: RulesEngine):
        super().__init__()
        self.rules_engine = rules_engine

    def run(self):
        try:
            scheduled = self.rules_engine.evaluate_and_schedule(
                progress_callback=lambda msg: self.progress.emit(msg)
            )
            self.finished.emit(scheduled, "")
        except Exception as e:
            self.finished.emit([], str(e))


class HealthCheckWorker(QThread):
    finished = pyqtSignal(dict)

    def __init__(self, guide_service: GuideService):
        super().__init__()
        self.guide_service = guide_service

    def run(self):
        try:
            results = self.guide_service.check_all_sources_health()
            self.finished.emit(results)
        except Exception:
            self.finished.emit({})


class UpdateCheckWorker(QThread):
    finished = pyqtSignal(dict)

    def run(self):
        try:
            from kaffeine_dvr.updater import check_for_updates
            res = check_for_updates()
            self.finished.emit(res)
        except Exception as e:
            self.finished.emit({"update_available": False, "details": str(e), "error": True})


class UpdateApplyWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def run(self):
        try:
            from kaffeine_dvr.updater import apply_update
            success, msg = apply_update(lambda text: self.progress.emit(text))
            self.finished.emit(success, msg)
        except Exception as e:
            self.finished.emit(False, str(e))


class ServiceLogsWorker(QThread):
    finished = pyqtSignal(str, bool)

    def __init__(self, lines: int = 100):
        super().__init__()
        self.lines = lines

    def run(self):
        try:
            cmd = ["journalctl", "--user", "-u", "kaffeine-dvr-watcher.service", "-n", str(self.lines), "--no-pager"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            output = res.stdout.strip() or res.stderr.strip() or "No log entries found for kaffeine-dvr-watcher.service."
            self.finished.emit(output, True)
        except Exception as e:
            self.finished.emit(f"Failed to fetch journal logs: {e}", False)


class ThemedComboBox(QComboBox):
    """
    QComboBox that renders a clean modern flat frame and an antialiased chevron vector arrow,
    eliminating raw 3D platform beveled buttons while matching the active theme.
    """
    def __init__(self, parent=None, centered: bool = False):
        super().__init__(parent)
        self.centered = centered

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, event):
        style_painter = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        opt.currentText = ""  # Prevent default left-aligned text rendering
        # Draw frame only, not the native arrow button
        opt.subControls = QStyle.SubControl.SC_ComboBoxFrame
        style_painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        arrow_area_width = 24

        # Draw clean chevron arrow on the right with interactive hover/focus accent
        is_active = self.underMouse() or self.hasFocus() or (self.view() and self.view().isVisible())
        if not self.isEnabled():
            arrow_color = self.palette().color(QPalette.ColorRole.PlaceholderText)
            arrow_color.setAlpha(100)
        elif is_active:
            arrow_color = self.palette().color(QPalette.ColorRole.Highlight)
        else:
            arrow_color = self.palette().color(QPalette.ColorRole.Text)
            arrow_color.setAlpha(200)

        pen = QPen(arrow_color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        ax = w - 14
        ay = h // 2 - 2
        painter.drawLine(ax - 4, ay, ax, ay + 4)
        painter.drawLine(ax, ay + 4, ax + 4, ay)

        # Draw text
        text = self.itemText(self.currentIndex())
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        if self.centered:
            text_rect = QRect(0, 0, w, h)
            style_painter.drawItemText(text_rect, Qt.AlignmentFlag.AlignCenter, self.palette(), self.isEnabled(), text, QPalette.ColorRole.Text)
        else:
            text_rect = QRect(8, 0, max(0, w - arrow_area_width - 8), h)
            style_painter.drawItemText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.palette(), self.isEnabled(), text, QPalette.ColorRole.Text)


class CenteredComboBox(ThemedComboBox):
    """
    QComboBox that displays its selected text and dropdown menu items centered.
    """
    def __init__(self, parent=None):
        super().__init__(parent, centered=True)

    def addItem(self, text: str, userData: Any = None):
        if userData is not None:
            super().addItem(text, userData)
        else:
            super().addItem(text)
        self.setItemData(self.count() - 1, Qt.AlignmentFlag.AlignCenter, Qt.ItemDataRole.TextAlignmentRole)

    def addItems(self, texts):
        super().addItems(texts)
        for i in range(self.count()):
            self.setItemData(i, Qt.AlignmentFlag.AlignCenter, Qt.ItemDataRole.TextAlignmentRole)

    def insertItem(self, index: int, text: str, userData: Any = None):
        if userData is not None:
            super().insertItem(index, text, userData)
        else:
            super().insertItem(index, text)
        self.setItemData(index, Qt.AlignmentFlag.AlignCenter, Qt.ItemDataRole.TextAlignmentRole)


class BaseFramelessDialog(QDialog):
    """
    Base dialog providing a modern frameless window without OS titlebar decorations,
    antialiased rounded corners (10px) matching the active application theme,
    draggable header/window movement, and keyboard accessibility.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def get_dialog_colors(self):
        bg = "#191c28"
        border = "#333a4d"
        parent = self.parent()
        config_mgr = None
        if hasattr(self, "config_mgr") and self.config_mgr:
            config_mgr = self.config_mgr
        elif parent and hasattr(parent, "config_mgr") and parent.config_mgr:
            config_mgr = parent.config_mgr

        if config_mgr:
            app_theme = getattr(config_mgr, "app_theme", "midnight")
            tokens = APP_THEMES.get(app_theme, APP_THEMES.get("midnight", {}))
            if tokens:
                bg = tokens.get("bg_window", bg)
                border = tokens.get("border_color", border)
        return bg, border

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        bg_col, border_col = self.get_dialog_colors()
        painter.setBrush(QColor(bg_col))
        painter.setPen(QPen(QColor(border_col), 1.5))
        painter.drawRoundedRect(rect, 10, 10)


class ServiceLogsDialog(BaseFramelessDialog):
    """
    Log viewer dialog displaying recent journalctl entries for kaffeine-dvr-watcher.service.
    Features fast live refresh, text search/filtering, line limit selection, and clipboard export.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Background Watcher Service Logs")
        self.resize(860, 560)
        self.raw_logs = ""
        self._worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # Header bar
        header_row = QHBoxLayout()
        header_info = QLabel("<b>kaffeine-dvr-watcher.service</b> &nbsp;•&nbsp; Systemd User Journal")
        header_info.setStyleSheet("font-size: 13px; color: #cdd6e2;")
        header_row.addWidget(header_info)
        header_row.addStretch()

        self.status_badge = QLabel("Checking...")
        self.status_badge.setStyleSheet("font-size: 11px; font-weight: bold; color: #8c98aa;")
        header_row.addWidget(self.status_badge)

        close_x = QToolButton(self)
        close_x.setText("✕")
        close_x.setToolTip("Close")
        close_x.setCursor(Qt.CursorShape.PointingHandCursor)
        close_x.setStyleSheet(
            "QToolButton { background: transparent; color: #8c98aa; font-size: 13px; font-weight: bold; border: none; padding: 2px 6px; border-radius: 4px; }"
            "QToolButton:hover { color: #ffffff; background-color: rgba(255, 255, 255, 0.1); }"
        )
        close_x.clicked.connect(self.accept)
        header_row.addWidget(close_x)

        layout.addLayout(header_row)

        # Controls row
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)

        ctrl_row.addWidget(QLabel("Lines:"))
        self.lines_combo = ThemedComboBox()
        self.lines_combo.addItems(["50", "100", "250", "500", "1000"])
        self.lines_combo.setCurrentText("100")
        self.lines_combo.currentIndexChanged.connect(self.refresh_logs)
        ctrl_row.addWidget(self.lines_combo)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter logs by text...")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self._apply_filter)
        ctrl_row.addWidget(self.filter_input, 1)

        self.refresh_btn = QPushButton("Refresh Logs")
        self.refresh_btn.clicked.connect(self.refresh_logs)
        ctrl_row.addWidget(self.refresh_btn)

        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        ctrl_row.addWidget(self.copy_btn)

        layout.addLayout(ctrl_row)

        # Log content view
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Monospace", 9))
        self.log_view.setStyleSheet(
            "QPlainTextEdit { background-color: #0f1218; color: #d0d8e2; border: 1px solid #2b3242; border-radius: 4px; padding: 8px; }"
        )
        layout.addWidget(self.log_view, 1)

        # Footer
        footer_row = QHBoxLayout()
        self.line_count_lbl = QLabel("")
        self.line_count_lbl.setStyleSheet("color: #8c98aa; font-size: 11px;")
        footer_row.addWidget(self.line_count_lbl)
        footer_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        footer_row.addWidget(close_btn)
        layout.addLayout(footer_row)

        self._update_status_badge()
        self.refresh_logs()

    def _update_status_badge(self):
        try:
            res = subprocess.run(
                ["systemctl", "--user", "is-active", "kaffeine-dvr-watcher.service"],
                capture_output=True, text=True, check=False
            )
            if res.stdout.strip() == "active":
                self.status_badge.setText("● Active (Running)")
                self.status_badge.setStyleSheet("font-size: 11px; font-weight: bold; color: #55a84c;")
            else:
                self.status_badge.setText("● Inactive / Stopped")
                self.status_badge.setStyleSheet("font-size: 11px; font-weight: bold; color: #e57373;")
        except Exception:
            self.status_badge.setText("● Status Unknown")
            self.status_badge.setStyleSheet("font-size: 11px; font-weight: bold; color: #8c98aa;")

    def refresh_logs(self):
        self._update_status_badge()
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Loading...")
        try:
            line_count = int(self.lines_combo.currentText())
        except (ValueError, TypeError):
            line_count = 100

        self._worker = ServiceLogsWorker(lines=line_count)
        self._worker.finished.connect(self._on_logs_loaded)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_logs_loaded(self, output: str, ok: bool):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh Logs")
        self.raw_logs = output
        self._apply_filter()

    def _apply_filter(self):
        query = self.filter_input.text().strip().lower()
        if not self.raw_logs:
            self.log_view.setPlainText("")
            self.line_count_lbl.setText("0 lines")
            return

        lines = self.raw_logs.splitlines()
        if query:
            filtered = [l for l in lines if query in l.lower()]
            self.log_view.setPlainText("\n".join(filtered))
            self.line_count_lbl.setText(f"Showing {len(filtered)} of {len(lines)} lines (filtered)")
        else:
            self.log_view.setPlainText(self.raw_logs)
            self.line_count_lbl.setText(f"Showing {len(lines)} lines")

        # Autoscroll to bottom for latest entries
        scrollbar = self.log_view.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def _copy_to_clipboard(self):
        text = self.log_view.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
                self.copy_btn.setText("Copied!")
                QTimer.singleShot(1500, lambda: self.copy_btn.setText("Copy to Clipboard"))

class ReleaseNotesDialog(BaseFramelessDialog):
    """
    Modal dialog providing an interactive 'What's New' release notes reader.
    Displays formatted changelog, version badge, and direct action buttons.
    """
    def __init__(self, parent=None, version: str = "", notes: str = "", update_available: bool = False, on_install_callback=None):
        super().__init__(parent)
        self.setWindowTitle(f"What's New - Kaffeine DVR v{version}" if version else "What's New in Kaffeine DVR")
        self.resize(720, 520)
        self.on_install_callback = on_install_callback

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(14)

        # Header bar
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        icon_lbl = QLabel()
        app_icon = get_app_icon()
        if not app_icon.isNull():
            icon_lbl.setPixmap(app_icon.pixmap(32, 32))
        header_row.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_text = f"Kaffeine DVR & TV Guide &nbsp;<span style='color: #52b774; font-size: 14px;'>v{version}</span>" if version else "Kaffeine DVR & TV Guide"
        dlg_title = QLabel(f"<b style='font-size: 16px; color: #ffffff;'>{title_text}</b>")
        title_col.addWidget(dlg_title)

        subtitle_text = "Release Notes and Changelog" if not update_available else "A newer update is available with the changes below:"
        dlg_sub = QLabel(f"<span style='color: #8c98aa; font-size: 12px;'>{subtitle_text}</span>")
        title_col.addWidget(dlg_sub)
        header_row.addLayout(title_col, 1)

        close_x = QToolButton(self)
        close_x.setText("✕")
        close_x.setToolTip("Close")
        close_x.setCursor(Qt.CursorShape.PointingHandCursor)
        close_x.setStyleSheet(
            "QToolButton { background: transparent; color: #8c98aa; font-size: 13px; font-weight: bold; border: none; padding: 2px 6px; border-radius: 4px; }"
            "QToolButton:hover { color: #ffffff; background-color: rgba(255, 255, 255, 0.1); }"
        )
        close_x.clicked.connect(self.accept)
        header_row.addWidget(close_x, 0, Qt.AlignmentFlag.AlignTop)

        layout.addLayout(header_row)

        # Markdown notes reader
        self.notes_view = QTextEdit()
        self.notes_view.setReadOnly(True)
        self.notes_view.setStyleSheet(
            "QTextEdit { background-color: #12141d; border: 1px solid #2d3548; "
            "border-radius: 6px; color: #d0d7de; font-size: 13px; line-height: 1.4; padding: 12px; }"
        )
        if notes:
            try:
                self.notes_view.setMarkdown(notes)
            except Exception:
                self.notes_view.setPlainText(notes)
        else:
            self.notes_view.setPlainText("No release notes found.")
        layout.addWidget(self.notes_view, 1)

        # Footer actions
        footer_row = QHBoxLayout()
        footer_row.setSpacing(10)

        github_btn = QPushButton("View on GitHub")
        github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        github_btn.clicked.connect(self._open_github)
        footer_row.addWidget(github_btn)

        footer_row.addStretch()

        if update_available and on_install_callback:
            install_btn = QPushButton("Install Update Now")
            install_btn.setObjectName("primaryActionBtn")
            install_btn.clicked.connect(self._install_and_close)
            footer_row.addWidget(install_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        footer_row.addWidget(close_btn)

        layout.addLayout(footer_row)

    def _open_github(self):
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl("https://github.com/PlasmaDrifter/Kaffeine-DVR-TV-Guide/releases/latest"))

    def _install_and_close(self):
        self.accept()
        if callable(self.on_install_callback):
            self.on_install_callback()



class ManualRecordDialog(BaseFramelessDialog):
    def __init__(self, channels: List[str], parent=None, default_buffer_mins: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Schedule Manual Recording")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)

        header_lbl = QLabel("<b>Schedule Manual Recording</b>")
        header_lbl.setStyleSheet("font-size: 15px; color: #ffffff; margin-bottom: 6px;")
        layout.addRow(header_lbl)

        self.title_input = QLineEdit()
        self.channel_combo = ThemedComboBox()
        self.channel_combo.addItems(channels)
        
        now = datetime.now()
        self.start_input = QLineEdit(now.strftime("%Y-%m-%dT%H:%M:00"))
        self.duration_input = QLineEdit("01:00:00")

        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(0, 180)
        self.buffer_spin.setValue(default_buffer_mins)
        self.buffer_spin.setSuffix(" minutes")

        layout.addRow("Title:", self.title_input)
        layout.addRow("Channel:", self.channel_combo)
        layout.addRow("Start (ISO):", self.start_input)
        layout.addRow("Duration (HH:MM:SS):", self.duration_input)
        layout.addRow("End Buffer (Post-Roll):", self.buffer_spin)

        btn_box = QHBoxLayout()
        self.ok_btn = QPushButton("Schedule")
        self.ok_btn.setObjectName("primaryActionBtn")
        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(self.ok_btn)
        btn_box.addWidget(self.cancel_btn)
        layout.addRow(btn_box)


class AddRuleDialog(BaseFramelessDialog):
    def __init__(self, channels: List[str], parent=None, default_title: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Add Auto-Record Rule")
        self.setMinimumWidth(380)
        layout = QFormLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)

        header_lbl = QLabel("<b>Add Auto-Record Rule</b>")
        header_lbl.setStyleSheet("font-size: 15px; color: #ffffff; margin-bottom: 6px;")
        layout.addRow(header_lbl)

        self.keyword_input = QLineEdit(default_title)
        self.channel_combo = ThemedComboBox()
        self.channel_combo.addItem("All")
        self.channel_combo.addItems(channels)

        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(0, 180)
        self.buffer_spin.setSpecialValueText("0 (Auto / Default)")
        self.buffer_spin.setSuffix(" min")
        self.buffer_spin.setValue(0)

        layout.addRow("Show Keyword / Title:", self.keyword_input)
        layout.addRow("Channel:", self.channel_combo)
        layout.addRow("Custom End Buffer:", self.buffer_spin)

        btn_box = QHBoxLayout()
        self.ok_btn = QPushButton("Save Rule")
        self.ok_btn.setObjectName("primaryActionBtn")
        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(self.ok_btn)
        btn_box.addWidget(self.cancel_btn)
        layout.addRow(btn_box)


class EditRuleDialog(BaseFramelessDialog):
    def __init__(self, channels: List[str], rule_id: str, keyword: str, channel: str, enabled: bool, buffer_mins: Optional[int] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Auto-Record Rule")
        self.setMinimumWidth(380)
        layout = QFormLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)

        header_lbl = QLabel("<b>Edit Auto-Record Rule</b>")
        header_lbl.setStyleSheet("font-size: 15px; color: #ffffff; margin-bottom: 6px;")
        layout.addRow(header_lbl)

        self.rule_id_lbl = QLabel(f"<b>{rule_id}</b>")
        self.keyword_input = QLineEdit(keyword)
        self.channel_combo = ThemedComboBox()
        self.channel_combo.addItem("All")
        self.channel_combo.addItems(channels)
        idx = self.channel_combo.findText(channel)
        if idx >= 0:
            self.channel_combo.setCurrentIndex(idx)
        else:
            self.channel_combo.setCurrentText(channel)

        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(0, 180)
        self.buffer_spin.setSpecialValueText("0 (Auto / Default)")
        self.buffer_spin.setSuffix(" min")
        self.buffer_spin.setValue(buffer_mins if (buffer_mins is not None and buffer_mins > 0) else 0)

        self.enabled_check = QCheckBox("Enable Rule")
        self.enabled_check.setChecked(enabled)

        layout.addRow("Rule ID:", self.rule_id_lbl)
        layout.addRow("Show Keyword / Title:", self.keyword_input)
        layout.addRow("Channel:", self.channel_combo)
        layout.addRow("Custom End Buffer:", self.buffer_spin)
        layout.addRow("Status:", self.enabled_check)

        btn_box = QHBoxLayout()
        self.ok_btn = QPushButton("Update Rule")
        self.ok_btn.setObjectName("primaryActionBtn")
        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(self.ok_btn)
        btn_box.addWidget(self.cancel_btn)
        layout.addRow(btn_box)


class ChannelSignalHealthDialog(BaseFramelessDialog):
    """
    Channel Signal Health & Reception Monitor dialog.
    Sequentially tests the digital TV lineup against live DVB frontend hardware,
    measuring digital carrier lock, signal strength %, SNR, and bit error status.
    """
    def __init__(self, channels: List[Dict[str, Any]], config_mgr: Optional[ConfigManager] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Channel Signal Health & Reception Monitor")
        self.resize(900, 780)
        self.channels = channels or []
        self.config_mgr = config_mgr
        self._worker: Optional[ChannelSignalScanWorker] = None
        self._results: Dict[str, Dict[str, Any]] = dict(self.config_mgr.channel_health) if self.config_mgr else {}
        self._aim_timer: Optional[QTimer] = None
        self._aim_channel: Optional[Dict[str, Any]] = None
        self._aim_peak_strength: float = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # Header description
        header_row = QHBoxLayout()
        desc_lbl = QLabel(
            "<b>Channel Signal Health & Reception Monitor</b><br>"
            "<span style='color: #8c98aa;'>Tests your digital TV lineup against physical DVB/ATSC tuner hardware, "
            "verifying digital carrier lock, reception signal strength, and SNR.</span>"
        )
        desc_lbl.setTextFormat(Qt.TextFormat.RichText)
        header_row.addWidget(desc_lbl, 1)

        close_x = QToolButton(self)
        close_x.setText("✕")
        close_x.setToolTip("Close")
        close_x.setCursor(Qt.CursorShape.PointingHandCursor)
        close_x.setStyleSheet(
            "QToolButton { background: transparent; color: #8c98aa; font-size: 13px; font-weight: bold; border: none; padding: 2px 6px; border-radius: 4px; }"
            "QToolButton:hover { color: #ffffff; background-color: rgba(255, 255, 255, 0.1); }"
        )
        close_x.clicked.connect(self.close)
        header_row.addWidget(close_x, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header_row)

        # Signal Reception Explanation Card
        explainer_box = QFrame()
        explainer_box.setObjectName("signalExplainerBox")
        explainer_box.setStyleSheet(
            "QFrame#signalExplainerBox {"
            "  background-color: rgba(255, 255, 255, 0.03);"
            "  border: 1px solid rgba(255, 255, 255, 0.08);"
            "  border-radius: 6px;"
            "  padding: 6px 10px;"
            "}"
        )
        explainer_layout = QVBoxLayout(explainer_box)
        explainer_layout.setContentsMargins(8, 6, 8, 6)
        explainer_layout.setSpacing(3)

        explainer_title = QLabel("<b>Signal Reception & Tuner Guide:</b>")
        explainer_title.setStyleSheet("font-size: 11px; color: #cbd5e1;")
        explainer_layout.addWidget(explainer_title)

        explainer_text = QLabel(
            "<span style='font-size: 11px; color: #94a3b8; line-height: 1.45;'>"
            "<span style='color: #38bdf8; font-weight: bold;'>● Kaffeine Requirement</span>: "
            "Kaffeine must be running to command the tuner hardware to switch frequencies. "
            "If Kaffeine is not running when scanning begins, it will automatically launch. "
            "You can choose whether Kaffeine runs hidden in the taskbar/tray or visible in DVR Settings ('Kaffeine Launch Mode'). "
            "If you close Kaffeine after scanning, DVR recordings will automatically restart it hidden if the option is set to hidden.<br>"
            "<span style='color: #4ade80; font-weight: bold;'>● Locked</span>: Full digital lock. Picture and sound decode cleanly for live viewing and DVR recordings.<br>"
            "<span style='color: #facc15; font-weight: bold;'>● Carrier (No Lock)</span>: Tower broadcast is detected, but the signal is too weak, noisy, or distorted to decode video packets. Re-aiming or boosting your antenna may turn this into a locked channel.<br>"
            "<span style='color: #f87171; font-weight: bold;'>● No Signal</span>: Zero broadcast transmission detected on this frequency (station out of range, obstructed, or off-air)."
            "</span>"
        )
        explainer_text.setTextFormat(Qt.TextFormat.RichText)
        explainer_text.setWordWrap(True)
        explainer_layout.addWidget(explainer_text)
        layout.addWidget(explainer_box)

        # Status & Progress row
        status_box = QHBoxLayout()
        self.status_lbl = QLabel("Ready to scan.")
        self.status_lbl.setStyleSheet("font-size: 12px; color: #cbd5e1;")
        status_box.addWidget(self.status_lbl, 1)

        self.summary_badge = QLabel("")
        self.summary_badge.setStyleSheet("font-size: 12px; font-weight: bold;")
        status_box.addWidget(self.summary_badge)
        layout.addLayout(status_box)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Live Antenna Aiming Meter Card (shown when aiming a channel)
        self.aim_card = QFrame()
        self.aim_card.setObjectName("aimCard")
        self.aim_card.setVisible(False)
        self.aim_card.setStyleSheet(
            "QFrame#aimCard {"
            "  background-color: rgba(30, 41, 59, 0.75);"
            "  border: 1px solid #38bdf8;"
            "  border-radius: 8px;"
            "  padding: 10px 14px;"
            "}"
        )
        aim_layout = QVBoxLayout(self.aim_card)
        aim_layout.setContentsMargins(10, 8, 10, 8)
        aim_layout.setSpacing(6)

        aim_top = QHBoxLayout()
        self.aim_title = QLabel("<b>Live Antenna Signal Adjuster</b>")
        self.aim_title.setStyleSheet("font-size: 13px; color: #38bdf8;")
        aim_top.addWidget(self.aim_title)
        aim_top.addStretch()

        self.aim_lock_badge = QLabel("● SEARCHING")
        self.aim_lock_badge.setStyleSheet("font-size: 12px; font-weight: bold; color: #facc15; padding: 2px 8px; border-radius: 4px; background: rgba(0,0,0,0.3);")
        aim_top.addWidget(self.aim_lock_badge)

        self.aim_done_btn = QPushButton("Done Aiming")
        self.aim_done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.aim_done_btn.setStyleSheet(
            "QPushButton { background: #0284c7; color: white; font-weight: bold; border-radius: 4px; padding: 4px 12px; }"
            "QPushButton:hover { background: #0369a1; }"
        )
        self.aim_done_btn.clicked.connect(self.stop_aiming)
        aim_top.addWidget(self.aim_done_btn)
        aim_layout.addLayout(aim_top)

        # Meter metrics row
        meter_row = QHBoxLayout()
        self.aim_strength_bar = QProgressBar()
        self.aim_strength_bar.setFixedHeight(18)
        self.aim_strength_bar.setRange(0, 100)
        self.aim_strength_bar.setValue(0)
        self.aim_strength_bar.setTextVisible(True)
        self.aim_strength_bar.setFormat("Strength: %p%")
        self.aim_strength_bar.setStyleSheet(
            "QProgressBar { border: 1px solid rgba(255,255,255,0.15); border-radius: 4px; text-align: center; font-weight: bold; background: rgba(0,0,0,0.4); color: white; }"
            "QProgressBar::chunk { background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #4ade80); border-radius: 3px; }"
        )
        meter_row.addWidget(self.aim_strength_bar, 2)

        self.aim_snr_lbl = QLabel("SNR: -- dB")
        self.aim_snr_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #cbd5e1; min-width: 110px;")
        meter_row.addWidget(self.aim_snr_lbl, 0)

        self.aim_peak_lbl = QLabel("Peak: 0.0%")
        self.aim_peak_lbl.setStyleSheet("font-size: 11px; color: #94a3b8; min-width: 90px;")
        meter_row.addWidget(self.aim_peak_lbl, 0)

        self.aim_ber_lbl = QLabel("BER: 0")
        self.aim_ber_lbl.setStyleSheet("font-size: 11px; color: #94a3b8; min-width: 70px;")
        meter_row.addWidget(self.aim_ber_lbl, 0)
        aim_layout.addLayout(meter_row)

        layout.addWidget(self.aim_card)

        # Table
        self.table = QTableWidget(len(self.channels), 6)
        self.table.setHorizontalHeaderLabels([
            "Channel Name", "Ch #", "Transponder / Frequency", "Lock Status", "Signal Strength", "SNR / Quality"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(2, 210)
        self.table.setColumnWidth(4, 150)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(lambda item: self.aim_antenna_selected_channel())
        layout.addWidget(self.table, 1)

        self._populate_table()
        self._update_summary_badge()

        # Action bar
        btn_bar = QHBoxLayout()
        self.scan_all_btn = QPushButton("Scan All Channels")
        self.scan_all_btn.setObjectName("primaryActionBtn")
        self.scan_all_btn.clicked.connect(self.scan_all_channels)
        btn_bar.addWidget(self.scan_all_btn)

        self.test_single_btn = QPushButton("Test Selected Channel")
        self.test_single_btn.clicked.connect(self.test_selected_channel)
        btn_bar.addWidget(self.test_single_btn)

        self.aim_antenna_btn = QPushButton("Aim Antenna (Live Meter)")
        self.aim_antenna_btn.setToolTip("Opens Kaffeine with live zero-latency video/audio and starts a fast live signal meter so you can adjust your antenna in real-time.")
        self.aim_antenna_btn.clicked.connect(self.aim_antenna_selected_channel)
        btn_bar.addWidget(self.aim_antenna_btn)

        self.stop_btn = QPushButton("Stop Scan")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scan)
        btn_bar.addWidget(self.stop_btn)

        self.quit_kaffeine_btn = QPushButton("Close Kaffeine")
        self.quit_kaffeine_btn.setToolTip("Close the background Kaffeine process now. It will automatically restart hidden if the option is set to hidden in DVR Settings.")
        self.quit_kaffeine_btn.clicked.connect(self._close_kaffeine_app)
        btn_bar.addWidget(self.quit_kaffeine_btn)

        btn_bar.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btn_bar.addWidget(self.close_btn)

        layout.addLayout(btn_bar)

    def _populate_table(self):
        for row, ch in enumerate(self.channels):
            name = ch.get("name", "").strip()
            num = str(ch.get("number") or "")
            tp = ch.get("transponder", "")
            if tp.startswith("A "):
                # Format ATSC frequency e.g. A 189028615 8VSB -> 189.0 MHz (8VSB)
                parts = tp.split()
                if len(parts) >= 3:
                    try:
                        freq_mhz = round(int(parts[1]) / 1000000.0, 1)
                        tp_fmt = f"{freq_mhz} MHz ({parts[2]})"
                    except Exception:
                        tp_fmt = tp
                else:
                    tp_fmt = tp
            else:
                tp_fmt = tp

            item_name = QTableWidgetItem(name)
            item_name.setData(Qt.ItemDataRole.UserRole, ch)
            item_num = QTableWidgetItem(num)
            item_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_tp = QTableWidgetItem(tp_fmt)

            self.table.setItem(row, 0, item_name)
            self.table.setItem(row, 1, item_num)
            self.table.setItem(row, 2, item_tp)

            # Check if previous metrics exist
            metrics = self._results.get(name)
            self._update_row_metrics(row, metrics)

    def _update_row_metrics(self, row: int, metrics: Optional[Dict[str, Any]]):
        if not metrics:
            item_status = QTableWidgetItem("Untested")
            item_status.setToolTip("Channel has not been scanned yet. Click 'Scan All Channels' or 'Test Selected Channel'.")
            item_status.setForeground(QColor("#94a3b8"))
            item_strength = QTableWidgetItem("--")
            item_quality = QTableWidgetItem("--")
        else:
            locked = metrics.get("locked", False)
            has_sig = metrics.get("has_signal", False) or metrics.get("has_carrier", False)
            pct = metrics.get("strength_pct", 0.0)
            snr = metrics.get("snr_db", 0.0)
            status_hex = metrics.get("status_hex", "")
            quality = metrics.get("quality_label", "No Signal")

            if locked:
                item_status = QTableWidgetItem(f"Locked ({status_hex})" if status_hex else "Locked")
                item_status.setToolTip("Full digital lock acquired. Transport stream decodes cleanly with video and audio.")
                item_status.setForeground(QColor("#4ade80"))
                item_strength = QTableWidgetItem(f"{pct:.1f}%")
                item_strength.setForeground(QColor("#4ade80") if pct >= 40.0 else QColor("#facc15"))
                item_quality = QTableWidgetItem(f"{snr:.1f} dB SNR - {quality}")
                item_quality.setForeground(QColor("#4ade80") if quality in ("Excellent", "Good") else QColor("#facc15"))
            elif has_sig:
                item_status = QTableWidgetItem("Carrier (No Lock)")
                item_status.setToolTip("Broadcast transmission detected from tower, but signal is too weak/noisy to decode video. Antenna re-aiming may help.")
                item_status.setForeground(QColor("#facc15"))
                item_strength = QTableWidgetItem(f"{pct:.1f}%")
                item_quality = QTableWidgetItem(f"{quality}")
                item_quality.setForeground(QColor("#facc15"))
            else:
                item_status = QTableWidgetItem("No Signal")
                item_status.setToolTip("No broadcast transmission detected on this frequency (tower out of range, obstructed, or off-air).")
                item_status.setForeground(QColor("#f87171"))
                item_strength = QTableWidgetItem("0.0%")
                item_strength.setForeground(QColor("#f87171"))
                item_quality = QTableWidgetItem("Offline")
                item_quality.setForeground(QColor("#f87171"))

        item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item_strength.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        self.table.setItem(row, 3, item_status)
        self.table.setItem(row, 4, item_strength)
        self.table.setItem(row, 5, item_quality)

    def _update_summary_badge(self):
        total = len(self.channels)
        locked_cnt = sum(1 for m in self._results.values() if m.get("locked"))
        carrier_cnt = sum(1 for m in self._results.values() if not m.get("locked") and (m.get("has_signal") or m.get("has_carrier")))
        dead_cnt = sum(1 for m in self._results.values() if not m.get("locked") and not m.get("has_signal") and not m.get("has_carrier"))
        if self._results:
            self.summary_badge.setText(
                f"<span style='color: #4ade80;'>● {locked_cnt} Locked</span>  |  "
                f"<span style='color: #facc15;'>● {carrier_cnt} Weak</span>  |  "
                f"<span style='color: #f87171;'>● {dead_cnt} No Signal</span>  |  "
                f"<span style='color: #94a3b8;'>Total: {total}</span>"
            )
        else:
            self.summary_badge.setText(f"<span style='color: #94a3b8;'>Total: {total} channels</span>")

    def aim_antenna_selected_channel(self):
        """Open Kaffeine live and start high-frequency signal strength meter for antenna aiming."""
        if self._worker and self._worker.isRunning():
            return

        row = self.table.currentRow()
        if row < 0 or row >= len(self.channels):
            self.status_lbl.setText("Select a channel first, then click 'Aim Antenna (Live Meter)' or double-click.")
            return

        ch = self.channels[row]
        ch_name = ch.get("name", "").strip()
        if not ch_name:
            return

        self._aim_channel = ch
        self._aim_peak_strength = 0.0

        # 1. Update UI to aiming mode
        self.aim_title.setText(f"<b>Live Antenna Adjuster — Tuning {ch_name}...</b>")
        self.aim_strength_bar.setValue(0)
        self.aim_snr_lbl.setText("SNR: -- dB")
        self.aim_peak_lbl.setText("Peak: 0.0%")
        self.aim_ber_lbl.setText("BER: 0")
        self.aim_lock_badge.setText("● TUNING")
        self.aim_lock_badge.setStyleSheet("font-size: 12px; font-weight: bold; color: #38bdf8; padding: 2px 8px; border-radius: 4px; background: rgba(0,0,0,0.3);")
        self.aim_card.setVisible(True)

        self.scan_all_btn.setEnabled(False)
        self.test_single_btn.setEnabled(False)
        self.aim_antenna_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.status_lbl.setText(f"Aiming antenna for {ch_name}. Watch live video in Kaffeine and adjust antenna for peak signal.")

        # 2. Instruct Kaffeine to tune to channel and unminimize/raise window for live zero-latency feedback
        from .dbus_client import KaffeineDbusClient
        client = KaffeineDbusClient()
        if not client.is_running():
            client.launch_kaffeine(mode="normal")
        client.tune_channel(ch_name, raise_window=True, view_mode="normal")

        # 3. Start high-frequency signal meter polling (every 120ms)
        if self._aim_timer is None:
            self._aim_timer = QTimer(self)
            self._aim_timer.timeout.connect(self._on_aim_timer_tick)
        self._aim_timer.start(120)

    def _on_aim_timer_tick(self):
        """Read instantaneous hardware metrics and update live aiming meter."""
        from .signal_scanner import DvbSignalReader
        metrics = DvbSignalReader.read_metrics()
        locked = metrics.get("locked", False)
        has_sig = metrics.get("has_signal", False) or metrics.get("has_carrier", False)
        pct = metrics.get("strength_pct", 0.0)
        snr = metrics.get("snr_db", 0.0)
        ber = metrics.get("ber", 0)

        if pct > self._aim_peak_strength:
            self._aim_peak_strength = pct

        ch_name = self._aim_channel.get("name", "") if self._aim_channel else ""
        self.aim_title.setText(f"<b>Live Antenna Adjuster — {ch_name}</b>")
        self.aim_strength_bar.setValue(int(round(pct)))
        self.aim_snr_lbl.setText(f"SNR: {snr:.1f} dB")
        self.aim_peak_lbl.setText(f"Peak: {self._aim_peak_strength:.1f}%")
        self.aim_ber_lbl.setText(f"BER: {ber}")

        if locked:
            self.aim_lock_badge.setText("● LOCKED")
            self.aim_lock_badge.setStyleSheet("font-size: 12px; font-weight: bold; color: #4ade80; padding: 2px 8px; border-radius: 4px; background: rgba(74, 222, 128, 0.15);")
            self.aim_strength_bar.setStyleSheet(
                "QProgressBar { border: 1px solid rgba(74, 222, 128, 0.4); border-radius: 4px; text-align: center; font-weight: bold; background: rgba(0,0,0,0.4); color: white; }"
                "QProgressBar::chunk { background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #4ade80); border-radius: 3px; }"
            )
        elif has_sig:
            self.aim_lock_badge.setText("● CARRIER (NO LOCK)")
            self.aim_lock_badge.setStyleSheet("font-size: 12px; font-weight: bold; color: #facc15; padding: 2px 8px; border-radius: 4px; background: rgba(250, 204, 21, 0.15);")
            self.aim_strength_bar.setStyleSheet(
                "QProgressBar { border: 1px solid rgba(250, 204, 21, 0.4); border-radius: 4px; text-align: center; font-weight: bold; background: rgba(0,0,0,0.4); color: white; }"
                "QProgressBar::chunk { background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d97706, stop:1 #facc15); border-radius: 3px; }"
            )
        else:
            self.aim_lock_badge.setText("● NO SIGNAL")
            self.aim_lock_badge.setStyleSheet("font-size: 12px; font-weight: bold; color: #f87171; padding: 2px 8px; border-radius: 4px; background: rgba(248, 113, 113, 0.15);")
            self.aim_strength_bar.setStyleSheet(
                "QProgressBar { border: 1px solid rgba(248, 113, 113, 0.4); border-radius: 4px; text-align: center; font-weight: bold; background: rgba(0,0,0,0.4); color: white; }"
                "QProgressBar::chunk { background-color: #ef4444; border-radius: 3px; }"
            )

        # Update table row with latest live sample
        if self._aim_channel:
            metrics["channel_name"] = ch_name
            metrics["channel_number"] = self._aim_channel.get("number")
            metrics["transponder"] = self._aim_channel.get("transponder", "")
            metrics["scanned_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._on_channel_result(ch_name, metrics)

    def stop_aiming(self):
        """Stop live aiming mode, silence Kaffeine, and minimize according to configured mode."""
        if self._aim_timer and self._aim_timer.isActive():
            self._aim_timer.stop()

        self.aim_card.setVisible(False)
        self.scan_all_btn.setEnabled(True)
        self.test_single_btn.setEnabled(True)
        self.aim_antenna_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        ch_name = self._aim_channel.get("name", "") if self._aim_channel else "channel"
        self.status_lbl.setText(f"Antenna aiming completed for {ch_name}. Peak signal: {self._aim_peak_strength:.1f}%.")
        self._aim_channel = None

        # Stop live playback
        self._stop_kaffeine_playback()

        # Minimize Kaffeine if configured launch mode is taskbar or tray
        try:
            from .dbus_client import KaffeineDbusClient
            from .config import ConfigManager
            cfg = ConfigManager()
            if cfg.launch_mode in ("taskbar", "tray"):
                KaffeineDbusClient().minimize_kaffeine(mode=cfg.launch_mode)
        except Exception:
            pass

    def scan_all_channels(self):
        if self._worker and self._worker.isRunning():
            return
        self.stop_aiming()
        self._start_scan(self.channels)

    def test_selected_channel(self):
        if self._worker and self._worker.isRunning():
            return
        self.stop_aiming()
        row = self.table.currentRow()
        if row < 0 or row >= len(self.channels):
            return
        ch = self.channels[row]
        self._start_scan([ch])

    def _start_scan(self, channels_to_scan: List[Dict[str, Any]]):
        self.scan_all_btn.setEnabled(False)
        self.test_single_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setRange(0, len(channels_to_scan))
        self.progress_bar.setValue(0)

        self._worker = ChannelSignalScanWorker(channels_to_scan, parent=self)
        self._worker.channel_started.connect(self._on_channel_started)
        self._worker.channel_result.connect(self._on_channel_result)
        self._worker.scan_progress.connect(self._on_scan_progress)
        self._worker.scan_finished.connect(self._on_scan_finished)
        self._worker.scan_error.connect(self._on_scan_error)
        self._worker.start()

    def _on_channel_started(self, ch_name: str, current: int, total: int):
        self.status_lbl.setText(f"Tuning and measuring {ch_name} ({current} of {total})...")

    def _on_channel_result(self, ch_name: str, metrics: Dict[str, Any]):
        self._results[ch_name] = metrics
        # Find row in table
        for row, ch in enumerate(self.channels):
            if ch.get("name", "").strip() == ch_name:
                self._update_row_metrics(row, metrics)
                break
        self._update_summary_badge()
        if self.config_mgr:
            self.config_mgr.channel_health = self._results

    def _on_scan_progress(self, current: int, total: int):
        self.progress_bar.setValue(current)

    def _on_scan_finished(self, results: Dict[str, Any]):
        self.status_lbl.setText("Scan completed. All background playback stopped.")
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.scan_all_btn.setEnabled(True)
        self.test_single_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._stop_kaffeine_playback()
        self._worker = None

    def _on_scan_error(self, err_msg: str):
        self.status_lbl.setText(f"Scanner notice: {err_msg}")

    def stop_scan(self):
        if self._worker and self._worker.isRunning():
            self.status_lbl.setText("Stopping scan...")
            self._worker.request_stop()
            self._worker.wait(1500)
            self._stop_kaffeine_playback()
            self.scan_all_btn.setEnabled(True)
            self.test_single_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def _stop_kaffeine_playback(self):
        try:
            import dbus
            bus = dbus.SessionBus()
            proxy = bus.get_object("org.mpris.kaffeine", "/Player")
            iface = dbus.Interface(proxy, "org.freedesktop.MediaPlayer")
            iface.Stop()
        except Exception:
            pass

    def _close_kaffeine_app(self):
        """Close the running Kaffeine application process."""
        self.stop_scan()
        self._stop_kaffeine_playback()
        try:
            import dbus
            bus = dbus.SessionBus()
            app_proxy = bus.get_object("org.kde.kaffeine", "/")
            app_iface = dbus.Interface(app_proxy, "org.freedesktop.MediaPlayer")
            app_iface.Quit()
            self.status_lbl.setText("Kaffeine closed. It will automatically restart hidden if the option is set to hidden.")
        except Exception:
            try:
                import subprocess
                subprocess.run(["pkill", "-x", "kaffeine"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.status_lbl.setText("Kaffeine closed. It will automatically restart hidden if the option is set to hidden.")
            except Exception as e:
                self.status_lbl.setText(f"Could not close Kaffeine: {e}")

    def closeEvent(self, event):
        self.stop_aiming()
        self.stop_scan()
        self._stop_kaffeine_playback()
        super().closeEvent(event)

    def reject(self):
        self.stop_aiming()
        self.stop_scan()
        self._stop_kaffeine_playback()
        super().reject()


class RetentionCleanupDialog(BaseFramelessDialog):
    """
    Compact confirmation dialog for manual retention cleanup.
    Provides a concise prompt with an option to ignore retention policy and delete all recordings.
    """
    def __init__(
        self,
        folder: str,
        retention_days: int,
        min_free_gb: int,
        disk_usage: Optional[dict] = None,
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Confirm Retention Cleanup")
        self.setFixedWidth(440)

        self.retention_days = retention_days
        self.min_free_gb = min_free_gb
        self.policy_active = (retention_days > 0 or min_free_gb > 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        # Header with icon and concise question
        header = QHBoxLayout()
        header.setSpacing(12)
        warn_icon = QLabel()
        std_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
        warn_icon.setPixmap(std_icon.pixmap(28, 28))
        header.addWidget(warn_icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        msg_lbl = QLabel("<b style='font-size: 13px; color: #ffffff;'>Run retention cleanup on recordings?</b>")
        path_lbl = QLabel(f"<span style='color: #8c98aa; font-size: 11px;'>{folder}</span>")
        path_lbl.setWordWrap(True)
        text_col.addWidget(msg_lbl)
        text_col.addWidget(path_lbl)
        header.addLayout(text_col, 1)
        layout.addLayout(header)

        # Checkbox controls
        opts_col = QVBoxLayout()
        opts_col.setSpacing(8)
        opts_col.setContentsMargins(40, 0, 0, 0)

        self.ignore_policy_cb = QCheckBox("Ignore retention policy and delete all")
        self.include_prot_cb = QCheckBox("Include protected recordings")
        self.include_prot_cb.setEnabled(False)
        self.include_prot_cb.setStyleSheet("color: #8c98aa;")

        opts_col.addWidget(self.ignore_policy_cb)
        opts_col.addWidget(self.include_prot_cb)
        layout.addLayout(opts_col)

        # Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        btn_box.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(self.cancel_btn)

        self.action_btn = QPushButton("Run Cleanup")
        self.action_btn.setObjectName("primaryActionBtn")
        self.action_btn.clicked.connect(self._on_action_clicked)
        btn_box.addWidget(self.action_btn)

        layout.addLayout(btn_box)

        # Connect toggles
        self.ignore_policy_cb.toggled.connect(self._update_ui_state)
        self._update_ui_state()

    def _update_ui_state(self):
        is_ignore = self.ignore_policy_cb.isChecked()
        self.include_prot_cb.setEnabled(is_ignore)
        if not is_ignore:
            self.include_prot_cb.setChecked(False)
            self.include_prot_cb.setStyleSheet("color: #8c98aa;")
            self.action_btn.setText("Run Cleanup")
            self.action_btn.setStyleSheet("")
            self.action_btn.setObjectName("primaryActionBtn")
        else:
            self.include_prot_cb.setStyleSheet("color: #e2e8f0;")
            self.action_btn.setText("Delete All")
            self.action_btn.setStyleSheet(
                "QPushButton { background-color: #dc2626; color: #ffffff; font-weight: bold; padding: 6px 14px; border-radius: 4px; }"
                "QPushButton:hover { background-color: #ef4444; }"
            )

    def _on_action_clicked(self):
        is_ignore = self.ignore_policy_cb.isChecked()
        if not is_ignore and not self.policy_active:
            QMessageBox.information(
                self,
                "Retention Policy Disabled",
                "Both the Retention Window (days) and Minimum Free Disk Space (GB) are set to 0.\n\n"
                "Please configure at least one retention policy rule or check 'Ignore retention policy and delete all'."
            )
            return

        if is_ignore and self.include_prot_cb.isChecked():
            confirm = QMessageBox.warning(
                self,
                "Confirm Deleting Protected Recordings",
                "You have selected to delete ALL recordings INCLUDING protected ones.\n\n"
                "Are you absolutely sure you want to proceed?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        self.accept()

    def get_cleanup_options(self) -> dict:
        return {
            "delete_all": self.ignore_policy_cb.isChecked(),
            "include_protected": self.include_prot_cb.isChecked() if self.ignore_policy_cb.isChecked() else False
        }


class HelpPopup(QFrame):
    """Clean popover displaying setting help text on click, dismissing on click outside."""
    _active_popup = None

    def __init__(self, text: str, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self._origin_widget: Optional[QWidget] = None
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: 500; line-height: 1.35; background: transparent;")
        lay.addWidget(lbl)
        self.setStyleSheet(
            "HelpPopup {"
            "  background-color: #1e293b;"
            "  border: 1.5px solid #4a8df5;"
            "  border-radius: 6px;"
            "}"
        )
        # Accurately compute needed width and height so box fits the text
        font = QFont(lbl.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Medium)
        fm = QFontMetrics(font)
        max_line_width = max((fm.horizontalAdvance(line) for line in text.splitlines()), default=200)
        content_width = min(400, max(220, max_line_width))
        text_rect = fm.boundingRect(QRect(0, 0, content_width, 10000), Qt.TextFlag.TextWordWrap, text)
        self.setFixedSize(content_width + 20, text_rect.height() + 16)

    _last_dismiss_widget = None
    _last_dismiss_time = 0.0

    @classmethod
    def show_for_widget(cls, widget: QWidget, text: str):
        if cls._active_popup:
            is_same = getattr(cls._active_popup, "_origin_widget", None) == widget
            cls.hide_active()
            if is_same:
                return

        win = widget.window()
        popup = cls(text, win)
        popup._origin_widget = widget
        cls._active_popup = popup
        if hasattr(widget, "set_active"):
            widget.set_active(True)

        app = QApplication.instance()
        if app:
            app.installEventFilter(popup)

        # Position just below the badge, offset slightly to the right
        pos = widget.mapToGlobal(QPoint(widget.width() // 2, widget.height() + 4))
        popup.move(pos)
        popup.show()

    @classmethod
    def hide_active(cls):
        if cls._active_popup:
            try:
                origin = getattr(cls._active_popup, "_origin_widget", None)
                if origin and hasattr(origin, "set_active"):
                    origin.set_active(False)
                app = QApplication.instance()
                if app:
                    app.removeEventFilter(cls._active_popup)
                cls._active_popup.close()
                cls._active_popup.deleteLater()
            except Exception:
                pass
            cls._active_popup = None

    def eventFilter(self, watched, event):
        # Automatically close popup if user switches away to another application or window
        if event.type() in (
            QEvent.Type.ApplicationDeactivate,
            QEvent.Type.WindowDeactivate,
            QEvent.Type.ActivationChange
        ):
            HelpPopup.hide_active()
            return False

        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            if watched != self:
                origin = getattr(self, "_origin_widget", None)
                # Check if click was directed to the badge that opened this popup
                is_on_origin = (watched == origin)
                if not is_on_origin and origin and hasattr(event, "globalPosition"):
                    gp = event.globalPosition().toPoint()
                    is_on_origin = origin.rect().contains(origin.mapFromGlobal(gp))
                elif not is_on_origin and origin and hasattr(event, "globalPos"):
                    gp = event.globalPos()
                    is_on_origin = origin.rect().contains(origin.mapFromGlobal(gp))

                if is_on_origin:
                    HelpPopup._last_dismiss_widget = origin
                    HelpPopup._last_dismiss_time = time.monotonic()

                HelpPopup.hide_active()
        return super().eventFilter(watched, event)


class HelpBadge(QLabel):
    """Circular '?' badge that displays help info popover on click."""
    def __init__(self, tooltip_text: str, parent=None):
        super().__init__("?", parent)
        self._tooltip_text = tooltip_text
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFixedSize(18, 18)
        self.setStyleSheet(
            "QLabel {"
            "  color: #ffffff;"
            "  background-color: #1e293b;"
            "  border: 1px solid #4a5568;"
            "  border-radius: 9px;"
            "  font-weight: bold;"
            "  font-size: 11px;"
            "  padding: 0px;"
            "  margin: 0px;"
            "  qproperty-alignment: AlignCenter;"
            "}"
            "QLabel:hover {"
            "  color: #ffffff;"
            "  background-color: #2d6cd4;"
            "  border: 1px solid #4a8df5;"
            "}"
            "QLabel[active=\"true\"] {"
            "  color: #ffffff;"
            "  background-color: #2d6cd4;"
            "  border: 1px solid #4a8df5;"
            "}"
        )

    def set_active(self, active: bool):
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().adjusted(-2, -2, 2, 2).contains(event.pos()):
            # If this click just dismissed this badge's popup via eventFilter, do not immediately reopen
            now = time.monotonic()
            if HelpPopup._last_dismiss_widget == self and (now - HelpPopup._last_dismiss_time) < 0.4:
                HelpPopup._last_dismiss_widget = None
                event.accept()
                return
            HelpPopup.show_for_widget(self, self._tooltip_text)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


def make_setting_label(title: str, tooltip_text: str) -> QWidget:
    """Create a composite widget containing a white '?' help badge followed by the label title."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    badge = HelpBadge(tooltip_text)
    lbl = QLabel(title)
    lbl.setStyleSheet("font-size: 13px; color: #e2e8f0;")
    lay.addWidget(badge)
    lay.addWidget(lbl)
    lay.addStretch()
    return w


class AdjustBufferDialog(BaseFramelessDialog):
    """
    Dialog for adjusting recording end buffer with a dedicated 2-line title container.
    Guarantees a clean 2-line layout without clipping and truncates to 2 lines max with ellipsis.
    """
    def __init__(self, title_text: str, current_buffer: int = 0, parent=None):
        super().__init__(parent)
        self.raw_title = title_text
        self.setWindowTitle("Adjust Recording Buffer")
        self.setMinimumWidth(440)

        form = QFormLayout(self)
        form.setContentsMargins(18, 16, 18, 16)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        header_lbl = QLabel("<b>Adjust Recording Buffer</b>")
        header_lbl.setStyleSheet("font-size: 15px; color: #ffffff; margin-bottom: 6px;")
        form.addRow(header_lbl)

        # 2-line title label
        self.title_lbl = QLabel()
        self.title_lbl.setWordWrap(True)
        # Calculate line height based on bold font metrics
        title_font = QFont(self.font())
        title_font.setBold(True)
        self.title_lbl.setFont(title_font)
        fm = QFontMetrics(title_font)
        line_h = fm.lineSpacing()
        two_line_h = line_h * 2 + 4
        self.title_lbl.setMinimumHeight(two_line_h)
        self.title_lbl.setMaximumHeight(two_line_h)
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.addRow("Show:", self.title_lbl)

        # Spinbox
        self.buf_spin = QSpinBox()
        self.buf_spin.setRange(0, 180)
        self.buf_spin.setValue(current_buffer)
        self.buf_spin.setSuffix(" minutes")
        form.addRow("End Buffer:", self.buf_spin)

        # Presets
        presets_box = QHBoxLayout()
        presets_box.setSpacing(6)
        for m in [0, 15, 30, 45, 60]:
            btn = QPushButton(f"+{m}m" if m > 0 else "None")
            btn.setStyleSheet("padding: 4px 6px; font-size: 12px;")
            btn.clicked.connect(lambda _, val=m: self.buf_spin.setValue(val))
            presets_box.addWidget(btn)
        form.addRow("Presets:", presets_box)

        # Buttons
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.ok_btn = QPushButton("Save Buffer")
        self.ok_btn.setObjectName("primaryActionBtn")
        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self.ok_btn)
        btns.addWidget(self.cancel_btn)
        form.addRow(btns)

        self._update_elided_title()

    def _update_elided_title(self):
        fm = self.title_lbl.fontMetrics()
        avail_w = max(100, self.title_lbl.width() if self.title_lbl.width() > 0 else self.width() - 80)
        
        words = self.raw_title.split()
        if not words:
            self.title_lbl.setText("")
            return

        line1_words = []
        rem_words = []
        for i, w in enumerate(words):
            test_line = " ".join(line1_words + [w])
            if fm.horizontalAdvance(test_line) <= avail_w:
                line1_words.append(w)
            else:
                rem_words = words[i:]
                break

        if not line1_words and words:
            line1_words = [words[0]]
            rem_words = words[1:]

        line1_text = " ".join(line1_words)

        if not rem_words:
            # Fits on 1 line: display line 1
            self.title_lbl.setText(f"<b>{line1_text}</b>")
        else:
            # 2nd line: elide if longer than available width
            rem_text = " ".join(rem_words)
            elided_line2 = fm.elidedText(rem_text, Qt.TextElideMode.ElideRight, avail_w)
            self.title_lbl.setText(f"<b>{line1_text}<br>{elided_line2}</b>")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided_title()

    def get_buffer(self) -> int:
        return self.buf_spin.value()


class CollapsibleHeaderButton(QToolButton):
    def __init__(self, subtitle: str = "", parent=None):
        super().__init__(parent)
        self._subtitle = subtitle

    def sizeHint(self) -> QSize:
        sh = super().sizeHint()
        if self._subtitle:
            sub_w = self.fontMetrics().horizontalAdvance(self._subtitle) + 24
            return QSize(sh.width() + sub_w, sh.height())
        return sh

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._subtitle:
            painter = QPainter(self)
            painter.setPen(QColor("#788496"))
            font = QFont(self.font())
            font.setItalic(True)
            font.setBold(False)
            font.setPointSize(10)
            painter.setFont(font)

            fm = self.fontMetrics()
            text_w = fm.horizontalAdvance(self.text())
            x = 12 + 16 + text_w + 14
            y = (self.height() + painter.fontMetrics().ascent() - painter.fontMetrics().descent()) // 2
            painter.drawText(x, y, self._subtitle)
            painter.end()


class CollapsibleSection(QWidget):
    def __init__(self, title: str = "", initially_expanded: bool = False, parent=None, subtitle: str = ""):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 4, 0, 4)
        self.main_layout.setSpacing(4)

        self.header_layout = QHBoxLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(8)

        self.toggle_btn = CollapsibleHeaderButton(subtitle=subtitle)
        self.toggle_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toggle_btn.setStyleSheet(
            "QToolButton { "
            "  border: 1px solid #333a4c; "
            "  border-radius: 5px; "
            "  background-color: #1e2333; "
            "  color: #d3dae3; "
            "  font-weight: bold; "
            "  font-size: 12px; "
            "  padding: 8px 12px; "
            "  text-align: left; "
            "} "
            "QToolButton:hover { "
            "  background-color: #262c3f; "
            "  border-color: #55a84c; "
            "  color: #ffffff; "
            "}"
        )
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow if initially_expanded else Qt.ArrowType.RightArrow)
        self.toggle_btn.setText("  " + title)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(initially_expanded)
        self.toggle_btn.clicked.connect(self.on_toggled)
        self.header_layout.addWidget(self.toggle_btn)
        self.main_layout.addLayout(self.header_layout)

        self.content_area = QFrame()
        self.content_area.setFrameShape(QFrame.Shape.StyledPanel)
        self.content_area.setStyleSheet(
            "QFrame#collapsibleContent { "
            "  border: 1px solid #2a3142; "
            "  border-radius: 5px; "
            "  background-color: #1a1e2b; "
            "  padding: 8px; "
            "}"
        )
        self.content_area.setObjectName("collapsibleContent")
        self.content_area.setVisible(initially_expanded)
        self.main_layout.addWidget(self.content_area)

    def addHeaderWidget(self, widget: QWidget):
        self.header_layout.addWidget(widget)

    def setContentLayout(self, layout):
        self.content_area.setLayout(layout)

    def on_toggled(self, checked: bool):
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.content_area.setVisible(checked)
        if checked:
            # Let the layout recalculate geometry, then ensure content is fully visible in parent scroll area
            QTimer.singleShot(60, self.scroll_into_view)

    def scroll_into_view(self):
        parent = self.parentWidget()
        scroll_area = None
        while parent:
            if isinstance(parent, QScrollArea):
                scroll_area = parent
                break
            parent = parent.parentWidget()
        if scroll_area:
            scroll_area.ensureWidgetVisible(self.content_area, 0, 15)


class NoWheelEventFilter(QObject):
    """
    Prevents mouse wheel scrolling from unintentionally modifying values in
    QSpinBox, QComboBox, and QSlider input controls while scrolling pages.
    If the widget is inside a QScrollArea, the wheel event is passed to the
    enclosing scroll area viewport so the page scrolls smoothly instead.
    """
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            if isinstance(obj, (QComboBox, QAbstractSpinBox, QSlider)):
                # If combo popup dropdown is open, allow scrolling through options
                if isinstance(obj, QComboBox) and obj.view() and obj.view().isVisible():
                    return False

                # Pass the wheel event to any enclosing QScrollArea viewport
                parent = obj.parentWidget()
                while parent and not isinstance(parent, QScrollArea):
                    parent = parent.parentWidget()

                if parent and isinstance(parent, QScrollArea):
                    parent_vp = parent.viewport()
                    mapped_pos = obj.mapTo(parent_vp, event.position().toPoint())
                    forwarded_event = QWheelEvent(
                        QPointF(mapped_pos),
                        event.globalPosition(),
                        event.pixelDelta(),
                        event.angleDelta(),
                        event.buttons(),
                        event.modifiers(),
                        event.phase(),
                        event.inverted()
                    )
                    QApplication.sendEvent(parent_vp, forwarded_event)
                return True
        return super().eventFilter(obj, event)


class TableViewportResizeFilter(QObject):
    """
    Listens for resize events on table viewports to dynamically recalculate
    and stretch column widths to match the available table geometry.
    """
    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.callback = callback
        self._busy = False

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            if not self._busy:
                self._busy = True
                try:
                    self.callback()
                finally:
                    self._busy = False
        return super().eventFilter(obj, event)


class OpacitySliderPopup(QFrame):
    """
    Compact popup displaying an opacity percentage label, interactive horizontal slider,
    and quick preset buttons (25%, 50%, 75%, 100%). Dismisses on outside click, origin toggle, or Escape.
    """
    _active_popup = None

    def __init__(self, current_val: int = 100, on_change=None, parent=None, tokens=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self._origin_widget = None
        self._on_change = on_change
        tokens = tokens or {}
        bg_panel = tokens.get("bg_panel", "#1a2233")
        border_col = tokens.get("accent_primary", "#38bdf8")
        accent = tokens.get("accent_hover", "#0284c7")
        text_col = tokens.get("text_primary", "#f1f5f9")

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setObjectName("opacitySliderPopup")
        self.setStyleSheet(f"""
            QFrame#opacitySliderPopup {{
                background-color: {bg_panel};
                border: 1.5px solid {border_col};
                border-radius: 8px;
            }}
            QLabel {{
                color: {text_col};
                font-size: 12px;
                font-weight: bold;
                background: transparent;
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: #334155;
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {border_col};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: #ffffff;
                border: 2px solid {border_col};
                width: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {accent};
            }}
            QPushButton.quick-preset {{
                background-color: #242c3d;
                border: 1px solid #3c465d;
                border-radius: 4px;
                color: #cbd5e1;
                font-size: 11px;
                font-weight: 500;
                padding: 2px 6px;
                min-width: 32px;
            }}
            QPushButton.quick-preset:hover {{
                background-color: #334155;
                border-color: {border_col};
                color: #ffffff;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        self.lbl = QLabel(f"Time Line Opacity: {current_val}%")
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(10, 100)
        self.slider.setSingleStep(5)
        self.slider.setPageStep(10)
        self.slider.setValue(current_val)
        self.slider.setFixedWidth(200)
        lay.addWidget(self.slider)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        for pct in (25, 50, 75, 100):
            p_btn = QPushButton(f"{pct}%")
            p_btn.setProperty("class", "quick-preset")
            p_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            p_btn.clicked.connect(lambda chk=False, v=pct: self.slider.setValue(v))
            preset_row.addWidget(p_btn)
        lay.addLayout(preset_row)

        self.slider.valueChanged.connect(self._handle_value_changed)

    def _handle_value_changed(self, val: int):
        self.lbl.setText(f"Time Line Opacity: {val}%")
        if self._on_change:
            self._on_change(val)

    @classmethod
    def show_for_widget(cls, widget: QWidget, current_val: int, on_change, tokens=None):
        if cls._active_popup:
            is_same = getattr(cls._active_popup, "_origin_widget", None) == widget
            cls.hide_active()
            if is_same:
                return

        win = widget.window()
        popup = cls(current_val, on_change, win, tokens)
        popup._origin_widget = widget
        cls._active_popup = popup

        app = QApplication.instance()
        if app:
            app.installEventFilter(popup)

        pos = widget.mapToGlobal(QPoint(widget.width() // 2 - 110, widget.height() + 4))
        popup.move(pos)
        popup.show()

    @classmethod
    def hide_active(cls):
        if cls._active_popup:
            try:
                app = QApplication.instance()
                if app:
                    app.removeEventFilter(cls._active_popup)
                cls._active_popup.close()
                cls._active_popup.deleteLater()
            except Exception:
                pass
            cls._active_popup = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            OpacitySliderPopup.hide_active()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if event.type() in (
            QEvent.Type.ApplicationDeactivate,
            QEvent.Type.WindowDeactivate,
            QEvent.Type.ActivationChange
        ):
            OpacitySliderPopup.hide_active()
            return False

        if event.type() == QEvent.Type.MouseButtonPress:
            origin = getattr(self, "_origin_widget", None)
            gp = None
            if hasattr(event, "globalPosition"):
                gp = event.globalPosition().toPoint()
            elif hasattr(event, "globalPos"):
                gp = event.globalPos()

            if gp:
                if self.rect().contains(self.mapFromGlobal(gp)):
                    return False
                if origin and origin.rect().contains(origin.mapFromGlobal(gp)):
                    OpacitySliderPopup.hide_active()
                    return True

            OpacitySliderPopup.hide_active()

        return super().eventFilter(watched, event)


class NumberStepper(QFrame):
    """
    Horizontal stepper control with [-] [ Number Box ] [+] layout.
    Provides clear, easy-to-click decrement and increment buttons with auto-repeat,
    while keeping precise keyboard number typing and full QSpinBox API compatibility.
    """
    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("numberStepper")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        self._btn_minus = QPushButton("−")
        self._btn_minus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_minus.setAutoRepeat(True)
        self._btn_minus.setAutoRepeatDelay(400)
        self._btn_minus.setAutoRepeatInterval(80)

        self._spin = QSpinBox()
        self._spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._spin.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._btn_plus = QPushButton("+")
        self._btn_plus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_plus.setAutoRepeat(True)
        self._btn_plus.setAutoRepeatDelay(400)
        self._btn_plus.setAutoRepeatInterval(80)

        layout.addWidget(self._btn_minus)
        layout.addWidget(self._spin, 1)
        layout.addWidget(self._btn_plus)

        self._btn_minus.clicked.connect(self._step_down)
        self._btn_plus.clicked.connect(self._step_up)
        self._spin.valueChanged.connect(self.valueChanged.emit)

        self._spin.installEventFilter(self)
        line_edit = self._spin.lineEdit()
        if line_edit:
            line_edit.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self._spin or (self._spin.lineEdit() and watched is self._spin.lineEdit()):
            if event.type() == QEvent.Type.FocusIn:
                self.setProperty("focused", "true")
                self.style().unpolish(self)
                self.style().polish(self)
            elif event.type() == QEvent.Type.FocusOut:
                self.setProperty("focused", "false")
                self.style().unpolish(self)
                self.style().polish(self)
        return super().eventFilter(watched, event)

    def _step_down(self):
        self._spin.stepDown()
        line_edit = self._spin.lineEdit()
        if line_edit:
            line_edit.deselect()

    def _step_up(self):
        self._spin.stepUp()
        line_edit = self._spin.lineEdit()
        if line_edit:
            line_edit.deselect()

    def value(self) -> int:
        return self._spin.value()

    def setValue(self, val: int):
        self._spin.setValue(val)

    def setRange(self, minimum: int, maximum: int):
        self._spin.setRange(minimum, maximum)

    def setSingleStep(self, step: int):
        self._spin.setSingleStep(step)

    def singleStep(self) -> int:
        return self._spin.singleStep()

    def minimum(self) -> int:
        return self._spin.minimum()

    def maximum(self) -> int:
        return self._spin.maximum()

    def setSuffix(self, suffix: str):
        self._spin.setSuffix(suffix)

    def setPrefix(self, prefix: str):
        self._spin.setPrefix(prefix)

    def setSpecialValueText(self, text: str):
        self._spin.setSpecialValueText(text)

    def setToolTip(self, text: Optional[str]):
        super().setToolTip(text or "")
        self._spin.setToolTip(text or "")

    def spinBox(self) -> QSpinBox:
        return self._spin


def get_theme_chip_fixed_width(font: Optional[QFont] = None) -> int:
    """
    Calculate a set uniform width for theme pills based on the largest theme entry
    across Application Themes and Guide Themes, padded by a few characters.
    """
    names = [t["name"].split(" (")[0] for t in APP_THEMES.values()]
    names += [p["name"].split(" (")[0] for p in THEME_PRESETS.values()]
    names.append("Custom")
    longest_name = max(names, key=len)

    if font is not None:
        f = QFont(font)
    else:
        app = QApplication.instance()
        f = QFont(app.font() if app else QFont())

    # ThemeChip stylesheet enforces 11px bold font
    f.setPixelSize(11)
    f.setBold(True)
    fm = QFontMetrics(f)

    # Longest entry + pad a few characters (4 spaces)
    sample_text = f"  {longest_name}    "
    text_width = fm.horizontalAdvance(sample_text)
    # 10px circle dot icon + 6px icon margin + 20px button padding (10 left + 10 right) + 4px border/safety
    return text_width + 40


class ThemeChip(QPushButton):
    """
    Compact, pill-shaped button for selecting a theme.
    Displays a small circular accent dot and theme label, highlighted via border/background when selected.
    """
    chip_clicked = pyqtSignal(str)

    def __init__(self, key: str, display_name: str, dot_color: str, parent=None, fixed_width: Optional[int] = None):
        super().__init__(parent)
        self.key = key
        self.display_name = display_name
        self.short_name = display_name.split(" (")[0]
        self.dot_color = dot_color
        self._is_selected = False

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fixed_width = fixed_width if fixed_width is not None else get_theme_chip_fixed_width(self.font())
        self.setFixedSize(self.fixed_width, 28)
        self.clicked.connect(lambda: self.chip_clicked.emit(self.key))
        self._update_appearance()

    def set_dot_color(self, color: str):
        self.dot_color = color
        self._update_appearance()

    def set_selected(self, selected: bool):
        self._is_selected = selected
        self._update_appearance()

    def _update_appearance(self):
        # Generate 10x10 colored circle dot
        pix = QPixmap(10, 10)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(self.dot_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, 10, 10)
        p.end()
        self.setIcon(QIcon(pix))
        self.setIconSize(QSize(10, 10))

        self.setText(f"  {self.short_name}")
        if self._is_selected:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #1e293b;
                    color: #38bdf8;
                    border: 1.5px solid #38bdf8;
                    border-radius: 12px;
                    padding: 3px 10px;
                    font-size: 11px;
                    font-weight: bold;
                    text-align: left;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #141c28;
                    color: #cbd5e1;
                    border: 1px solid #2a3a50;
                    border-radius: 12px;
                    padding: 3px 10px;
                    font-size: 11px;
                    text-align: left;
                }
                QPushButton:hover {
                    background-color: #1e2a3c;
                    border-color: #38bdf8;
                    color: #f8fafc;
                }
            """)


def format_american_datetime(val: Any) -> str:
    """Format an ISO date string or datetime into friendly American format: Sat, Oct 10, 2026 at 7:30 PM."""
    if not val:
        return ""
    if isinstance(val, (int, float)):
        try:
            val = datetime.fromtimestamp(val)
        except Exception:
            return str(val)
    if isinstance(val, datetime):
        dt = val
    else:
        s = str(val).strip()
        for fmt in ("%Y-%m-%d %I:%M:%S %p", "%Y-%m-%d %I:%M %p", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except Exception:
                continue
        else:
            return s
    time_part = dt.strftime("%I:%M %p").lstrip("0") or "12:00 AM"
    return f"{dt.strftime('%a, %b %-d, %Y')} at {time_part}"


def format_american_datetime_short(val: Any) -> str:
    """Format date/time into standard American short notation: 10/10/2026 7:30 PM."""
    if not val:
        return ""
    if isinstance(val, (int, float)):
        try:
            val = datetime.fromtimestamp(val)
        except Exception:
            return str(val)
    if isinstance(val, datetime):
        dt = val
    else:
        s = str(val).strip()
        for fmt in ("%Y-%m-%d %I:%M:%S %p", "%Y-%m-%d %I:%M %p", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except Exception:
                continue
        else:
            return s
    time_part = dt.strftime("%I:%M %p").lstrip("0") or "12:00 AM"
    return f"{dt.strftime('%m/%d/%Y')} {time_part}"


def classify_guide_category(prog: Dict[str, Any]) -> str:
    """
    Classifies a program into 'sports', 'news', 'movies', or 'tvshows'.
    Color mapping:
    - Sports: Orange (#ffa028)
    - News: Blue (#4fc3f7)
    - Movies: Purple (#c084fc)
    - TV Shows: Green (#66bb6a)
    """
    title = (prog.get("show_title") or "").strip()
    title_lower = title.lower()
    ep = (prog.get("episode_title") or "").strip()
    ep_lower = ep.lower()
    summary = (prog.get("summary") or "").lower()

    # 1. Sports: sporting leagues, games, matches, and athletic events
    sports_kw = [
        "football", "nfl", "ncaa", "basketball", "nba", "wnba", "baseball", "mlb",
        "hockey", "nhl", "soccer", "premier league", "nascar", "racing", "pga",
        "golf", "tennis", "wrestling", "wwe", "ufc", "boxing", "sportswrap",
        "sports stars", "sports legends", "gametime", "kickoff", "postgame", "pregame",
        "scoreboard", "flag football", "college football", "college basketball",
        "usl championship", "volleyball", "championship wrestling", "tailgate",
        "sports tonight"
    ]
    if any(k in title_lower for k in sports_kw):
        return "sports"
    if any(k in ep_lower for k in ["premier league", "nfl", "mlb", "nba", " vs. ", " at "]) and (
        "football" in summary or "game" in summary or "soccer" in summary or "basketball" in summary or "baseball" in summary
    ):
        return "sports"

    # 2. News: news broadcasts, morning news, evening news, journalism, and current affairs
    news_kw = [
        "news", "newschannel", "eyewitness", "action news", "today", "good morning",
        "cbs mornings", "gma", "nightly news", "world news", "evening news", "meet the press",
        "face the nation", "this week", "60 minutes", "20/20", "dateline", "frontline",
        "pbs newshour", "sunrise", "roundup", "fox news", "cnn", "msnbc",
        "weather", "briefing", "state of the union", "morning express", "early today",
        "morning joe", "morning edition", "all things considered", "first look",
        "newsbeat", "newswatch", "newsnight", "inside edition"
    ]
    if any(k in title_lower for k in news_kw):
        return "news"

    # 3. Movies: explicit indicators or standalone feature film heuristics
    if (
        prog.get("_is_movie")
        or title_lower == "movie"
        or title_lower.startswith("movie:")
        or title_lower.startswith("film:")
        or title_lower.endswith(" (movie)")
        or "feature film" in summary
        or " motion picture" in summary
        or ("directed by" in summary or "stars as" in summary) and prog.get("runtime_mins", 0) >= 75 and not prog.get("season")
    ):
        return "movies"

    # Standalone feature films / documentaries (>=80 mins, no season/episode, not recurring news/sports)
    runtime = prog.get("runtime_mins") or 0
    if runtime >= 80 and not prog.get("season") and not ep:
        non_movie_words = [
            "news", "today", "morning", "football", "baseball", "basketball", "soccer",
            "hockey", "volleyball", "nascar", "pbr", "wrestling", "wwe", "voice", "dance",
            "awards", "survivor", "amazing race", "frontline", "masters", "lens", "pov",
            "reframed", "midsomer", "phoenix suns", "rock, pop", "mannheim", "dolly",
            "dateline", "20/20", "saturday night live", "big noon", "to be announced"
        ]
        if not any(w in title_lower for w in non_movie_words):
            return "movies"

    # 4. TV Shows / Series / Daytime
    return "tvshows"


def get_program_display_titles(prog: Dict[str, Any]) -> Tuple[str, str]:
    """
    Returns (primary_title, secondary_subtitle) optimized for EPG grid tiles and list views.
    - Movies: returns (Movie Title, "")
    - Sports with Matchups (e.g. 'Ravens at Falcons'): returns (Matchup, League/Sport)
    - Sports without Matchups: returns (League / Sport + ' (Teams TBA)', "")
    - Standard Shows / Series: returns (Show Title, Episode Title)
    """
    show = (prog.get("show_title") or "").strip()
    ep = (prog.get("episode_title") or "").strip()
    cat = prog.get("_category") or classify_guide_category(prog)

    if cat == "sports":
        has_matchup = False
        if ep:
            ep_lower = ep.lower()
            if " at " in ep_lower or " vs. " in ep_lower or " vs " in ep_lower:
                has_matchup = True
            elif any(k in show.lower() for k in ["football", "baseball", "basketball", "soccer", "hockey"]):
                # If it's a known sport and has an episode title, it's typically the matchup or event
                has_matchup = True

        if has_matchup:
            # Primary is the specific matchup, secondary is the sport / league
            return ep, show
        elif not ep:
            # Broadcast does not list specific matchup (e.g. NFL Football on Fox)
            show_lower = show.lower()
            if show_lower in ("nfl football", "college football", "mlb baseball", "nba basketball", "nhl hockey"):
                return f"{show} (Teams TBA)", ""
            return show, ""

    elif cat == "movies":
        # Movie title is already in show_title; don't redundantly display subtitle if empty or 'Movie'
        if ep.lower() in ("movie", "feature film", "tv movie", "television movie"):
            return show, ""
        return show, ep

    return show, ep


def compute_alternating_shade(base: QColor) -> QColor:
    """
    Compute a subtle alternating row shade for the EPG grid given any base color.
    Preserves alternating row distinction across dark, medium, and pitch-black themes.
    """
    # For very dark or pure black (e.g. OLED), darkening has no effect so lighten slightly
    if base.lightness() < 25:
        return base.lighter(120) if base.lightness() > 0 else QColor("#12141a")
    # For normal dark to medium backgrounds, darken by ~10%
    return base.darker(110)


class ProgramTileDelegate(QStyledItemDelegate):
    """
    Custom item delegate for rendering traditional EPG grid program tiles.
    - Flawlessly aligns multi-line text flush to the left edge with uniform padding.
    - Colors show titles: Sports = Orange (#ffa028), News = Blue (#4fc3f7), Movies = Purple (#c084fc), TV Shows = Green (#66bb6a).
    - Subtext displays time range and episode title with high legibility.
    """
    COLOR_SELECTED_BG = QColor("#2b3e4f")
    COLOR_SELECTED_BORDER_SCHED = QColor("#ff5252")
    COLOR_SELECTED_BORDER = QColor("#38bdf8")
    COLOR_DEFAULT_BG = QColor("#222838")
    COLOR_DEFAULT_BG_ALT = QColor("#1e2332")
    COLOR_PAST_BG = QColor("#161922")
    COLOR_PAST_BG_ALT = QColor("#14171f")
    COLOR_LIVE_BG = QColor("#132400")
    COLOR_DEFAULT_BORDER_SCHED = QColor("#e53935")
    COLOR_DEFAULT_BORDER = QColor("#333c4e")
    COLOR_PAST_BORDER = QColor("#262c3a")
    COLOR_PAST_BORDER_SCHED = QColor("#8b0000")
    COLOR_REC_BADGE_PEN = QColor("#e53935")
    COLOR_REC_BADGE_BRUSH = QColor("#b71c1c")
    COLOR_LIVE_DOT = QColor("#66bb6a")
    COLOR_WHITE = QColor("#ffffff")
    COLOR_UPCOMING_TITLE = QColor("#b9feff")
    COLOR_PAST_TITLE = QColor("#788292")
    COLOR_PAST_SUBTEXT = QColor("#5a6474")
    COLOR_LIVE_TITLE = QColor("#66bb6a")
    COLOR_SUBTEXT = QColor("#a4b0c2")

    CATEGORY_COLORS = {
        "sports": QColor("#ffa028"),
        "news": QColor("#4fc3f7"),
        "movies": QColor("#c084fc"),
        "tvshows": QColor("#b9feff"),
        "highlight": QColor("#38bdf8"),
        "live_badge": QColor("#059669"),
        "live_bg": QColor("#132400"),
        "grid_bg": QColor("#222838"),
    }

    def __init__(self, parent=None, config_mgr=None):
        super().__init__(parent)
        self.zoom_delta = 0
        self.config_mgr = config_mgr
        self._qcolor_cache: Dict[str, QColor] = {}
        self._default_bg = self.COLOR_DEFAULT_BG
        self.color_past_bg = self.COLOR_PAST_BG
        self.color_past_bg_alt = self.COLOR_PAST_BG_ALT
        self.color_past_border = self.COLOR_PAST_BORDER
        self.color_past_title = self.COLOR_PAST_TITLE
        self.color_past_subtext = self.COLOR_PAST_SUBTEXT
        self.refresh_category_colors()

    def set_zoom_delta(self, delta: int):
        self.zoom_delta = delta

    def refresh_category_colors(self):
        cfg_colors = self.config_mgr.category_colors if self.config_mgr else DEFAULT_CATEGORY_COLORS
        self._qcolor_cache = {cat: QColor(hex_val) for cat, hex_val in cfg_colors.items()}
        base_hex = cfg_colors.get("grid_bg", DEFAULT_CATEGORY_COLORS.get("grid_bg", "#222838"))
        self._default_bg = QColor(base_hex)
        self._default_bg_alt = compute_alternating_shade(self._default_bg)

        # Harmonized theme colors for past shows
        from kaffeine_dvr.config import compute_past_theme_colors
        past_bg_hex = cfg_colors.get("past_bg")
        past_title_hex = cfg_colors.get("past_title")
        past_subtext_hex = cfg_colors.get("past_subtext")
        past_border_hex = cfg_colors.get("past_border")

        if not (past_bg_hex and past_title_hex and past_subtext_hex and past_border_hex):
            computed = compute_past_theme_colors(base_hex)
            past_bg_hex = past_bg_hex or computed.get("past_bg", "#161922")
            past_title_hex = past_title_hex or computed.get("past_title", "#788292")
            past_subtext_hex = past_subtext_hex or computed.get("past_subtext", "#5a6474")
            past_border_hex = past_border_hex or computed.get("past_border", "#262c3a")

        self.color_past_bg = QColor(past_bg_hex)
        past_bg_alt_hex = cfg_colors.get("past_bg_alt")
        self.color_past_bg_alt = QColor(past_bg_alt_hex) if past_bg_alt_hex else compute_alternating_shade(self.color_past_bg)
        self.color_past_border = QColor(past_border_hex)
        self.color_past_title = QColor(past_title_hex)
        self.color_past_subtext = QColor(past_subtext_hex)

    def get_category_color(self, cat: str) -> QColor:
        if cat in self._qcolor_cache:
            return self._qcolor_cache[cat]
        if self.config_mgr:
            val = self.config_mgr.category_colors.get(cat)
            if val:
                c = QColor(val)
                self._qcolor_cache[cat] = c
                return c
        return self.CATEGORY_COLORS.get(cat, self.COLOR_UPCOMING_TITLE)

    def paint(self, painter: Optional[QPainter], option: QStyleOptionViewItem, index):
        if not painter:
            return
        prog = index.data(Qt.ItemDataRole.UserRole)
        if not prog:
            super().paint(painter, option, index)
            return

        painter.save()
        rect = option.rect

        # Timing state & metadata
        is_selected = False
        grid = getattr(option, "widget", None)
        if not grid and callable(getattr(self, "parent", None)):
            grid = self.parent()
        mw = getattr(grid, "main_window", None) if grid else None
        cur_sel = getattr(mw, "selected_grid_program", None) if mw else None

        if cur_sel is not None:
            if cur_sel is prog:
                is_selected = True
            elif cur_sel.get("id") is not None and prog.get("id") is not None:
                is_selected = (cur_sel.get("id") == prog.get("id"))
            else:
                cur_ch = (cur_sel.get("kaffeine_channel") or cur_sel.get("channel") or "").strip().lower()
                prog_ch = (prog.get("kaffeine_channel") or prog.get("channel") or "").strip().lower()
                is_selected = bool(cur_ch and prog_ch and cur_ch == prog_ch and cur_sel.get("start_iso") == prog.get("start_iso"))
        else:
            is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
            if not is_selected and isinstance(grid, QTableWidget):
                sel = grid.selectionModel()
                if sel:
                    row = index.row()
                    col = index.column()
                    span = grid.columnSpan(row, col)
                    if any(sel.isSelected(grid.model().index(row, col + sc)) for sc in range(max(1, span))):
                        is_selected = True

        is_scheduled = bool(prog.get("_scheduled_rec"))
        is_past_recorded = bool(prog.get("_history_rec"))
        # Dynamically evaluate timing state against current time
        timing_state = prog.get("_timing_state")
        start_dt = prog.get("_parsed_start_dt")
        end_dt = prog.get("_parsed_end_dt")
        if start_dt is None:
            start_iso = prog.get("start_iso")
            if start_iso:
                try:
                    start_dt = datetime.fromisoformat(start_iso)
                    dur_iso = prog.get("duration_iso") or "00:30:00"
                    parts = [int(x) for x in dur_iso.split(":")]
                    dur = timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2] if len(parts) > 2 else 0)
                    end_dt = start_dt + dur
                    prog["_parsed_start_dt"] = start_dt
                    prog["_parsed_end_dt"] = end_dt
                except Exception:
                    pass

        if start_dt and end_dt:
            now = datetime.now()
            if now >= end_dt:
                timing_state = "past"
            elif start_dt <= now < end_dt:
                timing_state = "live"
            else:
                timing_state = "upcoming"
        else:
            timing_state = timing_state or "upcoming"

        # Background fill & border styling
        is_alt = (index.row() % 2 == 1)
        rec_data = prog.get("_scheduled_rec")
        rec_status = rec_data.get("status") if isinstance(rec_data, dict) else ""
        is_recording = is_scheduled and (rec_status == "RECORDING" or (timing_state == "live" and rec_status in ("ARMED", "RECORDING")))

        # Determine background fill based on program timing state
        same_bg = bool(getattr(self.config_mgr, "live_same_bg_as_others", False)) if self.config_mgr else False
        has_rec_border = is_scheduled or (timing_state == "past" and is_past_recorded)
        if timing_state == "past":
            bg_color = self.color_past_bg_alt if is_alt else self.color_past_bg
            default_border = self.COLOR_PAST_BORDER_SCHED if has_rec_border else self.color_past_border
        elif timing_state == "live" and not same_bg:
            bg_color = self.get_category_color("live_bg")
            default_border = self.COLOR_DEFAULT_BORDER_SCHED if has_rec_border else self.COLOR_DEFAULT_BORDER
        else:
            bg_color = self._default_bg_alt if is_alt else self._default_bg
            default_border = self.COLOR_DEFAULT_BORDER_SCHED if has_rec_border else self.COLOR_DEFAULT_BORDER

        if is_selected:
            border_color = self.get_category_color("highlight")
            pen_width = 2
        else:
            border_color = default_border
            pen_width = 2 if has_rec_border else 1

        painter.fillRect(rect, bg_color)
        painter.setPen(QPen(border_color, pen_width))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        # Uniform padding inside box
        pad_left = 10
        pad_top = 5
        pad_right = 10
        inner_width = max(10, rect.width() - pad_left - pad_right)

        # Draw Badges (Red dot indicator in upper right corner only if currently recording)
        badge_reserved_w = 0
        cur_right = rect.right() - pad_right

        if is_recording:
            dot_diameter = max(7, 8 + self.zoom_delta)
            dot_x = cur_right - dot_diameter
            # Center dot vertically with title line (line1_rect)
            calc_font = QFont(option.font)
            calc_font.setPointSize(max(8, 10 + self.zoom_delta))
            fm_calc = QFontMetrics(calc_font)
            dot_y = rect.top() + pad_top + int((fm_calc.height() - dot_diameter) / 2)

            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.COLOR_REC_BADGE_PEN)
            painter.drawEllipse(dot_x, dot_y, dot_diameter, dot_diameter)

            cur_right -= (dot_diameter + 6)
            badge_reserved_w += (dot_diameter + 6)

        # Title & Subtext color logic
        cat = prog.get("_category") or classify_guide_category(prog)
        if timing_state == "past":
            title_color = self.color_past_title
            subtext_color = self.color_past_subtext
        else:
            title_color = self.get_category_color(cat)
            subtext_color = self.COLOR_SUBTEXT

        primary_title = prog.get("_primary_title")
        secondary_sub = prog.get("_secondary_sub")
        if primary_title is None:
            primary_title, secondary_sub = get_program_display_titles(prog)
        time_range = prog.get("_time_range", "")

        # Line 1: Primary Title (bold, color-coded)
        font_title = QFont(option.font)
        font_title.setBold(True)
        font_title.setPointSize(max(8, 10 + self.zoom_delta))
        painter.setFont(font_title)
        painter.setPen(title_color)

        fm_title = painter.fontMetrics()
        inner_width_title = max(10, inner_width - badge_reserved_w)
        elided_title = fm_title.elidedText(primary_title, Qt.TextElideMode.ElideRight, inner_width_title)
        line1_y = rect.top() + pad_top
        line1_rect = QRect(rect.left() + pad_left, line1_y, inner_width_title, fm_title.height())
        painter.drawText(line1_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

        # Lower-right live badge (compact micro solid pill)
        live_badge_w = 0
        hide_badge = bool(getattr(self.config_mgr, "hide_live_badge", False)) if self.config_mgr else False
        if timing_state == "live" and not hide_badge:
            badge_font = QFont(option.font)
            badge_font.setBold(True)
            badge_font.setPointSize(max(5, 6 + int(self.zoom_delta * 0.4)))
            fm_badge = QFontMetrics(badge_font)
            text_w = fm_badge.horizontalAdvance("LIVE")

            live_badge_w = max(24, text_w + 7)
            live_badge_h = max(11, fm_badge.height() + 1)

            pad_b = 5
            badge_x = rect.right() - pad_right - live_badge_w
            badge_y = rect.bottom() - pad_b - live_badge_h
            badge_rect = QRect(badge_x, badge_y, live_badge_w, live_badge_h)

            badge_color = self.get_category_color("live_badge")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(badge_color)
            painter.drawRoundedRect(badge_rect, 2, 2)

            painter.setPen(QColor("#ffffff"))
            painter.setFont(badge_font)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "LIVE")

        # Line 2 & 3 Subtext font setup
        font_sub = QFont(option.font)
        font_sub.setBold(False)
        font_sub.setPointSize(max(7, 8 + self.zoom_delta))
        painter.setFont(font_sub)
        painter.setPen(subtext_color)
        fm_sub = painter.fontMetrics()

        # Line 2: Time Range
        line2_y = line1_y + fm_title.height() + 2
        # If there is no line 3, clear space for the live badge on line 2
        line2_reserve = (live_badge_w + 6) if (live_badge_w > 0 and not secondary_sub) else 0
        inner_width_time = max(10, inner_width - line2_reserve)
        elided_time = fm_sub.elidedText(time_range, Qt.TextElideMode.ElideRight, inner_width_time)
        line2_rect = QRect(rect.left() + pad_left, line2_y, inner_width_time, fm_sub.height())
        painter.drawText(line2_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_time)

        # Line 3: Subtitle / Episode Title (rendered if present and space permits)
        if secondary_sub:
            line3_y = line2_y + fm_sub.height() + 2
            if line3_y + fm_sub.height() <= rect.bottom() + 1:
                inner_width_sub = max(10, inner_width - (live_badge_w + 6 if live_badge_w > 0 else 0))
                elided_sub = fm_sub.elidedText(secondary_sub, Qt.TextElideMode.ElideRight, inner_width_sub)
                line3_rect = QRect(rect.left() + pad_left, line3_y, inner_width_sub, fm_sub.height())
                painter.drawText(line3_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_sub)

        painter.restore()


class GridPanFilter(QObject):
    """
    Event filter installed on the guide grid table viewport to support
    mouse grab-and-drag panning/scrolling while preserving cell click selection.
    """
    def __init__(self, table: QTableWidget, parent=None, main_window=None):
        super().__init__(parent or table)
        self.table = table
        self.main_window = main_window
        self._dragging = False
        self._drag_start_pos = None
        self._last_drag_pos = None
        self._drag_threshold = 5
        self._overscroll_x = 0
        self._overscroll_badge = None
        self._set_cursor(Qt.CursorShape.OpenHandCursor)

    def _set_cursor(self, shape: Qt.CursorShape):
        try:
            self.table.viewport().setCursor(shape)
            hdr = self.table.horizontalHeader()
            if hdr and hdr.viewport():
                hdr.viewport().setCursor(shape)
        except (RuntimeError, AttributeError):
            pass

    def _ensure_badge(self):
        if self._overscroll_badge is None:
            vp = self.table.viewport()
            self._overscroll_badge = QLabel(vp)
            self._overscroll_badge.setObjectName("gridOverscrollBadge")
            self._overscroll_badge.setStyleSheet(
                "QLabel#gridOverscrollBadge {"
                "  background-color: #1e3a8a;"
                "  color: #ffffff;"
                "  font-weight: bold;"
                "  font-size: 11px;"
                "  padding: 6px 14px;"
                "  border: 1.5px solid #3b82f6;"
                "  border-radius: 6px;"
                "}"
            )
            self._overscroll_badge.hide()

    def _update_overscroll_badge(self, direction: str):
        mw = self.main_window or getattr(self.table, "main_window", None)
        if not mw or not hasattr(mw, "guide_date_combo"):
            return
        combo = mw.guide_date_combo
        cur_idx = combo.currentIndex()
        if direction == "next":
            if cur_idx >= combo.count() - 1:
                return
            target_text = combo.itemText(cur_idx + 1)
            self._ensure_badge()
            self._overscroll_badge.setText(f"Release to advance to {target_text} →")
            self._overscroll_badge.adjustSize()
            vp = self.table.viewport()
            bx = vp.width() - self._overscroll_badge.width() - 16
            by = max(10, (vp.height() - self._overscroll_badge.height()) // 2)
            self._overscroll_badge.move(bx, by)
            self._overscroll_badge.show()
            self._overscroll_badge.raise_()
        elif direction == "prev":
            if cur_idx <= 1:
                return
            target_text = combo.itemText(cur_idx - 1)
            self._ensure_badge()
            self._overscroll_badge.setText(f"← Release for {target_text}")
            self._overscroll_badge.adjustSize()
            vp = self.table.viewport()
            bx = 16
            by = max(10, (vp.height() - self._overscroll_badge.height()) // 2)
            self._overscroll_badge.move(bx, by)
            self._overscroll_badge.show()
            self._overscroll_badge.raise_()

    def _hide_overscroll_badge(self):
        if self._overscroll_badge is not None:
            self._overscroll_badge.hide()

    def eventFilter(self, watched, event):
        evt_type = event.type()
        if evt_type == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            mw = self.main_window or getattr(self.table, "main_window", None)
            if mw and hasattr(mw, "clear_guide_selection"):
                mw.clear_guide_selection()
                return True

        try:
            vp = self.table.viewport()
            hdr = self.table.horizontalHeader()
            hdr_vp = hdr.viewport() if hdr else None
        except (RuntimeError, AttributeError):
            return False

        if watched not in (vp, hdr_vp):
            return super().eventFilter(watched, event)

        if evt_type == QEvent.Type.ContextMenu and self._dragging:
            return True

        if evt_type == QEvent.Type.MouseButtonPress:
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
                self._dragging = False
                self._overscroll_x = 0
                self._hide_overscroll_badge()
                pos = event.position().toPoint()
                self._drag_start_pos = pos
                self._last_drag_pos = pos
                # Consume press on the table viewport so table doesn't highlight/select cell on grab
                if watched is vp:
                    return True
                return False
            elif self._dragging:
                return True

        elif evt_type == QEvent.Type.MouseMove:
            if self._drag_start_pos is not None:
                # If neither left nor middle button is held down, end drag
                if not (event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.MiddleButton)):
                    was_drag = self._dragging
                    self._dragging = False
                    self._overscroll_x = 0
                    self._hide_overscroll_badge()
                    self._drag_start_pos = None
                    self._last_drag_pos = None
                    self._set_cursor(Qt.CursorShape.OpenHandCursor)
                    return was_drag

                cur_pos = event.position().toPoint()
                if not self._dragging:
                    total_dist = (cur_pos - self._drag_start_pos).manhattanLength()
                    if total_dist > self._drag_threshold:
                        self._dragging = True
                        self._set_cursor(Qt.CursorShape.ClosedHandCursor)

                if self._dragging:
                    delta = cur_pos - self._last_drag_pos
                    self._last_drag_pos = cur_pos

                    h_bar = self.table.horizontalScrollBar()
                    v_bar = self.table.verticalScrollBar()

                    if delta.x() != 0 and h_bar:
                        old_val = h_bar.value()
                        h_bar.setValue(old_val - delta.x())
                        new_val = h_bar.value()

                        # Detect overscroll when dragging past boundaries
                        if delta.x() < 0 and old_val == h_bar.maximum() and new_val == h_bar.maximum():
                            self._overscroll_x += abs(delta.x())
                            if self._overscroll_x > 35:
                                self._update_overscroll_badge("next")
                        elif delta.x() > 0 and old_val == 0 and new_val == 0:
                            self._overscroll_x -= abs(delta.x())
                            if self._overscroll_x < -35:
                                self._update_overscroll_badge("prev")
                        else:
                            if self._overscroll_x != 0:
                                self._overscroll_x = 0
                                self._hide_overscroll_badge()

                    if delta.y() != 0 and v_bar and watched is vp:
                        v_bar.setValue(v_bar.value() - delta.y())
                return True

        elif evt_type == QEvent.Type.MouseButtonRelease:
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
                was_dragging = self._dragging
                release_pos = self._drag_start_pos
                self._dragging = False
                self._drag_start_pos = None
                self._last_drag_pos = None
                self._set_cursor(Qt.CursorShape.OpenHandCursor)

                # Check if overscroll threshold was met to push through to next / prev day
                overscroll = getattr(self, "_overscroll_x", 0)
                self._overscroll_x = 0
                self._hide_overscroll_badge()

                if overscroll > 45:
                    mw = self.main_window or getattr(self.table, "main_window", None)
                    if mw and hasattr(mw, "advance_guide_date"):
                        mw.advance_guide_date(offset=1, position="0400")
                    return True
                elif overscroll < -45:
                    mw = self.main_window or getattr(self.table, "main_window", None)
                    if mw and hasattr(mw, "advance_guide_date"):
                        mw.advance_guide_date(offset=-1, position="end")
                    return True

                if was_dragging:
                    return True
                # Clean click without dragging: select cell on release
                if watched is vp and event.button() == Qt.MouseButton.LeftButton and release_pos is not None:
                    row = self.table.rowAt(release_pos.y())
                    col = self.table.columnAt(release_pos.x())
                    if row >= 0 and col >= 0:
                        target_col = col
                        item = self.table.item(row, col)
                        if not item:
                            for c in range(col - 1, -1, -1):
                                it = self.table.item(row, c)
                                if it:
                                    target_col = c
                                    break
                        self.table.setCurrentCell(row, target_col)
                        self.table.cellClicked.emit(row, col)
                    else:
                        mw = self.main_window or getattr(self.table, "main_window", None)
                        if mw and hasattr(mw, "clear_guide_selection"):
                            mw.clear_guide_selection()
                    return True
                return False

        elif evt_type == QEvent.Type.MouseButtonDblClick:
            if watched is vp and event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint()
                row = self.table.rowAt(pos.y())
                col = self.table.columnAt(pos.x())
                if row >= 0 and col >= 0:
                    self.table.cellDoubleClicked.emit(row, col)
                return True

        elif evt_type in (QEvent.Type.FocusOut, QEvent.Type.WindowDeactivate):
            self._dragging = False
            self._drag_start_pos = None
            self._last_drag_pos = None
            self._overscroll_x = 0
            self._hide_overscroll_badge()
            self._set_cursor(Qt.CursorShape.OpenHandCursor)

        elif evt_type == QEvent.Type.Enter:
            if not self._dragging:
                self._set_cursor(Qt.CursorShape.OpenHandCursor)

        return super().eventFilter(watched, event)


class GuideListClickFilter(QObject):
    """
    Event filter for guide list view (table) to handle clicking empty background space
    and pressing Escape to clear selection / unhighlight.
    """
    def __init__(self, table: QTableWidget, main_window=None):
        super().__init__(table)
        self.table = table
        self.main_window = main_window

    def eventFilter(self, watched, event):
        evt_type = event.type()
        if evt_type == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            row = self.table.rowAt(pos.y())
            if row < 0:
                mw = self.main_window or getattr(self.table, "main_window", None)
                if mw and hasattr(mw, "clear_guide_selection"):
                    mw.clear_guide_selection()
        elif evt_type == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            mw = self.main_window or getattr(self.table, "main_window", None)
            if mw and hasattr(mw, "clear_guide_selection"):
                mw.clear_guide_selection()
                return True
        return super().eventFilter(watched, event)


class GuideGridHeader(QHeaderView):
    """
    Custom horizontal header for the guide grid that draws a subtle current-time
    indicator marker when viewing today's programming.
    """
    def __init__(self, orientation, parent=None, main_window=None):
        super().__init__(orientation, parent)
        self.main_window = main_window

    def paintEvent(self, event):
        super().paintEvent(event)
        mw = getattr(self, "main_window", None)
        if not mw or not getattr(mw, "config_mgr", None):
            return
        if not getattr(mw.config_mgr, "guide_show_time_indicator", True):
            return
        if not mw.is_viewing_today():
            return

        now = datetime.now()
        current_slot = min(47, max(0, now.hour * 2 + (1 if now.minute >= 30 else 0)))
        slot_minute = now.minute % 30
        fraction = (slot_minute + now.second / 60.0) / 30.0
        slot_left_x = self.sectionViewportPosition(current_slot)
        slot_width = self.sectionSize(current_slot)
        line_x = slot_left_x + int(fraction * slot_width)

        vp_width = self.viewport().width()
        if 0 <= line_x <= vp_width:
            line_col_hex = mw.config_mgr.category_colors.get("time_indicator", "#06b6d4")
            opacity = getattr(mw.config_mgr, "time_line_opacity", 100) / 100.0
            color = QColor(line_col_hex)
            color.setAlphaF(color.alphaF() * max(0.05, min(1.0, opacity)))
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            h = self.viewport().height()
            tri = QPolygon([
                QPoint(line_x - 5, h - 7),
                QPoint(line_x + 5, h - 7),
                QPoint(line_x, h)
            ])
            painter.drawPolygon(tri)
            painter.end()

        # Draw subtle midnight boundary line at column 48 if visible
        if self.count() > 48:
            mid_x = self.sectionViewportPosition(48)
            vp_width = self.viewport().width()
            if 0 <= mid_x <= vp_width:
                painter = QPainter(self.viewport())
                painter.setPen(QPen(QColor("#3b82f6"), 2))
                painter.drawLine(mid_x, 0, mid_x, self.viewport().height())
                painter.end()


class GuideGridVerticalHeader(QHeaderView):
    """
    Custom vertical header for the TV guide grid:
    - Renders each channel label as a distinct, clearly separated square/card with clean borders.
    - Displays a pronounced visual indicator ('● PLAYING' badge, vibrant background, glowing border)
      when that channel is actively playing in live timeshift mode.
    - Provides a pointing hand cursor to make it obvious that each channel square is clickable.
    """
    def __init__(self, parent=None, main_window=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.main_window = main_window
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.viewport().setMouseTracking(True)
        self._hovered_section = -1

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        sec = self.logicalIndexAt(event.position().toPoint())
        if sec != self._hovered_section:
            self._hovered_section = sec
            self.viewport().update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._hovered_section != -1:
            self._hovered_section = -1
            self.viewport().update()

    def sizeHint(self):
        sz = super().sizeHint()
        # Maintain fixed compact width for channel square without resizing
        sz.setWidth(70)
        return sz

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int):
        painter.save()
        mw = getattr(self, "main_window", None)
        active_ts = getattr(mw, "_active_timeshift", None) if mw else None
        active_ch = (active_ts.get("channel") or "").strip().lower() if active_ts else ""

        # Retrieve active theme tokens and guide category colors
        cfg = getattr(mw, "config_mgr", None) if mw else None
        app_theme_key = getattr(cfg, "app_theme", "midnight") if cfg else "midnight"
        tokens = APP_THEMES.get(app_theme_key, APP_THEMES.get("midnight", {}))
        cat_colors = getattr(cfg, "category_colors", {}) if cfg else {}

        # Theme-derived color tokens
        header_bg_hex = tokens.get("table_header_bg") or "#1e2330"
        border_hex = tokens.get("border_color") or tokens.get("table_gridline") or "#332623"
        text_primary_hex = tokens.get("text_primary") or "#ffffff"
        accent_hex = tokens.get("accent_primary") or "#ea580c"

        # Retrieve channel name for this row
        channel_name = ""
        model = self.model()
        if model:
            val = model.headerData(logical_index, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole)
            if val is not None:
                channel_name = str(val).strip()
        if not channel_name and mw and hasattr(mw, "grid_channels") and logical_index < len(mw.grid_channels):
            channel_name = str(mw.grid_channels[logical_index]).strip()

        is_playing = bool(active_ch and channel_name and active_ch == channel_name.lower())
        is_hovered = (logical_index == getattr(self, "_hovered_section", -1))
        live_green = QColor("#66bb6a")

        # Card geometry with 2px margin around each channel square for clear separation
        card_rect = rect.adjusted(3, 3, -3, -3)

        if is_playing:
            # Active playing channel: uses exact live green #66bb6a for border and channel title
            border_color = live_green
            # Subtle dark live background tone harmonized with theme
            bg_color = QColor(19, 36, 0)
            border_width = 2
            text_color = live_green
        else:
            # Follow application & guide theme
            base_header_color = QColor(header_bg_hex)
            is_alt = (logical_index % 2 == 1)
            bg_color = compute_alternating_shade(base_header_color) if is_alt else base_header_color
            border_color = live_green if is_hovered else QColor(border_hex)
            border_width = 1
            # Channel name turns live green #66bb6a when hovering
            text_color = live_green if is_hovered else QColor(text_primary_hex)

        # Fill background card
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(bg_color)
        painter.drawRoundedRect(card_rect, 4, 4)

        # Base font setup allowing up to two rows for channel name with word wrap without changing box geometry
        text_rect = card_rect.adjusted(3, 2, -3, -2)
        flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap

        # Fit channel name cleanly across up to two lines, scaling down font if needed
        base_font = QFont(self.font())
        base_font.setBold(True)
        chosen_font = None
        for pt in [11, 10, 9, 8]:
            font = QFont(base_font)
            font.setPointSize(pt)
            fm = QFontMetrics(font)
            words = channel_name.split()
            all_words_fit = all(fm.horizontalAdvance(w) <= text_rect.width() for w in words) if words else True
            br = fm.boundingRect(text_rect, flags, channel_name)
            if all_words_fit and br.height() <= text_rect.height():
                chosen_font = font
                break
        if not chosen_font:
            chosen_font = QFont(base_font)
            chosen_font.setPointSize(8)

        # Clean centered channel title across the square (1 or 2 rows)
        painter.setFont(chosen_font)
        painter.setPen(text_color)
        painter.drawText(text_rect, flags, channel_name)

        painter.restore()


class GuideGridTable(QTableWidget):
    """
    Custom table widget for the guide grid that draws a vertical current-time
    indicator line down across the table viewport when viewing today's programming,
    and a subtle midnight demarcation line when viewing the extended 28-hour grid.
    """
    def __init__(self, *args, main_window=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.main_window = main_window

    def paintEvent(self, event):
        super().paintEvent(event)
        hdr = self.horizontalHeader()
        if hdr and self.columnCount() > 48:
            mid_x = hdr.sectionViewportPosition(48)
            vp_width = self.viewport().width()
            if 0 <= mid_x <= vp_width:
                painter = QPainter(self.viewport())
                painter.setPen(QPen(QColor("#3b82f6"), 1, Qt.PenStyle.DashLine))
                painter.drawLine(mid_x, 0, mid_x, self.viewport().height())
                painter.end()

        mw = getattr(self, "main_window", None)
        if not mw or not getattr(mw, "config_mgr", None):
            return
        if not getattr(mw.config_mgr, "guide_show_time_indicator", True):
            return
        if not mw.is_viewing_today():
            return

        if not hdr:
            return

        now = datetime.now()
        current_slot = min(47, max(0, now.hour * 2 + (1 if now.minute >= 30 else 0)))
        slot_minute = now.minute % 30
        fraction = (slot_minute + now.second / 60.0) / 30.0
        slot_left_x = hdr.sectionViewportPosition(current_slot)
        slot_width = self.columnWidth(current_slot)
        line_x = slot_left_x + int(fraction * slot_width)

        vp_width = self.viewport().width()
        if 0 <= line_x <= vp_width:
            line_col_hex = mw.config_mgr.category_colors.get("time_indicator", "#06b6d4")
            opacity = getattr(mw.config_mgr, "time_line_opacity", 100) / 100.0
            color = QColor(line_col_hex)
            color.setAlphaF(color.alphaF() * max(0.05, min(1.0, opacity)))
            painter = QPainter(self.viewport())
            painter.setPen(QPen(color, 2))
            painter.drawLine(line_x, 0, line_x, self.viewport().height())
            painter.end()


class UpcomingShowDialog(BaseFramelessDialog):
    ACTION_CANCEL = 0
    ACTION_RECORD = 1
    ACTION_TUNE = 2
    ACTION_CANCEL_RECORDING = 3

    def __init__(self, prog: Dict[str, Any], timing_info: Dict[str, Any], is_scheduled: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Upcoming Program")
        self.setMinimumWidth(460)
        self.action = self.ACTION_CANCEL
        self.is_scheduled = is_scheduled

        title = prog.get("show_title") or prog.get("title") or "Selected Program"
        ep = prog.get("episode_title")
        ch = prog.get("kaffeine_channel", "")
        time_desc = timing_info.get("time_desc", "")
        start_fmt = timing_info.get("start_fmt", "")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_lbl = QLabel(f"<b>{title}</b>")
        header_lbl.setStyleSheet("font-size: 15px; color: #66bb6a;")
        header_row.addWidget(header_lbl, 1)

        close_x = QToolButton(self)
        close_x.setText("✕")
        close_x.setToolTip("Close")
        close_x.setCursor(Qt.CursorShape.PointingHandCursor)
        close_x.setStyleSheet(
            "QToolButton { background: transparent; color: #8c98aa; font-size: 13px; font-weight: bold; border: none; padding: 2px 6px; border-radius: 4px; }"
            "QToolButton:hover { color: #ffffff; background-color: rgba(255, 255, 255, 0.1); }"
        )
        close_x.clicked.connect(self.reject)
        header_row.addWidget(close_x, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header_row)

        sub_parts = []
        if ep:
            sub_parts.append(f'"{ep}"')
        if ch:
            sub_parts.append(f"on {ch}")
        if start_fmt:
            sub_parts.append(f"at {start_fmt}")
        if time_desc:
            sub_parts.append(f"({time_desc})")
        info_lbl = QLabel(" • ".join(sub_parts))
        info_lbl.setStyleSheet("color: #a4b0c2; font-size: 13px;")
        layout.addWidget(info_lbl)

        prompt_lbl = QLabel("This program has not started yet. What would you like to do?")
        prompt_lbl.setStyleSheet("font-size: 13px; margin-top: 4px;")
        layout.addWidget(prompt_lbl)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        if self.is_scheduled:
            rec_btn = QPushButton("Cancel Recording")
            rec_btn.setObjectName("dangerActionBtn")
            rec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            rec_btn.setDefault(True)
            rec_btn.clicked.connect(self._on_cancel_recording)
            btn_layout.addWidget(rec_btn)
        else:
            rec_btn = QPushButton("Schedule Recording")
            rec_btn.setObjectName("primaryActionBtn")
            rec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            rec_btn.setDefault(True)
            rec_btn.clicked.connect(self._on_record)
            btn_layout.addWidget(rec_btn)

        tune_btn = QPushButton("Watch Channel")
        tune_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tune_btn.clicked.connect(self._on_tune)
        btn_layout.addWidget(tune_btn)

        cancel_btn = QPushButton("Close" if self.is_scheduled else "Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _on_record(self):
        self.action = self.ACTION_RECORD
        self.accept()

    def _on_cancel_recording(self):
        self.action = self.ACTION_CANCEL_RECORDING
        self.accept()

    def _on_tune(self):
        self.action = self.ACTION_TUNE
        self.accept()


class FirstRunWelcomeDialog(BaseFramelessDialog):
    def __init__(self, config_mgr: ConfigManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Kaffeine DVR & TV Guide")
        self.setFixedWidth(730)
        self.config_mgr = config_mgr
        self.setStyleSheet(f"""
            QDialog {{
                background: transparent;
                color: #dce1e8;
            }}
            QLabel {{
                color: #dce1e8;
            }}
            QGroupBox {{
                background-color: #1e2230;
                border: 1px solid #333a4c;
                border-radius: 6px;
                margin-top: 14px;
                padding-top: 14px;
                font-weight: bold;
                font-size: 13px;
                color: #d3dae3;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 8px;
                color: #d3dae3;
            }}
            QCheckBox {{
                color: #e0e6ed;
                font-size: 13px;
                spacing: 8px;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid #3d465c;
                border-radius: 3px;
                background-color: #141620;
            }}
            QCheckBox::indicator:hover {{
                border-color: #505c75;
            }}
            QCheckBox::indicator:checked {{
                background-color: #2d6cd4;
                border-color: #4a8df5;
                image: url("{get_checkmark_icon_path()}");
            }}
            QCheckBox::indicator:checked:disabled {{
                background-color: #238636;
                border-color: #2ea043;
                image: url("{get_checkmark_icon_path()}");
            }}
            QPushButton#primaryActionBtn {{
                background-color: #2d6cd4;
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 24px;
                border-radius: 5px;
                border: 1px solid #4a8df5;
            }}
            QPushButton#primaryActionBtn:hover {{
                background-color: #3b7ee8;
            }}
            QPushButton#primaryActionBtn:pressed {{
                background-color: #2259b3;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(22, 14, 22, 16)

        header_row = QHBoxLayout()
        header_row.addStretch()
        title_lbl = QLabel("Welcome to Kaffeine DVR & TV Guide")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        title_lbl.setStyleSheet("font-size: 19px; font-weight: bold; color: #ffffff; padding: 2px 0 2px 0; background: transparent;")
        header_row.addWidget(title_lbl)
        header_row.addStretch()

        close_x = QToolButton(self)
        close_x.setText("✕")
        close_x.setToolTip("Close")
        close_x.setCursor(Qt.CursorShape.PointingHandCursor)
        close_x.setStyleSheet(
            "QToolButton { background: transparent; color: #8c98aa; font-size: 13px; font-weight: bold; border: none; padding: 2px 6px; border-radius: 4px; }"
            "QToolButton:hover { color: #ffffff; background-color: rgba(255, 255, 255, 0.1); }"
        )
        close_x.clicked.connect(self.reject)
        header_row.addWidget(close_x, 0, Qt.AlignmentFlag.AlignTop)

        layout.addLayout(header_row)

        # Environment box
        env_box = QGroupBox("Detected System Environment")
        env_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        env_layout = QVBoxLayout(env_box)
        env_layout.setContentsMargins(20, 16, 20, 18)
        env_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        local_dt = datetime.now().astimezone()
        tz_name = local_dt.tzname() or "Local"
        tz_offset = local_dt.strftime("%z")
        tz_str = f"{tz_name} (UTC{tz_offset[:3]}:{tz_offset[3:]})"

        kaffeine_channels = self.config_mgr.get_scanned_kaffeine_channels()
        if kaffeine_channels:
            ch_count = len(kaffeine_channels)
            ch_status_html = (
                f"<b><span style='color: #4ade80; font-weight: bold;'>{ch_count} scanned channels</span> found in Kaffeine</b>"
            )
        else:
            ch_status_html = (
                "<b style='color: #fbbf24;'>No scanned channels found yet</b> "
                "<span style='color: #94a3b8; font-size: 11px;'>(Kaffeine scan not performed)</span>"
            )

        grid_container = QWidget()
        grid_lay = QGridLayout(grid_container)
        grid_lay.setContentsMargins(0, 0, 0, 0)
        grid_lay.setHorizontalSpacing(12)
        grid_lay.setVerticalSpacing(8)

        lbl_tz_label = QLabel("System Timezone:")
        lbl_tz_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_tz_label.setStyleSheet("color: #dce1e8; font-size: 13px; background: transparent;")

        lbl_tz_val = QLabel(f"<b>{tz_str}</b> <span style='color: #94a3b8; font-size: 11px;'>(Showtimes automatically align with this timezone)</span>")
        lbl_tz_val.setStyleSheet("font-size: 13px; color: #ffffff; background: transparent;")

        lbl_tun_label = QLabel("Kaffeine Tuner:")
        lbl_tun_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_tun_label.setStyleSheet("color: #dce1e8; font-size: 13px; background: transparent;")

        lbl_tun_val = QLabel(ch_status_html)
        lbl_tun_val.setStyleSheet("font-size: 13px; color: #ffffff; background: transparent;")

        grid_lay.addWidget(lbl_tz_label, 0, 0)
        grid_lay.addWidget(lbl_tz_val, 0, 1)
        grid_lay.addWidget(lbl_tun_label, 1, 0)
        grid_lay.addWidget(lbl_tun_val, 1, 1)

        env_layout.addWidget(grid_container, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(env_box)

        # TV Guide and Regional Channel Coverage Explanation
        guide_info_box = QGroupBox("TV Guide Coverage and Providers")
        guide_info_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        guide_info_layout = QVBoxLayout(guide_info_box)
        guide_info_layout.setSpacing(10)
        guide_info_layout.setContentsMargins(16, 16, 16, 16)

        guide_info_text = QLabel(
            "<div style='margin-bottom: 8px;'>"
            "  <div style='color: #60a5fa; font-weight: bold; font-size: 13px; margin-bottom: 2px;'>• National Networks (TVMaze — Zero Setup)</div>"
            "  <div style='color: #c9d4e2; font-size: 12px; margin-left: 14px; line-height: 1.45;'>"
            "    Covers major national feeds (<b>FOX, CBS, NBC, ABC</b>) with zero configuration.<br>"
            "    <span style='color: #94a3b8; font-style: italic;'>Note: National schedules only; local news and regional subchannels require TV Passport.</span>"
            "  </div>"
            "</div>"
            "<div style='margin-bottom: 8px;'>"
            "  <div style='color: #c084fc; font-weight: bold; font-size: 13px; margin-bottom: 2px;'>• 24/7 Local Affiliates, PBS, CW & Regional Channels (TV Passport)</div>"
            "  <div style='color: #c9d4e2; font-size: 12px; margin-left: 14px; line-height: 1.45;'>"
            "    Provides complete 24/7 schedules for local news, PBS member stations, CW syndication, and regional feeds.<br>"
            "    Find station IDs on <a href='https://www.tvpassport.com/index.php/lineups' style='color: #93c5fd; font-weight: bold; text-decoration: none;'>tvpassport.com</a> "
            "    and enter <code style='color: #52b788;'>Channel = StationID</code> under <b>Settings &gt; Guide Sources &amp; Health</b>."
            "  </div>"
            "</div>"
            "<div>"
            "  <div style='color: #4ade80; font-weight: bold; font-size: 13px; margin-bottom: 2px;'>• Hybrid Mode (Default)</div>"
            "  <div style='color: #c9d4e2; font-size: 12px; margin-left: 14px; line-height: 1.45;'>"
            "    TV Passport provides 24/7 local schedules for your configured stations, while TVMaze automatically covers remaining national networks."
            "  </div>"
            "</div>"
        )
        guide_info_text.setWordWrap(True)
        guide_info_text.setOpenExternalLinks(True)
        guide_info_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        guide_info_text.setStyleSheet("background: transparent;")
        guide_info_layout.addWidget(guide_info_text)

        # Check for unconfigured regional channels
        unconfigured_regional = self.config_mgr.get_unconfigured_regional_channels()
        if unconfigured_regional:
            ch_list_str = ", ".join(unconfigured_regional)
            notice_lbl = QLabel(
                f"<div style='border-left: 3px solid #f59e0b; border-radius: 4px; background-color: #211c14; padding: 10px 14px; margin-top: 4px; color: #fbbf24; font-size: 12px; line-height: 1.45;'>"
                f"  <b>Notice:</b> TVMaze only covers national broadcast feeds. The following local/regional channel(s) require TV Passport: "
                f"  <b style='color: #ffffff; background: #3d2c16; padding: 1px 6px; border-radius: 3px;'>{ch_list_str}</b>.<br>"
                f"  Configure their numeric station ID on <a href='https://www.tvpassport.com/index.php/lineups' style='color: #93c5fd; font-weight: bold; text-decoration: none;'>tvpassport.com</a> "
                f"  under <b>Settings &gt; Guide Sources &amp; Health</b> after startup."
                f"</div>"
            )
            notice_lbl.setWordWrap(True)
            notice_lbl.setOpenExternalLinks(True)
            notice_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            guide_info_layout.addWidget(notice_lbl)

        layout.addWidget(guide_info_box)

        options_box = QGroupBox("Initial Setup Options")
        options_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        options_layout = QVBoxLayout(options_box)
        options_layout.setSpacing(8)

        self.import_check = QCheckBox("Import detected channels from Kaffeine into lineup")
        self.import_check.setChecked(bool(kaffeine_channels))
        if not kaffeine_channels:
            self.import_check.setEnabled(False)
        options_layout.addWidget(self.import_check)

        self.sync_check = QCheckBox("Perform initial TV guide sync (download next 7 days)")
        self.sync_check.setChecked(True)
        options_layout.addWidget(self.sync_check)

        self.service_check = QCheckBox("Enable && start background recording dispatcher service (systemd)")
        self.service_check.setChecked(True)
        options_layout.addWidget(self.service_check)
        layout.addWidget(options_box)

        layout.addSpacing(10)
        btn_box = QHBoxLayout()
        self.start_btn = QPushButton("Start Kaffeine DVR")
        self.start_btn.setObjectName("primaryActionBtn")
        self.start_btn.clicked.connect(self.accept)
        btn_box.addStretch()
        btn_box.addWidget(self.start_btn)
        layout.addLayout(btn_box)


def get_app_icon() -> QIcon:
    # 1. Bundled application icon asset
    asset_path = _get_app_icon_asset_path()
    if asset_path and Path(asset_path).is_file():
        base_icon = QIcon(asset_path)
        if not base_icon.isNull():
            # Populate explicit standard pixmap sizes for X11 _NET_WM_ICON compatibility
            multi_icon = QIcon()
            for sz in [16, 22, 24, 32, 48, 64, 128, 256]:
                pix = base_icon.pixmap(sz, sz)
                if not pix.isNull():
                    multi_icon.addPixmap(pix)
            if not multi_icon.isNull():
                return multi_icon
            return base_icon

    # Ensure standard icon search paths are populated on systems where Qt misses user paths
    try:
        user_icons = str(Path.home() / ".local" / "share" / "icons")
        paths = QIcon.themeSearchPaths()
        if user_icons not in paths:
            paths.append(user_icons)
            QIcon.setThemeSearchPaths(paths)
    except Exception:
        pass

    # 2. Installed system / desktop theme lookups
    for name in ["kaffeine-dvr", "kaffeine", "org.kde.kaffeine", "video-television", "media-playback-start"]:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QIcon()


def build_app_stylesheet(theme_key: str = "midnight", checkmark_icon_path: str = "") -> str:
    tokens = APP_THEMES.get(theme_key, APP_THEMES["midnight"])
    return f"""
/* Base Application & Window Styling */
QWidget {{
    background-color: {tokens["bg_window"]};
    color: {tokens["text_primary"]};
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {tokens["bg_window"]};
    color: {tokens["text_primary"]};
}}

QMessageBox {{
    background-color: {tokens["bg_window"]};
    color: {tokens["text_primary"]};
}}

QMenu {{
    background-color: {tokens["menu_bg"]};
    color: {tokens["text_primary"]};
    border: 1px solid {tokens["border_color"]};
    padding: 4px;
}}
QMenu::item:selected {{
    background-color: {tokens["menu_item_selected"]};
    color: #ffffff;
}}

/* Default Form Controls */
QLineEdit, QTextEdit, QSpinBox, QComboBox {{
    background-color: {tokens["bg_input"]};
    border: 1px solid {tokens["border_color"]};
    border-radius: 4px;
    color: {tokens["text_primary"]};
    padding: 5px 8px;
}}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{
    border-color: {tokens["border_light"]};
}}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {tokens["accent_primary"]};
}}
QComboBox::drop-down {{
    border: none;
    background: transparent;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: {tokens["menu_bg"]};
    border: 1px solid {tokens["border_color"]};
    color: {tokens["text_primary"]};
    selection-background-color: {tokens["menu_item_selected"]};
    selection-color: #ffffff;
    outline: none;
    padding: 3px;
    border-radius: 4px;
}}
QComboBox QAbstractItemView::item {{
    min-height: 22px;
    padding: 2px 8px;
    border-radius: 3px;
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {tokens["bg_button_hover"]};
}}

/* NumberStepper Controls */
QFrame#numberStepper {{
    background-color: {tokens["bg_input"]};
    border: 1px solid {tokens["border_color"]};
    border-radius: 4px;
    min-height: 28px;
    max-height: 28px;
}}
QFrame#numberStepper:hover {{
    border-color: {tokens["border_light"]};
}}
QFrame#numberStepper[focused="true"] {{
    border-color: {tokens["accent_primary"]};
}}
QFrame#numberStepper QSpinBox {{
    border: none;
    background: transparent;
    color: {tokens["text_primary"]};
    min-height: 24px;
    max-height: 24px;
    font-size: 13px;
    padding: 0px 4px;
}}
QFrame#numberStepper QPushButton {{
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    font-size: 14px;
    font-weight: bold;
    border: none;
    border-radius: 3px;
    background-color: transparent;
    color: {tokens["text_secondary"]};
    padding: 0px;
}}
QFrame#numberStepper QPushButton:hover {{
    background-color: rgba(255, 255, 255, 0.08);
    color: {tokens["text_primary"]};
}}
QFrame#numberStepper QPushButton:pressed {{
    background-color: rgba(0, 0, 0, 0.15);
}}

/* Buttons */
QPushButton {{
    background-color: {tokens["bg_button"]};
    border: 1px solid {tokens["border_color"]};
    border-radius: 5px;
    color: {tokens["text_primary"]};
    padding: 6px 16px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {tokens["bg_button_hover"]};
    border: 1px solid {tokens["accent_primary"]};
    color: #ffffff;
}}
QPushButton:focus {{
    background-color: {tokens["bg_button_hover"]};
    border: 1.5px solid {tokens["accent_primary"]};
    color: #ffffff;
    outline: none;
}}
QPushButton:pressed {{
    background-color: {tokens["bg_button_pressed"]};
    border-color: {tokens["accent_pressed"]};
}}
QPushButton:disabled {{
    background-color: {tokens["bg_window"]};
    color: {tokens["text_secondary"]};
    border-color: {tokens["border_color"]};
}}

/* Primary Action Buttons */
QPushButton#primaryActionBtn {{
    background-color: {tokens["accent_primary"]};
    border: 1px solid {tokens["accent_hover"]};
    color: #ffffff;
    font-weight: bold;
}}
QPushButton#primaryActionBtn:hover {{
    background-color: {tokens["accent_hover"]};
    border: 1px solid #ffffff;
}}
QPushButton#primaryActionBtn:focus {{
    background-color: {tokens["accent_hover"]};
    border: 2px solid #ffffff;
    outline: none;
}}
QPushButton#primaryActionBtn:pressed {{
    background-color: {tokens["accent_pressed"]};
    border: 1px solid {tokens["accent_primary"]};
}}

/* Danger Action Buttons */
QPushButton#dangerActionBtn {{
    background-color: #7f1d1d;
    border: 1px solid #ef4444;
    color: #fee2e2;
    font-weight: bold;
}}
QPushButton#dangerActionBtn:hover {{
    background-color: #991b1b;
    border: 1px solid #fca5a5;
    color: #ffffff;
}}
QPushButton#dangerActionBtn:focus {{
    background-color: #991b1b;
    border: 2px solid #ffffff;
    outline: none;
}}
QPushButton#dangerActionBtn:pressed {{
    background-color: #5c1414;
    border: 1px solid #ef4444;
}}

/* Checkboxes */
QCheckBox {{
    color: {tokens["text_primary"]};
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {tokens["border_color"]};
    border-radius: 3px;
    background-color: {tokens["bg_input"]};
}}
QCheckBox::indicator:hover {{
    border-color: {tokens["border_light"]};
}}
QCheckBox::indicator:checked {{
    background-color: {tokens["accent_primary"]};
    border-color: {tokens["accent_hover"]};
    image: url("{checkmark_icon_path}");
}}
QCheckBox::indicator:checked:disabled {{
    background-color: {tokens["accent_pressed"]};
    border-color: {tokens["accent_primary"]};
    image: url("{checkmark_icon_path}");
}}

/* Top-Level Main Tabs: Option 4 Browser-Style Curved / Flowing Tabs */
QTabWidget#mainTabs::pane {{
    border: 1px solid {tokens["border_light"]};
    border-top: 1.5px solid {tokens["border_light"]};
    border-radius: 8px;
    background-color: {tokens["bg_window"]};
    top: -1px;
}}
QTabWidget#mainTabs > QTabBar {{
    background: transparent;
}}
QTabWidget#mainTabs > QTabBar::tab {{
    background-color: transparent;
    border: 1px solid transparent;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    padding: 9px 24px 8px 24px;
    margin-right: 4px;
    margin-top: 5px;
    color: {tokens["text_secondary"]};
    font-size: 13px;
    font-weight: 500;
}}
QTabWidget#mainTabs > QTabBar::tab:selected {{
    background-color: {tokens["bg_window"]};
    border: 1px solid {tokens["border_light"]};
    border-bottom: 2px solid {tokens["bg_window"]};
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    margin-top: 0px;
    padding-top: 11px;
    padding-bottom: 9px;
    color: #ffffff;
    font-weight: bold;
}}
QTabWidget#mainTabs > QTabBar::tab:hover:!selected {{
    background-color: {tokens["bg_subpanel"]};
    border: 1px solid {tokens["border_color"]};
    border-bottom: none;
    color: {tokens["text_primary"]};
}}

/* Secondary Subtabs: Curved Flowing Subtabs */
QTabWidget#recordingsSubTabs::pane,
QTabWidget#settingsSubTabs::pane,
QTabWidget#helpSubTabs::pane {{
    border: 1px solid {tokens["border_subtabs"]};
    border-top: 1.5px solid {tokens["border_light"]};
    border-radius: 6px;
    background-color: {tokens["bg_panel"]};
    padding: 6px;
    top: -1px;
}}
QTabWidget#recordingsSubTabs > QTabBar::tab,
QTabWidget#settingsSubTabs > QTabBar::tab,
QTabWidget#helpSubTabs > QTabBar::tab {{
    background-color: transparent;
    border: 1px solid transparent;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    padding: 6px 18px 5px 18px;
    margin-right: 4px;
    margin-top: 3px;
    color: {tokens["text_secondary"]};
    font-size: 12px;
    font-weight: 500;
}}
QTabWidget#recordingsSubTabs > QTabBar::tab:selected,
QTabWidget#settingsSubTabs > QTabBar::tab:selected,
QTabWidget#helpSubTabs > QTabBar::tab:selected {{
    background-color: {tokens["bg_panel"]};
    border: 1px solid {tokens["border_subtabs"]};
    border-bottom: 2px solid {tokens["bg_panel"]};
    margin-top: 0px;
    padding-top: 8px;
    color: #ffffff;
    font-weight: bold;
}}
QTabWidget#recordingsSubTabs > QTabBar::tab:hover:!selected,
QTabWidget#settingsSubTabs > QTabBar::tab:hover:!selected,
QTabWidget#helpSubTabs > QTabBar::tab:hover:!selected {{
    background-color: {tokens["bg_subpanel"]};
    border: 1px solid {tokens["border_color"]};
    border-bottom: none;
    color: {tokens["text_primary"]};
}}

/* Scroll area background inside settings */
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{
    background-color: {tokens["bg_panel"]};
    border: none;
}}

/* Group Boxes */
QGroupBox {{
    border: 1px solid {tokens["border_color"]};
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: bold;
    font-size: 13px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: {tokens["text_primary"]};
    font-size: 13px;
}}

/* High-Visibility Custom Scrollbars */
QScrollBar:vertical {{
    border: 1px solid {tokens["border_color"]};
    background: {tokens["scrollbar_bg"]};
    width: 14px;
    margin: 0px;
    border-radius: 7px;
}}
QScrollBar::handle:vertical {{
    background: {tokens["scrollbar_handle"]};
    min-height: 28px;
    border-radius: 6px;
    border: 1px solid {tokens["border_light"]};
}}
QScrollBar::handle:vertical:hover {{
    background: {tokens["scrollbar_handle_hover"]};
    border: 1px solid {tokens["scrollbar_handle_hover"]};
}}
QScrollBar::handle:vertical:pressed {{
    background: {tokens["scrollbar_handle_pressed"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    background: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    border: 1px solid {tokens["border_color"]};
    background: {tokens["scrollbar_bg"]};
    height: 14px;
    margin: 0px;
    border-radius: 7px;
}}
QScrollBar::handle:horizontal {{
    background: {tokens["scrollbar_handle"]};
    min-width: 28px;
    border-radius: 6px;
    border: 1px solid {tokens["border_light"]};
}}
QScrollBar::handle:horizontal:hover {{
    background: {tokens["scrollbar_handle_hover"]};
    border: 1px solid {tokens["scrollbar_handle_hover"]};
}}
QScrollBar::handle:horizontal:pressed {{
    background: {tokens["scrollbar_handle_pressed"]};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
    background: none;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}

/* Channel Order List Widget */
QListWidget#channelOrderList {{
    background-color: {tokens["bg_panel"]};
    border: 1px solid {tokens["border_color"]};
    border-radius: 6px;
    padding: 4px;
    font-size: 13px;
}}
QListWidget#channelOrderList::item {{
    background-color: {tokens["bg_subpanel"]};
    border: 1px solid {tokens["border_color"]};
    border-radius: 5px;
    padding: 6px 10px;
    margin-bottom: 3px;
    color: {tokens["text_primary"]};
    font-weight: 500;
}}
QListWidget#channelOrderList::item:hover {{
    background-color: {tokens["bg_button_hover"]};
    border-color: {tokens["border_light"]};
}}
QListWidget#channelOrderList::item:selected {{
    background-color: {tokens["accent_primary"]};
    border-color: {tokens["accent_hover"]};
    color: #ffffff;
    font-weight: bold;
}}

/* EPG Grid Table Styles */
QTableWidget#guideGridTable, QTableWidget#guideListTable {{
    background-color: {tokens["table_bg"]};
    gridline-color: {tokens["table_gridline"]};
    border: 1px solid {tokens["border_color"]};
    border-radius: 4px;
    font-size: 12px;
}}
QTableWidget#guideGridTable QHeaderView::section:horizontal {{
    background-color: {tokens["table_header_bg"]};
    color: {tokens["text_primary"]};
    font-weight: bold;
    font-size: 14px;
    padding: 6px;
    border: 1px solid {tokens["table_gridline"]};
    border-top: none;
}}
QTableWidget#guideGridTable QHeaderView::section:vertical {{
    background-color: transparent;
    color: #ffffff;
    font-weight: bold;
    font-size: 12px;
    padding: 0px;
    border: none;
}}

/* Modern Status & Progress Bar */
QProgressBar#statusBarProgressBar {{
    border: 1px solid {tokens["border_color"]};
    border-radius: 6px;
    background-color: {tokens["bg_input"]};
    text-align: center;
    color: #ffffff;
    font-size: 11px;
    font-weight: bold;
    min-height: 18px;
    max-height: 18px;
}}
QProgressBar#statusBarProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {tokens["accent_pressed"]}, stop:0.6 {tokens["accent_primary"]}, stop:1 {tokens["accent_hover"]});
    border-radius: 5px;
}}

/* Category Color Picker Tile */
QPushButton.category-color-tile {{
    border: 2px solid {tokens["border_light"]};
    border-radius: 6px;
    padding: 0px;
    margin: 0px;
}}
QPushButton.category-color-tile:hover {{
    border: 2px solid {tokens["accent_primary"]};
}}
QPushButton.category-color-tile:pressed {{
    border: 2px solid #ffffff;
}}

/* Custom Frameless Title Bar & Rounded Window */
QWidget#centralWidget[frameless_rounded="true"] {{
    background-color: {tokens["bg_window"]};
    border: 1px solid {tokens["border_color"]};
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    border-bottom-left-radius: 9px;
    border-bottom-right-radius: 9px;
}}

QWidget#customTitleBar {{
    background-color: {tokens["bg_panel"]};
    border-bottom: 1px solid {tokens["border_color"]};
    min-height: 34px;
    max-height: 34px;
}}
QWidget#customTitleBar[frameless_rounded="true"] {{
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}

QStatusBar {{
    background: transparent;
    min-height: 0px;
    max-height: 0px;
    border: none;
    margin: 0px;
    padding: 0px;
}}
QStatusBar::item {{
    border: none;
}}

QLabel#customTitleBarTitle {{
    color: {tokens["text_primary"]};
    font-size: 13px;
    font-weight: 600;
    padding-left: 6px;
    background: transparent;
}}

QToolButton.title-bar-btn {{
    background-color: transparent;
    border: none;
    border-radius: 4px;
    color: {tokens["text_secondary"]};
    font-size: 14px;
    font-weight: bold;
    min-width: 38px;
    max-width: 38px;
    min-height: 28px;
    max-height: 28px;
    margin: 3px 2px;
}}
QToolButton.title-bar-btn:hover {{
    background-color: {tokens["bg_button_hover"]};
    color: #ffffff;
}}
QToolButton.title-bar-btn:pressed {{
    background-color: {tokens["bg_button_pressed"]};
}}

QToolButton#titleBarCloseBtn:hover {{
    background-color: #dc2626;
    color: #ffffff;
}}
QToolButton#titleBarCloseBtn:pressed {{
    background-color: #b91c1c;
    color: #ffffff;
}}

/* Corner Resize Grip */
QSizeGrip#cornerResizeGrip {{
    width: 14px;
    height: 14px;
    background-color: transparent;
    margin: 0px 2px 2px 0px;
}}

/* Day Navigation Bar Arrows */
QWidget#dayNavBar QPushButton#dayNavPrevBtn, QWidget#dayNavBar QPushButton#dayNavNextBtn {{
    background-color: {tokens["bg_button"]};
    border: 1px solid {tokens["border_color"]};
    border-radius: 4px;
}}
QWidget#dayNavBar QPushButton#dayNavPrevBtn:hover, QWidget#dayNavBar QPushButton#dayNavNextBtn:hover {{
    background-color: {tokens["bg_button_hover"]};
    border: 1px solid {tokens["border_light"]};
}}
QWidget#dayNavBar QPushButton#dayNavPrevBtn:pressed, QWidget#dayNavBar QPushButton#dayNavNextBtn:pressed {{
    background-color: {tokens["bg_button_pressed"]};
}}
QWidget#dayNavBar QPushButton#dayNavPrevBtn:disabled, QWidget#dayNavBar QPushButton#dayNavNextBtn:disabled {{
    background-color: {tokens["bg_window"]};
    border: 1px solid {tokens["border_color"]};
}}

/* Guide Detail Text Box & Collapse Button */
QTextEdit#guideDetailText {{
    background-color: {tokens["bg_input"]};
    border: 1px solid {tokens["border_color"]};
    border-radius: 4px;
    color: {tokens["text_primary"]};
}}
QTextEdit#guideDetailText:focus {{
    border-color: {tokens["accent_primary"]};
}}
QPushButton#guideDetailCollapseBtn {{
    background-color: {tokens["bg_button"]};
    border: 1px solid {tokens["border_color"]};
    border-radius: 4px;
    color: {tokens["text_secondary"]};
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 500;
}}
QPushButton#guideDetailCollapseBtn:hover {{
    background-color: {tokens["bg_button_hover"]};
    border-color: {tokens["border_light"]};
    color: #ffffff;
}}
QPushButton#guideDetailCollapseBtn:pressed {{
    background-color: {tokens["bg_button_pressed"]};
}}

/* Custom Theme Action Icon Buttons */
QPushButton#saveThemePresetBtn, QPushButton#deleteThemePresetBtn, QPushButton#resetCatColorsBtn {{
    background-color: {tokens["bg_button"]};
    border: 1px solid {tokens["border_color"]};
    border-radius: 4px;
    padding: 2px;
}}
QPushButton#saveThemePresetBtn:hover, QPushButton#deleteThemePresetBtn:hover, QPushButton#resetCatColorsBtn:hover {{
    background-color: {tokens["bg_button_hover"]};
    border-color: {tokens["border_light"]};
}}
QPushButton#saveThemePresetBtn:pressed, QPushButton#deleteThemePresetBtn:pressed, QPushButton#resetCatColorsBtn:pressed {{
    background-color: {tokens["bg_button_pressed"]};
}}
QPushButton#deleteThemePresetBtn:disabled {{
    background-color: {tokens["bg_window"]};
    border-color: {tokens["border_color"]};
}}

/* Guide View Mode Toggle Buttons (Grid View vs List View) */
QPushButton#guideGridViewBtn, QPushButton#guideListViewBtn {{
    padding: 4px 12px;
    font-weight: bold;
    font-size: 11px;
    border: 1px solid {tokens["border_color"]};
    border-radius: 4px;
    background-color: {tokens["bg_button"]};
    color: {tokens["text_secondary"]};
}}
QPushButton#guideGridViewBtn:hover:!checked, QPushButton#guideListViewBtn:hover:!checked {{
    background-color: {tokens["bg_button_hover"]};
    border-color: {tokens["border_light"]};
    color: #ffffff;
}}
QPushButton#guideGridViewBtn:checked, QPushButton#guideListViewBtn:checked {{
    background-color: {tokens["accent_pressed"]};
    border: 1.5px solid {tokens["accent_hover"]};
    color: #ffffff;
}}
QPushButton#guideGridViewBtn:checked:hover, QPushButton#guideListViewBtn:checked:hover {{
    background-color: {tokens["accent_primary"]};
    border: 1.5px solid {tokens["accent_hover"]};
    color: #ffffff;
}}

/* Guide Filter Bar Utility Icon Buttons (Restore Dimensions & Maximize Guide) */
QPushButton#headerRestoreBtn, QPushButton#guideMaximizeBtn {{
    min-width: 28px;
    max-width: 28px;
    min-height: 24px;
    max-height: 24px;
    padding: 1px;
    border: 1px solid {tokens["border_color"]};
    border-radius: 4px;
    background-color: {tokens["bg_button"]};
}}
QPushButton#headerRestoreBtn:hover, QPushButton#guideMaximizeBtn:hover {{
    background-color: {tokens["bg_button_hover"]};
    border-color: {tokens["accent_hover"]};
}}
QPushButton#headerRestoreBtn:pressed, QPushButton#guideMaximizeBtn:pressed {{
    background-color: {tokens["bg_button_pressed"]};
}}

/* Guide Filter Bar Inputs & Labels */
QLabel#guideFilterLabel {{
    color: {tokens["text_secondary"]};
    font-weight: 600;
    font-size: 11px;
    padding-right: 2px;
}}
QComboBox#guideDateCombo, QComboBox#guideChannelCombo, QLineEdit#guideSearchInput {{
    background-color: {tokens["bg_button"]};
    border: 1px solid {tokens["border_light"]};
    border-radius: 4px;
    color: {tokens["text_primary"]};
    padding: 3px 8px;
    min-height: 20px;
    max-height: 20px;
    font-size: 12px;
}}
QComboBox#guideDateCombo:hover, QComboBox#guideChannelCombo:hover, QLineEdit#guideSearchInput:hover {{
    background-color: {tokens["bg_button_hover"]};
    border-color: {tokens["accent_hover"]};
}}
QComboBox#guideDateCombo:focus, QComboBox#guideChannelCombo:focus, QLineEdit#guideSearchInput:focus {{
    background-color: {tokens["bg_button_hover"]};
    border-color: {tokens["accent_primary"]};
}}
QLineEdit#guideSearchInput::placeholder {{
    color: {tokens["text_secondary"]};
}}
QLineEdit#guideSearchInput > QToolButton {{
    border: none;
    background: transparent;
    color: {tokens["text_secondary"]};
}}
"""

APP_STYLESHEET = build_app_stylesheet("midnight", "")


class TooltipDelayStyle(QProxyStyle):
    """Custom proxy style to add a small delay before hover tooltips appear."""
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return 1200  # 1.2 second delay before showing tooltips on hover
        if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
            return 0  # Put tooltip engine back to sleep immediately so moving between buttons requires full delay
        return super().styleHint(hint, option, widget, returnData)


def setup_dark_theme(app: Optional[QApplication], theme_key: str = "midnight"):
    if not app:
        return
    base_style = QStyleFactory.create("Fusion")
    if base_style:
        app.setStyle(TooltipDelayStyle(base_style))
    else:
        app.setStyle("Fusion")

    tokens = APP_THEMES.get(theme_key, APP_THEMES["midnight"])
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(tokens["bg_window"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(tokens["text_primary"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(tokens["bg_input"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(tokens["bg_window"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(tokens["tooltip_bg"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Text, QColor(tokens["text_primary"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(tokens["bg_button"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(tokens["text_primary"]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor(tokens["accent_primary"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens["accent_primary"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(tokens["text_secondary"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(tokens["text_secondary"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(tokens["text_secondary"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(tokens["text_secondary"]))
    app.setPalette(palette)
    stylesheet = build_app_stylesheet(theme_key, get_checkmark_icon_path())
    app.setStyleSheet(stylesheet)


class CustomTitleBar(QWidget):
    """Custom frameless window title bar with grab-and-move, title/icon, clock, and window controls."""

    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self.main_window = parent
        self.setObjectName("customTitleBar")
        self.setFixedHeight(34)
        self._drag_pos: Optional[QPoint] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 4, 0)
        layout.setSpacing(6)

        # Title Label
        self.title_lbl = QLabel("Kaffeine DVR & TV Guide")
        self.title_lbl.setObjectName("customTitleBarTitle")
        layout.addWidget(self.title_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch()

        # Window Controls: Minimize, Maximize/Restore, Close
        self.min_btn = QToolButton()
        self.min_btn.setObjectName("titleBarMinBtn")
        self.min_btn.setProperty("class", "title-bar-btn")
        self.min_btn.setText("—")
        self.min_btn.setToolTip("Minimize")
        self.min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.min_btn.clicked.connect(self.main_window.showMinimized)
        layout.addWidget(self.min_btn)

        self.max_btn = QToolButton()
        self.max_btn.setObjectName("titleBarMaxBtn")
        self.max_btn.setProperty("class", "title-bar-btn")
        self.max_btn.setText("▢")
        self.max_btn.setToolTip("Maximize")
        self.max_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.max_btn.clicked.connect(self._toggle_maximize_restore)
        layout.addWidget(self.max_btn)

        self.close_btn = QToolButton()
        self.close_btn.setObjectName("titleBarCloseBtn")
        self.close_btn.setProperty("class", "title-bar-btn")
        self.close_btn.setText("✕")
        self.close_btn.setToolTip("Close")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.main_window.close)
        layout.addWidget(self.close_btn)

    def _toggle_maximize_restore(self):
        if self.main_window.isMaximized():
            self.main_window.showNormal()
        else:
            self.main_window.showMaximized()
        self.update_max_button_icon()

    def update_max_button_icon(self):
        if self.main_window.isMaximized():
            self.max_btn.setText("❐")
            self.max_btn.setToolTip("Restore")
        else:
            self.max_btn.setText("▢")
            self.max_btn.setToolTip("Maximize")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Try native Wayland/X11 system move first for smooth desktop snapping
            win_handle = self.main_window.windowHandle()
            if win_handle and hasattr(win_handle, "startSystemMove"):
                if win_handle.startSystemMove():
                    event.accept()
                    return
            # Fallback manual drag calculation
            self._drag_pos = event.globalPosition().toPoint() - self.main_window.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            if not self.main_window.isMaximized():
                self.main_window.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize_restore()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class SilentStatusBar(QStatusBar):
    """Hidden dummy status bar that absorbs all showMessage calls without allocating window space."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.hide()

    def showMessage(self, text, timeout=0):
        pass  # Absorb text so nothing is displayed at the bottom of the window

    def setVisible(self, visible):
        super().setVisible(False)


class CornerResizeGrip(QSizeGrip):
    """Custom size grip that paints classic diagonal grip stripes matching application theme."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen_bg = QPen(QColor("#1e293b"), 1)
        pen_fg = QPen(QColor("#64748b"), 1)
        w, h = self.width(), self.height()
        for offset in (4, 8, 12):
            painter.setPen(pen_bg)
            painter.drawLine(w - offset - 1, h, w, h - offset - 1)
            painter.setPen(pen_fg)
            painter.drawLine(w - offset, h, w, h - offset)


class FramelessResizeFilter(QObject):
    """
    Enables smooth edge and corner window resizing from all 4 borders and 4 corners
    for frameless windows, utilizing native startSystemResize where available
    with manual geometry calculation fallback.
    """
    def __init__(self, target: "MainWindow", margin: int = 7):
        super().__init__(target)
        self.target = target
        self.margin = margin
        self._resizing = False
        self._resize_edge = 0
        self._drag_start_pos = QPoint()
        self._drag_start_geom = QRect()
        self.target.installEventFilter(self)

    def _get_edges(self, pos: QPoint) -> int:
        rect = self.target.rect()
        edges = 0
        if pos.x() <= self.margin:
            edges |= Qt.Edge.LeftEdge.value
        elif pos.x() >= rect.width() - self.margin:
            edges |= Qt.Edge.RightEdge.value
        if pos.y() <= self.margin:
            edges |= Qt.Edge.TopEdge.value
        elif pos.y() >= rect.height() - self.margin:
            edges |= Qt.Edge.BottomEdge.value
        return edges

    def _cursor_for_edges(self, edges: int):
        if (edges & Qt.Edge.LeftEdge.value and edges & Qt.Edge.TopEdge.value) or (edges & Qt.Edge.RightEdge.value and edges & Qt.Edge.BottomEdge.value):
            return Qt.CursorShape.SizeFDiagCursor
        if (edges & Qt.Edge.RightEdge.value and edges & Qt.Edge.TopEdge.value) or (edges & Qt.Edge.LeftEdge.value and edges & Qt.Edge.BottomEdge.value):
            return Qt.CursorShape.SizeBDiagCursor
        if edges & (Qt.Edge.LeftEdge.value | Qt.Edge.RightEdge.value):
            return Qt.CursorShape.SizeHorCursor
        if edges & (Qt.Edge.TopEdge.value | Qt.Edge.BottomEdge.value):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def eventFilter(self, obj, event):
        if obj != self.target or not getattr(self.target.config_mgr, "use_custom_title_bar", True):
            return super().eventFilter(obj, event)

        if self.target.isMaximized() or self.target.isFullScreen():
            if self._resizing:
                self._resizing = False
                self.target.unsetCursor()
            return super().eventFilter(obj, event)

        etype = event.type()
        if etype == QEvent.Type.MouseMove:
            if not self._resizing:
                edges = self._get_edges(event.pos())
                if edges:
                    self.target.setCursor(self._cursor_for_edges(edges))
                else:
                    self.target.unsetCursor()
            else:
                diff = event.globalPosition().toPoint() - self._drag_start_pos
                geom = QRect(self._drag_start_geom)
                min_w = self.target.minimumWidth() or 400
                min_h = self.target.minimumHeight() or 300

                if self._resize_edge & Qt.Edge.RightEdge.value:
                    geom.setWidth(max(min_w, self._drag_start_geom.width() + diff.x()))
                elif self._resize_edge & Qt.Edge.LeftEdge.value:
                    new_w = max(min_w, self._drag_start_geom.width() - diff.x())
                    geom.setLeft(self._drag_start_geom.right() - new_w)

                if self._resize_edge & Qt.Edge.BottomEdge.value:
                    geom.setHeight(max(min_h, self._drag_start_geom.height() + diff.y()))
                elif self._resize_edge & Qt.Edge.TopEdge.value:
                    new_h = max(min_h, self._drag_start_geom.height() - diff.y())
                    geom.setTop(self._drag_start_geom.bottom() - new_h)

                self.target.setGeometry(geom)
                return True

        elif etype == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            edges = self._get_edges(event.pos())
            if edges:
                wh = self.target.windowHandle()
                if wh and hasattr(wh, "startSystemResize"):
                    if wh.startSystemResize(Qt.Edge(edges)):
                        return True
                self._resizing = True
                self._resize_edge = edges
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_start_geom = self.target.geometry()
                return True

        elif etype == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self._resizing:
                self._resizing = False
                self._resize_edge = 0
                self.target.unsetCursor()
                return True

        return super().eventFilter(obj, event)


class MainWindow(QMainWindow):
    def __init__(self, config_mgr: Optional[ConfigManager] = None):
        super().__init__()
        self.config_mgr = config_mgr or ConfigManager()
        self.setWindowTitle("Kaffeine DVR & TV Guide")
        self.setWindowIcon(get_app_icon())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if getattr(self.config_mgr, "use_custom_title_bar", True):
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        app_inst = QApplication.instance()
        if app_inst:
            setup_dark_theme(app_inst, self.config_mgr.app_theme)

        self.settings = QSettings("KaffeineDVR", "TVGuide")
        saved_w = self.settings.value("custom_window_width", type=int)
        saved_h = self.settings.value("custom_window_height", type=int)
        if saved_w and saved_h and saved_w >= 400 and saved_h >= 300:
            self.resize(saved_w, saved_h)
        else:
            geo = self.settings.value("geometry")
            if geo and isinstance(geo, QByteArray) and not geo.isEmpty():
                self.restoreGeometry(geo)
            else:
                self.resize(1100, 750)

        self.dbus_client = KaffeineDbusClient()
        self.queue_mgr = QueueManager(data_dir=self.config_mgr.data_dir)
        self.guide_service = GuideService(data_dir=self.config_mgr.data_dir, channel_map=self.config_mgr.channel_map, config_mgr=self.config_mgr)
        self.rules_engine = RulesEngine(self.config_mgr, self.dbus_client, self.guide_service)
        self.watcher = Watcher(self.dbus_client, self.queue_mgr)
        self.storage_mgr = StorageManager(self.config_mgr, self.queue_mgr)
        self.day_nav_offset = 0
        self._active_timeshift = None
        self.selected_grid_program = None
        self._last_clicked_guide_list_row = -1

        self.init_ui()
        self.setup_timers()
        self.refresh_all(on_startup=True)

        # Ensure mouse wheel scrolling on setting input widgets (spinboxes, combos)
        # doesn't accidentally mutate values while scrolling through settings pages
        app = QApplication.instance()
        if app and not getattr(app, "_wheel_filter_installed", False):
            self._wheel_filter = NoWheelEventFilter(app)
            app.installEventFilter(self._wheel_filter)
            app._wheel_filter_installed = True

        # Check for first-run setup wizard for new users
        QTimer.singleShot(600, self.check_first_run)

        # Run health check quietly on startup to populate settings dashboard
        QTimer.singleShot(1500, lambda: self.test_all_sources_health(silent=True))

        # Check monthly updates if enabled
        QTimer.singleShot(2500, self.check_monthly_updates_on_startup)

    def init_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Muted update notification badge (placed in action bar just above status bar)
        self.update_badge_widget = self._create_update_badge_widget()

        # Custom Frameless Title Bar (placed at the very top above main tabs)
        self.custom_title_bar = CustomTitleBar(self)
        main_layout.addWidget(self.custom_title_bar)
        use_custom = getattr(self.config_mgr, "use_custom_title_bar", True)
        self.custom_title_bar.setVisible(use_custom)

        # Main Tabs
        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.addTab(self.create_guide_tab(), "Web TV Guide Browser")
        self.tabs.addTab(self.create_recordings_tab(), "Recordings Schedule")
        self.tabs.addTab(self.create_settings_tab(), "Settings")
        self.tabs.addTab(self.create_help_tab(), "Help and Information")
        self.tabs.currentChanged.connect(self._on_main_tab_changed)

        # Corner Clock Widget for Tabs (used when native OS title bar is active)
        self.clock_widget = self._create_clock_widget()
        self.tabs.setCornerWidget(self.clock_widget, Qt.Corner.TopRightCorner)
        self._update_clock_display()
        main_layout.addWidget(self.tabs)

        # Hidden status handler that absorbs status messages without allocating window layout space
        self.status_bar = SilentStatusBar(self)
        self.setStatusBar(None)

        # Bottom-right corner resize grip indicator
        self.corner_grip = CornerResizeGrip(self)
        self.corner_grip.setObjectName("cornerResizeGrip")
        self.corner_grip.raise_()

        # Frameless edge and corner resize filter (resizes from all edges and corners)
        self._resize_filter = FramelessResizeFilter(self)

        self._update_window_frame_styling()

        if getattr(self.config_mgr, "guide_maximized", False):
            self.toggle_guide_maximized()

    def _create_clock_widget(self) -> QWidget:
        clock_frame = QFrame()
        clock_frame.setObjectName("topCornerClockFrame")
        clock_frame.setStyleSheet(
            "QFrame#topCornerClockFrame { "
            "background: transparent; border: none; "
            "margin-right: 8px; margin-top: 2px; margin-bottom: 2px; }"
        )
        layout = QHBoxLayout(clock_frame)
        layout.setContentsMargins(0, 0, 0, 0)
        self.clock_label = QLabel()
        self.clock_label.setObjectName("topCornerClockLabel")
        layout.addWidget(self.clock_label)
        return clock_frame

    def _update_clock_display(self):
        is_shown = getattr(self.config_mgr, "show_clock", True)

        # Always display clock in top-right corner of tabs
        if hasattr(self, "clock_widget"):
            self.clock_widget.setVisible(is_shown)

        if not is_shown:
            return

        now = datetime.now()
        col_hex = self.config_mgr.category_colors.get("clock", DEFAULT_CATEGORY_COLORS.get("clock", "#38bdf8"))
        font_sz = getattr(self.config_mgr, "clock_font_size", 11)
        clock_str = now.strftime("%a, %b %-d  %-I:%M %p")
        style = f"color: {col_hex}; font-size: {font_sz}px; font-weight: bold; padding: 2px 4px; background: transparent;"

        if hasattr(self, "clock_label"):
            if getattr(self, "_last_clock_style", None) != style:
                self.clock_label.setStyleSheet(style)
                self._last_clock_style = style
            if getattr(self, "_last_clock_str", None) != clock_str:
                self.clock_label.setText(clock_str)
                self._last_clock_str = clock_str

    def _create_update_badge_widget(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("updateBadge")
        badge_layout = QHBoxLayout(widget)
        badge_layout.setContentsMargins(0, 3, 4, 0)
        badge_layout.setSpacing(6)
        widget.setStyleSheet("QWidget#updateBadge { background: transparent; border: none; }")

        self.update_badge_btn = QPushButton("Update Available")
        self.update_badge_btn.setFlat(True)
        self.update_badge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_badge_btn.setToolTip("Click to view details and install update in Settings")
        self.update_badge_btn.setStyleSheet(
            "QPushButton { color: #52b774; font-size: 13px; font-weight: 600; border: none; padding: 0; margin: 0; background: transparent; }"
            "QPushButton:hover { color: #7de89f; text-decoration: underline; }"
        )
        self.update_badge_btn.clicked.connect(self.navigate_to_updates_tab)
        badge_layout.addWidget(self.update_badge_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.update_badge_dismiss_btn = QToolButton()
        self.update_badge_dismiss_btn.setText("x")
        self.update_badge_dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_badge_dismiss_btn.setToolTip("Dismiss update notice")
        self.update_badge_dismiss_btn.setStyleSheet(
            "QToolButton { color: #788898; font-size: 15px; font-weight: bold; border: none; background: transparent; padding: 0 4px 3px 0; margin: 0; }"
            "QToolButton:hover { color: #d0d8e2; }"
        )
        self.update_badge_dismiss_btn.clicked.connect(self.dismiss_update_badge)
        badge_layout.addWidget(self.update_badge_dismiss_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        widget.setVisible(False)
        return widget

    # ------------------ TAB 1: RECORDINGS ------------------
    def create_recordings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self.recordings_subtabs = QTabWidget()
        self.recordings_subtabs.setObjectName("recordingsSubTabs")

        # ----- SUBTAB 1: Active Schedule -----
        active_widget = QWidget()
        active_layout = QVBoxLayout(active_widget)

        # Controls bar for Active Schedule
        ctrl_bar = QHBoxLayout()
        self.refresh_rec_btn = QPushButton("Refresh Schedule")
        self.refresh_rec_btn.clicked.connect(self.refresh_recordings)
        ctrl_bar.addWidget(self.refresh_rec_btn)

        self.add_rec_btn = QPushButton("Add Manual Recording")
        self.add_rec_btn.clicked.connect(self.add_manual_recording)
        ctrl_bar.addWidget(self.add_rec_btn)

        self.adjust_buffer_btn = QPushButton("Adjust Buffer...")
        self.adjust_buffer_btn.clicked.connect(self.adjust_selected_buffer)
        ctrl_bar.addWidget(self.adjust_buffer_btn)

        self.protect_rec_btn = QPushButton("Protect / Keep Forever")
        self.protect_rec_btn.clicked.connect(self.toggle_protect_selected_recording)
        ctrl_bar.addWidget(self.protect_rec_btn)

        ctrl_bar.addStretch()

        self.cancel_rec_btn = QPushButton("Cancel Selected Recording")
        self.cancel_rec_btn.setStyleSheet("color: #ff5252; font-weight: bold;")
        self.cancel_rec_btn.clicked.connect(self.cancel_selected_recording)
        ctrl_bar.addWidget(self.cancel_rec_btn)

        active_layout.addLayout(ctrl_bar)

        # Active Schedule Table
        self.rec_table = QTableWidget()
        self.rec_table.setColumnCount(6)
        self.rec_table.setHorizontalHeaderLabels(["Title", "Schedule", "Channel", "Duration", "Status", "Retain"])
        for i in range(6):
            self.rec_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self.rec_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.rec_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rec_table.itemDoubleClicked.connect(self._on_rec_table_double_clicked)
        active_layout.addWidget(self.rec_table)
        self.rec_table_resize_filter = TableViewportResizeFilter(self._adjust_table_columns, self)
        self.rec_table.viewport().installEventFilter(self.rec_table_resize_filter)

        self.recordings_subtabs.addTab(active_widget, "Active Schedule")
        self.recordings_subtabs.addTab(self.create_rules_tab(), "Auto-Record Rules")

        # ----- SUBTAB 3: History -----
        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)

        hist_ctrl_bar = QHBoxLayout()
        self.refresh_hist_btn = QPushButton("Refresh History")
        self.refresh_hist_btn.clicked.connect(self.refresh_history)
        hist_ctrl_bar.addWidget(self.refresh_hist_btn)

        hist_ctrl_bar.addSpacing(10)
        hist_limit_lbl = QLabel("Max entries to keep:")
        hist_limit_lbl.setStyleSheet("font-size: 12px; color: #a4b0c2;")
        hist_ctrl_bar.addWidget(hist_limit_lbl)

        self.hist_max_spin = NumberStepper()
        self.hist_max_spin.setRange(5, 500)
        self.hist_max_spin.setSingleStep(5)
        self.hist_max_spin.setValue(self.config_mgr.max_history_entries)
        self.hist_max_spin.setFixedWidth(130)
        self.hist_max_spin.valueChanged.connect(self.on_max_history_changed)
        hist_ctrl_bar.addWidget(self.hist_max_spin)

        hist_ctrl_bar.addSpacing(16)
        self.clear_hist_entry_btn = QPushButton("Clear Entry")
        self.clear_hist_entry_btn.clicked.connect(self.clear_selected_history_entry)
        hist_ctrl_bar.addWidget(self.clear_hist_entry_btn)

        self.clear_all_hist_btn = QPushButton("Clear All")
        self.clear_all_hist_btn.setStyleSheet("color: #d9534f;")
        self.clear_all_hist_btn.clicked.connect(self.clear_all_history)
        hist_ctrl_bar.addWidget(self.clear_all_hist_btn)

        hist_ctrl_bar.addStretch()
        history_layout.addLayout(hist_ctrl_bar)

        # History Table
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["Title", "Date / Time", "Channel", "Runtime"])
        for i in range(4):
            self.history_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        history_layout.addWidget(self.history_table)
        self.history_table_resize_filter = TableViewportResizeFilter(self._adjust_table_columns, self)
        self.history_table.viewport().installEventFilter(self.history_table_resize_filter)

        self.recordings_subtabs.addTab(history_widget, "History")
        self.recordings_subtabs.currentChanged.connect(lambda: self._adjust_table_columns())

        layout.addWidget(self.recordings_subtabs)
        return widget

    # ------------------ TAB 2: TV GUIDE BROWSER ------------------
    def create_guide_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Filter & View Mode Bar
        filter_bar = QHBoxLayout()

        # View Mode Toggle: Grid View vs List View
        self.guide_view_group = QButtonGroup(self)
        self.grid_view_btn = QPushButton("Grid View")
        self.grid_view_btn.setObjectName("guideGridViewBtn")
        self.grid_view_btn.setCheckable(True)
        self.list_view_btn = QPushButton("List View")
        self.list_view_btn.setObjectName("guideListViewBtn")
        self.list_view_btn.setCheckable(True)
        self.guide_view_group.addButton(self.grid_view_btn, 0)
        self.guide_view_group.addButton(self.list_view_btn, 1)

        # Default to Grid View
        saved_view = self.settings.value("guide_view_mode", "grid")
        if saved_view == "list":
            self.list_view_btn.setChecked(True)
        else:
            self.grid_view_btn.setChecked(True)

        self.grid_view_btn.clicked.connect(self._on_guide_view_toggled)
        self.list_view_btn.clicked.connect(self._on_guide_view_toggled)

        filter_bar.addWidget(self.grid_view_btn)
        filter_bar.addWidget(self.list_view_btn)
        filter_bar.addSpacing(14)

        # Date & Channel Dropdowns immediately to the right of List View
        self.date_label = QLabel("Date:")
        self.date_label.setObjectName("guideFilterLabel")
        filter_bar.addWidget(self.date_label)
        self.guide_date_combo = ThemedComboBox()
        self.guide_date_combo.setObjectName("guideDateCombo")
        self.guide_date_combo.addItem("All Upcoming", None)
        today = date.today()
        for i in range(14):
            d = today + timedelta(days=i)
            label = "Today" if i == 0 else ("Tomorrow" if i == 1 else d.strftime("%a, %b %d"))
            self.guide_date_combo.addItem(label, d.strftime("%Y-%m-%d"))
        self.guide_date_combo.setCurrentIndex(1)
        self.guide_date_combo.currentIndexChanged.connect(self.filter_guide)
        filter_bar.addWidget(self.guide_date_combo)
        filter_bar.addSpacing(6)

        self.channel_label = QLabel("Channel:")
        self.channel_label.setObjectName("guideFilterLabel")
        filter_bar.addWidget(self.channel_label)
        self.guide_channel_combo = ThemedComboBox()
        self.guide_channel_combo.setObjectName("guideChannelCombo")
        self.guide_channel_combo.addItem("All")
        channels = self.config_mgr.get_ordered_channels()
        self.guide_channel_combo.addItems(channels)
        self.guide_channel_combo.currentIndexChanged.connect(self.filter_guide)
        filter_bar.addWidget(self.guide_channel_combo)

        # Center Time Jump Controls with symmetrical stretches
        filter_bar.addStretch(1)

        self.jump_now_btn = QPushButton("Jump to Now")
        self.jump_now_btn.setObjectName("guideJumpNowBtn")
        self.jump_now_btn.clicked.connect(self.jump_guide_to_now)
        filter_bar.addWidget(self.jump_now_btn)

        self.jump_prime_btn = QPushButton("Prime Time (7 PM)")
        self.jump_prime_btn.setObjectName("guideJumpPrimeBtn")
        self.jump_prime_btn.clicked.connect(self.jump_guide_to_primetime)
        filter_bar.addWidget(self.jump_prime_btn)

        filter_bar.addStretch(1)

        # Guide Font / Box Size Zoom (+ / -) Controls
        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.setObjectName("guideZoomOutBtn")
        self.zoom_out_btn.setToolTip("Decrease guide font and box size")
        self.zoom_out_btn.clicked.connect(self.zoom_out_guide)
        filter_bar.addWidget(self.zoom_out_btn)

        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setObjectName("guideZoomInBtn")
        self.zoom_in_btn.setToolTip("Increase guide font and box size")
        self.zoom_in_btn.clicked.connect(self.zoom_in_guide)
        filter_bar.addWidget(self.zoom_in_btn)

        # Search box anchored to the far right
        self.search_label = QLabel("Search:")
        self.search_label.setObjectName("guideFilterLabel")
        filter_bar.addWidget(self.search_label)
        self.guide_search_input = QLineEdit()
        self.guide_search_input.setObjectName("guideSearchInput")
        self.guide_search_input.setPlaceholderText("Filter shows...")
        self.guide_search_input.setClearButtonEnabled(True)
        self.guide_search_input.setFixedWidth(160)
        self.guide_search_input.textChanged.connect(self.filter_guide)
        filter_bar.addWidget(self.guide_search_input)

        app_theme = getattr(self.config_mgr, "app_theme", "midnight") if hasattr(self, "config_mgr") and self.config_mgr else "midnight"
        init_tokens = APP_THEMES.get(app_theme, APP_THEMES["midnight"])

        # Restore Saved Window Size Button
        self.header_restore_btn = QPushButton()
        self.header_restore_btn.setObjectName("headerRestoreBtn")
        self.header_restore_btn.setToolTip("Restore saved window dimensions (also accessible in Settings)")
        self.header_restore_btn.setIcon(self._create_restore_window_icon(init_tokens.get("accent_hover")))
        self.header_restore_btn.setIconSize(QSize(19, 19))
        self.header_restore_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.header_restore_btn.clicked.connect(self.restore_saved_window_size)
        filter_bar.addWidget(self.header_restore_btn)

        # Maximize / Expand TV Guide Button
        self.guide_maximize_btn = QPushButton()
        self.guide_maximize_btn.setObjectName("guideMaximizeBtn")
        self.guide_maximize_btn.setToolTip("Maximize guide to fill window")
        self.guide_maximize_btn.setIcon(self._create_guide_maximize_icon(init_tokens.get("accent_primary")))
        self.guide_maximize_btn.setIconSize(QSize(19, 19))
        self.guide_maximize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.guide_maximize_btn.clicked.connect(self.toggle_guide_maximized)
        filter_bar.addWidget(self.guide_maximize_btn)

        layout.addLayout(filter_bar)

        # Guide Views Container (Stacked: 0 = Grid View, 1 = List View)
        self.guide_stack = QStackedWidget()

        # 1. Traditional EPG Grid Table
        self.guide_grid_table = GuideGridTable(main_window=self)
        self.guide_grid_table.setObjectName("guideGridTable")
        self.guide_grid_header = GuideGridHeader(Qt.Orientation.Horizontal, self.guide_grid_table, main_window=self)
        self.guide_grid_table.setHorizontalHeader(self.guide_grid_header)
        self.guide_grid_vheader = GuideGridVerticalHeader(self.guide_grid_table, main_window=self)
        self.guide_grid_table.setVerticalHeader(self.guide_grid_vheader)
        self.guide_grid_vheader.sectionClicked.connect(self._on_grid_channel_header_clicked)
        self.guide_grid_table.setColumnCount(56)
        grid_headers = []
        for h in range(24):
            for m in (0, 30):
                grid_headers.append(f"{h%12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}")
        for h in range(4):
            for m in (0, 30):
                if h == 0 and m == 0:
                    grid_headers.append("12:00 AM (+1)")
                else:
                    grid_headers.append(f"{h%12 or 12}:{m:02d} AM")
        self.guide_grid_table.setHorizontalHeaderLabels(grid_headers)
        self.guide_grid_table.horizontalHeader().setDefaultSectionSize(200)
        self.guide_grid_table.horizontalHeader().setHighlightSections(False)
        self.guide_grid_table.verticalHeader().setDefaultSectionSize(62)
        self.guide_grid_table.verticalHeader().setHighlightSections(False)
        self.grid_tile_delegate = ProgramTileDelegate(self.guide_grid_table, config_mgr=self.config_mgr)
        self.guide_grid_table.setItemDelegate(self.grid_tile_delegate)
        self.guide_grid_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.guide_grid_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.guide_grid_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.guide_grid_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.guide_grid_table.main_window = self
        self.grid_pan_filter = GridPanFilter(self.guide_grid_table, main_window=self)
        self.guide_grid_table.installEventFilter(self.grid_pan_filter)
        self.guide_grid_table.viewport().installEventFilter(self.grid_pan_filter)
        self.guide_grid_table.horizontalHeader().viewport().installEventFilter(self.grid_pan_filter)
        self.grid_resize_filter = TableViewportResizeFilter(self._apply_guide_zoom, self)
        self.guide_grid_table.viewport().installEventFilter(self.grid_resize_filter)
        self.guide_grid_table.horizontalScrollBar().valueChanged.connect(self._on_grid_horizontal_scroll)
        self.guide_grid_table.cellClicked.connect(self.on_grid_cell_clicked)
        self.guide_grid_table.cellDoubleClicked.connect(self.on_grid_cell_double_clicked)
        self.guide_grid_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.guide_grid_table.customContextMenuRequested.connect(self._on_guide_grid_context_menu)
        self.guide_stack.addWidget(self.guide_grid_table)

        # 2. Existing Detailed List Table
        self.guide_table = QTableWidget()
        self.guide_table.setObjectName("guideListTable")
        self.guide_table.setShowGrid(True)
        self.guide_table.setColumnCount(6)
        self.guide_table.setHorizontalHeaderLabels(["REC", "Start Time", "Channel", "Duration", "Show Title", "Episode Title"])
        hdr = self.guide_table.horizontalHeader()
        for c in range(6):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionsMovable(True)
        saved_hdr = self.settings.value("guide_table_header_state")
        if saved_hdr:
            try:
                hdr.restoreState(saved_hdr)
            except Exception:
                pass
        hdr.sectionResized.connect(self._save_guide_table_header_state)
        hdr.sectionMoved.connect(self._save_guide_table_header_state)
        self.guide_table.verticalHeader().setVisible(False)
        self.guide_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.guide_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.guide_list_click_filter = GuideListClickFilter(self.guide_table, main_window=self)
        self.guide_table.installEventFilter(self.guide_list_click_filter)
        self.guide_table.viewport().installEventFilter(self.guide_list_click_filter)
        self.guide_table.cellClicked.connect(self.on_guide_list_cell_clicked)
        self.guide_table.itemSelectionChanged.connect(self.on_guide_selection_changed)
        self.guide_table.itemDoubleClicked.connect(self.on_guide_table_double_clicked)
        self.guide_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.guide_table.customContextMenuRequested.connect(self._on_guide_list_context_menu)
        self.guide_stack.addWidget(self.guide_table)

        # Initialize guide zoom levels from settings (-3 to +5, default 0)
        legacy_zoom = self.settings.value("guide_zoom_level", 0, type=int)
        self.guide_grid_zoom_level = self.settings.value("guide_grid_zoom_level", legacy_zoom, type=int)
        self.guide_list_zoom_level = self.settings.value("guide_list_zoom_level", legacy_zoom, type=int)
        self.guide_zoom_level = self.guide_grid_zoom_level
        self._apply_guide_zoom()

        # Set initial stack page
        self.guide_stack.setCurrentIndex(1 if saved_view == "list" else 0)
        self._update_time_jump_buttons_visibility()
        self._update_zoom_buttons_state()

        guide_container = QWidget()
        guide_container_layout = QVBoxLayout(guide_container)
        guide_container_layout.setContentsMargins(0, 0, 0, 0)
        guide_container_layout.setSpacing(4)
        guide_container_layout.addWidget(self.guide_stack, 1)

        self.day_nav_bar = self._create_day_nav_bar()
        guide_container_layout.addWidget(self.day_nav_bar, 0)

        layout.addWidget(guide_container, 1)

        # Detail Panel
        detail_widget = QWidget()
        self.guide_detail_widget = detail_widget
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.setSpacing(4)

        # Header row: left spacer, centered title, and compact collapse button on the right
        detail_header_row = QHBoxLayout()
        detail_header_row.setContentsMargins(0, 0, 0, 0)
        detail_header_row.setSpacing(8)

        # Left spacer with same width as the collapse button on the right to guarantee true horizontal centering of title
        self.guide_detail_left_spacer = QWidget()
        self.guide_detail_left_spacer.setFixedSize(30, 24)
        detail_header_row.addWidget(self.guide_detail_left_spacer)

        self.guide_detail_title = QLabel("Select a program to view details")
        self.guide_detail_title.setObjectName("guideDetailTitle")
        self.guide_detail_title.setStyleSheet("font-weight: bold; font-size: 16px;")
        self.guide_detail_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_header_row.addWidget(self.guide_detail_title, 1)

        self.guide_detail_collapse_btn = QPushButton("▼")
        self.guide_detail_collapse_btn.setObjectName("guideDetailCollapseBtn")
        self.guide_detail_collapse_btn.setFixedSize(30, 24)
        self.guide_detail_collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.guide_detail_collapse_btn.setToolTip("Collapse description panel")
        self.guide_detail_collapse_btn.clicked.connect(self.toggle_guide_detail_collapsed)
        detail_header_row.addWidget(self.guide_detail_collapse_btn)

        detail_layout.addLayout(detail_header_row)

        self.guide_detail_text = QTextEdit()
        self.guide_detail_text.setObjectName("guideDetailText")
        self.guide_detail_text.setReadOnly(True)
        font = self.guide_detail_text.font()
        font.setPixelSize(16)
        self.guide_detail_text.setFont(font)
        self.guide_detail_text.setStyleSheet("font-size: 16px; line-height: 1.35; padding: 6px 10px;")
        self._update_guide_detail_box_height()
        self._apply_guide_detail_collapsed_state()
        detail_layout.addWidget(self.guide_detail_text)

        action_bar = QHBoxLayout()

        self.record_guide_btn = QPushButton("Record Program")
        self.record_guide_btn.setStyleSheet("font-weight: bold;")
        self.record_guide_btn.clicked.connect(self.record_selected_guide_item)
        action_bar.addWidget(self.record_guide_btn)

        self.cancel_guide_btn = QPushButton("Cancel Recording")
        self.cancel_guide_btn.setStyleSheet("color: #ff5252; font-weight: bold;")
        self.cancel_guide_btn.setVisible(False)
        self.cancel_guide_btn.clicked.connect(self.cancel_selected_guide_recording)
        action_bar.addWidget(self.cancel_guide_btn)

        self.add_rule_guide_btn = QPushButton("Record Series")
        self.add_rule_guide_btn.clicked.connect(self.add_rule_from_selected_guide_item)
        action_bar.addWidget(self.add_rule_guide_btn)

        self.watch_guide_btn = QPushButton("Watch Live")
        self.watch_guide_btn.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: #ffffff; padding: 4px 12px;")
        self.watch_guide_btn.setVisible(False)
        self.watch_guide_btn.clicked.connect(self.watch_or_tune_selected_guide_item)
        action_bar.addWidget(self.watch_guide_btn)

        # Ensure all four primary guide action buttons share identical width
        for btn in (self.record_guide_btn, self.cancel_guide_btn, self.add_rule_guide_btn, self.watch_guide_btn):
            btn.setFixedWidth(168)

        self.stop_timeshift_btn = QPushButton("Stop Timeshift (Free Tuner)")
        self.stop_timeshift_btn.setStyleSheet("font-weight: bold; background-color: #c62828; color: #ffffff; padding: 4px 12px;")
        self.stop_timeshift_btn.setVisible(False)
        self.stop_timeshift_btn.clicked.connect(lambda: self.stop_timeshift_session(user_initiated=True))
        action_bar.addWidget(self.stop_timeshift_btn)

        self.adjust_buffer_guide_btn = QPushButton("Adjust Buffer...")
        self.adjust_buffer_guide_btn.setStyleSheet("font-weight: bold;")
        self.adjust_buffer_guide_btn.setVisible(False)
        self.adjust_buffer_guide_btn.clicked.connect(self.record_selected_guide_item)
        action_bar.addWidget(self.adjust_buffer_guide_btn)

        action_bar.addStretch()
        action_bar.addWidget(self.update_badge_widget)
        detail_layout.addLayout(action_bar)
        layout.addWidget(detail_widget, 0)
        return widget

    # ------------------ TAB 3: AUTO-RECORD RULES ------------------
    def create_rules_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        ctrl_bar = QHBoxLayout()
        self.add_rule_btn = QPushButton("Add New Rule")
        self.add_rule_btn.clicked.connect(self.add_rule_dialog)
        ctrl_bar.addWidget(self.add_rule_btn)

        self.edit_rule_btn = QPushButton("Edit Rule")
        self.edit_rule_btn.clicked.connect(self.edit_rule_dialog)
        ctrl_bar.addWidget(self.edit_rule_btn)

        self.remove_rule_btn = QPushButton("Remove Selected Rule")
        self.remove_rule_btn.clicked.connect(self.remove_selected_rule)
        ctrl_bar.addWidget(self.remove_rule_btn)

        self.run_rules_btn = QPushButton("Run Rules and Schedule Now")
        self.run_rules_btn.clicked.connect(self.run_rules)
        ctrl_bar.addWidget(self.run_rules_btn)

        ctrl_bar.addStretch()
        layout.addLayout(ctrl_bar)

        self.rules_table = QTableWidget()
        self.rules_table.setColumnCount(5)
        self.rules_table.setHorizontalHeaderLabels(["ID", "Title / Keyword", "Channel", "End Buffer", "Enabled"])
        self.rules_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.rules_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.rules_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rules_table.itemDoubleClicked.connect(lambda item: self.edit_rule_dialog())
        layout.addWidget(self.rules_table)

        return widget

    # ------------------ TAB 4: SETTINGS (SUB-CATEGORIZED) ------------------
    def create_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.settings_subtabs = QTabWidget()
        self.settings_subtabs.setObjectName("settingsSubTabs")
        self.settings_subtabs.addTab(self.create_settings_automation_tab(), "General")
        self.settings_subtabs.addTab(self.create_settings_channels_tab(), "Channel Source")
        self.settings_subtabs.addTab(self.create_settings_guide_tab(), "Guide Sources and Health")
        self.settings_subtabs.addTab(self.create_settings_updates_tab(), "Updates and Maintenance")
        layout.addWidget(self.settings_subtabs)

        return widget

    # Subcategory 1: Guide Sources and Health
    def create_settings_guide_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)

        # 1. Active Provider Selector
        prov_box = QGroupBox("Active Guide Provider")
        prov_layout = QHBoxLayout(prov_box)
        prov_layout.addWidget(QLabel("Primary Guide Engine:"))

        self.provider_combo = ThemedComboBox()
        self.provider_combo.addItem("Free Hybrid (TVMaze National + TV Passport Regional)", "hybrid")
        self.provider_combo.addItem("TV Passport (Web Station Directory)", "tvpassport")
        self.provider_combo.addItem("Custom XMLTV Feed (Local File or Remote URL)", "xmltv")
        self.provider_combo.addItem("Schedules Direct (Paid Official Gracenote API)", "schedules_direct")

        # Set current provider index
        curr_prov = self.config_mgr.guide_provider
        idx = self.provider_combo.findData(curr_prov)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        prov_layout.addWidget(self.provider_combo)

        save_prov_btn = QPushButton("Save Active Provider")
        save_prov_btn.setObjectName("primaryActionBtn")
        save_prov_btn.clicked.connect(self.save_active_provider)
        prov_layout.addWidget(save_prov_btn)
        prov_layout.addStretch()
        layout.addWidget(prov_box)

        # 2. Live Health Monitor
        health_box = QGroupBox("Guide Sources Health and Connectivity Monitor")
        health_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        health_layout = QVBoxLayout(health_box)
        health_layout.setContentsMargins(10, 0, 10, 8)
        health_layout.setSpacing(4)

        monitor_desc = QLabel(
            "Live monitoring of configured TV guide backends. Check status codes, latency, and program contributions."
        )
        monitor_desc.setStyleSheet("color: #6c757d; font-size: 11px;")
        health_layout.addWidget(monitor_desc)

        self.health_table = QTableWidget()
        self.health_table.setColumnCount(6)
        self.health_table.setHorizontalHeaderLabels([
            "Source Name", "Type", "Status", "Latency", "Cached Programs", "Diagnostic Details"
        ])
        self.health_table.setWordWrap(False)
        self.health_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.health_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.health_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.health_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.health_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.health_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.health_table.setColumnWidth(0, 280)
        self.health_table.setColumnWidth(1, 200)
        self.health_table.setColumnWidth(2, 110)
        self.health_table.setColumnWidth(3, 90)
        self.health_table.setColumnWidth(4, 140)
        self.health_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.health_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.health_table.verticalHeader().setVisible(False)
        self.health_table.setFixedHeight(120)
        self.health_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.health_table.cellDoubleClicked.connect(lambda r, c: self.test_all_sources_health(silent=False))
        health_layout.addWidget(self.health_table)

        btn_row = QHBoxLayout()
        self.test_health_btn = QPushButton("Test All Sources Now")
        self.test_health_btn.clicked.connect(lambda: self.test_all_sources_health(silent=False))
        btn_row.addWidget(self.test_health_btn)

        self.sync_guide_btn = QPushButton("Sync Guide Now")
        self.sync_guide_btn.setStyleSheet(
            "QPushButton { padding: 4px 14px; font-weight: 500; }"
        )
        self.sync_guide_btn.clicked.connect(self.sync_guide)
        btn_row.addWidget(self.sync_guide_btn)

        self.guide_status_lbl = QLabel("Guide: Checking...")
        self.guide_status_lbl.setStyleSheet("font-size: 12px; color: #a4b0c2; font-weight: 500; padding-left: 6px;")
        btn_row.addWidget(self.guide_status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("statusBarProgressBar")
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setMinimumWidth(160)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)
        btn_row.addWidget(self.progress_bar)

        self.sync_progress_lbl = QLabel("")
        self.sync_progress_lbl.setStyleSheet("font-size: 12px; color: #52b788; font-weight: 500; padding-left: 6px;")
        self.sync_progress_lbl.setVisible(False)
        btn_row.addWidget(self.sync_progress_lbl)

        btn_row.addStretch()
        health_layout.addLayout(btn_row)
        layout.addWidget(health_box)

        # 3. Source Configurations (Collapsible Sections)
        # Collapsible 1: TV Passport Custom Stations (Above Custom XMLTV)
        self.pass_collapsible = CollapsibleSection("TV Passport Regional Over-The-Air Stations", initially_expanded=False)

        # Header warning banner visible even when section is collapsed
        self.passport_header_warning = QLabel()
        self.passport_header_warning.setStyleSheet(
            "QLabel { "
            "  background-color: #3b2810; "
            "  color: #ffc107; "
            "  border: 1px solid #d4882c; "
            "  border-radius: 4px; "
            "  padding: 4px 10px; "
            "  font-size: 11px; "
            "  font-weight: bold; "
            "}"
        )
        self.passport_header_warning.setCursor(Qt.CursorShape.PointingHandCursor)
        self.passport_header_warning.setToolTip("Click to open and configure TV Passport station IDs")
        self.passport_header_warning.mousePressEvent = lambda ev: self.pass_collapsible.toggle_btn.click()
        self.passport_header_warning.setVisible(False)
        self.pass_collapsible.addHeaderWidget(self.passport_header_warning)

        pass_content = QWidget()
        pass_layout = QHBoxLayout(pass_content)
        pass_layout.setContentsMargins(12, 12, 12, 12)
        pass_layout.setSpacing(25)

        # Left Column: Instructions and guidelines
        left_col_widget = QWidget()
        left_col_layout = QVBoxLayout(left_col_widget)
        left_col_layout.setContentsMargins(0, 0, 0, 0)
        left_col_layout.setSpacing(10)

        pass_instructions = QLabel(
            "<b>24/7 Broadcast Station & Affiliate Guide (TV Passport):</b><br>"
            "TV Passport provides full 24/7 local broadcast schedules for your stations. "
            "Any stations you configure here will automatically download their complete daily listings for your guide.<br><br>"
            "<b>Instructions:</b><br>"
            "1. Visit <a href='https://www.tvpassport.com/index.php/lineups' style='color: #64b5f6; font-weight: bold;'>tvpassport.com</a> in your browser, enter your postal/ZIP code, and select your antenna broadcast lineup.<br>"
            "2. Select your channel to open its listings page. Look at the web address (URL):<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<code>https://www.tvpassport.com/tv-listings/stations/station/<b>1812</b>/2026-10-07</code><br>"
            "3. The number right after <code>/station/</code> is your station ID (e.g. <b>1812</b>).<br>"
            "4. Enter one station per line: <b>Guide Name = Station ID</b> (e.g. <code>NBC = 1812</code>, <code>Fox = 1809</code>, or <code>PBS = 1184</code>).<br><br>"
            "<b>Automatic Sync:</b> When you click <i>Save Station IDs</i>, Kaffeine DVR immediately syncs guide listings in the background without needing a manual sync."
        )
        pass_instructions.setWordWrap(True)
        pass_instructions.setOpenExternalLinks(True)
        pass_instructions.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        pass_instructions.setStyleSheet("color: #cdd6e2; font-size: 13px; line-height: 1.5;")
        left_col_layout.addWidget(pass_instructions)

        self.passport_notice = QLabel()
        self.passport_notice.setWordWrap(True)
        self.passport_notice.setOpenExternalLinks(True)
        self.passport_notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        left_col_layout.addWidget(self.passport_notice)
        self.update_tvpassport_notice()
        left_col_layout.addStretch()

        pass_layout.addWidget(left_col_widget, stretch=5)

        # Right Column: Station Mappings Editor & Save Button
        right_col_widget = QWidget()
        right_col_layout = QVBoxLayout(right_col_widget)
        right_col_layout.setContentsMargins(0, 0, 0, 0)
        right_col_layout.setSpacing(8)

        mapping_hdr = QLabel("<b>Station ID Setup (Guide Name = Station ID):</b>")
        mapping_hdr.setStyleSheet("color: #9cb0c6; font-size: 12px; font-weight: bold;")
        right_col_layout.addWidget(mapping_hdr)

        self.passport_stations_text = QTextEdit()
        self.passport_stations_text.setPlaceholderText("Example:\nNBC = 1812\nABC = 4163\nFox = 1809")
        stations_lines = [f"{k} = {v}" for k, v in self.config_mgr.tvpassport_stations.items()]
        self.passport_stations_text.setPlainText("\n".join(stations_lines))
        self.passport_stations_text.setMinimumHeight(300)
        right_col_layout.addWidget(self.passport_stations_text)

        save_pass_btn = QPushButton("Save Station IDs")
        save_pass_btn.setObjectName("primaryActionBtn")
        save_pass_btn.clicked.connect(self.save_tvpassport_settings)
        pass_btn_row = QHBoxLayout()
        pass_btn_row.addWidget(save_pass_btn)
        pass_btn_row.addStretch()
        right_col_layout.addLayout(pass_btn_row)

        pass_layout.addWidget(right_col_widget, stretch=5)

        self.pass_collapsible.setContentLayout(pass_layout)
        layout.addWidget(self.pass_collapsible)

        # Collapsible 2: XMLTV
        self.xml_collapsible = CollapsibleSection("Custom XMLTV Provider (Manual / Alternative Feed)", initially_expanded=False)
        xml_content = QWidget()
        xml_layout = QFormLayout(xml_content)
        xml_desc = QLabel("Supports local XMLTV files (e.g. from zap2xml or WebGrab+) or remote HTTP/HTTPS XMLTV URLs.")
        xml_desc.setStyleSheet("color: #6c757d; font-size: 11px;")
        xml_layout.addRow(xml_desc)

        file_row = QHBoxLayout()
        self.xmltv_input = QLineEdit(self.config_mgr.xmltv_path_or_url)
        self.xmltv_input.setPlaceholderText("Path to .xml / .xmltv file or URL (http://...)")
        file_row.addWidget(self.xmltv_input)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_xmltv_file)
        file_row.addWidget(browse_btn)

        test_xml_btn = QPushButton("Test XMLTV Feed")
        test_xml_btn.clicked.connect(self.test_xmltv_feed)
        file_row.addWidget(test_xml_btn)
        xml_layout.addRow("Feed Path / URL:", file_row)

        save_xml_btn = QPushButton("Save XMLTV Setting")
        save_xml_btn.setObjectName("primaryActionBtn")
        save_xml_btn.clicked.connect(self.save_xmltv_settings)
        xml_btn_row = QHBoxLayout()
        xml_btn_row.addWidget(save_xml_btn)
        xml_btn_row.addStretch()
        xml_layout.addRow(xml_btn_row)
        self.xml_collapsible.setContentLayout(xml_layout)
        layout.addWidget(self.xml_collapsible)

        # Collapsible 3: Schedules Direct
        self.sd_collapsible = CollapsibleSection(
            "Schedules Direct (Paid Official Gracenote API)",
            initially_expanded=False,
            subtitle="(untested)"
        )
        sd_content = QWidget()
        sd_layout = QFormLayout(sd_content)
        sd_desc = QLabel("Official non-profit EPG service (~$35/year) providing direct Gracenote listings with high reliability.")
        sd_desc.setStyleSheet("color: #6c757d; font-size: 11px;")
        sd_layout.addRow(sd_desc)

        sd_data = self.config_mgr.schedules_direct
        self.sd_user_input = QLineEdit(sd_data.get("username", ""))
        self.sd_pass_input = QLineEdit(sd_data.get("password", ""))
        self.sd_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.sd_lineup_input = QLineEdit(sd_data.get("lineup", ""))
        self.sd_lineup_input.setPlaceholderText("Lineup ID or Postal Code (e.g. USA-OTA-85364)")

        sd_layout.addRow("Username:", self.sd_user_input)
        sd_layout.addRow("Password:", self.sd_pass_input)
        sd_layout.addRow("Lineup / Zip:", self.sd_lineup_input)

        sd_btn_row = QHBoxLayout()
        verify_sd_btn = QPushButton("Verify Account Login")
        verify_sd_btn.clicked.connect(self.verify_sd_account)
        sd_btn_row.addWidget(verify_sd_btn)

        save_sd_btn = QPushButton("Save Schedules Direct Credentials")
        save_sd_btn.setObjectName("primaryActionBtn")
        save_sd_btn.clicked.connect(self.save_sd_settings)
        sd_btn_row.addWidget(save_sd_btn)
        sd_btn_row.addStretch()
        sd_layout.addRow(sd_btn_row)
        self.sd_collapsible.setContentLayout(sd_layout)
        layout.addWidget(self.sd_collapsible)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    # Subcategory 2: Channel Source
    def create_settings_channels_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Splitter / Two-panel layout
        lineup_panels = QHBoxLayout()

        map_box = QGroupBox("Channel Importing && Renaming")
        map_layout = QVBoxLayout(map_box)

        # Buttons placed directly above the channel importing & renaming box
        btn_row = QHBoxLayout()
        import_kaffeine_btn = QPushButton("Import Channels from Kaffeine")
        import_kaffeine_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #1b4332;"
            "  border: 1.5px solid #2d6a4f;"
            "  color: #e8f5e9;"
            "  font-weight: bold;"
            "  padding: 6px 14px;"
            "  border-radius: 5px;"
            "}"
            "QPushButton:hover {"
            "  background-color: #2d6a4f;"
            "  border-color: #40916c;"
            "  color: #ffffff;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #081c15;"
            "}"
        )
        import_kaffeine_btn.clicked.connect(lambda: self.import_channels_from_kaffeine(silent=False))
        btn_row.addWidget(import_kaffeine_btn)

        save_mapping_btn = QPushButton("Save Channels")
        save_mapping_btn.setObjectName("primaryActionBtn")
        save_mapping_btn.clicked.connect(self.save_channel_mapping)
        btn_row.addWidget(save_mapping_btn)

        reset_mapping_btn = QPushButton("Reset Defaults")
        reset_mapping_btn.setToolTip("Reset to standard over-the-air antenna channel names")
        reset_mapping_btn.clicked.connect(self.reset_channel_mapping_defaults)
        btn_row.addWidget(reset_mapping_btn)

        scanner_btn = QPushButton("Channel\nStrength Scan")
        scanner_btn.setObjectName("scannerActionBtn")
        scanner_btn.setToolTip("Open Channel Signal Health Scanner to test digital reception")
        scanner_btn.setStyleSheet(
            "QPushButton#scannerActionBtn {"
            "  background-color: #1e3a8a;"
            "  border: 1.5px solid #3b82f6;"
            "  color: #eff6ff;"
            "  font-weight: bold;"
            "  font-size: 11px;"
            "  padding: 3px 8px;"
            "  border-radius: 5px;"
            "  text-align: center;"
            "}"
            "QPushButton#scannerActionBtn:hover {"
            "  background-color: #2563eb;"
            "  border-color: #60a5fa;"
            "  color: #ffffff;"
            "}"
            "QPushButton#scannerActionBtn:pressed {"
            "  background-color: #1d4ed8;"
            "}"
        )
        scanner_btn.clicked.connect(self.open_channel_health_dialog)
        btn_row.addWidget(scanner_btn)

        btn_row.addStretch()
        map_layout.addLayout(btn_row)

        health_row = QHBoxLayout()
        self.channel_health_badge = QLabel("")
        self.channel_health_badge.setStyleSheet("font-size: 11px;")
        health_row.addWidget(self.channel_health_badge)
        health_row.addStretch()
        map_layout.addLayout(health_row)

        # Non-overlapping tip frame
        tip_frame = QFrame()
        tip_frame.setStyleSheet(
            "QFrame {"
            "  background-color: rgba(255, 255, 255, 0.02);"
            "  border: 1px solid rgba(255, 255, 255, 0.06);"
            "  border-radius: 4px;"
            "  padding: 4px 8px;"
            "}"
        )
        tip_layout = QVBoxLayout(tip_frame)
        tip_layout.setContentsMargins(6, 4, 6, 4)
        tip_layout.setSpacing(2)
        tip_lbl = QLabel(
            "<span style='color: #8a99ad; font-size: 11px;'>"
            "<b>Format:</b> Guide Name = Tuned Channel (e.g. <code>Fox = KSAZ-HD</code>). "
            "Colored dots show live reception: "
            "<span style='color: #4ade80; font-weight: bold;'>● Locked</span> &nbsp; "
            "<span style='color: #facc15; font-weight: bold;'>● Weak</span> &nbsp; "
            "<span style='color: #f87171; font-weight: bold;'>● No Signal</span> &nbsp; "
            "<span style='color: #64748b;'>● Untested</span>"
            "</span>"
        )
        tip_lbl.setTextFormat(Qt.TextFormat.RichText)
        tip_lbl.setWordWrap(True)
        tip_layout.addWidget(tip_lbl)
        map_layout.addWidget(tip_frame)

        self.mapping_text = QTextEdit()
        self.mapping_text.setMinimumHeight(200)
        map_layout.addWidget(self.mapping_text)
        lineup_panels.addWidget(map_box, 1)

        # Right Panel: Interactive Channel Order List
        order_box = QGroupBox("TV Guide Channel Order (Manual Priority)")
        order_layout = QVBoxLayout(order_box)

        desc = QLabel("Reorder rows in your EPG TV Guide using drag-and-drop or the Move Up/Down buttons.")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #8a99ad; font-size: 11px;")
        order_layout.addWidget(desc)

        order_legend = QLabel(
            "<span style='color: #8a99ad; font-size: 10px;'>"
            "Signal: "
            "<span style='color: #4ade80; font-weight: bold;'>● Locked</span> &nbsp; "
            "<span style='color: #facc15; font-weight: bold;'>● Weak</span> &nbsp; "
            "<span style='color: #f87171; font-weight: bold;'>● No Signal</span> &nbsp; "
            "<span style='color: #64748b;'>● Untested</span>"
            "</span>"
        )
        order_legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        order_layout.addWidget(order_legend)

        self.channel_order_list = QListWidget()
        self.channel_order_list.setObjectName("channelOrderList")
        self.channel_order_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.channel_order_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.channel_order_list.model().rowsMoved.connect(self._on_channel_rows_dragged)
        order_layout.addWidget(self.channel_order_list)

        order_ctrl_bar = QHBoxLayout()
        self.move_up_btn = QPushButton("▲ Move Up")
        self.move_up_btn.clicked.connect(self._move_channel_up)
        order_ctrl_bar.addWidget(self.move_up_btn)

        self.move_down_btn = QPushButton("▼ Move Down")
        self.move_down_btn.clicked.connect(self._move_channel_down)
        order_ctrl_bar.addWidget(self.move_down_btn)

        self.sort_alpha_btn = QPushButton("Sort A-Z")
        self.sort_alpha_btn.clicked.connect(self._sort_channels_alphabetical)
        order_ctrl_bar.addWidget(self.sort_alpha_btn)

        order_layout.addLayout(order_ctrl_bar)
        lineup_panels.addWidget(order_box, 1)
        layout.addLayout(lineup_panels)

        self.populate_channel_mapping_text()
        self.refresh_channel_order_list()
        self.refresh_channel_health_badge()
        return widget

    def refresh_channel_health_badge(self):
        if not hasattr(self, "channel_health_badge"):
            return
        health_data = self.config_mgr.channel_health
        if not health_data:
            self.channel_health_badge.setText("<span style='color: #8c98aa;'>Signal health not yet scanned</span>")
            return

        channels = self.config_mgr.get_ordered_channels()
        if not channels:
            channels = list(self.config_mgr.channel_map.keys())

        locked_cnt = 0
        carrier_cnt = 0
        nosig_cnt = 0
        for ch in channels:
            kaffeine_name = self.config_mgr.channel_map.get(ch, ch)
            h = health_data.get(ch) or health_data.get(kaffeine_name)
            if h:
                if h.get("locked"):
                    locked_cnt += 1
                elif h.get("has_signal") or h.get("has_carrier"):
                    carrier_cnt += 1
                else:
                    nosig_cnt += 1

        parts = []
        if locked_cnt:
            parts.append(f"<span style='color: #4ade80; font-weight: bold;'>● {locked_cnt} Locked</span>")
        if carrier_cnt:
            parts.append(f"<span style='color: #facc15; font-weight: bold;'>● {carrier_cnt} Weak</span>")
        if nosig_cnt:
            parts.append(f"<span style='color: #f87171; font-weight: bold;'>● {nosig_cnt} No Signal</span>")

        if parts:
            self.channel_health_badge.setText("  |  ".join(parts))
        else:
            self.channel_health_badge.setText("<span style='color: #8c98aa;'>Signal health not yet scanned</span>")

    def populate_channel_mapping_text(self):
        if not hasattr(self, "mapping_text"):
            return
        health_data = self.config_mgr.channel_health
        lines_html = []
        for k, v in self.config_mgr.channel_map.items():
            # Check health of tuned channel v, then fallback to guide name k
            h = health_data.get(v) or health_data.get(k)
            if h:
                if h.get("locked"):
                    dot_color = "#4ade80"  # Green
                elif h.get("has_signal") or h.get("has_carrier"):
                    dot_color = "#facc15"  # Yellow
                else:
                    dot_color = "#f87171"  # Red
            else:
                dot_color = "#64748b"      # Slate / Untested
            lines_html.append(f"<span style='color: {dot_color}; font-weight: bold;'>●</span> {html.escape(k)} = {html.escape(v)}")

        html_content = "<div style='font-family: monospace; font-size: 13px; line-height: 1.6;'>" + "<br>".join(lines_html) + "</div>"
        self.mapping_text.setHtml(html_content)

    def open_channel_health_dialog(self):
        channels = self.config_mgr.get_scanned_kaffeine_channels()
        if not channels:
            # Fallback to configured channel_map channels if Kaffeine DB has no scanned entries
            channels = [
                {"id": idx, "name": ch_name, "number": "", "transponder": ""}
                for idx, ch_name in enumerate(self.config_mgr.channel_map.values(), 1)
            ]
        if not channels:
            QMessageBox.information(
                self,
                "No Channels Available",
                "No digital TV channels were found to test.\n"
                "Please scan channels in Kaffeine or import channels first."
            )
            return
        dlg = ChannelSignalHealthDialog(channels, config_mgr=self.config_mgr, parent=self)
        dlg.exec()
        self.populate_channel_mapping_text()
        self.refresh_channel_order_list()

    def refresh_channel_order_list(self):
        if not hasattr(self, "channel_order_list"):
            return
        self.channel_order_list.blockSignals(True)
        self.channel_order_list.clear()
        ordered = self.config_mgr.get_ordered_channels()
        health_data = self.config_mgr.channel_health
        for idx, ch in enumerate(ordered, 1):
            item = QListWidgetItem(f"{idx}.  {ch}")
            item.setData(Qt.ItemDataRole.UserRole, ch)
            kaffeine_name = self.config_mgr.channel_map.get(ch, ch)
            h = health_data.get(ch) or health_data.get(kaffeine_name)
            if h:
                locked = h.get("locked")
                has_sig = h.get("has_signal") or h.get("has_carrier")
                pct = h.get("strength_pct", 0.0)
                snr = h.get("snr_db", 0.0)
                quality = h.get("quality_label", "")
                if locked:
                    item.setIcon(make_status_dot_icon("#4ade80"))
                    item.setToolTip(f"{ch}: Locked ({pct:.1f}% Signal, {snr:.1f} dB SNR - {quality})")
                elif has_sig:
                    item.setIcon(make_status_dot_icon("#facc15"))
                    item.setToolTip(f"{ch}: Carrier Detected ({pct:.1f}% Signal - Weak / No Lock. Antenna re-aiming may help)")
                else:
                    item.setIcon(make_status_dot_icon("#f87171"))
                    item.setToolTip(f"{ch}: No Signal (Zero broadcast transmission detected)")
            else:
                item.setIcon(make_status_dot_icon("#64748b"))
                item.setToolTip(f"{ch}: Untested (Click 'Check Channel Health' to test signal reception)")
            self.channel_order_list.addItem(item)
        self.channel_order_list.blockSignals(False)
        self.refresh_channel_health_badge()

    def _get_current_list_channels(self) -> List[str]:
        channels = []
        for i in range(self.channel_order_list.count()):
            it = self.channel_order_list.item(i)
            ch = it.data(Qt.ItemDataRole.UserRole) or it.text().strip()
            channels.append(ch)
        return channels

    def _renumber_channel_order_list(self):
        for i in range(self.channel_order_list.count()):
            it = self.channel_order_list.item(i)
            ch = it.data(Qt.ItemDataRole.UserRole)
            it.setText(f"{i + 1}.  {ch}")

    def _move_channel_up(self):
        row = self.channel_order_list.currentRow()
        if row > 0:
            item = self.channel_order_list.takeItem(row)
            self.channel_order_list.insertItem(row - 1, item)
            self.channel_order_list.setCurrentRow(row - 1)
            self._renumber_channel_order_list()
            self._save_current_channel_order()

    def _move_channel_down(self):
        row = self.channel_order_list.currentRow()
        if 0 <= row < self.channel_order_list.count() - 1:
            item = self.channel_order_list.takeItem(row)
            self.channel_order_list.insertItem(row + 1, item)
            self.channel_order_list.setCurrentRow(row + 1)
            self._renumber_channel_order_list()
            self._save_current_channel_order()

    def _sort_channels_alphabetical(self):
        channels = sorted(self._get_current_list_channels())
        self.config_mgr.channel_order = channels
        self.refresh_channel_order_list()
        self._apply_channel_order_to_views()
        self.flash_save_indicator("Lineup Sorted A-Z")

    def _on_channel_rows_dragged(self):
        self._renumber_channel_order_list()
        self._save_current_channel_order()

    def _save_current_channel_order(self):
        ordered = self._get_current_list_channels()
        self.config_mgr.channel_order = ordered
        self._apply_channel_order_to_views()
        self.flash_save_indicator("Channel Order Saved")

    def _apply_channel_order_to_views(self):
        self.refresh_channel_dropdowns()
        self._refresh_guide_view(keep_scroll=True)

    # Subcategory 3: Automation & DVR
    def create_settings_automation_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        two_col_layout = QHBoxLayout()
        two_col_layout.setSpacing(20)

        # ------------------ LEFT COLUMN: DVR & Window Settings ------------------
        left_col = QVBoxLayout()
        left_col.setSpacing(15)

        # Group 1: DVR Scheduling & Automation
        dvr_group = QGroupBox("DVR Scheduling && Automation")
        dvr_layout = QFormLayout(dvr_group)
        dvr_layout.setContentsMargins(15, 15, 15, 15)
        dvr_layout.setSpacing(12)

        self.lead_time_spin = NumberStepper()
        self.lead_time_spin.setRange(1, 60)
        self.lead_time_spin.setValue(self.config_mgr.lead_time_mins)
        self.lead_time_spin.setSuffix(" minutes")
        self.lead_time_spin.setFixedWidth(160)

        # Auto-save indicator aligned on the far right of the top DVR row
        self.save_indicator_lbl = QLabel("Auto-save active")
        self.save_indicator_lbl.setStyleSheet(
            "color: #8c98aa; font-size: 11px; padding: 2px 4px; background: transparent;"
        )

        lead_time_row = QHBoxLayout()
        lead_time_row.setContentsMargins(0, 0, 0, 0)
        lead_time_row.addWidget(self.lead_time_spin)
        lead_time_row.addStretch()
        lead_time_row.addWidget(self.save_indicator_lbl)

        dvr_layout.addRow(
            make_setting_label(
                "Just-In-Time Lead Time:",
                "Minutes before show start time to auto-launch Kaffeine and arm recording timer.\n"
                "Keeping this low (e.g. 2-5m) prevents Kaffeine from blocking system reboots and shutdowns."
            ),
            lead_time_row
        )

        self.end_buffer_spin = NumberStepper()
        self.end_buffer_spin.setRange(0, 180)
        self.end_buffer_spin.setValue(self.config_mgr.end_buffer_mins)
        self.end_buffer_spin.setSuffix(" minutes")
        self.end_buffer_spin.setFixedWidth(160)
        dvr_layout.addRow(
            make_setting_label(
                "Default End Buffer:",
                "Extra post-roll buffer added to the end of scheduled recordings to avoid clipping broadcast overruns.\n\n"
                "Note: Automatically suppressed for back-to-back recordings scheduled on different channels to yield the tuner for the next program on time."
            ),
            self.end_buffer_spin
        )

        self.sports_buffer_spin = NumberStepper()
        self.sports_buffer_spin.setRange(0, 180)
        self.sports_buffer_spin.setValue(self.config_mgr.sports_buffer_mins)
        self.sports_buffer_spin.setSuffix(" minutes")
        self.sports_buffer_spin.setFixedWidth(160)

        self.auto_buffer_sports_check = QCheckBox("Auto-Extend Sports")
        self.auto_buffer_sports_check.setChecked(self.config_mgr.auto_buffer_sports)

        sports_row = QHBoxLayout()
        sports_row.addWidget(self.sports_buffer_spin)
        sports_row.addSpacing(12)
        sports_row.addWidget(self.auto_buffer_sports_check)
        sports_row.addStretch()
        dvr_layout.addRow(
            make_setting_label(
                "Sports Auto-Extend:",
                "Applies extended post-roll padding to live sporting events, games, and matches to catch overtime."
            ),
            sports_row
        )

        self.interval_spin = NumberStepper()
        self.interval_spin.setRange(30, 600)
        self.interval_spin.setSingleStep(30)
        self.interval_spin.setValue(self.config_mgr.watcher_interval_seconds)
        self.interval_spin.setSuffix(" seconds")
        self.interval_spin.setFixedWidth(160)
        dvr_layout.addRow(
            make_setting_label(
                "Watcher Polling Frequency:",
                "How often the background watcher service checks the DVR queue for upcoming shows."
            ),
            self.interval_spin
        )


        self.notify_lead_spin = NumberStepper()
        self.notify_lead_spin.setRange(0, 999)
        self.notify_lead_spin.setValue(self.config_mgr.notification_lead_time_mins)
        self.notify_lead_spin.setFixedWidth(160)
        self.notify_lead_spin.setEnabled(self.config_mgr.enable_desktop_notifications)

        self.notify_check = QCheckBox("Enable Desktop Notifications")
        self.notify_check.setChecked(self.config_mgr.enable_desktop_notifications)
        self.notify_check.toggled.connect(self.notify_lead_spin.setEnabled)

        notify_row = QHBoxLayout()
        notify_row.addWidget(self.notify_lead_spin)
        notify_row.addSpacing(12)
        notify_row.addWidget(self.notify_check)
        notify_row.addStretch()
        dvr_layout.addRow(
            make_setting_label(
                "Notification Lead Time (Mins):",
                "Sends a persistent desktop notification via notify-send when a scheduled recording is starting.\n"
                "• 0: Sends notification at the exact moment the recording begins.\n"
                "• 1–999: Sends notification in advance before the recording starts."
            ),
            notify_row
        )

        self.launch_mode_combo = ThemedComboBox()
        self.launch_mode_combo.addItem("Minimized to Taskbar (Panel)", "taskbar")
        self.launch_mode_combo.addItem("Minimize to System Tray (-m minimal)", "tray")
        self.launch_mode_combo.addItem("Normal Window (Visible desktop)", "normal")
        self.launch_mode_combo.setFixedWidth(290)
        cur_mode = self.config_mgr.launch_mode
        mode_idx = self.launch_mode_combo.findData(cur_mode)
        if mode_idx >= 0:
            self.launch_mode_combo.setCurrentIndex(mode_idx)
        dvr_layout.addRow(
            make_setting_label(
                "Recording Launch Mode:",
                "Controls how Kaffeine starts when armed for recording:\n"
                "• Minimized to Taskbar: Quietly minimizes to your panel taskbar without touching tray.\n"
                "• Minimize to System Tray: Starts with -m minimal mode and docks into tray.\n"
                "• Normal Window: Opens as an active visible window on your desktop."
            ),
            self.launch_mode_combo
        )

        # Live TV Playback Player
        self.live_tv_mode_combo = ThemedComboBox()
        from kaffeine_dvr.dbus_client import (
            SUPPORTED_PLAYERS,
            detect_player_installation,
        )

        cur_live_mode = getattr(self.config_mgr, "live_tv_watch_mode", "smplayer")

        for key, pinfo in SUPPORTED_PLAYERS.items():
            pname = pinfo["name"]
            if key == "system":
                self.live_tv_mode_combo.addItem(pname, key)
            else:
                itype = detect_player_installation(key)
                if itype == "native":
                    self.live_tv_mode_combo.addItem(f"{pname} (Installed)", key)
                elif itype == "flatpak":
                    self.live_tv_mode_combo.addItem(f"{pname} (Flatpak)", key)
                elif key == cur_live_mode:
                    self.live_tv_mode_combo.addItem(f"{pname} (Not Detected)", key)

        self.live_tv_mode_combo.addItem("Custom Command...", "custom")
        self.live_tv_mode_combo.setFixedWidth(290)

        l_idx = self.live_tv_mode_combo.findData(cur_live_mode)
        if l_idx >= 0:
            self.live_tv_mode_combo.setCurrentIndex(l_idx)
        else:
            self.live_tv_mode_combo.setCurrentIndex(0)

        self.custom_live_player_edit = QLineEdit()
        self.custom_live_player_edit.setPlaceholderText("e.g. mpv --fs {file}")
        self.custom_live_player_edit.setText(self.config_mgr.custom_live_tv_player_cmd)
        self.custom_live_player_edit.setFixedWidth(290)
        self.custom_live_player_edit.setVisible(cur_live_mode == "custom")

        def _on_live_player_combo_changed(idx):
            mode = self.live_tv_mode_combo.itemData(idx)
            self.custom_live_player_edit.setVisible(mode == "custom")

        self.live_tv_mode_combo.currentIndexChanged.connect(_on_live_player_combo_changed)

        live_player_container = QWidget()
        live_player_vbox = QVBoxLayout(live_player_container)
        live_player_vbox.setContentsMargins(0, 0, 0, 0)
        live_player_vbox.setSpacing(4)
        live_player_vbox.addWidget(self.live_tv_mode_combo)
        live_player_vbox.addWidget(self.custom_live_player_edit)

        dvr_layout.addRow(
            make_setting_label(
                "Playback Player:",
                "Select which media player opens TV broadcasts and recorded shows from the Guide:\n"
                "• Unified Playback: Used for Live TV timeshift streams, continuous channel streaming, and recorded video files.\n"
                "• Controls & Capabilities: Enables full pause, rewind, instant replay, and seek controls in your preferred external player.\n"
                "• Instance Isolation: Players like SMPlayer launch as an independent window so they will never hijack or close separate video windows you have open.\n"
                "• Auto-Stop & Tuner Release: Closing the player window during live timeshifting automatically stops background capture in Kaffeine and frees the tuner hardware.\n"
                "• Supported Players: Automatically discovers native and Flatpak players (SMPlayer, MPV, VLC, MPC-Qt, Celluloid, Haruna) or accepts custom command templates ({file})."
            ),
            live_player_container
        )

        self.timeshift_buffer_spin = NumberStepper()
        self.timeshift_buffer_spin.setRange(1, 15)
        self.timeshift_buffer_spin.setSuffix(" sec")
        self.timeshift_buffer_spin.setFixedWidth(160)
        self.timeshift_buffer_spin.setValue(getattr(self.config_mgr, "timeshift_buffer_seconds", 2))

        dvr_layout.addRow(
            make_setting_label(
                "Timeshift Initial Buffer:",
                "Initial wait duration (seconds) before opening your video player when timeshifting live TV. Allows Kaffeine to lock the tuner frequency and write stream packets."
            ),
            self.timeshift_buffer_spin
        )

        self.delete_timeshift_check = QCheckBox("Delete temporary timeshift buffer files when player closes")
        self.delete_timeshift_check.setChecked(getattr(self.config_mgr, "delete_timeshift_on_exit", True))
        dvr_layout.addRow(
            make_setting_label(
                "Timeshift File Retention:",
                "When checked, temporary buffer files created during live TV timeshifting are automatically deleted upon stopping to avoid consuming disk space. Shows specifically scheduled to record are always preserved."
            ),
            self.delete_timeshift_check
        )

        left_col.addWidget(dvr_group)

        # Storage & Auto-Cleanup Card (Moved under DVR Scheduling)
        storage_box = QGroupBox("Storage && Video Retention")
        storage_layout = QVBoxLayout(storage_box)
        storage_layout.setContentsMargins(15, 15, 15, 15)
        storage_layout.setSpacing(12)

        self.storage_status_lbl = QLabel("Checking storage space...")
        self.storage_status_lbl.setStyleSheet("font-weight: bold; font-size: 13px; color: #55a84c;")
        storage_layout.addWidget(self.storage_status_lbl)

        storage_form = QFormLayout()
        storage_form.setSpacing(10)

        self.cleanup_enable_check = QCheckBox("Enable Automatic Video Cleanup")
        self.cleanup_enable_check.setChecked(self.config_mgr.auto_cleanup_enabled)
        self.cleanup_enable_check.stateChanged.connect(self._auto_save_automation_settings)
        storage_form.addRow(
            make_setting_label("Auto-Cleanup:", "Automatically purges unprotected videos matching age or disk thresholds."),
            self.cleanup_enable_check
        )

        self.retention_days_spin = NumberStepper()
        self.retention_days_spin.setRange(0, 365)
        self.retention_days_spin.setValue(self.config_mgr.retention_days)
        self.retention_days_spin.setSuffix(" days")
        self.retention_days_spin.setFixedWidth(160)
        self.retention_days_spin.valueChanged.connect(self._auto_save_automation_settings)
        storage_form.addRow(
            make_setting_label("Retention Window:", "Delete recordings older than this age. Set to 0 to disable age-based pruning."),
            self.retention_days_spin
        )

        self.min_free_spin = NumberStepper()
        self.min_free_spin.setRange(0, 1000)
        self.min_free_spin.setSingleStep(5)
        self.min_free_spin.setValue(self.config_mgr.min_free_disk_gb)
        self.min_free_spin.setSuffix(" GB")
        self.min_free_spin.setFixedWidth(160)
        self.min_free_spin.valueChanged.connect(self._auto_save_automation_settings)
        storage_form.addRow(
            make_setting_label("Min Free Space:", "If free disk space drops below this limit, oldest unprotected recordings are purged first."),
            self.min_free_spin
        )

        detected_folder = str(self.storage_mgr.get_recording_folder())
        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.setSpacing(8)
        self.custom_folder_input = QLineEdit()
        self.custom_folder_input.setText(self.config_mgr.custom_recording_folder)
        self.custom_folder_input.setPlaceholderText(f"Auto-detected: {detected_folder}")
        self.custom_folder_input.textChanged.connect(self._auto_save_automation_settings)
        folder_row.addWidget(self.custom_folder_input)
        self.browse_folder_btn = QPushButton("Browse...")
        self.browse_folder_btn.clicked.connect(self.browse_custom_recording_folder)
        folder_row.addWidget(self.browse_folder_btn)
        storage_form.addRow(
            make_setting_label("Recording Folder:", "Folder where Kaffeine saves .m2t recordings. Auto-detected from kaffeinerc or overridden here."),
            folder_row
        )

        storage_layout.addLayout(storage_form)

        storage_btn_row = QHBoxLayout()
        storage_btn_row.setSpacing(10)
        self.run_cleanup_btn = QPushButton("Run Retention Cleanup Now")
        self.run_cleanup_btn.setStyleSheet("color: #ff5252; font-weight: bold;")
        self.run_cleanup_btn.clicked.connect(self.run_manual_cleanup)
        storage_btn_row.addWidget(self.run_cleanup_btn)

        self.refresh_storage_btn = QPushButton("Refresh Disk Usage")
        self.refresh_storage_btn.clicked.connect(self.update_storage_status_ui)
        storage_btn_row.addWidget(self.refresh_storage_btn)
        storage_btn_row.addStretch()
        storage_layout.addLayout(storage_btn_row)

        left_col.addWidget(storage_box)
        left_col.addStretch()
        two_col_layout.addLayout(left_col, 40)

        # ------------------ RIGHT COLUMN: Grid Guide & Themes ------------------
        right_col = QVBoxLayout()
        right_col.setSpacing(15)

        # Grid Guide Options Card (Moved to top of right column)
        color_box = QGroupBox("Grid Guide Options")
        color_layout = QVBoxLayout(color_box)
        color_layout.setContentsMargins(15, 15, 15, 15)
        color_layout.setSpacing(12)

        color_grid = QGridLayout()
        color_grid.setHorizontalSpacing(10)
        color_grid.setVerticalSpacing(8)

        self._cat_swatches: Dict[str, QPushButton] = {}

        categories_specs = [
            ("sports", "Sports"),
            ("news", "News"),
            ("movies", "Movies"),
            ("tvshows", "TV Shows / Series"),
            ("grid_bg", "Grid Background"),
        ]

        cur_colors = self.config_mgr.category_colors

        # Three evenly spaced columns in a clean horizontal box
        cols_row = QHBoxLayout()
        cols_row.setSpacing(18)

        # Sub-Column 1: Broadcast Categories
        col1_grid = QGridLayout()
        col1_grid.setHorizontalSpacing(10)
        col1_grid.setVerticalSpacing(8)
        for r_idx, (cat_key, cat_label) in enumerate(categories_specs):
            hex_val = cur_colors.get(cat_key, DEFAULT_CATEGORY_COLORS.get(cat_key, "#ffffff"))

            swatch_btn = QPushButton()
            swatch_btn.setProperty("class", "category-color-tile")
            swatch_btn.setFixedSize(26, 26)
            swatch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch_btn.setStyleSheet(f"QPushButton.category-color-tile {{ background-color: {hex_val}; }}")
            swatch_btn.clicked.connect(lambda checked=False, k=cat_key, l=cat_label: self._choose_category_color(k, l))
            col1_grid.addWidget(swatch_btn, r_idx, 0, Qt.AlignmentFlag.AlignVCenter)
            self._cat_swatches[cat_key] = swatch_btn

            lbl_name = QLabel(f"<b>{cat_label}</b>")
            lbl_name.setStyleSheet("font-size: 13px; color: #e2e8f0;")
            col1_grid.addWidget(lbl_name, r_idx, 1, Qt.AlignmentFlag.AlignVCenter)
        col1_grid.setColumnStretch(1, 1)
        cols_row.addLayout(col1_grid, 1)

        # Sub-Column 2: Tile Highlight & Live Options
        col2_grid = QGridLayout()
        col2_grid.setHorizontalSpacing(8)
        col2_grid.setVerticalSpacing(8)

        # Row 0: Tile Highlight
        hl_hex = cur_colors.get("highlight", DEFAULT_CATEGORY_COLORS.get("highlight", "#ffffff"))
        swatch_hl = QPushButton()
        swatch_hl.setProperty("class", "category-color-tile")
        swatch_hl.setFixedSize(26, 26)
        swatch_hl.setCursor(Qt.CursorShape.PointingHandCursor)
        swatch_hl.setStyleSheet(f"QPushButton.category-color-tile {{ background-color: {hl_hex}; }}")
        swatch_hl.clicked.connect(lambda checked=False: self._choose_category_color("highlight", "Tile Highlight"))
        col2_grid.addWidget(swatch_hl, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        self._cat_swatches["highlight"] = swatch_hl

        lbl_hl = QLabel("<b>Tile Highlight</b>")
        lbl_hl.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        col2_grid.addWidget(lbl_hl, 0, 1, Qt.AlignmentFlag.AlignVCenter)

        # Row 1: Live Badge & Hide Toggle
        badge_hex = cur_colors.get("live_badge", DEFAULT_CATEGORY_COLORS.get("live_badge", "#059669"))
        swatch_badge = QPushButton()
        swatch_badge.setProperty("class", "category-color-tile")
        swatch_badge.setFixedSize(26, 26)
        swatch_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        swatch_badge.setStyleSheet(f"QPushButton.category-color-tile {{ background-color: {badge_hex}; }}")
        swatch_badge.clicked.connect(lambda checked=False: self._choose_category_color("live_badge", "Live Badge"))
        col2_grid.addWidget(swatch_badge, 1, 0, Qt.AlignmentFlag.AlignVCenter)
        self._cat_swatches["live_badge"] = swatch_badge

        lbl_badge = QLabel("<b>Live Badge</b>")
        lbl_badge.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        col2_grid.addWidget(lbl_badge, 1, 1, Qt.AlignmentFlag.AlignVCenter)

        self.hide_live_badge_check = QCheckBox("Disable")
        self.hide_live_badge_check.setChecked(self.config_mgr.hide_live_badge)
        self.hide_live_badge_check.toggled.connect(self._on_hide_live_badge_toggled)
        col2_grid.addWidget(self.hide_live_badge_check, 1, 2, Qt.AlignmentFlag.AlignVCenter)

        # Row 2: Live Tile Tint & Disable Toggle
        bg_hex = cur_colors.get("live_bg", DEFAULT_CATEGORY_COLORS.get("live_bg", "#132400"))
        swatch_bg = QPushButton()
        swatch_bg.setProperty("class", "category-color-tile")
        swatch_bg.setFixedSize(26, 26)
        swatch_bg.setCursor(Qt.CursorShape.PointingHandCursor)
        swatch_bg.setStyleSheet(f"QPushButton.category-color-tile {{ background-color: {bg_hex}; }}")
        swatch_bg.clicked.connect(lambda checked=False: self._choose_category_color("live_bg", "Live Tile Tint"))
        col2_grid.addWidget(swatch_bg, 2, 0, Qt.AlignmentFlag.AlignVCenter)
        self._cat_swatches["live_bg"] = swatch_bg

        lbl_bg = QLabel("<b>Live Tile Tint</b>")
        lbl_bg.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        col2_grid.addWidget(lbl_bg, 2, 1, Qt.AlignmentFlag.AlignVCenter)

        self.live_same_bg_check = QCheckBox("Disable")
        self.live_same_bg_check.setChecked(self.config_mgr.live_same_bg_as_others)
        self.live_same_bg_check.toggled.connect(self._on_live_same_bg_toggled)
        col2_grid.addWidget(self.live_same_bg_check, 2, 2, Qt.AlignmentFlag.AlignVCenter)

        # Row 3: Time Line Swatch & Disable Toggle
        line_hex = cur_colors.get("time_indicator", DEFAULT_CATEGORY_COLORS.get("time_indicator", "#06b6d4"))
        swatch_line = QPushButton()
        swatch_line.setProperty("class", "category-color-tile")
        swatch_line.setFixedSize(26, 26)
        swatch_line.setCursor(Qt.CursorShape.PointingHandCursor)
        swatch_line.setStyleSheet(f"QPushButton.category-color-tile {{ background-color: {line_hex}; }}")
        swatch_line.clicked.connect(lambda checked=False: self._choose_category_color("time_indicator", "Time Line"))
        col2_grid.addWidget(swatch_line, 3, 0, Qt.AlignmentFlag.AlignVCenter)
        self._cat_swatches["time_indicator"] = swatch_line

        lbl_time_line = QLabel("<b>Time Line</b>")
        lbl_time_line.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        col2_grid.addWidget(lbl_time_line, 3, 1, Qt.AlignmentFlag.AlignVCenter)

        self.hide_time_line_check = QCheckBox("Disable")
        self.hide_time_line_check.setChecked(not getattr(self.config_mgr, "guide_show_time_indicator", True))
        self.hide_time_line_check.toggled.connect(self._on_hide_time_line_toggled)
        col2_grid.addWidget(self.hide_time_line_check, 3, 2, Qt.AlignmentFlag.AlignVCenter)

        self.time_line_opacity_btn = QPushButton(f"Opacity: {getattr(self.config_mgr, 'time_line_opacity', 100)}%")
        self.time_line_opacity_btn.setObjectName("timeLineOpacityBtn")
        self.time_line_opacity_btn.setToolTip("Click to adjust the transparency / opacity of the time line")
        self.time_line_opacity_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.time_line_opacity_btn.setFixedHeight(24)
        self.time_line_opacity_btn.setStyleSheet("""
            QPushButton#timeLineOpacityBtn {
                background-color: #1e293b;
                border: 1px solid #3c465d;
                border-radius: 4px;
                color: #e2e8f0;
                font-size: 11px;
                font-weight: 600;
                padding: 1px 7px;
            }
            QPushButton#timeLineOpacityBtn:hover {
                background-color: #2e3d55;
                border-color: #38bdf8;
                color: #ffffff;
            }
            QPushButton#timeLineOpacityBtn:disabled {
                background-color: #141721;
                border-color: #232a3b;
                color: #64748b;
            }
        """)
        self.time_line_opacity_btn.setEnabled(getattr(self.config_mgr, "guide_show_time_indicator", True))
        self.time_line_opacity_btn.clicked.connect(self._open_time_line_opacity_popup)
        col2_grid.addWidget(self.time_line_opacity_btn, 3, 3, Qt.AlignmentFlag.AlignVCenter)

        # Row 4: Clock Swatch & Disable Toggle
        clock_hex = cur_colors.get("clock", DEFAULT_CATEGORY_COLORS.get("clock", "#38bdf8"))
        swatch_clock = QPushButton()
        swatch_clock.setProperty("class", "category-color-tile")
        swatch_clock.setFixedSize(26, 26)
        swatch_clock.setCursor(Qt.CursorShape.PointingHandCursor)
        swatch_clock.setStyleSheet(f"QPushButton.category-color-tile {{ background-color: {clock_hex}; }}")
        swatch_clock.clicked.connect(lambda checked=False: self._choose_category_color("clock", "Clock"))
        col2_grid.addWidget(swatch_clock, 4, 0, Qt.AlignmentFlag.AlignVCenter)
        self._cat_swatches["clock"] = swatch_clock

        lbl_clock = QLabel("<b>Clock</b>")
        lbl_clock.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        col2_grid.addWidget(lbl_clock, 4, 1, Qt.AlignmentFlag.AlignVCenter)

        self.hide_clock_check = QCheckBox("Disable")
        self.hide_clock_check.setChecked(not getattr(self.config_mgr, "show_clock", True))
        self.hide_clock_check.toggled.connect(self._on_hide_clock_toggled)
        col2_grid.addWidget(self.hide_clock_check, 4, 2, Qt.AlignmentFlag.AlignVCenter)

        col2_grid.setColumnStretch(4, 1)
        cols_row.addLayout(col2_grid, 1)

        # Sub-Column 3: Guide & Detail Sizing
        col3_grid = QGridLayout()
        col3_grid.setHorizontalSpacing(10)
        col3_grid.setVerticalSpacing(8)

        lbl_rows = QLabel("<b>Grid Rows:</b>")
        lbl_rows.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        col3_grid.addWidget(lbl_rows, 0, 0, Qt.AlignmentFlag.AlignVCenter)

        self.grid_rows_spin = NumberStepper()
        self.grid_rows_spin.setRange(4, 16)
        self.grid_rows_spin.setValue(self.config_mgr.grid_visible_rows)
        self.grid_rows_spin.setSuffix(" rows")
        self.grid_rows_spin.setFixedWidth(120)
        self.grid_rows_spin.valueChanged.connect(self._on_grid_rows_changed)
        col3_grid.addWidget(self.grid_rows_spin, 0, 1, Qt.AlignmentFlag.AlignVCenter)

        lbl_desc_lines = QLabel("<b>Grid Box:</b>")
        lbl_desc_lines.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        col3_grid.addWidget(lbl_desc_lines, 1, 0, Qt.AlignmentFlag.AlignVCenter)

        self.guide_desc_lines_combo = CenteredComboBox()
        self.guide_desc_lines_combo.addItem("2 Lines", 2)
        self.guide_desc_lines_combo.addItem("3 Lines", 3)
        self.guide_desc_lines_combo.setFixedWidth(120)
        cur_desc_lines = getattr(self.config_mgr, "guide_detail_lines", 3)
        d_idx = self.guide_desc_lines_combo.findData(cur_desc_lines)
        self.guide_desc_lines_combo.setCurrentIndex(d_idx if d_idx >= 0 else 1)
        self.guide_desc_lines_combo.currentIndexChanged.connect(self._on_guide_desc_lines_changed)
        col3_grid.addWidget(self.guide_desc_lines_combo, 1, 1, Qt.AlignmentFlag.AlignVCenter)

        lbl_auto_adv = QLabel("<b>Auto-Advance:</b>")
        lbl_auto_adv.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        col3_grid.addWidget(lbl_auto_adv, 2, 0, Qt.AlignmentFlag.AlignVCenter)

        auto_adv_widget = QWidget()
        auto_adv_layout = QHBoxLayout(auto_adv_widget)
        auto_adv_layout.setContentsMargins(0, 0, 0, 0)
        auto_adv_layout.setSpacing(6)

        self.guide_auto_advance_spin = NumberStepper()
        self.guide_auto_advance_spin.setRange(0, 59)
        self.guide_auto_advance_spin.setValue(getattr(self.config_mgr, "guide_auto_advance_minute", 50))
        self.guide_auto_advance_spin.setPrefix(":")
        self.guide_auto_advance_spin.setSuffix(" min")
        self.guide_auto_advance_spin.setFixedWidth(120)
        self.guide_auto_advance_spin.valueChanged.connect(self._on_guide_auto_advance_min_changed)
        auto_adv_layout.addWidget(self.guide_auto_advance_spin)

        self.guide_auto_advance_check = QCheckBox()
        self.guide_auto_advance_check.setToolTip("Enable or disable guide auto-advance past the hour")
        self.guide_auto_advance_check.setChecked(getattr(self.config_mgr, "guide_auto_advance", True))
        self.guide_auto_advance_check.toggled.connect(self._on_guide_auto_advance_toggled)
        self.guide_auto_advance_spin.setEnabled(self.guide_auto_advance_check.isChecked())
        auto_adv_layout.addWidget(self.guide_auto_advance_check)

        auto_adv_badge = HelpBadge(
            "Automatically advances the guide forward to the next hour when the clock reaches the configured minute past the hour (default :50 min).\n\n"
            "Safeguards prevent scrolling while actively dragging or browsing past/future time slots, and auto-advance only runs when viewing today's guide."
        )
        auto_adv_layout.addWidget(auto_adv_badge)
        auto_adv_layout.addStretch()

        col3_grid.addWidget(auto_adv_widget, 2, 1, Qt.AlignmentFlag.AlignVCenter)

        lbl_clock_size = QLabel("<b>Clock Size:</b>")
        lbl_clock_size.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        col3_grid.addWidget(lbl_clock_size, 3, 0, Qt.AlignmentFlag.AlignVCenter)

        self.clock_size_spin = NumberStepper()
        self.clock_size_spin.setRange(8, 24)
        self.clock_size_spin.setValue(getattr(self.config_mgr, "clock_font_size", 11))
        self.clock_size_spin.setSuffix(" pt")
        self.clock_size_spin.setFixedWidth(120)
        self.clock_size_spin.valueChanged.connect(self._on_clock_size_changed)
        self.clock_size_spin.setEnabled(getattr(self.config_mgr, "show_clock", True))
        col3_grid.addWidget(self.clock_size_spin, 3, 1, Qt.AlignmentFlag.AlignVCenter)

        lbl_single_click = QLabel("<b>Single-Click Play:</b>")
        lbl_single_click.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        col3_grid.addWidget(lbl_single_click, 4, 0, Qt.AlignmentFlag.AlignVCenter)

        single_click_widget = QWidget()
        single_click_layout = QHBoxLayout(single_click_widget)
        single_click_layout.setContentsMargins(0, 0, 0, 0)
        single_click_layout.setSpacing(6)

        self.single_click_play_check = QCheckBox("Enable")
        self.single_click_play_check.setToolTip("Play live/recordings or open schedule options on a single click instead of requiring a double-click (click '?' for full details)")
        self.single_click_play_check.setChecked(getattr(self.config_mgr, "guide_single_click_play", True))
        self.single_click_play_check.toggled.connect(self._on_single_click_play_toggled)
        single_click_layout.addWidget(self.single_click_play_check)

        single_click_help = (
            "Single-Click Play vs Select for Details:\n\n"
            "• Single-Click Play (Enabled):\n"
            "  A single click immediately tunes live TV, plays recordings, or prompts to schedule upcoming airings.\n\n"
            "• Select for Details (Disabled):\n"
            "  A single click selects the show to view its full description and metadata in the bottom panel without starting playback. Double-click to play or schedule.\n\n"
            "• Right-Click Quick Actions:\n"
            "  Right-clicking any show opens the quick action popup menu with program details and instant Watch, Record, and Record Series pill buttons without playing the show or expanding the bottom box."
        )
        self.single_click_badge = HelpBadge(single_click_help)
        self.single_click_badge.setToolTip("Click for details on single-click, select, and right-click actions")
        single_click_layout.addWidget(self.single_click_badge)
        single_click_layout.addStretch()

        col3_grid.addWidget(single_click_widget, 4, 1, Qt.AlignmentFlag.AlignVCenter)

        col3_grid.setColumnStretch(1, 1)
        cols_row.addLayout(col3_grid, 1)

        color_layout.addLayout(cols_row)
        right_col.addWidget(color_box)

        # ------------------ Guide Grid Themes Card (Below Grid Guide Options) ------------------
        guide_theme_box = QGroupBox("Guide Grid Themes")
        guide_theme_layout = QVBoxLayout(guide_theme_box)
        guide_theme_layout.setContentsMargins(15, 15, 15, 15)
        guide_theme_layout.setSpacing(10)

        # Hidden combobox to preserve backward compatibility and signals
        self.theme_preset_combo = CenteredComboBox()
        self.theme_preset_combo.setVisible(False)
        self.theme_preset_combo.currentIndexChanged.connect(self._on_theme_preset_changed)

        # Guide Grid Themes and Custom Themes side-by-side
        guide_themes_row = QHBoxLayout()
        guide_themes_row.setSpacing(18)

        # Left: Preset Themes
        left_guide_layout = QVBoxLayout()
        left_guide_layout.setSpacing(6)
        hdr_guide_row = QHBoxLayout()
        lbl_guide_theme = QLabel("<b>Guide Grid Theme</b>")
        lbl_guide_theme.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        hdr_guide_row.addWidget(lbl_guide_theme)
        lbl_guide_hint = QLabel("(TV Guide tiles, category colors, timeline & clock)")
        lbl_guide_hint.setStyleSheet("font-size: 11px; color: #94a3b8;")
        hdr_guide_row.addWidget(lbl_guide_hint)
        hdr_guide_row.addStretch()
        left_guide_layout.addLayout(hdr_guide_row)

        self._guide_theme_chips: Dict[str, ThemeChip] = {}
        self.guide_theme_grid = QGridLayout()
        self.guide_theme_grid.setHorizontalSpacing(8)
        self.guide_theme_grid.setVerticalSpacing(6)
        left_grid_wrap = QHBoxLayout()
        left_grid_wrap.setContentsMargins(0, 0, 0, 0)
        left_grid_wrap.addLayout(self.guide_theme_grid)
        left_grid_wrap.addStretch()
        left_guide_layout.addLayout(left_grid_wrap)
        left_guide_layout.addStretch()
        guide_themes_row.addLayout(left_guide_layout, 0)

        # Right: Custom Themes (next to the grid guide themes)
        right_custom_layout = QVBoxLayout()
        right_custom_layout.setSpacing(6)
        hdr_custom_row = QHBoxLayout()
        hdr_custom_row.setContentsMargins(0, 0, 0, 0)
        hdr_custom_row.setSpacing(6)
        lbl_custom = QLabel("<b>Custom Grid Themes</b>")
        lbl_custom.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        hdr_custom_row.addWidget(lbl_custom)
        hdr_custom_row.addSpacing(4)

        btn_size = QSize(26, 24)
        icon_size = QSize(16, 16)

        self.save_theme_preset_btn = QPushButton()
        self.save_theme_preset_btn.setObjectName("saveThemePresetBtn")
        self.save_theme_preset_btn.setFixedSize(btn_size)
        self.save_theme_preset_btn.setIcon(self._create_save_theme_icon())
        self.save_theme_preset_btn.setIconSize(icon_size)
        self.save_theme_preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_theme_preset_btn.setToolTip("Save Theme As... (Save current guide grid colors as a new preset)")
        self.save_theme_preset_btn.clicked.connect(self._save_current_theme_preset)
        hdr_custom_row.addWidget(self.save_theme_preset_btn)

        self.delete_theme_preset_btn = QPushButton()
        self.delete_theme_preset_btn.setObjectName("deleteThemePresetBtn")
        self.delete_theme_preset_btn.setFixedSize(btn_size)
        self.delete_theme_preset_btn.setIcon(self._create_delete_theme_icon())
        self.delete_theme_preset_btn.setIconSize(icon_size)
        self.delete_theme_preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_theme_preset_btn.setToolTip("Delete Theme (Delete selected custom theme preset)")
        self.delete_theme_preset_btn.clicked.connect(self._delete_current_theme_preset)
        hdr_custom_row.addWidget(self.delete_theme_preset_btn)

        self.reset_cat_colors_btn = QPushButton()
        self.reset_cat_colors_btn.setObjectName("resetCatColorsBtn")
        self.reset_cat_colors_btn.setFixedSize(btn_size)
        self.reset_cat_colors_btn.setIcon(self._create_defaults_theme_icon())
        self.reset_cat_colors_btn.setIconSize(icon_size)
        self.reset_cat_colors_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_cat_colors_btn.setToolTip("Defaults (Reset guide grid colors to factory defaults)")
        self.reset_cat_colors_btn.clicked.connect(self._reset_category_colors)
        hdr_custom_row.addWidget(self.reset_cat_colors_btn)
        hdr_custom_row.addStretch()

        right_custom_layout.addLayout(hdr_custom_row)

        self.guide_custom_grid = QGridLayout()
        self.guide_custom_grid.setHorizontalSpacing(8)
        self.guide_custom_grid.setVerticalSpacing(6)
        right_grid_wrap = QHBoxLayout()
        right_grid_wrap.setContentsMargins(0, 0, 0, 0)
        right_grid_wrap.addLayout(self.guide_custom_grid)
        right_grid_wrap.addStretch()
        right_custom_layout.addLayout(right_grid_wrap)
        right_custom_layout.addStretch()
        guide_themes_row.addLayout(right_custom_layout, 1)

        self._populate_theme_preset_combo()

        guide_theme_layout.addLayout(guide_themes_row)

        right_col.addWidget(guide_theme_box)

        # ------------------ Themes & Styling Card (Below Guide Grid Themes) ------------------
        theme_box = QGroupBox("Themes && Styling")
        theme_layout = QVBoxLayout(theme_box)
        theme_layout.setContentsMargins(15, 15, 15, 15)
        theme_layout.setSpacing(10)

        # Hidden combobox to preserve backward compatibility and signals
        self.app_theme_combo = CenteredComboBox()
        self.app_theme_combo.setVisible(False)

        # Section: Application Theme Chips
        app_header_row = QHBoxLayout()
        lbl_app_theme = QLabel("<b>Application Theme</b>")
        lbl_app_theme.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        app_header_row.addWidget(lbl_app_theme)
        lbl_app_hint = QLabel("(Window, tables, dialogs, buttons & menus)")
        lbl_app_hint.setStyleSheet("font-size: 11px; color: #94a3b8;")
        app_header_row.addWidget(lbl_app_hint)
        app_header_row.addStretch()
        theme_layout.addLayout(app_header_row)

        self._app_theme_chips: Dict[str, ThemeChip] = {}
        self.app_theme_grid = QGridLayout()
        self.app_theme_grid.setHorizontalSpacing(8)
        self.app_theme_grid.setVerticalSpacing(6)
        self._build_app_theme_chips()
        app_grid_wrap = QHBoxLayout()
        app_grid_wrap.setContentsMargins(0, 0, 0, 0)
        app_grid_wrap.addLayout(self.app_theme_grid)
        app_grid_wrap.addStretch()
        theme_layout.addLayout(app_grid_wrap)

        right_col.addWidget(theme_box)

        # Application Window Dimensions (Under Themes & Styling)
        win_group = QGroupBox("Application Window Dimensions")
        win_layout = QVBoxLayout(win_group)
        win_layout.setContentsMargins(15, 15, 15, 15)
        win_layout.setSpacing(10)

        self.win_size_lbl = QLabel(self._get_window_size_label_text())
        self.win_size_lbl.setStyleSheet("color: #a0b2c6; font-size: 13px; font-weight: 500;")
        win_layout.addWidget(self.win_size_lbl)

        win_size_btn_row = QHBoxLayout()
        win_size_btn_row.setContentsMargins(0, 0, 0, 0)
        win_size_btn_row.setSpacing(10)

        self.save_win_size_btn = QPushButton("Save Size")
        self.save_win_size_btn.setObjectName("primaryActionBtn")
        self.save_win_size_btn.clicked.connect(self.save_current_window_size)
        win_size_btn_row.addWidget(self.save_win_size_btn)

        self.restore_win_size_btn = QPushButton("Restore Size")
        self.restore_win_size_btn.clicked.connect(self.restore_saved_window_size)
        win_size_btn_row.addWidget(self.restore_win_size_btn)

        self.reset_win_size_btn = QPushButton("Reset Default")
        self.reset_win_size_btn.clicked.connect(self.reset_window_size_to_default)
        win_size_btn_row.addWidget(self.reset_win_size_btn)
        win_size_btn_row.addStretch()
        win_layout.addLayout(win_size_btn_row)

        self.custom_title_bar_check = QCheckBox("Use Modern Frameless Title Bar (Custom drag, minimize && close)")
        self.custom_title_bar_check.setStyleSheet("color: #e2e8f0; font-size: 13px; font-weight: 500; margin-top: 4px;")
        self.custom_title_bar_check.setChecked(getattr(self.config_mgr, "use_custom_title_bar", True))
        self.custom_title_bar_check.toggled.connect(self._on_custom_title_bar_toggled)
        win_layout.addWidget(self.custom_title_bar_check)

        right_col.addWidget(win_group)
        right_col.addStretch()
        two_col_layout.addLayout(right_col, 60)

        main_layout.addLayout(two_col_layout)

        # Wire up auto-saves
        self.lead_time_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.end_buffer_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.auto_buffer_sports_check.stateChanged.connect(self._auto_save_automation_settings)
        self.sports_buffer_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.interval_spin.valueChanged.connect(self._auto_save_automation_settings)
        if hasattr(self, "guide_watch_combo"):
            self.guide_watch_combo.currentIndexChanged.connect(self._auto_save_automation_settings)
        if hasattr(self, "live_tv_mode_combo"):
            self.live_tv_mode_combo.currentIndexChanged.connect(self._auto_save_automation_settings)
        if hasattr(self, "custom_live_player_edit"):
            self.custom_live_player_edit.textChanged.connect(self._auto_save_automation_settings)
        if hasattr(self, "timeshift_buffer_spin"):
            self.timeshift_buffer_spin.valueChanged.connect(self._auto_save_automation_settings)
        if hasattr(self, "delete_timeshift_check"):
            self.delete_timeshift_check.stateChanged.connect(self._auto_save_automation_settings)
        self.notify_check.stateChanged.connect(self._auto_save_automation_settings)
        if hasattr(self, "notify_lead_spin"):
            self.notify_lead_spin.valueChanged.connect(self._auto_save_automation_settings)

        scroll.setWidget(container)
        return scroll

    # Subcategory 4: Updates and Maintenance
    def create_settings_updates_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # 1. Environment & Version Info
        env_box = QGroupBox("Application && System Environment")
        env_layout = QFormLayout(env_box)
        env_layout.setContentsMargins(15, 15, 15, 15)
        env_layout.setSpacing(10)

        from kaffeine_dvr.updater import get_install_info
        info = get_install_info()

        self.updates_current_ver_lbl = QLabel(f"<b>v{info['current_version']}</b>")
        env_layout.addRow("Installed Version:", self.updates_current_ver_lbl)

        install_type_str = f"Git Repository ({info['repo_path']})" if info['is_git'] else "Standard Package"
        self.updates_install_type_lbl = QLabel(install_type_str)
        env_layout.addRow("Installation Source:", self.updates_install_type_lbl)

        service_status = "Active and running" if info['is_service_active'] else "Inactive / Disabled"
        self.updates_service_lbl = QLabel(service_status)
        if info['is_service_active']:
            self.updates_service_lbl.setStyleSheet("color: #28a745; font-weight: bold;")
        else:
            self.updates_service_lbl.setStyleSheet("color: #8c98aa;")

        svc_row_widget = QWidget()
        svc_row_layout = QHBoxLayout(svc_row_widget)
        svc_row_layout.setContentsMargins(0, 0, 0, 0)
        svc_row_layout.setSpacing(10)
        svc_row_layout.addWidget(self.updates_service_lbl)

        self.start_svc_btn = QPushButton("Start && Enable Service")
        self.start_svc_btn.clicked.connect(self.start_background_service)
        svc_row_layout.addWidget(self.start_svc_btn)

        self.restart_svc_btn = QPushButton("Restart Service")
        self.restart_svc_btn.clicked.connect(self.restart_background_service)
        svc_row_layout.addWidget(self.restart_svc_btn)

        self.updates_view_logs_btn = QPushButton("View Logs")
        self.updates_view_logs_btn.clicked.connect(self.open_service_logs_dialog)
        svc_row_layout.addWidget(self.updates_view_logs_btn)
        self.view_svc_logs_btn = self.updates_view_logs_btn

        svc_row_layout.addStretch()

        env_layout.addRow("Background Watcher Service:", svc_row_widget)

        main_layout.addWidget(env_box)

        # 2. Update Preferences & Check Options
        pref_box = QGroupBox("Update Options && Frequency")
        pref_layout = QVBoxLayout(pref_box)
        pref_layout.setContentsMargins(15, 15, 15, 15)
        pref_layout.setSpacing(12)

        freq_row = QHBoxLayout()
        freq_row.setSpacing(10)
        self.auto_check_updates_cb = QCheckBox("Automatically check for updates:")
        self.auto_check_updates_cb.setChecked(self.config_mgr.auto_check_updates)
        self.auto_check_updates_cb.toggled.connect(self._on_auto_check_updates_toggled)
        freq_row.addWidget(self.auto_check_updates_cb)

        self.update_freq_combo = ThemedComboBox()
        self.update_freq_combo.addItems(["Weekly", "Monthly"])
        current_freq = self.config_mgr.update_check_frequency.capitalize()
        self.update_freq_combo.setCurrentText(current_freq if current_freq in ("Weekly", "Monthly") else "Weekly")
        self.update_freq_combo.setEnabled(self.config_mgr.auto_check_updates)
        self.update_freq_combo.currentTextChanged.connect(self._on_update_freq_changed)
        freq_row.addWidget(self.update_freq_combo)
        freq_row.addStretch()
        pref_layout.addLayout(freq_row)

        self.check_desc = QLabel(self._get_update_freq_desc_text())
        self.check_desc.setStyleSheet("color: #8c98aa; font-size: 11px;")
        self.check_desc.setWordWrap(True)
        pref_layout.addWidget(self.check_desc)

        btn_row = QHBoxLayout()
        self.check_updates_btn = QPushButton("Check for Updates Now")
        self.check_updates_btn.setObjectName("primaryActionBtn")
        self.check_updates_btn.clicked.connect(lambda: self.start_update_check(silent=False))
        btn_row.addWidget(self.check_updates_btn)


        last_check_ts = self.config_mgr.last_update_check_timestamp
        last_str = format_american_datetime_short(last_check_ts) if last_check_ts > 0 else "Never"
        self.last_check_lbl = QLabel(f"Last checked: {last_str}")
        self.last_check_lbl.setStyleSheet("color: #8c98aa; font-size: 11px;")
        btn_row.addWidget(self.last_check_lbl)
        btn_row.addStretch()
        pref_layout.addLayout(btn_row)

        main_layout.addWidget(pref_box)

        # 3. Update Status & Installation
        action_box = QGroupBox("Software Update Status")
        action_layout = QVBoxLayout(action_box)
        action_layout.setContentsMargins(15, 15, 15, 15)
        action_layout.setSpacing(12)

        self.update_status_lbl = QLabel("Click 'Check for Updates Now' to query for available updates.")
        self.update_status_lbl.setStyleSheet("font-size: 13px; color: #cdd6e2;")
        self.update_status_lbl.setWordWrap(True)
        action_layout.addWidget(self.update_status_lbl)

        # Pre-query latest release notes in background for the dialog
        QTimer.singleShot(500, self._load_initial_release_notes)

        self.update_progress_lbl = QLabel("")
        self.update_progress_lbl.setStyleSheet("color: #55a84c; font-size: 12px; font-weight: bold;")
        self.update_progress_lbl.setVisible(False)
        action_layout.addWidget(self.update_progress_lbl)

        install_btn_row = QHBoxLayout()
        install_btn_row.setSpacing(10)

        self.apply_update_btn = QPushButton("Install Update Now")
        self.apply_update_btn.setEnabled(False)
        self.apply_update_btn.clicked.connect(self.start_apply_update)
        install_btn_row.addWidget(self.apply_update_btn)

        self.view_notes_dialog_btn = QPushButton("View Release Notes...")
        self.view_notes_dialog_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_notes_dialog_btn.clicked.connect(self.open_release_notes_dialog)
        install_btn_row.addWidget(self.view_notes_dialog_btn)

        install_btn_row.addStretch()
        action_layout.addLayout(install_btn_row)

        main_layout.addWidget(action_box)

        # 4. Maintenance & Reset
        maint_box = QGroupBox("Maintenance")
        maint_layout = QVBoxLayout(maint_box)
        maint_layout.setContentsMargins(15, 15, 15, 15)
        maint_layout.setSpacing(12)

        maint_desc = QLabel(
            "Restore all application preferences, recording buffers, lead times, player options, and guide display settings to factory defaults. "
            "Your channel lineup and recording rules will be preserved."
        )
        maint_desc.setStyleSheet("color: #8c98aa; font-size: 12px;")
        maint_desc.setWordWrap(True)
        maint_layout.addWidget(maint_desc)

        maint_btn_row = QHBoxLayout()
        self.reset_defaults_btn = QPushButton("Reset to Default Settings")
        self.reset_defaults_btn.setStyleSheet(
            "QPushButton { background-color: #2e3846; color: #f87171; border: 1px solid #475569; font-weight: bold; padding: 6px 14px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #7f1d1d; color: #ffffff; border-color: #ef4444; }"
        )
        self.reset_defaults_btn.clicked.connect(self._confirm_reset_to_defaults)
        maint_btn_row.addWidget(self.reset_defaults_btn)
        maint_btn_row.addStretch()
        maint_layout.addLayout(maint_btn_row)

        main_layout.addWidget(maint_box)
        main_layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _confirm_reset_to_defaults(self):
        reply = QMessageBox.question(
            self,
            "Reset to Default Settings",
            "Are you sure you want to reset all settings to their default values?\n\n"
            "This will restore all buffers, lead times, player options, and guide display settings to defaults.\n\n"
            "Your channel lineup and recording rules will be preserved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config_mgr.reset_to_defaults(keep_channels_and_rules=True)
            self._refresh_all_settings_ui()
            self._apply_guide_zoom()
            if hasattr(self, "guide_grid_table"):
                self.guide_grid_table.viewport().update()
            self.flash_save_indicator("Settings restored to defaults")
            QMessageBox.information(
                self,
                "Settings Reset",
                "All settings have been restored to their default values."
            )

    def _refresh_all_settings_ui(self):
        # General / Automation tab
        if hasattr(self, "lead_time_spin"):
            self.lead_time_spin.blockSignals(True)
            self.lead_time_spin.setValue(self.config_mgr.lead_time_mins)
            self.lead_time_spin.blockSignals(False)

        if hasattr(self, "end_buffer_spin"):
            self.end_buffer_spin.blockSignals(True)
            self.end_buffer_spin.setValue(self.config_mgr.end_buffer_mins)
            self.end_buffer_spin.blockSignals(False)

        if hasattr(self, "auto_buffer_sports_check"):
            self.auto_buffer_sports_check.blockSignals(True)
            self.auto_buffer_sports_check.setChecked(self.config_mgr.auto_buffer_sports)
            self.auto_buffer_sports_check.blockSignals(False)

        if hasattr(self, "sports_buffer_spin"):
            self.sports_buffer_spin.blockSignals(True)
            self.sports_buffer_spin.setValue(self.config_mgr.sports_buffer_mins)
            self.sports_buffer_spin.blockSignals(False)

        if hasattr(self, "interval_spin"):
            self.interval_spin.blockSignals(True)
            self.interval_spin.setValue(self.config_mgr.watcher_interval_seconds)
            self.interval_spin.blockSignals(False)

        if hasattr(self, "notify_check"):
            self.notify_check.blockSignals(True)
            self.notify_check.setChecked(self.config_mgr.enable_desktop_notifications)
            self.notify_check.blockSignals(False)

        if hasattr(self, "notify_lead_spin"):
            self.notify_lead_spin.blockSignals(True)
            self.notify_lead_spin.setValue(self.config_mgr.notification_lead_time_mins)
            self.notify_lead_spin.setEnabled(self.config_mgr.enable_desktop_notifications)
            self.notify_lead_spin.blockSignals(False)

        if hasattr(self, "launch_mode_combo"):
            self.launch_mode_combo.blockSignals(True)
            idx = self.launch_mode_combo.findData(self.config_mgr.launch_mode)
            if idx >= 0:
                self.launch_mode_combo.setCurrentIndex(idx)
            self.launch_mode_combo.blockSignals(False)

        if hasattr(self, "live_tv_mode_combo"):
            self.live_tv_mode_combo.blockSignals(True)
            idx = self.live_tv_mode_combo.findData(self.config_mgr.live_tv_watch_mode)
            if idx >= 0:
                self.live_tv_mode_combo.setCurrentIndex(idx)
            self.live_tv_mode_combo.blockSignals(False)

        if hasattr(self, "custom_live_player_edit"):
            self.custom_live_player_edit.blockSignals(True)
            self.custom_live_player_edit.setText(self.config_mgr.custom_live_tv_player_cmd)
            self.custom_live_player_edit.blockSignals(False)

        if hasattr(self, "timeshift_buffer_spin"):
            self.timeshift_buffer_spin.blockSignals(True)
            self.timeshift_buffer_spin.setValue(self.config_mgr.timeshift_buffer_seconds)
            self.timeshift_buffer_spin.blockSignals(False)

        if hasattr(self, "delete_timeshift_check"):
            self.delete_timeshift_check.blockSignals(True)
            self.delete_timeshift_check.setChecked(self.config_mgr.delete_timeshift_on_exit)
            self.delete_timeshift_check.blockSignals(False)

        if hasattr(self, "custom_title_bar_check"):
            self.custom_title_bar_check.blockSignals(True)
            self.custom_title_bar_check.setChecked(getattr(self.config_mgr, "use_custom_title_bar", True))
            self.custom_title_bar_check.blockSignals(False)

        # Grid Guide Options
        if hasattr(self, "grid_rows_spin"):
            self.grid_rows_spin.blockSignals(True)
            self.grid_rows_spin.setValue(self.config_mgr.grid_visible_rows)
            self.grid_rows_spin.blockSignals(False)

        if hasattr(self, "hide_live_badge_check"):
            self.hide_live_badge_check.blockSignals(True)
            self.hide_live_badge_check.setChecked(self.config_mgr.hide_live_badge)
            self.hide_live_badge_check.blockSignals(False)

        if hasattr(self, "live_same_bg_check"):
            self.live_same_bg_check.blockSignals(True)
            self.live_same_bg_check.setChecked(self.config_mgr.live_same_bg_as_others)
            self.live_same_bg_check.blockSignals(False)

        if hasattr(self, "guide_desc_lines_combo"):
            self.guide_desc_lines_combo.blockSignals(True)
            d_idx = self.guide_desc_lines_combo.findData(self.config_mgr.guide_detail_lines)
            self.guide_desc_lines_combo.setCurrentIndex(d_idx if d_idx >= 0 else 1)
            self.guide_desc_lines_combo.blockSignals(False)
            self._update_guide_detail_box_height()

        if hasattr(self, "guide_auto_advance_check"):
            self.guide_auto_advance_check.blockSignals(True)
            self.guide_auto_advance_check.setChecked(self.config_mgr.guide_auto_advance)
            self.guide_auto_advance_check.blockSignals(False)

        if hasattr(self, "guide_auto_advance_spin"):
            self.guide_auto_advance_spin.blockSignals(True)
            self.guide_auto_advance_spin.setValue(self.config_mgr.guide_auto_advance_minute)
            self.guide_auto_advance_spin.setEnabled(self.config_mgr.guide_auto_advance)
            self.guide_auto_advance_spin.blockSignals(False)

        if hasattr(self, "hide_time_line_check"):
            self.hide_time_line_check.blockSignals(True)
            self.hide_time_line_check.setChecked(not self.config_mgr.guide_show_time_indicator)
            self.hide_time_line_check.blockSignals(False)

        if hasattr(self, "time_line_opacity_btn"):
            self.time_line_opacity_btn.setText(f"Opacity: {self.config_mgr.time_line_opacity}%")
            self.time_line_opacity_btn.setEnabled(self.config_mgr.guide_show_time_indicator)

        if hasattr(self, "hide_clock_check"):
            self.hide_clock_check.blockSignals(True)
            self.hide_clock_check.setChecked(not self.config_mgr.show_clock)
            self.hide_clock_check.blockSignals(False)

        if hasattr(self, "clock_size_spin"):
            self.clock_size_spin.blockSignals(True)
            self.clock_size_spin.setValue(self.config_mgr.clock_font_size)
            self.clock_size_spin.setEnabled(self.config_mgr.show_clock)
            self.clock_size_spin.blockSignals(False)
        self._update_clock_display()

        if hasattr(self, "single_click_play_check"):
            self.single_click_play_check.blockSignals(True)
            self.single_click_play_check.setChecked(self.config_mgr.guide_single_click_play)
            self.single_click_play_check.blockSignals(False)

        # Color Swatches & Theme Presets
        if hasattr(self, "app_theme_combo"):
            self.app_theme_combo.blockSignals(True)
            a_idx = self.app_theme_combo.findData(self.config_mgr.app_theme)
            self.app_theme_combo.setCurrentIndex(max(a_idx, 0))
            self.app_theme_combo.blockSignals(False)
        self._sync_app_theme_chips()

        if hasattr(self, "theme_preset_combo"):
            self.theme_preset_combo.blockSignals(True)
            p_idx = self.theme_preset_combo.findData(self.config_mgr.theme_preset)
            self.theme_preset_combo.setCurrentIndex(max(p_idx, 0))
            self.theme_preset_combo.blockSignals(False)
        self._sync_guide_theme_chips()

        colors = self.config_mgr.category_colors
        if hasattr(self, "_cat_swatches"):
            for cat_key, swatch_btn in self._cat_swatches.items():
                hex_val = colors.get(cat_key, DEFAULT_CATEGORY_COLORS.get(cat_key, "#ffffff"))
                swatch_btn.setStyleSheet(f"QPushButton.category-color-tile {{ background-color: {hex_val}; }}")

        # Updates tab
        if hasattr(self, "auto_check_updates_cb"):
            self.auto_check_updates_cb.blockSignals(True)
            self.auto_check_updates_cb.setChecked(self.config_mgr.auto_check_updates)
            self.auto_check_updates_cb.blockSignals(False)

        if hasattr(self, "update_freq_combo"):
            self.update_freq_combo.blockSignals(True)
            current_freq = self.config_mgr.update_check_frequency.capitalize()
            self.update_freq_combo.setCurrentText(current_freq if current_freq in ("Weekly", "Monthly") else "Weekly")
            self.update_freq_combo.setEnabled(self.config_mgr.auto_check_updates)
            self.update_freq_combo.blockSignals(False)

        if hasattr(self, "check_desc"):
            self.check_desc.setText(self._get_update_freq_desc_text())

    def _get_update_freq_desc_text(self) -> str:
        freq = self.config_mgr.update_check_frequency
        days_str = "7 days" if freq == "weekly" else "30 days"
        return (
            f"When enabled, Kaffeine DVR silently checks GitHub for new updates once every {days_str}. "
            "If an update is found, a subtle green badge appears in the bottom action bar with a dismissal button."
        )

    def _on_auto_check_updates_toggled(self, checked: bool):
        self.config_mgr.auto_check_updates = checked
        if hasattr(self, "update_freq_combo"):
            self.update_freq_combo.setEnabled(checked)
        self.flash_save_indicator("Update settings saved")

    def _on_update_freq_changed(self, text: str):
        self.config_mgr.update_check_frequency = text.lower()
        if hasattr(self, "check_desc"):
            self.check_desc.setText(self._get_update_freq_desc_text())
        self.flash_save_indicator(f"Update check set to {text.lower()}")

    def navigate_to_updates_tab(self):
        self.tabs.setCurrentIndex(2)
        self.settings_subtabs.setCurrentIndex(3)

    def dismiss_update_badge(self):
        self.update_badge_widget.setVisible(False)
        if hasattr(self, "_latest_detected_version") and self._latest_detected_version:
            self.config_mgr.dismissed_update_version = self._latest_detected_version

    def check_monthly_updates_on_startup(self):
        if not self.config_mgr.auto_check_updates:
            return
        now = time.time()
        last_check = self.config_mgr.last_update_check_timestamp
        freq = self.config_mgr.update_check_frequency
        # Weekly: 7 days = 7 * 86400 = 604800s. Monthly: 30 days = 30 * 86400 = 2592000s
        interval_seconds = 604800 if freq == "weekly" else 2592000
        if now - last_check >= interval_seconds:
            self.start_update_check(silent=True)

    def _load_initial_release_notes(self):
        """Asynchronously queries the latest release notes in the background for the dialog."""
        if not getattr(self, "_cached_release_notes", ""):
            self._initial_notes_worker = UpdateCheckWorker()
            self._initial_notes_worker.finished.connect(self._on_initial_notes_loaded)
            self._initial_notes_worker.finished.connect(self._initial_notes_worker.deleteLater)
            self._initial_notes_worker.start()

    def _on_initial_notes_loaded(self, res: dict):
        self._cached_release_notes = res.get("release_notes", "").strip()
        self._cached_latest_version = res.get("latest_version", "")
        self._cached_update_available = res.get("update_available", False)

    def open_release_notes_dialog(self):
        """Opens the interactive modal release notes dialog."""
        from kaffeine_dvr import __version__
        is_avail = bool(getattr(self, "_cached_update_available", False))
        if is_avail:
            version = getattr(self, "_cached_latest_version", "") or getattr(self, "_latest_detected_version", "") or __version__
        else:
            version = __version__

        notes = getattr(self, "_cached_release_notes", "").strip()
        if not notes:
            from kaffeine_dvr.updater import get_local_release_notes
            notes = get_local_release_notes(version)

        dlg = ReleaseNotesDialog(
            parent=self,
            version=version,
            notes=notes,
            update_available=is_avail,
            on_install_callback=self.start_apply_update if is_avail else None
        )
        dlg.exec()

    def start_update_check(self, silent: bool = False):
        if hasattr(self, "check_updates_btn"):
            self.check_updates_btn.setEnabled(False)
        if not silent and hasattr(self, "update_status_lbl"):
            self.update_status_lbl.setText("Checking for updates from GitHub / Git repository...")
        if not silent:
            self.status_bar.showMessage("Checking for application updates...")

        self.update_check_worker = UpdateCheckWorker()
        self.update_check_worker.finished.connect(lambda res: self.on_update_check_finished(res, silent))
        self.update_check_worker.finished.connect(self.update_check_worker.deleteLater)
        self.update_check_worker.start()

    def on_update_check_finished(self, res: dict, silent: bool):
        if hasattr(self, "check_updates_btn"):
            self.check_updates_btn.setEnabled(True)

        now = time.time()
        self.config_mgr.last_update_check_timestamp = now
        last_str = format_american_datetime_short(now)
        if hasattr(self, "last_check_lbl"):
            self.last_check_lbl.setText(f"Last checked: {last_str}")

        update_available = res.get("update_available", False)
        latest_ver = res.get("latest_version", "")
        details = res.get("details", "")

        if hasattr(self, "update_status_lbl"):
            if update_available:
                disp_ver = f"v{latest_ver}" if latest_ver else "available"
                formatted_details = f"New version <span style='color: #66bb6a; font-weight: bold;'>{disp_ver}</span> is available on GitHub."
                self.update_status_lbl.setText(formatted_details)
            else:
                self.update_status_lbl.setText(details)
        if hasattr(self, "apply_update_btn"):
            self.apply_update_btn.setEnabled(update_available)

        notes = res.get("release_notes", "").strip()
        self._cached_release_notes = notes
        self._cached_latest_version = latest_ver
        self._cached_update_available = update_available

        if update_available:
            self._latest_detected_version = latest_ver
            dismissed = self.config_mgr.dismissed_update_version
            if latest_ver != dismissed:
                if hasattr(self, "update_badge_widget") and hasattr(self, "update_badge_btn"):
                    self.update_badge_btn.setText(f"Update Available: v{latest_ver}")
                    self.update_badge_widget.setVisible(True)
            if not silent:
                self.status_bar.showMessage(f"Update available: v{latest_ver}", 5000)
        else:
            if hasattr(self, "update_badge_widget"):
                self.update_badge_widget.setVisible(False)
            if not silent:
                self.status_bar.showMessage("Application is up to date.", 4000)

    def start_apply_update(self):
        reply = QMessageBox.question(
            self,
            "Install Update",
            "Are you ready to download and install the latest update?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.apply_update_btn.setEnabled(False)
        if hasattr(self, "check_updates_btn"):
            self.check_updates_btn.setEnabled(False)
        self.update_progress_lbl.setVisible(True)
        self.update_progress_lbl.setText("Starting update...")
        self.status_bar.showMessage("Installing update...")

        self.update_apply_worker = UpdateApplyWorker()
        self.update_apply_worker.progress.connect(self._on_update_progress)
        self.update_apply_worker.finished.connect(self.on_update_apply_finished)
        self.update_apply_worker.finished.connect(self.update_apply_worker.deleteLater)
        self.update_apply_worker.start()

    def _on_update_progress(self, msg: str):
        self.update_progress_lbl.setText(msg)
        self.status_bar.showMessage(msg)

    def on_update_apply_finished(self, success: bool, msg: str):
        if hasattr(self, "check_updates_btn"):
            self.check_updates_btn.setEnabled(True)
        self.update_progress_lbl.setVisible(False)

        if success:
            self.update_status_lbl.setText("Update installed successfully!")
            self.apply_update_btn.setEnabled(False)
            if hasattr(self, "update_badge_widget"):
                self.update_badge_widget.setVisible(False)

            restart_reply = QMessageBox.question(
                self,
                "Update Complete",
                "The update has been installed successfully!\n\nWould you like to restart Kaffeine DVR now to apply the changes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if restart_reply == QMessageBox.StandardButton.Yes:
                self.restart_application()
        else:
            self.apply_update_btn.setEnabled(True)
            self.update_status_lbl.setText(f"Update failed: {msg}")
            QMessageBox.critical(self, "Update Failed", f"Failed to apply update:\n\n{msg}")

    def restart_application(self):
        from PyQt6.QtCore import QProcess
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

    # ------------------ TAB 5: HELP AND INFORMATION ------------------
    def create_help_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.help_subtabs = QTabWidget()
        self.help_subtabs.setObjectName("helpSubTabs")
        self.help_subtabs.addTab(self.create_help_setup_guide_tab(), "Quick Setup Guide")
        self.help_subtabs.addTab(self.create_help_grid_guide_tab(), "Grid Guide Usage && Capabilities")
        self.help_subtabs.addTab(self.create_help_reference_tab(), "System Architecture && Reference")
        layout.addWidget(self.help_subtabs)

        return widget

    def create_help_setup_guide_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)

        # Header Title
        title_box = QWidget()
        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 0, 0)
        h1 = QLabel("<b>Channel &amp; Guide Setup Walkthrough</b>")
        h1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h1.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        title_layout.addWidget(h1)
        layout.addWidget(title_box)

        # Base style helper
        make_card_style = lambda color: (
            "QGroupBox { font-size: 15px; font-weight: bold; margin-top: 14px; padding-top: 18px; } "
            f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top center; padding: 0 6px; color: {color}; }}"
        )
        body_style = "color: #d8e2ee; font-size: 14px; line-height: 1.6;"

        # Step 1: Physical Channels & Antenna Scan (Kaffeine)
        s1_box = QGroupBox("Step 1: Antenna Scan in Kaffeine")
        s1_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s1_box.setStyleSheet(make_card_style("#38bdf8"))
        s1_lay = QVBoxLayout(s1_box)
        s1_lay.setContentsMargins(15, 15, 15, 15)
        s1_text = QLabel(
            "• <b style='color: #38bdf8;'>Scan Channels with Your Digital TV Tuner:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;1. Open the native Kaffeine application.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;2. Go to <b>Television &gt; Channels</b> and run an automated scan for your ATSC/DVB antenna.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;3. Verify channels play properly. You can leave channels named with station callsigns (e.g. <code>KSAZ-HD</code>) or friendly names.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;4. Close Kaffeine once scanning is finished."
        )
        s1_text.setWordWrap(True)
        s1_text.setStyleSheet(body_style)
        s1_lay.addWidget(s1_text)
        layout.addWidget(s1_box)

        # Step 2: Import Channels & Organize Lineup
        s2_box = QGroupBox("Step 2: Import Channels && Organize Lineup (Settings > Channel Source)")
        s2_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s2_box.setStyleSheet(make_card_style("#4ade80"))
        s2_lay = QVBoxLayout(s2_box)
        s2_lay.setContentsMargins(15, 15, 15, 15)
        s2_text = QLabel(
            "• <b style='color: #4ade80;'>1. Automatic & One-Click Channel Import:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Channels are normally imported automatically during the initial Welcome Wizard.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– If you skipped that step or recently scanned new channels in Kaffeine, go to <b>Settings &gt; Channel Source</b> and click <b style='color: #4ade80;'>Import Channels from Kaffeine</b> to refresh your lineup.<br><br>"
            "• <b style='color: #4ade80;'>2. Channel Importing & Renaming (Left Panel - Format: Guide Name = Tuned Channel):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Want to rename how a channel appears in your guide? Do it here. This connects your guide display names to your tuned Kaffeine channels.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Example: <code style='color: #52b788;'>Fox = KSAZ-HD</code> displays 'Fox' in the guide while tuning KSAZ-HD on your antenna.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– If you renamed them already, leave them as <code style='color: #52b788;'>Fox = Fox</code>.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Click <b>Save Channels</b> when finished.<br><br>"
            "• <b style='color: #4ade80;'>3. TV Guide Channel Order (Right Panel):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Drag and drop channels or use <b>Move Up</b> / <b>Move Down</b> / <b>Sort A-Z</b> to prioritize how channels are stacked in your EPG TV Guide grid."
        )
        s2_text.setWordWrap(True)
        s2_text.setStyleSheet(body_style)
        s2_lay.addWidget(s2_text)
        layout.addWidget(s2_box)

        # Step 3: Choose & Configure Your Guide Feed
        s3_box = QGroupBox("Step 3: Guide Source Setup (National && Local Affiliates)")
        s3_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s3_box.setStyleSheet(make_card_style("#c084fc"))
        s3_lay = QVBoxLayout(s3_box)
        s3_lay.setContentsMargins(15, 15, 15, 15)
        s3_text = QLabel(
            "• <b style='color: #c084fc;'>National Networks (TVMaze - Zero Configuration):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Works out of the box with zero configuration for major national broadcast networks (FOX, CBS, NBC, ABC).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <i>Note:</i> TVMaze tracks national feeds only and <b>does not provide local programming</b> (local news, regional daytime talk shows, and independent subchannels). To receive local programming, TV Passport will need to be configured.<br><br>"
            "• <b style='color: #c084fc;'>Full 24/7 Local Affiliates, PBS, CW & Regional Channels (TV Passport):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;1. Open <a href='https://www.tvpassport.com/index.php/lineups' style='color: #64b5f6; font-weight: bold;'>tvpassport.com</a>, enter your ZIP/postal code, and select your local broadcast lineup.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;2. Copy the numeric station ID from the URL (e.g. <code>1809</code> for Fox Phoenix).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;3. Go to <b>Settings &gt; Guide Sources &amp; Health</b>, expand <b>TV Passport Station IDs</b>, and enter: <code>Guide Name = Station ID</code> (e.g. <code>Fox = 1809</code> or <code>PBS = 1184</code>).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;4. Click <b>Save Station IDs</b> to download 24/7 listings with local news, daytime syndication, and sports."
        )
        s3_text.setWordWrap(True)
        s3_text.setOpenExternalLinks(True)
        s3_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        s3_text.setStyleSheet(body_style)
        s3_lay.addWidget(s3_text)
        layout.addWidget(s3_box)

        # Step 4: Test Live TV & Schedule Recordings
        s4_box = QGroupBox("Step 4: Test Live TV && Schedule Recordings")
        s4_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s4_box.setStyleSheet(make_card_style("#60a5fa"))
        s4_lay = QVBoxLayout(s4_box)
        s4_lay.setContentsMargins(15, 15, 15, 15)
        s4_text = QLabel(
            "• <b style='color: #60a5fa;'>Navigating the TV Guide Grid:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Fluid Navigation:</b> Use the scrollbars or click and drag (grab) anywhere on the grid in any direction to smoothly pan through channels and time slots.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Grid Zoom (+ / -):</b> Use the <b>+</b> and <b>−</b> zoom buttons to increase or decrease the font and tile size of the guide grid to your preference.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Maximize Grid:</b> Click the <b>⛶ Maximize</b> button (or press <b>Escape</b> to exit) to expand the guide grid to fill the entire application window.<br><br>"
            "• <b style='color: #60a5fa;'>Watching Live TV:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Switch to <b>Web TV Guide Browser</b>. Double-click any live show tile or click <b>Watch Live</b> to tune Kaffeine.<br><br>"
            "• <b style='color: #60a5fa;'>Scheduling DVR Recordings:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Double-click upcoming shows or click <b>Record This Program</b> to queue a one-off recording.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Click <b>Auto-Record This Series</b> to create keyword auto-record rules that automatically capture all future airings.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– The unified background service (<code>kaffeine-dvr-watcher.service</code>) safely dispatches timers Just-In-Time without locking up system reboots."
        )
        s4_text.setWordWrap(True)
        s4_text.setStyleSheet(body_style)
        s4_lay.addWidget(s4_text)
        layout.addWidget(s4_box)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def create_help_reference_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)

        # Header Title
        title_box = QWidget()
        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 0, 0)
        h1 = QLabel("<b>Kaffeine DVR &amp; TV Info</b>")
        h1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h1.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        title_layout.addWidget(h1)
        layout.addWidget(title_box)

        # Base styles
        make_group_style = lambda color: (
            "QGroupBox { font-size: 15px; font-weight: bold; margin-top: 14px; padding-top: 18px; } "
            f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top center; padding: 0 6px; color: {color}; }}"
        )
        body_style = "color: #d8e2ee; font-size: 14px; line-height: 1.6;"

        # Section 1: Guide Sources & Coverage
        sources_box = QGroupBox("1. TV Guide Coverage and Providers")
        sources_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sources_box.setStyleSheet(make_group_style("#4ade80"))
        sources_layout = QVBoxLayout(sources_box)
        sources_layout.setContentsMargins(15, 15, 15, 15)
        sources_text = QLabel(
            "• <b style='color: #4ade80;'>National Broadcast Networks (TVMaze API):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Works out of the box with zero setup (no account, fees, or API keys required).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Covers major broadcast networks: FOX, CBS, NBC, and ABC.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Automatically fetches up to 7 days of prime-time listings upon launch.<br><br>"
            "• <b style='color: #4ade80;'>National Feeds vs. Local Daytime Programming:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– TVMaze provides national schedules (prime-time series, national sports, and network specials).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Daytime syndication, local news, PBS member stations, CW affiliates, and regional subchannels require TV Passport.<br><br>"
            "• <b style='color: #4ade80;'>24/7 Local Affiliate Schedules, PBS, CW & Regional Subchannels (TV Passport):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;1. Look up your local affiliate station on <a href='https://www.tvpassport.com/index.php/lineups' style='color: #64b5f6; font-weight: bold;'>tvpassport.com</a> (enter your ZIP code).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;2. Copy the numeric station ID from the URL and enter <code>ChannelName = StationID</code> in <i>Settings &gt; TV Passport</i>.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;3. Click <i>Save Station IDs</i> to automatically download full 24/7 local affiliate listings.<br><br>"
            "• <b style='color: #4ade80;'>Free Hybrid Mode (Recommended & Default):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Combines local 24/7 schedules from TV Passport with instant national listings from TVMaze.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Automatically avoids duplicate channel entries.<br><br>"
            "• <b style='color: #4ade80;'>Additional Custom Providers & International Support:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Supports custom local XMLTV files, remote XMLTV URLs, and paid Schedules Direct (Gracenote) accounts."
        )
        sources_text.setWordWrap(True)
        sources_text.setOpenExternalLinks(True)
        sources_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        sources_text.setStyleSheet(body_style)
        sources_layout.addWidget(sources_text)
        layout.addWidget(sources_box)

        # Section 2: Core Concept and Why this App Exists
        concept_box = QGroupBox("2. How Kaffeine DVR Scheduling Works")
        concept_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        concept_box.setStyleSheet(make_group_style("#f87171"))
        concept_layout = QVBoxLayout(concept_box)
        concept_layout.setContentsMargins(15, 15, 15, 15)
        concept_text = QLabel(
            "• <b style='color: #f87171;'>The Problem with Native Kaffeine Timers:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– When timers are stored directly inside Kaffeine, Kaffeine blocks Linux system reboots and shutdowns to avoid losing recordings.<br><br>"
            "• <b style='color: #f87171;'>Just-In-Time (JIT) Dispatching:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Upcoming recordings are stored safely in an external database queue (<code>recordings_queue.sqlite</code>).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Kaffeine stays clean with 0 active timers until a show is about to air.<br><br>"
            "• <b style='color: #f87171;'>Unified Background Watcher Daemon:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– A single background daemon (<code>kaffeine-dvr-watcher.service</code>) monitors the queue and syncs guide data.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Right before showtime (e.g. 5 minutes early), it automatically launches Kaffeine minimized and arms the timer via D-Bus.<br><br>"
            "• <b style='color: #f87171;'>Safe Power Operations:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– You can reboot or shut down your PC freely at any time without Kaffeine freezing or blocking systemd."
        )
        concept_text.setWordWrap(True)
        concept_text.setStyleSheet(body_style)
        concept_layout.addWidget(concept_text)
        layout.addWidget(concept_box)

        # Section 3: Background Service and System Commands
        services_box = QGroupBox("3. Unified Background Service and Commands")
        services_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        services_box.setStyleSheet(make_group_style("#60a5fa"))
        services_layout = QVBoxLayout(services_box)
        services_layout.setContentsMargins(15, 15, 15, 15)
        services_text = QLabel(
            "• <b style='color: #60a5fa;'>Unified Background Daemon:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <code>kaffeine-dvr-watcher.service</code> : Monitors the queue and refreshes guide feeds periodically.<br><br>"
            "• <b style='color: #60a5fa;'>Configurable Window Launch Modes (Settings &gt; Automation &amp; DVR):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Minimized to Taskbar (Default):</b> Silently minimizes to KDE panel via <code>kdotool</code>/<code>xdotool</code> without disturbing desktop workspace.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Minimize to System Tray:</b> Starts with <code>-m</code> flag to dock cleanly into the KDE system tray.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Normal Window:</b> Opens as a standard visible desktop window.<br><br>"
            "• <b style='color: #60a5fa;'>Command Line Utility (kaffeine-dvr):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <code>kaffeine-dvr --status</code> : Print provider health, cache counts, and Kaffeine status.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <code>kaffeine-dvr --list</code>   : List scheduled recordings in the DVR queue.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <code>kaffeine-dvr --sync</code>   : Force an immediate TV guide download.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <code>kaffeine-dvr --rules</code>  : Evaluate series auto-record rules immediately.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <code>kaffeine-dvr --watch</code>  : Run the watcher dispatcher in foreground debug mode.<br><br>"
            "• <b style='color: #60a5fa;'>Managing the Background Service:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <code>systemctl --user status kaffeine-dvr-watcher.service</code> : Check daemon running state.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <code>systemctl --user restart kaffeine-dvr-watcher.service</code> : Restart the background daemon.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <code>journalctl --user -u kaffeine-dvr-watcher.service -f</code> : Follow live daemon logs."
        )
        services_text.setWordWrap(True)
        services_text.setStyleSheet(body_style)
        services_layout.addWidget(services_text)
        layout.addWidget(services_box)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def create_help_grid_guide_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)

        # Header Title
        title_box = QWidget()
        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 0, 0)
        h1 = QLabel("<b>TV Guide Grid Usage &amp; Capabilities</b>")
        h1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h1.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        title_layout.addWidget(h1)
        sub1 = QLabel("Master navigation, continuous live channel playback, recording scheduling, and visual customization.")
        sub1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub1.setStyleSheet("font-size: 13px; color: #94a3b8;")
        title_layout.addWidget(sub1)
        layout.addWidget(title_box)

        # Base style helpers
        make_group_style = lambda color: (
            "QGroupBox { font-size: 15px; font-weight: bold; margin-top: 14px; padding-top: 18px; } "
            f"QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top center; padding: 0 6px; color: {color}; }}"
        )
        body_style = "color: #d8e2ee; font-size: 14px; line-height: 1.6;"

        # Section 1: Navigation & Interactive Controls
        nav_box = QGroupBox("1. Fluid Navigation && Grid Controls")
        nav_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_box.setStyleSheet(make_group_style("#38bdf8"))
        nav_layout = QVBoxLayout(nav_box)
        nav_layout.setContentsMargins(15, 15, 15, 15)
        nav_text = QLabel(
            "• <b style='color: #38bdf8;'>Smooth Hand-Grab Panning:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Click and drag anywhere across the guide grid to pan smoothly in any direction (both horizontal time and vertical channels).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Traditional vertical and horizontal scrollbars are also fully active at all times.<br><br>"
            "• <b style='color: #38bdf8;'>Quick Time Navigation (Header Bar):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Day Selector:</b> Jump between any of the 7 scheduled days instantly.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Now / Current Time:</b> Instantly scrolls the grid directly to the current broadcast hour with the real-time indicator line in view.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Prime Time:</b> Jump straight to 8:00 PM evening programming in one click.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Noon:</b> Jump straight to 12:00 PM midday programming in one click.<br><br>"
            "• <b style='color: #38bdf8;'>Auto-Advance Past the Hour:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– By default, when viewing today's guide, the grid automatically scrolls forward to the next hour when reaching your configured minute (default :50 past the hour).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Built-in safeguards automatically pause auto-advance while you are actively dragging or browsing past/future time slots.<br><br>"
            "• <b style='color: #38bdf8;'>Zoom & View Controls:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Zoom In (+) / Zoom Out (−):</b> Adjust grid tile dimensions and font sizes dynamically from compact to large.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Maximize Grid:</b> Expands the EPG grid to full-screen view. Press <b>Escape</b> anytime to restore standard view.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>View Toggle:</b> Switch between the visual <b>Grid Guide</b> and the filterable <b>List Guide</b>."
        )
        nav_text.setWordWrap(True)
        nav_text.setStyleSheet(body_style)
        nav_layout.addWidget(nav_text)
        layout.addWidget(nav_box)

        # Section 2: Continuous Channel Streaming & Single-Click Play
        play_box = QGroupBox("2. Continuous Live Streaming && Playback Modes")
        play_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        play_box.setStyleSheet(make_group_style("#4ade80"))
        play_lay = QVBoxLayout(play_box)
        play_lay.setContentsMargins(15, 15, 15, 15)
        play_text = QLabel(
            "• <b style='color: #4ade80;'>Continuous Channel Streaming (Click Channel Square):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Click any <b>Channel Square</b> on the far left column (e.g. ABC, NBC, CBS, FOX).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Launches continuous live TV playback that keeps streaming across show transitions uninterrupted without stopping when individual shows end.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– The active channel square highlights in bright live green (<code>#66bb6a</code>) and responds to mouse hover with an interactive glowing outline.<br><br>"
            "• <b style='color: #4ade80;'>Single-Click Play:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Enabled by default in <b>Settings &gt; Grid Guide Options &gt; Single-Click Play</b>.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Clicking any show tile immediately plays live TV, launches recorded playback for past shows, or prompts the scheduler for upcoming shows without requiring a second click.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– When disabled, clicking highlights and displays show details in the bottom panel, and double-clicking triggers playback.<br><br>"
            "• <b style='color: #4ade80;'>Live Timeshift vs. Direct Tuning:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Live Timeshift (Default):</b> Streams the live broadcast into your configured external media player (e.g. mpv or VLC) with pause, instant replay, and rewind controls.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Native Kaffeine Window:</b> Direct tuning brings the native Kaffeine DVB viewer window to the foreground."
        )
        play_text.setWordWrap(True)
        play_text.setStyleSheet(body_style)
        play_lay.addWidget(play_text)
        layout.addWidget(play_box)

        # Section 3: Show Selection, Details & Recording Workflows
        rec_box = QGroupBox("3. Program Details, Recording && Series Scheduling")
        rec_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rec_box.setStyleSheet(make_group_style("#f59e0b"))
        rec_lay = QVBoxLayout(rec_box)
        rec_lay.setContentsMargins(15, 15, 15, 15)
        rec_text = QLabel(
            "• <b style='color: #f59e0b;'>Bottom Program Detail Panel:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Displays complete program metadata: show title, episode name, season &amp; episode numbers, airtime range, broadcast duration, and full plot summary.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Displays live recording status indicators (e.g. <code>[● QUEUED]</code> or <code>[● RECORDING]</code>).<br><br>"
            "• <b style='color: #f59e0b;'>Smart Action Buttons:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Watch Live / Watch Channel:</b> Tune or stream the selected channel instantly.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Record Program:</b> Schedule a one-off recording for upcoming broadcasts.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Auto-Record This Series:</b> Creates keyword recording rules that automatically record all future episodes matching your criteria.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Cancel Recording / Adjust Buffers:</b> Easily adjust lead-in / lead-out minutes or remove scheduled timers directly from the guide.<br><br>"
            "• <b style='color: #f59e0b;'>Unhighlight & Deselect:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Click the currently highlighted program tile again, click empty grid space, or press <b>Escape</b> to unhighlight and reset the bottom action panel."
        )
        rec_text.setWordWrap(True)
        rec_text.setStyleSheet(body_style)
        rec_lay.addWidget(rec_text)
        layout.addWidget(rec_box)

        # Section 4: Visual Themes & Customization
        theme_box = QGroupBox("4. Themes, Colors && Visual Personalization")
        theme_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme_box.setStyleSheet(make_group_style("#c084fc"))
        theme_lay = QVBoxLayout(theme_box)
        theme_lay.setContentsMargins(15, 15, 15, 15)
        theme_text = QLabel(
            "• <b style='color: #c084fc;'>Guide Grid Presets & App Themes (Settings > Grid Guide Options):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Switch between built-in curated color palettes including <b>Midnight</b>, <b>Charcoal</b>, <b>Deep Blue</b>, <b>Slate</b>, and <b>High Contrast</b>.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Channel squares and grid headers dynamically match your active theme colors automatically.<br><br>"
            "• <b style='color: #c084fc;'>Genre & Category Color Coding:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Customize color swatches for <b>Sports</b>, <b>News</b>, <b>Movies</b>, and <b>TV Shows / Series</b>.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Shows are subtly color-coded by category for effortless scanning across prime-time lineups.<br><br>"
            "• <b style='color: #c084fc;'>Real-Time Indicator Line & Clock:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Time Line:</b> Displays a vertical cyan indicator line showing the exact current minute across all channels, with adjustable opacity.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Header Clock:</b> Live digital clock in the corner of the grid header with customizable font size and toggleable visibility.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– <b>Live Badge & Tint:</b> Toggle or customize the compact green 'LIVE' badge and background tint on active broadcasts."
        )
        theme_text.setWordWrap(True)
        theme_text.setStyleSheet(body_style)
        theme_lay.addWidget(theme_text)
        layout.addWidget(theme_box)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    # ------------------ SETTINGS ACTIONS ------------------
    def save_active_provider(self):
        new_prov = self.provider_combo.currentData()
        self.config_mgr.guide_provider = new_prov
        prov_name = self.provider_combo.currentText()
        self.test_all_sources_health(silent=True)
        self.status_bar.showMessage(f"Active guide provider set to: {prov_name}", 4000)
        self.flash_save_indicator("Active Provider Saved")
        QMessageBox.information(self, "Saved", f"Active guide provider switched to:\n{prov_name}")

    def test_all_sources_health(self, silent: bool = False):
        if not silent:
            self.test_health_btn.setEnabled(False)
            self.status_bar.showMessage("Testing connection and latency for all guide sources...")

        self.health_worker = HealthCheckWorker(self.guide_service)
        self.health_worker.finished.connect(lambda res: self.on_health_check_finished(res, silent))
        self.health_worker.finished.connect(self.health_worker.deleteLater)
        self.health_worker.start()

    def on_health_check_finished(self, results: Dict[str, Any], silent: bool):
        try:
            if hasattr(self, "test_health_btn") and self.test_health_btn:
                self.test_health_btn.setEnabled(True)
        except RuntimeError:
            return

        if not results:
            if not silent:
                try:
                    self.status_bar.showMessage("Health check failed.", 4000)
                except RuntimeError:
                    pass
            return

        try:
            self.health_table.setRowCount(len(results))
        except RuntimeError:
            return
        for row, (key, data) in enumerate(results.items()):
            name = data.get("name", key)
            ptype = data.get("provider_type", "API")
            status = data.get("status", "Unknown")
            latency = data.get("latency_ms", 0)
            cached = data.get("cached_shows", 0)
            details = data.get("details", "")

            # Latency display
            lat_str = f"{latency} ms" if latency > 0 else "-"

            # Status item with color styling
            status_item = QTableWidgetItem(status)
            status_item.setFont(QFont("", -1, QFont.Weight.Bold))
            if status == "Online":
                status_item.setForeground(QColor("#28a745"))
            elif status == "Degraded":
                status_item.setForeground(QColor("#fd7e14"))
            elif status == "Unconfigured":
                status_item.setForeground(QColor("#6c757d"))
            else:
                status_item.setForeground(QColor("#dc3545"))

            self.health_table.setItem(row, 0, QTableWidgetItem(name))
            self.health_table.setItem(row, 1, QTableWidgetItem(ptype))
            self.health_table.setItem(row, 2, status_item)
            self.health_table.setItem(row, 3, QTableWidgetItem(lat_str))
            self.health_table.setItem(row, 4, QTableWidgetItem(f"{cached} shows"))
            details_item = QTableWidgetItem(details)
            details_item.setToolTip(details)
            self.health_table.setItem(row, 5, details_item)

        self.health_table.resizeRowsToContents()
        total_rows_h = sum(self.health_table.rowHeight(r) for r in range(self.health_table.rowCount()))
        header_h = self.health_table.horizontalHeader().height()
        needed_h = header_h + total_rows_h + 6
        self.health_table.setFixedHeight(needed_h)

        if not silent:
            self.status_bar.showMessage("Source health check completed.", 4000)

    def browse_xmltv_file(self):
        start_dir = str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Select XMLTV File", start_dir, "XML Files (*.xml *.xmltv);;All Files (*)"
        )
        if path:
            self.xmltv_input.setText(path)

    def test_xmltv_feed(self):
        target = self.xmltv_input.text().strip()
        if not target:
            QMessageBox.warning(self, "Input Required", "Please enter a local file path or remote URL for XMLTV.")
            return

        self.status_bar.showMessage("Testing XMLTV source...")
        ok, details = self.guide_service.test_xmltv_source(target)
        if ok:
            self.test_all_sources_health(silent=True)
            QMessageBox.information(self, "XMLTV Valid", f"XMLTV source is accessible and valid:\n\n{details}")
        else:
            QMessageBox.critical(self, "XMLTV Error", f"Unable to read XMLTV source:\n\n{details}")
        self.status_bar.showMessage("XMLTV check completed.", 3000)

    def save_xmltv_settings(self):
        path = self.xmltv_input.text().strip()
        self.config_mgr.xmltv_path_or_url = path
        self.test_all_sources_health(silent=True)
        QMessageBox.information(self, "Saved", "XMLTV setting saved successfully.")

    def verify_sd_account(self):
        u = self.sd_user_input.text().strip()
        p = self.sd_pass_input.text().strip()
        if not u or not p:
            QMessageBox.warning(self, "Input Required", "Please enter both username and password.")
            return

        self.status_bar.showMessage("Contacting Schedules Direct...")
        ok, details = self.guide_service.test_schedules_direct_login(u, p)
        if ok:
            self.test_all_sources_health(silent=True)
            QMessageBox.information(self, "Authentication Successful", f"Schedules Direct account verified:\n\n{details}")
        else:
            QMessageBox.critical(self, "Authentication Failed", f"Schedules Direct authentication error:\n\n{details}")
        self.status_bar.showMessage("Schedules Direct check completed.", 3000)

    def save_sd_settings(self):
        u = self.sd_user_input.text().strip()
        p = self.sd_pass_input.text().strip()
        l = self.sd_lineup_input.text().strip()
        self.config_mgr.schedules_direct = {"username": u, "password": p, "lineup": l}
        self.test_all_sources_health(silent=True)
        QMessageBox.information(self, "Saved", "Schedules Direct credentials saved successfully.")

    def update_tvpassport_notice(self):
        unconfigured = self.config_mgr.get_unconfigured_regional_channels()
        if unconfigured:
            ch_list_str = ", ".join(unconfigured)
            if hasattr(self, "passport_header_warning"):
                self.passport_header_warning.setText(
                    f"Action Needed: Regional channel(s) require Station ID: {ch_list_str}"
                )
                self.passport_header_warning.setVisible(True)
            if hasattr(self, "passport_notice"):
                self.passport_notice.setText(
                    f"<div style='border: 1px solid #c8832a; border-radius: 6px; background-color: #2b2214; padding: 10px 14px; color: #ffc107; font-size: 13px; margin-top: 6px; margin-bottom: 8px; line-height: 1.5;'>"
                    f"<b>Action Needed:</b> The following scanned channel(s) are local/regional and not covered by national feeds: "
                    f"<b>{ch_list_str}</b>.<br><br>"
                    f"<b>Where to get Station IDs:</b><br>"
                    f"Go to <a href='https://www.tvpassport.com/index.php/lineups' style='color: #64b5f6; font-weight: bold; text-decoration: underline;'>https://www.tvpassport.com/index.php/lineups</a>, "
                    f"enter your ZIP/postal code, choose your antenna lineup, click on your channel, and copy the numeric ID from the URL (e.g. <code>/station/1812/</code>).<br><br>"
                    f"<b>Do you need to click sync?</b><br>"
                    f"<b>No manual sync required:</b> When you click <i>Save Station IDs</i> below, Kaffeine DVR will automatically save the station, verify connection health, and immediately sync guide listings in the background.</div>"
                )
                self.passport_notice.setVisible(True)
        else:
            if hasattr(self, "passport_header_warning"):
                self.passport_header_warning.setVisible(False)
            if hasattr(self, "passport_notice"):
                self.passport_notice.setVisible(False)

    def save_tvpassport_settings(self):
        raw = self.passport_stations_text.toPlainText()
        stations = {}
        for line in raw.splitlines():
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() and v.strip():
                    stations[k.strip()] = v.strip()
        self.config_mgr.tvpassport_stations = stations

        # Ensure station names exist in channel_map so they immediately appear in all dropdowns
        cur_map = dict(self.config_mgr.channel_map)
        for st_name in stations:
            if st_name not in cur_map:
                cur_map[st_name] = st_name
        self.config_mgr.channel_map = cur_map
        self.guide_service.set_channel_map(cur_map)
        if hasattr(self, "mapping_text"):
            self.populate_channel_mapping_text()

        self.update_tvpassport_notice()
        self.refresh_channel_dropdowns()
        self.test_all_sources_health(silent=True)

        # Automatically sync guide in background so listings for the new channel are downloaded immediately
        QTimer.singleShot(400, self.sync_guide)
        self.flash_save_indicator("Station IDs Saved")

        QMessageBox.information(
            self, "Saved & Syncing",
            f"Saved {len(stations)} TV Passport station mapping(s).\n\n"
            f"TV Guide sync has been started in the background to fetch listings immediately."
        )

    def save_channel_mapping(self):
        raw_text = self.mapping_text.toPlainText()
        new_map = {}
        for line in raw_text.splitlines():
            line = re.sub(r"^[●\s]+", "", line).strip()
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() and v.strip():
                    new_map[k.strip()] = v.strip()
        self.config_mgr.channel_map = new_map
        self.guide_service.set_channel_map(new_map)
        self.populate_channel_mapping_text()
        self.update_tvpassport_notice()
        self.refresh_channel_order_list()
        self.refresh_channel_dropdowns()
        self.flash_save_indicator("Lineup Saved")
        QMessageBox.information(self, "Saved", "Channel mapping saved successfully.")
        self.filter_guide()

    def import_channels_from_kaffeine(self, silent: bool = False) -> int:
        channels = self.config_mgr.get_scanned_kaffeine_channels()
        if not channels:
            if not silent:
                QMessageBox.warning(
                    self, "No Kaffeine Channels Found",
                    "No scanned digital TV channels were found in Kaffeine's database (~/.local/share/kaffeine/sqlite.db).\n\n"
                    "Please ensure you have performed an antenna channel scan in Kaffeine first."
                )
            return 0

        # Build clean 1:1 mapping directly from scanned channels
        current_map = {}
        for ch in channels:
            ch_name = ch["name"].strip()
            current_map[ch_name] = ch_name

        self.config_mgr.channel_map = current_map
        self.guide_service.set_channel_map(current_map)
        self.populate_channel_mapping_text()
        self.update_tvpassport_notice()
        self.refresh_channel_order_list()
        self.refresh_channel_dropdowns()
        self.filter_guide()

        if not silent:
            names_str = ", ".join([f"{c['name']} (Ch {c['number']})" if c.get('number') else c['name'] for c in channels])
            QMessageBox.information(
                self, "Channels Imported",
                f"Successfully imported {len(channels)} channel(s) from Kaffeine:\n{names_str}\n\n"
                f"Review the mappings above and click 'Save Channels' to persist."
            )
        return len(channels)

    def check_first_run(self):
        guide_status = self.guide_service.get_guide_status()
        is_empty = guide_status.get("total_programs", 0) == 0
        if not self.config_mgr.first_run_completed or is_empty:
            dlg = FirstRunWelcomeDialog(self.config_mgr, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                if dlg.import_check.isChecked():
                    self.import_channels_from_kaffeine(silent=True)
                if getattr(dlg, "service_check", None) and dlg.service_check.isChecked():
                    try:
                        ensure_systemd_service(force=True)
                        res = subprocess.run(
                            ["systemctl", "--user", "enable", "--now", "kaffeine-dvr-watcher.service"],
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        if res.returncode != 0:
                            print(f"Error starting background service: {res.stderr.strip() or res.stdout.strip()}", flush=True)
                        self.update_service_status_ui()
                    except Exception as e:
                        print(f"Error starting background service: {e}", flush=True)
                if dlg.sync_check.isChecked():
                    QTimer.singleShot(600, self.sync_guide)
            self.config_mgr.first_run_completed = True

    def reset_channel_mapping_defaults(self):
        confirm = QMessageBox.question(
            self, "Reset Channels",
            "Reset channel mappings by re-importing from Kaffeine's scanned channel list?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.import_channels_from_kaffeine(silent=False)

    def flash_save_indicator(self, text: str = "Settings Saved"):
        """Displays a saved confirmation in the top-right corner, then returns to idle."""
        if not hasattr(self, "save_indicator_lbl"):
            return
        self.save_indicator_lbl.setText(f"✓ {text}")
        self.save_indicator_lbl.setStyleSheet(
            "color: #78c48a; font-size: 11px; padding: 4px 6px; background: transparent;"
        )
        if hasattr(self, "_save_indicator_timer") and self._save_indicator_timer:
            self._save_indicator_timer.stop()
        self._save_indicator_timer = QTimer(self)
        self._save_indicator_timer.setSingleShot(True)
        self._save_indicator_timer.timeout.connect(self._reset_save_indicator)
        self._save_indicator_timer.start(1400)

    def _reset_save_indicator(self):
        if hasattr(self, "save_indicator_lbl"):
            self.save_indicator_lbl.setText("Auto-save active")
            self.save_indicator_lbl.setStyleSheet(
                "color: #8c98aa; font-size: 11px; padding: 2px 4px; background: transparent;"
            )

    def _get_window_size_label_text(self) -> str:
        cur_w = self.width() if self.isVisible() else (self.size().width() or 1100)
        cur_h = self.height() if self.isVisible() else (self.size().height() or 750)
        saved_w = self.settings.value("custom_window_width", type=int) if hasattr(self, "settings") else 0
        saved_h = self.settings.value("custom_window_height", type=int) if hasattr(self, "settings") else 0
        if saved_w and saved_h:
            return f"Current Size: {cur_w} × {cur_h}  (Saved: {saved_w} × {saved_h})"
        return f"Current Size: {cur_w} × {cur_h}  (Default: 1100 × 750)"

    def save_current_window_size(self):
        cur_w = self.width()
        cur_h = self.height()
        self.settings.setValue("custom_window_width", cur_w)
        self.settings.setValue("custom_window_height", cur_h)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.sync()
        if hasattr(self, "win_size_lbl"):
            self.win_size_lbl.setText(self._get_window_size_label_text())
        self.flash_save_indicator(f"Window Size Saved ({cur_w} × {cur_h})")

    def restore_saved_window_size(self):
        saved_w = self.settings.value("custom_window_width", type=int) if hasattr(self, "settings") else 0
        saved_h = self.settings.value("custom_window_height", type=int) if hasattr(self, "settings") else 0
        if saved_w and saved_h:
            self.resize(saved_w, saved_h)
            self.flash_save_indicator(f"Restored Saved Size ({saved_w} × {saved_h})")
        else:
            self.resize(1100, 750)
            self.flash_save_indicator("Restored Default Size (1100 × 750)")
        if hasattr(self, "win_size_lbl"):
            self.win_size_lbl.setText(self._get_window_size_label_text())

    def reset_window_size_to_default(self):
        self.settings.remove("custom_window_width")
        self.settings.remove("custom_window_height")
        self.settings.remove("geometry")
        self.settings.sync()
        self.resize(1100, 750)
        if hasattr(self, "win_size_lbl"):
            self.win_size_lbl.setText(self._get_window_size_label_text())
        self.flash_save_indicator("Window Size Reset (1100 × 750)")

    def _update_window_frame_styling(self):
        use_custom = getattr(self.config_mgr, "use_custom_title_bar", True)
        is_floating = use_custom and not self.isMaximized() and not self.isFullScreen()
        prop_val = "true" if is_floating else "false"

        cw = self.centralWidget()
        if cw:
            cw.setProperty("frameless_rounded", prop_val)
            cw.style().unpolish(cw)
            cw.style().polish(cw)

        if hasattr(self, "custom_title_bar") and self.custom_title_bar:
            self.custom_title_bar.setProperty("frameless_rounded", prop_val)
            self.custom_title_bar.style().unpolish(self.custom_title_bar)
            self.custom_title_bar.style().polish(self.custom_title_bar)

        if hasattr(self, "status_bar") and self.status_bar:
            self.status_bar.setProperty("frameless_rounded", prop_val)
            self.status_bar.style().unpolish(self.status_bar)
            self.status_bar.style().polish(self.status_bar)

        if hasattr(self, "corner_grip") and self.corner_grip:
            self.corner_grip.setVisible(is_floating)
            self._reposition_corner_grip()

    def _reposition_corner_grip(self):
        if hasattr(self, "corner_grip") and self.corner_grip:
            grip_size = self.corner_grip.size()
            self.corner_grip.move(self.width() - grip_size.width() - 1, self.height() - grip_size.height() - 1)
            self.corner_grip.raise_()

    def _on_custom_title_bar_toggled(self, checked: bool):
        self.config_mgr.use_custom_title_bar = checked
        if hasattr(self, "custom_title_bar"):
            self.custom_title_bar.setVisible(checked)
        flags = self.windowFlags()
        if checked:
            self.setWindowFlags(flags | Qt.WindowType.FramelessWindowHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.FramelessWindowHint)
        self.show()
        self._update_window_frame_styling()
        self._update_clock_display()
        self.flash_save_indicator("Title Bar preference saved")

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            if hasattr(self, "custom_title_bar"):
                self.custom_title_bar.update_max_button_icon()
            self._update_window_frame_styling()
        super().changeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition_corner_grip()
        QTimer.singleShot(0, self._adjust_table_columns)
        QTimer.singleShot(100, self._adjust_table_columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_corner_grip()
        if hasattr(self, "win_size_lbl"):
            self.win_size_lbl.setText(self._get_window_size_label_text())
        self._adjust_table_columns()
        if hasattr(self, "_apply_guide_zoom"):
            self._apply_guide_zoom()

    def _adjust_table_columns(self):
        """Dynamically distributes column widths proportionally based on available table viewport width."""
        # 1. Active Schedule Table
        if hasattr(self, "rec_table"):
            rec_w = self.rec_table.viewport().width()
            if rec_w > 100:
                # Title, Schedule, Channel, Duration, Status, Retain
                min_widths = [200, 130, 65, 115, 170, 55]
                shares = [0.36, 0.17, 0.08, 0.13, 0.20, 0.06]
                allocated = [max(mw, int(rec_w * s)) for mw, s in zip(min_widths, shares)]
                diff = rec_w - sum(allocated)
                if diff > 0:
                    allocated[0] += diff
                h = self.rec_table.horizontalHeader()
                for i, fw in enumerate(allocated):
                    h.resizeSection(i, fw)

        # 2. History Table
        if hasattr(self, "history_table"):
            hist_w = self.history_table.viewport().width()
            if hist_w > 100:
                # Title, Date / Time, Channel, Runtime
                min_widths = [220, 160, 80, 90]
                shares = [0.44, 0.26, 0.15, 0.15]
                allocated = [max(mw, int(hist_w * s)) for mw, s in zip(min_widths, shares)]
                diff = hist_w - sum(allocated)
                if diff > 0:
                    allocated[0] += diff
                h = self.history_table.horizontalHeader()
                for i, fw in enumerate(allocated):
                    h.resizeSection(i, fw)

    def _auto_save_automation_settings(self):
        """Silently persist automation and storage retention settings whenever any control is changed."""
        if not hasattr(self, "lead_time_spin") or not hasattr(self, "cleanup_enable_check"):
            return
        self.config_mgr.lead_time_mins = self.lead_time_spin.value()
        if hasattr(self, "end_buffer_spin"):
            self.config_mgr.end_buffer_mins = self.end_buffer_spin.value()
        if hasattr(self, "auto_buffer_sports_check"):
            self.config_mgr.auto_buffer_sports = self.auto_buffer_sports_check.isChecked()
        if hasattr(self, "sports_buffer_spin"):
            self.config_mgr.sports_buffer_mins = self.sports_buffer_spin.value()
        self.config_mgr.watcher_interval_seconds = self.interval_spin.value()
        self.config_mgr.launch_mode = self.launch_mode_combo.currentData()
        if hasattr(self, "guide_watch_combo"):
            self.config_mgr.guide_watch_mode = self.guide_watch_combo.currentData()
        if hasattr(self, "live_tv_mode_combo"):
            mode = self.live_tv_mode_combo.currentData()
            self.config_mgr.live_tv_watch_mode = mode
            self.config_mgr.playback_player = mode
        if hasattr(self, "custom_live_player_edit"):
            cmd = self.custom_live_player_edit.text().strip()
            self.config_mgr.custom_live_tv_player_cmd = cmd
            self.config_mgr.custom_playback_player_cmd = cmd
        if hasattr(self, "timeshift_buffer_spin"):
            self.config_mgr.timeshift_buffer_seconds = self.timeshift_buffer_spin.value()
        if hasattr(self, "delete_timeshift_check"):
            self.config_mgr.delete_timeshift_on_exit = self.delete_timeshift_check.isChecked()
        self.config_mgr.enable_desktop_notifications = self.notify_check.isChecked()
        if hasattr(self, "notify_lead_spin"):
            self.config_mgr.notification_lead_time_mins = self.notify_lead_spin.value()
        if hasattr(self, "grid_rows_spin"):
            self.config_mgr.grid_visible_rows = self.grid_rows_spin.value()
        if hasattr(self, "hide_live_badge_check"):
            self.config_mgr.hide_live_badge = self.hide_live_badge_check.isChecked()
        if hasattr(self, "live_same_bg_check"):
            self.config_mgr.live_same_bg_as_others = self.live_same_bg_check.isChecked()
        if hasattr(self, "guide_desc_lines_combo"):
            self.config_mgr.guide_detail_lines = self.guide_desc_lines_combo.currentData()
        if hasattr(self, "guide_auto_advance_check"):
            self.config_mgr.guide_auto_advance = self.guide_auto_advance_check.isChecked()
        if hasattr(self, "guide_auto_advance_spin"):
            self.config_mgr.guide_auto_advance_minute = self.guide_auto_advance_spin.value()
        if hasattr(self, "hide_time_line_check"):
            self.config_mgr.guide_show_time_indicator = not self.hide_time_line_check.isChecked()
        if hasattr(self, "hide_clock_check"):
            self.config_mgr.show_clock = not self.hide_clock_check.isChecked()
        if hasattr(self, "clock_size_spin"):
            self.config_mgr.clock_font_size = self.clock_size_spin.value()

        # Storage & Retention settings
        self.config_mgr.auto_cleanup_enabled = self.cleanup_enable_check.isChecked()
        self.config_mgr.retention_days = self.retention_days_spin.value()
        self.config_mgr.min_free_disk_gb = self.min_free_spin.value()
        self.config_mgr.custom_recording_folder = self.custom_folder_input.text().strip()

        self.update_storage_status_ui()
        self.flash_save_indicator("Settings Saved")

    def _update_guide_detail_box_height(self):
        """Size description box to fit 2 or 3 lines of text based on user setting."""
        if not hasattr(self, "guide_detail_text"):
            return
        lines = getattr(self.config_mgr, "guide_detail_lines", 3)
        line_height = self.guide_detail_text.fontMetrics().lineSpacing()
        doc_margin = int(self.guide_detail_text.document().documentMargin())
        desc_height = line_height * lines + doc_margin * 2 + 16
        self.guide_detail_text.setFixedHeight(desc_height)

    def _apply_guide_detail_collapsed_state(self):
        """Show or hide the description box based on guide_detail_collapsed."""
        collapsed = bool(getattr(self.config_mgr, "guide_detail_collapsed", False))
        if hasattr(self, "guide_detail_text"):
            self.guide_detail_text.setVisible(not collapsed)
        if hasattr(self, "guide_detail_collapse_btn"):
            if collapsed:
                self.guide_detail_collapse_btn.setText("▼")
                self.guide_detail_collapse_btn.setToolTip("Expand program description box")
            else:
                self.guide_detail_collapse_btn.setText("▲")
                self.guide_detail_collapse_btn.setToolTip("Collapse program description box")

        if hasattr(self, "guide_desc_lines_combo") and self.guide_desc_lines_combo:
            self.guide_desc_lines_combo.blockSignals(True)
            if not collapsed:
                lines = getattr(self.config_mgr, "guide_detail_lines", 3)
                idx = self.guide_desc_lines_combo.findData(lines)
                if idx >= 0:
                    self.guide_desc_lines_combo.setCurrentIndex(idx)
            self.guide_desc_lines_combo.blockSignals(False)

    def toggle_guide_detail_collapsed(self):
        """Toggle collapsed/expanded state of the program description box."""
        collapsed = not getattr(self.config_mgr, "guide_detail_collapsed", False)
        self.config_mgr.guide_detail_collapsed = collapsed
        self._apply_guide_detail_collapsed_state()
        self._apply_guide_zoom()
        status_msg = "Description Box Collapsed" if collapsed else "Description Box Expanded"
        self.flash_save_indicator(status_msg)

    def _on_guide_desc_lines_changed(self, idx: int):
        val = self.guide_desc_lines_combo.currentData()
        if val in (2, 3):
            self.config_mgr.guide_detail_collapsed = False
            self.config_mgr.guide_detail_lines = val
            self._apply_guide_detail_collapsed_state()
            self._update_guide_detail_box_height()
            self._apply_guide_zoom()
            self.flash_save_indicator("Settings Saved")

    def _on_grid_rows_changed(self, val: int):
        self.config_mgr.grid_visible_rows = val
        self.guide_grid_zoom_level = 0
        self.settings.setValue("guide_grid_zoom_level", 0)
        self._apply_guide_zoom()
        if hasattr(self, "_update_zoom_buttons_state"):
            self._update_zoom_buttons_state()

    def _on_hide_live_badge_toggled(self, checked: bool):
        self.config_mgr.hide_live_badge = checked
        if hasattr(self, "guide_grid_table"):
            self.guide_grid_table.viewport().update()

    def _on_live_same_bg_toggled(self, checked: bool):
        self.config_mgr.live_same_bg_as_others = checked
        if hasattr(self, "guide_grid_table"):
            self.guide_grid_table.viewport().update()

    def _on_guide_auto_advance_toggled(self, checked: bool):
        self.config_mgr.guide_auto_advance = checked
        if hasattr(self, "guide_auto_advance_spin"):
            self.guide_auto_advance_spin.setEnabled(checked)

    def _on_guide_auto_advance_min_changed(self, val: int):
        self.config_mgr.guide_auto_advance_minute = val

    def _on_single_click_play_toggled(self, checked: bool):
        self.config_mgr.guide_single_click_play = checked
        sel = getattr(self, "selected_grid_program", None) or self._get_active_selected_program()
        if sel:
            self._display_program_details(sel)
        else:
            if hasattr(self, "watch_guide_btn") and checked:
                self.watch_guide_btn.setVisible(False)
            if hasattr(self, "stop_timeshift_btn") and checked:
                self.stop_timeshift_btn.setVisible(False)

    def _on_hide_time_line_toggled(self, checked: bool):
        self.config_mgr.guide_show_time_indicator = not checked
        if hasattr(self, "time_line_opacity_btn"):
            self.time_line_opacity_btn.setEnabled(not checked)
        if hasattr(self, "guide_grid_table"):
            self.guide_grid_table.viewport().update()
            if self.guide_grid_table.horizontalHeader():
                self.guide_grid_table.horizontalHeader().viewport().update()

    def _open_time_line_opacity_popup(self):
        app_theme = getattr(self.config_mgr, "app_theme", "midnight") if hasattr(self, "config_mgr") and self.config_mgr else "midnight"
        tokens = APP_THEMES.get(app_theme, APP_THEMES["midnight"])
        OpacitySliderPopup.show_for_widget(
            self.time_line_opacity_btn,
            self.config_mgr.time_line_opacity,
            self._on_time_line_opacity_changed,
            tokens=tokens
        )

    def _on_time_line_opacity_changed(self, val: int):
        self.config_mgr.time_line_opacity = val
        if hasattr(self, "time_line_opacity_btn"):
            self.time_line_opacity_btn.setText(f"Opacity: {val}%")
        if hasattr(self, "guide_grid_table"):
            self.guide_grid_table.viewport().update()
            if self.guide_grid_table.horizontalHeader():
                self.guide_grid_table.horizontalHeader().viewport().update()

    def _on_hide_clock_toggled(self, checked: bool):
        self.config_mgr.show_clock = not checked
        if hasattr(self, "hide_clock_check") and self.hide_clock_check.isChecked() != checked:
            self.hide_clock_check.blockSignals(True)
            self.hide_clock_check.setChecked(checked)
            self.hide_clock_check.blockSignals(False)
        if hasattr(self, "clock_size_spin"):
            self.clock_size_spin.setEnabled(not checked)
        self._update_clock_display()

    def _on_clock_size_changed(self, val: int):
        self.config_mgr.clock_font_size = val
        self._update_clock_display()

    def apply_app_theme(self, theme_key: str):
        """Applies a full application shell theme dynamically to the running Qt application."""
        if theme_key not in APP_THEMES:
            return
        self.config_mgr.apply_app_theme(theme_key)
        app_inst = QApplication.instance()
        if app_inst:
            setup_dark_theme(app_inst, theme_key)

        tokens = APP_THEMES[theme_key]
        if hasattr(self, "_refresh_day_nav_styles"):
            self._refresh_day_nav_styles()
        if hasattr(self, "_update_day_nav_bar"):
            self._update_day_nav_bar(sync_week_with_selection=False)

        # Update dynamic icons to match new theme
        if hasattr(self, "day_nav_prev_btn") and self.day_nav_prev_btn:
            self.day_nav_prev_btn.setIcon(self._create_nav_arrow_icon("left", tokens.get("text_primary")))
        if hasattr(self, "day_nav_next_btn") and self.day_nav_next_btn:
            self.day_nav_next_btn.setIcon(self._create_nav_arrow_icon("right", tokens.get("text_primary")))
        if hasattr(self, "guide_refresh_btn") and self.guide_refresh_btn:
            self.guide_refresh_btn.setIcon(self._create_guide_refresh_icon(tokens.get("text_primary")))
        if hasattr(self, "header_restore_btn") and self.header_restore_btn:
            self.header_restore_btn.setIcon(self._create_restore_window_icon(tokens.get("accent_hover")))
        if hasattr(self, "guide_maximize_btn") and self.guide_maximize_btn:
            if getattr(self, "_guide_maximized", False):
                self.guide_maximize_btn.setIcon(self._create_guide_restore_icon(tokens.get("accent_primary")))
            else:
                self.guide_maximize_btn.setIcon(self._create_guide_maximize_icon(tokens.get("accent_primary")))
        if hasattr(self, "save_theme_preset_btn") and self.save_theme_preset_btn:
            self.save_theme_preset_btn.setIcon(self._create_save_theme_icon(tokens.get("accent_hover")))
        if hasattr(self, "delete_theme_preset_btn") and self.delete_theme_preset_btn:
            self.delete_theme_preset_btn.setIcon(self._create_delete_theme_icon())
        if hasattr(self, "reset_cat_colors_btn") and self.reset_cat_colors_btn:
            self.reset_cat_colors_btn.setIcon(self._create_defaults_theme_icon(tokens.get("accent_primary")))

        self.flash_save_indicator(f"App Theme: {tokens['name']}")

    def _build_app_theme_chips(self):
        if not hasattr(self, "app_theme_grid"):
            return
        while self.app_theme_grid.count():
            item = self.app_theme_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._app_theme_chips.clear()

        if not hasattr(self, "app_theme_combo"):
            self.app_theme_combo = CenteredComboBox()
            self.app_theme_combo.currentIndexChanged.connect(self._on_app_theme_changed)
        self.app_theme_combo.blockSignals(True)
        self.app_theme_combo.clear()

        cur_app_theme = getattr(self.config_mgr, "app_theme", "midnight") if self.config_mgr else "midnight"
        sorted_themes = sorted(APP_THEMES.items(), key=lambda item: item[1]["name"].lower())
        chip_w = get_theme_chip_fixed_width(self.font())

        num_cols = 3
        for idx, (t_key, t_info) in enumerate(sorted_themes):
            self.app_theme_combo.addItem(t_info["name"], t_key)
            accent_dot = t_info.get("accent_primary", "#0284c7")
            chip = ThemeChip(t_key, t_info["name"], accent_dot, parent=self, fixed_width=chip_w)
            chip.chip_clicked.connect(self.select_app_theme)
            self.app_theme_grid.addWidget(chip, idx // num_cols, idx % num_cols, Qt.AlignmentFlag.AlignLeft)
            self._app_theme_chips[t_key] = chip

        a_idx = self.app_theme_combo.findData(cur_app_theme)
        self.app_theme_combo.setCurrentIndex(max(a_idx, 0))
        self.app_theme_combo.blockSignals(False)
        self._sync_app_theme_chips()

    def select_app_theme(self, theme_key: str):
        if not theme_key or theme_key not in APP_THEMES:
            return
        if hasattr(self, "app_theme_combo"):
            self.app_theme_combo.blockSignals(True)
            idx = self.app_theme_combo.findData(theme_key)
            if idx >= 0:
                self.app_theme_combo.setCurrentIndex(idx)
            self.app_theme_combo.blockSignals(False)
        self.apply_app_theme(theme_key)
        self._sync_app_theme_chips()

    def _sync_app_theme_chips(self):
        if not hasattr(self, "_app_theme_chips"):
            return
        cur_theme = getattr(self.config_mgr, "app_theme", "midnight") if self.config_mgr else "midnight"
        for k, chip in self._app_theme_chips.items():
            chip.set_selected(k == cur_theme)

    def _on_app_theme_changed(self, index: int):
        if not hasattr(self, "app_theme_combo"):
            return
        theme_key = self.app_theme_combo.currentData()
        if not theme_key or theme_key not in APP_THEMES:
            return
        self.apply_app_theme(theme_key)
        self._sync_app_theme_chips()

    def _populate_theme_preset_combo(self):
        if not hasattr(self, "theme_preset_combo"):
            self.theme_preset_combo = CenteredComboBox()
            self.theme_preset_combo.currentIndexChanged.connect(self._on_theme_preset_changed)

        if not hasattr(self, "guide_theme_grid"):
            return

        while self.guide_theme_grid.count():
            item = self.guide_theme_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if hasattr(self, "guide_custom_grid"):
            while self.guide_custom_grid.count():
                item = self.guide_custom_grid.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()

        self._guide_theme_chips.clear()
        self.theme_preset_combo.blockSignals(True)
        self.theme_preset_combo.clear()

        cur_preset = getattr(self.config_mgr, "theme_preset", "midnight") if self.config_mgr else "midnight"
        chip_w = 165
        num_cols = 2

        # 1. Built-in presets in guide_theme_grid (alphabetical order by display name)
        built_in_sorted = sorted(THEME_PRESETS.items(), key=lambda x: x[1]["name"].lower())
        for slot_idx, (p_key, p_info) in enumerate(built_in_sorted):
            self.theme_preset_combo.addItem(p_info["name"], p_key)
            dot_color = p_info["colors"].get("sports", "#38bdf8")
            chip = ThemeChip(p_key, p_info["name"], dot_color, parent=self, fixed_width=chip_w)
            chip.chip_clicked.connect(self.select_guide_theme)
            self.guide_theme_grid.addWidget(chip, slot_idx // num_cols, slot_idx % num_cols, Qt.AlignmentFlag.AlignLeft)
            self._guide_theme_chips[p_key] = chip

        # 2. Custom (Manual) pill permanently anchors slot 0 (0, 0)
        target_custom_grid = self.guide_custom_grid if hasattr(self, "guide_custom_grid") else self.guide_theme_grid
        self.theme_preset_combo.addItem("Custom (Manual)", "custom")
        cur_colors = self.config_mgr.category_colors if self.config_mgr else DEFAULT_CATEGORY_COLORS
        custom_dot = cur_colors.get("sports", "#ffa028")
        custom_chip = ThemeChip("custom", "Custom (Manual)", custom_dot, parent=self, fixed_width=chip_w)
        custom_chip.chip_clicked.connect(self.select_guide_theme)
        target_custom_grid.addWidget(custom_chip, 0, 0, Qt.AlignmentFlag.AlignLeft)
        self._guide_theme_chips["custom"] = custom_chip

        # 3. Saved custom presets listed starting at slot 1, preserving Custom anchor at (0, 0)
        custom_presets = self.config_mgr.custom_theme_presets if self.config_mgr else {}
        custom_sorted = sorted(custom_presets.items(), key=lambda x: x[1]["name"].lower())
        c_slot = 1
        for p_key, p_info in custom_sorted:
            self.theme_preset_combo.addItem(p_info["name"], p_key)
            dot_color = p_info["colors"].get("sports", "#38bdf8")
            chip = ThemeChip(p_key, p_info["name"], dot_color, parent=self, fixed_width=chip_w)
            chip.chip_clicked.connect(self.select_guide_theme)
            target_custom_grid.addWidget(chip, c_slot // num_cols, c_slot % num_cols, Qt.AlignmentFlag.AlignLeft)
            self._guide_theme_chips[p_key] = chip
            c_slot += 1

        p_idx = self.theme_preset_combo.findData(cur_preset)
        self.theme_preset_combo.setCurrentIndex(max(p_idx, 0))
        self.theme_preset_combo.blockSignals(False)
        self._sync_guide_theme_chips()

    def select_guide_theme(self, preset_key: str):
        if not preset_key:
            return
        if hasattr(self, "theme_preset_combo"):
            self.theme_preset_combo.blockSignals(True)
            idx = self.theme_preset_combo.findData(preset_key)
            if idx >= 0:
                self.theme_preset_combo.setCurrentIndex(idx)
            self.theme_preset_combo.blockSignals(False)
        if preset_key != "custom":
            self._apply_guide_theme_preset(preset_key)
        else:
            self.config_mgr.theme_preset = "custom"
        self._sync_guide_theme_chips()

    def _sync_guide_theme_chips(self):
        if not hasattr(self, "_guide_theme_chips"):
            return
        cur_preset = getattr(self.config_mgr, "theme_preset", "midnight") if self.config_mgr else "midnight"
        for k, chip in self._guide_theme_chips.items():
            chip.set_selected(k == cur_preset)

        if "custom" in self._guide_theme_chips and self.config_mgr:
            cur_colors = self.config_mgr.category_colors
            self._guide_theme_chips["custom"].set_dot_color(cur_colors.get("sports", "#ffa028"))

        # Enable Delete Theme button only if currently selected preset is a user custom preset
        if hasattr(self, "delete_theme_preset_btn") and self.config_mgr:
            is_custom_saved = cur_preset in self.config_mgr.custom_theme_presets
            self.delete_theme_preset_btn.setEnabled(is_custom_saved)

    def _apply_guide_theme_preset(self, preset_key: str):
        if not preset_key or preset_key == "custom":
            return
        all_presets = self.config_mgr.get_all_theme_presets() if self.config_mgr else dict(THEME_PRESETS)
        if preset_key in all_presets:
            self.config_mgr.apply_theme_preset(preset_key)

            colors = self.config_mgr.category_colors
            if hasattr(self, "_cat_swatches"):
                for cat_key, swatch_btn in self._cat_swatches.items():
                    hex_val = colors.get(cat_key, DEFAULT_CATEGORY_COLORS.get(cat_key, "#ffffff"))
                    swatch_btn.setStyleSheet(f"QPushButton.category-color-tile {{ background-color: {hex_val}; }}")
                    if hasattr(self, "_cat_hex_labels") and cat_key in self._cat_hex_labels:
                        self._cat_hex_labels[cat_key].setText(hex_val.upper())

            if hasattr(self, "grid_tile_delegate") and self.grid_tile_delegate:
                self.grid_tile_delegate.refresh_category_colors()

            self._apply_guide_zoom()
            self._refresh_guide_view(keep_scroll=True)
            if hasattr(self, "guide_grid_table") and self.guide_grid_table.horizontalHeader():
                self.guide_grid_table.horizontalHeader().viewport().update()
            self._update_clock_display()
            active_prog = self._get_active_selected_program()
            if active_prog:
                self._display_program_details(active_prog)

            self.flash_save_indicator(f"Theme Preset: {all_presets[preset_key]['name']}")

    def _on_theme_preset_changed(self, index: int):
        if not hasattr(self, "theme_preset_combo"):
            return
        preset_key = self.theme_preset_combo.currentData()
        if not preset_key or preset_key == "custom":
            return

        all_presets = self.config_mgr.get_all_theme_presets() if self.config_mgr else dict(THEME_PRESETS)
        if preset_key in all_presets:
            self.config_mgr.apply_theme_preset(preset_key)

            colors = self.config_mgr.category_colors
            if hasattr(self, "_cat_swatches"):
                for cat_key, swatch_btn in self._cat_swatches.items():
                    hex_val = colors.get(cat_key, DEFAULT_CATEGORY_COLORS.get(cat_key, "#ffffff"))
                    swatch_btn.setStyleSheet(f"QPushButton.category-color-tile {{ background-color: {hex_val}; }}")
                    if hasattr(self, "_cat_hex_labels") and cat_key in self._cat_hex_labels:
                        self._cat_hex_labels[cat_key].setText(hex_val.upper())

            if hasattr(self, "grid_tile_delegate") and self.grid_tile_delegate:
                self.grid_tile_delegate.refresh_category_colors()

            self._apply_guide_zoom()
            self._refresh_guide_view(keep_scroll=True)
            if hasattr(self, "guide_grid_table") and self.guide_grid_table.horizontalHeader():
                self.guide_grid_table.horizontalHeader().viewport().update()
            self._update_clock_display()
            active_prog = self._get_active_selected_program()
            if active_prog:
                self._display_program_details(active_prog)

            self.flash_save_indicator(f"Theme Preset: {all_presets[preset_key]['name']}")
            self._sync_guide_theme_chips()

    def _save_current_theme_preset(self):
        """Prompt user for a preset name and save the current guide grid category colors."""
        name, ok = QInputDialog.getText(
            self,
            "Save Theme Preset",
            "Enter a name for this custom theme preset:",
            QLineEdit.EchoMode.Normal,
            ""
        )
        if ok and name.strip():
            preset_name = name.strip()
            preset_key = self.config_mgr.save_custom_theme_preset(preset_name)
            self._populate_theme_preset_combo()
            self.select_guide_theme(preset_key)
            self.flash_save_indicator(f"Saved Theme Preset: {preset_name}")

    def _delete_current_theme_preset(self):
        """Delete the currently selected custom theme preset."""
        cur_preset = self.config_mgr.theme_preset
        custom_presets = self.config_mgr.custom_theme_presets
        if cur_preset not in custom_presets:
            return

        preset_name = custom_presets[cur_preset]["name"]
        reply = QMessageBox.question(
            self,
            "Delete Theme Preset",
            f"Are you sure you want to delete the theme preset '{preset_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config_mgr.delete_custom_theme_preset(cur_preset)
            self._populate_theme_preset_combo()
            self.select_guide_theme("midnight")
            self.flash_save_indicator(f"Deleted Theme Preset: {preset_name}")

    def _choose_category_color(self, category_key: str, category_label: str):
        """Open dark-themed QColorDialog to select a custom color for a guide category."""
        cur_hex = self.config_mgr.category_colors.get(
            category_key,
            DEFAULT_CATEGORY_COLORS.get(category_key, "#ffffff")
        )
        initial_color = QColor(cur_hex)
        chosen_color = QColorDialog.getColor(
            initial_color,
            self,
            f"Select Color for {category_label}",
            options=QColorDialog.ColorDialogOption.DontUseNativeDialog
        )
        if chosen_color.isValid():
            new_hex = chosen_color.name()
            self.config_mgr.set_category_color(category_key, new_hex)

            # Mark theme preset as custom
            if hasattr(self, "theme_preset_combo"):
                self.theme_preset_combo.blockSignals(True)
                c_idx = self.theme_preset_combo.findData("custom")
                if c_idx >= 0:
                    self.theme_preset_combo.setCurrentIndex(c_idx)
                self.theme_preset_combo.blockSignals(False)
            self._sync_guide_theme_chips()

            # Update swatch tile
            if hasattr(self, "_cat_swatches") and category_key in self._cat_swatches:
                self._cat_swatches[category_key].setStyleSheet(f"QPushButton.category-color-tile {{ background-color: {new_hex}; }}")
            if hasattr(self, "_cat_hex_labels") and category_key in self._cat_hex_labels:
                self._cat_hex_labels[category_key].setText(new_hex.upper())

            # Invalidate grid tile delegate color cache
            if hasattr(self, "grid_tile_delegate") and self.grid_tile_delegate:
                self.grid_tile_delegate.refresh_category_colors()

            # Refresh views live
            self._apply_guide_zoom()
            self._refresh_guide_view(keep_scroll=True)
            if hasattr(self, "guide_grid_table") and self.guide_grid_table.horizontalHeader():
                self.guide_grid_table.horizontalHeader().viewport().update()
            if category_key == "clock":
                self._update_clock_display()
            active_prog = self._get_active_selected_program()
            if active_prog:
                self._display_program_details(active_prog)
            self.flash_save_indicator(f"{category_label} Color Updated")

    def _reset_category_colors(self):
        """Reset all category colors to default factory values."""
        self.config_mgr.reset_category_colors()

        if hasattr(self, "theme_preset_combo"):
            self.theme_preset_combo.blockSignals(True)
            m_idx = self.theme_preset_combo.findData("midnight")
            if m_idx >= 0:
                self.theme_preset_combo.setCurrentIndex(m_idx)
            self.theme_preset_combo.blockSignals(False)
        self._sync_guide_theme_chips()

        if hasattr(self, "_cat_swatches"):
            for cat_key, swatch in self._cat_swatches.items():
                def_hex = DEFAULT_CATEGORY_COLORS.get(cat_key, "#ffffff")
                swatch.setStyleSheet(f"QPushButton.category-color-tile {{ background-color: {def_hex}; }}")
                if hasattr(self, "_cat_hex_labels") and cat_key in self._cat_hex_labels:
                    self._cat_hex_labels[cat_key].setText(def_hex.upper())

        if hasattr(self, "grid_tile_delegate") and self.grid_tile_delegate:
            self.grid_tile_delegate.refresh_category_colors()

        self._apply_guide_zoom()
        self._refresh_guide_view(keep_scroll=True)
        if hasattr(self, "guide_grid_table") and self.guide_grid_table.horizontalHeader():
            self.guide_grid_table.horizontalHeader().viewport().update()
        self._update_clock_display()
        active_prog = self._get_active_selected_program()
        if active_prog:
            self._display_program_details(active_prog)
        self.flash_save_indicator("Guide Colors Reset to Defaults")

    def browse_custom_recording_folder(self):
        current = self.custom_folder_input.text().strip() or str(self.storage_mgr.get_recording_folder())
        chosen = QFileDialog.getExistingDirectory(self, "Select DVR Recording Folder", current)
        if chosen:
            self.custom_folder_input.setText(chosen)
            self.update_storage_status_ui()

    def update_storage_status_ui(self):
        folder_str = self.custom_folder_input.text().strip() if hasattr(self, "custom_folder_input") else ""
        target_path = Path(folder_str) if folder_str else self.storage_mgr.get_recording_folder()
        usage = self.storage_mgr.get_disk_usage(target_path)
        if hasattr(self, "storage_status_lbl"):
            free_gb = usage["free_gb"]
            total_gb = usage["total_gb"]
            pct = usage["free_percent"]
            folder = usage["folder"]
            color = "#55a84c" if free_gb > 25 else "#e06c75"
            self.storage_status_lbl.setText(
                f"Directory: {folder}\nFree Disk Space: {free_gb} GB / {total_gb} GB ({pct}% free)"
            )
            self.storage_status_lbl.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {color};")

    def run_manual_cleanup(self):
        retention_days = self.retention_days_spin.value()
        min_free = self.min_free_spin.value()
        folder_str = self.custom_folder_input.text().strip()
        folder_path = Path(folder_str) if folder_str else self.storage_mgr.get_recording_folder()
        disk_usage = self.storage_mgr.get_disk_usage(folder_path)

        dlg = RetentionCleanupDialog(
            folder=str(folder_path),
            retention_days=retention_days,
            min_free_gb=min_free,
            disk_usage=disk_usage,
            parent=self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        opts = dlg.get_cleanup_options()
        delete_all = opts.get("delete_all", False)
        include_protected = opts.get("include_protected", False)

        try:
            # Apply current settings to manager first
            self.config_mgr.retention_days = retention_days
            self.config_mgr.min_free_disk_gb = min_free
            self.config_mgr.custom_recording_folder = folder_str

            res = self.storage_mgr.run_cleanup_cycle(
                force=True,
                delete_all=delete_all,
                include_protected=include_protected
            )
            self.update_storage_status_ui()
            self.refresh_recordings()

            cnt = res.get("deleted_count", 0)
            freed = res.get("freed_gb", 0.0)
            target = res.get("folder", "")
            action_name = "Purge All Recordings" if delete_all else "Retention Cleanup"
            if cnt > 0:
                deleted_list = "\n".join(f"• {f}" for f in res.get("deleted_files", []))
                QMessageBox.information(
                    self, f"{action_name} Completed",
                    f"Successfully deleted {cnt} recording(s), reclaiming {freed} GB in:\n{target}\n\nDeleted files:\n{deleted_list}"
                )
            else:
                msg = (
                    f"No recorded video files found to delete in:\n{target}"
                    if delete_all
                    else f"No old recordings met the purge criteria in:\n{target}\n\nFree space remains within configured limits."
                )
                QMessageBox.information(
                    self, action_name,
                    msg
                )
        except Exception as e:
            QMessageBox.critical(
                self, "Retention Cleanup Error",
                f"An error occurred while running retention cleanup:\n{e}"
            )

    def update_service_status_ui(self):
        try:
            res = subprocess.run(
                ["systemctl", "--user", "is-active", "kaffeine-dvr-watcher.service"],
                capture_output=True, text=True, check=False
            )
            active = res.stdout.strip() == "active"
            if hasattr(self, "service_status_lbl"):
                if active:
                    self.service_status_lbl.setText("Status: Active and Running")
                    self.service_status_lbl.setStyleSheet("color: #55a84c; font-weight: bold; font-size: 12px;")
                else:
                    self.service_status_lbl.setText("Status: Inactive / Stopped")
                    self.service_status_lbl.setStyleSheet("color: #e57373; font-weight: bold; font-size: 12px;")
            if hasattr(self, "updates_service_lbl"):
                if active:
                    self.updates_service_lbl.setText("Active and running")
                    self.updates_service_lbl.setStyleSheet("color: #28a745; font-weight: bold;")
                else:
                    self.updates_service_lbl.setText("Inactive / Disabled")
                    self.updates_service_lbl.setStyleSheet("color: #8c98aa;")
        except Exception:
            if hasattr(self, "service_status_lbl"):
                self.service_status_lbl.setText("Status: Unknown")
            if hasattr(self, "updates_service_lbl"):
                self.updates_service_lbl.setText("Unknown")

    def start_background_service(self):
        try:
            ensure_systemd_service(force=True)
            res = subprocess.run(
                ["systemctl", "--user", "enable", "--now", "kaffeine-dvr-watcher.service"],
                capture_output=True, text=True, check=False
            )
            self.update_service_status_ui()
            if res.returncode == 0:
                QMessageBox.information(self, "Service Started", "kaffeine-dvr-watcher.service has been started and enabled.")
            else:
                err = res.stderr.strip() or res.stdout.strip() or f"Exit code {res.returncode}"
                QMessageBox.warning(self, "Service Error", f"Failed to start service:\n{err}")
        except Exception as e:
            QMessageBox.warning(self, "Service Error", f"Failed to start service: {e}")

    def restart_background_service(self):
        try:
            ensure_systemd_service(force=True)
            res = subprocess.run(
                ["systemctl", "--user", "restart", "kaffeine-dvr-watcher.service"],
                capture_output=True, text=True, check=False
            )
            self.update_service_status_ui()
            if res.returncode == 0:
                QMessageBox.information(self, "Service Restarted", "kaffeine-dvr-watcher.service has been restarted.")
            else:
                err = res.stderr.strip() or res.stdout.strip() or f"Exit code {res.returncode}"
                QMessageBox.warning(self, "Service Error", f"Failed to restart service:\n{err}")
        except Exception as e:
            QMessageBox.warning(self, "Service Error", f"Failed to restart service: {e}")

    def open_service_logs_dialog(self):
        dlg = ServiceLogsDialog(self)
        dlg.exec()

    # ------------------ LOGIC & REFRESH ------------------
    def setup_timers(self):
        # Poll active timeshift sessions every 1 second to detect when player exits
        self._timeshift_poll_timer = QTimer(self)
        self._timeshift_poll_timer.setInterval(1000)
        self._timeshift_poll_timer.timeout.connect(self._poll_timeshift_session)

        # Top-corner clock update timer (1 second interval)
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock_display)
        self._clock_timer.start()

        # Real-time guide synchronization every 60 seconds
        self._guide_realtime_timer = QTimer(self)
        self._guide_realtime_timer.setInterval(60000)
        self._guide_realtime_timer.timeout.connect(self._update_guide_realtime)
        self._guide_realtime_timer.start()

    def is_viewing_today(self) -> bool:
        """Returns True if the current guide date selector is viewing today or all upcoming."""
        if not hasattr(self, "guide_date_combo"):
            return True
        sel_date = self.guide_date_combo.currentData()
        today_str = date.today().strftime("%Y-%m-%d")
        return sel_date is None or sel_date == today_str

    def _update_guide_realtime(self):
        """
        Periodic (60s) timer callback to:
        1. Keep tile timing states (past, live, upcoming) synchronized in memory for Grid & List views.
        2. Repaint viewport so the current-time indicator line advances.
        3. Auto-advance the grid / list view at :50 past the hour if enabled.
        """
        now = datetime.now()
        is_today = self.is_viewing_today()

        # At midnight, refresh date dropdown so 'Today' refers to the new date
        today_str = date.today().strftime("%Y-%m-%d")
        combo_today = self.guide_date_combo.itemData(1) if hasattr(self, "guide_date_combo") and self.guide_date_combo.count() > 1 else None
        if combo_today and combo_today != today_str:
            self.refresh_date_dropdown()
            return

        # 1. Update Grid View tiles if populated
        if hasattr(self, "guide_grid_table") and self.guide_grid_table.rowCount() > 0:
            rows = self.guide_grid_table.rowCount()
            cols = self.guide_grid_table.columnCount()
            past_bg = getattr(self.grid_tile_delegate, "color_past_bg", QColor("#161922"))
            past_bg_alt = getattr(self.grid_tile_delegate, "color_past_bg_alt", QColor("#14171f"))
            tile_bg = getattr(self.grid_tile_delegate, "_default_bg", QColor("#222838"))
            tile_bg_alt = getattr(self.grid_tile_delegate, "_default_bg_alt", QColor("#1e2332"))
            live_bg = self.grid_tile_delegate.get_category_color("live_bg") if hasattr(self, "grid_tile_delegate") else QColor("#132400")

            for r in range(rows):
                is_alt = (r % 2 == 1)
                for c in range(cols):
                    item = self.guide_grid_table.item(r, c)
                    if not item:
                        continue
                    p_copy = item.data(Qt.ItemDataRole.UserRole)
                    if not isinstance(p_copy, dict):
                        continue
                    start_dt = p_copy.get("_parsed_start_dt")
                    end_dt = p_copy.get("_parsed_end_dt")
                    if start_dt is None:
                        start_iso = p_copy.get("start_iso")
                        if not start_iso:
                            continue
                        try:
                            start_dt = datetime.fromisoformat(start_iso)
                            dur_iso = p_copy.get("duration_iso") or "00:30:00"
                            parts = [int(x) for x in dur_iso.split(":")]
                            dur = timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2] if len(parts) > 2 else 0)
                            end_dt = start_dt + dur
                            p_copy["_parsed_start_dt"] = start_dt
                            p_copy["_parsed_end_dt"] = end_dt
                        except Exception:
                            continue

                    if not start_dt or not end_dt:
                        continue

                    try:
                        if now >= end_dt:
                            new_timing = "past"
                        elif start_dt <= now < end_dt:
                            new_timing = "live"
                        else:
                            new_timing = "upcoming"

                        old_timing = p_copy.get("_timing_state")
                        if new_timing != old_timing:
                            p_copy["_timing_state"] = new_timing
                            item.setData(Qt.ItemDataRole.UserRole, p_copy)
                            # Theme-aware visual background styling based on timing state
                            if new_timing == "past":
                                cur_bg = past_bg_alt if is_alt else past_bg
                            elif new_timing == "live":
                                cur_bg = live_bg
                            else:
                                cur_bg = tile_bg_alt if is_alt else tile_bg
                            item.setBackground(cur_bg)
                    except Exception:
                        pass

            # Repaint viewport and header so time line and tiles update
            self.guide_grid_table.viewport().update()
            if self.guide_grid_table.horizontalHeader():
                self.guide_grid_table.horizontalHeader().viewport().update()

        # 2. Update List View items if populated
        if hasattr(self, "guide_table") and self.guide_table.rowCount() > 0:
            programs = getattr(self, "current_guide_items", None) or []
            cat_colors = self.config_mgr.category_colors
            active_scheduled = self.queue_mgr.get_active_scheduled_map() if hasattr(self, "queue_mgr") else {}
            history_map = self.queue_mgr.get_history_map(limit=200) if hasattr(self, "queue_mgr") else {}

            for r, p in enumerate(programs):
                if r >= self.guide_table.rowCount():
                    break
                timing_info = self._get_program_timing_state(p, check_files=False)
                timing_state = timing_info.get("state", "upcoming")
                cat = p.get("_category") or classify_guide_category(p)

                # REC column
                ch = (p.get("kaffeine_channel") or "").strip().lower()
                start_iso = (p.get("start_iso") or "")[:16]
                rec_info = active_scheduled.get((ch, start_iso))
                hist_info = history_map.get((ch, start_iso))
                rec_status = rec_info.get("status", "") if isinstance(rec_info, dict) else ""
                is_recording = bool(rec_info) and (rec_status == "RECORDING" or (timing_state == "live" and rec_status in ("ARMED", "RECORDING")))

                rec_item = self.guide_table.item(r, 0)
                if rec_item:
                    if is_recording:
                        rec_item.setText("● REC")
                        rec_item.setForeground(QColor("#ff5252"))
                    elif rec_info:
                        rec_item.setText("○ SCHED")
                        rec_item.setForeground(QColor("#ffa028"))
                    elif hist_info and timing_state == "past":
                        rec_item.setText("● REC")
                        rec_item.setForeground(QColor("#8b0000"))
                    else:
                        rec_item.setText("")

                time_item = self.guide_table.item(r, 1)
                chan_item = self.guide_table.item(r, 2)
                dur_item = self.guide_table.item(r, 3)
                title_item = self.guide_table.item(r, 4)
                sub_item = self.guide_table.item(r, 5)

                if timing_state == "past":
                    gray_color = getattr(self.grid_tile_delegate, "color_past_title", QColor("#788292"))
                    for it in (time_item, chan_item, dur_item, title_item, sub_item):
                        if it:
                            it.setForeground(gray_color)
                            f = it.font()
                            f.setBold(False)
                            it.setFont(f)
                elif timing_state == "live":
                    t_color = QColor(cat_colors.get(cat, DEFAULT_CATEGORY_COLORS.get(cat, "#b9feff")))
                    if title_item:
                        title_item.setForeground(t_color)
                        f = title_item.font()
                        f.setBold(True)
                        title_item.setFont(f)
                    for it in (time_item, chan_item, dur_item, sub_item):
                        if it:
                            it.setForeground(QColor("#e2e8f0"))
                            f = it.font()
                            f.setBold(False)
                            it.setFont(f)
                else:
                    t_color = QColor(cat_colors.get(cat, DEFAULT_CATEGORY_COLORS.get(cat, "#b9feff")))
                    if title_item:
                        title_item.setForeground(t_color)
                        f = title_item.font()
                        f.setBold(False)
                        title_item.setFont(f)
                    for it in (time_item, chan_item, dur_item, sub_item):
                        if it:
                            it.setForeground(QColor("#e2e8f0"))
                            f = it.font()
                            f.setBold(False)
                            it.setFont(f)

        # 3. Auto-Advance at configured minute past the hour (default :50)
        auto_adv = getattr(self.config_mgr, "guide_auto_advance", True)
        adv_min = getattr(self.config_mgr, "guide_auto_advance_minute", 50)
        if auto_adv and is_today and now.minute >= adv_min:
            last_adv = getattr(self, "_last_auto_advanced_hour", None)
            cur_key = (now.year, now.month, now.day, now.hour)
            if last_adv != cur_key:
                # Check user interaction guards:
                is_dragging = getattr(self, "grid_pan_filter", None) and getattr(self.grid_pan_filter, "_dragging", False)
                has_modal = QApplication.activeModalWidget() is not None
                if not is_dragging and not has_modal:
                    if self._is_grid_view_active():
                        # Browsing safeguard: only advance if scroll is near current hour slot
                        col_width = self.guide_grid_table.horizontalHeader().defaultSectionSize()
                        cur_hour_slot = min(47, now.hour * 2)
                        expected_x = self.guide_grid_table.horizontalHeader().sectionPosition(cur_hour_slot)
                        cur_x = self.guide_grid_table.horizontalScrollBar().value()
                        if abs(cur_x - expected_x) <= col_width * 2:
                            self.jump_guide_to_now()
                            self._last_auto_advanced_hour = cur_key
                    else:
                        cur_top_row = self.guide_table.rowAt(0)
                        programs = getattr(self, "current_guide_items", None) or []
                        first_act = -1
                        for r, p in enumerate(programs):
                            tm = self._get_program_timing_state(p, check_files=False)
                            if tm.get("state") in ("live", "upcoming"):
                                first_act = r
                                break
                        if first_act >= 0 and abs(cur_top_row - first_act) <= 5:
                            self._scroll_list_to_first_active()
                            self._last_auto_advanced_hour = cur_key

    def refresh_date_dropdown(self, reset_to_default: bool = False):
        """Refreshes the Date dropdown when a new calendar day begins or on app startup."""
        if not hasattr(self, "guide_date_combo"):
            return
        today = date.today()
        # Item 0 is 'All Upcoming' (data=None), Item 1 is 'Today' (data=today_str)
        today_date_in_combo = self.guide_date_combo.itemData(1) if self.guide_date_combo.count() > 1 else None
        today_str = today.strftime("%Y-%m-%d")
        if not reset_to_default and today_date_in_combo == today_str:
            return  # Date dropdown is already up to date

        cur_data = None if reset_to_default else self.guide_date_combo.currentData()
        self.guide_date_combo.blockSignals(True)
        self.guide_date_combo.clear()
        self.guide_date_combo.addItem("All Upcoming", None)
        for i in range(14):
            d = today + timedelta(days=i)
            label = "Today" if i == 0 else ("Tomorrow" if i == 1 else d.strftime("%a, %b %d"))
            self.guide_date_combo.addItem(label, d.strftime("%Y-%m-%d"))

        if reset_to_default or cur_data is None:
            self.guide_date_combo.setCurrentIndex(1)
        else:
            idx = self.guide_date_combo.findData(cur_data)
            if idx >= 0:
                self.guide_date_combo.setCurrentIndex(idx)
            else:
                self.guide_date_combo.setCurrentIndex(1)
        self.guide_date_combo.blockSignals(False)
        self.filter_guide()

    def refresh_channel_dropdowns(self, reset_to_default: bool = False):
        channels = self.config_mgr.get_ordered_channels()
        if hasattr(self, "guide_channel_combo"):
            cur_selected = "All" if reset_to_default else self.guide_channel_combo.currentText()
            self.guide_channel_combo.blockSignals(True)
            self.guide_channel_combo.clear()
            self.guide_channel_combo.addItem("All")
            self.guide_channel_combo.addItems(channels)
            idx = 0 if reset_to_default else self.guide_channel_combo.findText(cur_selected)
            if idx >= 0:
                self.guide_channel_combo.setCurrentIndex(idx)
            else:
                self.guide_channel_combo.setCurrentIndex(0)
            self.guide_channel_combo.blockSignals(False)

    def refresh_all(self, on_startup: bool = False):
        self.refresh_date_dropdown(reset_to_default=on_startup)
        self.update_status_badges()
        self.update_service_status_ui()
        self.update_storage_status_ui()
        self.refresh_channel_dropdowns(reset_to_default=on_startup)
        self.refresh_recordings()
        self.filter_guide()
        self.refresh_rules()

    def update_status_badges(self):
        guide_status = self.guide_service.get_guide_status()
        last_updated = guide_status.get("last_updated")
        if last_updated:
            relative_str = "Recently"
            try:
                # Try parsing format: "YYYY-MM-DD hh:mm:ss AM/PM" or ISO
                for fmt in ("%Y-%m-%d %I:%M:%S %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        up_dt = datetime.strptime(last_updated.strip(), fmt)
                        diff = datetime.now() - up_dt
                        total_mins = int(diff.total_seconds() // 60)
                        if total_mins < 1:
                            relative_str = "Just now"
                        elif total_mins == 1:
                            relative_str = "1 min ago"
                        elif total_mins < 60:
                            relative_str = f"{total_mins} mins ago"
                        else:
                            hours = total_mins // 60
                            if hours == 1:
                                relative_str = "1 hour ago"
                            elif hours < 24:
                                relative_str = f"{hours} hours ago"
                            else:
                                days = hours // 24
                                relative_str = f"{days} day{'s' if days > 1 else ''} ago"
                        break
                    except ValueError:
                        continue
            except Exception:
                relative_str = last_updated

            self.guide_status_lbl.setText(f"Guide Updated: {relative_str}")
            friendly_updated = format_american_datetime(last_updated) or last_updated
            self.guide_status_lbl.setToolTip(f"Last sync completed: {friendly_updated}")
        else:
            self.guide_status_lbl.setText("Guide: Not Synced")

    def launch_kaffeine(self):
        self.status_bar.showMessage("Launching Kaffeine...", 3000)
        self.dbus_client.launch_kaffeine(mode=self.config_mgr.launch_mode)
        QTimer.singleShot(2000, self.update_status_badges)

    def sync_guide(self):
        self.sync_guide_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.sync_progress_lbl.setText("Syncing guide data...")
        self.sync_progress_lbl.setVisible(True)

        self.sync_worker = SyncWorker(self.guide_service, self.config_mgr.guide_days_ahead)
        self.sync_worker.progress.connect(self._on_sync_progress_msg)
        self.sync_worker.progress_val.connect(self._on_sync_progress_val)
        self.sync_worker.finished.connect(self.on_sync_finished)
        self.sync_worker.finished.connect(self.sync_worker.deleteLater)
        self.sync_worker.start()

    def _on_sync_progress_msg(self, msg: str):
        self.sync_progress_lbl.setText(msg)

    def _on_sync_progress_val(self, val: int):
        self.progress_bar.setValue(max(self.progress_bar.value(), val))

    def on_sync_finished(self, count: int, error: str):
        self.progress_bar.setValue(100)
        self.sync_guide_btn.setEnabled(True)
        QTimer.singleShot(600, lambda: self.progress_bar.setVisible(False))
        if error:
            self.sync_progress_lbl.setText("Sync failed.")
            QTimer.singleShot(4000, lambda: self.sync_progress_lbl.setVisible(False))
            QMessageBox.critical(self, "Guide Sync Error", f"Failed to sync guide: {error}")
        else:
            self.sync_progress_lbl.setText(f"Complete ({count} shows cached)")
            QTimer.singleShot(4000, lambda: self.sync_progress_lbl.setVisible(False))
            self.refresh_date_dropdown()
            self.update_status_badges()
            self.refresh_channel_dropdowns()
            self.filter_guide()
            self.run_rules(silent=True)
            self.test_all_sources_health(silent=True)
            import gc
            gc.collect()

    def refresh_recordings(self):
        # Update queue statuses (archives finished recordings to history)
        self.queue_mgr.update_statuses([], max_history=self.config_mgr.max_history_entries)

        # Active Schedule only shows QUEUED, ARMED, RECORDING
        queue = self.queue_mgr.list_queue(include_completed=False)
        self.rec_table.setRowCount(len(queue))
        today = date.today()

        for row, rec in enumerate(queue):
            qid = rec.get("id")
            title = rec.get("title", "")
            channel = rec.get("channel", "")
            duration = rec.get("duration_iso", "")
            status = rec.get("status", "QUEUED")
            start_iso = rec.get("start_iso", "")

            # Schedule text (e.g. Sat @ 1700 or Next Thu (Oct 15) @ 1700)
            schedule_text = ""
            full_date_text = rec.get("start_time_local", "")
            try:
                dt = datetime.fromisoformat(start_iso)
                full_date_text = dt.strftime("%A, %B %d, %Y at %I:%M %p")
                diff_days = (dt.date() - today).days
                time_24 = dt.strftime("%H%M")
                if diff_days == 0:
                    schedule_text = f"Today @ {time_24}"
                elif diff_days == 1:
                    schedule_text = f"Tomorrow @ {time_24}"
                elif 2 <= diff_days < 7:
                    schedule_text = f"{dt.strftime('%a')} @ {time_24}"
                elif 7 <= diff_days < 14:
                    schedule_text = f"Next {dt.strftime('%a')} ({dt.strftime('%b %d')}) @ {time_24}"
                elif diff_days >= 14:
                    schedule_text = f"{dt.strftime('%a, %b %d')} @ {time_24}"
                elif diff_days == -1:
                    schedule_text = f"Yesterday @ {time_24}"
                else:
                    schedule_text = f"Past ({dt.strftime('%b %d')}) @ {time_24}"
            except Exception:
                schedule_text = full_date_text

            title_item = QTableWidgetItem(title)
            title_item.setData(Qt.ItemDataRole.UserRole, qid)

            sched_item = QTableWidgetItem(schedule_text)
            sched_item.setFont(QFont("", -1, QFont.Weight.Bold))

            self.rec_table.setItem(row, 0, title_item)
            self.rec_table.setItem(row, 1, sched_item)
            self.rec_table.setItem(row, 2, QTableWidgetItem(channel))

            buf_val = rec.get("buffer_mins", 0) or 0
            if buf_val > 0:
                duration_display = f"{duration} (+{buf_val}m)"
            else:
                duration_display = duration
            dur_item = QTableWidgetItem(duration_display)
            self.rec_table.setItem(row, 3, dur_item)

            status_display = status
            color = "#007bff"
            if status == "QUEUED":
                lead = self.config_mgr.lead_time_mins
                status_display = f"Queued (Arms {lead}m before show)"
                color = "#17a2b8"
            elif status == "ARMED":
                status_display = "Armed in Kaffeine"
                color = "#fd7e14"
            elif status == "RECORDING":
                status_display = "Recording Now"
                color = "#ff5252"
            elif status == "COMPLETED":
                status_display = "Completed"
                color = "#6c757d"
            elif status == "PURGED":
                status_display = "Purged (Auto-Deleted)"
                color = "#8c98aa"

            status_item = QTableWidgetItem(status_display)
            status_item.setForeground(QColor(color))
            self.rec_table.setItem(row, 4, status_item)

            is_prot = bool(rec.get("protected", 0))
            prot_item = QTableWidgetItem("Protected" if is_prot else "Auto")
            prot_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_prot:
                prot_item.setForeground(QColor("#28a745"))
                prot_item.setFont(QFont("", -1, QFont.Weight.Bold))
            else:
                prot_item.setForeground(QColor("#a0aec0"))
            self.rec_table.setItem(row, 5, prot_item)

        # Also refresh history table
        self.refresh_history()

    # ------------------ RECORDING HISTORY UI ------------------

    def refresh_history(self):
        """Populates the History table with recorded broadcast history."""
        if not hasattr(self, "history_table"):
            return
        hist = self.queue_mgr.list_history()
        self.history_table.setRowCount(len(hist))

        for row, item in enumerate(hist):
            hid = item.get("id")
            title = item.get("title", "")
            channel = item.get("channel", "")
            duration = item.get("duration_iso", "")
            start_iso = item.get("start_iso", "")
            start_local = item.get("start_time_local", "")

            # Format Date / Time nicely
            date_time_str = start_local
            try:
                dt = datetime.fromisoformat(start_iso)
                date_time_str = dt.strftime("%A, %b %d, %Y @ %I:%M %p")
            except Exception:
                pass

            title_item = QTableWidgetItem(title)
            title_item.setData(Qt.ItemDataRole.UserRole, hid)

            dt_item = QTableWidgetItem(date_time_str)

            chan_item = QTableWidgetItem(channel)
            dur_item = QTableWidgetItem(duration)

            self.history_table.setItem(row, 0, title_item)
            self.history_table.setItem(row, 1, dt_item)
            self.history_table.setItem(row, 2, chan_item)
            self.history_table.setItem(row, 3, dur_item)

        self._adjust_table_columns()

    def on_max_history_changed(self, val: int):
        self.config_mgr.max_history_entries = val
        self.queue_mgr.prune_history(val)
        self.refresh_history()

    def clear_selected_history_entry(self):
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Selection Required", "Please select a history entry to clear.")
            return

        hid = self.history_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        title = self.history_table.item(row, 0).text()
        if hid:
            self.queue_mgr.delete_history_entry(int(hid))
            self.status_bar.showMessage(f"Removed '{title}' from history.", 3000)
            self.refresh_history()

    def clear_all_history(self):
        count = self.history_table.rowCount()
        if count == 0:
            return
        confirm = QMessageBox.question(
            self, "Clear History",
            f"Are you sure you want to clear all {count} history entries?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.queue_mgr.clear_all_history()
            self.status_bar.showMessage("Recording history cleared.", 3000)
            self.refresh_history()

    def _on_rec_table_double_clicked(self, item):
        col = item.column()
        if col == 3:  # Duration column
            self.adjust_selected_buffer()
        elif col == 5:  # Retain / Protect column
            self.toggle_protect_selected_recording()

    def adjust_selected_buffer(self):
        row = self.rec_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Selection Required", "Please select a recording to adjust its buffer.")
            return

        qid = self.rec_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        rec_title = self.rec_table.item(row, 0).text()

        all_recs = self.queue_mgr.list_queue(include_completed=True)
        rec = next((r for r in all_recs if r.get("id") == int(qid)), None)
        if not rec:
            return
        if rec.get("status") != "QUEUED":
            QMessageBox.information(
                self, "Cannot Adjust Buffer",
                f"Recording '{rec_title}' is currently {rec.get('status')}. Only QUEUED recordings can have their buffer adjusted."
            )
            return

        current_buf = rec.get("buffer_mins", 0) or 0
        dlg = AdjustBufferDialog(rec_title, current_buffer=current_buf, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_buf = dlg.get_buffer()
            if self.queue_mgr.update_recording_buffer(int(qid), new_buf):
                self.status_bar.showMessage(f"Updated buffer for '{rec_title}' to +{new_buf}m.", 4000)
                self.refresh_recordings()
                self._refresh_guide_view(keep_scroll=True)
            else:
                QMessageBox.warning(self, "Update Failed", "Could not update recording buffer.")

    def toggle_protect_selected_recording(self):
        row = self.rec_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Selection Required", "Please select a recording to toggle protection.")
            return

        qid = self.rec_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        rec_title = self.rec_table.item(row, 0).text()
        new_state = self.queue_mgr.toggle_protected(int(qid))
        state_str = "Protected (Keep Forever)" if new_state else "Standard (Auto-cleanup eligible)"
        self.status_bar.showMessage(f"'{rec_title}' is now {state_str}.", 4000)
        self.refresh_recordings()

    def cancel_selected_recording(self):
        row = self.rec_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Selection Required", "Please select a recording to cancel.")
            return

        qid = self.rec_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        rec_title = self.rec_table.item(row, 0).text()
        rec_info = self.queue_mgr.remove_recording(int(qid))
        if rec_info:
            self.dbus_client.cancel_recording(
                key=rec_info.get("kaffeine_key"),
                channel=rec_info.get("channel"),
                title=rec_info.get("title")
            )
        else:
            self.dbus_client.cancel_recording(title=rec_title)
        self.status_bar.showMessage(f"Cancelled recording '{rec_title}'.", 3000)
        self.refresh_recordings()
        self._refresh_guide_view(keep_scroll=True)

    def add_manual_recording(self):
        channels = self.config_mgr.get_ordered_channels()
        dlg = ManualRecordDialog(channels, self, default_buffer_mins=self.config_mgr.end_buffer_mins)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            title = dlg.title_input.text().strip()
            ch = dlg.channel_combo.currentText()
            start = dlg.start_input.text().strip()
            dur = dlg.duration_input.text().strip()
            buf = dlg.buffer_spin.value()
            if not title or not start or not dur:
                QMessageBox.warning(self, "Invalid Input", "Please fill in all fields.")
                return
            try:
                lead = self.config_mgr.lead_time_mins
                qid = self.queue_mgr.add_recording(title, ch, start, dur, lead_time_mins=lead, buffer_mins=buf)
                armed = self.watcher.check_and_dispatch(notify=False)
                buf_msg = f" (+{buf}m buffer)" if buf > 0 else ""
                if armed > 0:
                    self.status_bar.showMessage(f"Armed recording '{title}'{buf_msg} in Kaffeine (Queue #{qid})", 4000)
                else:
                    self.status_bar.showMessage(f"Queued recording '{title}'{buf_msg} (Queue #{qid})", 4000)
                self.refresh_recordings()
            except Exception as e:
                QMessageBox.critical(self, "Scheduling Error", str(e))

    def _on_main_tab_changed(self, index: int):
        if index == 0:
            self.refresh_date_dropdown()
            sel_date = self.guide_date_combo.currentData()
            today_str = date.today().strftime("%Y-%m-%d")
            if sel_date == today_str or sel_date is None:
                QTimer.singleShot(60, self.jump_guide_to_now)
            else:
                QTimer.singleShot(60, self.jump_guide_to_noon)
        elif index == 1:
            self._adjust_table_columns()

    def _update_time_jump_buttons_visibility(self):
        # Keep Jump to Now and Prime Time buttons visible in both Grid and List views
        if hasattr(self, "jump_now_btn"):
            self.jump_now_btn.setVisible(True)
        if hasattr(self, "jump_prime_btn"):
            self.jump_prime_btn.setVisible(True)

    def _on_guide_view_toggled(self):
        if self.grid_view_btn.isChecked():
            self.guide_stack.setCurrentIndex(0)
            self.settings.setValue("guide_view_mode", "grid")
        else:
            self.guide_stack.setCurrentIndex(1)
            self.settings.setValue("guide_view_mode", "list")
        self._update_time_jump_buttons_visibility()
        self._update_zoom_buttons_state()
        self.filter_guide()
        if not self.grid_view_btn.isChecked():
            QTimer.singleShot(0, self._scroll_list_to_first_active)

    def _scroll_grid_to_slot(self, slot: int, center: bool = False):
        bar = self.guide_grid_table.horizontalScrollBar()
        col_width = self.guide_grid_table.horizontalHeader().defaultSectionSize() or 200
        is_pixel = (self.guide_grid_table.horizontalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel)

        if not center or slot <= 0:
            target_val = (slot * col_width) if is_pixel else slot
            bar.setValue(max(0, min(bar.maximum(), target_val)))
            return

        vp_width = self.guide_grid_table.viewport().width()
        cols_visible = max(1, vp_width // col_width)
        target_col = max(0, slot - (cols_visible // 2))
        target_val = (target_col * col_width) if is_pixel else target_col
        bar.setValue(max(0, min(bar.maximum(), target_val)))

    def jump_guide_to_now(self):
        # If currently viewing a future or past date, switch back to Today first
        if hasattr(self, "guide_date_combo"):
            today_str = date.today().strftime("%Y-%m-%d")
            cur_date = self.guide_date_combo.currentData()
            if cur_date is not None and cur_date != today_str:
                today_idx = self.guide_date_combo.findData(today_str)
                if today_idx >= 0:
                    self.guide_date_combo.setCurrentIndex(today_idx)
                    return

        if self._is_grid_view_active():
            now = datetime.now()
            # Align the left edge of the grid to the current hour (e.g. 10:00 AM at 10:15).
            # Advance to the next hour when reaching the configured minute past the hour (default :50).
            adv_min = getattr(self.config_mgr, "guide_auto_advance_minute", 50) if hasattr(self, "config_mgr") else 50
            effective_hour = (now.hour + 1) if now.minute >= adv_min else now.hour
            target_slot = min(47, effective_hour * 2)
            self._scroll_grid_to_slot(target_slot, center=False)
        else:
            self._scroll_list_to_first_active()

    def jump_guide_to_start(self):
        self._scroll_grid_to_slot(0, center=False)

    def jump_guide_to_noon(self):
        # 12:00 PM (Noon) is hour 12 -> slot 24
        self._scroll_grid_to_slot(24, center=False)

    def jump_guide_to_0400(self):
        # 4:00 AM (0400) is hour 4 -> slot 8
        self._scroll_grid_to_slot(8, center=False)

    def jump_guide_to_primetime(self):
        if self._is_grid_view_active():
            # 7:00 PM (19:00) is hour 19 -> slot 38
            self._scroll_grid_to_slot(38, center=False)
        else:
            self._scroll_list_to_primetime()

    def advance_guide_date(self, offset: int = 1, position: str = "0400"):
        """Advances or rewinds the guide date by offset days and positions the scrollbar."""
        if not hasattr(self, "guide_date_combo"):
            return
        combo = self.guide_date_combo
        cur_idx = combo.currentIndex()
        target_idx = cur_idx + offset
        if 1 <= target_idx < combo.count():
            self._target_grid_scroll_position = position
            combo.setCurrentIndex(target_idx)

    def _on_grid_horizontal_scroll(self, val: int):
        """Updates day nav bar highlight when user scrolls past midnight into late night."""
        if not hasattr(self, "guide_grid_table") or self.guide_stack.currentIndex() != 0:
            return
        col_w = self.guide_grid_table.horizontalHeader().defaultSectionSize() or 200
        # Column 48 is midnight (+1 day)
        is_past_midnight = (val >= 48 * col_w - 50)
        if getattr(self, "_is_viewing_late_night_overhang", False) != is_past_midnight:
            self._is_viewing_late_night_overhang = is_past_midnight
            self._update_day_nav_bar(sync_week_with_selection=False)

    def _scroll_list_to_primetime(self):
        """Scroll list guide table to the first show at or after 7:00 PM (19:00)."""
        if self.guide_stack.currentIndex() != 1:
            return
        programs = getattr(self, "current_guide_items", None) or []
        today_str = datetime.now().strftime("%Y-%m-%d")
        prime_row = -1

        for r, p in enumerate(programs):
            start_iso = p.get("start_iso", "")
            # Check for today's prime time (>= 19:00)
            if start_iso.startswith(today_str) and len(start_iso) >= 16:
                time_part = start_iso[11:16]
                if time_part >= "19:00":
                    prime_row = r
                    break
            elif start_iso > f"{today_str}T19:00":
                prime_row = r
                break

        if prime_row < 0:
            # Fallback to any show at or after 19:00
            for r, p in enumerate(programs):
                start_iso = p.get("start_iso", "")
                if len(start_iso) >= 16 and start_iso[11:16] >= "19:00":
                    prime_row = r
                    break

        if prime_row >= 0 and prime_row < self.guide_table.rowCount():
            target_item = self.guide_table.item(prime_row, 1) or self.guide_table.item(prime_row, 0)
            if target_item:
                self.guide_table.scrollToItem(target_item, QTableWidget.ScrollHint.PositionAtTop)

    def _is_grid_view_active(self) -> bool:
        return hasattr(self, "guide_stack") and self.guide_stack.currentIndex() == 0

    def _update_zoom_buttons_state(self):
        """Update zoom button tooltips and enabled states according to active view (grid vs list)."""
        is_grid = self._is_grid_view_active()
        if is_grid:
            grid_lvl = getattr(self, "guide_grid_zoom_level", 0)
            target_rows = max(1, min(16, 8 - grid_lvl))
            can_zoom_in = target_rows > 1
            can_zoom_out = target_rows < 16
            tooltip_in = "Increase grid font and tile size"
            tooltip_out = "Decrease grid font and tile size"
        else:
            list_lvl = getattr(self, "guide_list_zoom_level", 0)
            can_zoom_in = list_lvl < 42
            can_zoom_out = list_lvl > -3
            tooltip_in = "Increase list view font size"
            tooltip_out = "Decrease list view font size"

        if hasattr(self, "zoom_in_btn"):
            self.zoom_in_btn.setEnabled(can_zoom_in)
            self.zoom_in_btn.setToolTip(tooltip_in)
        if hasattr(self, "zoom_out_btn"):
            self.zoom_out_btn.setEnabled(can_zoom_out)
            self.zoom_out_btn.setToolTip(tooltip_out)

    def zoom_in_guide(self):
        """Increase font and box size independently for the currently active view."""
        if self._is_grid_view_active():
            if not hasattr(self, "guide_grid_zoom_level"):
                self.guide_grid_zoom_level = 0
            target_rows = max(1, min(16, 8 - self.guide_grid_zoom_level))
            if target_rows > 1:
                self.guide_grid_zoom_level += 1
                self.settings.setValue("guide_grid_zoom_level", self.guide_grid_zoom_level)
                self._apply_guide_zoom()
        else:
            if not hasattr(self, "guide_list_zoom_level"):
                self.guide_list_zoom_level = 0
            if self.guide_list_zoom_level < 42:
                self.guide_list_zoom_level += 1
                self.settings.setValue("guide_list_zoom_level", self.guide_list_zoom_level)
                self._apply_guide_zoom()
        self._update_zoom_buttons_state()

    def zoom_out_guide(self):
        """Decrease font and box size independently for the currently active view."""
        if self._is_grid_view_active():
            if not hasattr(self, "guide_grid_zoom_level"):
                self.guide_grid_zoom_level = 0
            target_rows = max(1, min(16, 8 - self.guide_grid_zoom_level))
            if target_rows < 16:
                self.guide_grid_zoom_level -= 1
                self.settings.setValue("guide_grid_zoom_level", self.guide_grid_zoom_level)
                self._apply_guide_zoom()
        else:
            if not hasattr(self, "guide_list_zoom_level"):
                self.guide_list_zoom_level = 0
            if self.guide_list_zoom_level > -3:
                self.guide_list_zoom_level -= 1
                self.settings.setValue("guide_list_zoom_level", self.guide_list_zoom_level)
                self._apply_guide_zoom()
        self._update_zoom_buttons_state()

    def _apply_guide_zoom(self):
        """Apply the current guide zoom level to Grid and List views with intelligent bottom alignment."""
        grid_lvl = getattr(self, "guide_grid_zoom_level", getattr(self, "guide_zoom_level", 0))
        list_lvl = getattr(self, "guide_list_zoom_level", getattr(self, "guide_zoom_level", 0))

        # 1. Grid View intelligent sizing
        if hasattr(self, "guide_grid_table"):
            # Target number of rows visible in the viewport:
            # Baseline is user-configured grid_visible_rows (range: 4–16, default: 9).
            # Zoom in (lvl > 0) shows fewer rows (down to 1 row) with large tiles and text.
            # Zoom out (lvl < 0) shows more rows (up to 20) with compact tiles.
            base_rows = getattr(self.config_mgr, "grid_visible_rows", 9)
            target_rows = max(1, min(20, base_rows - grid_lvl))

            vp = self.guide_grid_table.viewport()
            vh = vp.height() if vp else 0

            total_rows = self.guide_grid_table.rowCount()
            # If all channels fit within target_rows, reserve a 4px safety margin so rounding
            # or header border differences never trigger a ghost 2-4px scrollbar.
            safety_margin = 4 if (total_rows > 0 and total_rows <= target_rows) else 0

            if vh < 100:
                base_row_h = max(58, 62 + (grid_lvl * 12))
                rem = 0
            else:
                eff_vh = max(16, vh - safety_margin)
                calc_h = eff_vh // target_rows
                if calc_h < 58:
                    base_row_h = 58
                    rem = 0
                else:
                    base_row_h = calc_h
                    rem = eff_vh % target_rows

            for r in range(total_rows):
                extra = 1 if (r % target_rows) < rem else 0
                self.guide_grid_table.setRowHeight(r, base_row_h + extra)

            self.guide_grid_table.verticalHeader().setDefaultSectionSize(base_row_h)
            self.guide_grid_table.verticalScrollBar().setSingleStep(base_row_h)

            # Preserve current visible time slot across column width recalculations
            h_bar = self.guide_grid_table.horizontalScrollBar()
            old_col_w = self.guide_grid_table.horizontalHeader().defaultSectionSize() or 205
            saved_slot = (h_bar.value() / old_col_w) if (h_bar and old_col_w > 0) else 0

            # 30-minute block width: comfortable baseline (205px) scaled by grid zoom level
            col_w = max(180, min(320, 205 + (grid_lvl * 15)))
            self.guide_grid_table.horizontalHeader().setDefaultSectionSize(col_w)

            # Restore exact time slot so window resize or maximize never jumps to start of day
            if saved_slot > 0 and h_bar:
                new_h_val = int(saved_slot * col_w)
                h_bar.setValue(max(0, min(h_bar.maximum(), new_h_val)))

            zoom_delta = int((base_row_h - 62) / 8)
            if hasattr(self, "grid_tile_delegate"):
                self.grid_tile_delegate.set_zoom_delta(zoom_delta)

            hdr_font_sz = max(11, min(38, 14 + zoom_delta))
            v_hdr_font_sz = max(10, min(36, 12 + zoom_delta))
            cur_hdr_sizes = getattr(self, "_cur_hdr_sizes", None)
            if cur_hdr_sizes != (hdr_font_sz, v_hdr_font_sz):
                self._cur_hdr_sizes = (hdr_font_sz, v_hdr_font_sz)
                self.guide_grid_table.setStyleSheet(
                    f"QTableWidget#guideGridTable QHeaderView::section:horizontal {{ font-size: {hdr_font_sz}px; color: #e2e8f0; }} "
                    f"QTableWidget#guideGridTable QHeaderView::section:vertical {{ font-size: {v_hdr_font_sz}px; }}"
                )
            self.guide_grid_table.viewport().update()

        # 2. List View sizing
        if hasattr(self, "guide_table"):
            list_font_sz = max(9, 12 + list_lvl)
            list_row_h = max(22, list_font_sz + 14)
            self.guide_table.verticalHeader().setDefaultSectionSize(list_row_h)
            hl_hex = self.config_mgr.category_colors.get("highlight", "#38bdf8")
            hl_color = QColor(hl_hex)
            sel_bg = f"rgba({hl_color.red()}, {hl_color.green()}, {hl_color.blue()}, 0.35)"
            list_hdr_sz = max(9, min(16, list_font_sz - 1))
            self.guide_table.setStyleSheet(
                f"QTableWidget#guideListTable {{ font-size: {list_font_sz}px; gridline-color: #2b3242; }} "
                f"QTableWidget#guideListTable QHeaderView::section {{ font-size: {list_hdr_sz}px; }} "
                f"QTableWidget#guideListTable::item:selected {{ background-color: {sel_bg}; }}"
            )
            self.guide_table.viewport().update()

        self._update_zoom_buttons_state()

    def toggle_guide_maximized(self):
        self._guide_maximized = not getattr(self, "_guide_maximized", False)
        is_max = self._guide_maximized
        if hasattr(self, "config_mgr") and hasattr(self.config_mgr, "guide_maximized"):
            self.config_mgr.guide_maximized = is_max

        if hasattr(self, "tabs"):
            self.tabs.tabBar().setVisible(not is_max)

        if hasattr(self, "guide_detail_widget"):
            self.guide_detail_widget.setVisible(not is_max)

        if hasattr(self, "status_bar"):
            self.status_bar.setVisible(not is_max)

        cur_theme = getattr(self.config_mgr, "app_theme", "midnight") if hasattr(self, "config_mgr") and self.config_mgr else "midnight"
        theme_tokens = APP_THEMES.get(cur_theme, APP_THEMES["midnight"])
        accent = theme_tokens.get("accent_primary")

        if hasattr(self, "guide_maximize_btn"):
            if is_max:
                self.guide_maximize_btn.setToolTip("Restore standard view (Esc)")
                self.guide_maximize_btn.setIcon(self._create_guide_restore_icon(accent))
            else:
                self.guide_maximize_btn.setToolTip("Maximize guide to fill window")
                self.guide_maximize_btn.setIcon(self._create_guide_maximize_icon(accent))

        QTimer.singleShot(30, self._apply_guide_zoom)

    @staticmethod
    def _create_guide_maximize_icon(color: Optional[str] = None) -> QIcon:
        """
        Emerald green 4-corner outward expansion brackets icon (fullscreen metaphor).
        Maximizes canvas coverage (22x22) to fill the button box nicely.
        """
        icon = QIcon()
        norm_color = color or "#66bb6a"
        for mode, c in [(QIcon.Mode.Normal, norm_color), (QIcon.Mode.Disabled, "#3b5c3d")]:
            pix = QPixmap(22, 22)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(c), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin)
            p.setPen(pen)

            # Top-Left corner outward bracket
            p.drawLine(QPointF(2.5, 8.0), QPointF(2.5, 2.5))
            p.drawLine(QPointF(2.5, 2.5), QPointF(8.0, 2.5))

            # Top-Right corner outward bracket
            p.drawLine(QPointF(14.0, 2.5), QPointF(19.5, 2.5))
            p.drawLine(QPointF(19.5, 2.5), QPointF(19.5, 8.0))

            # Bottom-Left corner outward bracket
            p.drawLine(QPointF(2.5, 14.0), QPointF(2.5, 19.5))
            p.drawLine(QPointF(2.5, 19.5), QPointF(8.0, 19.5))

            # Bottom-Right corner outward bracket
            p.drawLine(QPointF(14.0, 19.5), QPointF(19.5, 19.5))
            p.drawLine(QPointF(19.5, 19.5), QPointF(19.5, 14.0))

            p.end()
            icon.addPixmap(pix, mode)
        return icon

    @staticmethod
    def _create_guide_restore_icon(color: Optional[str] = None) -> QIcon:
        """
        Emerald green 4-corner inward contraction brackets icon (exit fullscreen metaphor).
        Maximizes canvas coverage (22x22) to fill the button box nicely.
        """
        icon = QIcon()
        norm_color = color or "#66bb6a"
        for mode, c in [(QIcon.Mode.Normal, norm_color), (QIcon.Mode.Disabled, "#3b5c3d")]:
            pix = QPixmap(22, 22)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(c), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin)
            p.setPen(pen)

            # Top-Left corner pointing toward center
            p.drawLine(QPointF(8.0, 2.5), QPointF(8.0, 8.0))
            p.drawLine(QPointF(8.0, 8.0), QPointF(2.5, 8.0))

            # Top-Right corner pointing toward center
            p.drawLine(QPointF(14.0, 2.5), QPointF(14.0, 8.0))
            p.drawLine(QPointF(14.0, 8.0), QPointF(19.5, 8.0))

            # Bottom-Left corner pointing toward center
            p.drawLine(QPointF(2.5, 14.0), QPointF(8.0, 14.0))
            p.drawLine(QPointF(8.0, 14.0), QPointF(8.0, 19.5))

            # Bottom-Right corner pointing toward center
            p.drawLine(QPointF(19.5, 14.0), QPointF(14.0, 14.0))
            p.drawLine(QPointF(14.0, 14.0), QPointF(14.0, 19.5))

            p.end()
            icon.addPixmap(pix, mode)
        return icon

    @staticmethod
    def _create_guide_refresh_icon(color: Optional[str] = None) -> QIcon:
        """
        Crisp circular refresh arrow icon (22x22).
        """
        icon = QIcon()
        norm_color = color or "#c8d2df"
        for mode, c in [(QIcon.Mode.Normal, norm_color), (QIcon.Mode.Disabled, "#414b5d")]:
            pix = QPixmap(22, 22)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            arc_pen = QPen(QColor(c), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(arc_pen)
            # Circular arc centered in 22x22 box
            arc_rect = QRectF(3.5, 3.5, 15.0, 15.0)
            # Span from 45 degrees for 280 degrees clockwise
            p.drawArc(arc_rect, 45 * 16, 280 * 16)

            # Arrow head pointing clockwise at top-right
            arrow_pen = QPen(QColor(c), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin)
            p.setPen(arrow_pen)
            p.drawLine(QPointF(14.0, 2.0), QPointF(17.5, 5.5))
            p.drawLine(QPointF(13.0, 6.5), QPointF(17.5, 5.5))

            p.end()
            icon.addPixmap(pix, mode)
        return icon

    @staticmethod
    def _create_save_theme_icon(color: Optional[str] = None) -> QIcon:
        """Crisp floppy disk / save preset icon (20x20)."""
        icon = QIcon()
        norm_color = color or "#60a5fa"
        for mode, c in [(QIcon.Mode.Normal, norm_color), (QIcon.Mode.Disabled, "#475569")]:
            pix = QPixmap(20, 20)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(c), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)

            poly = QPolygonF([
                QPointF(3.5, 3.5),
                QPointF(13.5, 3.5),
                QPointF(16.5, 6.5),
                QPointF(16.5, 16.5),
                QPointF(3.5, 16.5),
            ])
            p.drawPolygon(poly)
            p.drawRect(QRectF(6.5, 3.5, 6.0, 4.5))
            p.drawRect(QRectF(5.5, 11.5, 9.0, 5.0))

            p.end()
            icon.addPixmap(pix, mode)
        return icon

    @staticmethod
    def _create_delete_theme_icon(color: Optional[str] = None) -> QIcon:
        """Crisp trash can / delete preset icon (20x20)."""
        icon = QIcon()
        norm_color = color or "#f87171"
        for mode, c in [(QIcon.Mode.Normal, norm_color), (QIcon.Mode.Disabled, "#475569")]:
            pix = QPixmap(20, 20)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(c), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)

            p.drawLine(QPointF(8.0, 3.5), QPointF(12.0, 3.5))
            p.drawLine(QPointF(4.0, 5.5), QPointF(16.0, 5.5))

            body = QPolygonF([
                QPointF(5.5, 6.5),
                QPointF(6.5, 16.5),
                QPointF(13.5, 16.5),
                QPointF(14.5, 6.5),
            ])
            p.drawPolygon(body)

            p.drawLine(QPointF(8.5, 8.5), QPointF(8.5, 14.5))
            p.drawLine(QPointF(11.5, 8.5), QPointF(11.5, 14.5))

            p.end()
            icon.addPixmap(pix, mode)
        return icon

    @staticmethod
    def _create_defaults_theme_icon(color: Optional[str] = None) -> QIcon:
        """Crisp circular reset / defaults arrow icon (20x20)."""
        icon = QIcon()
        norm_color = color or "#34d399"
        for mode, c in [(QIcon.Mode.Normal, norm_color), (QIcon.Mode.Disabled, "#475569")]:
            pix = QPixmap(20, 20)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            arc_pen = QPen(QColor(c), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(arc_pen)
            arc_rect = QRectF(3.5, 3.5, 13.0, 13.0)
            p.drawArc(arc_rect, 45 * 16, 275 * 16)

            arrow_pen = QPen(QColor(c), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin)
            p.setPen(arrow_pen)
            p.drawLine(QPointF(9.5, 1.5), QPointF(14.5, 3.5))
            p.drawLine(QPointF(13.5, 7.5), QPointF(14.5, 3.5))

            p.end()
            icon.addPixmap(pix, mode)
        return icon

    @staticmethod
    def _create_restore_window_icon(color: Optional[str] = None) -> QIcon:
        """
        Sky cyan window contour with counter-clockwise reset / restore arrow.
        Maximizes canvas coverage (22x22) to fill the button box nicely.
        """
        icon = QIcon()
        norm_color = color or "#4fc3f7"
        for mode, c in [(QIcon.Mode.Normal, norm_color), (QIcon.Mode.Disabled, "#2d4857")]:
            pix = QPixmap(22, 22)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Outer subtle window frame in upper portion
            frame_pen = QPen(QColor(c), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(frame_pen)
            # Window top border and top-right corner
            p.drawLine(QPointF(3.0, 2.5), QPointF(19.0, 2.5))
            p.drawLine(QPointF(19.0, 2.5), QPointF(19.0, 16.0))
            p.drawLine(QPointF(19.0, 16.0), QPointF(16.0, 16.0))
            p.drawLine(QPointF(3.0, 2.5), QPointF(3.0, 7.5))

            # Reset circular arc (counter-clockwise)
            arc_pen = QPen(QColor(c), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(arc_pen)
            # Arc bounding box centered in bottom-left
            arc_rect = QRectF(2.0, 6.0, 14.0, 14.0)
            # Start at 40 degrees, span 270 degrees
            p.drawArc(arc_rect, 40 * 16, 270 * 16)

            # Reset Arrow head at start of arc (top-right of the circle)
            arrow_pen = QPen(QColor(c), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin)
            p.setPen(arrow_pen)
            p.drawLine(QPointF(11.0, 4.0), QPointF(13.0, 8.5))
            p.drawLine(QPointF(8.0, 8.5), QPointF(13.0, 8.5))

            p.end()
            icon.addPixmap(pix, mode)
        return icon

    @staticmethod
    def _create_nav_arrow_icon(direction: str = "left", color: Optional[str] = None) -> QIcon:
        icon = QIcon()
        norm_color = color or "#c5d1de"
        # Create crisp pixmaps for Normal and Disabled states
        states = [
            (QIcon.Mode.Normal, norm_color),
            (QIcon.Mode.Disabled, "#414b5d"),
        ]
        for mode, c in states:
            pix = QPixmap(24, 24)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(c)))
            if direction == "left":
                pts = [QPoint(15, 6), QPoint(7, 12), QPoint(15, 18)]
            else:
                pts = [QPoint(9, 6), QPoint(17, 12), QPoint(9, 18)]
            p.drawPolygon(QPolygon(pts))
            p.end()
            icon.addPixmap(pix, mode)
        return icon

    def _create_day_nav_bar(self) -> QWidget:
        container = QWidget()
        container.setObjectName("dayNavBar")
        nav_layout = QHBoxLayout(container)
        nav_layout.setContentsMargins(0, 4, 0, 2)
        nav_layout.setSpacing(6)

        self.day_nav_prev_btn = QPushButton()
        self.day_nav_prev_btn.setObjectName("dayNavPrevBtn")
        self.day_nav_prev_btn.setIcon(self._create_nav_arrow_icon("left"))
        self.day_nav_prev_btn.setIconSize(QSize(20, 20))
        self.day_nav_prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.day_nav_prev_btn.setFixedWidth(36)
        self.day_nav_prev_btn.setFixedHeight(44)
        self.day_nav_prev_btn.clicked.connect(self._on_day_nav_prev)
        nav_layout.addWidget(self.day_nav_prev_btn)

        self._refresh_day_nav_styles()

        self.day_nav_buttons = []
        for i in range(7):
            btn = QPushButton()
            btn.setFixedHeight(44)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(self._make_day_nav_handler(btn))
            nav_layout.addWidget(btn, 1)
            self.day_nav_buttons.append(btn)

        self.day_nav_next_btn = QPushButton()
        self.day_nav_next_btn.setObjectName("dayNavNextBtn")
        self.day_nav_next_btn.setIcon(self._create_nav_arrow_icon("right"))
        self.day_nav_next_btn.setIconSize(QSize(20, 20))
        self.day_nav_next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.day_nav_next_btn.setFixedWidth(36)
        self.day_nav_next_btn.setFixedHeight(44)
        self.day_nav_next_btn.clicked.connect(self._on_day_nav_next)
        nav_layout.addWidget(self.day_nav_next_btn)

        return container

    def _refresh_day_nav_styles(self):
        """Builds dynamically themed button styles for day navigation buttons."""
        app_theme = getattr(self.config_mgr, "app_theme", "midnight") if self.config_mgr else "midnight"
        tokens = APP_THEMES.get(app_theme, APP_THEMES["midnight"])

        bg_btn = tokens.get("bg_button", "#1e2330")
        bg_btn_hover = tokens.get("bg_button_hover", "#262e3f")
        bg_btn_pressed = tokens.get("bg_button_pressed", "#161a24")
        border = tokens.get("border_color", "#303746")
        border_light = tokens.get("border_light", "#455470")
        text_pri = tokens.get("text_primary", "#dce1e8")
        text_sec = tokens.get("text_secondary", "#a4b0c2")
        accent = tokens.get("accent_primary", "#2d6cd4")
        accent_hover = tokens.get("accent_hover", "#3b7ee8")
        accent_pressed = tokens.get("accent_pressed", "#2259b3")

        # Standard upcoming unselected day
        self._day_style_unselected = (
            f"QPushButton {{ padding: 4px 2px; font-size: 13px; font-weight: 500; line-height: 1.2; "
            f"border: 1px solid {border}; border-radius: 4px; background-color: {bg_btn}; color: {text_sec}; }} "
            f"QPushButton:hover {{ background-color: {bg_btn_hover}; border: 1px solid {border_light}; color: {text_pri}; }} "
            f"QPushButton:pressed {{ background-color: {bg_btn_pressed}; }}"
        )

        # Theme-specific color palettes for the current day ("Today")
        # Unselected: subtle tint background, theme border, theme-accent text
        # Selected: rich theme fill, bright accent border, high-contrast text
        today_palettes = {
            "midnight": {
                "unsel_bg": "#16233b",
                "unsel_border": "#254b8c",
                "unsel_text": "#60a5fa",
                "unsel_hover_bg": "#1c2d4a",
                "unsel_hover_border": "#3b82f6",
                "unsel_hover_text": "#93c5fd",
                "unsel_pressed_bg": "#121d30",
                "sel_bg": "#1d3d73",
                "sel_border": "#3b82f6",
                "sel_text": "#ffffff",
                "sel_hover_bg": "#254d8f",
                "sel_hover_border": "#60a5fa",
                "sel_pressed_bg": "#16305a",
            },
            "oled_black": {
                "unsel_bg": "#071a0e",
                "unsel_border": "#15803d",
                "unsel_text": "#4ade80",
                "unsel_hover_bg": "#0d2616",
                "unsel_hover_border": "#22c55e",
                "unsel_hover_text": "#86efac",
                "unsel_pressed_bg": "#041008",
                "sel_bg": "#14532d",
                "sel_border": "#22c55e",
                "sel_text": "#ffffff",
                "sel_hover_bg": "#166534",
                "sel_hover_border": "#4ade80",
                "sel_pressed_bg": "#0f3d21",
            },
            "nordic_frost": {
                "unsel_bg": "#0d2338",
                "unsel_border": "#0369a1",
                "unsel_text": "#38bdf8",
                "unsel_hover_bg": "#132d47",
                "unsel_hover_border": "#0ea5e9",
                "unsel_hover_text": "#7dd3fc",
                "unsel_pressed_bg": "#0a1a2b",
                "sel_bg": "#075985",
                "sel_border": "#0ea5e9",
                "sel_text": "#ffffff",
                "sel_hover_bg": "#0369a1",
                "sel_hover_border": "#38bdf8",
                "sel_pressed_bg": "#0c4a6e",
            },
            "charcoal": {
                "unsel_bg": "#1b1c36",
                "unsel_border": "#4338ca",
                "unsel_text": "#818cf8",
                "unsel_hover_bg": "#232545",
                "unsel_hover_border": "#6366f1",
                "unsel_hover_text": "#a5b4fc",
                "unsel_pressed_bg": "#15162b",
                "sel_bg": "#3730a3",
                "sel_border": "#6366f1",
                "sel_text": "#ffffff",
                "sel_hover_bg": "#4338ca",
                "sel_hover_border": "#818cf8",
                "sel_pressed_bg": "#312e81",
            },
            "cyberpunk": {
                "unsel_bg": "#052230",
                "unsel_border": "#0891b2",
                "unsel_text": "#22d3ee",
                "unsel_hover_bg": "#092d3f",
                "unsel_hover_border": "#00f0ff",
                "unsel_hover_text": "#67e8f9",
                "unsel_pressed_bg": "#031721",
                "sel_bg": "#0e7490",
                "sel_border": "#00f0ff",
                "sel_text": "#ffffff",
                "sel_hover_bg": "#155e75",
                "sel_hover_border": "#38f5ff",
                "sel_pressed_bg": "#083344",
            },
            "warm_sunset": {
                "unsel_bg": "#2e1b10",
                "unsel_border": "#92400e",
                "unsel_text": "#fbbf24",
                "unsel_hover_bg": "#3d2415",
                "unsel_hover_border": "#f59e0b",
                "unsel_hover_text": "#fcd34d",
                "unsel_pressed_bg": "#20120a",
                "sel_bg": "#78350f",
                "sel_border": "#f59e0b",
                "sel_text": "#ffffff",
                "sel_hover_bg": "#92400e",
                "sel_hover_border": "#fbbf24",
                "sel_pressed_bg": "#451a03",
            },
            "synthwave": {
                "unsel_bg": "#2e0f2b",
                "unsel_border": "#86198f",
                "unsel_text": "#f472b6",
                "unsel_hover_bg": "#3d153a",
                "unsel_hover_border": "#e024c3",
                "unsel_hover_text": "#f9a8d4",
                "unsel_pressed_bg": "#20091e",
                "sel_bg": "#701a75",
                "sel_border": "#e024c3",
                "sel_text": "#ffffff",
                "sel_hover_bg": "#86198f",
                "sel_hover_border": "#f472b6",
                "sel_pressed_bg": "#4a044e",
            },
        }

        p = today_palettes.get(app_theme)
        if not p:
            p = {
                "unsel_bg": bg_btn,
                "unsel_border": border_light,
                "unsel_text": accent,
                "unsel_hover_bg": bg_btn_hover,
                "unsel_hover_border": accent,
                "unsel_hover_text": accent_hover,
                "unsel_pressed_bg": bg_btn_pressed,
                "sel_bg": accent_pressed,
                "sel_border": accent,
                "sel_text": "#ffffff",
                "sel_hover_bg": accent,
                "sel_hover_border": accent_hover,
                "sel_pressed_bg": bg_btn_pressed,
            }

        # Today's day (when NOT currently selected) - themed tint & border
        self._day_style_today_unselected = (
            f"QPushButton {{ padding: 4px 2px; font-size: 13px; font-weight: 600; line-height: 1.2; "
            f"border: 1px solid {p['unsel_border']}; border-radius: 4px; background-color: {p['unsel_bg']}; color: {p['unsel_text']}; }} "
            f"QPushButton:hover {{ background-color: {p['unsel_hover_bg']}; border: 1px solid {p['unsel_hover_border']}; color: {p['unsel_hover_text']}; }} "
            f"QPushButton:pressed {{ background-color: {p['unsel_pressed_bg']}; }}"
        )

        # Today's day (when ALSO currently selected) - rich theme fill with bright accent border
        self._day_style_today_selected = (
            f"QPushButton {{ padding: 4px 2px; font-size: 13px; font-weight: 600; line-height: 1.2; "
            f"border: 1.5px solid {p['sel_border']}; border-radius: 4px; background-color: {p['sel_bg']}; color: {p['sel_text']}; }} "
            f"QPushButton:hover {{ background-color: {p['sel_hover_bg']}; border: 1.5px solid {p['sel_hover_border']}; color: {p['sel_text']}; }} "
            f"QPushButton:pressed {{ background-color: {p['sel_pressed_bg']}; }}"
        )

        # Selected day (when it is NOT Today) - themed accent styling
        self._day_style_selected = (
            f"QPushButton {{ padding: 4px 2px; font-size: 13px; font-weight: 600; line-height: 1.2; "
            f"border: 1.5px solid {accent}; border-radius: 4px; background-color: {accent_pressed}; color: #ffffff; }} "
            f"QPushButton:hover {{ background-color: {accent_hover}; border: 1.5px solid {accent_hover}; color: #ffffff; }} "
            f"QPushButton:pressed {{ background-color: {bg_btn_pressed}; }}"
        )

    def _make_day_nav_handler(self, btn: QPushButton):
        def handler():
            date_str = btn.property("date_str")
            if date_str:
                self._on_day_nav_clicked(date_str)
        return handler

    def _on_day_nav_clicked(self, target_date_str: str):
        if not hasattr(self, "guide_date_combo"):
            return
        self._skip_day_nav_sync = True
        idx = self.guide_date_combo.findData(target_date_str)
        if idx >= 0:
            self.guide_date_combo.setCurrentIndex(idx)
        else:
            self._skip_day_nav_sync = False
            self.filter_guide()

    def _on_day_nav_prev(self):
        new_offset = max(0, getattr(self, "day_nav_offset", 0) - 7)
        if new_offset == getattr(self, "day_nav_offset", 0):
            return
        self.day_nav_offset = new_offset
        self._update_day_nav_bar(sync_week_with_selection=False)

        current_sel = self.guide_date_combo.currentData() if hasattr(self, "guide_date_combo") else None
        target_btn = None
        if current_sel:
            try:
                curr_dt = datetime.strptime(current_sel, "%Y-%m-%d").date()
                target_date_str = (curr_dt - timedelta(days=7)).strftime("%Y-%m-%d")
                for btn in self.day_nav_buttons:
                    if btn.property("date_str") == target_date_str:
                        target_btn = btn
                        break
            except Exception:
                pass

        if not target_btn and new_offset == 0:
            today_str = date.today().strftime("%Y-%m-%d")
            for btn in self.day_nav_buttons:
                if btn.property("date_str") == today_str:
                    target_btn = btn
                    break

        if not target_btn and self.day_nav_buttons:
            target_btn = self.day_nav_buttons[0]
        if target_btn and target_btn.property("date_str"):
            self._on_day_nav_clicked(target_btn.property("date_str"))

    def _on_day_nav_next(self):
        new_offset = min(7, getattr(self, "day_nav_offset", 0) + 7)
        if new_offset == getattr(self, "day_nav_offset", 0):
            return
        self.day_nav_offset = new_offset
        self._update_day_nav_bar(sync_week_with_selection=False)

        current_sel = self.guide_date_combo.currentData() if hasattr(self, "guide_date_combo") else None
        target_btn = None
        if current_sel:
            try:
                curr_dt = datetime.strptime(current_sel, "%Y-%m-%d").date()
                target_date_str = (curr_dt + timedelta(days=7)).strftime("%Y-%m-%d")
                for btn in self.day_nav_buttons:
                    if btn.property("date_str") == target_date_str:
                        target_btn = btn
                        break
            except Exception:
                pass

        if not target_btn and self.day_nav_buttons:
            target_btn = self.day_nav_buttons[0]
        if target_btn and target_btn.property("date_str"):
            self._on_day_nav_clicked(target_btn.property("date_str"))

    def _update_day_nav_bar(self, sync_week_with_selection: bool = False):
        if not hasattr(self, "day_nav_buttons") or not self.day_nav_buttons:
            return

        selected_date_str = self.guide_date_combo.currentData() if hasattr(self, "guide_date_combo") else None
        today = date.today()
        today_str = today.strftime("%Y-%m-%d")
        today_idx = (today.weekday() + 1) % 7

        if not hasattr(self, "day_nav_offset"):
            self.day_nav_offset = 0

        # If sync_week_with_selection is requested (e.g. when selected from dropdown),
        # adjust offset to display the week containing the selected date.
        if sync_week_with_selection and selected_date_str:
            try:
                sel_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
                sel_weekday_idx = (sel_date.weekday() + 1) % 7
                nominal_days = (sel_weekday_idx - today_idx) % 7
                actual_days = (sel_date - today).days
                if actual_days >= nominal_days + 7:
                    self.day_nav_offset = 7
                else:
                    self.day_nav_offset = 0
            except Exception:
                pass

        for i, btn in enumerate(self.day_nav_buttons):
            days_ahead = (i - today_idx) % 7 + self.day_nav_offset
            btn_date = today + timedelta(days=days_ahead)
            btn_date_str = btn_date.strftime("%Y-%m-%d")

            day_name = btn_date.strftime("%A")
            short_date = btn_date.strftime("%b ") + str(btn_date.day)
            btn.setText(f"{day_name}\n{short_date}")
            btn.setProperty("date_str", btn_date_str)

            is_today = (btn_date_str == today_str)
            is_selected = (btn_date_str == selected_date_str)

            if is_today and is_selected:
                if getattr(self, "_is_viewing_late_night_overhang", False):
                    overhang_color = self.config_mgr.category_colors.get("time_indicator", "#06b6d4") if self.config_mgr else "#06b6d4"
                    btn.setStyleSheet(self._day_style_today_selected + f" border: 1.5px solid {overhang_color};")
                    btn.setToolTip("Viewing late-night broadcasts (midnight to 4:00 AM)")
                else:
                    btn.setStyleSheet(self._day_style_today_selected)
                    btn.setToolTip("")
            elif is_today:
                btn.setStyleSheet(self._day_style_today_unselected)
                btn.setToolTip("")
            elif is_selected:
                if getattr(self, "_is_viewing_late_night_overhang", False):
                    overhang_color = self.config_mgr.category_colors.get("time_indicator", "#06b6d4") if self.config_mgr else "#06b6d4"
                    btn.setStyleSheet(self._day_style_selected + f" border: 1.5px solid {overhang_color};")
                    btn.setToolTip("Viewing late-night broadcasts (midnight to 4:00 AM)")
                else:
                    btn.setStyleSheet(self._day_style_selected)
                    btn.setToolTip("")
            else:
                btn.setStyleSheet(self._day_style_unselected)
                btn.setToolTip("")

        if hasattr(self, "day_nav_prev_btn"):
            self.day_nav_prev_btn.setEnabled(self.day_nav_offset > 0)
        if hasattr(self, "day_nav_next_btn"):
            self.day_nav_next_btn.setEnabled(self.day_nav_offset < 7)

    def filter_guide(self):
        # Automatically prune already elapsed past entries from SQLite database
        try:
            self.guide_service.prune_past_programs()
        except Exception:
            pass

        query = self.guide_search_input.text().strip()
        channel = self.guide_channel_combo.currentText()
        airdate = self.guide_date_combo.currentData()
        
        # When viewing the grid for a specific date or today, don't trim earlier shows of that day.
        # In list mode with All Upcoming, trim ended programs.
        is_grid = (self.guide_stack.currentIndex() == 0)
        trim_ended = (not is_grid and airdate is None)
        programs = self.guide_service.search_programs(
            query=query, channel=channel, airdate=airdate, trim_ended=trim_ended, include_overhang=is_grid
        )

        self.current_guide_items = programs

        if self.guide_stack.currentIndex() == 0:
            self._populate_grid_guide(programs, airdate)
        else:
            self._populate_list_guide(programs)

        sync_week = not getattr(self, "_skip_day_nav_sync", False)
        self._skip_day_nav_sync = False
        self._update_day_nav_bar(sync_week_with_selection=sync_week)

    def _populate_list_guide(self, programs: List[Dict[str, Any]]):
        active_scheduled = self.queue_mgr.get_active_scheduled_map()
        history_map = self.queue_mgr.get_history_map(limit=200)
        self.guide_table.setUpdatesEnabled(False)
        self.guide_table.blockSignals(True)
        try:
            self.guide_table.setRowCount(len(programs))
            for row, p in enumerate(programs):
                ch = (p.get("kaffeine_channel") or "").strip().lower()
                start_iso = (p.get("start_iso") or "")[:16]
                rec_info = active_scheduled.get((ch, start_iso))
                hist_info = history_map.get((ch, start_iso))

                timing_info = self._get_program_timing_state(p, check_files=False)
                timing_state = timing_info.get("state", "upcoming")
                cat = p.get("_category") or classify_guide_category(p)

                rec_status = rec_info.get("status", "") if isinstance(rec_info, dict) else ""
                is_recording = bool(rec_info) and (rec_status == "RECORDING" or (timing_state == "live" and rec_status in ("ARMED", "RECORDING")))

                if is_recording:
                    rec_text = "● REC"
                elif rec_info:
                    rec_text = "○ SCHED"
                elif hist_info and timing_state == "past":
                    rec_text = "● REC"
                else:
                    rec_text = ""

                rec_item = QTableWidgetItem(rec_text)
                rec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if is_recording:
                    rec_item.setForeground(QColor("#ff5252"))
                    tip_prefix = "Recording Now"
                    buf_val = rec_info.get("buffer_mins", 0) if rec_info else 0
                    buf_tip = f" | +{buf_val}m buffer" if buf_val else ""
                    rec_item.setToolTip(f"{tip_prefix} (Queue #{rec_info.get('id')} - {rec_info.get('status')}{buf_tip})")
                    rec_item.setFont(QFont("", -1, QFont.Weight.Bold))
                elif rec_info:
                    rec_item.setForeground(QColor("#ffa028"))
                    tip_prefix = "Recording Scheduled"
                    buf_val = rec_info.get("buffer_mins", 0)
                    buf_tip = f" | +{buf_val}m buffer" if buf_val else ""
                    rec_item.setToolTip(f"{tip_prefix} (Queue #{rec_info.get('id')} - {rec_info.get('status')}{buf_tip})")
                    rec_item.setFont(QFont("", -1, QFont.Weight.Bold))
                elif hist_info and timing_state == "past":
                    rec_item.setForeground(QColor("#8b0000"))
                    rec_item.setToolTip(f"Recorded Program (Completed at {hist_info.get('completed_at', '')})")
                    rec_item.setFont(QFont("", -1, QFont.Weight.Bold))
                self.guide_table.setItem(row, 0, rec_item)

                raw_start = p.get("start_time_local", "")
                friendly_time = format_american_datetime_short(raw_start) or raw_start
                time_item = QTableWidgetItem(friendly_time)
                chan_item = QTableWidgetItem(p.get("kaffeine_channel", ""))

                disp_title, disp_sub = get_program_display_titles(p)
                title_item = QTableWidgetItem(disp_title)
                sub_item = QTableWidgetItem(disp_sub)
                dur_item = QTableWidgetItem(p.get("duration_iso", ""))

                # Option 1 coloring for list view:
                cat_colors = self.config_mgr.category_colors
                if timing_state == "past":
                    gray_color = getattr(self.grid_tile_delegate, "color_past_title", QColor("#788292"))
                    time_item.setForeground(gray_color)
                    chan_item.setForeground(gray_color)
                    title_item.setForeground(gray_color)
                    sub_item.setForeground(gray_color)
                    dur_item.setForeground(gray_color)
                elif timing_state == "live":
                    t_color = QColor(cat_colors.get(cat, DEFAULT_CATEGORY_COLORS.get(cat, "#b9feff")))
                    title_item.setForeground(t_color)
                    title_font = QFont()
                    title_font.setBold(True)
                    title_item.setFont(title_font)
                else:
                    t_color = QColor(cat_colors.get(cat, DEFAULT_CATEGORY_COLORS.get(cat, "#b9feff")))
                    title_item.setForeground(t_color)

                self.guide_table.setItem(row, 1, time_item)
                self.guide_table.setItem(row, 2, chan_item)
                self.guide_table.setItem(row, 3, dur_item)
                self.guide_table.setItem(row, 4, title_item)
                self.guide_table.setItem(row, 5, sub_item)

            if not self.settings.contains("guide_table_header_state"):
                for col in [0, 1, 2, 3]:
                    self.guide_table.resizeColumnToContents(col)

            # Auto-scroll to first currently playing or upcoming show
            QTimer.singleShot(0, self._scroll_list_to_first_active)
        finally:
            self.guide_table.blockSignals(False)
            self.guide_table.setUpdatesEnabled(True)

    def _save_guide_table_header_state(self, *args):
        """Persists the user's custom column widths and section positions."""
        if hasattr(self, "guide_table") and hasattr(self, "settings"):
            self.settings.setValue("guide_table_header_state", self.guide_table.horizontalHeader().saveState())

    def _scroll_list_to_first_active(self):
        """Scroll list guide table to the first live or upcoming show."""
        if self.guide_stack.currentIndex() != 1:
            return
        programs = getattr(self, "current_guide_items", None) or []
        first_active_row = -1
        for r, p in enumerate(programs):
            timing = self._get_program_timing_state(p, check_files=False)
            if timing.get("state") in ("live", "upcoming"):
                first_active_row = r
                break
        if first_active_row >= 0 and first_active_row < self.guide_table.rowCount():
            target_item = self.guide_table.item(first_active_row, 1) or self.guide_table.item(first_active_row, 0)
            if target_item:
                self.guide_table.scrollToItem(target_item, QTableWidget.ScrollHint.PositionAtTop)

    def _populate_grid_guide(self, programs: List[Dict[str, Any]], airdate: Optional[str], keep_scroll: bool = False):
        saved_h = self.guide_grid_table.horizontalScrollBar().value() if keep_scroll else 0
        saved_v = self.guide_grid_table.verticalScrollBar().value() if keep_scroll else 0
        active_scheduled = self.queue_mgr.get_active_scheduled_map()
        history_map = self.queue_mgr.get_history_map(limit=200)

        # Clear existing spans and items
        self.guide_grid_table.clearSpans()
        self.guide_grid_table.clearContents()

        # Determine channels to display
        filter_ch = self.guide_channel_combo.currentText()
        if filter_ch and filter_ch != "All":
            channels = [filter_ch]
        else:
            channels = list(self.config_mgr.get_ordered_channels())
            # Also include any channel present in programs that wasn't in config
            for p in programs:
                ch_name = p.get("kaffeine_channel")
                if ch_name and ch_name not in channels:
                    channels.append(ch_name)

        self.grid_channels = channels
        self.guide_grid_table.setRowCount(len(channels))
        self.guide_grid_table.setVerticalHeaderLabels(channels)

        today = date.today()
        target_date_str = airdate or today.strftime("%Y-%m-%d")

        # Configure columns and headers for extended 28-hour grid (56 columns including 4h late night)
        total_cols = 56
        if self.guide_grid_table.columnCount() != total_cols:
            self.guide_grid_table.setColumnCount(total_cols)
        base_dt = datetime.combine(datetime.strptime(target_date_str, "%Y-%m-%d").date(), datetime.min.time())
        next_dt = base_dt + timedelta(days=1)
        next_day_abbr = next_dt.strftime("%a")

        grid_headers = []
        for h in range(24):
            for m in (0, 30):
                grid_headers.append(f"{h%12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}")
        for h in range(4):
            for m in (0, 30):
                if h == 0 and m == 0:
                    grid_headers.append(f"12:00 AM ({next_day_abbr})")
                else:
                    grid_headers.append(f"{h%12 or 12}:{m:02d} AM")
        self.guide_grid_table.setHorizontalHeaderLabels(grid_headers)

        cut_dt = base_dt + timedelta(hours=28)

        # Color palette for tiles
        tile_bg = getattr(self.grid_tile_delegate, "_default_bg", QColor("#222838"))
        tile_bg_alt = getattr(self.grid_tile_delegate, "_default_bg_alt", QColor("#1e2332"))
        tile_text_color = QColor("#ffffff")

        for row_idx, ch in enumerate(channels):
            # Filter specifically to selected airdate and next-day late-night overhang
            ch_progs = []
            for p in programs:
                if p.get("kaffeine_channel") != ch:
                    continue
                start_iso = p.get("start_iso")
                if not start_iso:
                    continue
                try:
                    p_dt = datetime.fromisoformat(start_iso)
                    if base_dt <= p_dt < cut_dt:
                        ch_progs.append(p)
                except Exception:
                    continue
            ch_progs.sort(key=lambda x: x.get("start_iso", ""))

            current_col = 0
            for idx, p in enumerate(ch_progs):
                start_iso = p.get("start_iso")
                if not start_iso:
                    continue
                try:
                    dt = datetime.fromisoformat(start_iso)
                except Exception:
                    continue

                dur_iso = p.get("duration_iso") or "00:30:00"
                try:
                    parts = [int(x) for x in dur_iso.split(":")]
                    dur = timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2] if len(parts) > 2 else 0)
                except Exception:
                    dur = timedelta(minutes=30)
                end_dt = dt + dur

                start_col = int((dt - base_dt).total_seconds() // 1800)
                start_col = max(start_col, current_col)
                if start_col >= total_cols:
                    break

                # Determine nominal end slot
                if idx + 1 < len(ch_progs):
                    try:
                        next_dt = datetime.fromisoformat(ch_progs[idx + 1].get("start_iso", ""))
                        next_start_col = int((next_dt - base_dt).total_seconds() // 1800)
                    except Exception:
                        next_start_col = total_cols
                    nominal_end_col = int((end_dt - base_dt).total_seconds() + 1799) // 1800
                    end_col = max(start_col + 1, min(next_start_col, nominal_end_col))
                else:
                    nominal_end_col = int((end_dt - base_dt).total_seconds() + 1799) // 1800
                    end_col = max(start_col + 1, min(total_cols, nominal_end_col))

                span = max(1, end_col - start_col)

                # Format time range and categorize
                show_title = p.get("show_title", "")
                start_fmt = dt.strftime("%I:%M %p").lstrip("0")
                end_fmt = end_dt.strftime("%I:%M %p").lstrip("0")
                time_range = f"{start_fmt} - {end_fmt}"

                # Match active recording or past completed recording
                ch_key = (ch or "").strip().lower()
                iso_key = (start_iso or "")[:16]
                scheduled_rec = active_scheduled.get((ch_key, iso_key))
                history_rec = history_map.get((ch_key, iso_key))

                # Determine timing state (past, live, upcoming)
                now = datetime.now()
                if now >= end_dt:
                    timing_state = "past"
                elif dt <= now < end_dt:
                    timing_state = "live"
                else:
                    timing_state = "upcoming"

                # Annotate program metadata for delegate renderer
                p_copy = dict(p)
                p_copy["_time_range"] = time_range
                p_copy["_category"] = classify_guide_category(p)
                p_copy["_scheduled_rec"] = scheduled_rec
                p_copy["_history_rec"] = history_rec
                p_copy["_timing_state"] = timing_state
                p_title, p_sub = get_program_display_titles(p)
                p_copy["_primary_title"] = p_title
                p_copy["_secondary_sub"] = p_sub
                p_copy["_start_col"] = start_col
                p_copy["_span"] = span

                item = QTableWidgetItem(show_title)
                item.setData(Qt.ItemDataRole.UserRole, p_copy)
                
                # Visual styling based on timing state
                if timing_state == "past":
                    cur_bg = QColor("#161922") if (idx % 2 == 0) else QColor("#14171f")
                elif timing_state == "live":
                    cur_bg = QColor("#17261c")
                else:
                    cur_bg = tile_bg_alt if (row_idx % 2 == 1) else tile_bg
                item.setBackground(cur_bg)
                item.setForeground(tile_text_color)

                self.guide_grid_table.setItem(row_idx, start_col, item)

                # For spanned columns, fill with ghost items referencing program data so clicking anywhere works
                for c in range(start_col + 1, start_col + span):
                    ghost = QTableWidgetItem()
                    ghost.setData(Qt.ItemDataRole.UserRole, p_copy)
                    ghost.setBackground(cur_bg)
                    self.guide_grid_table.setItem(row_idx, c, ghost)

                if span > 1:
                    self.guide_grid_table.setSpan(row_idx, start_col, 1, span)

                current_col = start_col + span

        # Ensure all populated rows fit intelligently flush at the bottom
        self._apply_guide_zoom()

        # Auto-scroll based on push-through gesture target position or selected date:
        target_pos = getattr(self, "_target_grid_scroll_position", None)
        self._target_grid_scroll_position = None

        if target_pos in ("0400", "04:00", "4am", "start"):
            QTimer.singleShot(60, self.jump_guide_to_0400)
        elif target_pos == "end":
            QTimer.singleShot(60, lambda: self._scroll_grid_to_slot(48, center=False))
        elif keep_scroll:
            self.guide_grid_table.horizontalScrollBar().setValue(saved_h)
            self.guide_grid_table.verticalScrollBar().setValue(saved_v)
        else:
            if target_date_str == today.strftime("%Y-%m-%d"):
                QTimer.singleShot(60, self.jump_guide_to_now)
            else:
                QTimer.singleShot(60, self.jump_guide_to_noon)

    def clear_guide_selection(self):
        """
        Clears the selection and unhighlights any selected program in both
        the guide grid and list views, resetting the program detail panel.
        """
        self.selected_grid_program = None
        self._last_clicked_guide_list_row = -1

        if hasattr(self, "guide_grid_table") and self.guide_grid_table:
            self.guide_grid_table.clearSelection()
            self.guide_grid_table.setCurrentCell(-1, -1)
            self.guide_grid_table.viewport().update()

        if hasattr(self, "guide_table") and self.guide_table:
            self.guide_table.clearSelection()
            self.guide_table.setCurrentCell(-1, -1)
            self.guide_table.viewport().update()

        if hasattr(self, "guide_detail_title"):
            self.guide_detail_title.setText("Select a program to view details")
        if hasattr(self, "guide_detail_text"):
            self.guide_detail_text.clear()

        if hasattr(self, "watch_guide_btn"):
            self.watch_guide_btn.setVisible(False)
        if hasattr(self, "stop_timeshift_btn"):
            self.stop_timeshift_btn.setVisible(False)
        if hasattr(self, "record_guide_btn"):
            self.record_guide_btn.setVisible(True)
            self.record_guide_btn.setText("Record Program")
        if hasattr(self, "adjust_buffer_guide_btn"):
            self.adjust_buffer_guide_btn.setVisible(False)
        if hasattr(self, "cancel_guide_btn"):
            self.cancel_guide_btn.setVisible(False)

    def on_grid_cell_clicked(self, row: int, col: int):
        item = self.guide_grid_table.item(row, col)
        if not item:
            # Check previous columns in case of span
            for c in range(col - 1, -1, -1):
                it = self.guide_grid_table.item(row, c)
                if it and it.data(Qt.ItemDataRole.UserRole):
                    p_data = it.data(Qt.ItemDataRole.UserRole)
                    p_span = p_data.get("_span", 1) if isinstance(p_data, dict) else 1
                    if c + p_span > col:
                        item = it
                    break

        if not item or not item.data(Qt.ItemDataRole.UserRole):
            self.clear_guide_selection()
            return

        prog = item.data(Qt.ItemDataRole.UserRole)
        # Option 1: Clicking the currently selected program tile again toggles / unhighlights it
        cur_sel = getattr(self, "selected_grid_program", None)
        if cur_sel is not None:
            is_same = False
            if cur_sel is prog or cur_sel == prog:
                is_same = True
            elif cur_sel.get("id") is not None and prog.get("id") is not None:
                is_same = (cur_sel.get("id") == prog.get("id"))
            else:
                cur_ch = (cur_sel.get("kaffeine_channel") or cur_sel.get("channel") or cur_sel.get("channel_id") or "").strip().lower()
                prog_ch = (prog.get("kaffeine_channel") or prog.get("channel") or prog.get("channel_id") or "").strip().lower()
                cur_start = cur_sel.get("start_iso") or ""
                prog_start = prog.get("start_iso") or ""
                if cur_ch and prog_ch and cur_ch == prog_ch and cur_start and prog_start and cur_start == prog_start:
                    is_same = True

            if is_same:
                self.clear_guide_selection()
                return

        root_col = prog.get("_start_col", col)
        root_item = self.guide_grid_table.item(row, root_col)
        self.guide_grid_table.clearSelection()
        if root_item:
            self.guide_grid_table.setCurrentCell(row, root_col)
            root_item.setSelected(True)

        self.selected_grid_program = prog
        self._display_program_details(prog)
        self.guide_grid_table.viewport().update()

        if getattr(self.config_mgr, "guide_single_click_play", True):
            self.handle_program_activation(prog)

    def _display_program_details(self, prog: Dict[str, Any]):
        channel = prog.get("kaffeine_channel", "")
        start = prog.get("start_time_local", "")
        season = prog.get("season")
        number = prog.get("number")
        summary = prog.get("summary") or "No description available."

        active_map = self.queue_mgr.get_active_scheduled_map()
        ch_key = (channel or "").strip().lower()
        iso_key = (prog.get("start_iso") or "")[:16]
        rec_info = active_map.get((ch_key, iso_key))

        # Smart timing state for Watch Live / Tune Channel / Play Recording button
        timing_info = self._get_program_timing_state(prog)
        state = timing_info.get("state", "upcoming")

        header_prefix = ""
        if rec_info:
            st = (rec_info.get("status") or "QUEUED").upper()
            header_prefix = f"<span style='color: #ff5252; font-weight: bold;'>[● {st}]</span> "

        # Color-code the show title by its timing state and category (Option 1)
        cat = prog.get("_category") or classify_guide_category(prog)
        cat_colors = self.config_mgr.category_colors
        if state == "past":
            title_color_hex = "#788292"  # Dark grey, readable
        elif state == "live":
            if cat in ("sports", "news", "movies"):
                title_color_hex = cat_colors.get(cat, DEFAULT_CATEGORY_COLORS.get(cat, "#ffa028"))
            else:
                title_color_hex = "#66bb6a"  # Green used before
        else: # upcoming
            title_color_hex = cat_colors.get(cat, cat_colors.get("tvshows", "#b9feff"))

        primary_title, secondary_sub = get_program_display_titles(prog)
        escaped_title = html.escape(primary_title)
        colored_title = f"<span style='color: {title_color_hex}; font-weight: bold;'>{escaped_title}</span>"

        details_parts = []
        if cat == "sports" and secondary_sub:
            details_parts.append(f" ({html.escape(secondary_sub)})")
        elif cat != "movies" and secondary_sub and secondary_sub != primary_title:
            details_parts.append(f" - &quot;{html.escape(secondary_sub)}&quot;")

        if season and number:
            details_parts.append(f" (S{season:02d}E{number:02d})")
        friendly_start = format_american_datetime(start) or str(start)
        details_parts.append(f" on {html.escape(str(channel))} at {html.escape(friendly_start)}")
        rest_of_header = "".join(details_parts)

        self.guide_detail_title.setText(header_prefix + colored_title + rest_of_header)
        self.guide_detail_text.setText(summary)

        live_mode = getattr(self.config_mgr, "live_tv_watch_mode", "timeshift")
        rec_file = timing_info.get("recorded_file")
        is_live_rec = timing_info.get("is_active_recording") or bool(rec_file)
        player_name = self.config_mgr.playback_player
        player_disp = "Player" if player_name == "system" else player_name.upper()

        single_click = getattr(self.config_mgr, "guide_single_click_play", True)

        if hasattr(self, "watch_guide_btn"):
            if single_click:
                self.watch_guide_btn.setVisible(False)
            elif state == "live":
                self.watch_guide_btn.setVisible(True)
                self.watch_guide_btn.setText("Watch Live")
                self.watch_guide_btn.setStyleSheet("font-weight: bold; background-color: #1976d2; color: #ffffff; padding: 4px 12px;")
            elif state == "upcoming":
                self.watch_guide_btn.setVisible(True)
                self.watch_guide_btn.setText("Watch Channel")
                self.watch_guide_btn.setStyleSheet("padding: 4px 12px;")
            elif state == "past":
                if timing_info.get("recorded_file"):
                    self.watch_guide_btn.setVisible(True)
                    self.watch_guide_btn.setText("Play Recording")
                    self.watch_guide_btn.setStyleSheet("font-weight: bold; background-color: #1976d2; color: #ffffff; padding: 4px 12px;")
                else:
                    self.watch_guide_btn.setVisible(False)

        if hasattr(self, "record_guide_btn"):
            self.record_guide_btn.setVisible(rec_info is None)
            self.record_guide_btn.setText("Record Program")

        if hasattr(self, "adjust_buffer_guide_btn"):
            self.adjust_buffer_guide_btn.setVisible(rec_info is not None)

        if hasattr(self, "cancel_guide_btn"):
            self.cancel_guide_btn.setVisible(rec_info is not None)

        has_active_ts = bool(getattr(self, "_active_timeshift", None))
        cur_ts_ch = (self._active_timeshift.get("channel") or "").strip().lower() if has_active_ts else ""
        sel_ch = (channel or "").strip().lower()

        if hasattr(self, "stop_timeshift_btn"):
            if single_click:
                self.stop_timeshift_btn.setVisible(False)
            elif has_active_ts and (cur_ts_ch == sel_ch or state == "live"):
                self.stop_timeshift_btn.setVisible(True)
                self.stop_timeshift_btn.setText(f"Stop Timeshift ({self._active_timeshift.get('channel')})")
            else:
                self.stop_timeshift_btn.setVisible(False)

    def on_guide_list_cell_clicked(self, row: int, col: int):
        if getattr(self, "_last_clicked_guide_list_row", -1) == row:
            self.clear_guide_selection()
        else:
            self._last_clicked_guide_list_row = row
            if getattr(self.config_mgr, "guide_single_click_play", True):
                if 0 <= row < len(getattr(self, "current_guide_items", [])):
                    prog = self.current_guide_items[row]
                    self.handle_program_activation(prog)

    def on_guide_selection_changed(self):
        row = self.guide_table.currentRow()
        if row < 0 or row >= len(getattr(self, "current_guide_items", [])):
            self.clear_guide_selection()
            return

        self._last_clicked_guide_list_row = row
        prog = self.current_guide_items[row]
        self._display_program_details(prog)

    def _get_active_selected_program(self) -> Optional[Dict[str, Any]]:
        if self.guide_stack.currentIndex() == 0:
            return getattr(self, "selected_grid_program", None)
        else:
            row = self.guide_table.currentRow()
            if row >= 0 and row < len(getattr(self, "current_guide_items", [])):
                return self.current_guide_items[row]
        return None

    def _get_program_timing_state(self, prog: Dict[str, Any], check_files: bool = True) -> Dict[str, Any]:
        """
        Calculates whether a program is live, upcoming, or past, and looks for recorded files if past.
        When check_files is False (e.g. bulk table population or row styling), bypasses disk scans
        and database lookups for instant memory-speed execution.
        """
        now = datetime.now()
        start_iso = prog.get("start_iso")
        dur_iso = prog.get("duration_iso") or "00:30:00"

        start_dt = prog.get("_parsed_start_dt")
        end_dt = prog.get("_parsed_end_dt")
        if start_dt is None and start_iso:
            try:
                start_dt = datetime.fromisoformat(start_iso)
                parts = [int(x) for x in dur_iso.split(":")]
                dur = timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2] if len(parts) > 2 else 0)
                end_dt = start_dt + dur
                prog["_parsed_start_dt"] = start_dt
                prog["_parsed_end_dt"] = end_dt
            except Exception:
                pass

        if not start_dt or not end_dt:
            return {"state": "live", "time_desc": "", "start_fmt": "", "recorded_file": None}

        start_fmt = start_dt.strftime("%I:%M %p").lstrip("0")
        if start_dt.date() == now.date():
            time_prefix = f"Today at {start_fmt}"
        elif start_dt.date() == (now.date() + timedelta(days=1)):
            time_prefix = f"Tomorrow at {start_fmt}"
        else:
            time_prefix = f"{start_dt.strftime('%a, %b %d')} at {start_fmt}"

        recorded_file = None

        if start_dt <= now < end_dt:
            mins_left = max(1, int((end_dt - now).total_seconds() // 60))
            if not check_files:
                return {
                    "state": "live",
                    "time_desc": f"Live Now ({mins_left}m remaining)",
                    "start_fmt": start_fmt,
                    "recorded_file": None,
                    "is_active_recording": False,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                }

            active_file = None
            title = (prog.get("show_title") or prog.get("title") or "").strip()
            ch = (prog.get("kaffeine_channel") or "").strip().lower()
            start_iso_prefix = (start_iso or "")[:16]

            # Check if this live program has an active recording or recording file
            rec_data = prog.get("_scheduled_rec")
            if not rec_data:
                try:
                    active_map = self.queue_mgr.get_active_scheduled_map()
                    rec_data = active_map.get((ch, start_iso_prefix))
                except Exception:
                    pass

            if rec_data or prog.get("_scheduled_rec"):
                try:
                    cand = self.storage_mgr.find_active_or_recent_recording_file(title)
                    if cand:
                        active_file = str(cand)
                except Exception:
                    pass

            return {
                "state": "live",
                "time_desc": f"Live Now ({mins_left}m remaining)",
                "start_fmt": start_fmt,
                "recorded_file": active_file,
                "is_active_recording": bool(rec_data and active_file),
                "start_dt": start_dt,
                "end_dt": end_dt,
            }
        elif now < start_dt:
            delta_sec = int((start_dt - now).total_seconds())
            if delta_sec < 3600:
                mins = max(1, delta_sec // 60)
                relative = f"in {mins}m"
            elif delta_sec < 86400:
                hours = delta_sec // 3600
                mins = (delta_sec % 3600) // 60
                relative = f"in {hours}h {mins}m"
            else:
                days = delta_sec // 86400
                relative = f"in {days}d"

            return {
                "state": "upcoming",
                "time_desc": f"{relative} ({time_prefix})",
                "start_fmt": time_prefix,
                "recorded_file": None,
                "start_dt": start_dt,
                "end_dt": end_dt,
            }
        else:
            end_fmt = end_dt.strftime("%I:%M %p").lstrip("0")
            if not check_files:
                return {
                    "state": "past",
                    "time_desc": f"Ended at {end_fmt} ({start_dt.strftime('%b %d')})",
                    "start_fmt": start_fmt,
                    "recorded_file": None,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                }

            # Past program: search for recorded file
            title = (prog.get("show_title") or prog.get("title") or "").strip()
            ch = (prog.get("kaffeine_channel") or "").strip().lower()
            start_iso_prefix = (start_iso or "")[:16]

            # 1. Search in QueueManager
            try:
                for q_item in self.queue_mgr.list_queue(include_completed=True):
                    q_ch = (q_item.get("channel") or "").strip().lower()
                    q_iso = (q_item.get("start_iso") or "")[:16]
                    if (q_ch == ch and q_iso == start_iso_prefix) or (title and title.lower() in (q_item.get("title") or "").lower() and q_iso == start_iso_prefix):
                        fp = q_item.get("file_path")
                        if fp and os.path.exists(fp):
                            recorded_file = fp
                            break
            except Exception:
                pass

            # 2. Search in Recording Folder if not found yet
            if not recorded_file:
                try:
                    rec_folder = self.storage_mgr.get_recording_folder()
                    if rec_folder and rec_folder.exists():
                        safe_title_words = [w.lower() for w in re.findall(r"\w+", title) if len(w) > 3]
                        date_str = start_dt.strftime("%Y-%m-%d")
                        for ext in StorageManager.VIDEO_EXTENSIONS:
                            for vf in rec_folder.glob(f"*{ext}"):
                                vf_name_lower = vf.name.lower()
                                if date_str in vf_name_lower and any(w in vf_name_lower for w in safe_title_words):
                                    recorded_file = str(vf)
                                    break
                            if recorded_file:
                                break
                except Exception:
                    pass

            return {
                "state": "past",
                "time_desc": f"Ended at {end_fmt} ({start_dt.strftime('%b %d')})",
                "start_fmt": start_fmt,
                "recorded_file": recorded_file,
                "start_dt": start_dt,
                "end_dt": end_dt,
            }

    def _find_live_program_for_channel(self, ch: str) -> Optional[Dict[str, Any]]:
        """Finds the currently broadcasting program for the given channel in the guide database."""
        if not ch or not hasattr(self, "guide_service") or not self.guide_service:
            return None
        try:
            return self.guide_service.get_live_program_for_channel(ch)
        except Exception as e:
            print(f"Error finding live program for channel {ch}: {e}")
        return None

    def watch_or_tune_selected_guide_item(self, target_prog: Optional[Dict[str, Any]] = None):
        prog = target_prog or self._get_active_selected_program()
        if not prog:
            QMessageBox.warning(self, "Selection Required", "Please select a program from the guide.")
            return

        timing_info = self._get_program_timing_state(prog)
        state = timing_info.get("state")
        ch = prog.get("kaffeine_channel") or prog.get("channel", "")
        title = prog.get("show_title") or prog.get("title") or "Program"
        rec_file = timing_info.get("recorded_file")
        is_live_rec = timing_info.get("is_active_recording") or bool(rec_file)

        if state == "live":
            if is_live_rec and rec_file:
                self.dbus_client.play_file(
                    rec_file,
                    player=self.config_mgr.live_tv_watch_mode,
                    custom_cmd=self.config_mgr.custom_live_tv_player_cmd
                )
                self.status_bar.showMessage(f"Playing live recording: {os.path.basename(rec_file)}", 4000)
            else:
                self.start_timeshift_playback(prog)
        elif state == "upcoming":
            live_prog = self._find_live_program_for_channel(ch)
            if not live_prog:
                now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                live_prog = {
                    "show_title": f"{ch} Live",
                    "title": f"{ch} Live",
                    "kaffeine_channel": ch,
                    "channel": ch,
                    "start_iso": now_iso,
                    "duration_iso": "02:00:00",
                }
            self.start_timeshift_playback(live_prog)
        elif state == "past":
            if rec_file:
                self.dbus_client.play_file(
                    rec_file,
                    player=self.config_mgr.playback_player,
                    custom_cmd=self.config_mgr.custom_playback_player_cmd
                )
                self.status_bar.showMessage(f"Playing recording: {os.path.basename(rec_file)}", 4000)

    def alt_watch_or_tune_selected_guide_item(self):
        self.watch_or_tune_selected_guide_item()

    def handle_program_activation(self, prog: Dict[str, Any]):
        if not prog:
            return

        timing_info = self._get_program_timing_state(prog)
        state = timing_info.get("state")
        ch = prog.get("kaffeine_channel") or prog.get("channel", "")
        title = prog.get("show_title") or prog.get("title") or "Program"
        rec_file = timing_info.get("recorded_file")
        is_live_rec = timing_info.get("is_active_recording") or bool(rec_file)

        if state == "live":
            if is_live_rec and rec_file:
                self.dbus_client.play_file(
                    rec_file,
                    player=self.config_mgr.live_tv_watch_mode,
                    custom_cmd=self.config_mgr.custom_live_tv_player_cmd
                )
                self.status_bar.showMessage(f"Playing live recording: {os.path.basename(rec_file)}", 4000)
            else:
                self.start_timeshift_playback(prog)
        elif state == "upcoming":
            # Check if this program has an active scheduled recording
            active_map = self.queue_mgr.get_active_scheduled_map() if hasattr(self, "queue_mgr") and self.queue_mgr else {}
            ch_key = (ch or "").strip().lower()
            iso_key = (prog.get("start_iso") or "")[:16]
            is_scheduled = bool(prog.get("_scheduled_rec") or active_map.get((ch_key, iso_key)))

            # Smart Choice Dialog
            dlg = UpcomingShowDialog(prog, timing_info, is_scheduled=is_scheduled, parent=self)
            dlg.exec()
            if dlg.action == UpcomingShowDialog.ACTION_RECORD:
                self.record_selected_guide_item()
            elif dlg.action == UpcomingShowDialog.ACTION_CANCEL_RECORDING:
                self.cancel_selected_guide_recording()
            elif dlg.action == UpcomingShowDialog.ACTION_TUNE:
                self.watch_or_tune_selected_guide_item()
        elif state == "past":
            if rec_file:
                self.dbus_client.play_file(
                    rec_file,
                    player=self.config_mgr.playback_player,
                    custom_cmd=self.config_mgr.custom_playback_player_cmd
                )
                self.status_bar.showMessage(f"Playing recording: {os.path.basename(rec_file)}", 4000)
            else:
                QMessageBox.information(
                    self, "Broadcast Ended",
                    f"'{title}' on {ch} has already finished broadcasting ({timing_info.get('time_desc')})."
                )

    def _on_grid_channel_header_clicked(self, logical_index: int):
        """
        Handles user clicking the channel header square on the left of the TV guide grid:
        - If the channel is already playing, informs the user or focuses the session.
        - Otherwise, initiates continuous live channel playback without program boundary cuts.
        """
        channel_name = ""
        if hasattr(self, "grid_channels") and logical_index < len(self.grid_channels):
            channel_name = str(self.grid_channels[logical_index]).strip()
        elif hasattr(self, "guide_grid_table") and self.guide_grid_table.model():
            val = self.guide_grid_table.model().headerData(logical_index, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole)
            if val is not None:
                channel_name = str(val).strip()

        if not channel_name:
            return

        active_ts = getattr(self, "_active_timeshift", None)
        active_ch = (active_ts.get("channel") or "").strip().lower() if active_ts else ""
        if active_ch and active_ch == channel_name.lower():
            # Channel is currently playing
            self.status_bar.showMessage(f"Channel {channel_name} is already playing continuously in {self.config_mgr.live_tv_watch_mode.upper()}.", 4000)
            return

        self.start_continuous_channel_playback(channel_name)

    def start_continuous_channel_playback(self, channel: str):
        """
        Starts continuous live channel timeshifting for an extended 8-hour block on the given channel:
        - Unlike individual show playback, continuous channel playback keeps recording and playing
          through consecutive shows uninterrupted until the player is closed or stopped.
        """
        if not channel:
            return

        ch = channel.strip()
        now_dt = datetime.now()
        now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%S")

        live_prog = self._find_live_program_for_channel(ch)
        current_show_title = live_prog.get("show_title") or live_prog.get("title") if live_prog else "Live Stream"

        # Continuous capture program definition: 8-hour block
        continuous_prog = {
            "show_title": f"{ch} Live Stream",
            "title": f"{ch} Live Stream",
            "kaffeine_channel": ch,
            "channel": ch,
            "start_iso": now_iso,
            "duration_iso": "08:00:00",
            "_is_continuous_channel": True,
            "_original_show": current_show_title
        }

        self.status_bar.showMessage(f"Starting continuous stream on {ch} (Now: {current_show_title})...", 5000)
        self.start_timeshift_playback(continuous_prog)

    def start_timeshift_playback(self, prog: Dict[str, Any]):
        """
        Timeshifts a live broadcast in the user's selected video player:
        - If already recording and .m2t file exists, opens immediately in player.
        - Otherwise, queues recording directly for prog, dispatches to Kaffeine (minimized in background),
          waits a few seconds for tuner lock and stream buffering, then launches the player.
        """
        if not prog:
            return

        title = prog.get("show_title") or prog.get("title") or "Live Program"
        ch = prog.get("kaffeine_channel") or prog.get("channel", "")

        # If switching from an existing timeshift channel, stop previous session first
        if getattr(self, "_active_timeshift", None):
            prev_ch = (self._active_timeshift.get("channel") or "").strip().lower()
            cur_ch = (ch or "").strip().lower()
            if prev_ch != cur_ch:
                self.status_bar.showMessage(f"Switching channels: stopping previous stream on {self._active_timeshift.get('channel')}...", 3000)
                self.stop_timeshift_session(user_initiated=True)

        active_map = self.queue_mgr.get_active_scheduled_map()
        ch_key = (ch or "").strip().lower()
        iso_key = (prog.get("start_iso") or "")[:16]
        rec_info = active_map.get((ch_key, iso_key))
        was_already_scheduled = bool(rec_info)

        # Compute recording title for this specific program
        cat = prog.get("_category") or classify_guide_category(prog)
        show = prog.get("show_title") or prog.get("title") or "Live TV"
        ep = prog.get("episode_title", "")
        if cat == "movies":
            rec_title = show
        elif cat == "sports" and ep:
            rec_title = f"{show}: {ep}" if show else ep
        else:
            rec_title = f"{show} - {ep}" if ep else show

        # Check if file is already active on disk (search by title or rec_title)
        active_file = (
            self.storage_mgr.find_active_or_recent_recording_file(rec_title, max_age_seconds=7200)
            or self.storage_mgr.find_active_or_recent_recording_file(title, max_age_seconds=7200)
        )
        if active_file and active_file.exists():
            proc = self.dbus_client.play_file(
                str(active_file),
                player=self.config_mgr.live_tv_watch_mode,
                custom_cmd=self.config_mgr.custom_live_tv_player_cmd,
                standalone=True
            )
            pname = self.config_mgr.live_tv_watch_mode.upper()
            self.status_bar.showMessage(f"Playing active recording '{title}' in {pname}.", 5000)
            self._active_timeshift = {
                "title": rec_title,
                "channel": ch,
                "queue_id": rec_info.get("id") if rec_info else None,
                "kaffeine_key": rec_info.get("kaffeine_key") if rec_info else None,
                "process": proc,
                "file_path": str(active_file),
                "is_scheduled_recording": was_already_scheduled
            }
            if proc and hasattr(self, "_timeshift_poll_timer"):
                self._timeshift_poll_timer.start()
            if hasattr(self, "guide_grid_vheader") and self.guide_grid_vheader:
                self.guide_grid_vheader.viewport().update()
            self._display_program_details(prog)
            return

        # Ensure program is queued specifically for prog and recording is dispatched
        qid = None
        if not rec_info:
            try:
                now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                start_iso = prog.get("start_iso") or now_iso
                duration_iso = prog.get("duration_iso") or "02:00:00"

                qid = self.queue_mgr.add_recording(
                    rec_title, ch, start_iso, duration_iso,
                    lead_time_mins=0, buffer_mins=0
                )
                self.watcher.check_and_dispatch(notify=False)
                active_map = self.queue_mgr.get_active_scheduled_map()
                rec_info = active_map.get((ch_key, iso_key))
                if not rec_info and qid:
                    for item in active_map.values():
                        if item.get("id") == qid:
                            rec_info = item
                            break
            except Exception as e:
                self.status_bar.showMessage(f"Error starting background recording for timeshift: {e}", 4000)
                return
        else:
            qid = rec_info.get("id")

        buf_secs = getattr(self.config_mgr, "timeshift_buffer_seconds", 2)
        pname = self.config_mgr.live_tv_watch_mode.upper()
        self.status_bar.showMessage(f"Buffering live stream ({buf_secs}s) before opening in {pname}...", (buf_secs + 4) * 1000)
        QTimer.singleShot(
            buf_secs * 1000,
            lambda: self._on_timeshift_buffer_ready(
                prog,
                retries_left=6,
                was_already_scheduled=was_already_scheduled,
                queue_id=qid,
                rec_title=rec_title
            )
        )

    def _on_timeshift_buffer_ready(
        self,
        prog: Dict[str, Any],
        retries_left: int = 6,
        was_already_scheduled: bool = False,
        queue_id: Optional[int] = None,
        rec_title: Optional[str] = None
    ):
        title = prog.get("show_title") or prog.get("title") or ""
        ch = prog.get("kaffeine_channel") or prog.get("channel", "")
        lookup_title = rec_title or title

        active_file = (
            self.storage_mgr.find_active_or_recent_recording_file(lookup_title, max_age_seconds=600)
            or self.storage_mgr.find_active_or_recent_recording_file(title, max_age_seconds=600)
        )
        if not active_file or not active_file.exists():
            # If title search had no hit, check if any recent file appeared in recording folder
            try:
                rec_folder = self.storage_mgr.get_recording_folder()
                if rec_folder and rec_folder.exists():
                    now_ts = time.time()
                    newest_file = None
                    newest_mtime = 0
                    for ext in StorageManager.VIDEO_EXTENSIONS:
                        for vf in rec_folder.glob(f"*{ext}"):
                            try:
                                st = vf.stat()
                                if (now_ts - st.st_mtime) < 120 and st.st_size > 16384:
                                    if st.st_mtime > newest_mtime:
                                        newest_mtime = st.st_mtime
                                        newest_file = vf
                            except Exception:
                                pass
                    if newest_file:
                        active_file = newest_file
            except Exception:
                pass

        if active_file and active_file.exists():
            proc = self.dbus_client.play_file(
                str(active_file),
                player=self.config_mgr.live_tv_watch_mode,
                custom_cmd=self.config_mgr.custom_live_tv_player_cmd,
                standalone=True
            )
            pname = self.config_mgr.live_tv_watch_mode.upper()
            self.status_bar.showMessage(f"Playing live broadcast '{title}' in {pname}.", 5000)

            ch_key = (ch or "").strip().lower()
            iso_key = (prog.get("start_iso") or "")[:16]
            rec_info = self.queue_mgr.get_active_scheduled_map().get((ch_key, iso_key))

            self._active_timeshift = {
                "title": lookup_title,
                "channel": ch,
                "queue_id": queue_id or (rec_info.get("id") if rec_info else None),
                "kaffeine_key": rec_info.get("kaffeine_key") if rec_info else None,
                "process": proc,
                "file_path": str(active_file),
                "is_scheduled_recording": was_already_scheduled
            }
            if proc and hasattr(self, "_timeshift_poll_timer"):
                self._timeshift_poll_timer.start()
            if hasattr(self, "guide_grid_vheader") and self.guide_grid_vheader:
                self.guide_grid_vheader.viewport().update()
            self._display_program_details(prog)
            return

        if retries_left > 0:
            self.status_bar.showMessage("Buffering stream data...", 1000)
            QTimer.singleShot(
                600,
                lambda: self._on_timeshift_buffer_ready(
                    prog,
                    retries_left - 1,
                    was_already_scheduled=was_already_scheduled,
                    queue_id=queue_id,
                    rec_title=rec_title
                )
            )
        else:
            self.status_bar.showMessage(
                f"Recording started on '{title}', but could not locate playable .m2t file yet. Check recording folder.", 6000
            )

    def _poll_timeshift_session(self):
        if not getattr(self, "_active_timeshift", None):
            if hasattr(self, "_timeshift_poll_timer"):
                self._timeshift_poll_timer.stop()
            return

        proc = self._active_timeshift.get("process")
        # xdg-open exits immediately upon delegating to the desktop environment;
        # do not treat immediate xdg-open exit as player closure.
        if getattr(proc, "_is_xdg_open", False) or (proc and getattr(proc, "args", None) and "xdg-open" in str(proc.args[0])):
            return

        if proc is not None and proc.poll() is not None:
            # Process has exited!
            if hasattr(self, "_timeshift_poll_timer"):
                self._timeshift_poll_timer.stop()
            self.stop_timeshift_session(user_initiated=False)

    def stop_timeshift_session(self, user_initiated: bool = False):
        if not getattr(self, "_active_timeshift", None):
            return

        session = dict(self._active_timeshift)
        self._active_timeshift = None
        if hasattr(self, "_timeshift_poll_timer"):
            self._timeshift_poll_timer.stop()

        title = session.get("title", "")
        ch = session.get("channel", "")
        qid = session.get("queue_id")
        key = session.get("kaffeine_key")
        fpath = session.get("file_path")
        is_scheduled = session.get("is_scheduled_recording", False)
        proc = session.get("process")

        if user_initiated and proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

        if not is_scheduled:
            # Cancel background recording in Kaffeine to immediately free tuner
            try:
                self.dbus_client.cancel_recording(key=key, channel=ch, title=title)
            except Exception as e:
                print(f"Error cancelling Kaffeine timeshift recording: {e}")

            # Remove from queue manager
            if qid:
                try:
                    self.queue_mgr.remove_recording(int(qid))
                except Exception:
                    pass

            # Clean up temporary buffer file if configured
            if getattr(self.config_mgr, "delete_timeshift_on_exit", True) and fpath:
                try:
                    p = Path(fpath)
                    if p.exists():
                        p.unlink()
                        print(f"Deleted temporary timeshift buffer: {p.name}")
                except Exception as e:
                    print(f"Error removing temporary timeshift file {fpath}: {e}")

            msg = f"Timeshift ended on {ch} ('{title}'). Tuner released."
        else:
            msg = f"Closed playback for '{title}'. Scheduled recording continues in background."

        self.status_bar.showMessage(msg, 5000)
        self.refresh_recordings()
        self._refresh_guide_view(keep_scroll=True)
        if hasattr(self, "guide_grid_vheader") and self.guide_grid_vheader:
            self.guide_grid_vheader.viewport().update()
        prog = self._get_active_selected_program()
        if prog:
            self._display_program_details(prog)
        else:
            self.clear_guide_selection()

    def on_grid_cell_double_clicked(self, row: int, col: int):
        item = self.guide_grid_table.item(row, col)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            for c in range(col - 1, -1, -1):
                it = self.guide_grid_table.item(row, c)
                if it and it.data(Qt.ItemDataRole.UserRole):
                    item = it
                    break
        if item and item.data(Qt.ItemDataRole.UserRole):
            prog = item.data(Qt.ItemDataRole.UserRole)
            root_col = prog.get("_start_col", col)
            root_item = self.guide_grid_table.item(row, root_col)
            if root_item:
                self.guide_grid_table.setCurrentCell(row, root_col)
                root_item.setSelected(True)
            self.selected_grid_program = prog
            self._display_program_details(prog)
            self.handle_program_activation(prog)

    def on_guide_table_double_clicked(self, item: QTableWidgetItem):
        row = item.row()
        if 0 <= row < len(getattr(self, "current_guide_items", [])):
            prog = self.current_guide_items[row]
            self._display_program_details(prog)
            self.handle_program_activation(prog)

    def _on_guide_grid_context_menu(self, pos: QPoint):
        row = self.guide_grid_table.rowAt(pos.y())
        col = self.guide_grid_table.columnAt(pos.x())
        if row < 0 or col < 0:
            return

        item = self.guide_grid_table.item(row, col)
        if not item or not item.data(Qt.ItemDataRole.UserRole):
            for c in range(col - 1, -1, -1):
                it = self.guide_grid_table.item(row, c)
                if it and it.data(Qt.ItemDataRole.UserRole):
                    p_data = it.data(Qt.ItemDataRole.UserRole)
                    p_span = p_data.get("_span", 1) if isinstance(p_data, dict) else 1
                    if c + p_span > col:
                        item = it
                    break

        if not item or not item.data(Qt.ItemDataRole.UserRole):
            return

        prog = item.data(Qt.ItemDataRole.UserRole)
        root_col = prog.get("_start_col", col)
        root_item = self.guide_grid_table.item(row, root_col)
        self.guide_grid_table.clearSelection()
        if root_item:
            self.guide_grid_table.setCurrentCell(row, root_col)
            root_item.setSelected(True)

        self.selected_grid_program = prog
        self._display_program_details(prog)
        self.guide_grid_table.viewport().update()

        global_pos = self.guide_grid_table.viewport().mapToGlobal(pos)
        self._show_guide_program_context_menu(prog, global_pos)

    def _on_guide_list_context_menu(self, pos: QPoint):
        row = self.guide_table.rowAt(pos.y())
        if row < 0 or row >= len(getattr(self, "current_guide_items", [])):
            return

        prog = self.current_guide_items[row]
        self.guide_table.setCurrentCell(row, 0)
        self.guide_table.selectRow(row)
        self._last_clicked_guide_list_row = row
        self._display_program_details(prog)

        global_pos = self.guide_table.viewport().mapToGlobal(pos)
        self._show_guide_program_context_menu(prog, global_pos)

    def _show_guide_program_context_menu(self, prog: Dict[str, Any], global_pos: Optional[QPoint] = None):
        if not prog:
            return

        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setObjectName("guideContextMenu")

        primary_title, secondary_sub = get_program_display_titles(prog)
        channel = prog.get("kaffeine_channel") or prog.get("channel") or ""
        start = prog.get("start_time_local", "")
        season = prog.get("season")
        number = prog.get("number")
        summary = (prog.get("summary") or "").strip() or "No description available."
        friendly_start = format_american_datetime(start) or str(start)

        dur_iso = prog.get("duration_iso", "") or ""
        dur_str = ""
        if dur_iso:
            parts = dur_iso.split(":")
            if len(parts) >= 2:
                try:
                    h = int(parts[0])
                    m = int(parts[1])
                    if h > 0 and m > 0:
                        dur_str = f"{h}h {m}m"
                    elif h > 0:
                        dur_str = f"{h}h"
                    else:
                        dur_str = f"{m}m"
                except ValueError:
                    dur_str = dur_iso

        theme_key = getattr(self.config_mgr, "app_theme", "midnight")
        tokens = APP_THEMES.get(theme_key, APP_THEMES.get("midnight", {}))
        text_primary = tokens.get("text_primary", "#dce1e8")
        text_secondary = tokens.get("text_secondary", "#8c9bb0")
        popup_bg = tokens.get("bg_button", "#272d3d")
        popup_border = tokens.get("border_light", tokens.get("border_color", "#3d465c"))
        item_hover_bg = tokens.get("bg_button_hover", tokens.get("menu_item_selected", "#333a50"))

        menu.setStyleSheet(f"""
            QMenu#guideContextMenu {{
                background-color: {popup_bg};
                color: {text_primary};
                border: 1.5px solid {popup_border};
                border-radius: 10px;
                padding: 8px 6px;
                font-size: 14px;
            }}
            QMenu#guideContextMenu::item {{
                padding: 8px 18px;
                border-radius: 6px;
                margin: 2px 6px;
                font-size: 14px;
                font-weight: 500;
            }}
            QMenu#guideContextMenu::item:selected {{
                background-color: {item_hover_bg};
                color: #ffffff;
            }}
            QMenu#guideContextMenu::separator {{
                height: 1px;
                background-color: {popup_border};
                margin: 6px 10px;
            }}
        """)

        cat = prog.get("_category") or classify_guide_category(prog)
        cat_colors = getattr(self.config_mgr, "category_colors", {})
        title_color_hex = cat_colors.get(cat, DEFAULT_CATEGORY_COLORS.get(cat, "#b9feff"))

        container = QWidget()
        container.setObjectName("guideContextMenuContainer")
        container.setMinimumWidth(480)
        container.setMaximumWidth(540)
        container.setStyleSheet(
            "QWidget#guideContextMenuContainer { background: transparent; } "
            "QLabel { background: transparent; }"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(6)

        title_lbl = QLabel()
        title_lbl.setWordWrap(True)
        title_lbl.setMaximumWidth(520)
        escaped_title = html.escape(primary_title)
        title_html = f"<span style='font-size: 16px; font-weight: bold; color: {title_color_hex};'>{escaped_title}</span>"
        if season and number:
            title_html += f" <span style='font-size: 13px; color: {text_secondary};'>(S{season:02d}E{number:02d})</span>"
        title_lbl.setText(title_html)
        layout.addWidget(title_lbl)

        if secondary_sub and secondary_sub != primary_title:
            sub_lbl = QLabel(f"&quot;{html.escape(secondary_sub)}&quot;")
            sub_lbl.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {text_secondary};")
            sub_lbl.setWordWrap(True)
            sub_lbl.setMaximumWidth(520)
            layout.addWidget(sub_lbl)

        meta_parts = []
        if channel:
            meta_parts.append(str(channel))
        if friendly_start:
            meta_parts.append(friendly_start)
        if dur_str:
            meta_parts.append(f"({dur_str})")
        if meta_parts:
            meta_lbl = QLabel(" • ".join(meta_parts))
            meta_lbl.setStyleSheet(f"font-size: 12px; color: {text_secondary};")
            meta_lbl.setWordWrap(True)
            meta_lbl.setMaximumWidth(520)
            layout.addWidget(meta_lbl)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        divider.setStyleSheet(f"color: {popup_border}; background-color: {popup_border}; max-height: 1px; margin-top: 4px; margin-bottom: 4px;")
        layout.addWidget(divider)

        display_summary = summary
        has_more = False
        if len(summary) > 420:
            display_summary = summary[:417].rstrip() + "..."
            has_more = True

        desc_lbl = QLabel(display_summary)
        desc_lbl.setWordWrap(True)
        desc_lbl.setMaximumWidth(520)
        desc_lbl.setStyleSheet(f"font-size: 13px; color: {text_primary}; line-height: 1.4;")
        layout.addWidget(desc_lbl)

        if has_more:
            more_btn = QPushButton("Show full description...")
            more_btn.setObjectName("guidePillMoreDesc")
            more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            more_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {tokens.get('accent_color', '#3b82f6')};
                    font-size: 11.5px;
                    font-weight: 600;
                    border: none;
                    text-align: left;
                    padding: 2px 0px;
                }}
                QPushButton:hover {{
                    text-decoration: underline;
                }}
            """)
            more_btn.clicked.connect(lambda: (menu.close(), QMessageBox.information(self, f"{primary_title} - Program Details", summary)))
            layout.addWidget(more_btn)

        # Pill buttons row at bottom of card
        divider_bottom = QFrame()
        divider_bottom.setFrameShape(QFrame.Shape.HLine)
        divider_bottom.setFrameShadow(QFrame.Shadow.Plain)
        divider_bottom.setStyleSheet(f"color: {popup_border}; background-color: {popup_border}; max-height: 1px; margin-top: 8px; margin-bottom: 6px;")
        layout.addWidget(divider_bottom)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setContentsMargins(0, 2, 0, 2)

        def _add_pill(text, bg_color, hover_color, pressed_color, callback, obj_name=""):
            btn = QPushButton(text)
            if obj_name:
                btn.setObjectName(obj_name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setMinimumHeight(34)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
                    color: #ffffff;
                    font-size: 12.5px;
                    font-weight: 600;
                    border-radius: 17px;
                    padding: 6px 12px;
                    border: 1px solid rgba(255, 255, 255, 0.12);
                }}
                QPushButton:hover {{
                    background-color: {hover_color};
                }}
                QPushButton:pressed {{
                    background-color: {pressed_color};
                }}
            """)
            btn.clicked.connect(lambda checked=False, cb=callback: (menu.close(), cb()))
            btn_row.addWidget(btn)
            return btn

        # 1. Watch / Tune pill first
        timing_info = self._get_program_timing_state(prog)
        state = timing_info.get("state", "upcoming")
        if state == "live":
            _add_pill("Watch Live", "#2563eb", "#1d4ed8", "#1e40af", lambda: self.watch_or_tune_selected_guide_item(prog), "guidePillWatch")
        elif state == "upcoming":
            _add_pill("Watch Channel", "#2563eb", "#1d4ed8", "#1e40af", lambda: self.watch_or_tune_selected_guide_item(prog), "guidePillWatch")
        elif state == "past" and timing_info.get("recorded_file"):
            _add_pill("Play Recording", "#2563eb", "#1d4ed8", "#1e40af", lambda: self.watch_or_tune_selected_guide_item(prog), "guidePillWatch")

        has_active_ts = bool(getattr(self, "_active_timeshift", None))
        cur_ts_ch = (self._active_timeshift.get("channel") or "").strip().lower() if has_active_ts else ""
        sel_ch = (channel or "").strip().lower()
        if has_active_ts and (cur_ts_ch == sel_ch or state == "live"):
            _add_pill(f"Stop Timeshift ({self._active_timeshift.get('channel')})", "#475569", "#334155", "#1e293b", self.stop_timeshift, "guidePillStopTimeshift")

        # 2. Record Program pill second
        active_map = self.queue_mgr.get_active_scheduled_map()
        ch_key = (channel or "").strip().lower()
        iso_key = (prog.get("start_iso") or "")[:16]
        rec_info = active_map.get((ch_key, iso_key))

        if rec_info is None:
            _add_pill("Record Program", "#dc2626", "#b91c1c", "#991b1b", lambda: self.record_selected_guide_item(prog), "guidePillRecord")
        else:
            buf_val = rec_info.get("buffer_mins", 0) or 0
            _add_pill(f"Buffer (+{buf_val}m)", "#d97706", "#b45309", "#92400e", lambda: self.record_selected_guide_item(prog), "guidePillAdjustBuffer")
            _add_pill("Cancel Rec", "#991b1b", "#7f1d1d", "#5c1313", lambda: self.cancel_selected_guide_recording(prog), "guidePillCancelRecord")

        # 3. Record Series pill third
        _add_pill("Record Series", "#6366f1", "#4f46e5", "#4338ca", lambda: self.add_rule_from_selected_guide_item(prog), "guidePillRecordSeries")

        layout.addLayout(btn_row)

        header_action = QWidgetAction(menu)
        header_action.setDefaultWidget(container)
        menu.addAction(header_action)

        target_pos = global_pos if global_pos is not None else QCursor.pos()
        menu.exec(target_pos)

    def cancel_selected_guide_recording(self, target_prog: Optional[Dict[str, Any]] = None):
        prog = target_prog or self._get_active_selected_program()
        if not prog:
            QMessageBox.warning(self, "Selection Required", "Please select a program from the guide.")
            return

        active_map = self.queue_mgr.get_active_scheduled_map()
        ch_key = (prog.get("kaffeine_channel") or "").strip().lower()
        iso_key = (prog.get("start_iso") or "")[:16]
        rec_info = active_map.get((ch_key, iso_key))
        if not rec_info:
            QMessageBox.information(self, "No Recording Scheduled", "This program does not have an active scheduled recording.")
            return

        qid = rec_info.get("id")
        rec_title = rec_info.get("title") or prog.get("show_title", "")
        removed_info = self.queue_mgr.remove_recording(int(qid))
        target_info = removed_info or rec_info or {}
        self.dbus_client.cancel_recording(
            key=target_info.get("kaffeine_key"),
            channel=target_info.get("channel") or prog.get("kaffeine_channel"),
            title=target_info.get("title") or prog.get("show_title") or rec_title
        )
        self.status_bar.showMessage(f"Cancelled recording '{rec_title}'.", 3000)
        self.refresh_recordings()
        self._refresh_guide_view(keep_scroll=True)
        self._display_program_details(prog)

    def _refresh_guide_view(self, keep_scroll: bool = True):
        airdate = self.guide_date_combo.currentData() if hasattr(self, "guide_date_combo") else None
        if hasattr(self, "current_guide_items") and self.current_guide_items is not None:
            if self.guide_stack.currentIndex() == 0:
                self._populate_grid_guide(self.current_guide_items, airdate, keep_scroll=keep_scroll)
            else:
                self._populate_list_guide(self.current_guide_items)
        else:
            self.filter_guide()

    def record_selected_guide_item(self, target_prog: Optional[Dict[str, Any]] = None):
        prog = target_prog or self._get_active_selected_program()
        if not prog:
            QMessageBox.warning(self, "Selection Required", "Please select a program from the guide.")
            return

        channel = prog.get("kaffeine_channel", "")
        start_iso = prog.get("start_iso", "")
        duration_iso = prog.get("duration_iso", "")
        show = prog.get("show_title", "")
        ep = prog.get("episode_title", "")

        cat = prog.get("_category") or classify_guide_category(prog)
        if cat == "movies":
            rec_title = show
        elif cat == "sports" and ep:
            rec_title = f"{show}: {ep}" if show else ep
        else:
            rec_title = f"{show} - {ep}" if ep else show

        active_map = self.queue_mgr.get_active_scheduled_map()
        ch_key = (channel or "").strip().lower()
        iso_key = (start_iso or "")[:16]
        rec_info = active_map.get((ch_key, iso_key))

        if rec_info:
            # Already queued: open buffer adjust dialog directly
            qid = rec_info.get("id")
            current_buf = rec_info.get("buffer_mins", 0) or 0
            dlg = AdjustBufferDialog(rec_title, current_buffer=current_buf, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                new_buf = dlg.get_buffer()
                if self.queue_mgr.update_recording_buffer(int(qid), new_buf):
                    self.status_bar.showMessage(f"Updated buffer for '{rec_title}' to +{new_buf}m.", 4000)
                    self.refresh_recordings()
                    self._refresh_guide_view(keep_scroll=True)
                    self._display_program_details(prog)
                else:
                    QMessageBox.warning(self, "Update Failed", "Could not update recording buffer.")
            return

        is_sports = (classify_guide_category(prog) == "sports")
        if is_sports and self.config_mgr.auto_buffer_sports:
            buf_mins = self.config_mgr.sports_buffer_mins
        elif self.config_mgr.end_buffer_mins > 0:
            buf_mins = self.config_mgr.end_buffer_mins
        else:
            buf_mins = 0

        try:
            lead = self.config_mgr.lead_time_mins
            qid = self.queue_mgr.add_recording(
                rec_title, channel, start_iso, duration_iso,
                lead_time_mins=lead, buffer_mins=buf_mins
            )
            # Check if this program is immediately due (e.g. live or starting within lead time)
            armed = self.watcher.check_and_dispatch(notify=False)
            if armed > 0:
                self.status_bar.showMessage(f"Armed recording in Kaffeine: '{rec_title}' on {channel}", 4000)
            else:
                self.status_bar.showMessage(f"Queued recording: '{rec_title}' on {channel}", 4000)
            self.refresh_recordings()
            self._refresh_guide_view(keep_scroll=True)
            self._display_program_details(prog)
        except Exception as e:
            QMessageBox.critical(self, "Error Queueing Recording", str(e))

    def add_rule_from_selected_guide_item(self, target_prog: Optional[Dict[str, Any]] = None):
        prog = target_prog or self._get_active_selected_program()
        if not prog:
            QMessageBox.warning(self, "Selection Required", "Please select a program first.")
            return

        show_title = prog.get("show_title", "")
        ch = prog.get("kaffeine_channel", "All")
        self.rules_engine.add_rule(show_title, ch, buffer_mins=None)
        self.refresh_rules()
        self.tabs.setCurrentIndex(1)
        if hasattr(self, "recordings_subtabs"):
            self.recordings_subtabs.setCurrentIndex(1)
        self.run_rules(silent=False)

    # ------------------ RULES LOGIC ------------------
    def refresh_rules(self):
        rules = self.rules_engine.get_rules()
        self.rules_table.setRowCount(len(rules))
        for row, r in enumerate(rules):
            self.rules_table.setItem(row, 0, QTableWidgetItem(str(r.get("id"))))
            self.rules_table.setItem(row, 1, QTableWidgetItem(r.get("title_keyword", "")))
            self.rules_table.setItem(row, 2, QTableWidgetItem(r.get("channel", "All")))

            buf_val = r.get("buffer_mins")
            buf_str = f"+{buf_val}m" if (buf_val is not None and buf_val > 0) else "Auto / Default"
            buf_item = QTableWidgetItem(buf_str)
            buf_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.rules_table.setItem(row, 3, buf_item)

            enabled_str = "Yes" if r.get("enabled", True) else "No"
            enabled_item = QTableWidgetItem(enabled_str)
            enabled_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.rules_table.setItem(row, 4, enabled_item)

    def add_rule_dialog(self):
        channels = self.config_mgr.get_ordered_channels()
        dlg = AddRuleDialog(channels, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            kw = dlg.keyword_input.text().strip()
            ch = dlg.channel_combo.currentText()
            buf = dlg.buffer_spin.value()
            rule_buf = buf if buf > 0 else None
            if kw:
                self.rules_engine.add_rule(kw, ch, buffer_mins=rule_buf)
                self.refresh_rules()
                self.tabs.setCurrentIndex(1)
                if hasattr(self, "recordings_subtabs"):
                    self.recordings_subtabs.setCurrentIndex(1)
                self.run_rules(silent=False)

    def edit_rule_dialog(self):
        row = self.rules_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Selection Required", "Please select a rule from the table to edit.")
            return

        rule_id = self.rules_table.item(row, 0).text()
        current_kw = self.rules_table.item(row, 1).text()
        current_ch = self.rules_table.item(row, 2).text()
        current_enabled = self.rules_table.item(row, 4).text() == "Yes"

        rule_obj = next((r for r in self.rules_engine.get_rules() if str(r.get("id")) == rule_id), {})
        current_buffer = rule_obj.get("buffer_mins")

        channels = self.config_mgr.get_ordered_channels()
        dlg = EditRuleDialog(
            channels=channels,
            rule_id=rule_id,
            keyword=current_kw,
            channel=current_ch,
            enabled=current_enabled,
            buffer_mins=current_buffer,
            parent=self
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_kw = dlg.keyword_input.text().strip()
            new_ch = dlg.channel_combo.currentText()
            new_enabled = dlg.enabled_check.isChecked()
            buf = dlg.buffer_spin.value()
            new_buffer = buf if buf > 0 else None
            if new_kw:
                self.rules_engine.update_rule(
                    rule_id=rule_id,
                    title_keyword=new_kw,
                    channel=new_ch,
                    enabled=new_enabled,
                    buffer_mins=new_buffer
                )
                self.refresh_rules()
                self.status_bar.showMessage(f"Rule '{new_kw}' updated.", 4000)
                if new_enabled:
                    self.run_rules(silent=True)

    def remove_selected_rule(self):
        row = self.rules_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Selection Required", "Please select a rule to remove.")
            return
        rule_id = self.rules_table.item(row, 0).text()
        self.rules_engine.remove_rule(rule_id)
        self.refresh_rules()

    def run_rules(self, silent: bool = False):
        if not silent:
            self.status_bar.showMessage("Evaluating rules against guide data...")
        self.rules_worker = RulesWorker(self.rules_engine)
        self.rules_worker.progress.connect(lambda msg: self.status_bar.showMessage(msg))
        self.rules_worker.finished.connect(lambda scheduled, err: self.on_rules_finished(scheduled, err, silent))
        self.rules_worker.finished.connect(self.rules_worker.deleteLater)
        self.rules_worker.start()

    def on_rules_finished(self, scheduled: list, error: str, silent: bool):
        if error:
            if not silent:
                QMessageBox.critical(self, "Rules Error", error)
        else:
            msg = f"Rule check completed. {len(scheduled)} new recordings scheduled."
            self.status_bar.showMessage(msg, 5000)
            if scheduled:
                self.watcher.check_and_dispatch(notify=False)
                self.refresh_recordings()
                if not silent:
                    details = "\n".join([f"- {s['title']} ({s['channel']} at {s['start_time']})" for s in scheduled])
                    QMessageBox.information(self, "New Recordings Scheduled", f"Scheduled {len(scheduled)} shows:\n\n{details}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            has_sel = (
                getattr(self, "selected_grid_program", None) is not None
                or (hasattr(self, "guide_grid_table") and bool(self.guide_grid_table.selectedItems()))
                or (hasattr(self, "guide_table") and bool(self.guide_table.selectedItems()))
            )
            if has_sel:
                self.clear_guide_selection()
                event.accept()
                return
            if getattr(self, "_guide_maximized", False):
                self.toggle_guide_maximized()
                event.accept()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        try:
            self.settings.setValue("geometry", self.saveGeometry())
            self._auto_save_automation_settings()
            if hasattr(self, "config_mgr"):
                if hasattr(self, "_guide_maximized"):
                    self.config_mgr.guide_maximized = bool(self._guide_maximized)
                self.config_mgr.save()
            if hasattr(self, "_timeshift_poll_timer") and self._timeshift_poll_timer.isActive():
                self._timeshift_poll_timer.stop()
            if hasattr(self, "_clock_timer") and self._clock_timer.isActive():
                self._clock_timer.stop()
            if hasattr(self, "_guide_realtime_timer") and self._guide_realtime_timer.isActive():
                self._guide_realtime_timer.stop()
            if hasattr(self, "_save_indicator_timer") and self._save_indicator_timer and self._save_indicator_timer.isActive():
                self._save_indicator_timer.stop()

            # Cleanly disconnect and terminate all active background workers
            worker_names = (
                "_initial_notes_worker",
                "health_worker",
                "sync_worker",
                "rules_worker",
                "update_check_worker",
                "update_apply_worker",
            )
            for w_name in worker_names:
                w = getattr(self, w_name, None)
                if w and hasattr(w, "isRunning") and w.isRunning():
                    try:
                        w.disconnect()
                    except Exception:
                        pass
                    try:
                        w.quit()
                        w.wait(200)
                    except Exception:
                        pass

            if getattr(self, "_active_timeshift", None):
                self.stop_timeshift_session(user_initiated=False)
        except Exception:
            pass
        super().closeEvent(event)


def ensure_desktop_launcher():
    """Ensure kaffeine-dvr.desktop exists in user applications directory."""
    try:
        import shutil
        import subprocess
        from pathlib import Path

        xdg_data = os.environ.get("XDG_DATA_HOME")
        apps_dir = (Path(xdg_data) if xdg_data else Path.home() / ".local" / "share") / "applications"
        desktop_file = apps_dir / "kaffeine-dvr.desktop"

        content = (
            "[Desktop Entry]\n"
            "Categories=AudioVideo;TV;Recorder;\n"
            "Comment=Modern TV Guide & DVR Recording Manager for Kaffeine\n"
            "Exec=sh -c 'PATH=\"$HOME/.local/bin:$PATH\" exec kaffeine-dvr'\n"
            "GenericName=TV Guide & Recording Manager\n"
            "Icon=kaffeine-dvr\n"
            "Keywords=tv;dvr;kaffeine;record;guide;epg;\n"
            "Name=Kaffeine DVR & TV Guide\n"
            "StartupNotify=true\n"
            "StartupWMClass=kaffeine-dvr\n"
            "Terminal=false\n"
            "Type=Application\n"
        )
        needs_write = not desktop_file.exists()
        if not needs_write:
            try:
                curr = desktop_file.read_text(encoding="utf-8")
                if "Icon=kaffeine\n" in curr or "Icon=kaffeine" == curr.strip():
                    needs_write = True
            except Exception:
                needs_write = True

        if needs_write:
            apps_dir.mkdir(parents=True, exist_ok=True)
            desktop_file.write_text(content, encoding="utf-8")
            if shutil.which("update-desktop-database"):
                subprocess.run(
                    ["update-desktop-database", str(apps_dir)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False
                )
    except Exception:
        pass


def resolve_systemd_exec_start() -> str:
    """Resolve the appropriate ExecStart command line for the background watcher service."""
    import shutil
    from pathlib import Path

    # 1. Prefer local binary (~/.local/bin/kaffeine-dvr) so development tweaks take effect immediately
    local_bin = Path.home() / ".local" / "bin" / "kaffeine-dvr"
    if local_bin.is_file():
        return "%h/.local/bin/kaffeine-dvr --watch"

    # 2. If running inside an AppImage and no local binary exists, use the AppImage
    appimage_path = os.environ.get("APPIMAGE")
    if appimage_path and Path(appimage_path).is_file():
        return f'"{Path(appimage_path).resolve()}" --watch'

    cmd = shutil.which("kaffeine-dvr")
    if cmd:
        return f'"{cmd}" --watch'

    try:
        repo_root = Path(__file__).resolve().parent.parent
        cli_file = repo_root / "kaffeine_dvr" / "cli.py"
        if cli_file.is_file():
            return f'"{sys.executable}" "{cli_file}" --watch'
    except Exception:
        pass

    return f'"{sys.executable}" -m kaffeine_dvr.cli --watch'


def ensure_systemd_service(force: bool = False) -> bool:
    """Ensure kaffeine-dvr-watcher.service unit file exists in user systemd directory."""
    try:
        import subprocess
        from pathlib import Path

        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg_config) if xdg_config else Path.home() / ".config"
        service_dir = base / "systemd" / "user"
        service_file = service_dir / "kaffeine-dvr-watcher.service"

        exec_start = resolve_systemd_exec_start()
        unit_content = (
            "[Unit]\n"
            "Description=Kaffeine DVR Background Watcher (Just-In-Time Dispatcher)\n"
            "After=network.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={exec_start}\n"
            "Restart=on-failure\n"
            "RestartSec=10\n"
            "Environment=\"PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin\"\n"
            "Environment=\"PYTHONUNBUFFERED=1\"\n"
            "Environment=\"XDG_CURRENT_DESKTOP=KDE\"\n"
            "Environment=\"KDE_FULL_SESSION=true\"\n"
            "Environment=\"KDE_SESSION_VERSION=6\"\n"
            "Environment=\"DESKTOP_SESSION=plasma.desktop\"\n"
            "StandardOutput=journal\n"
            "StandardError=journal\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )

        needs_write = force or (not service_file.exists())
        if not needs_write:
            try:
                current_text = service_file.read_text(encoding="utf-8")
                if current_text.strip() != unit_content.strip():
                    needs_write = True
            except Exception:
                needs_write = True

        if needs_write:
            service_dir.mkdir(parents=True, exist_ok=True)
            service_file.write_text(unit_content, encoding="utf-8")
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
        return True
    except Exception as e:
        print(f"Error ensuring systemd service: {e}")
        return False


def main():
    cli_flags = ["--watch", "--sync", "--rules", "--list", "--status", "--help", "-h"]
    if any(arg in sys.argv for arg in cli_flags):
        try:
            from .cli import main as cli_main
        except (ImportError, ValueError):
            from kaffeine_dvr.cli import main as cli_main
        cli_main()
        return

    app = QApplication(sys.argv)
    ensure_desktop_launcher()
    ensure_systemd_service()
    wheel_filter = NoWheelEventFilter(app)
    app.installEventFilter(wheel_filter)
    app.setApplicationName("kaffeine-dvr")
    app.setApplicationDisplayName("Kaffeine DVR & TV Guide")
    app.setDesktopFileName("kaffeine-dvr")
    app.setWindowIcon(get_app_icon())
    setup_dark_theme(app)
    window = MainWindow()
    window.show()
    ret = app.exec()
    try:
        app.removeEventFilter(wheel_filter)
    except Exception:
        pass
    os._exit(ret)


if __name__ == "__main__":
    main()
