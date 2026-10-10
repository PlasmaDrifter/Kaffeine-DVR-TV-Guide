import os
import re
import sys
import time
import html
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QTextEdit, QHeaderView,
    QMessageBox, QDialog, QFormLayout, QSpinBox, QCheckBox,
    QProgressBar, QStatusBar, QFrame, QGroupBox, QFileDialog,
    QScrollArea, QToolButton, QSizePolicy, QAbstractSpinBox, QSlider,
    QStackedWidget, QButtonGroup, QStyledItemDelegate, QStyleOptionViewItem,
    QStyle, QListWidget, QListWidgetItem, QAbstractItemView, QToolTip,
    QLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings, QByteArray, QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QWheelEvent, QPainter, QPalette, QPixmap, QPen, QPolygon, QBrush

try:
    from .config import ConfigManager, DEFAULT_CHANNEL_MAP
    from .dbus_client import KaffeineDbusClient
    from .guide_service import GuideService
    from .rules_engine import RulesEngine
    from .queue_manager import QueueManager
    from .watcher import Watcher
    from .storage_manager import StorageManager
except (ImportError, ValueError):
    from kaffeine_dvr.config import ConfigManager, DEFAULT_CHANNEL_MAP
    from kaffeine_dvr.dbus_client import KaffeineDbusClient
    from kaffeine_dvr.guide_service import GuideService
    from kaffeine_dvr.rules_engine import RulesEngine
    from kaffeine_dvr.queue_manager import QueueManager
    from kaffeine_dvr.watcher import Watcher
    from kaffeine_dvr.storage_manager import StorageManager


def _get_checkmark_icon_path() -> str:
    # First check relative to this source tree
    base_dir = Path(__file__).resolve().parent.parent
    asset_path = base_dir / "assets" / "checkmark.png"
    if not asset_path.parent.exists():
        try:
            asset_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    # If not writable or not found, fallback to user config/cache directory
    if not asset_path.exists():
        try:
            pix = QPixmap(14, 14)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor('#ffffff'), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawLine(2, 7, 5, 11)
            p.drawLine(5, 11, 12, 3)
            p.end()
            pix.save(str(asset_path), 'PNG')
        except Exception:
            # Fallback location in user home
            fallback_dir = Path.home() / ".config" / "kaffeine-dvr" / "assets"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            asset_path = fallback_dir / "checkmark.png"
            if not asset_path.exists():
                try:
                    pix = QPixmap(14, 14)
                    pix.fill(Qt.GlobalColor.transparent)
                    p = QPainter(pix)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    pen = QPen(QColor('#ffffff'), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                    p.setPen(pen)
                    p.drawLine(2, 7, 5, 11)
                    p.drawLine(5, 11, 12, 3)
                    p.end()
                    pix.save(str(asset_path), 'PNG')
                except Exception:
                    pass
    return str(asset_path).replace("\\", "/")


def get_checkmark_icon_path() -> str:
    global _CACHED_CHECKMARK_PATH
    if _CACHED_CHECKMARK_PATH is None:
        _CACHED_CHECKMARK_PATH = _get_checkmark_icon_path()
    return _CACHED_CHECKMARK_PATH

_CACHED_CHECKMARK_PATH = None


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
        except Exception as e:
            self.finished.emit({})


class ManualRecordDialog(QDialog):
    def __init__(self, channels: List[str], parent=None, default_buffer_mins: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Schedule Manual Recording")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)

        self.title_input = QLineEdit()
        self.channel_combo = QComboBox()
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


class AddRuleDialog(QDialog):
    def __init__(self, channels: List[str], parent=None, default_title: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Add Auto-Record Rule")
        self.setMinimumWidth(380)
        layout = QFormLayout(self)

        self.keyword_input = QLineEdit(default_title)
        self.channel_combo = QComboBox()
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


class EditRuleDialog(QDialog):
    def __init__(self, channels: List[str], rule_id: str, keyword: str, channel: str, enabled: bool, buffer_mins: Optional[int] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Auto-Record Rule")
        self.setMinimumWidth(380)
        layout = QFormLayout(self)

        self.rule_id_lbl = QLabel(f"<b>{rule_id}</b>")
        self.keyword_input = QLineEdit(keyword)
        self.channel_combo = QComboBox()
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


class HelpPopup(QFrame):
    """Clean popover displaying setting help text on click, dismissing on click outside."""
    _active_popup = None

    def __init__(self, text: str, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: 500; line-height: 1.4; background: transparent;")
        lay.addWidget(lbl)
        self.setStyleSheet(
            "HelpPopup {"
            "  background-color: #1e293b;"
            "  border: 1.5px solid #38bdf8;"
            "  border-radius: 8px;"
            "}"
        )
        # Accurately compute needed width and height so box fits the text
        font = QFont(lbl.font())
        font.setPixelSize(14)
        font.setWeight(QFont.Weight.Medium)
        fm = QFontMetrics(font)
        max_line_width = max((fm.horizontalAdvance(line) for line in text.splitlines()), default=200)
        content_width = min(420, max(240, max_line_width))
        text_rect = fm.boundingRect(QRect(0, 0, content_width, 10000), Qt.TextFlag.TextWordWrap, text)
        self.setFixedSize(content_width + 28, text_rect.height() + 24)

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
    """White circular '?' badge that displays help info popover on click."""
    def __init__(self, tooltip_text: str, parent=None):
        super().__init__("?", parent)
        self._tooltip_text = tooltip_text
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setStyleSheet(
            "QLabel {"
            "  color: #ffffff;"
            "  background-color: #1e293b;"
            "  border: 1px solid #64748b;"
            "  border-radius: 8px;"
            "  font-weight: bold;"
            "  font-size: 11px;"
            "  min-width: 16px;"
            "  max-width: 16px;"
            "  min-height: 16px;"
            "  max-height: 16px;"
            "  qproperty-alignment: AlignCenter;"
            "}"
            "QLabel:hover {"
            "  color: #ffffff;"
            "  background-color: #334155;"
            "  border-color: #94a3b8;"
            "}"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
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
    lay.addWidget(badge)
    lay.addWidget(lbl)
    lay.addStretch()
    return w


class AdjustBufferDialog(QDialog):
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
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

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


class CollapsibleSection(QWidget):
    def __init__(self, title: str = "", initially_expanded: bool = False, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 4, 0, 4)
        self.main_layout.setSpacing(4)

        self.header_layout = QHBoxLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(8)

        self.toggle_btn = QToolButton()
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


def classify_guide_category(prog: Dict[str, Any]) -> str:
    """
    Classifies a program into 'sports', 'news', 'movies', or 'tvshows'.
    Color mapping:
    - Sports: Orange (#ffa028)
    - News: Blue (#4fc3f7)
    - Movies: Red (#ff5c5c)
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


class ProgramTileDelegate(QStyledItemDelegate):
    """
    Custom item delegate for rendering traditional EPG grid program tiles.
    - Flawlessly aligns multi-line text flush to the left edge with uniform padding.
    - Colors show titles: Sports = Orange (#ffa028), News = Blue (#4fc3f7), Movies = Red (#ff5c5c), TV Shows = Green (#66bb6a).
    - Subtext displays time range and episode title with high legibility.
    """
    COLOR_SELECTED_BG = QColor("#2b3e4f")
    COLOR_SELECTED_BORDER_SCHED = QColor("#ff5252")
    COLOR_SELECTED_BORDER = QColor("#38bdf8")
    COLOR_DEFAULT_BG = QColor("#222838")
    COLOR_DEFAULT_BG_ALT = QColor("#1e2332")
    COLOR_PAST_BG = QColor("#161922")
    COLOR_PAST_BG_ALT = QColor("#14171f")
    COLOR_LIVE_BG = QColor("#17261c")
    COLOR_DEFAULT_BORDER_SCHED = QColor("#e53935")
    COLOR_DEFAULT_BORDER = QColor("#333c4e")
    COLOR_PAST_BORDER = QColor("#262c3a")
    COLOR_PAST_BORDER_SCHED = QColor("#8b0000")
    COLOR_REC_BADGE_PEN = QColor("#e53935")
    COLOR_REC_BADGE_BRUSH = QColor("#b71c1c")
    COLOR_LIVE_DOT = QColor("#66bb6a")
    COLOR_WHITE = QColor("#ffffff")
    COLOR_UPCOMING_TITLE = QColor("#f1f5f9")
    COLOR_PAST_TITLE = QColor("#788292")
    COLOR_PAST_SUBTEXT = QColor("#5a6474")
    COLOR_LIVE_TITLE = QColor("#66bb6a")
    COLOR_SUBTEXT = QColor("#a4b0c2")

    CATEGORY_COLORS = {
        "sports": QColor("#ffa028"),
        "news": QColor("#4fc3f7"),
        "movies": QColor("#ff5c5c"),
        "tvshows": QColor("#f1f5f9"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom_delta = 0

    def set_zoom_delta(self, delta: int):
        self.zoom_delta = delta

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        prog = index.data(Qt.ItemDataRole.UserRole)
        if not prog:
            super().paint(painter, option, index)
            return

        painter.save()
        rect = option.rect

        # Timing state & metadata
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_scheduled = bool(prog.get("_scheduled_rec"))
        timing_state = prog.get("_timing_state")
        if not timing_state:
            start_iso = prog.get("start_iso")
            dur_iso = prog.get("duration_iso") or "00:30:00"
            if start_iso:
                try:
                    dt = datetime.fromisoformat(start_iso)
                    parts = [int(x) for x in dur_iso.split(":")]
                    dur = timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2] if len(parts) > 2 else 0)
                    now = datetime.now()
                    if now >= dt + dur:
                        timing_state = "past"
                    elif dt <= now < dt + dur:
                        timing_state = "live"
                    else:
                        timing_state = "upcoming"
                except Exception:
                    timing_state = "upcoming"
            else:
                timing_state = "upcoming"

        # Background fill & border styling
        is_alt = (index.row() % 2 == 1)
        if is_selected:
            bg_color = self.COLOR_SELECTED_BG
            border_color = self.COLOR_SELECTED_BORDER_SCHED if is_scheduled else self.COLOR_SELECTED_BORDER
            pen_width = 2
        else:
            pen_width = 1
            if timing_state == "past":
                bg_color = self.COLOR_PAST_BG_ALT if is_alt else self.COLOR_PAST_BG
                border_color = self.COLOR_PAST_BORDER_SCHED if is_scheduled else self.COLOR_PAST_BORDER
            elif timing_state == "live":
                bg_color = self.COLOR_LIVE_BG
                border_color = self.COLOR_DEFAULT_BORDER_SCHED if is_scheduled else self.COLOR_DEFAULT_BORDER
            else:
                bg_color = self.COLOR_DEFAULT_BG_ALT if is_alt else self.COLOR_DEFAULT_BG
                border_color = self.COLOR_DEFAULT_BORDER_SCHED if is_scheduled else self.COLOR_DEFAULT_BORDER

        painter.fillRect(rect, bg_color)
        painter.setPen(QPen(border_color, pen_width))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        # Uniform padding inside box
        pad_left = 10
        pad_top = 8
        pad_right = 10
        inner_width = max(10, rect.width() - pad_left - pad_right)

        # Draw Badges (REC badge in upper right corner if scheduled)
        badge_reserved_w = 0
        cur_right = rect.right() - pad_right

        if is_scheduled:
            badge_font = QFont(option.font)
            badge_font.setBold(True)
            badge_font.setPointSize(7)
            painter.setFont(badge_font)
            fm_badge = painter.fontMetrics()

            rec_text = "REC"
            rec_w = fm_badge.horizontalAdvance(rec_text)
            pad_h = 6
            bw = rec_w + (pad_h * 2)
            bh = 15

            bx = cur_right - bw
            by = rect.top() + pad_top
            badge_rect = QRect(bx, by, bw, bh)

            painter.setPen(self.COLOR_REC_BADGE_PEN)
            painter.setBrush(self.COLOR_REC_BADGE_BRUSH)
            painter.drawRoundedRect(badge_rect, 4, 4)

            painter.setPen(self.COLOR_WHITE)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, rec_text)

            cur_right -= (bw + 5)
            badge_reserved_w += (bw + 5)

        # Title & Subtext color logic (Option 1)
        cat = prog.get("_category") or classify_guide_category(prog)
        if timing_state == "past":
            title_color = self.COLOR_PAST_TITLE
            subtext_color = self.COLOR_PAST_SUBTEXT
        elif timing_state == "live":
            if cat in ("sports", "news", "movies"):
                title_color = self.CATEGORY_COLORS[cat]
            else:
                title_color = self.COLOR_LIVE_TITLE
            subtext_color = self.COLOR_SUBTEXT
        else:
            title_color = self.CATEGORY_COLORS.get(cat, self.COLOR_UPCOMING_TITLE)
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
        line1_rect = QRect(rect.left() + pad_left, rect.top() + pad_top, inner_width_title, fm_title.height())
        painter.drawText(line1_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

        # Line 2: Time Range & Subtitle
        font_sub = QFont(option.font)
        font_sub.setBold(False)
        font_sub.setPointSize(max(7, 9 + self.zoom_delta))
        painter.setFont(font_sub)
        painter.setPen(subtext_color)

        fm_sub = painter.fontMetrics()
        subtext = f"{time_range} • {secondary_sub}" if secondary_sub else time_range
        elided_sub = fm_sub.elidedText(subtext, Qt.TextElideMode.ElideRight, inner_width)
        line2_rect = QRect(rect.left() + pad_left, rect.top() + pad_top + fm_title.height() + 4, inner_width, fm_sub.height())
        painter.drawText(line2_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_sub)

        painter.restore()


class GridPanFilter(QObject):
    """
    Event filter installed on the guide grid table viewport to support
    mouse grab-and-drag panning/scrolling while preserving cell click selection.
    """
    def __init__(self, table: QTableWidget, parent=None):
        super().__init__(parent or table)
        self.table = table
        self._dragging = False
        self._drag_start_pos = None
        self._last_drag_pos = None
        self._drag_threshold = 5
        self._set_cursor(Qt.CursorShape.OpenHandCursor)

    def _set_cursor(self, shape: Qt.CursorShape):
        try:
            self.table.viewport().setCursor(shape)
            hdr = self.table.horizontalHeader()
            if hdr and hdr.viewport():
                hdr.viewport().setCursor(shape)
        except (RuntimeError, AttributeError):
            pass

    def eventFilter(self, watched, event):
        try:
            vp = self.table.viewport()
            hdr = self.table.horizontalHeader()
            hdr_vp = hdr.viewport() if hdr else None
        except (RuntimeError, AttributeError):
            return False

        if watched not in (vp, hdr_vp):
            return super().eventFilter(watched, event)

        evt_type = event.type()

        if evt_type == QEvent.Type.MouseButtonPress:
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
                self._dragging = False
                pos = event.position().toPoint()
                self._drag_start_pos = pos
                self._last_drag_pos = pos
                return False
            elif self._dragging:
                return True

        elif evt_type == QEvent.Type.MouseMove:
            if self._drag_start_pos is not None:
                # If neither left nor middle button is held down, end drag
                if not (event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.MiddleButton)):
                    was_drag = self._dragging
                    self._dragging = False
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
                        h_bar.setValue(h_bar.value() - delta.x())
                    if delta.y() != 0 and v_bar and watched is vp:
                        v_bar.setValue(v_bar.value() - delta.y())
                    return True

        elif evt_type == QEvent.Type.MouseButtonRelease:
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
                was_dragging = self._dragging
                self._dragging = False
                self._drag_start_pos = None
                self._last_drag_pos = None
                self._set_cursor(Qt.CursorShape.OpenHandCursor)
                if was_dragging:
                    return True
                return False

        elif evt_type in (QEvent.Type.FocusOut, QEvent.Type.WindowDeactivate):
            self._dragging = False
            self._drag_start_pos = None
            self._last_drag_pos = None
            self._set_cursor(Qt.CursorShape.OpenHandCursor)

        elif evt_type == QEvent.Type.Enter:
            if not self._dragging:
                self._set_cursor(Qt.CursorShape.OpenHandCursor)

        return super().eventFilter(watched, event)


class UpcomingShowDialog(QDialog):
    ACTION_CANCEL = 0
    ACTION_RECORD = 1
    ACTION_TUNE = 2

    def __init__(self, prog: Dict[str, Any], timing_info: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Upcoming Program")
        self.setMinimumWidth(460)
        self.action = self.ACTION_CANCEL

        title = prog.get("show_title") or prog.get("title") or "Selected Program"
        ep = prog.get("episode_title")
        ch = prog.get("kaffeine_channel", "")
        time_desc = timing_info.get("time_desc", "")
        start_fmt = timing_info.get("start_fmt", "")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header_lbl = QLabel(f"<b>{title}</b>")
        header_lbl.setStyleSheet("font-size: 15px; color: #66bb6a;")
        layout.addWidget(header_lbl)

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

        record_btn = QPushButton("Schedule Recording")
        record_btn.setStyleSheet("font-weight: bold; background-color: #212635; color: #ffffff; padding: 6px 12px;")
        record_btn.setDefault(True)
        record_btn.clicked.connect(self._on_record)
        btn_layout.addWidget(record_btn)

        tune_btn = QPushButton("Tune Channel Now")
        tune_btn.setStyleSheet("padding: 6px 12px;")
        tune_btn.clicked.connect(self._on_tune)
        btn_layout.addWidget(tune_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _on_record(self):
        self.action = self.ACTION_RECORD
        self.accept()

    def _on_tune(self):
        self.action = self.ACTION_TUNE
        self.accept()


class FirstRunWelcomeDialog(QDialog):
    def __init__(self, config_mgr: ConfigManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Kaffeine DVR & TV Guide")
        self.setFixedWidth(730)
        self.config_mgr = config_mgr
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #191c28;
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

        title_lbl = QLabel("Welcome to Kaffeine DVR & TV Guide")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        title_lbl.setStyleSheet("font-size: 19px; font-weight: bold; color: #ffffff; padding: 2px 0 2px 0; background: transparent;")
        layout.addWidget(title_lbl)

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
            "    Find station IDs on <a href='https://www.tvpassport.com' style='color: #93c5fd; font-weight: bold; text-decoration: none;'>tvpassport.com</a> "
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
                f"  Configure their numeric station ID on <a href='https://www.tvpassport.com' style='color: #93c5fd; font-weight: bold; text-decoration: none;'>tvpassport.com</a> "
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
    for name in ["kaffeine", "org.kde.kaffeine", "video-television", "media-playback-start"]:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QIcon()


APP_STYLESHEET = """
/* Base Application & Window Styling */
QWidget {
    background-color: #191c28;
    color: #dce1e8;
    font-size: 13px;
}

QMainWindow, QDialog {
    background-color: #191c28;
    color: #dce1e8;
}

QMessageBox {
    background-color: #191c28;
    color: #dce1e8;
}

QMenu {
    background-color: #1c202e;
    color: #e0e6ed;
    border: 1px solid #333a4c;
    padding: 4px;
}
QMenu::item:selected {
    background-color: #2b3346;
    color: #ffffff;
}

/* Default Form Controls */
QLineEdit, QTextEdit, QSpinBox, QComboBox {
    background-color: #12141d;
    border: 1px solid #333a4c;
    border-radius: 4px;
    color: #e4e9f0;
    padding: 5px 8px;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #4a8df5;
}

/* Buttons */
QPushButton {
    background-color: #272d3d;
    border: 1px solid #3c465d;
    border-radius: 5px;
    color: #e0e6ed;
    padding: 6px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #333a50;
    border-color: #4f5b79;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #1e2330;
}
QPushButton:disabled {
    background-color: #181b24;
    color: #5a6475;
    border-color: #252b38;
}

/* Primary Action Buttons */
QPushButton#primaryActionBtn {
    background-color: #2d6cd4;
    border: 1px solid #4a8df5;
    color: #ffffff;
    font-weight: bold;
}
QPushButton#primaryActionBtn:hover {
    background-color: #3b7ee8;
}
QPushButton#primaryActionBtn:pressed {
    background-color: #2259b3;
}

/* Checkboxes */
QCheckBox {
    color: #dce1e8;
    spacing: 8px;
    background: transparent;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #3d465c;
    border-radius: 3px;
    background-color: #13151f;
}
QCheckBox::indicator:hover {
    border-color: #505c75;
}
QCheckBox::indicator:checked {
    background-color: #2d6cd4;
    border-color: #4a8df5;
    image: url("__CHECKMARK_ICON_PATH__");
}
QCheckBox::indicator:checked:disabled {
    background-color: #238636;
    border-color: #2ea043;
    image: url("__CHECKMARK_ICON_PATH__");
}

/* Top-Level Main Tabs: Option 4 Browser-Style Curved / Flowing Tabs */
QTabWidget#mainTabs::pane {
    border: 1px solid #3d465c;
    border-top: 1.5px solid #4a5570;
    border-radius: 8px;
    background-color: #191c28;
    top: -1px;
}
QTabWidget#mainTabs > QTabBar {
    background: transparent;
}
QTabWidget#mainTabs > QTabBar::tab {
    background-color: transparent;
    border: 1px solid transparent;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    padding: 9px 24px 8px 24px;
    margin-right: 4px;
    margin-top: 5px;
    color: #8c9bb0;
    font-size: 13px;
    font-weight: 500;
}
QTabWidget#mainTabs > QTabBar::tab:selected {
    background-color: #191c28;
    border: 1px solid #3d465c;
    border-bottom: 2px solid #191c28;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    margin-top: 0px;
    padding-top: 11px;
    padding-bottom: 9px;
    color: #ffffff;
    font-weight: bold;
}
QTabWidget#mainTabs > QTabBar::tab:hover:!selected {
    background-color: #212637;
    border: 1px solid #2f374a;
    border-bottom: none;
    color: #d8e2ee;
}

/* Secondary Subtabs: Curved Flowing Subtabs */
QTabWidget#recordingsSubTabs::pane,
QTabWidget#settingsSubTabs::pane {
    border: 1px solid #323a4d;
    border-top: 1.5px solid #3f4961;
    border-radius: 6px;
    background-color: #151822;
    padding: 6px;
    top: -1px;
}
QTabWidget#recordingsSubTabs > QTabBar::tab,
QTabWidget#settingsSubTabs > QTabBar::tab {
    background-color: transparent;
    border: 1px solid transparent;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    padding: 6px 18px 5px 18px;
    margin-right: 4px;
    margin-top: 3px;
    color: #8896aa;
    font-size: 12px;
    font-weight: 500;
}
QTabWidget#recordingsSubTabs > QTabBar::tab:selected,
QTabWidget#settingsSubTabs > QTabBar::tab:selected {
    background-color: #151822;
    border: 1px solid #323a4d;
    border-bottom: 2px solid #151822;
    margin-top: 0px;
    padding-top: 8px;
    color: #ffffff;
    font-weight: bold;
}
QTabWidget#recordingsSubTabs > QTabBar::tab:hover:!selected,
QTabWidget#settingsSubTabs > QTabBar::tab:hover:!selected {
    background-color: #1e2332;
    border: 1px solid #2a3142;
    border-bottom: none;
    color: #d1dbe7;
}

/* Scroll area background inside settings */
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {
    background-color: #171a26;
    border: none;
}

/* Group Boxes */
QGroupBox {
    border: 1px solid #333a4c;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: bold;
    font-size: 13px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #d3dae3;
    font-size: 13px;
}

/* High-Visibility Custom Scrollbars */
QScrollBar:vertical {
    border: 1px solid #2a3040;
    background: #141722;
    width: 14px;
    margin: 0px;
    border-radius: 7px;
}
QScrollBar::handle:vertical {
    background: #4a5568;
    min-height: 28px;
    border-radius: 6px;
    border: 1px solid #5a667d;
}
QScrollBar::handle:vertical:hover {
    background: #55a84c;
    border: 1px solid #68c75e;
}
QScrollBar::handle:vertical:pressed {
    background: #43873c;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    border: 1px solid #2a3040;
    background: #141722;
    height: 14px;
    margin: 0px;
    border-radius: 7px;
}
QScrollBar::handle:horizontal {
    background: #4a5568;
    min-width: 28px;
    border-radius: 6px;
    border: 1px solid #5a667d;
}
QScrollBar::handle:horizontal:hover {
    background: #55a84c;
    border: 1px solid #68c75e;
}
QScrollBar::handle:horizontal:pressed {
    background: #43873c;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}

/* Channel Order List Widget */
QListWidget#channelOrderList {
    background-color: #141722;
    border: 1px solid #323b4e;
    border-radius: 6px;
    padding: 4px;
    font-size: 13px;
}
QListWidget#channelOrderList::item {
    background-color: #1c2130;
    border: 1px solid #2d3547;
    border-radius: 5px;
    padding: 6px 10px;
    margin-bottom: 3px;
    color: #e0e6ed;
    font-weight: 500;
}
QListWidget#channelOrderList::item:hover {
    background-color: #272f44;
    border-color: #43516f;
}
QListWidget#channelOrderList::item:selected {
    background-color: #2563eb;
    border-color: #3b82f6;
    color: #ffffff;
    font-weight: bold;
}

/* EPG Grid Table Styles */
QTableWidget#guideGridTable {
    background-color: #161922;
    gridline-color: #2b3242;
    border: 1px solid #363c4e;
    border-radius: 4px;
    font-size: 12px;
}
QTableWidget#guideGridTable QHeaderView::section:horizontal {
    background-color: #1e2330;
    color: #9cb0c6;
    font-weight: bold;
    font-size: 11px;
    padding: 6px;
    border: 1px solid #2b3242;
    border-top: none;
}
QTableWidget#guideGridTable QHeaderView::section:vertical {
    background-color: #1e2330;
    color: #ffffff;
    font-weight: bold;
    font-size: 12px;
    padding: 6px 10px;
    border: 1px solid #2b3242;
    border-left: none;
}

/* Modern Status & Progress Bar */
QProgressBar#statusBarProgressBar {
    border: 1px solid #364156;
    border-radius: 6px;
    background-color: #12151e;
    text-align: center;
    color: #ffffff;
    font-size: 11px;
    font-weight: bold;
    min-height: 18px;
    max-height: 18px;
}
QProgressBar#statusBarProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #1d4ed8, stop:0.6 #2563eb, stop:1 #3b82f6);
    border-radius: 5px;
}
"""


def setup_dark_theme(app: Optional[QApplication]):
    if not app:
        return
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#191c28"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e0e6ed"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#13151f"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#191c28"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#222736"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e0e6ed"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#222634"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e0e6ed"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#5b9cf6"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2d6cd4"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#656f82"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#656f82"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#656f82"))
    app.setPalette(palette)
    stylesheet = APP_STYLESHEET.replace("__CHECKMARK_ICON_PATH__", get_checkmark_icon_path())
    app.setStyleSheet(stylesheet)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kaffeine DVR & TV Guide")
        self.setWindowIcon(get_app_icon())
        app_inst = QApplication.instance()
        if app_inst:
            setup_dark_theme(app_inst)

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

        self.config_mgr = ConfigManager()
        self.dbus_client = KaffeineDbusClient()
        self.queue_mgr = QueueManager()
        self.guide_service = GuideService(channel_map=self.config_mgr.channel_map, config_mgr=self.config_mgr)
        self.rules_engine = RulesEngine(self.config_mgr, self.dbus_client, self.guide_service)
        self.watcher = Watcher(self.dbus_client, self.queue_mgr)
        self.storage_mgr = StorageManager(self.config_mgr, self.queue_mgr)
        self.day_nav_offset = 0

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

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Status Banner
        self.status_banner_widget = QWidget()
        self.status_banner_widget.setLayout(self.create_status_banner())
        main_layout.addWidget(self.status_banner_widget)

        # Main Tabs
        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.addTab(self.create_guide_tab(), "Web TV Guide Browser")
        self.tabs.addTab(self.create_recordings_tab(), "Recordings Schedule")
        self.tabs.addTab(self.create_settings_tab(), "Settings")
        self.tabs.addTab(self.create_help_tab(), "Help and Information")
        self.tabs.currentChanged.connect(self._on_main_tab_changed)
        main_layout.addWidget(self.tabs)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("statusBarProgressBar")
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setMinimumWidth(160)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)

    def create_status_banner(self) -> QGridLayout:
        banner = QGridLayout()
        banner.setContentsMargins(0, 0, 0, 0)
        banner.setSpacing(0)

        # Column 0: Far Left Restore Saved Window Size button
        left_container = QWidget()
        left_layout = QHBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.header_restore_btn = QPushButton()
        self.header_restore_btn.setIcon(self._create_restore_window_icon())
        self.header_restore_btn.setIconSize(QSize(16, 16))
        self.header_restore_btn.setFixedSize(28, 26)
        self.header_restore_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.header_restore_btn.setToolTip("Restore saved window dimensions (also accessible in Settings)")
        self.header_restore_btn.setStyleSheet(
            "QPushButton { border: 1px solid #3d465c; border-radius: 4px; background-color: #212635; color: #c8d2df; }"
            "QPushButton:hover { background-color: #313d56; border: 1px solid #5a80b8; }"
            "QPushButton:pressed { background-color: #1a1e2b; }"
        )
        self.header_restore_btn.clicked.connect(self.restore_saved_window_size)
        left_layout.addWidget(self.header_restore_btn)
        left_layout.addStretch()

        banner.addWidget(left_container, 0, 0, Qt.AlignmentFlag.AlignLeft)

        # Column 1: Middle auto-save notification indicator (guaranteed true center)
        self.save_indicator_lbl = QLabel("Changes save automatically")
        self.save_indicator_lbl.setStyleSheet(
            "color: #8c98aa; font-size: 11px; padding: 4px 6px; background: transparent;"
        )
        self.save_indicator_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.addWidget(self.save_indicator_lbl, 0, 1, Qt.AlignmentFlag.AlignCenter)

        # Column 2: Far Right Guide status label and sync button
        right_container = QWidget()
        right_layout = QHBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.guide_status_lbl = QLabel("TV Guide: Checking...")
        self.guide_status_lbl.setStyleSheet("font-size: 12px; color: #a4b0c2; font-weight: 500;")
        right_layout.addWidget(self.guide_status_lbl)

        self.sync_guide_btn = QPushButton("Sync Guide Now")
        self.sync_guide_btn.setStyleSheet(
            "QPushButton { padding: 3px 10px; font-size: 11px; font-weight: 500; "
            "border: 1px solid #3d465c; border-radius: 4px; background-color: #212635; color: #c8d2df; }"
            "QPushButton:hover { background-color: #313d56; border: 1px solid #5a80b8; color: #ffffff; }"
            "QPushButton:pressed { background-color: #1a1e2b; border: 1px solid #353d50; }"
            "QPushButton:disabled { background-color: #1a1c26; border: 1px solid #2a3040; color: #5d6778; }"
        )
        self.sync_guide_btn.clicked.connect(self.sync_guide)
        right_layout.addWidget(self.sync_guide_btn)

        banner.addWidget(right_container, 0, 2, Qt.AlignmentFlag.AlignRight)

        # Guarantee true horizontal centering by making col 0 and col 2 stretch equally
        banner.setColumnStretch(0, 1)
        banner.setColumnStretch(1, 0)
        banner.setColumnStretch(2, 1)

        return banner

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

        self.hist_max_spin = QSpinBox()
        self.hist_max_spin.setRange(5, 500)
        self.hist_max_spin.setSingleStep(5)
        self.hist_max_spin.setValue(self.config_mgr.max_history_entries)
        self.hist_max_spin.setToolTip("Maximum number of completed recording history entries to retain")
        self.hist_max_spin.valueChanged.connect(self.on_max_history_changed)
        hist_ctrl_bar.addWidget(self.hist_max_spin)

        hist_ctrl_bar.addSpacing(16)
        self.clear_hist_entry_btn = QPushButton("Clear Entry")
        self.clear_hist_entry_btn.setToolTip("Remove the selected item from history")
        self.clear_hist_entry_btn.clicked.connect(self.clear_selected_history_entry)
        hist_ctrl_bar.addWidget(self.clear_hist_entry_btn)

        self.clear_all_hist_btn = QPushButton("Clear All")
        self.clear_all_hist_btn.setStyleSheet("color: #d9534f;")
        self.clear_all_hist_btn.setToolTip("Clear all completed recording history")
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
        self.grid_view_btn.setCheckable(True)
        self.list_view_btn = QPushButton("List View")
        self.list_view_btn.setCheckable(True)
        self.guide_view_group.addButton(self.grid_view_btn, 0)
        self.guide_view_group.addButton(self.list_view_btn, 1)

        # Style toggle buttons (subtle outline unselected, calmed/less bright green when selected)
        btn_style = (
            "QPushButton { padding: 4px 12px; font-weight: bold; font-size: 11px; "
            "border: 1px solid #3d465c; border-radius: 4px; background-color: #212635; color: #a4b0c2; }"
            "QPushButton:hover:!checked { background-color: #313d56; border: 1px solid #5a80b8; color: #ffffff; }"
            "QPushButton:checked { background-color: #1e2e1f; border: 1.5px solid #3e7e3d; color: #ffffff; }"
            "QPushButton:checked:hover { background-color: #243725; border: 1.5px solid #478e45; color: #ffffff; }"
        )
        self.grid_view_btn.setStyleSheet(btn_style)
        self.list_view_btn.setStyleSheet(btn_style)

        # Default to Grid View
        saved_view = self.settings.value("guide_view_mode", "grid")
        if saved_view == "list":
            self.list_view_btn.setChecked(True)
        else:
            self.grid_view_btn.setChecked(True)

        self.grid_view_btn.clicked.connect(self._on_guide_view_toggled)
        self.list_view_btn.clicked.connect(self._on_guide_view_toggled)

        filter_bar.addWidget(QLabel("View:"))
        filter_bar.addWidget(self.grid_view_btn)
        filter_bar.addWidget(self.list_view_btn)
        filter_bar.addSpacing(14)

        # Date & Channel Dropdowns immediately to the right of List View
        filter_bar.addWidget(QLabel("Date:"))
        self.guide_date_combo = QComboBox()
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

        filter_bar.addWidget(QLabel("Channel:"))
        self.guide_channel_combo = QComboBox()
        self.guide_channel_combo.addItem("All")
        channels = self.config_mgr.get_ordered_channels()
        self.guide_channel_combo.addItems(channels)
        self.guide_channel_combo.currentIndexChanged.connect(self.filter_guide)
        filter_bar.addWidget(self.guide_channel_combo)

        # Dynamic stretch before Jump and Prime Time buttons
        filter_bar.addStretch(1)

        # Quick Time Jump Controls centrally between Channel dropdown and Search box
        jump_btn_style = (
            "QPushButton { padding: 4px 10px; font-size: 11px; font-weight: 500; "
            "border: 1px solid #3d465c; border-radius: 4px; background-color: #212635; color: #c8d2df; }"
            "QPushButton:hover { background-color: #313d56; border: 1px solid #5a80b8; color: #ffffff; }"
            "QPushButton:pressed { background-color: #1a1e2b; border: 1px solid #353d50; }"
        )
        self.jump_now_btn = QPushButton("Jump to Now")
        self.jump_now_btn.setToolTip("Scroll guide grid to current time")
        self.jump_now_btn.setStyleSheet(jump_btn_style)
        self.jump_now_btn.clicked.connect(self.jump_guide_to_now)
        filter_bar.addWidget(self.jump_now_btn)

        self.jump_prime_btn = QPushButton("Prime Time (7 PM)")
        self.jump_prime_btn.setToolTip("Scroll guide grid to 7:00 PM (19:00) evening prime time")
        self.jump_prime_btn.setStyleSheet(jump_btn_style)
        self.jump_prime_btn.clicked.connect(self.jump_guide_to_primetime)
        filter_bar.addWidget(self.jump_prime_btn)

        # Dynamic stretch before Zoom (+ / -) controls to center between Prime Time and Search
        filter_bar.addStretch(1)

        # Guide Font / Box Size Zoom (+ / -) Controls
        zoom_btn_style = (
            "QPushButton { min-width: 28px; max-width: 28px; min-height: 24px; max-height: 24px; "
            "padding: 0px; font-size: 14px; font-weight: bold; "
            "border: 1px solid #3d465c; border-radius: 4px; background-color: #212635; color: #c8d2df; }"
            "QPushButton:hover { background-color: #313d56; border: 1px solid #5a80b8; color: #ffffff; }"
            "QPushButton:pressed { background-color: #1a1e2b; border: 1px solid #353d50; }"
        )
        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.setToolTip("Decrease guide font and box size")
        self.zoom_out_btn.setStyleSheet(zoom_btn_style)
        self.zoom_out_btn.clicked.connect(self.zoom_out_guide)
        filter_bar.addWidget(self.zoom_out_btn)

        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setToolTip("Increase guide font and box size")
        self.zoom_in_btn.setStyleSheet(zoom_btn_style)
        self.zoom_in_btn.clicked.connect(self.zoom_in_guide)
        filter_bar.addWidget(self.zoom_in_btn)

        # Dynamic stretch after Zoom controls to maintain centering
        filter_bar.addStretch(1)

        # Search box anchored to the far right
        filter_bar.addWidget(QLabel("Search:"))
        self.guide_search_input = QLineEdit()
        self.guide_search_input.setPlaceholderText("Filter shows...")
        self.guide_search_input.setFixedWidth(130)
        self.guide_search_input.textChanged.connect(self.filter_guide)
        filter_bar.addWidget(self.guide_search_input)

        # Maximize Guide Button (toggles maximized full-window guide view)
        max_btn_style = (
            "QPushButton { min-width: 28px; max-width: 28px; min-height: 24px; max-height: 24px; "
            "border: 1px solid #3d465c; border-radius: 4px; background-color: #212635; color: #c8d2df; }"
            "QPushButton:hover { background-color: #313d56; border: 1px solid #5a80b8; color: #ffffff; }"
            "QPushButton:pressed { background-color: #1a1e2b; border: 1px solid #353d50; }"
        )
        self.guide_maximize_btn = QPushButton()
        self.guide_maximize_btn.setToolTip("Maximize guide to fill window")
        self.guide_maximize_btn.setIcon(self._create_guide_maximize_icon())
        self.guide_maximize_btn.setIconSize(QSize(14, 14))
        self.guide_maximize_btn.setStyleSheet(max_btn_style)
        self.guide_maximize_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.guide_maximize_btn.clicked.connect(self.toggle_guide_maximized)
        filter_bar.addWidget(self.guide_maximize_btn)

        layout.addLayout(filter_bar)

        # Guide Views Container (Stacked: 0 = Grid View, 1 = List View)
        self.guide_stack = QStackedWidget()

        # 1. Traditional EPG Grid Table
        self.guide_grid_table = QTableWidget()
        self.guide_grid_table.setObjectName("guideGridTable")
        self.guide_grid_table.setColumnCount(48)
        grid_headers = []
        for h in range(24):
            for m in (0, 30):
                grid_headers.append(f"{h%12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}")
        self.guide_grid_table.setHorizontalHeaderLabels(grid_headers)
        self.guide_grid_table.horizontalHeader().setDefaultSectionSize(165)
        self.guide_grid_table.horizontalHeader().setHighlightSections(False)
        self.guide_grid_table.verticalHeader().setDefaultSectionSize(62)
        self.guide_grid_table.verticalHeader().setHighlightSections(False)
        self.grid_tile_delegate = ProgramTileDelegate(self.guide_grid_table)
        self.guide_grid_table.setItemDelegate(self.grid_tile_delegate)
        self.guide_grid_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.guide_grid_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.guide_grid_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.guide_grid_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.grid_pan_filter = GridPanFilter(self.guide_grid_table)
        self.guide_grid_table.viewport().installEventFilter(self.grid_pan_filter)
        self.guide_grid_table.horizontalHeader().viewport().installEventFilter(self.grid_pan_filter)
        self.guide_grid_table.cellClicked.connect(self.on_grid_cell_clicked)
        self.guide_grid_table.cellDoubleClicked.connect(self.on_grid_cell_double_clicked)
        self.guide_stack.addWidget(self.guide_grid_table)

        # 2. Existing Detailed List Table
        self.guide_table = QTableWidget()
        self.guide_table.setColumnCount(6)
        self.guide_table.setHorizontalHeaderLabels(["REC", "Start Time", "Channel", "Show Title", "Episode Title", "Duration"])
        self.guide_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.guide_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.guide_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.guide_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.guide_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.guide_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.guide_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.guide_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.guide_table.itemSelectionChanged.connect(self.on_guide_selection_changed)
        self.guide_table.itemDoubleClicked.connect(self.on_guide_table_double_clicked)
        self.guide_stack.addWidget(self.guide_table)

        # Initialize guide zoom level from settings (-3 to +5, default 0)
        self.guide_zoom_level = self.settings.value("guide_zoom_level", 0, type=int)
        self._apply_guide_zoom()

        # Set initial stack page
        self.guide_stack.setCurrentIndex(1 if saved_view == "list" else 0)
        self._update_time_jump_buttons_visibility()

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
        self.guide_detail_title = QLabel("Select a program to view details")
        self.guide_detail_title.setStyleSheet("font-weight: bold; font-size: 16px;")
        self.guide_detail_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_layout.addWidget(self.guide_detail_title)

        self.guide_detail_text = QTextEdit()
        self.guide_detail_text.setReadOnly(True)
        font = self.guide_detail_text.font()
        font.setPixelSize(16)
        self.guide_detail_text.setFont(font)
        self.guide_detail_text.setStyleSheet("font-size: 16px; line-height: 1.35; padding: 6px 10px;")
        # Size description box to fit approximately 4 lines of text
        line_height = self.guide_detail_text.fontMetrics().lineSpacing()
        doc_margin = int(self.guide_detail_text.document().documentMargin())
        desc_height = line_height * 4 + doc_margin * 2 + 16
        self.guide_detail_text.setFixedHeight(desc_height)
        detail_layout.addWidget(self.guide_detail_text)

        action_bar = QHBoxLayout()

        self.record_guide_btn = QPushButton("Record This Program")
        self.record_guide_btn.setStyleSheet("font-weight: bold;")
        self.record_guide_btn.clicked.connect(self.record_selected_guide_item)
        action_bar.addWidget(self.record_guide_btn)

        self.cancel_guide_btn = QPushButton("Cancel Recording")
        self.cancel_guide_btn.setStyleSheet("color: #ff5252; font-weight: bold;")
        self.cancel_guide_btn.setVisible(False)
        self.cancel_guide_btn.clicked.connect(self.cancel_selected_guide_recording)
        action_bar.addWidget(self.cancel_guide_btn)

        self.add_rule_guide_btn = QPushButton("Auto-Record This Series")
        self.add_rule_guide_btn.clicked.connect(self.add_rule_from_selected_guide_item)
        action_bar.addWidget(self.add_rule_guide_btn)

        self.watch_guide_btn = QPushButton("Watch Live")
        self.watch_guide_btn.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: #ffffff; padding: 4px 12px;")
        self.watch_guide_btn.setVisible(False)
        self.watch_guide_btn.clicked.connect(self.watch_or_tune_selected_guide_item)
        action_bar.addWidget(self.watch_guide_btn)

        self.adjust_buffer_guide_btn = QPushButton("Adjust Buffer...")
        self.adjust_buffer_guide_btn.setStyleSheet("font-weight: bold;")
        self.adjust_buffer_guide_btn.setVisible(False)
        self.adjust_buffer_guide_btn.clicked.connect(self.record_selected_guide_item)
        action_bar.addWidget(self.adjust_buffer_guide_btn)

        action_bar.addStretch()
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
        self.settings_subtabs.addTab(self.create_settings_automation_tab(), "Automation and DVR")
        self.settings_subtabs.addTab(self.create_settings_channels_tab(), "Channel Source")
        self.settings_subtabs.addTab(self.create_settings_guide_tab(), "Guide Sources and Health")
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

        self.provider_combo = QComboBox()
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
        pass_layout = QVBoxLayout(pass_content)

        pass_instructions = QLabel(
            "<b>24/7 Broadcast Station & Affiliate Guide (TV Passport):</b><br>"
            "TV Passport provides complete 24/7 listings with local affiliate morning-to-night syndicated programming. "
            "Having both TV Passport and TVMaze active together is completely supported: "
            "under Free Hybrid mode, adding a station ID here will automatically supersede national TVMaze data for that specific channel, "
            "giving you full local affiliate listings while TVMaze continues providing automatic national listings for any unmapped channels without duplicates.<br><br>"
            "<b>Instructions:</b><br>"
            "1. Visit <a href='https://www.tvpassport.com' style='color: #64b5f6; font-weight: bold;'>tvpassport.com</a> in your browser and search for your station or city.<br>"
            "2. Select your channel to open its listings page. Look at the web address (URL):<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<code>https://www.tvpassport.com/tv-listings/stations/station/<b>1812</b>/2026-10-07</code><br>"
            "3. The number right after <code>/station/</code> is your station ID (e.g. <b>1812</b>).<br>"
            "4. Enter one mapping per line below using the format: <b>KaffeineChannelName = StationID</b> (e.g. <code>NBC = 1812</code> or <code>CW = 11611</code>).<br><br>"
            "<b>Automatic Sync:</b> When you click <i>Save Station IDs</i>, Kaffeine DVR immediately syncs guide listings in the background without needing a manual sync."
        )
        pass_instructions.setWordWrap(True)
        pass_instructions.setOpenExternalLinks(True)
        pass_instructions.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        pass_instructions.setStyleSheet("color: #cdd6e2; font-size: 13px; line-height: 1.5;")
        pass_layout.addWidget(pass_instructions)

        self.passport_notice = QLabel()
        self.passport_notice.setWordWrap(True)
        self.passport_notice.setOpenExternalLinks(True)
        self.passport_notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        pass_layout.addWidget(self.passport_notice)
        self.update_tvpassport_notice()

        self.passport_stations_text = QTextEdit()
        self.passport_stations_text.setPlaceholderText("Example:\nNBC = 1812\nABC = 4163\nFox = 1809")
        stations_lines = [f"{k} = {v}" for k, v in self.config_mgr.tvpassport_stations.items()]
        self.passport_stations_text.setPlainText("\n".join(stations_lines))
        self.passport_stations_text.setMinimumHeight(200)
        pass_layout.addWidget(self.passport_stations_text)

        save_pass_btn = QPushButton("Save Station IDs")
        save_pass_btn.setObjectName("primaryActionBtn")
        save_pass_btn.clicked.connect(self.save_tvpassport_settings)
        pass_btn_row = QHBoxLayout()
        pass_btn_row.addWidget(save_pass_btn)
        pass_btn_row.addStretch()
        pass_layout.addLayout(pass_btn_row)
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
        self.sd_collapsible = CollapsibleSection("Schedules Direct (Paid Official Gracenote API)", initially_expanded=False)
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

        # Left Panel: Channel & Network Mapping
        map_box = QGroupBox("Guide Network Mapping (Name = Channel)")
        map_layout = QVBoxLayout(map_box)

        self.mapping_text = QTextEdit()
        mapping_str = "\n".join([f"{k} = {v}" for k, v in self.config_mgr.channel_map.items()])
        self.mapping_text.setPlainText(mapping_str)
        self.mapping_text.setMinimumHeight(200)

        # 5-line concise explainer inside the text area
        self.mapping_tip_lbl = QLabel(self.mapping_text)
        self.mapping_tip_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.mapping_tip_lbl.setText(
            "Online guides use network names (e.g. Fox, NBC).<br>"
            "Antennas scan local station callsigns (e.g. KSAZ-HD).<br>"
            "Format: <span style='color: #52b788;'>Guide Name = Tuned Channel</span>.<br>"
            "Example: <span style='color: #52b788;'>Fox = KSAZ-HD</span> connects Fox to your antenna.<br>"
            "If channels in Kaffeine already match, leave as <span style='color: #52b788;'>Fox = Fox</span>."
        )
        self.mapping_tip_lbl.setStyleSheet("color: #8a99ad; font-size: 13px; line-height: 1.5; background: transparent;")
        self.mapping_tip_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        mapping_tip_layout = QHBoxLayout(self.mapping_text)
        mapping_tip_layout.addStretch(1)
        mapping_tip_layout.addWidget(self.mapping_tip_lbl, 1)
        mapping_tip_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        mapping_tip_layout.setContentsMargins(20, 15, 20, 20)

        map_layout.addWidget(self.mapping_text)
        lineup_panels.addWidget(map_box, 1)

        # Right Panel: Interactive Channel Order List
        order_box = QGroupBox("TV Guide Channel Order (Manual Priority)")
        order_layout = QVBoxLayout(order_box)

        desc = QLabel("Reorder rows in your EPG TV Guide using drag-and-drop or the Move Up/Down buttons.")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #8a99ad; font-size: 11px;")
        order_layout.addWidget(desc)

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

        # Bottom Button Row
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

        reset_mapping_btn = QPushButton("Reset to Antenna Defaults")
        reset_mapping_btn.clicked.connect(self.reset_channel_mapping_defaults)
        btn_row.addWidget(reset_mapping_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.refresh_channel_order_list()
        return widget

    def refresh_channel_order_list(self):
        if not hasattr(self, "channel_order_list"):
            return
        self.channel_order_list.blockSignals(True)
        self.channel_order_list.clear()
        ordered = self.config_mgr.get_ordered_channels()
        for idx, ch in enumerate(ordered, 1):
            item = QListWidgetItem(f"{idx}.  {ch}")
            item.setData(Qt.ItemDataRole.UserRole, ch)
            self.channel_order_list.addItem(item)
        self.channel_order_list.blockSignals(False)

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

        self.lead_time_spin = QSpinBox()
        self.lead_time_spin.setRange(1, 60)
        self.lead_time_spin.setValue(self.config_mgr.lead_time_mins)
        self.lead_time_spin.setSuffix(" minutes")
        self.lead_time_spin.setFixedWidth(160)
        dvr_layout.addRow(
            make_setting_label(
                "Just-In-Time Lead Time:",
                "Minutes before show start time to auto-launch Kaffeine and arm recording timer.\n"
                "Keeping this low (e.g. 2-5m) prevents Kaffeine from blocking system reboots and shutdowns."
            ),
            self.lead_time_spin
        )

        self.end_buffer_spin = QSpinBox()
        self.end_buffer_spin.setRange(0, 180)
        self.end_buffer_spin.setValue(self.config_mgr.end_buffer_mins)
        self.end_buffer_spin.setSuffix(" minutes")
        self.end_buffer_spin.setFixedWidth(160)
        dvr_layout.addRow(
            make_setting_label(
                "Default End Buffer:",
                "Extra post-roll buffer added to the end of scheduled recordings to avoid clipping broadcast overruns."
            ),
            self.end_buffer_spin
        )

        self.auto_buffer_sports_check = QCheckBox("Auto-Extend Sports")
        self.auto_buffer_sports_check.setChecked(self.config_mgr.auto_buffer_sports)
        self.sports_buffer_spin = QSpinBox()
        self.sports_buffer_spin.setRange(0, 180)
        self.sports_buffer_spin.setValue(self.config_mgr.sports_buffer_mins)
        self.sports_buffer_spin.setSuffix(" minutes")
        self.sports_buffer_spin.setFixedWidth(130)
        sports_row = QHBoxLayout()
        sports_row.addWidget(self.auto_buffer_sports_check)
        sports_row.addSpacing(10)
        sports_row.addWidget(self.sports_buffer_spin)
        sports_row.addStretch()
        dvr_layout.addRow(
            make_setting_label(
                "Sports Auto-Extend:",
                "Applies extended post-roll padding to live sporting events, games, and matches to catch overtime."
            ),
            sports_row
        )

        self.interval_spin = QSpinBox()
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

        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 14)
        self.days_spin.setValue(self.config_mgr.guide_days_ahead)
        self.days_spin.setSuffix(" days")
        self.days_spin.setFixedWidth(160)
        dvr_layout.addRow(
            make_setting_label(
                "Guide Cache Horizon:",
                "How many future days to query and cache in the local SQLite guide database."
            ),
            self.days_spin
        )

        self.launch_mode_combo = QComboBox()
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

        self.guide_watch_combo = QComboBox()
        self.guide_watch_combo.addItem("Minimal Mode (-m clean player)", "minimal")
        self.guide_watch_combo.addItem("Minimal + Always On Top (-m -t)", "minimal_alwaysontop")
        self.guide_watch_combo.addItem("Full Screen (-f fullscreen)", "fullscreen")
        self.guide_watch_combo.addItem("Always On Top (-t always on top)", "alwaysontop")
        self.guide_watch_combo.addItem("Normal Window (Full KDE controls)", "normal")
        self.guide_watch_combo.setFixedWidth(290)
        cur_watch_mode = self.config_mgr.guide_watch_mode
        watch_idx = self.guide_watch_combo.findData(cur_watch_mode)
        if watch_idx >= 0:
            self.guide_watch_combo.setCurrentIndex(watch_idx)
        dvr_layout.addRow(
            make_setting_label(
                "Guide Live TV View Mode:",
                "Controls window display mode when watching live TV directly from the Guide:\n"
                "• Minimal Mode: Hides toolbars and menus for clean playback.\n"
                "• Minimal + Always On Top: Borderless minimal player pinned on top.\n"
                "• Full Screen: Expands to full screen immediately.\n"
                "• Always On Top: Keeps video pinned on top of other windows.\n"
                "• Normal Window: Standard window with playback bars."
            ),
            self.guide_watch_combo
        )

        self.notify_check = QCheckBox("Show Persistent Desktop Notification on Record Launch")
        self.notify_check.setChecked(self.config_mgr.enable_desktop_notifications)
        dvr_layout.addRow(
            make_setting_label(
                "Desktop Notifications:",
                "Sends a persistent desktop notification via notify-send when Kaffeine is launched and armed for a scheduled show."
            ),
            self.notify_check
        )

        left_col.addWidget(dvr_group)

        # Group 2: Window Dimensions
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
        self.save_win_size_btn.setToolTip("Save current window dimensions to restore automatically on launch")
        self.save_win_size_btn.clicked.connect(self.save_current_window_size)
        win_size_btn_row.addWidget(self.save_win_size_btn)

        self.restore_win_size_btn = QPushButton("Restore Size")
        self.restore_win_size_btn.setToolTip("Resize back to saved dimensions without restarting")
        self.restore_win_size_btn.clicked.connect(self.restore_saved_window_size)
        win_size_btn_row.addWidget(self.restore_win_size_btn)

        self.reset_win_size_btn = QPushButton("Reset Default")
        self.reset_win_size_btn.setToolTip("Reset window dimensions to default (1100 × 750)")
        self.reset_win_size_btn.clicked.connect(self.reset_window_size_to_default)
        win_size_btn_row.addWidget(self.reset_win_size_btn)
        win_size_btn_row.addStretch()
        win_layout.addLayout(win_size_btn_row)

        left_col.addWidget(win_group)
        left_col.addStretch()
        two_col_layout.addLayout(left_col, 50)

        # ------------------ RIGHT COLUMN: Service & Storage ------------------
        right_col = QVBoxLayout()
        right_col.setSpacing(15)

        # Service Management Card
        service_box = QGroupBox("Unified Background Service (kaffeine-dvr-watcher)")
        service_layout = QVBoxLayout(service_box)
        service_layout.setContentsMargins(15, 0, 15, 10)
        service_layout.setSpacing(4)

        self.service_status_lbl = QLabel("Checking service status...")
        self.service_status_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        service_layout.addWidget(self.service_status_lbl)

        svc_btn_row = QHBoxLayout()
        svc_btn_row.setSpacing(10)
        self.start_svc_btn = QPushButton("Start && Enable Service")
        self.start_svc_btn.clicked.connect(self.start_background_service)
        svc_btn_row.addWidget(self.start_svc_btn)

        self.restart_svc_btn = QPushButton("Restart Service")
        self.restart_svc_btn.clicked.connect(self.restart_background_service)
        svc_btn_row.addWidget(self.restart_svc_btn)
        svc_btn_row.addStretch()
        service_layout.addLayout(svc_btn_row)

        right_col.addWidget(service_box)

        # Storage & Auto-Cleanup Card
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

        self.retention_days_spin = QSpinBox()
        self.retention_days_spin.setRange(0, 365)
        self.retention_days_spin.setValue(self.config_mgr.retention_days)
        self.retention_days_spin.setSuffix(" days")
        self.retention_days_spin.setFixedWidth(150)
        self.retention_days_spin.valueChanged.connect(self._auto_save_automation_settings)
        storage_form.addRow(
            make_setting_label("Retention Window:", "Delete recordings older than this age. Set to 0 to disable age-based pruning."),
            self.retention_days_spin
        )

        self.min_free_spin = QSpinBox()
        self.min_free_spin.setRange(0, 1000)
        self.min_free_spin.setSingleStep(5)
        self.min_free_spin.setValue(self.config_mgr.min_free_disk_gb)
        self.min_free_spin.setSuffix(" GB")
        self.min_free_spin.setFixedWidth(150)
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

        right_col.addWidget(storage_box)
        right_col.addStretch()
        two_col_layout.addLayout(right_col, 50)

        main_layout.addLayout(two_col_layout)

        # Wire up auto-saves
        self.lead_time_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.end_buffer_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.auto_buffer_sports_check.stateChanged.connect(self._auto_save_automation_settings)
        self.sports_buffer_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.interval_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.days_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.launch_mode_combo.currentIndexChanged.connect(self._auto_save_automation_settings)
        self.guide_watch_combo.currentIndexChanged.connect(self._auto_save_automation_settings)
        self.notify_check.stateChanged.connect(self._auto_save_automation_settings)

        scroll.setWidget(container)
        return scroll

    # ------------------ TAB 5: HELP AND INFORMATION ------------------
    def create_help_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.help_subtabs = QTabWidget()
        self.help_subtabs.setObjectName("helpSubTabs")
        self.help_subtabs.addTab(self.create_help_setup_guide_tab(), "Quick Setup Guide")
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
        h1 = QLabel("<b>Step-by-Step Channel &amp; Guide Setup Walkthrough</b>")
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
            "• <b style='color: #4ade80;'>1. One-Click Database Import:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– In this app, go to <b>Settings &gt; Channel Source</b>.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Click the emerald green button at the bottom: <b style='color: #4ade80;'>Import Channels from Kaffeine</b>.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– The app connects to <code>~/.local/share/kaffeine/sqlite.db</code>, instantly populating your channel lineup and guide mapping area.<br><br>"
            "• <b style='color: #4ade80;'>2. Guide Network Mapping (Left Panel - Format: Guide Name = Tuned Channel):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Online schedules use network names (e.g. <code>Fox</code>), while your antenna scans station callsigns (e.g. <code>KSAZ-HD</code>).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– Example: <code style='color: #52b788;'>Fox = KSAZ-HD</code> maps Fox schedule listings to tune <code>KSAZ-HD</code> on your antenna.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;– If channels in Kaffeine already match, leave them as <code style='color: #52b788;'>Fox = Fox</code>.<br>"
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
            "&nbsp;&nbsp;&nbsp;&nbsp;1. Open <a href='https://www.tvpassport.com' style='color: #64b5f6; font-weight: bold;'>tvpassport.com</a> and find your city's local affiliate station.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;2. Copy the numeric station ID from the URL (e.g. <code>1809</code> for Fox Phoenix).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;3. Go to <b>Settings &gt; Guide Sources &amp; Health</b>, expand <b>TV Passport Station IDs</b>, and enter: <code>Fox = 1809</code> (or <code>KSAZ-HD = 1809</code>).<br>"
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
            "&nbsp;&nbsp;&nbsp;&nbsp;1. Look up your local affiliate station on <a href='https://www.tvpassport.com' style='color: #64b5f6; font-weight: bold;'>tvpassport.com</a>.<br>"
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
        self.health_worker.start()

    def on_health_check_finished(self, results: Dict[str, Any], silent: bool):
        self.test_health_btn.setEnabled(True)
        if not results:
            if not silent:
                self.status_bar.showMessage("Health check failed.", 4000)
            return

        self.health_table.setRowCount(len(results))
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
                    f"Go to <a href='https://www.tvpassport.com' style='color: #64b5f6; font-weight: bold; text-decoration: underline;'>https://www.tvpassport.com</a>, "
                    f"search your city or station, click on your channel, and copy the numeric ID from the URL (e.g. <code>/station/1812/</code>).<br><br>"
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
        for st_name in stations.keys():
            if st_name not in cur_map:
                cur_map[st_name] = st_name
        self.config_mgr.channel_map = cur_map
        self.guide_service.set_channel_map(cur_map)
        mapping_str = "\n".join([f"{k} = {v}" for k, v in cur_map.items()])
        if hasattr(self, "mapping_text"):
            self.mapping_text.setPlainText(mapping_str)

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
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() and v.strip():
                    new_map[k.strip()] = v.strip()
        self.config_mgr.channel_map = new_map
        self.guide_service.set_channel_map(new_map)
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
        mapping_str = "\n".join([f"{k} = {v}" for k, v in current_map.items()])
        self.mapping_text.setPlainText(mapping_str)
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
                        subprocess.run(
                            ["systemctl", "--user", "enable", "--now", "kaffeine-dvr-watcher.service"],
                            check=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                    except Exception as e:
                        print(f"Error starting background service: {e}")
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
            self.save_indicator_lbl.setText("Changes save automatically")
            self.save_indicator_lbl.setStyleSheet(
                "color: #8c98aa; font-size: 11px; padding: 4px 6px; background: transparent;"
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

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._adjust_table_columns)
        QTimer.singleShot(100, self._adjust_table_columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "win_size_lbl"):
            self.win_size_lbl.setText(self._get_window_size_label_text())
        self._adjust_table_columns()

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
        self.config_mgr.guide_days_ahead = self.days_spin.value()
        self.config_mgr.launch_mode = self.launch_mode_combo.currentData()
        if hasattr(self, "guide_watch_combo"):
            self.config_mgr.guide_watch_mode = self.guide_watch_combo.currentData()
        self.config_mgr.enable_desktop_notifications = self.notify_check.isChecked()

        # Storage & Retention settings
        self.config_mgr.auto_cleanup_enabled = self.cleanup_enable_check.isChecked()
        self.config_mgr.retention_days = self.retention_days_spin.value()
        self.config_mgr.min_free_disk_gb = self.min_free_spin.value()
        self.config_mgr.custom_recording_folder = self.custom_folder_input.text().strip()

        self.update_storage_status_ui()
        self.flash_save_indicator("Settings Saved")

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
            self.storage_status_lbl.setStyleSheet(f"font-weight: bold; font-size: 11px; color: {color};")

    def run_manual_cleanup(self):
        retention_days = self.retention_days_spin.value()
        min_free = self.min_free_spin.value()
        folder = self.custom_folder_input.text().strip() or self.storage_mgr.get_active_recording_folder()

        confirm = QMessageBox.warning(
            self,
            "Confirm Retention Cleanup",
            f"Are you sure you want to run retention cleanup now?\n\n"
            f"Target Directory: {folder}\n"
            f"Retention Policy: Delete unprotected recordings older than {retention_days} days "
            f"or if free space is below {min_free} GB.\n\n"
            f"Recordings matching these criteria will be permanently deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # Apply current settings to manager first
        self.config_mgr.auto_cleanup_enabled = True
        self.config_mgr.retention_days = retention_days
        self.config_mgr.min_free_disk_gb = min_free
        self.config_mgr.custom_recording_folder = self.custom_folder_input.text().strip()

        res = self.storage_mgr.run_cleanup_cycle()
        self.update_storage_status_ui()
        self.refresh_recordings()

        cnt = res.get("deleted_count", 0)
        freed = res.get("freed_gb", 0.0)
        target = res.get("folder", "")
        if cnt > 0:
            deleted_list = "\n".join(f"• {f}" for f in res.get("deleted_files", []))
            QMessageBox.information(
                self, "Retention Cleanup Completed",
                f"Successfully deleted {cnt} recording(s), reclaiming {freed} GB in:\n{target}\n\nDeleted files:\n{deleted_list}"
            )
        else:
            QMessageBox.information(
                self, "Retention Cleanup",
                f"No old recordings met the purge criteria in:\n{target}\n\nFree space remains within configured limits."
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
        except Exception:
            if hasattr(self, "service_status_lbl"):
                self.service_status_lbl.setText("Status: Unknown")

    def start_background_service(self):
        try:
            subprocess.run(["systemctl", "--user", "enable", "--now", "kaffeine-dvr-watcher.service"], check=False)
            self.update_service_status_ui()
            QMessageBox.information(self, "Service Started", "kaffeine-dvr-watcher.service has been started and enabled.")
        except Exception as e:
            QMessageBox.warning(self, "Service Error", f"Failed to start service: {e}")

    def restart_background_service(self):
        try:
            subprocess.run(["systemctl", "--user", "restart", "kaffeine-dvr-watcher.service"], check=False)
            self.update_service_status_ui()
            QMessageBox.information(self, "Service Restarted", "kaffeine-dvr-watcher.service has been restarted.")
        except Exception as e:
            QMessageBox.warning(self, "Service Error", f"Failed to restart service: {e}")

    # ------------------ LOGIC & REFRESH ------------------
    def setup_timers(self):
        # Background scheduling and recording dispatch are handled by the systemd service.
        # GUI refreshes on-demand (when syncing guide, switching tabs, or user actions).
        pass

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

            self.guide_status_lbl.setText(f"TV Guide Updated: {relative_str}")
            self.guide_status_lbl.setToolTip(f"Last sync completed: {last_updated}")
        else:
            self.guide_status_lbl.setText("TV Guide: Not Synced")

    def launch_kaffeine(self):
        self.status_bar.showMessage("Launching Kaffeine...", 3000)
        self.dbus_client.launch_kaffeine(mode=self.config_mgr.launch_mode)
        QTimer.singleShot(2000, self.update_status_badges)

    def sync_guide(self):
        self.sync_guide_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_bar.showMessage("Syncing guide data...")

        self.sync_worker = SyncWorker(self.guide_service, self.config_mgr.guide_days_ahead)
        self.sync_worker.progress.connect(lambda msg: self.status_bar.showMessage(msg))
        self.sync_worker.progress_val.connect(self._on_sync_progress_val)
        self.sync_worker.finished.connect(self.on_sync_finished)
        self.sync_worker.start()

    def _on_sync_progress_val(self, val: int):
        self.progress_bar.setValue(max(self.progress_bar.value(), val))

    def on_sync_finished(self, count: int, error: str):
        self.progress_bar.setValue(100)
        self.sync_guide_btn.setEnabled(True)
        QTimer.singleShot(600, lambda: self.progress_bar.setVisible(False))
        if error:
            QMessageBox.critical(self, "Guide Sync Error", f"Failed to sync guide: {error}")
            self.status_bar.showMessage("Guide sync failed.")
        else:
            self.status_bar.showMessage(f"Guide synced: {count} programs cached.", 5000)
            self.refresh_date_dropdown()
            self.update_status_badges()
            self.refresh_channel_dropdowns()
            self.filter_guide()
            self.run_rules(silent=True)
            self.test_all_sources_health(silent=True)

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
            sched_item.setToolTip(f"Full broadcast time: {full_date_text}")

            self.rec_table.setItem(row, 0, title_item)
            self.rec_table.setItem(row, 1, sched_item)
            self.rec_table.setItem(row, 2, QTableWidgetItem(channel))

            buf_val = rec.get("buffer_mins", 0) or 0
            if buf_val > 0:
                duration_display = f"{duration} (+{buf_val}m)"
            else:
                duration_display = duration
            dur_item = QTableWidgetItem(duration_display)
            if buf_val > 0:
                dur_item.setToolTip(f"Includes +{buf_val} minutes post-roll buffer")
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
                prot_item.setToolTip("Protected: Will never be automatically deleted by retention rules.")
            else:
                prot_item.setForeground(QColor("#a0aec0"))
                prot_item.setToolTip("Standard: Subject to auto-cleanup retention rules.")
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
            dt_item.setToolTip(f"Broadcast start: {start_iso}")

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
        confirm = QMessageBox.question(
            self, "Confirm Cancellation",
            f"Are you sure you want to cancel the recording for '{rec_title}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            k_key = self.queue_mgr.remove_recording(int(qid))
            if k_key:
                self.dbus_client.remove_recording(k_key)
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
        is_grid = self.guide_stack.currentIndex() == 0
        self.jump_now_btn.setVisible(is_grid)
        self.jump_prime_btn.setVisible(is_grid)

    def _on_guide_view_toggled(self):
        if self.grid_view_btn.isChecked():
            self.guide_stack.setCurrentIndex(0)
            self.settings.setValue("guide_view_mode", "grid")
        else:
            self.guide_stack.setCurrentIndex(1)
            self.settings.setValue("guide_view_mode", "list")
        self._update_time_jump_buttons_visibility()
        self.filter_guide()

    def _scroll_grid_to_slot(self, slot: int, center: bool = False):
        bar = self.guide_grid_table.horizontalScrollBar()
        col_width = self.guide_grid_table.horizontalHeader().defaultSectionSize() or 165
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
        now = datetime.now()
        # 10-minute buffer: if 50+ minutes past the hour, advance to the next hour's slot
        if now.minute >= 50:
            target_slot = min(47, (now.hour + 1) * 2)
        elif now.minute >= 30:
            target_slot = now.hour * 2 + 1
        else:
            target_slot = now.hour * 2

        self._scroll_grid_to_slot(target_slot, center=False)

    def jump_guide_to_start(self):
        self._scroll_grid_to_slot(0, center=False)

    def jump_guide_to_noon(self):
        # 12:00 PM (Noon) is hour 12 -> slot 24
        self._scroll_grid_to_slot(24, center=False)

    def jump_guide_to_primetime(self):
        # 7:00 PM (19:00) is hour 19 -> slot 38
        self._scroll_grid_to_slot(38, center=False)

    def zoom_in_guide(self):
        """Increase font and box size for both grid and list views."""
        if not hasattr(self, "guide_zoom_level"):
            self.guide_zoom_level = 0
        if self.guide_zoom_level < 5:
            self.guide_zoom_level += 1
            self.settings.setValue("guide_zoom_level", self.guide_zoom_level)
            self._apply_guide_zoom()

    def zoom_out_guide(self):
        """Decrease font and box size for both grid and list views."""
        if not hasattr(self, "guide_zoom_level"):
            self.guide_zoom_level = 0
        if self.guide_zoom_level > -3:
            self.guide_zoom_level -= 1
            self.settings.setValue("guide_zoom_level", self.guide_zoom_level)
            self._apply_guide_zoom()

    def _apply_guide_zoom(self):
        """Apply the current guide zoom level to Grid and List views."""
        lvl = getattr(self, "guide_zoom_level", 0)

        # Update enable state of buttons
        if hasattr(self, "zoom_in_btn"):
            self.zoom_in_btn.setEnabled(lvl < 5)
        if hasattr(self, "zoom_out_btn"):
            self.zoom_out_btn.setEnabled(lvl > -3)

        # 1. Grid View sizing
        # Base dimensions: col_width = 165, row_height = 62
        col_w = max(110, 165 + (lvl * 25))
        row_h = max(44, 62 + (lvl * 10))

        if hasattr(self, "guide_grid_table"):
            self.guide_grid_table.horizontalHeader().setDefaultSectionSize(col_w)
            self.guide_grid_table.verticalHeader().setDefaultSectionSize(row_h)

            # Update delegate font delta and trigger repaint
            if hasattr(self, "grid_tile_delegate"):
                self.grid_tile_delegate.set_zoom_delta(lvl)

            # Dynamic header font size
            hdr_font_sz = max(9, 11 + lvl)
            v_hdr_font_sz = max(10, 12 + lvl)
            self.guide_grid_table.setStyleSheet(
                f"QTableWidget#guideGridTable QHeaderView::section:horizontal {{ font-size: {hdr_font_sz}px; }} "
                f"QTableWidget#guideGridTable QHeaderView::section:vertical {{ font-size: {v_hdr_font_sz}px; }}"
            )
            self.guide_grid_table.viewport().update()

        # 2. List View sizing
        # Base row height = 28, base font = 12px
        if hasattr(self, "guide_table"):
            list_font_sz = max(9, 12 + lvl)
            list_row_h = max(22, 28 + (lvl * 5))
            self.guide_table.verticalHeader().setDefaultSectionSize(list_row_h)
            self.guide_table.setStyleSheet(f"QTableWidget {{ font-size: {list_font_sz}px; }}")
            self.guide_table.viewport().update()

    def toggle_guide_maximized(self):
        self._guide_maximized = not getattr(self, "_guide_maximized", False)
        is_max = self._guide_maximized

        if hasattr(self, "status_banner_widget"):
            self.status_banner_widget.setVisible(not is_max)

        if hasattr(self, "tabs"):
            self.tabs.tabBar().setVisible(not is_max)

        if hasattr(self, "guide_detail_widget"):
            self.guide_detail_widget.setVisible(not is_max)

        if hasattr(self, "status_bar"):
            self.status_bar.setVisible(not is_max)

        if hasattr(self, "guide_maximize_btn"):
            if is_max:
                self.guide_maximize_btn.setToolTip("Restore standard view (Esc)")
                self.guide_maximize_btn.setIcon(self._create_guide_restore_icon())
            else:
                self.guide_maximize_btn.setToolTip("Maximize guide to fill window")
                self.guide_maximize_btn.setIcon(self._create_guide_maximize_icon())

    @staticmethod
    def _create_guide_maximize_icon() -> QIcon:
        icon = QIcon()
        for mode, color in [(QIcon.Mode.Normal, "#c8d2df"), (QIcon.Mode.Disabled, "#414b5d")]:
            pix = QPixmap(18, 18)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(color), 1.8)
            p.setPen(pen)
            # Crisp maximize rectangle
            p.drawRoundedRect(QRectF(2.5, 2.5, 13, 13), 1.5, 1.5)
            # Thicker top titlebar line
            p.fillRect(QRectF(3.5, 3.5, 11, 2.5), QColor(color))
            p.end()
            icon.addPixmap(pix, mode)
        return icon

    @staticmethod
    def _create_guide_restore_icon() -> QIcon:
        icon = QIcon()
        for mode, color in [(QIcon.Mode.Normal, "#c8d2df"), (QIcon.Mode.Disabled, "#414b5d")]:
            pix = QPixmap(18, 18)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(color), 1.8)
            p.setPen(pen)
            # Main foreground window rectangle
            p.drawRoundedRect(QRectF(2, 5, 10, 10), 1.5, 1.5)
            p.fillRect(QRectF(3, 6, 8, 2), QColor(color))
            # Background overlapping window
            p.drawLine(QPointF(5.5, 4), QPointF(5.5, 2))
            p.drawLine(QPointF(5.5, 2), QPointF(15, 2))
            p.drawLine(QPointF(15, 2), QPointF(15, 11.5))
            p.drawLine(QPointF(15, 11.5), QPointF(13, 11.5))
            p.end()
            icon.addPixmap(pix, mode)
        return icon

    @staticmethod
    def _create_restore_window_icon() -> QIcon:
        icon = QIcon()
        for mode, color in [(QIcon.Mode.Normal, "#c8d2df"), (QIcon.Mode.Disabled, "#414b5d")]:
            pix = QPixmap(18, 18)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(color), 1.8)
            p.setPen(pen)
            # Main window rectangle
            p.drawRoundedRect(QRectF(1.5, 4.5, 11, 11), 1.5, 1.5)
            # Overlapping window top-right
            p.drawLine(5, 4, 5, 2)
            p.drawLine(5, 2, 15, 2)
            p.drawLine(15, 2, 15, 12)
            p.drawLine(15, 12, 13, 12)
            p.end()
            icon.addPixmap(pix, mode)
        return icon

    @staticmethod
    def _create_nav_arrow_icon(direction: str = "left") -> QIcon:
        icon = QIcon()
        # Create crisp pixmaps for Normal and Disabled states
        states = [
            (QIcon.Mode.Normal, "#c5d1de"),
            (QIcon.Mode.Disabled, "#414b5d"),
        ]
        for mode, color in states:
            pix = QPixmap(24, 24)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(color)))
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

        arrow_style = (
            "QPushButton { "
            "border: 1px solid #303746; border-radius: 4px; background-color: #1e2330; }"
            "QPushButton:hover { background-color: #262e3f; border: 1px solid #455470; }"
            "QPushButton:pressed { background-color: #161a24; }"
            "QPushButton:disabled { background-color: #161a22; border: 1px solid #242935; }"
        )

        self.day_nav_prev_btn = QPushButton()
        self.day_nav_prev_btn.setIcon(self._create_nav_arrow_icon("left"))
        self.day_nav_prev_btn.setIconSize(QSize(20, 20))
        self.day_nav_prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.day_nav_prev_btn.setToolTip("Previous week (Sun - Sat)")
        self.day_nav_prev_btn.setFixedWidth(36)
        self.day_nav_prev_btn.setFixedHeight(44)
        self.day_nav_prev_btn.setStyleSheet(arrow_style)
        self.day_nav_prev_btn.clicked.connect(self._on_day_nav_prev)
        nav_layout.addWidget(self.day_nav_prev_btn)

        # Standard upcoming unselected day
        self._day_style_unselected = (
            "QPushButton { padding: 4px 2px; font-size: 13px; font-weight: 500; line-height: 1.2; "
            "border: 1px solid #303746; border-radius: 4px; background-color: #1e2330; color: #a4b0c2; }"
            "QPushButton:hover { background-color: #262e3f; border: 1px solid #455470; color: #e2e8f0; }"
            "QPushButton:pressed { background-color: #161a24; }"
        )

        # Today's day (when NOT currently selected) - understated dark green tint & border
        self._day_style_today_unselected = (
            "QPushButton { padding: 4px 2px; font-size: 13px; font-weight: 600; line-height: 1.2; "
            "border: 1px solid #2e5937; border-radius: 4px; background-color: #16261b; color: #7ec788; }"
            "QPushButton:hover { background-color: #1e3324; border: 1px solid #3d7349; color: #9cdba4; }"
            "QPushButton:pressed { background-color: #111e15; }"
        )

        # Today's day (when ALSO currently selected) - subdued dark forest green with clean accent
        self._day_style_today_selected = (
            "QPushButton { padding: 4px 2px; font-size: 13px; font-weight: 600; line-height: 1.2; "
            "border: 1px solid #438450; border-radius: 4px; background-color: #223f2a; color: #e8f5e9; }"
            "QPushButton:hover { background-color: #2a4c33; border: 1px solid #529c62; color: #ffffff; }"
            "QPushButton:pressed { background-color: #1a3221; }"
        )

        # Selected day (when it is NOT Today) - subdued dark warm amber with soft border
        self._day_style_selected = (
            "QPushButton { padding: 4px 2px; font-size: 13px; font-weight: 600; line-height: 1.2; "
            "border: 1px solid #b86e28; border-radius: 4px; background-color: #3b2818; color: #ffd8a8; }"
            "QPushButton:hover { background-color: #4a3320; border: 1px solid #d48332; color: #ffe3c2; }"
            "QPushButton:pressed { background-color: #2e1f13; }"
        )

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
        self.day_nav_next_btn.setIcon(self._create_nav_arrow_icon("right"))
        self.day_nav_next_btn.setIconSize(QSize(20, 20))
        self.day_nav_next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.day_nav_next_btn.setToolTip("Next week (Sun - Sat)")
        self.day_nav_next_btn.setFixedWidth(36)
        self.day_nav_next_btn.setFixedHeight(44)
        self.day_nav_next_btn.setStyleSheet(arrow_style)
        self.day_nav_next_btn.clicked.connect(self._on_day_nav_next)
        nav_layout.addWidget(self.day_nav_next_btn)

        return container

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

            full_label = f"{day_name}, {short_date}"
            if is_today and is_selected:
                btn.setStyleSheet(self._day_style_today_selected)
                btn.setToolTip(f"{full_label} (Current Day - Selected)")
            elif is_today:
                btn.setStyleSheet(self._day_style_today_unselected)
                btn.setToolTip(f"{full_label} (Current Day)")
            elif is_selected:
                btn.setStyleSheet(self._day_style_selected)
                btn.setToolTip(f"{full_label} (Selected)")
            else:
                btn.setStyleSheet(self._day_style_unselected)
                btn.setToolTip(full_label)

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
        trim_ended = (self.guide_stack.currentIndex() == 1 and airdate is None)
        programs = self.guide_service.search_programs(
            query=query, channel=channel, airdate=airdate, trim_ended=trim_ended
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
        self.guide_table.setUpdatesEnabled(False)
        self.guide_table.blockSignals(True)
        try:
            self.guide_table.setRowCount(len(programs))
            for row, p in enumerate(programs):
                ch = (p.get("kaffeine_channel") or "").strip().lower()
                start_iso = (p.get("start_iso") or "")[:16]
                rec_info = active_scheduled.get((ch, start_iso))

                timing_info = self._get_program_timing_state(p)
                timing_state = timing_info.get("state", "upcoming")
                cat = p.get("_category") or classify_guide_category(p)

                rec_item = QTableWidgetItem("● REC" if rec_info else "")
                rec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if rec_info:
                    rec_item.setForeground(QColor("#ff5252"))
                    rec_item.setFont(QFont("", -1, QFont.Weight.Bold))
                    buf_val = rec_info.get("buffer_mins", 0)
                    buf_tip = f" | +{buf_val}m buffer" if buf_val else ""
                    rec_item.setToolTip(f"Recording Scheduled (Queue #{rec_info.get('id')} - {rec_info.get('status')}{buf_tip})")
                self.guide_table.setItem(row, 0, rec_item)

                time_item = QTableWidgetItem(p.get("start_time_local", ""))
                chan_item = QTableWidgetItem(p.get("kaffeine_channel", ""))

                disp_title, disp_sub = get_program_display_titles(p)
                title_item = QTableWidgetItem(disp_title)
                sub_item = QTableWidgetItem(disp_sub)
                dur_item = QTableWidgetItem(p.get("duration_iso", ""))

                # Option 1 coloring for list view:
                if timing_state == "past":
                    gray_color = QColor("#788292")
                    time_item.setForeground(gray_color)
                    chan_item.setForeground(gray_color)
                    title_item.setForeground(gray_color)
                    sub_item.setForeground(gray_color)
                    dur_item.setForeground(gray_color)
                elif timing_state == "live":
                    if cat == "sports":
                        t_color = QColor("#ffa028")
                    elif cat == "news":
                        t_color = QColor("#4fc3f7")
                    elif cat == "movies":
                        t_color = QColor("#ff5c5c")
                    else:
                        t_color = QColor("#66bb6a")
                    title_item.setForeground(t_color)
                    title_font = QFont()
                    title_font.setBold(True)
                    title_item.setFont(title_font)
                else:
                    if cat == "sports":
                        t_color = QColor("#ffa028")
                    elif cat == "news":
                        t_color = QColor("#4fc3f7")
                    elif cat == "movies":
                        t_color = QColor("#ff5c5c")
                    else:
                        t_color = QColor("#f1f5f9")
                    title_item.setForeground(t_color)

                self.guide_table.setItem(row, 1, time_item)
                self.guide_table.setItem(row, 2, chan_item)
                self.guide_table.setItem(row, 3, title_item)
                self.guide_table.setItem(row, 4, sub_item)
                self.guide_table.setItem(row, 5, dur_item)

            for col in [0, 1, 2, 5]:
                self.guide_table.resizeColumnToContents(col)

            # Auto-scroll to first currently playing or upcoming show
            first_active_row = -1
            for r, p in enumerate(programs):
                timing = self._get_program_timing_state(p)
                if timing.get("state") in ("live", "upcoming"):
                    first_active_row = r
                    break
            if first_active_row >= 0:
                target_item = self.guide_table.item(first_active_row, 1) or self.guide_table.item(first_active_row, 0)
                if target_item:
                    self.guide_table.scrollToItem(target_item, QTableWidget.ScrollHint.PositionAtTop)
        finally:
            self.guide_table.blockSignals(False)
            self.guide_table.setUpdatesEnabled(True)

    def _populate_grid_guide(self, programs: List[Dict[str, Any]], airdate: Optional[str], keep_scroll: bool = False):
        active_scheduled = self.queue_mgr.get_active_scheduled_map()

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

        # Configure columns and headers for single-day 24-hour grid (48 columns)
        total_cols = 48
        if self.guide_grid_table.columnCount() != total_cols:
            self.guide_grid_table.setColumnCount(total_cols)
        grid_headers = []
        for h in range(24):
            for m in (0, 30):
                grid_headers.append(f"{h%12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}")
        self.guide_grid_table.setHorizontalHeaderLabels(grid_headers)
        base_dt = datetime.combine(datetime.strptime(target_date_str, "%Y-%m-%d").date(), datetime.min.time())

        # Color palette for tiles
        tile_bg = QColor("#222838")
        tile_bg_alt = QColor("#1e2332")
        tile_text_color = QColor("#ffffff")

        for row_idx, ch in enumerate(channels):
            # Filter specifically to selected airdate
            ch_progs = [
                p for p in programs
                if p.get("kaffeine_channel") == ch and (
                    p.get("airdate") == target_date_str or
                    (p.get("start_iso") and p.get("start_iso").startswith(target_date_str))
                )
            ]
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
                if start_col < current_col:
                    start_col = current_col
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
                ep_title = p.get("episode_title", "")
                start_fmt = dt.strftime("%I:%M %p").lstrip("0")
                end_fmt = end_dt.strftime("%I:%M %p").lstrip("0")
                time_range = f"{start_fmt} - {end_fmt}"

                # Match active recording
                ch_key = (ch or "").strip().lower()
                iso_key = (start_iso or "")[:16]
                scheduled_rec = active_scheduled.get((ch_key, iso_key))

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
                p_copy["_timing_state"] = timing_state
                p_title, p_sub = get_program_display_titles(p)
                p_copy["_primary_title"] = p_title
                p_copy["_secondary_sub"] = p_sub

                item = QTableWidgetItem(show_title)
                item.setData(Qt.ItemDataRole.UserRole, p_copy)
                
                # Visual styling based on timing state
                if timing_state == "past":
                    cur_bg = QColor("#161922") if (idx % 2 == 0) else QColor("#14171f")
                elif timing_state == "live":
                    cur_bg = QColor("#17261c")
                else:
                    cur_bg = tile_bg if (idx % 2 == 0) else tile_bg_alt
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

        # Auto-scroll based on selected date (unless preserving scroll position):
        if not keep_scroll:
            if target_date_str == today.strftime("%Y-%m-%d"):
                QTimer.singleShot(60, self.jump_guide_to_now)
            else:
                QTimer.singleShot(60, self.jump_guide_to_noon)

    def on_grid_cell_clicked(self, row: int, col: int):
        item = self.guide_grid_table.item(row, col)
        if not item:
            # Check previous columns in case of span
            for c in range(col - 1, -1, -1):
                it = self.guide_grid_table.item(row, c)
                if it and it.data(Qt.ItemDataRole.UserRole):
                    item = it
                    break

        if not item or not item.data(Qt.ItemDataRole.UserRole):
            self.guide_detail_title.setText("Select a program to view details")
            self.guide_detail_text.clear()
            self.selected_grid_program = None
            if hasattr(self, "watch_guide_btn"):
                self.watch_guide_btn.setVisible(False)
            if hasattr(self, "record_guide_btn"):
                self.record_guide_btn.setVisible(True)
                self.record_guide_btn.setText("Record This Program")
            if hasattr(self, "adjust_buffer_guide_btn"):
                self.adjust_buffer_guide_btn.setVisible(False)
            if hasattr(self, "cancel_guide_btn"):
                self.cancel_guide_btn.setVisible(False)
            return

        prog = item.data(Qt.ItemDataRole.UserRole)
        self.selected_grid_program = prog
        self._display_program_details(prog)

    def _display_program_details(self, prog: Dict[str, Any]):
        title = prog.get("show_title", "")
        ep = prog.get("episode_title", "")
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
        if state == "past":
            title_color_hex = "#788292"  # Dark grey, readable
        elif state == "live":
            if cat == "sports":
                title_color_hex = "#ffa028"  # Orange
            elif cat == "news":
                title_color_hex = "#4fc3f7"  # Blue
            elif cat == "movies":
                title_color_hex = "#ff5c5c"  # Red
            else:
                title_color_hex = "#66bb6a"  # Green used before
        else: # upcoming
            if cat == "sports":
                title_color_hex = "#ffa028"  # Orange
            elif cat == "news":
                title_color_hex = "#4fc3f7"  # Blue
            elif cat == "movies":
                title_color_hex = "#ff5c5c"  # Red
            else:
                title_color_hex = "#f1f5f9"  # White / light grey

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
        details_parts.append(f" on {html.escape(str(channel))} at {html.escape(str(start))}")
        rest_of_header = "".join(details_parts)

        self.guide_detail_title.setText(header_prefix + colored_title + rest_of_header)
        self.guide_detail_text.setText(summary)

        if hasattr(self, "watch_guide_btn"):
            if state == "live":
                self.watch_guide_btn.setVisible(True)
                self.watch_guide_btn.setText("Watch Live")
                self.watch_guide_btn.setToolTip(f"Watch live broadcast on {channel} in Kaffeine")
                self.watch_guide_btn.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: #ffffff; padding: 4px 12px;")
            elif state == "upcoming":
                self.watch_guide_btn.setVisible(True)
                self.watch_guide_btn.setText("Tune Channel Now")
                self.watch_guide_btn.setToolTip(f"Tune Kaffeine to {channel} now ({timing_info.get('time_desc')})")
                self.watch_guide_btn.setStyleSheet("padding: 4px 12px;")
            elif state == "past":
                if timing_info.get("recorded_file"):
                    self.watch_guide_btn.setVisible(True)
                    self.watch_guide_btn.setText("Play Recording")
                    self.watch_guide_btn.setToolTip(f"Play recorded file in player: {os.path.basename(timing_info['recorded_file'])}")
                    self.watch_guide_btn.setStyleSheet("font-weight: bold; background-color: #1976d2; color: #ffffff; padding: 4px 12px;")
                else:
                    self.watch_guide_btn.setVisible(False)

        if hasattr(self, "record_guide_btn"):
            self.record_guide_btn.setVisible(rec_info is None)
            self.record_guide_btn.setText("Record This Program")

        if hasattr(self, "adjust_buffer_guide_btn"):
            self.adjust_buffer_guide_btn.setVisible(rec_info is not None)

        if hasattr(self, "cancel_guide_btn"):
            self.cancel_guide_btn.setVisible(rec_info is not None)

    def on_guide_selection_changed(self):
        row = self.guide_table.currentRow()
        if row < 0 or row >= len(getattr(self, "current_guide_items", [])):
            self.guide_detail_title.setText("Select a program to view details")
            self.guide_detail_text.clear()
            if hasattr(self, "watch_guide_btn"):
                self.watch_guide_btn.setVisible(False)
            if hasattr(self, "record_guide_btn"):
                self.record_guide_btn.setVisible(True)
                self.record_guide_btn.setText("Record This Program")
            if hasattr(self, "adjust_buffer_guide_btn"):
                self.adjust_buffer_guide_btn.setVisible(False)
            if hasattr(self, "cancel_guide_btn"):
                self.cancel_guide_btn.setVisible(False)
            return

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

    def _get_program_timing_state(self, prog: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculates whether a program is live, upcoming, or past, and looks for recorded files if past.
        """
        now = datetime.now()
        start_iso = prog.get("start_iso")
        dur_iso = prog.get("duration_iso") or "00:30:00"

        start_dt = None
        end_dt = None
        if start_iso:
            try:
                start_dt = datetime.fromisoformat(start_iso)
                parts = [int(x) for x in dur_iso.split(":")]
                dur = timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2] if len(parts) > 2 else 0)
                end_dt = start_dt + dur
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
            return {
                "state": "live",
                "time_desc": f"Live Now ({mins_left}m remaining)",
                "start_fmt": start_fmt,
                "recorded_file": None,
                "start_dt": start_dt,
                "end_dt": end_dt
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
                "end_dt": end_dt
            }
        else:
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

            end_fmt = end_dt.strftime("%I:%M %p").lstrip("0")
            return {
                "state": "past",
                "time_desc": f"Ended at {end_fmt} ({start_dt.strftime('%b %d')})",
                "start_fmt": start_fmt,
                "recorded_file": recorded_file,
                "start_dt": start_dt,
                "end_dt": end_dt
            }

    def watch_or_tune_selected_guide_item(self):
        prog = self._get_active_selected_program()
        if not prog:
            QMessageBox.warning(self, "Selection Required", "Please select a program from the guide.")
            return

        timing_info = self._get_program_timing_state(prog)
        state = timing_info.get("state")
        ch = prog.get("kaffeine_channel", "")
        title = prog.get("show_title") or prog.get("title") or "Program"

        watch_mode = self.config_mgr.guide_watch_mode
        if state == "live":
            self.dbus_client.tune_channel(ch, raise_window=True, view_mode=watch_mode)
            self.status_bar.showMessage(f"Tuned to {ch} - Watching '{title}' live.", 4000)
        elif state == "upcoming":
            # Direct button click in detail pane tunes directly without popup
            self.dbus_client.tune_channel(ch, raise_window=True, view_mode=watch_mode)
            self.status_bar.showMessage(f"Tuned to {ch} (Upcoming: '{title}' {timing_info.get('time_desc')}).", 4000)
        elif state == "past":
            rec_file = timing_info.get("recorded_file")
            if rec_file:
                self.dbus_client.play_file(rec_file)
                self.status_bar.showMessage(f"Playing recording: {os.path.basename(rec_file)}", 4000)

    def handle_program_activation(self, prog: Dict[str, Any]):
        if not prog:
            return

        timing_info = self._get_program_timing_state(prog)
        state = timing_info.get("state")
        ch = prog.get("kaffeine_channel", "")
        title = prog.get("show_title") or prog.get("title") or "Program"
        watch_mode = self.config_mgr.guide_watch_mode

        if state == "live":
            self.dbus_client.tune_channel(ch, raise_window=True, view_mode=watch_mode)
            self.status_bar.showMessage(f"Tuned to {ch} - Watching '{title}' live.", 4000)
        elif state == "upcoming":
            # Option A: Smart Choice Dialog
            dlg = UpcomingShowDialog(prog, timing_info, parent=self)
            dlg.exec()
            if dlg.action == UpcomingShowDialog.ACTION_RECORD:
                self.record_selected_guide_item()
            elif dlg.action == UpcomingShowDialog.ACTION_TUNE:
                self.dbus_client.tune_channel(ch, raise_window=True, view_mode=watch_mode)
                self.status_bar.showMessage(f"Tuned to {ch} (Upcoming: '{title}' {timing_info.get('time_desc')}).", 4000)
        elif state == "past":
            rec_file = timing_info.get("recorded_file")
            if rec_file:
                self.dbus_client.play_file(rec_file)
                self.status_bar.showMessage(f"Playing recording: {os.path.basename(rec_file)}", 4000)
            else:
                QMessageBox.information(
                    self, "Broadcast Ended",
                    f"'{title}' on {ch} has already finished broadcasting ({timing_info.get('time_desc')})."
                )

    def on_grid_cell_double_clicked(self, row: int, col: int):
        item = self.guide_grid_table.item(row, col)
        if not item:
            for c in range(col - 1, -1, -1):
                it = self.guide_grid_table.item(row, c)
                if it and it.data(Qt.ItemDataRole.UserRole):
                    item = it
                    break
        if item and item.data(Qt.ItemDataRole.UserRole):
            prog = item.data(Qt.ItemDataRole.UserRole)
            self.selected_grid_program = prog
            self._display_program_details(prog)
            self.handle_program_activation(prog)

    def on_guide_table_double_clicked(self, item: QTableWidgetItem):
        row = item.row()
        if 0 <= row < len(getattr(self, "current_guide_items", [])):
            prog = self.current_guide_items[row]
            self._display_program_details(prog)
            self.handle_program_activation(prog)

    def cancel_selected_guide_recording(self):
        prog = self._get_active_selected_program()
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
        confirm = QMessageBox.question(
            self, "Confirm Cancellation",
            f"Are you sure you want to cancel the scheduled recording for '{rec_title}' (Queue #{qid})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            k_key = self.queue_mgr.remove_recording(int(qid))
            if k_key:
                self.dbus_client.remove_recording(k_key)
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

    def record_selected_guide_item(self):
        prog = self._get_active_selected_program()
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
            buf_note = f"\nEnd Buffer: +{buf_mins} minutes (Sports Auto-Extend)"
        elif self.config_mgr.end_buffer_mins > 0:
            buf_mins = self.config_mgr.end_buffer_mins
            buf_note = f"\nEnd Buffer: +{buf_mins} minutes (Default Buffer)"
        else:
            buf_mins = 0
            buf_note = ""

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

    def add_rule_from_selected_guide_item(self):
        prog = self._get_active_selected_program()
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
        if event.key() == Qt.Key.Key_Escape and getattr(self, "_guide_maximized", False):
            self.toggle_guide_maximized()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self._auto_save_automation_settings()
        super().closeEvent(event)


def ensure_desktop_launcher():
    """Ensure kaffeine-dvr.desktop exists in user applications directory."""
    try:
        from pathlib import Path
        import shutil
        import subprocess

        xdg_data = os.environ.get("XDG_DATA_HOME")
        apps_dir = (Path(xdg_data) if xdg_data else Path.home() / ".local" / "share") / "applications"
        desktop_file = apps_dir / "kaffeine-dvr.desktop"

        if not desktop_file.exists():
            apps_dir.mkdir(parents=True, exist_ok=True)
            content = (
                "[Desktop Entry]\n"
                "Categories=AudioVideo;TV;Recorder;\n"
                "Comment=Modern TV Guide & DVR Recording Manager for Kaffeine\n"
                "Exec=sh -c 'PATH=\"$HOME/.local/bin:$PATH\" exec kaffeine-dvr'\n"
                "GenericName=TV Guide & Recording Manager\n"
                "Icon=kaffeine\n"
                "Keywords=tv;dvr;kaffeine;record;guide;epg;\n"
                "Name=Kaffeine DVR & TV Guide\n"
                "StartupNotify=true\n"
                "StartupWMClass=kaffeine-dvr\n"
                "Terminal=false\n"
                "Type=Application\n"
            )
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


def main():
    app = QApplication(sys.argv)
    ensure_desktop_launcher()
    wheel_filter = NoWheelEventFilter(app)
    app.installEventFilter(wheel_filter)
    app.setApplicationName("kaffeine-dvr")
    app.setApplicationDisplayName("Kaffeine DVR & TV Guide")
    app.setDesktopFileName("kaffeine-dvr")
    app.setWindowIcon(get_app_icon())
    setup_dark_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
