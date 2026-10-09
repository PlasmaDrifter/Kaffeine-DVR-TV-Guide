import sys
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
    QStyle, QListWidget, QListWidgetItem, QAbstractItemView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings, QByteArray, QEvent, QObject, QPointF, QRect
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QWheelEvent, QPainter, QPalette, QPixmap, QPen

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
    return str(asset_path).replace("\\", "/")


CHECKMARK_ICON_PATH = _get_checkmark_icon_path()


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

    # 3. Movies: title starts with 'Movie', or explicit film indicators
    if (
        title_lower == "movie"
        or title_lower.startswith("movie:")
        or title_lower.startswith("film:")
        or title_lower.endswith(" (movie)")
        or "feature film" in summary
        or " motion picture" in summary
    ):
        return "movies"
    if ("directed by" in summary or "stars as" in summary) and prog.get("runtime_mins", 0) >= 75 and not prog.get("season"):
        return "movies"

    # 4. TV Shows / Series / Daytime
    return "tvshows"


class ProgramTileDelegate(QStyledItemDelegate):
    """
    Custom item delegate for rendering traditional EPG grid program tiles.
    - Flawlessly aligns multi-line text flush to the left edge with uniform padding.
    - Colors show titles: Sports = Orange (#ffa028), News = Blue (#4fc3f7), Movies = Red (#ff5c5c), TV Shows = Green (#66bb6a).
    - Subtext displays time range and episode title with high legibility.
    """
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        prog = index.data(Qt.ItemDataRole.UserRole)
        if not prog:
            super().paint(painter, option, index)
            return

        painter.save()
        rect = option.rect

        # Background fill & subtle border
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_scheduled = bool(prog.get("_scheduled_rec"))

        if is_selected:
            bg_color = QColor("#2b3e4f")
            border_color = QColor("#ff5252") if is_scheduled else QColor("#55a84c")
        else:
            bg_color = index.data(Qt.ItemDataRole.BackgroundRole) or QColor("#222838")
            border_color = QColor("#e53935") if is_scheduled else QColor("#333c4e")

        painter.fillRect(rect, bg_color)
        painter.setPen(border_color)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        # Uniform padding inside box
        pad_left = 10
        pad_top = 8
        pad_right = 10
        inner_width = max(10, rect.width() - pad_left - pad_right)

        # Draw Scheduled [REC] badge in upper right corner if scheduled
        badge_reserved_w = 0
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

            bx = rect.right() - pad_right - bw
            by = rect.top() + pad_top
            badge_rect = QRect(bx, by, bw, bh)

            # Draw curved corners rectangle background with border
            painter.setPen(QColor("#e53935"))
            painter.setBrush(QColor("#b71c1c"))
            painter.drawRoundedRect(badge_rect, 4, 4)

            # Draw "REC" text perfectly centered
            painter.setPen(QColor("#ffffff"))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, rec_text)

            badge_reserved_w = bw + 6

        # Title Color coding: sports=orange, news=blue, movies=red, tvshows=green
        cat = prog.get("_category") or classify_guide_category(prog)
        if cat == "sports":
            title_color = QColor("#ffa028")  # Vibrant Orange
        elif cat == "news":
            title_color = QColor("#4fc3f7")  # Vibrant Light Blue
        elif cat == "movies":
            title_color = QColor("#ff5c5c")  # Vibrant Red
        else:
            title_color = QColor("#66bb6a")  # Vibrant Green

        show_title = prog.get("show_title", "")
        time_range = prog.get("_time_range", "")
        ep_title = prog.get("episode_title", "")

        # Line 1: Show Title (bold, color-coded)
        font_title = QFont(option.font)
        font_title.setBold(True)
        font_title.setPointSize(10)
        painter.setFont(font_title)
        painter.setPen(title_color)

        fm_title = painter.fontMetrics()
        inner_width_title = max(10, inner_width - badge_reserved_w)
        elided_title = fm_title.elidedText(show_title, Qt.TextElideMode.ElideRight, inner_width_title)
        line1_rect = QRect(rect.left() + pad_left, rect.top() + pad_top, inner_width_title, fm_title.height())
        painter.drawText(line1_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

        # Line 2: Time Range & Episode Title (crisply aligned with exact same pad_left margin)
        font_sub = QFont(option.font)
        font_sub.setBold(False)
        font_sub.setPointSize(9)
        painter.setFont(font_sub)
        painter.setPen(QColor("#a4b0c2"))

        fm_sub = painter.fontMetrics()
        subtext = f"{time_range} • {ep_title}" if ep_title else time_range
        elided_sub = fm_sub.elidedText(subtext, Qt.TextElideMode.ElideRight, inner_width)
        line2_rect = QRect(rect.left() + pad_left, rect.top() + pad_top + fm_title.height() + 4, inner_width, fm_sub.height())
        painter.drawText(line2_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_sub)

        painter.restore()


class FirstRunWelcomeDialog(QDialog):
    def __init__(self, config_mgr: ConfigManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Kaffeine DVR & TV Guide")
        self.setMinimumWidth(820)
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
                subcontrol-position: top left;
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
                image: url("{CHECKMARK_ICON_PATH}");
            }}
            QCheckBox::indicator:checked:disabled {{
                background-color: #238636;
                border-color: #2ea043;
                image: url("{CHECKMARK_ICON_PATH}");
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
        layout.setSpacing(12)

        title_lbl = QLabel("<b>Welcome to Kaffeine DVR & Web TV Guide</b>")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff; background: transparent;")
        layout.addWidget(title_lbl)

        desc_lbl = QLabel(
            "This application enables online TV guide browsing and DVR scheduling for Kaffeine "
            "without blocking system restarts or shutdowns."
        )
        desc_lbl.setStyleSheet("color: #a4b0c2; font-size: 13px; line-height: 1.4; background: transparent;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        # Environment box
        env_box = QGroupBox("Detected System Environment")
        env_layout = QFormLayout(env_box)

        local_dt = datetime.now().astimezone()
        tz_name = local_dt.tzname() or "Local"
        tz_offset = local_dt.strftime("%z")
        tz_str = f"{tz_name} (UTC{tz_offset[:3]}:{tz_offset[3:]})"

        tz_val = QLabel(f"<b>{tz_str}</b>")
        tz_val.setStyleSheet("font-size: 13px; color: #ffffff; background: transparent;")
        env_layout.addRow("System Timezone:", tz_val)
        tz_note = QLabel("Showtimes and recording timers automatically align with this local timezone.")
        tz_note.setWordWrap(True)
        tz_note.setStyleSheet("color: #a4b0c2; font-size: 12px; background: transparent;")
        env_layout.addRow("", tz_note)

        kaffeine_channels = self.config_mgr.get_scanned_kaffeine_channels()
        if kaffeine_channels:
            ch_status = f"{len(kaffeine_channels)} scanned channels found in Kaffeine"
        else:
            ch_status = "No scanned channels found yet (Kaffeine scan not performed)"
        ch_val = QLabel(f"<b>{ch_status}</b>")
        ch_val.setStyleSheet("font-size: 13px; color: #ffffff; background: transparent;")
        env_layout.addRow("Kaffeine Tuner:", ch_val)
        layout.addWidget(env_box)

        # TV Guide and Regional Channel Coverage Explanation
        guide_info_box = QGroupBox("TV Guide Coverage and Providers")
        guide_info_layout = QVBoxLayout(guide_info_box)

        guide_info_text = QLabel(
            "<b>TV Guide Sources and How Listings Work:</b><br>"
            "• <b>TVMaze API (Zero Configuration Required - Works Out of the Box):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;Major broadcast networks (<b>FOX, CBS, NBC, ABC, PBS, and The CW</b>) work immediately with <b>zero setup, no account, and no API keys required</b>. "
            "The moment the app starts, TVMaze automatically downloads up to 7 days of prime-time listings for all mapped national channels.<br><br>"
            "• <b>National Programming vs. Local Daytime Programming:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;Because TVMaze tracks national network schedules, it covers all nationally broadcast prime-time series, network specials, and national sports. "
            "However, broadcast networks relinquish morning, midday, and late-afternoon blocks to local affiliates. Consequently, <b>local news broadcasts, daytime syndicated talk shows, game shows, and independent local subchannels</b> "
            "are not included in TVMaze's national feed.<br><br>"
            "• <b>Getting 24/7 Local & Regional Schedules (TV Passport):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;If you want full 24/7 continuous coverage including local morning/evening news and daytime shows, or listings for local independent subchannels, configure free station IDs via TV Passport:<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;1. Look up your local affiliate station ID on <a href='https://www.tvpassport.com' style='color: #64b5f6; font-weight: bold;'>tvpassport.com</a>.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;2. Enter <code>ChannelName = StationID</code> in <i>Settings &gt; Guide Sources &gt; TV Passport</i> and click <i>Save Station IDs</i>.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;3. The app connects and immediately syncs complete 24/7 local listings in the background.<br><br>"
            "• <b>Free Hybrid Mode (Best of Both Worlds):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;Running both sources together is the default mode. For channels where you enter a TV Passport station ID, TV Passport automatically takes over to provide 24/7 local affiliate listings, "
            "while TVMaze seamlessly covers any remaining national channels with zero setup and no duplicate entries."
        )
        guide_info_text.setWordWrap(True)
        guide_info_text.setOpenExternalLinks(True)
        guide_info_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        guide_info_text.setStyleSheet("color: #d1d8e0; font-size: 12px; line-height: 1.5; background: transparent;")
        guide_info_layout.addWidget(guide_info_text)

        # Check for unconfigured regional channels
        unconfigured_regional = self.config_mgr.get_unconfigured_regional_channels()
        if unconfigured_regional:
            ch_list_str = ", ".join(unconfigured_regional)
            notice_lbl = QLabel(
                f"<div style='border: 1px solid #c8832a; border-radius: 4px; background-color: #2b2214; padding: 8px 12px; color: #ffc107; font-size: 12px; line-height: 1.4;'>"
                f"<b>Notice:</b> The following scanned channel(s) are local/regional and not covered by national feeds: "
                f"<b>{ch_list_str}</b>.<br>"
                f"You can configure their free station ID under <b>Settings &gt; Guide Sources &gt; TV Passport</b> after startup.</div>"
            )
            notice_lbl.setWordWrap(True)
            guide_info_layout.addWidget(notice_lbl)

        layout.addWidget(guide_info_box)

        options_box = QGroupBox("Initial Setup Options")
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

        self.service_check = QCheckBox("Enable & start background recording dispatcher service (systemd)")
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
    stylesheet = APP_STYLESHEET.replace("__CHECKMARK_ICON_PATH__", CHECKMARK_ICON_PATH)
    app.setStyleSheet(stylesheet)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kaffeine DVR & Web TV Guide")
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
        main_layout.addLayout(self.create_status_banner())

        # Main Tabs
        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.addTab(self.create_recordings_tab(), "Recordings Schedule")
        self.tabs.addTab(self.create_guide_tab(), "Web TV Guide Browser")
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

        # Column 0: Left spacer (takes equal stretch as column 2)
        left_spacer = QWidget()
        banner.addWidget(left_spacer, 0, 0, Qt.AlignmentFlag.AlignLeft)

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
        self.rec_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.rec_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.rec_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.rec_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.rec_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.rec_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.rec_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.rec_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rec_table.itemDoubleClicked.connect(self._on_rec_table_double_clicked)
        active_layout.addWidget(self.rec_table)

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
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        history_layout.addWidget(self.history_table)

        self.recordings_subtabs.addTab(history_widget, "History")

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
        filter_bar.addSpacing(12)

        # Quick Time Jump Controls (useful in Grid View)
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

        self.jump_prime_btn = QPushButton("Prime Time (8 PM)")
        self.jump_prime_btn.setToolTip("Scroll guide grid to 8:00 PM evening prime time")
        self.jump_prime_btn.setStyleSheet(jump_btn_style)
        self.jump_prime_btn.clicked.connect(self.jump_guide_to_primetime)
        filter_bar.addWidget(self.jump_prime_btn)
        filter_bar.addSpacing(14)

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

        filter_bar.addWidget(QLabel("Channel:"))
        self.guide_channel_combo = QComboBox()
        self.guide_channel_combo.addItem("All")
        channels = self.config_mgr.get_ordered_channels()
        self.guide_channel_combo.addItems(channels)
        self.guide_channel_combo.currentIndexChanged.connect(self.filter_guide)
        filter_bar.addWidget(self.guide_channel_combo)

        filter_bar.addWidget(QLabel("Search:"))
        self.guide_search_input = QLineEdit()
        self.guide_search_input.setPlaceholderText("Filter shows...")
        self.guide_search_input.textChanged.connect(self.filter_guide)
        filter_bar.addWidget(self.guide_search_input)

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
        self.guide_grid_table.setItemDelegate(ProgramTileDelegate(self.guide_grid_table))
        self.guide_grid_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.guide_grid_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.guide_grid_table.cellClicked.connect(self.on_grid_cell_clicked)
        self.guide_stack.addWidget(self.guide_grid_table)

        # 2. Existing Detailed List Table
        self.guide_table = QTableWidget()
        self.guide_table.setColumnCount(6)
        self.guide_table.setHorizontalHeaderLabels(["REC", "Start Time", "Channel", "Show Title", "Episode Title", "Duration"])
        self.guide_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.guide_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.guide_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.guide_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.guide_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.guide_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.guide_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.guide_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.guide_table.itemSelectionChanged.connect(self.on_guide_selection_changed)
        self.guide_stack.addWidget(self.guide_table)

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
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.setSpacing(4)
        self.guide_detail_title = QLabel("Select a program to view details")
        self.guide_detail_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.guide_detail_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_layout.addWidget(self.guide_detail_title)

        self.guide_detail_text = QTextEdit()
        self.guide_detail_text.setReadOnly(True)
        # Size description box to fit approximately 4 lines of text
        line_height = self.guide_detail_text.fontMetrics().lineSpacing()
        doc_margin = int(self.guide_detail_text.document().documentMargin())
        desc_height = line_height * 4 + doc_margin * 2 + 6
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
        self.settings_subtabs.addTab(self.create_settings_guide_tab(), "Guide Sources and Health")
        self.settings_subtabs.addTab(self.create_settings_channels_tab(), "Channels Lineup")
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
        health_layout = QVBoxLayout(health_box)

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
        self.health_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.health_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.health_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.health_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.health_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.health_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
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
        pass_instructions.setStyleSheet("color: #b0bac8; font-size: 11px; line-height: 1.4;")
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

    # Subcategory 2: Channels Lineup
    def create_settings_channels_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("<b>Kaffeine Channel Lineup & Guide Network Mapping</b>:"))
        desc = QLabel(
            "Reorder rows in your EPG TV Guide using drag-and-drop or the Move Up/Down buttons.\n"
            "Map external guide broadcast network names to your exact Kaffeine tuned channel names on the right."
        )
        desc.setStyleSheet("color: #6c757d; font-size: 11px;")
        layout.addWidget(desc)

        # Splitter / Two-panel layout
        lineup_panels = QHBoxLayout()

        # Left Panel: Interactive Channel Order List
        order_box = QGroupBox("TV Guide Channel Order (Manual Priority)")
        order_layout = QVBoxLayout(order_box)

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

        # Right Panel: Channel & Network Mapping
        map_box = QGroupBox("Guide Network Mapping (Name = Channel)")
        map_layout = QVBoxLayout(map_box)

        self.mapping_text = QTextEdit()
        mapping_str = "\n".join([f"{k} = {v}" for k, v in self.config_mgr.channel_map.items()])
        self.mapping_text.setPlainText(mapping_str)
        self.mapping_text.setMinimumHeight(200)
        map_layout.addWidget(self.mapping_text)

        lineup_panels.addWidget(map_box, 1)
        layout.addLayout(lineup_panels)

        # Bottom Button Row
        btn_row = QHBoxLayout()
        import_kaffeine_btn = QPushButton("Import Channels from Kaffeine")
        import_kaffeine_btn.clicked.connect(lambda: self.import_channels_from_kaffeine(silent=False))
        btn_row.addWidget(import_kaffeine_btn)

        save_mapping_btn = QPushButton("Save Channel Lineup")
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
        layout = QVBoxLayout(container)

        layout.addWidget(QLabel("<b>DVR Automation & Polling Frequencies</b>:"))
        form = QFormLayout()

        self.lead_time_spin = QSpinBox()
        self.lead_time_spin.setRange(1, 60)
        self.lead_time_spin.setValue(self.config_mgr.lead_time_mins)
        self.lead_time_spin.setSuffix(" minutes")
        lead_time_lbl = QLabel(
            "Minutes before show start time to auto-launch Kaffeine and arm recording timer.\n"
            "Keeping this low (e.g. 5m) prevents Kaffeine from blocking system reboots and shutdowns."
        )
        lead_time_lbl.setStyleSheet("color: #6c757d; font-size: 11px;")
        form.addRow("Just-In-Time Lead Time:", self.lead_time_spin)
        form.addRow("", lead_time_lbl)

        self.end_buffer_spin = QSpinBox()
        self.end_buffer_spin.setRange(0, 180)
        self.end_buffer_spin.setValue(self.config_mgr.end_buffer_mins)
        self.end_buffer_spin.setSuffix(" minutes")
        end_buffer_lbl = QLabel(
            "Extra post-roll buffer added to the end of scheduled recordings to avoid clipping broadcast overruns."
        )
        end_buffer_lbl.setStyleSheet("color: #6c757d; font-size: 11px;")
        form.addRow("Default End Buffer:", self.end_buffer_spin)
        form.addRow("", end_buffer_lbl)

        self.auto_buffer_sports_check = QCheckBox("Automatically Extend Sports Broadcasts")
        self.auto_buffer_sports_check.setChecked(self.config_mgr.auto_buffer_sports)
        self.sports_buffer_spin = QSpinBox()
        self.sports_buffer_spin.setRange(0, 180)
        self.sports_buffer_spin.setValue(self.config_mgr.sports_buffer_mins)
        self.sports_buffer_spin.setSuffix(" minutes")
        sports_row = QHBoxLayout()
        sports_row.addWidget(self.auto_buffer_sports_check)
        sports_row.addSpacing(15)
        sports_row.addWidget(QLabel("Sports Buffer:"))
        sports_row.addWidget(self.sports_buffer_spin)
        sports_row.addStretch()
        sports_buffer_lbl = QLabel("Applies extended post-roll padding to live sporting events, games, and matches.")
        sports_buffer_lbl.setStyleSheet("color: #6c757d; font-size: 11px;")
        form.addRow("Sports Auto-Extend:", sports_row)
        form.addRow("", sports_buffer_lbl)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(30, 600)
        self.interval_spin.setSingleStep(30)
        self.interval_spin.setValue(self.config_mgr.watcher_interval_seconds)
        self.interval_spin.setSuffix(" seconds")
        interval_lbl = QLabel("How often the background watcher service checks the DVR queue for upcoming shows.")
        interval_lbl.setStyleSheet("color: #6c757d; font-size: 11px;")
        form.addRow("Watcher Polling Frequency:", self.interval_spin)
        form.addRow("", interval_lbl)

        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 14)
        self.days_spin.setValue(self.config_mgr.guide_days_ahead)
        self.days_spin.setSuffix(" days")
        days_lbl = QLabel("How many future days to query and cache in the local SQLite guide database.")
        days_lbl.setStyleSheet("color: #6c757d; font-size: 11px;")
        form.addRow("Guide Cache Horizon:", self.days_spin)
        form.addRow("", days_lbl)

        self.launch_mode_combo = QComboBox()
        self.launch_mode_combo.addItem("Minimized to Taskbar (Panel)", "taskbar")
        self.launch_mode_combo.addItem("Minimize to System Tray (-m minimal mode)", "tray")
        self.launch_mode_combo.addItem("Normal Window (Visible on desktop)", "normal")
        cur_mode = self.config_mgr.launch_mode
        mode_idx = self.launch_mode_combo.findData(cur_mode)
        if mode_idx >= 0:
            self.launch_mode_combo.setCurrentIndex(mode_idx)

        launch_mode_lbl = QLabel(
            "Controls how Kaffeine starts when armed for recording:\n"
            "• Minimized to Taskbar: Quietly minimizes to your panel taskbar without touching the tray.\n"
            "• Minimize to System Tray: Starts in minimal mode (-m) and docks into the KDE tray (if enabled in Kaffeine).\n"
            "• Normal Window: Opens as an active visible window on your desktop."
        )
        launch_mode_lbl.setStyleSheet("color: #8c98aa; font-size: 11px;")
        form.addRow("Window Launch Mode:", self.launch_mode_combo)
        form.addRow("", launch_mode_lbl)

        self.notify_check = QCheckBox("Show Persistent Desktop Notification on Record Launch")
        self.notify_check.setChecked(self.config_mgr.enable_desktop_notifications)
        notify_lbl = QLabel(
            "Sends a desktop notification via notify-send when Kaffeine is launched and armed for a scheduled show.\n"
            "The notification persists in your notification center until explicitly dismissed."
        )
        notify_lbl.setStyleSheet("color: #6c757d; font-size: 11px;")
        form.addRow("Notifications:", self.notify_check)
        form.addRow("", notify_lbl)

        # Application Window Dimensions
        self.win_size_lbl = QLabel(self._get_window_size_label_text())
        self.win_size_lbl.setStyleSheet("color: #a0b2c6; font-size: 11px;")
        win_size_row = QHBoxLayout()
        win_size_row.addWidget(self.win_size_lbl)
        win_size_row.addSpacing(12)

        self.save_win_size_btn = QPushButton("Save Current Window Size")
        self.save_win_size_btn.setObjectName("primaryActionBtn")
        self.save_win_size_btn.setToolTip("Saves the current width and height of this window to restore whenever the app opens")
        self.save_win_size_btn.clicked.connect(self.save_current_window_size)
        win_size_row.addWidget(self.save_win_size_btn)

        self.reset_win_size_btn = QPushButton("Reset to Default (1100 × 750)")
        self.reset_win_size_btn.setToolTip("Resets the saved window dimensions to standard default")
        self.reset_win_size_btn.clicked.connect(self.reset_window_size_to_default)
        win_size_row.addWidget(self.reset_win_size_btn)
        win_size_row.addStretch()

        win_size_desc = QLabel("Resize the application to your preferred width and height, then click 'Save Current Window Size' to lock it in.")
        win_size_desc.setStyleSheet("color: #6c757d; font-size: 11px;")
        form.addRow("Application Window Size:", win_size_row)
        form.addRow("", win_size_desc)

        self.lead_time_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.end_buffer_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.auto_buffer_sports_check.stateChanged.connect(self._auto_save_automation_settings)
        self.sports_buffer_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.interval_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.days_spin.valueChanged.connect(self._auto_save_automation_settings)
        self.launch_mode_combo.currentIndexChanged.connect(self._auto_save_automation_settings)
        self.notify_check.stateChanged.connect(self._auto_save_automation_settings)

        layout.addLayout(form)
        layout.addSpacing(10)

        # Storage & Auto-Cleanup Section
        storage_box = QGroupBox("Storage & Video Retention (Auto-Delete Old Recordings)")
        storage_layout = QVBoxLayout(storage_box)

        # Disk space status display
        self.storage_status_lbl = QLabel("Checking storage space...")
        self.storage_status_lbl.setStyleSheet("font-weight: bold; font-size: 12px; color: #55a84c;")
        storage_layout.addWidget(self.storage_status_lbl)

        storage_form = QFormLayout()
        self.cleanup_enable_check = QCheckBox("Enable Automatic Video Cleanup")
        self.cleanup_enable_check.setChecked(self.config_mgr.auto_cleanup_enabled)
        self.cleanup_enable_check.stateChanged.connect(self._auto_save_automation_settings)
        storage_form.addRow("Auto-Cleanup:", self.cleanup_enable_check)

        self.retention_days_spin = QSpinBox()
        self.retention_days_spin.setRange(0, 365)
        self.retention_days_spin.setValue(self.config_mgr.retention_days)
        self.retention_days_spin.setSuffix(" days")
        self.retention_days_spin.valueChanged.connect(self._auto_save_automation_settings)
        retention_lbl = QLabel("Delete recordings older than this age. Set to 0 to disable age-based pruning.")
        retention_lbl.setStyleSheet("color: #6c757d; font-size: 11px;")
        storage_form.addRow("Retention Window:", self.retention_days_spin)
        storage_form.addRow("", retention_lbl)

        self.min_free_spin = QSpinBox()
        self.min_free_spin.setRange(0, 1000)
        self.min_free_spin.setSingleStep(5)
        self.min_free_spin.setValue(self.config_mgr.min_free_disk_gb)
        self.min_free_spin.setSuffix(" GB")
        self.min_free_spin.valueChanged.connect(self._auto_save_automation_settings)
        free_lbl = QLabel("If free disk space drops below this limit, oldest unprotected recordings are purged first.")
        free_lbl.setStyleSheet("color: #6c757d; font-size: 11px;")
        storage_form.addRow("Minimum Free Space:", self.min_free_spin)
        storage_form.addRow("", free_lbl)

        # Custom recording folder override
        detected_folder = str(self.storage_mgr.get_recording_folder())
        folder_row = QHBoxLayout()
        self.custom_folder_input = QLineEdit()
        self.custom_folder_input.setText(self.config_mgr.custom_recording_folder)
        self.custom_folder_input.setPlaceholderText(f"Auto-detected from Kaffeine: {detected_folder}")
        self.custom_folder_input.textChanged.connect(self._auto_save_automation_settings)
        folder_row.addWidget(self.custom_folder_input)
        self.browse_folder_btn = QPushButton("Browse...")
        self.browse_folder_btn.clicked.connect(self.browse_custom_recording_folder)
        folder_row.addWidget(self.browse_folder_btn)
        storage_form.addRow("Recording Folder:", folder_row)

        storage_layout.addLayout(storage_form)

        # Storage Action Buttons
        storage_btn_row = QHBoxLayout()
        self.run_cleanup_btn = QPushButton("Run Retention Cleanup Now")
        self.run_cleanup_btn.setStyleSheet("color: #ff5252; font-weight: bold;")
        self.run_cleanup_btn.clicked.connect(self.run_manual_cleanup)
        storage_btn_row.addWidget(self.run_cleanup_btn)

        self.refresh_storage_btn = QPushButton("Refresh Disk Usage")
        self.refresh_storage_btn.clicked.connect(self.update_storage_status_ui)
        storage_btn_row.addWidget(self.refresh_storage_btn)
        storage_btn_row.addStretch()
        storage_layout.addLayout(storage_btn_row)

        layout.addWidget(storage_box)
        layout.addSpacing(15)

        # Service Management Section
        service_box = QGroupBox("Unified Background Service (kaffeine-dvr-watcher.service)")
        service_layout = QVBoxLayout(service_box)
        
        self.service_status_lbl = QLabel("Checking service status...")
        self.service_status_lbl.setStyleSheet("font-weight: bold; font-size: 12px;")
        service_layout.addWidget(self.service_status_lbl)

        svc_desc = QLabel(
            "The background daemon dispatches recordings just-in-time and synchronizes guide data periodically.\n"
            "It runs under systemd user mode and persists automatically across system reboots."
        )
        svc_desc.setStyleSheet("color: #8c98aa; font-size: 11px;")
        service_layout.addWidget(svc_desc)

        svc_btn_row = QHBoxLayout()
        self.start_svc_btn = QPushButton("Start & Enable Service")
        self.start_svc_btn.clicked.connect(self.start_background_service)
        svc_btn_row.addWidget(self.start_svc_btn)

        self.restart_svc_btn = QPushButton("Restart Service")
        self.restart_svc_btn.clicked.connect(self.restart_background_service)
        svc_btn_row.addWidget(self.restart_svc_btn)
        svc_btn_row.addStretch()
        service_layout.addLayout(svc_btn_row)

        layout.addWidget(service_box)
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    # ------------------ TAB 5: HELP AND INFORMATION ------------------
    def create_help_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)

        # Header Title
        title_box = QWidget()
        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 0, 0)
        h1 = QLabel("<b>Kaffeine DVR and TV Guide - Help and Reference Guide</b>")
        h1.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        h1_sub = QLabel(
            "Overview of features, automatic scheduling, power management, and TV guide configuration."
        )
        h1_sub.setStyleSheet("color: #a0b2c6; font-size: 14px;")
        title_layout.addWidget(h1)
        title_layout.addWidget(h1_sub)
        layout.addWidget(title_box)

        group_style = "QGroupBox { font-size: 15px; font-weight: bold; margin-top: 6px; padding-top: 14px; } QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        body_style = "color: #d8e2ee; font-size: 14px; line-height: 1.6;"

        # Section 1: Core Concept and Why this App Exists
        concept_box = QGroupBox("1. How Kaffeine DVR Scheduling Works (Safe Reboots and Shutdowns)")
        concept_box.setStyleSheet(group_style)
        concept_layout = QVBoxLayout(concept_box)
        concept_text = QLabel(
            "• <b>The Problem with Native Kaffeine Timers:</b> Whenever timers are active directly inside Kaffeine, "
            "Kaffeine inhibits Linux system restarts and shutdowns to prevent losing recordings.<br><br>"
            "• <b>Just-In-Time (JIT) Dispatching:</b> This application stores upcoming recordings in an external queue "
            "(<code>recordings_queue.sqlite</code>) rather than inside Kaffeine immediately. Kaffeine remains clean with 0 active timers.<br><br>"
            "• <b>Unified Background Watcher Daemon:</b> A single background service (<code>kaffeine-dvr-watcher.service</code>) handles both queue monitoring and periodic TV guide synchronizations. "
            "When a show is about to start (e.g. 5 minutes before showtime), it automatically launches Kaffeine minimized to your taskbar "
            "and arms the recording via D-Bus Just-In-Time.<br><br>"
            "• <b>Safe Power Operations:</b> You can reboot or power off your computer at any time without Kaffeine freezing or blocking systemd."
        )
        concept_text.setWordWrap(True)
        concept_text.setStyleSheet(body_style)
        concept_layout.addWidget(concept_text)
        layout.addWidget(concept_box)

        # Section 2: Guide Sources & Coverage
        sources_box = QGroupBox("2. TV Guide Coverage and Providers")
        sources_box.setStyleSheet(group_style)
        sources_layout = QVBoxLayout(sources_box)
        sources_text = QLabel(
            "• <b>National Broadcast Networks (TVMaze API - Zero Configuration Required):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;Networks like <b>FOX, CBS, NBC, ABC, PBS, and The CW</b> work out of the box with <b>zero configuration</b>. "
            "No account, API keys, or manual setup are required—TVMaze automatically synchronizes up to 7 days of prime-time listings immediately upon launch.<br><br>"
            "• <b>Understanding National Feeds vs. Local Daytime Programming:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;TVMaze tracks national network schedules, which includes all major prime-time dramas, comedies, national sports, and network specials. "
            "However, US broadcast networks delegate midday and daytime time-slots to regional affiliates. As a result, <b>local news, syndicated morning/daytime talk shows, game shows, and local independent subchannels</b> "
            "do not appear in TVMaze's national feed.<br><br>"
            "• <b>Getting 24/7 Local Affiliate Schedules & Regional Subchannels (TV Passport):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;To obtain continuous 24/7 schedules including local news and daytime programming, or to support independent local channels, use TV Passport in <i>Settings &gt; Guide Sources &gt; TV Passport</i>:<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;1. Look up your local affiliate station on <a href='https://www.tvpassport.com' style='color: #64b5f6; font-weight: bold;'>tvpassport.com</a>.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;2. Copy the numeric station ID from the URL and enter <code>ChannelName = StationID</code>.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;3. Click <i>Save Station IDs</i>. The app immediately verifies the station and downloads full 24/7 local affiliate listings in the background.<br><br>"
            "• <b>Free Hybrid Mode (Recommended & Default):</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;Running TVMaze and TV Passport together is seamless. TV Passport provides complete 24/7 local schedules for any stations you configure with IDs, "
            "while TVMaze automatically fills in listings for any remaining national networks with zero configuration and no duplicate rows.<br><br>"
            "• <b>Additional Custom Providers & International Support:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;You can also connect a custom local XMLTV file or remote URL, or use a paid Schedules Direct (Gracenote) account for international listings."
        )
        sources_text.setWordWrap(True)
        sources_text.setOpenExternalLinks(True)
        sources_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        sources_text.setStyleSheet(body_style)
        sources_layout.addWidget(sources_text)
        layout.addWidget(sources_box)

        # Section 3: Step-by-Step Feature Walkthrough
        guide_box = QGroupBox("3. Feature Walkthrough")
        guide_box.setStyleSheet(group_style)
        guide_layout = QVBoxLayout(guide_box)
        guide_text = QLabel(
            "• <b>Recordings Schedule Tab:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;View all upcoming queued recordings, their scheduled start time, duration, and status. "
            "You can manually add one-off recordings or cancel scheduled shows here.<br><br>"
            "• <b>Web TV Guide Browser Tab:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;Browse cached 7-day TV listings by date and channel. Filter by show title, view episode summaries, "
            "and click <i>Record This Program</i> or <i>Auto-Record This Series</i> directly from the listings.<br><br>"
            "• <b>Auto-Record Rules Tab:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;Create series recording rules (e.g. record any show titled <i>'NBA Basketball'</i> or <i>'News'</i>). "
            "The system checks the guide periodically and automatically schedules any newly matching episodes. Use <i>Edit Rule</i> "
            "or double-click any row to update rule keywords, channel filters, or enable/disable them.<br><br>"
            "• <b>Settings Tab:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<b>Guide Sources & Health:</b> Monitor provider status codes and latency in real time.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<b>Channels Lineup:</b> Import your scanned digital TV channels directly from Kaffeine with one click.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<b>Automation & DVR:</b> Configure lead time (default: 5 min), taskbar minimization, and persistent desktop notifications."
        )
        guide_text.setWordWrap(True)
        guide_text.setStyleSheet(body_style)
        guide_layout.addWidget(guide_text)
        layout.addWidget(guide_box)

        # Section 4: Background Service and System Commands
        services_box = QGroupBox("4. Unified Background Service and Commands")
        services_box.setStyleSheet(group_style)
        services_layout = QVBoxLayout(services_box)
        services_text = QLabel(
            "• <b>Unified Background Daemon:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<code>kaffeine-dvr-watcher.service</code> : Single unified background daemon that monitors the recording queue "
            "and periodically synchronizes guide data (default every 6 hours).<br><br>"
            "• <b>Configurable Window Launch Modes:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;In <i>Settings &gt; Automation &amp; DVR</i>, you can choose how Kaffeine opens when armed for recording:<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;1. <b>Minimized to Taskbar (Default):</b> Minimizes quietly to your KDE taskbar panel via <code>kdotool</code> (or <code>xdotool</code>). "
            "Preserves menus and toolbars, avoids system tray clutter, and never affects manual launches from your pinned icon.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;2. <b>Minimize to System Tray:</b> Starts with the <code>-m</code> flag (minimal mode) to dock into the KDE system tray (if enabled in Kaffeine).<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;3. <b>Normal Window:</b> Opens as a standard visible window on your desktop.<br><br>"
            "• <b>Command Line Tool:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<code>kaffeine-dvr --status</code> : Print provider health, cache counts, and Kaffeine status.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<code>kaffeine-dvr --list</code>   : List all scheduled recordings in the DVR queue.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<code>kaffeine-dvr --sync</code>   : Force an immediate TV guide download.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<code>kaffeine-dvr --rules</code>  : Evaluate series auto-record rules immediately.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<code>kaffeine-dvr --watch</code>  : Run the watcher dispatcher in foreground debug mode.<br><br>"
            "• <b>Managing the Background Service:</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<code>systemctl --user status kaffeine-dvr-watcher.service</code> : Check daemon running state.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<code>systemctl --user restart kaffeine-dvr-watcher.service</code> : Restart the background daemon.<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;<code>journalctl --user -u kaffeine-dvr-watcher.service -f</code> : Follow live daemon logs."
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
            self.health_table.setItem(row, 5, QTableWidgetItem(details))

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
                    f"<div style='border: 1px solid #c8832a; border-radius: 6px; background-color: #2b2214; padding: 10px 14px; color: #ffc107; font-size: 11px; margin-top: 6px; margin-bottom: 8px; line-height: 1.4;'>"
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
                f"Review the mappings above and click 'Save Channel Lineup' to persist."
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

    def reset_window_size_to_default(self):
        self.settings.remove("custom_window_width")
        self.settings.remove("custom_window_height")
        self.settings.remove("geometry")
        self.settings.sync()
        self.resize(1100, 750)
        if hasattr(self, "win_size_lbl"):
            self.win_size_lbl.setText(self._get_window_size_label_text())
        self.flash_save_indicator("Window Size Reset (1100 × 750)")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "win_size_lbl"):
            self.win_size_lbl.setText(self._get_window_size_label_text())

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
                buf_msg = f" (+{buf}m buffer)" if buf > 0 else ""
                self.status_bar.showMessage(f"Queued recording '{title}'{buf_msg} (Queue #{qid})", 4000)
                self.refresh_recordings()
            except Exception as e:
                QMessageBox.critical(self, "Scheduling Error", str(e))

    def _on_main_tab_changed(self, index: int):
        # When switching to the TV Guide Browser tab (index 1)
        if index == 1:
            self.refresh_date_dropdown()
            sel_date = self.guide_date_combo.currentData()
            today_str = date.today().strftime("%Y-%m-%d")
            if sel_date == today_str or sel_date is None:
                QTimer.singleShot(60, self.jump_guide_to_now)
            else:
                QTimer.singleShot(60, self.jump_guide_to_noon)

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
        if not center or slot <= 0:
            bar.setValue(max(0, min(bar.maximum(), slot)))
            return

        vp_width = self.guide_grid_table.viewport().width()
        col_width = self.guide_grid_table.horizontalHeader().defaultSectionSize() or 165
        cols_visible = max(1, vp_width // col_width)
        target_col = max(0, slot - (cols_visible // 2))
        bar.setValue(min(bar.maximum(), target_col))

    def jump_guide_to_now(self):
        now = datetime.now()
        now_slot = max(0, min(47, (now.hour * 60 + now.minute) // 30))

        # Check currently active programs in the grid to find the earliest starting slot
        # among programs currently airing (start <= now < end).
        # We clamp to at most 2 slots (1 hour) before now_slot so we don't jump too far back.
        target_slot = now_slot
        if hasattr(self, "current_guide_items") and self.current_guide_items:
            earliest_slot = now_slot
            for p in self.current_guide_items:
                start_iso = p.get("start_iso")
                if not start_iso:
                    continue
                try:
                    p_start = datetime.fromisoformat(start_iso)
                    dur_iso = p.get("duration_iso") or "00:30:00"
                    parts = [int(x) for x in dur_iso.split(":")]
                    dur = timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2] if len(parts) > 2 else 0)
                    p_end = p_start + dur
                    if p_start <= now < p_end:
                        p_slot = (p_start.hour * 60 + p_start.minute) // 30
                        if p_slot < earliest_slot:
                            earliest_slot = p_slot
                except Exception:
                    continue
            target_slot = max(max(0, now_slot - 2), earliest_slot)

        self._scroll_grid_to_slot(target_slot, center=False)

    def jump_guide_to_start(self):
        self._scroll_grid_to_slot(0, center=False)

    def jump_guide_to_noon(self):
        # 12:00 PM (Noon) is hour 12 -> slot 24
        self._scroll_grid_to_slot(24, center=False)

    def jump_guide_to_primetime(self):
        # 8:00 PM is 20:00 -> slot 40
        self._scroll_grid_to_slot(40, center=False)

    def _create_day_nav_bar(self) -> QWidget:
        container = QWidget()
        container.setObjectName("dayNavBar")
        nav_layout = QHBoxLayout(container)
        nav_layout.setContentsMargins(0, 4, 0, 2)
        nav_layout.setSpacing(6)

        arrow_style = (
            "QPushButton { font-size: 15px; font-weight: bold; "
            "border: 1px solid #303746; border-radius: 4px; background-color: #1e2330; color: #a4b0c2; }"
            "QPushButton:hover { background-color: #262e3f; border: 1px solid #455470; color: #e2e8f0; }"
            "QPushButton:disabled { background-color: #161a22; border: 1px solid #242935; color: #434a58; }"
        )

        self.day_nav_prev_btn = QPushButton("◀")
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
            btn.clicked.connect(self._make_day_nav_handler(btn))
            nav_layout.addWidget(btn, 1)
            self.day_nav_buttons.append(btn)

        self.day_nav_next_btn = QPushButton("▶")
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
        self.day_nav_offset = max(0, getattr(self, "day_nav_offset", 0) - 7)
        self._update_day_nav_bar(sync_week_with_selection=False)

    def _on_day_nav_next(self):
        self.day_nav_offset = min(7, getattr(self, "day_nav_offset", 0) + 7)
        self._update_day_nav_bar(sync_week_with_selection=False)

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
                days_ahead = (sel_date - today).days
                day_of_week_idx = (sel_date.weekday() + 1) % 7
                nominal_offset0 = (day_of_week_idx - today_idx) % 7
                if days_ahead >= nominal_offset0 + 7:
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
        self.guide_table.setRowCount(len(programs))
        for row, p in enumerate(programs):
            ch = (p.get("kaffeine_channel") or "").strip().lower()
            start_iso = (p.get("start_iso") or "")[:16]
            rec_info = active_scheduled.get((ch, start_iso))

            rec_item = QTableWidgetItem("● REC" if rec_info else "")
            rec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if rec_info:
                rec_item.setForeground(QColor("#ff5252"))
                rec_item.setFont(QFont("", -1, QFont.Weight.Bold))
                buf_val = rec_info.get("buffer_mins", 0)
                buf_tip = f" | +{buf_val}m buffer" if buf_val else ""
                rec_item.setToolTip(f"Recording Scheduled (Queue #{rec_info.get('id')} - {rec_info.get('status')}{buf_tip})")
            self.guide_table.setItem(row, 0, rec_item)

            self.guide_table.setItem(row, 1, QTableWidgetItem(p.get("start_time_local", "")))
            self.guide_table.setItem(row, 2, QTableWidgetItem(p.get("kaffeine_channel", "")))
            self.guide_table.setItem(row, 3, QTableWidgetItem(p.get("show_title", "")))
            self.guide_table.setItem(row, 4, QTableWidgetItem(p.get("episode_title", "")))
            self.guide_table.setItem(row, 5, QTableWidgetItem(p.get("duration_iso", "")))

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

                # Annotate program metadata for delegate renderer
                p_copy = dict(p)
                p_copy["_time_range"] = time_range
                p_copy["_category"] = classify_guide_category(p)
                p_copy["_scheduled_rec"] = scheduled_rec

                item = QTableWidgetItem(show_title)
                item.setData(Qt.ItemDataRole.UserRole, p_copy)
                
                # Visual styling
                item.setBackground(tile_bg if (idx % 2 == 0) else tile_bg_alt)
                item.setForeground(tile_text_color)

                self.guide_grid_table.setItem(row_idx, start_col, item)

                # For spanned columns, fill with ghost items referencing program data so clicking anywhere works
                for c in range(start_col + 1, start_col + span):
                    ghost = QTableWidgetItem()
                    ghost.setData(Qt.ItemDataRole.UserRole, p_copy)
                    ghost.setBackground(tile_bg if (idx % 2 == 0) else tile_bg_alt)
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
            if hasattr(self, "record_guide_btn"):
                self.record_guide_btn.setText("Record This Program")
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

        header_prefix = ""
        if rec_info:
            qid = rec_info.get("id")
            st = rec_info.get("status", "QUEUED")
            buf_val = rec_info.get("buffer_mins", 0)
            buf_txt = f" | Buffer: +{buf_val}m" if buf_val else ""
            header_prefix = f"<span style='color: #ff5252; font-weight: bold;'>[● REC QUEUED #{qid} - {st}{buf_txt}]</span> "

        # Color-code the show title by its category (sports=orange, news=blue, movies=red, tvshows=green)
        cat = prog.get("_category") or classify_guide_category(prog)
        if cat == "sports":
            title_color_hex = "#ffa028"  # Orange
        elif cat == "news":
            title_color_hex = "#4fc3f7"  # Blue
        elif cat == "movies":
            title_color_hex = "#ff5c5c"  # Red
        else:
            title_color_hex = "#66bb6a"  # Green

        escaped_title = html.escape(title)
        colored_title = f"<span style='color: {title_color_hex}; font-weight: bold;'>{escaped_title}</span>"

        details_parts = []
        if ep:
            details_parts.append(f" - &quot;{html.escape(ep)}&quot;")
        if season and number:
            details_parts.append(f" (S{season:02d}E{number:02d})")
        details_parts.append(f" on {html.escape(str(channel))} at {html.escape(str(start))}")
        rest_of_header = "".join(details_parts)

        self.guide_detail_title.setText(header_prefix + colored_title + rest_of_header)
        self.guide_detail_text.setText(summary)

        if hasattr(self, "record_guide_btn"):
            if rec_info:
                self.record_guide_btn.setText("Adjust Buffer...")
            else:
                self.record_guide_btn.setText("Record This Program")

        if hasattr(self, "cancel_guide_btn"):
            self.cancel_guide_btn.setVisible(rec_info is not None)

    def on_guide_selection_changed(self):
        row = self.guide_table.currentRow()
        if row < 0 or row >= len(getattr(self, "current_guide_items", [])):
            self.guide_detail_title.setText("Select a program to view details")
            self.guide_detail_text.clear()
            if hasattr(self, "record_guide_btn"):
                self.record_guide_btn.setText("Record This Program")
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
            QMessageBox.information(
                self, "Recording Queued",
                f"Successfully added to DVR Queue (Queue #{qid}):\n\n"
                f"'{rec_title}' on {channel}\n"
                f"Airs: {prog.get('start_time_local')}{buf_note}\n\n"
                f"It is safely queued and will automatically launch Kaffeine and arm the timer {lead} minutes before showtime, preventing restart/shutdown blocks in Kaffeine."
            )
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
        self.tabs.setCurrentIndex(0)
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
                self.tabs.setCurrentIndex(0)
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
                self.refresh_recordings()
                if not silent:
                    details = "\n".join([f"- {s['title']} ({s['channel']} at {s['start_time']})" for s in scheduled])
                    QMessageBox.information(self, "New Recordings Scheduled", f"Scheduled {len(scheduled)} shows:\n\n{details}")

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self._auto_save_automation_settings()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
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
