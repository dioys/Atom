"""ui.py - everything you see.

Atom is a small see-through window. You only see:
  * a slim menu bar on top (Upload files, Files, Settings, Pin, hide)
  * your last message (your bubble)
  * Atom's last reply (his bubble)
  * Atom himself (an animated character)
  * the box where you type, and a mic button next to it (click, talk, and
    Atom answers in his bubble just like when you type)

Drag Atom by his body or by any empty space to move him. Drop files anywhere
on him to add them. This file only draws things and reacts to clicks; the
thinking lives in brain.py and the file handling in tools.py.
"""

from __future__ import annotations

import io
import math
import os
import random
import threading
import time
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QObject, QPointF, QRect, QRectF, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

import atomlog
import babble
import backup
import callpanel
import charpack
import checkup
import config
import kokovoice
import robot
import personality
import spotify
import startup
import timeparse
import version
from brain import Brain
from hotkey import GlobalHotkey
from speaker import Speaker, estimate_ms, speakable
from suggestions import Suggester
from tools import FileStore
from voice import EndpointDetector, SpeechError, convert_audio, speech_engine, transcribe
from watcher import FileWatcher

try:  # voice needs Qt's multimedia module; the rest of Atom works without it
    from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSource, QMediaDevices
except ImportError:
    QAudio = QAudioFormat = QAudioSource = QMediaDevices = None

C = config.COLORS


def qcolor(color, alpha: int = 255) -> QColor:
    """A QColor from '#rrggbb' (or another QColor) with the given opacity (0-255)."""
    result = QColor(color)
    result.setAlpha(alpha)
    return result


# ================================================================ HUD helpers
HUD = config.HUD
IS_PLATE = config.THEME == "plate"          # the transmission-plate look (default)
IS_HUD = config.THEME in ("hud", "plate")   # either of the two sharp-cornered looks
PL = config.PLATE


def hud_font(size: float, bold: bool = False, spacing: float = 0.0) -> QFont:
    """The HUD's lettering: Bahnschrift (comes with Windows 10/11) or Segoe UI."""
    family = "Bahnschrift"
    try:
        if family not in QFontDatabase.families():
            family = "Segoe UI"
    except Exception:
        family = "Segoe UI"
    font = QFont(family)
    font.setPointSizeF(size)
    font.setBold(bold)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def cut_polygon(rect: QRectF, cut: float) -> QPolygonF:
    """A rectangle with its top-left and bottom-right corners cut off (the HUD panel shape)."""
    x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
    return QPolygonF([
        QPointF(x0 + cut, y0), QPointF(x1, y0), QPointF(x1, y1 - cut),
        QPointF(x1 - cut, y1), QPointF(x0, y1), QPointF(x0, y0 + cut),
    ])


# =============================================================== stylesheet
def build_stylesheet() -> str:
    css = _classic_stylesheet()
    if IS_PLATE:
        return css + _plate_stylesheet()
    return css + (_hud_stylesheet() if IS_HUD else "")


def _plate_stylesheet() -> str:
    k = PL
    mono = "Consolas, 'Cascadia Mono', monospace"
    return f"""
    #menuBar {{ background: {k["ink"]}; border: 2px solid {k["crimson"]}; border-radius: 0; }}
    #menuBar QPushButton {{
        background: transparent; border: 0; border-radius: 0; padding: 4px 6px;
        color: {k["paper2"]}; font-family: {mono}; font-size: 11px;
    }}
    #menuBar QPushButton:hover {{ background: {k["crimson"]}; color: {k["ink"]}; }}
    #menuBar QPushButton:checked {{ background: {k["gold"]}; color: {k["ink"]}; }}
    #hudTitle {{ color: {k["gold"]}; }}
    #hudSub {{ color: {k["paper3"]}; }}
    #chatInput {{
        background: {k["ink2"]}; color: {k["paper"]}; border: 0; border-radius: 0;
        border-bottom: 2px solid {k["gold"]}; border-left: 4px solid {k["gold"]};
        padding: 9px 12px 8px 12px; font-family: {mono}; font-size: 13px;
    }}
    #chatInput:focus {{ background: #271c1f; }}
    #micBtn, #speakBtn, #hearBtn, #lookBtn {{
        background: {k["ink"]}; color: {k["paper"]}; font-size: 15px; border-radius: 0;
        border: 2px solid {k["gold"]};
        min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; padding: 0;
    }}
    #micBtn:hover, #speakBtn:hover, #hearBtn:hover, #lookBtn:hover {{ background: {k["ink2"]}; }}
    #micBtn:checked, #hearBtn:checked {{ background: {k["crimson"]}; border-color: {k["crimson"]}; }}
    #speakBtn:checked {{ background: {k["gold"]}; }}
    
"""


def _hud_stylesheet() -> str:
    h = HUD
    return f"""
    /* ---- HUD look: dark panel, cyan lines, square corners ---- */
    #menuBar {{
        background: rgba(18, 6, 11, 230); border: 1px solid {h['line_dim']}; border-radius: 3px;
    }}
    #menuBar QPushButton {{
        background: transparent; border: 1px solid transparent; border-radius: 2px;
        padding: 3px 5px; color: {h['muted']}; font-size: 11px;
    }}
    #menuBar QPushButton:hover {{ color: {h['text']}; border-color: {h['line_dim']}; background: rgba(216, 30, 60, 40); }}
    #menuBar QPushButton:checked {{ background: {h['line']}; color: #ffffff; border-color: {h['line']}; }}
    #hudTitle {{ color: {h['text']}; }}
    #hudSub {{ color: {h['muted']}; }}
    #hudTag {{ color: {h['line']}; }}
    #hudHint {{ color: {h['muted']}; }}
    #chatInput {{
        background: rgba(18, 6, 11, 238); color: {h['text']};
        border: 1px solid {h['line_dim']}; border-left: 4px solid {h['accent']}; border-radius: 0;
        padding: 10px 14px; font-size: 13px;
    }}
    #chatInput:focus {{ border: 1px solid {h['line']}; border-left: 4px solid {h['accent']}; }}
    #micBtn, #speakBtn, #hearBtn, #lookBtn {{
        background: rgba(18, 6, 11, 238); color: {h['text']}; font-size: 15px;
        border: 1px solid {h['line_dim']}; border-radius: 0;
        min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px;
    }}
    #hearBtn, #lookBtn {{ min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; font-size: 14px; }}
    #micBtn:hover, #speakBtn:hover, #hearBtn:hover, #lookBtn:hover {{ border-color: {h['line']}; }}
    #micBtn:checked, #hearBtn:checked {{ background: {h['line']}; border-color: {h['line']}; }}
    #speakBtn:checked {{ background: {h['accent']}; border-color: {h['accent']}; }}
    """


def _classic_stylesheet() -> str:
    return f"""
    QMainWindow {{ background: transparent; }}
    #central {{ background: rgba(0, 0, 0, 2); border-radius: 18px; }}
    #central[dragging="true"] {{
        background: rgba(91, 140, 255, 45); border: 2px dashed {C['accent']};
    }}
    QLabel {{ color: {C['text']}; background: transparent; }}
    #muted {{ color: {C['muted']}; font-size: 12px; }}
    #title {{ font-size: 15px; font-weight: 700; }}

    /* top menu bar */
    #menuBar {{
        background: rgba(20, 22, 28, 215);
        border: 1px solid rgba(255, 255, 255, 30); border-radius: 16px;
    }}
    #menuBar QPushButton {{
        background: transparent; border: none; border-radius: 10px;
        padding: 6px 10px; color: {C['text']};
    }}
    #menuBar QPushButton:hover {{ background: rgba(255, 255, 255, 28); }}
    #menuBar QPushButton:checked {{ background: {C['accent']}; color: white; }}

    /* the box you type in */
    #chatInput {{
        background: rgba(20, 22, 28, 225); color: {C['text']};
        border: 1px solid rgba(255, 255, 255, 45); border-radius: 20px;
        padding: 11px 18px; font-size: 13px;
    }}
    #chatInput:focus {{ border: 1px solid {C['accent']}; }}

    /* the round mic button next to it */
    #micBtn {{
        background: rgba(20, 22, 28, 225); color: white; font-size: 16px;
        border: 1px solid rgba(255, 255, 255, 45); border-radius: 21px;
        min-width: 42px; max-width: 42px; min-height: 42px; max-height: 42px; padding: 0;
    }}
    #micBtn:hover {{ border-color: {C['accent']}; }}
    #micBtn:checked {{ background: {C['danger']}; border-color: {C['danger']}; }}
    #speakBtn, #hearBtn, #lookBtn {{
        background: rgba(20, 22, 28, 225); color: white; font-size: 15px;
        border: 1px solid rgba(255, 255, 255, 45); border-radius: 21px;
        min-width: 42px; max-width: 42px; min-height: 42px; max-height: 42px; padding: 0;
    }}
    #speakBtn:hover, #hearBtn:hover, #lookBtn:hover {{ border-color: {C['accent']}; }}
    #speakBtn:checked {{ background: {C['accent']}; border-color: {C['accent']}; }}
    #hearBtn:checked {{ background: {C['danger']}; border-color: {C['danger']}; }}

    /* dialogs (Files, Settings) */
    QDialog {{ background: {C['panel']}; }}
    QCheckBox {{ color: {C['text']}; }}
    QPushButton {{
        background: {C['panel_alt']}; color: {C['text']};
        border: 1px solid {C['border']}; border-radius: 8px; padding: 6px 12px;
    }}
    QPushButton:hover {{ border-color: {C['accent']}; }}
    QPushButton:disabled {{ color: {C['muted']}; }}
    QLineEdit {{
        background: {C['bg']}; color: {C['text']};
        border: 1px solid {C['border']}; border-radius: 8px; padding: 7px 10px;
    }}
    QComboBox {{
        background: {C['bg']}; color: {C['text']};
        border: 1px solid {C['border']}; border-radius: 8px; padding: 7px 10px;
    }}
    QComboBox QAbstractItemView {{
        background: {C['panel_alt']}; color: {C['text']};
        selection-background-color: {C['accent']}; outline: 0;
    }}
    #filePanel {{ background: {C['panel']}; }}
    #dropZone {{
        border: 2px dashed {C['border']}; border-radius: 12px; color: {C['muted']};
        padding: 16px 10px; background: {C['bg']};
    }}
    #dropZone:hover {{ border-color: {C['accent']}; color: {C['text']}; }}
    QListWidget {{ background: transparent; border: none; color: {C['text']}; outline: 0; }}
    QListWidget::item {{
        background: {C['panel_alt']}; border-radius: 8px; padding: 8px 10px; margin: 3px 0;
    }}
    QListWidget::item:selected {{ background: {C['accent']}; color: white; }}
    QToolTip {{ background: {C['panel_alt']}; color: {C['text']}; border: 1px solid {C['border']}; }}
    """


# ================================================================ tray icon
def make_icon() -> QIcon:
    """Atom's icon: his character's face if he has one, otherwise drawn in code."""
    pack = charpack.find_pack(config.CHARACTER)
    if pack:
        art = QPixmap(str(pack.sprites[pack.icon]))
        if not art.isNull():
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.GlobalColor.transparent)
            art = art.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter = QPainter(pixmap)
            painter.drawPixmap((64 - art.width()) // 2, (64 - art.height()) // 2, art)
            painter.end()
            return QIcon(pixmap)
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(C["accent"]))
    painter.drawEllipse(2, 2, 60, 60)
    painter.setPen(QColor("white"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(38)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "A")
    painter.end()
    return QIcon(pixmap)


# ============================================================== the character
class Character(QWidget):
    """Atom himself: a glowing orb with orbiting electrons, eyes that follow
    your mouse, and a few moods.

    Moods (set with set_state): "idle", "thinking", "talking", "happy", "listening",
    "worried" (something went wrong), "sleepy" (you've been away) and "looking"
    (glancing around while idle). The richer moods of a picture character
    (laughing, proud, sad, annoyed, surprised, curious) borrow the nearest orb face.
    """

    ALIASES = {
        "laughing": "happy", "proud": "happy", "sad": "worried", "annoyed": "worried",
        "surprised": "looking", "curious": "idle",
    }

    def __init__(self):
        super().__init__()
        self.setFixedSize(190, 190)
        self.state = "idle"
        self.t = 0.0       # real time, drives bobbing and mouth
        self.orbit = 0.0   # drives the electrons (spins faster while thinking)
        self._blink_frames = 0
        self._frames_to_blink = 90
        self.level = 0.0   # microphone loudness (0-1) while listening

        self._timer = QTimer(self)
        self._timer.setInterval(33)  # about 30 frames per second
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._next: list[tuple[str, int]] = []
        self._back_to_idle = QTimer(self)
        self._back_to_idle.setSingleShot(True)
        self._back_to_idle.timeout.connect(self._finish_state)

    def set_state(self, state: str, duration_ms: int = 0, then: list | None = None) -> None:
        """Change mood. With duration_ms, Atom returns to idle afterwards, or goes on
        to the next (mood, milliseconds) pair in `then`."""
        self.state = self.ALIASES.get(state, state)
        self._next = list(then or [])
        if duration_ms:
            self._back_to_idle.start(duration_ms)
        else:
            self._back_to_idle.stop()

    def _finish_state(self) -> None:
        if self._next:
            state, ms = self._next.pop(0)
            rest = self._next
            self.set_state(state, ms, rest)
        else:
            self.set_state("idle")

    def set_level(self, level: float) -> None:
        """Feed in the microphone loudness (0-1); the listening ring pulses with it."""
        self.level = max(self.level, min(1.0, level * 5))

    def _tick(self) -> None:
        self.t += 0.033
        self.level *= 0.85  # the ring settles back down between sounds
        speed = {"thinking": 3.5, "sleepy": 0.3}.get(self.state, 1.0)
        self.orbit += 0.033 * speed
        if self._blink_frames > 0:
            self._blink_frames -= 1
        else:
            self._frames_to_blink -= 1
            if self._frames_to_blink <= 0:
                self._blink_frames = 5
                self._frames_to_blink = random.randint(70, 170)
        self.update()

    # ----------------------------------------------------------- drawing
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        bob = math.sin(self.t * (0.9 if self.state == "sleepy" else 2.2)) * 4
        if self.state == "happy":
            bob -= abs(math.sin(self.t * 9)) * 16
        cx, cy = w / 2, h / 2 + bob
        accent = QColor(C["accent"])
        no_pen = Qt.PenStyle.NoPen
        no_brush = Qt.BrushStyle.NoBrush

        # soft glow behind everything
        glow = QRadialGradient(QPointF(cx, cy), 88)
        glow.setColorAt(0, qcolor(accent, 80))
        glow.setColorAt(1, qcolor(accent, 0))
        p.setPen(no_pen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), 88, 88)

        # while listening, a red ring pulses with how loud you are
        if self.state == "listening":
            ring = 54 + self.level * 36 + math.sin(self.t * 6) * 2
            p.setPen(QPen(qcolor(C["danger"], 190), 2.5))
            p.setBrush(no_brush)
            p.drawEllipse(QPointF(cx, cy), ring, ring)
            p.setPen(no_pen)

        # three tilted orbit rings that turn slowly
        rings = [(0, 80, 27), (60, 80, 27), (120, 80, 27)]  # (angle, rx, ry)
        for angle, rx, ry in rings:
            p.save()
            p.translate(cx, cy)
            p.rotate(angle + self.orbit * 8)
            p.setPen(QPen(qcolor(accent, 120), 1.6))
            p.setBrush(no_brush)
            p.drawEllipse(QPointF(0, 0), rx, ry)
            p.restore()

        # body
        body = QRadialGradient(QPointF(cx - 12, cy - 16), 62)
        body.setColorAt(0, QColor("#9bb8ff"))
        body.setColorAt(1, QColor("#3f66d8"))
        p.setBrush(body)
        p.setPen(QPen(qcolor("#ffffff", 70), 1.5))
        p.drawEllipse(QPointF(cx, cy), 46, 46)

        # electrons travelling along the rings (drawn over the body)
        p.setPen(no_pen)
        p.setBrush(QColor("#dfe8ff"))
        for i, (angle, rx, ry) in enumerate(rings):
            theta = self.orbit * (1.6 + i * 0.5) + i * 2.1
            lx, ly = rx * math.cos(theta), ry * math.sin(theta)
            rad = math.radians(angle + self.orbit * 8)
            x = lx * math.cos(rad) - ly * math.sin(rad)
            y = lx * math.sin(rad) + ly * math.cos(rad)
            p.drawEllipse(QPointF(cx + x, cy + y), 4.5, 4.5)

        self._draw_face(p, cx, cy)
        if self.state == "sleepy":  # floating z z z
            font = p.font()
            font.setBold(True)
            for i in range(3):
                phase = (self.t * 0.45 + i / 3) % 1.0
                font.setPointSizeF(9 + phase * 10)
                p.setFont(font)
                p.setPen(qcolor("#dfe8ff", int(255 * (1 - phase))))
                p.drawText(QPointF(cx + 34 + phase * 24, cy - 36 - phase * 38), "z")
        p.end()

    def _draw_face(self, p: QPainter, cx: float, cy: float) -> None:
        dark = QColor("#14161c")
        eye_open = 0.12 if self._blink_frames > 0 and self.state != "sleepy" else 1.0
        cursor = self.mapFromGlobal(QCursor.pos())
        line_pen = QPen(dark, 2.6)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        for side, ex in ((-1, cx - 16), (1, cx + 16)):
            ey = cy - 6
            if self.state == "sleepy":  # eyes shut, a gentle curve
                p.setPen(line_pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(QRectF(ex - 8, ey - 4, 16, 10), 200 * 16, 140 * 16)
                continue
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("white"))
            p.drawEllipse(QPointF(ex, ey), 9, 10 * eye_open)
            if self.state == "worried":  # eyebrows tilted up in the middle
                p.setPen(line_pen)
                # outer end low, inner end (toward the middle) high
                p.drawLine(QPointF(ex + 8 * side, ey - 15), QPointF(ex - 8 * side, ey - 20))
                p.setPen(Qt.PenStyle.NoPen)
            if eye_open > 0.5:
                if self.state == "thinking":
                    dx, dy = -2.0, -3.5  # looking up, thinking
                elif self.state == "looking":
                    dx, dy = math.sin(self.t * 1.8) * 3.8, math.sin(self.t * 0.9) * 1.2  # glancing around
                else:
                    dx, dy = cursor.x() - ex, cursor.y() - ey
                    length = math.hypot(dx, dy) or 1.0
                    scale = min(3.5, length / 20) / length
                    dx, dy = dx * scale, dy * scale
                p.setBrush(dark)
                p.drawEllipse(QPointF(ex + dx, ey + dy), 4.6, 4.6)

        p.setBrush(Qt.BrushStyle.NoBrush)
        mouth_pen = QPen(dark, 2.6)
        mouth_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(mouth_pen)
        if self.state == "talking":
            height = 4 + 9 * abs(math.sin(self.t * 14))
            p.setBrush(dark)
            p.drawEllipse(QPointF(cx, cy + 15), 7, height / 2)
        elif self.state == "listening":
            p.setBrush(dark)
            size = 4 + self.level * 5
            p.drawEllipse(QPointF(cx, cy + 15), size, size * 1.2)
        elif self.state == "happy":
            p.setBrush(dark)
            p.drawChord(QRectF(cx - 12, cy + 7, 24, 18), 180 * 16, 180 * 16)
        elif self.state == "thinking":
            p.setBrush(dark)
            p.drawEllipse(QPointF(cx + 6, cy + 15), 3.5, 3.5)
        elif self.state == "worried":
            p.drawArc(QRectF(cx - 9, cy + 13, 18, 11), 20 * 16, 140 * 16)  # a small frown
        elif self.state == "sleepy":
            p.setBrush(dark)
            p.drawEllipse(QPointF(cx, cy + 15), 3.2, 2.2 + math.sin(self.t * 1.5) * 1.2)  # slow breathing
        else:
            p.drawArc(QRectF(cx - 10, cy + 6, 20, 13), 200 * 16, 140 * 16)


class SpriteCharacter(QWidget):
    """Atom as a picture character (like the jester): a different drawing for each
    expression, a mouth that flaps while he talks, and a little body movement.
    The decisions about which picture and which movement are made in charpack.py.

    It has the same methods as the orb Character, so the rest of Atom doesn't care
    which one is on screen.
    """

    PAD_X, PAD_TOP, PAD_BOTTOM = 20, 24, 12

    def __init__(self, pack: charpack.Pack):
        super().__init__()
        self.pack = pack
        self.animator = charpack.Animator(pack)
        self.state = "idle"
        self._next: list[tuple[str, int]] = []
        self.level = 0.0
        self._last = time.monotonic()

        first = QPixmap(str(pack.sprites[pack.states["idle"][0]]))
        self._ref_h = max(1, first.height())
        screen = QApplication.primaryScreen()
        ratio = (screen.devicePixelRatio() if screen else 1.0) or 1.0  # crisp on scaled (125%, 150%) screens
        scale = pack.height / self._ref_h  # one scale for every picture, so he never changes size
        mode = Qt.TransformationMode.SmoothTransformation
        height = pack.height
        size_ratio = ratio
        self._pix: dict[str, QPixmap] = {}
        width = 0
        for name, path in pack.sprites.items():
            art = QPixmap(str(path))
            if art.isNull():
                continue
            art = art.scaled(
                max(1, round(art.width() * scale * size_ratio)),
                max(1, round(art.height() * scale * size_ratio)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                mode,
            )
            art.setDevicePixelRatio(ratio)
            self._pix[name] = art
            width = max(width, int(art.width() / ratio))
        self.setFixedSize(width + 2 * self.PAD_X, height + self.PAD_TOP + self.PAD_BOTTOM)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._back_to_idle = QTimer(self)
        self._back_to_idle.setSingleShot(True)
        self._back_to_idle.timeout.connect(self._finish_state)

    # same methods as the orb ------------------------------------------
    def set_state(self, state: str, duration_ms: int = 0, then: list | None = None) -> None:
        self.state = state
        self.animator.set_state(state)
        self._next = list(then or [])
        if duration_ms:
            self._back_to_idle.start(duration_ms)
        else:
            self._back_to_idle.stop()

    def _finish_state(self) -> None:
        if self._next:
            state, ms = self._next.pop(0)
            self.set_state(state, ms, self._next)
        else:
            self.set_state("idle")

    def set_level(self, level: float) -> None:
        self.animator.set_level(level)

    def portrait(self) -> QPixmap | None:
        """His face as it is right now, cropped square (for the chat plate's portrait)."""
        name = self.animator.frame
        cache = self.__dict__.setdefault("_faces", {})
        if name not in cache:
            art = QPixmap(str(self.pack.sprites[name]))
            if art.isNull():
                return None
            x, y, w, h = self.pack.face_box(art.width(), art.height())
            crop = art.copy(x, y, w, h)
            cache[name] = crop.scaled(
                120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        return cache[name]

    # ------------------------------------------------------------ frames
    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._last = now - self._last, now
        cursor = self.mapFromGlobal(QCursor.pos())
        self.animator.set_look((cursor.x() - self.width() / 2) / 500.0)
        self._pose = self.animator.tick(dt)
        self.update()

    def paintEvent(self, _event) -> None:
        pose = getattr(self, "_pose", None) or self.animator.tick(0.0)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        foot_y = h - self.PAD_BOTTOM
        cx = w / 2

        # a soft shadow under him that shrinks when he hops
        lift = max(0.0, -pose.dy)
        shadow = QRadialGradient(QPointF(cx, foot_y), w * 0.36)
        shadow.setColorAt(0, QColor(0, 0, 0, int(70 * max(0.3, 1 - lift / 40))))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(QPointF(cx, foot_y + 2), w * 0.36, 7)

        if pose.ring > 0:  # listening: a red ring that pulses with your voice
            radius = h * 0.40 + self.animator.level * 24 + math.sin(self.animator.t * 6) * 2
            p.setPen(QPen(qcolor(C["danger"], 190), 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, h * 0.55), radius * 1.05, radius)
            p.setPen(Qt.PenStyle.NoPen)

        # body: turn and squash around his feet
        p.save()
        p.translate(cx + pose.dx, foot_y + pose.dy)
        p.rotate(pose.rot)
        p.scale(pose.sx, pose.sy)
        if pose.previous and pose.previous in self._pix:
            self._draw_sprite(p, pose.previous, 1.0)
        self._draw_sprite(p, pose.frame, pose.blend if pose.previous else 1.0)
        p.restore()

        if pose.zzz:  # floating z z z
            font = p.font()
            font.setBold(True)
            for i in range(3):
                phase = (self.animator.t * 0.45 + i / 3) % 1.0
                font.setPointSizeF(9 + phase * 10)
                p.setFont(font)
                p.setPen(qcolor("#dfe8ff", int(255 * (1 - phase))))
                p.drawText(QPointF(cx + 48 + phase * 28, h * 0.30 - phase * 30), "z")
        p.end()

    def _draw_sprite(self, p: QPainter, name: str, opacity: float) -> None:
        art = self._pix.get(name)
        if art is None:
            return
        ratio = art.devicePixelRatio() or 1.0
        aw, ah = art.width() / ratio, art.height() / ratio
        p.setOpacity(max(0.0, min(1.0, opacity)))
        p.drawPixmap(QPointF(-aw / 2, -ah), art)
        p.setOpacity(1.0)


CHARACTER_NOTE = ""  # set when the chosen character couldn't be used (shown to you in a bubble)


def make_character():
    """The character chosen in config.CHARACTER: a picture pack, or the glowing orb
    if that is chosen or the pictures can't be found."""
    pack = charpack.find_pack(config.CHARACTER)
    if pack:
        if IS_HUD:
            pack.height = min(pack.height, config.PLATE_CHARACTER_HEIGHT if IS_PLATE else config.HUD_CHARACTER_HEIGHT)
        try:
            return SpriteCharacter(pack)
        except Exception as error:  # a broken picture pack must never stop Atom starting
            print(f"[atom] couldn't load character '{config.CHARACTER}': {error}")
            _set_character_note(f"I couldn't load the '{config.CHARACTER}' pictures ({error}), so I'm the orb for now.")
    elif config.CHARACTER and config.CHARACTER.lower() != "orb":
        print(f"[atom] character '{config.CHARACTER}' not found in the characters folder: using the orb")
        _set_character_note(
            f"I couldn't find the '{config.CHARACTER}' pictures, so I'm the orb for now. "
            "In a terminal run:  python charpack.py  to see where I looked."
        )
    return Character()


def _set_character_note(text: str) -> None:
    global CHARACTER_NOTE
    CHARACTER_NOTE = text


# ============================================================= HUD panels
HUD_TAGS = {  # (left caption, right caption) shown at the bottom of the character frame
    "idle": ("STANDING BY", "ALL SYSTEMS NORMAL"),
    "talking": ("TRANSMITTING", "INCOMING VOICE"),
    "thinking": ("PROCESSING", "GIVE ME A MOMENT"),
    "listening": ("LISTENING", "VOICE LINK OPEN"),
    "happy": ("CHEERFUL", "GOOD NEWS"),
    "laughing": ("LAUGHING", "THAT WAS FUNNY"),
    "proud": ("PROUD", "NAILED IT"),
    "worried": ("NERVOUS", "SOMETHING IS OFF"),
    "sad": ("DOWN", "SORRY ABOUT THAT"),
    "annoyed": ("ANNOYED", "NOT IMPRESSED"),
    "surprised": ("SURPRISED", "DIDN'T SEE THAT COMING"),
    "curious": ("CURIOUS", "TELL ME MORE"),
    "sleepy": ("SLEEPING", "WAKE ME ANY TIME"),
    "looking": ("SCANNING", "ANYONE THERE?"),
}

# plate look: which colours and which state tag go with which mood
PLATE_KIND = {
    "happy": "done", "laughing": "done", "proud": "done",
    "worried": "alert", "sad": "alert", "annoyed": "alert",
    "sleepy": "idle",
}
PLATE_CHIP = {
    "thinking": "THINKING", "listening": "LISTENING", "happy": "DONE", "laughing": "HA HA", "proud": "NAILED IT",
    "worried": "ALERT", "sad": "SORRY", "annoyed": "HMPH", "surprised": "WOW", "curious": "HMM?",
    "sleepy": "ASLEEP", "looking": "SCANNING",
}


def _mic_level(character) -> float:
    animator = getattr(character, "animator", None)
    return animator.level if animator is not None else getattr(character, "level", 0.0)


class ListeningBadge(QWidget):
    """The "I'M LISTENING / SPEAK NOW" box with moving level bars."""

    def __init__(self, character, parent: QWidget):
        super().__init__(parent)
        self.character = character
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(190, 44)
        self.hide()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(HUD["line"]), 1.5))
        p.setBrush(qcolor("#12060b", 240))
        p.drawPolygon(cut_polygon(QRectF(0.75, 0.75, self.width() - 1.5, self.height() - 1.5), 8))
        level = min(1.0, _mic_level(self.character))
        t = time.monotonic()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(HUD["accent"]))
        for i in range(6):  # six bars that jump with your voice
            height = 5 + (4 + level * 16) * (0.5 + 0.5 * math.sin(t * 9 + i * 1.3)) ** 1.3
            p.drawRect(QRectF(14 + i * 8, self.height() / 2 - height / 2, 4, height))
        p.setPen(QColor(HUD["text"]))
        p.setFont(hud_font(10, True, 1.2))
        p.drawText(QPointF(68, 20), "I'M LISTENING")
        p.setPen(QColor(HUD["line"]))
        p.setFont(hud_font(7.5, True, 2.0))
        p.drawText(QPointF(68, 34), "SPEAK NOW")
        p.end()


class HudFrame(QWidget):
    """The character's window: cyan corner brackets, a name tab, faint scan lines,
    a slow scan band and two small caption lines that follow his mood."""

    TAB_H = 18

    def __init__(self, character: QWidget, title: str = "ATOM // SAY ATOM"):
        super().__init__()
        self.character = character
        self.title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, self.TAB_H + 6, 10, 22)
        layout.addWidget(character, 1, Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(max(260, character.width() + 40), character.height() + self.TAB_H + 6 + 22 + 4)
        self.badge = ListeningBadge(character, self)
        self._last_state = character.state
        self._glitch = 0  # frames of flicker left after his mood changes
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        if self.character.state != self._last_state:
            self._last_state = self.character.state
            self._glitch = 6
        elif self._glitch > 0:
            self._glitch -= 1
        self.badge.setVisible(self.character.state == "listening")
        if self.badge.isVisible():
            self.badge.raise_()
            self.badge.update()
        self.update()

    def resizeEvent(self, event) -> None:
        self.badge.move((self.width() - self.badge.width()) // 2, self.height() - self.badge.height() - 26)
        super().resizeEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        shape = cut_polygon(QRectF(0.75, 0.75, w - 1.5, h - 1.5), 14)

        back = QLinearGradient(0, 0, 0, h)
        back.setColorAt(0, QColor("#2a0c14"))
        back.setColorAt(1, QColor("#0e0408"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(back)
        p.drawPolygon(shape)

        clip = QPainterPath()
        clip.addPolygon(shape)
        p.save()
        p.setClipPath(clip)
        p.setPen(QPen(qcolor(HUD["line"], 16), 1))
        for y in range(0, h, 4):  # scan lines
            p.drawLine(0, y, w, y)
        band = (time.monotonic() * 55) % (h + 60) - 30  # a pale band that drifts down
        sweep = QLinearGradient(0, band - 22, 0, band + 22)
        sweep.setColorAt(0, qcolor(HUD["line"], 0))
        sweep.setColorAt(0.5, qcolor(HUD["line"], 26))
        sweep.setColorAt(1, qcolor(HUD["line"], 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(sweep)
        p.drawRect(QRectF(0, band - 22, w, 44))
        p.restore()

        p.setPen(QPen(QColor(HUD["line_dim"]), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolygon(shape)
        p.setPen(QPen(QColor(HUD["line"]), 2.6))  # bright corner brackets
        m, n = 6, 16
        for x, y, dx, dy in ((m, m + self.TAB_H, 1, 1), (w - m, m + self.TAB_H, -1, 1), (m, h - m, 1, -1), (w - m, h - m, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * n, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * n))

        p.setFont(hud_font(7.5, True, 1.8))  # name tab
        tab_w = p.fontMetrics().horizontalAdvance(self.title) + 22
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(HUD["accent"]))
        p.drawPolygon(QPolygonF([QPointF(0.75, 0.75), QPointF(tab_w, 0.75), QPointF(tab_w - 7, self.TAB_H), QPointF(0.75, self.TAB_H)]))
        p.setPen(QColor("#1a0408"))
        p.drawText(QPointF(10, self.TAB_H - 5), self.title)

        if self._glitch > 0:  # flicker: bright slices and a pink ghost of the frame
            shift = random.choice((-5, -3, 3, 5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(qcolor(HUD["accent"], 140), 1.5))
            p.drawPolygon(cut_polygon(QRectF(0.75 + shift, 0.75, w - 1.5, h - 1.5), 14))
            for _ in range(3):
                p.fillRect(QRectF(0, random.uniform(self.TAB_H, h - 8), w, random.choice((2, 3, 5))), qcolor(HUD["line"], 60))

        left, right = HUD_TAGS.get(self.character.state, (self.character.state.upper(), ""))
        p.setFont(hud_font(7, True, 1.4))
        p.setPen(QColor(HUD["line_dim"]))
        p.drawText(QPointF(16, h - 9), left)
        p.drawText(QPointF(w - 16 - p.fontMetrics().horizontalAdvance(right), h - 9), right)
        p.end()


# ================================================================== bubbles
class Bubble(QWidget):
    """A speech bubble that sizes itself to its text. Long text scrolls.

    In the HUD look it is a framed "chat box": Atom's one holds your last line on top
    ("YOU  open spotify"), then "ATOM / INCOMING TRANSMISSION", then his reply, which
    types itself out and flickers when it arrives."""

    PAD_X, PAD_Y, TAIL = 14, 10, 10
    HEAD = 17    # height of the small heading line in the HUD look
    QUOTE = 15   # height of the "YOU ..." line

    # plate look (Atom's transmission plate)
    M = 8        # margin around the plate (room for the echo and the corner brackets)
    PORT = 58    # his portrait: a cut-corner square
    META = 18    # the "/// ATOM" line
    QLINE = 18   # the "> your words" line
    TAIL_H = 22  # the jagged tail that points down at him

    def __init__(self, role: str, max_size: tuple[int, int]):
        super().__init__()
        self.role = role
        self.max_w, self.max_h = max_size
        self.hud = IS_HUD
        self.plate = IS_PLATE
        self.kind = "info"          # plate colours: info / done / alert / idle (follows his mood)
        self.chip = ""              # the state chip on the plate, e.g. THINKING
        self.tag = ""               # what he is doing right now, e.g. READING BUDGET.XLSX
        self._portrait: QPixmap | None = None
        self._portrait_key = None
        self._sync_state = None
        self._plate_rect = QRectF(0, 0, 10, 10)
        self._head = self.HEAD if self.hud else 0
        self._tail = self.TAIL if (role == "atom" and not self.hud) else 0  # only Atom's bubble points down
        self.heading = "INCOMING TRANSMISSION"
        self._text = " "
        self._quote = ""            # your last line (HUD look, Atom's box only)
        self._quote_on = False
        self._typed: int | None = None  # characters shown so far while typing; None = all of them
        self._cps = 50.0
        self._glitch = 0            # frames of screen-flicker left
        self._follow = False        # words are still arriving: keep the newest ones in view

        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setFont(hud_font(11.5, True) if self.plate else hud_font(11) if self.hud else QFont("Segoe UI", 10))
        color = PL["paper"] if self.plate else HUD["text"] if self.hud else "white"
        self.label.setStyleSheet(f"color: {color}; background: transparent;")

        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,90); border-radius: 3px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self.scroll.setWidget(self.label)
        self.scroll.viewport().setStyleSheet("background: transparent;")

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self.set_text("")

    # ------------------------------------------------------------ content
    def set_text(self, text: str, follow: bool = False) -> None:
        """Show `text` at once. It starts at the top; with `follow` (words still arriving)
        a long text keeps its newest words in view instead."""
        self._timer.stop()
        self._typed = None
        self._follow = follow
        self._text = text or " "
        self._layout()

    def _scroll_to_reading_spot(self) -> None:
        """A finished text is read from its first line. While words are still coming in, the
        view follows them (when typing: in step with how much has been typed)."""
        bar = self.scroll.verticalScrollBar()
        if not self._follow and self._typed is None:
            bar.setValue(0)
            return
        if self._typed is not None and self._follow:
            fraction = self._typed / max(1, len(self._text))
            bar.setValue(int(bar.maximum() * min(1.0, fraction)))
        else:
            bar.setValue(bar.maximum())

    def type_text(self, text: str, cps: float = 50.0) -> None:
        """HUD look: type `text` out letter by letter, with a short screen flicker.
        (Anything already shown, or the classic look, just appears.)"""
        text = text or " "
        if not self.hud or text == self._text:
            self.set_text(text)
            return
        self._text = text
        self._typed = 0
        self._follow = True
        self._cps = max(5.0, cps)
        self._glitch = 8
        self._layout()
        self._timer.start()

    def set_quote(self, text: str) -> None:
        """Your last line, shown small above Atom's heading."""
        self._quote = " ".join((text or "").split())
        self.update()

    def set_quote_visible(self, on: bool) -> None:
        on = bool(on and self._quote)
        if on != self._quote_on:
            self._quote_on = on
            self._layout()
        else:
            self.update()

    def _shown(self) -> str:
        if self._typed is None:
            return self._text
        cursor = "\u258c" if self.plate else ""    # a block cursor while it types
        return self._text[: self._typed] + cursor

    def _tick(self) -> None:
        busy = False
        if self._typed is not None:
            self._typed += max(1, round(self._cps * 0.030))
            if self._typed >= len(self._text):
                self._typed = None
                self._follow = False     # all of it is there: back to the first line
            else:
                busy = True
            self.label.setText(self._shown())
            self._scroll_to_reading_spot()
        if self._glitch > 0:
            self._glitch -= 1
            busy = busy or self._glitch > 0
        if not busy:
            self._timer.stop()
        self.update()

    def _layout_plate(self) -> None:
        text = self._text
        w_total = self.max_w
        plate_w = w_total - 2 * self.M
        text_w = plate_w - (14 + self.PORT + 12 + 16)
        self.label.setText(text)  # measure the whole text, so the plate doesn't grow while it types
        self.label.setFixedWidth(text_w)
        text_h = self.label.heightForWidth(text_w)
        if text_h > self.max_h:  # leave room for the scroll bar
            text_w -= 12
            self.label.setFixedWidth(text_w)
            text_h = self.label.heightForWidth(text_w)
        self.label.setFixedHeight(text_h)
        self.label.setText(self._shown())
        overflow = text_h > self.max_h
        shown_h = min(text_h, self.max_h)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn if overflow else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        quote_h = self.QLINE if self._quote_on else 0
        body_h = self.META + quote_h + shown_h
        plate_h = max(14 + self.PORT + 22, 14 + body_h + 18)
        self._plate_rect = QRectF(self.M, self.M, plate_w, plate_h)
        self.scroll.setGeometry(
            self.M + 14 + self.PORT + 12,
            self.M + 14 + self.META + quote_h,
            text_w + (12 if overflow else 0),
            shown_h,
        )
        self.setFixedSize(w_total, int(self.M + plate_h + self.TAIL_H + 2))
        self._scroll_to_reading_spot()
        self.update()

    def _layout(self) -> None:
        if self.plate:
            self._layout_plate()
            return
        text = self._text
        metrics = QFontMetrics(self.label.font())
        inner_max = self.max_w - 2 * self.PAD_X
        longest_line = max(metrics.horizontalAdvance(line) for line in text.split("\n"))
        text_w = inner_max if self.hud else min(inner_max, longest_line + 8)  # HUD panels are full width

        self.label.setText(text)  # measure the whole text, so the box doesn't grow while it types
        self.label.setFixedWidth(text_w)
        text_h = self.label.heightForWidth(text_w)
        if self.hud and text_h > self.max_h:  # leave room for the scroll bar
            text_w = inner_max - 12
            self.label.setFixedWidth(text_w)
            text_h = self.label.heightForWidth(text_w)
        self.label.setFixedHeight(text_h)
        self.label.setText(self._shown())

        overflow = text_h > self.max_h
        scrollbar = 12 if overflow else 0
        shown_h = min(text_h, self.max_h)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn if overflow else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        quote_h = self.QUOTE if (self.hud and self._quote_on) else 0
        top = self.PAD_Y + quote_h + self._head
        self.scroll.setGeometry(self.PAD_X, top, text_w + scrollbar, shown_h)
        self.setFixedSize(text_w + scrollbar + 2 * self.PAD_X, top + shown_h + self.PAD_Y + self._tail)
        self._scroll_to_reading_spot()
        self.update()

    # ------------------------------------------------------------ drawing
    def _paint_hud(self, p: QPainter) -> None:
        w, h = self.width(), self.height()
        rect = QRectF(0.75, 0.75, w - 1.5, h - 1.5)
        shape = cut_polygon(rect, 10)
        p.setBrush(qcolor(HUD["panel"], 230))
        p.setPen(QPen(qcolor(HUD["line"], 40), 5))   # soft glow
        p.drawPolygon(shape)
        p.setPen(QPen(QColor(HUD["line"]), 1.5))     # the line itself
        p.drawPolygon(shape)

        y = self.PAD_Y + 5
        if self._quote_on:  # "YOU  open spotify" in small italics
            p.setFont(hud_font(7.5, True, 1.6))
            p.setPen(QColor(HUD["line_dim"]))
            p.drawText(QPointF(self.PAD_X, y + 4), "YOU")
            lead = p.fontMetrics().horizontalAdvance("YOU  ")
            italic = hud_font(8.5)
            italic.setItalic(True)
            p.setFont(italic)
            p.setPen(QColor(HUD["muted"]))
            room = w - 2 * self.PAD_X - lead
            p.drawText(QPointF(self.PAD_X + lead, y + 4), p.fontMetrics().elidedText(self._quote, Qt.TextElideMode.ElideRight, room))
            y += self.QUOTE
        p.setFont(hud_font(7.5, True, 1.6))
        p.setPen(QColor(HUD["accent"]))
        p.drawText(QPointF(self.PAD_X, y + 4), "ATOM")
        lead = p.fontMetrics().horizontalAdvance("ATOM ")
        p.setPen(QColor(HUD["line_dim"]))
        p.drawText(QPointF(self.PAD_X + lead, y + 4), f"/  {self.heading}")

        if self._glitch > 0:  # a brief screen flicker when a message arrives
            shift = random.choice((-4, -2, 2, 4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(qcolor(HUD["accent"], 150), 1.2))
            p.drawPolygon(cut_polygon(QRectF(rect.left() + shift, rect.top(), rect.width(), rect.height()), 10))
            for _ in range(2):
                bar_y = random.uniform(2, h - 6)
                p.fillRect(QRectF(0, bar_y, w, random.choice((1, 2, 3))), qcolor(HUD["line"], 80))

    # ------------------------------------------------------- plate look
    def kick(self, frames: int = 6) -> None:
        """A short screen flicker (when he changes mood or a message arrives)."""
        self._glitch = max(self._glitch, frames)
        self._timer.start()

    def set_tag(self, text: str) -> None:
        """What he is doing right now (shown after /// ATOM), e.g. 'reading budget.xlsx'."""
        self.tag = (text or "").strip().rstrip(".").upper()
        self.update()

    def sync(self, character) -> None:
        """Plate look: follow the character's mood (colours, state chip) and face (portrait)."""
        if not self.plate:
            return
        state = character.state
        if state != self._sync_state:
            self._sync_state = state
            self.kind = PLATE_KIND.get(state, "info")
            self.chip = PLATE_CHIP.get(state, "")
            self.kick(5)
        portrait = character.portrait() if hasattr(character, "portrait") else None
        key = portrait.cacheKey() if portrait is not None else None
        if key != self._portrait_key:
            self._portrait, self._portrait_key = portrait, key
            self.update()
            return
        if self.kind == "alert":   # the ALERT chip blinks
            self.update()

    def _plate_colors(self) -> tuple[QColor, QColor, QColor]:
        """(outline, echo, accent) for the current mood."""
        crimson, gold, red = QColor(PL["crimson"]), QColor(PL["gold"]), QColor(PL["red"])
        if self.kind == "done":
            return gold, crimson, gold
        if self.kind == "alert":
            return red, gold, red
        if self.kind == "idle":
            return QColor(PL["paper3"]), QColor(PL["ink2"]), QColor(PL["paper3"])
        return crimson, gold, gold

    @staticmethod
    def _plate_polygon(r: QRectF, cut: float = 18.0) -> QPolygonF:
        """The plate: a rectangle with a small notch in the top edge and a cut bottom-right corner."""
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        return QPolygonF([
            QPointF(x, y), QPointF(x + w * 0.57, y), QPointF(x + w * 0.59, y + 4),
            QPointF(x + w * 0.75, y + 4), QPointF(x + w * 0.77, y), QPointF(x + w, y),
            QPointF(x + w, y + h - cut), QPointF(x + w - cut, y + h), QPointF(x, y + h),
        ])

    def _paint_plate(self, p: QPainter) -> None:
        outline, echo, accent = self._plate_colors()
        ink = QColor(PL["ink"])
        r = self._plate_rect
        shape = self._plate_polygon(r)
        cx = self.width() / 2
        tail = QPolygonF([
            QPointF(cx - 15, r.bottom() - 1), QPointF(cx + 15, r.bottom() - 1),
            QPointF(cx + 3.6, r.bottom() + self.TAIL_H - 1),
            QPointF(cx, r.bottom() + 10), QPointF(cx - 6, r.bottom() + 15),
        ])

        glitch = self._glitch > 0
        shift = random.choice((-3, -2, 2, 3)) if glitch else 0

        # 1. the offset "echo" copy behind the plate
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(echo)
        p.drawPolygon(shape.translated(5 + shift, 5))

        # 2. the outline (a fat fill), then the dark plate on top of it
        p.setPen(QPen(outline, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
        p.setBrush(outline)
        p.drawPolygon(shape)
        p.drawPolygon(tail)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        p.drawPolygon(shape)
        p.drawPolygon(tail)

        # 3. corner brackets, top left and top right
        p.setPen(QPen(outline, 2))
        m = 2
        for x0, y0, dx in (
            (r.left() - m - 5, r.top() - m - 5, 1),
            (r.right() + m + 5, r.top() - m - 5, -1),
        ):
            p.drawLine(QPointF(x0, y0), QPointF(x0 + dx * 11, y0))
            p.drawLine(QPointF(x0, y0), QPointF(x0, y0 + 11))

        # 4. a little barcode, bottom left
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(PL["ink2"]))
        bx, by = r.left() + 14, r.bottom() - 16
        for i in range(0, 46, 7):
            p.drawRect(QRectF(bx + i, by, 2, 6))
            p.drawRect(QRectF(bx + i + 3, by, 1, 6))

        # 5. his portrait in a cut-corner frame (it jumps sideways while the screen flickers)
        px = r.left() + 14 + (random.choice((-4, 3)) if glitch else 0)
        py = r.top() + 16
        port = QRectF(px, py, self.PORT, self.PORT)
        p.setBrush(outline)
        p.drawPolygon(QPolygonF([
            QPointF(port.left(), port.top()), QPointF(port.right(), port.top()),
            QPointF(port.right(), port.bottom() - 12),
            QPointF(port.right() - 12, port.bottom()), QPointF(port.left(), port.bottom()),
        ]))
        inner = port.adjusted(2, 2, -2, -2)
        clip = QPainterPath()
        clip.addPolygon(QPolygonF([
            QPointF(inner.left(), inner.top()), QPointF(inner.right(), inner.top()),
            QPointF(inner.right(), inner.bottom() - 11),
            QPointF(inner.right() - 11, inner.bottom()), QPointF(inner.left(), inner.bottom()),
        ]))
        p.save()
        p.setClipPath(clip)
        if self._portrait is not None:
            p.drawPixmap(inner, self._portrait, QRectF(0, 0, self._portrait.width(), self._portrait.height()))
        else:
            p.fillRect(inner, QColor(PL["ink2"]))
            p.setPen(accent)
            p.setFont(hud_font(20, True))
            p.drawText(inner, Qt.AlignmentFlag.AlignCenter, "A")
        p.restore()

        # 6. the meta line:  /// ATOM  .READING BUDGET.XLSX                [THINKING]
        left = r.left() + 14 + self.PORT + 12
        right = r.right() - 16
        mono = QFont("Consolas")
        mono.setPointSizeF(8)
        mono.setBold(True)
        mono.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        p.setFont(mono)
        base = r.top() + 14 + 11
        p.setPen(QColor(PL["gold"]))
        p.drawText(QPointF(left, base), "/// ATOM")
        used = p.fontMetrics().horizontalAdvance("/// ATOM ")
        chip_w = 0.0
        if self.chip and (self.kind != "alert" or int(time.monotonic() * 2) % 2 == 0):
            chip_w = p.fontMetrics().horizontalAdvance(self.chip) + 16
            chip = QRectF(right - chip_w, r.top() + 12, chip_w, 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent)
            p.drawPolygon(QPolygonF([
                QPointF(chip.left(), chip.top()), QPointF(chip.right(), chip.top()),
                QPointF(chip.right(), chip.bottom() - 5),
                QPointF(chip.right() - 5, chip.bottom()), QPointF(chip.left(), chip.bottom()),
            ]))
            p.setPen(ink)
            p.drawText(QPointF(chip.left() + 8, base), self.chip)
        elif self.chip:   # the blinking ALERT chip keeps its place while it is "off"
            chip_w = p.fontMetrics().horizontalAdvance(self.chip) + 16
        if self.tag:
            p.setPen(QColor(PL["paper3"]))
            room = right - left - used - chip_w - 10
            p.drawText(
                QPointF(left + used, base),
                p.fontMetrics().elidedText("." + self.tag, Qt.TextElideMode.ElideRight, int(max(10, room))),
            )

        # 7. your last words:  > open spotify
        if self._quote_on:
            qfont = QFont("Consolas")
            qfont.setPointSizeF(8.5)
            p.setFont(qfont)
            y = base + self.QLINE - 2
            p.setPen(accent)
            p.drawText(QPointF(left, y), ">")
            p.setPen(QColor(PL["paper2"]))
            p.drawText(
                QPointF(left + 14, y),
                p.fontMetrics().elidedText(self._quote, Qt.TextElideMode.ElideRight, int(right - left - 14)),
            )

        # 8. flicker lines
        if glitch:
            for _ in range(2):
                p.fillRect(
                    QRectF(r.left(), random.uniform(r.top(), r.bottom() - 4), r.width(), random.choice((1, 2, 3))),
                    QColor(accent.red(), accent.green(), accent.blue(), 90),
                )

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.plate:
            self._paint_plate(p)
            p.end()
            return
        if self.hud:
            self._paint_hud(p)
            p.end()
            return
        body_h = self.height() - self._tail
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), body_h), 16, 16)
        if self._tail:
            mid = self.width() / 2
            tail = QPainterPath()
            tail.moveTo(mid - 9, body_h - 1)
            tail.lineTo(mid, body_h + self._tail)
            tail.lineTo(mid + 9, body_h - 1)
            tail.closeSubpath()
            path = path.united(tail)
        fill = C["user_bubble"] if self.role == "user" else C["atom_bubble"]
        p.setPen(QPen(qcolor("#ffffff", 30), 1))
        p.setBrush(qcolor(fill, 240))
        p.drawPath(path)
        p.end()


class _Quote:
    """In the HUD look there is no separate bubble for you: your words go into the top
    line of Atom's chat box. This stands in for the old user bubble."""

    def __init__(self, box: Bubble):
        self.box = box

    def set_text(self, text: str) -> None:
        self.box.set_quote(text)


class _QuoteRow:
    def __init__(self, box: Bubble):
        self.box = box

    def show(self) -> None:
        self.box.set_quote_visible(True)

    def hide(self) -> None:
        self.box.set_quote_visible(False)


class ReplyWorker(QThread):
    """Runs brain.reply() in the background so the window never freezes.

    While the answer is being written it emits `partial`, so the bubble can
    fill in live instead of staying empty until the end.
    """

    partial = Signal(str)
    done = Signal(str)
    status = Signal(str)             # "Searching your files..." while a tool runs
    confirm_requested = Signal(str)  # Atom wants to open something: ask the user

    def __init__(self, brain: Brain, text: str):
        super().__init__()
        self.brain = brain
        self.text = text
        self._last_emit = 0.0
        self._answer_ready = threading.Event()
        self._answer = False

    def _on_text(self, text: str) -> None:
        now = time.monotonic()
        if now - self._last_emit >= 0.08:  # at most about 12 screen updates a second
            self._last_emit = now
            self.partial.emit(text)

    def _confirm(self, question: str) -> bool:
        """Called from this background thread: show the Yes/No box in the window
        and wait (up to 2 minutes) for the click. No answer means no."""
        self._answer_ready.clear()
        self._answer = False
        self.confirm_requested.emit(question)
        self._answer_ready.wait(120)
        return self._answer

    def answer(self, yes: bool) -> None:
        """Called by the window with what the user clicked."""
        self._answer = yes
        self._answer_ready.set()

    def run(self) -> None:
        try:
            self.done.emit(
                self.brain.reply(
                    self.text,
                    on_text=self._on_text,
                    confirm=self._confirm,
                    on_status=self.status.emit,
                )
            )
        except Exception as error:
            self.done.emit(f"Something went wrong: {error}")


# ===================================================================== voice
class Recorder(QObject):
    """Records from the microphone. Stops by itself when you stop talking."""

    level_changed = Signal(float)
    # raw audio, sample rate, channels, sample format, did we hear speech?
    finished = Signal(object, int, int, str, bool)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None
        self._io = None
        self._chunks: list[bytes] = []
        self._detector: EndpointDetector | None = None
        self._rate = config.SAMPLE_RATE
        self._channels = 1
        self._format = "int16"
        self._limit = QTimer(self)  # safety net in case no audio ever arrives
        self._limit.setSingleShot(True)
        self._limit.timeout.connect(self.stop)

    @property
    def active(self) -> bool:
        return self._source is not None

    def start(self) -> bool:
        """Begin recording. On failure, emits `failed` and returns False."""
        if QAudioSource is None:
            self.failed.emit(
                "Voice needs Qt's multimedia support, which isn't installed. "
                "Try: python -m pip install --upgrade PySide6"
            )
            return False
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self.failed.emit(
                "I can't find a microphone. Plug one in or check your Windows sound settings."
            )
            return False

        # try 16 kHz mono first; if that won't open, use the mic's own format and convert later
        names = {
            QAudioFormat.SampleFormat.Int16: "int16",
            QAudioFormat.SampleFormat.Int32: "int32",
            QAudioFormat.SampleFormat.Float: "float32",
        }
        wanted = QAudioFormat()
        wanted.setSampleRate(config.SAMPLE_RATE)
        wanted.setChannelCount(1)
        wanted.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        candidates = []
        if device.isFormatSupported(wanted):
            candidates.append(wanted)
        candidates.append(device.preferredFormat())

        source = io = None
        problem = ""
        for fmt in candidates:
            name = names.get(fmt.sampleFormat(), "")
            if not name:
                problem = "unreadable audio format"
                continue
            attempt = QAudioSource(device, fmt, self)
            stream = attempt.start()
            error = attempt.error()
            # compare by name: newer Qt versions have two different "Error" enums
            # that both print as NoError but never compare equal
            no_error = str(getattr(error, "name", error)).split(".")[-1] == "NoError"
            if stream is not None and no_error:
                source, io = attempt, stream
                self._format = name
                self._rate, self._channels = fmt.sampleRate(), fmt.channelCount()
                break
            # remember WHY it failed (e.g. OpenError) so the message can say so
            problem = "no audio stream" if no_error else str(getattr(error, "name", error)).split(".")[-1]
            attempt.stop()
            attempt.deleteLater()

        if source is None:
            self.failed.emit(
                f"I couldn't open the microphone ({device.description()}: {problem or 'unknown error'}). "
                "Another app may be using it, or Windows is blocking access "
                "(Settings > Privacy & security > Microphone)."
            )
            return False

        self._source, self._io = source, io
        self._chunks = []
        self._detector = EndpointDetector(self._rate)
        io.readyRead.connect(self._on_ready)
        self._limit.start(int((config.MAX_RECORD_SECONDS + 3) * 1000))
        return True

    def _on_ready(self) -> None:
        if self._io is None:
            return
        data = self._io.readAll().data()
        if not data:
            return
        self._chunks.append(data)
        # a quick 16-bit mono copy (no resampling) just to measure loudness
        mono = convert_audio(data, self._rate, self._channels, self._format, target_rate=self._rate)
        level, done = self._detector.feed(mono)
        self.level_changed.emit(level)
        if done:
            self.stop()

    def stop(self, send: bool = True) -> None:
        """Stop recording. With send=False the audio is thrown away."""
        if self._source is None:
            return
        self._limit.stop()
        source, self._source, self._io = self._source, None, None
        source.stop()
        source.deleteLater()
        raw = b"".join(self._chunks)
        heard = bool(self._detector and self._detector.heard_speech)
        self._chunks = []
        if send:
            self.finished.emit(raw, self._rate, self._channels, self._format, heard)


class TranscribeWorker(QThread):
    """Converts and transcribes recorded speech in the background."""

    done = Signal(str, str)  # (text, error message)

    def __init__(self, raw: bytes, rate: int, channels: int, fmt: str, hint: str = ""):
        super().__init__()
        self.audio = (raw, rate, channels, fmt)
        self.hint = hint  # words Whisper should expect (your file names)

    def run(self) -> None:
        try:
            pcm = convert_audio(*self.audio)
            self.done.emit(transcribe(pcm, hint=self.hint), "")
        except SpeechError as error:
            self.done.emit("", str(error))
        except Exception as error:
            self.done.emit("", f"Voice problem: {error}")


# ============================================================ files + settings
class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class RegionPicker(QWidget):
    """A frozen picture of the screen. Drag a box around the ONE problem you want help with.
    Enter or a double-click = the whole screen. Esc = cancel."""

    picked = Signal(object)          # the part you chose (a QImage), or None if you cancelled

    def __init__(self, shot: QPixmap, area: QRect):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self._shot = shot
        self._a = None
        self._b = None
        self._done = False
        self.setGeometry(area)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _box(self) -> QRect:
        if self._a is None or self._b is None:
            return QRect()
        return QRect(self._a, self._b).normalized()

    def _source(self, box: QRect) -> QRect:
        """The same box in the picture's own pixels (a sharp screen has more pixels than the window has points)."""
        ratio = self._shot.width() / max(1, self.width())
        return QRect(int(box.x() * ratio), int(box.y() * ratio), max(1, int(box.width() * ratio)), max(1, int(box.height() * ratio)))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._shot)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        box = self._box()
        if not box.isNull():
            painter.drawPixmap(box, self._shot, self._source(box))
            painter.setPen(QPen(QColor("#ff4d5e"), 2))
            painter.drawRect(box)
        painter.setPen(QColor("white"))
        painter.setFont(QFont(painter.font().family(), 13))
        painter.drawText(self.rect().adjusted(0, 18, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                         "Drag a box around the problem     Enter = whole screen     Esc = cancel")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._a = self._b = event.position().toPoint()
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._a is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._b = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._a is None:
            return
        self._b = event.position().toPoint()
        box = self._box()
        if box.width() < 12 or box.height() < 12:      # a plain click, not a box: keep waiting
            self._a = self._b = None
            self.update()
            return
        self._finish(self._shot.copy(self._source(box)).toImage())

    def mouseDoubleClickEvent(self, event) -> None:
        self._finish(self._shot.toImage())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._finish(None)
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish(self._shot.toImage())

    def _finish(self, image) -> None:
        if self._done:
            return
        self._done = True
        self.hide()
        self.picked.emit(image)
        self.deleteLater()

    def closeEvent(self, event) -> None:
        if not self._done:
            self._done = True
            self.picked.emit(None)
        super().closeEvent(event)


def qimage_to_pil(image):
    """A Qt picture -> a Pillow picture (what the screen reader wants)."""
    from PIL import Image
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data()))).copy()


class FilePanel(QFrame):
    """Drop-box hint + the list of files Atom knows about."""

    browse_requested = Signal()
    remove_requested = Signal(list)
    clear_requested = Signal()
    move_requested = Signal(list, str)   # (paths, folder)
    folder_created = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("filePanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.heading = QLabel("Files")
        self.heading.setObjectName("title")
        layout.addWidget(self.heading)

        self._records: list = []
        self._folders: list[str] = []
        folder_row = QHBoxLayout()
        self.folder_box = QComboBox()
        self.folder_box.setToolTip("Show the files of one folder. New files go into the folder you are looking at.")
        self.folder_box.currentIndexChanged.connect(self._show_folder)
        new_folder = QPushButton("+ Folder")
        new_folder.setToolTip("Make a new folder")
        new_folder.clicked.connect(self._new_folder)
        folder_row.addWidget(self.folder_box, 1)
        folder_row.addWidget(new_folder)
        layout.addLayout(folder_row)

        self.drop_zone = ClickableLabel("Drop files or folders\nonto Atom or this window\n\n(or click to browse)")
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone.setCursor(Qt.CursorShape.PointingHandCursor)
        self.drop_zone.clicked.connect(self.browse_requested)
        layout.addWidget(self.drop_zone)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(self._open_item)
        layout.addWidget(self.list, 1)

        self.empty_hint = QLabel("No files yet.")
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_hint)

        buttons = QHBoxLayout()
        self.remove_btn = QPushButton("Remove")
        self.move_btn = QPushButton("Move to...")
        self.move_btn.setToolTip("File the selected files in a folder")
        self.clear_btn = QPushButton("Clear all")
        self.remove_btn.clicked.connect(self._emit_remove)
        self.clear_btn.clicked.connect(self.clear_requested)
        buttons.addWidget(self.remove_btn)
        buttons.addWidget(self.move_btn)
        buttons.addWidget(self.clear_btn)
        layout.addLayout(buttons)

        delete_key = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.list)
        delete_key.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_key.activated.connect(self._emit_remove)

    ALL = "All files"

    def current_folder(self) -> str | None:
        """The folder being shown (None = all files). New files are filed here."""
        name = self.folder_box.currentData()
        return name if name else None

    def refresh(self, records, folders=None) -> None:
        self._records = list(records)
        if folders is not None:
            self._folders = list(folders)
        keep = self.current_folder()
        counts: dict[str, int] = {}
        for record in self._records:
            counts[record.folder] = counts.get(record.folder, 0) + 1
        names = self._folders or sorted(counts)
        self.folder_box.blockSignals(True)
        self.folder_box.clear()
        self.folder_box.addItem(f"{self.ALL} ({len(self._records)})", "")
        for name in names:
            self.folder_box.addItem(f"{name} ({counts.get(name, 0)})", name)
        index = self.folder_box.findData(keep or "")
        self.folder_box.setCurrentIndex(index if index >= 0 else 0)
        self.folder_box.blockSignals(False)
        old_menu = self.move_btn.menu()
        if old_menu is not None:
            old_menu.deleteLater()
        menu = QMenu(self.move_btn)
        for name in names:
            action = menu.addAction(name)
            action.triggered.connect(lambda _checked=False, folder=name: self._emit_move(folder))
        menu.addSeparator()
        menu.addAction("New folder...").triggered.connect(lambda _checked=False: self._emit_move(None))
        self.move_btn.setMenu(menu)
        self._show_folder()

    def _show_folder(self, _index: int = 0) -> None:
        folder = self.current_folder()
        shown = [r for r in self._records if not folder or r.folder == folder]
        self.list.clear()
        for record in shown:
            item = QListWidgetItem(f"{record.name}\n{record.subtitle}")
            item.setData(Qt.ItemDataRole.UserRole, record.path)
            item.setToolTip(f"{record.path}\nFolder: {record.folder}")
            self.list.addItem(item)
        total = len(self._records)
        self.heading.setText(f"Files ({total})" if total else "Files")
        self.empty_hint.setText("No files yet." if not total else f"Nothing in '{folder}' yet. Drop files here.")
        self.empty_hint.setVisible(not shown)
        self.remove_btn.setEnabled(bool(shown))
        self.move_btn.setEnabled(bool(shown))
        self.clear_btn.setEnabled(total > 0)

    def _new_folder(self) -> None:
        name, ok = QInputDialog.getText(self, "New folder", "Name of the new folder:")
        if ok and name.strip():
            self.folder_created.emit(name.strip())

    def _emit_move(self, folder: str | None) -> None:
        paths = [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]
        if not paths:
            return
        if folder is None:
            folder, ok = QInputDialog.getText(self, "New folder", "Move them to a new folder called:")
            if not ok or not folder.strip():
                return
        self.move_requested.emit(paths, folder.strip())

    def _emit_remove(self) -> None:
        paths = [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]
        if paths:
            self.remove_requested.emit(paths)

    def _open_item(self, item: QListWidgetItem) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole)))


class FilesDialog(QDialog):
    """The 'Files' window opened from the menu bar. Drops work here too."""

    files_dropped = Signal(list)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Atom - Files")
        self.setAcceptDrops(True)
        self.resize(320, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = FilePanel()
        layout.addWidget(self.panel)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)


_RUNNING_WORKERS: list = []  # keeps background threads alive until they finish


class SpotifyConnectWorker(QThread):
    """Waits for you to approve Atom in the browser without freezing the window."""

    done = Signal(bool, str)  # (worked, message)

    def run(self) -> None:
        try:
            self.done.emit(True, spotify.connect())
        except spotify.SpotifyError as error:
            self.done.emit(False, str(error))
        except Exception as error:
            self.done.emit(False, f"Something went wrong: {error}")


class IndexWorker(QThread):
    """Reads dropped files (slow for big ones) without freezing the window."""

    done = Signal(list, list)  # (files added, problems)

    def __init__(self, store: FileStore, paths: list, folder: str | None = None):
        super().__init__()
        self.store = store
        self.paths = paths
        self.folder = folder

    def run(self) -> None:
        try:
            added, problems = self.store.add(self.paths, folder=self.folder)
        except Exception as error:
            added, problems = [], [f"I couldn't read those files: {error}"]
        self.done.emit(added, problems)


class SuggestWorker(QThread):
    """Lets Atom look for changed files and overdue work in the background."""

    done = Signal(str)  # what to say, or "" if nothing

    def __init__(self, suggester: Suggester):
        super().__init__()
        self.suggester = suggester

    def run(self) -> None:
        try:
            self.done.emit(self.suggester.check() or "")
        except Exception:
            self.done.emit("")  # a suggestion must never break Atom


class DayDialog(QDialog):
    """Reminders and the to-do list in one window: snooze, cancel, tick off, add."""

    changed = Signal()

    def __init__(self, parent: QWidget, book):
        super().__init__(parent)
        self.book = book
        self.setWindowTitle("Atom - Reminders and to-dos")
        self.resize(420, 540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(6)

        title = QLabel("Reminders")
        title.setObjectName("title")
        layout.addWidget(title)
        self.reminder_list = QListWidget()
        layout.addWidget(self.reminder_list, 1)
        row = QHBoxLayout()
        snooze = QPushButton("Snooze 10 min")
        snooze.clicked.connect(self._snooze)
        cancel = QPushButton("Cancel reminder")
        cancel.clicked.connect(self._cancel)
        row.addWidget(snooze)
        row.addWidget(cancel)
        row.addStretch(1)
        layout.addLayout(row)
        hint = QLabel("To add one, tell Atom: \"remind me tomorrow 9am to call the bank\".")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addSpacing(6)
        title2 = QLabel("To-do list")
        title2.setObjectName("title")
        layout.addWidget(title2)
        self.todo_list = QListWidget()
        layout.addWidget(self.todo_list, 1)
        row2 = QHBoxLayout()
        done = QPushButton("Done")
        done.clicked.connect(self._done)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        row2.addWidget(done)
        row2.addWidget(remove)
        row2.addStretch(1)
        layout.addLayout(row2)
        add_row = QHBoxLayout()
        self.new_item = QLineEdit()
        self.new_item.setPlaceholderText("Add something to the list...")
        self.new_item.returnPressed.connect(self._add)
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        add_row.addWidget(self.new_item, 1)
        add_row.addWidget(add)
        layout.addLayout(add_row)
        self.message = QLabel()
        self.message.setObjectName("muted")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.refresh()

    def refresh(self) -> None:
        now = datetime.now()
        self.reminder_list.clear()
        for r in self.book.reminders():
            again = f" (repeats {r.repeat})" if r.repeat else ""
            item = QListWidgetItem(f"{timeparse.nice(r.due, now)}  -  {r.text}{again}")
            item.setData(Qt.ItemDataRole.UserRole, r.id)
            self.reminder_list.addItem(item)
        self.todo_list.clear()
        today = date.today()
        for t in self.book.todos():
            tag = ""
            if t.due:
                tag = ("  [OVERDUE " if t.due < today else "  [due ") + t.due.strftime("%a %d %b") + "]"
            item = QListWidgetItem(t.text + tag)
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            self.todo_list.addItem(item)

    def _picked(self, widget) -> int | None:
        item = widget.currentItem()
        if item is None:
            self.message.setText("Click one in the list first.")
            return None
        self.message.setText("")
        return int(item.data(Qt.ItemDataRole.UserRole))

    def _run(self, action) -> None:
        try:
            action()
        except Exception as error:
            self.message.setText(str(error))
        self.refresh()
        self.changed.emit()

    def _snooze(self) -> None:
        picked = self._picked(self.reminder_list)
        if picked is not None:
            self._run(lambda: self.book.snooze(picked, 10))

    def _cancel(self) -> None:
        picked = self._picked(self.reminder_list)
        if picked is not None:
            self._run(lambda: self.book.cancel_reminder(f"#{picked}"))

    def _done(self) -> None:
        picked = self._picked(self.todo_list)
        if picked is not None:
            self._run(lambda: self.book.complete_todo(f"#{picked}"))

    def _remove(self) -> None:
        picked = self._picked(self.todo_list)
        if picked is not None:
            self._run(lambda: self.book.remove_todo(f"#{picked}"))

    def _add(self) -> None:
        text = self.new_item.text().strip()
        if text:
            self.new_item.clear()
            self._run(lambda: self.book.add_todo(text))


class CheckupDialog(QDialog):
    """Shows the "Check my setup" report: what works, what is optional, what to fix."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Atom - Check my setup")
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 12px;")
        self.text.setPlainText("Checking...")
        layout.addWidget(self.text, 1)
        row = QHBoxLayout()
        again = QPushButton("Check again")
        again.clicked.connect(self.refresh)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        log_btn = QPushButton("Open the log")
        log_btn.clicked.connect(self._open_log)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for button in (again, copy, log_btn):
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        QTimer.singleShot(50, self.refresh)      # let the window appear first; the checks take a second

    def refresh(self) -> None:
        self.text.setPlainText("Checking...")
        QApplication.processEvents()
        self.text.setPlainText(checkup.report())

    def _open_log(self) -> None:
        target = atomlog.path()
        if not target.exists():
            atomlog.log("log opened")
        try:
            os.startfile(str(target))            # Windows opens it in Notepad
        except (AttributeError, OSError):
            QMessageBox.information(self, "Atom's log", f"The log is here:\n{target}\n\nLast lines:\n{atomlog.tail(15)}")


class SettingsDialog(QDialog):
    """Pick the AI provider, paste its key, choose the voice language."""

    saved = Signal()
    quit_requested = Signal()
    open_call = Signal()
    open_profile = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Atom - Settings")
        self.setMinimumWidth(460)

        settings = config.load_settings()
        # what you type for each provider is remembered while this window is open
        self._keys = dict(settings.get("keys") or {})
        if settings.get("api_key") and not self._keys.get("claude"):
            self._keys["claude"] = settings["api_key"]  # key saved by an older version
        self._models = dict(settings.get("models") or {})
        self._current = config.get_provider()

        # the settings scroll if the screen is small; Quit / Close / Save stay pinned at the bottom
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 18, 18, 8)
        layout.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        try:
            self.resize(500, max(420, min(780, self.screen().availableGeometry().height() - 90)))
        except Exception:
            self.resize(500, 640)

        title = QLabel("AI provider")
        title.setObjectName("title")
        layout.addWidget(title)
        self.provider_box = QComboBox()
        for provider_id, info in config.PROVIDERS.items():
            self.provider_box.addItem(info["label"], provider_id)
        self.provider_box.setCurrentIndex(self.provider_box.findData(self._current))
        layout.addWidget(self.provider_box)

        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.note.setTextFormat(Qt.TextFormat.RichText)
        self.note.setOpenExternalLinks(True)
        layout.addWidget(self.note)

        layout.addSpacing(4)
        key_title = QLabel("API key")
        key_title.setObjectName("title")
        layout.addWidget(key_title)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.key_edit)
        self.key_hint = QLabel()
        self.key_hint.setObjectName("muted")
        self.key_hint.setWordWrap(True)
        layout.addWidget(self.key_hint)

        model_title = QLabel("Model")
        model_title.setObjectName("title")
        layout.addWidget(model_title)
        self.model_edit = QLineEdit()
        layout.addWidget(self.model_edit)
        model_hint = QLabel("Leave as is unless the provider renames its models.")
        model_hint.setObjectName("muted")
        layout.addWidget(model_hint)

        layout.addSpacing(8)
        lang_title = QLabel("Voice language")
        lang_title.setObjectName("title")
        layout.addWidget(lang_title)
        self.lang_edit = QLineEdit(config.get_speech_language())
        self.lang_edit.setPlaceholderText(config.SPEECH_LANGUAGE)
        layout.addWidget(self.lang_edit)
        lang_hint = QLabel(
            "Language you speak to Atom, e.g. en-US, fil-PH (Filipino), es-ES, ja-JP.\n"
            + (
                "Your voice is sent to Groq (Whisper) to be turned into text."
                if speech_engine() == "whisper"
                else "Your voice is sent to Google's speech service to be turned into text. "
                "Add a Groq key above for the more accurate Whisper."
            )
        )
        lang_hint.setObjectName("muted")
        lang_hint.setWordWrap(True)
        layout.addWidget(lang_hint)
        self.google_only = QCheckBox("Use Google speech instead of Whisper")
        self.google_only.setChecked(config.load_settings().get("speech_engine") == "google")
        layout.addWidget(self.google_only)

        layout.addSpacing(8)
        voice_title = QLabel("Atom's voice (when he reads answers aloud)")
        voice_title.setObjectName("title")
        layout.addWidget(voice_title)
        self._speaker = getattr(parent, "speaker", None)
        saved = config.load_settings()
        self.mode_box = QComboBox()
        self.mode_box.addItem("Boy voice: a young robot boy", "boy")
        self.mode_box.addItem("Electric voice: real words with a robot sound", "robot")
        self.mode_box.addItem("Babble: a cute blip for every syllable (like Capri)", "babble")
        self.mode_box.addItem("Windows voice: plain, real speech", "windows")
        self.mode_box.setCurrentIndex(max(0, self.mode_box.findData(saved.get("voice_mode") or config.VOICE_MODE)))
        layout.addWidget(self.mode_box)
        self.boy_box = QComboBox()
        for key, label in kokovoice.VOICES.items():
            self.boy_box.addItem(label, key)
        self.boy_box.setCurrentIndex(max(0, self.boy_box.findData(saved.get("boy_voice") or config.BOY_VOICE)))
        layout.addWidget(self.boy_box)
        self.age_box = QComboBox()
        for key, label in robot.AGE_LABELS.items():
            self.age_box.addItem(label, key)
        self.age_box.setCurrentIndex(max(0, self.age_box.findData(saved.get("boy_age") or config.BOY_AGE)))
        layout.addWidget(self.age_box)
        self.boy_status = QLabel("")
        self.boy_status.setObjectName("muted")
        self.boy_status.setWordWrap(True)
        layout.addWidget(self.boy_status)
        self.style_box = QComboBox()
        for key, label in babble.STYLES.items():
            self.style_box.addItem(label, key)
        self.style_box.setCurrentIndex(max(0, self.style_box.findData(saved.get("babble_style") or config.BABBLE_STYLE)))
        layout.addWidget(self.style_box)
        self.fx_box = QComboBox()
        for key, label in robot.STYLES.items():
            self.fx_box.addItem(label, key)
        self.fx_box.setCurrentIndex(max(0, self.fx_box.findData(saved.get("robot_style") or config.ROBOT_STYLE)))
        layout.addWidget(self.fx_box)
        self.voice_box = QComboBox()
        self.voice_box.addItem("Windows default voice", None)
        chosen = saved.get("voice") or {}
        if self._speaker and self._speaker.has_windows_voice:
            for voice in self._speaker.voices():
                self.voice_box.addItem(voice["label"], f'{voice["name"]}|{voice["locale"]}')
            index = self.voice_box.findData(f'{chosen.get("name")}|{chosen.get("locale")}')
            self.voice_box.setCurrentIndex(max(0, index))
        else:
            self.voice_box.setEnabled(False)
        layout.addWidget(self.voice_box)

        def slider_row(text: str, value: float) -> QSlider:
            row = QHBoxLayout()
            label = QLabel(text)
            label.setMinimumWidth(60)
            row.addWidget(label)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-10, 10)
            slider.setValue(round(max(-1.0, min(1.0, float(value))) * 10))
            row.addWidget(slider)
            layout.addLayout(row)
            return slider

        self.rate_slider = slider_row("Speed", saved.get("speech_rate", config.SPEECH_RATE))
        self.pitch_slider = slider_row("Pitch", saved.get("speech_pitch", config.SPEECH_PITCH))
        self.test_voice_btn = QPushButton("Test this voice")
        self.test_voice_btn.clicked.connect(self._test_voice)
        layout.addWidget(self.test_voice_btn)
        self.mode_box.currentIndexChanged.connect(lambda _=0: self._mode_changed())
        self._mode_changed()
        self.finished.connect(self._restore_voice)
        voice_hint = QLabel(
            "The boy voice is made on this computer by the free Kokoro model, then made younger, with a faint robot "
            "shimmer. It takes a second to prepare each answer. Until it is set up, he uses "
            "the Windows voice chosen below, with the same boy sound. Speed and Pitch change all voices. "
            "More Windows voices: Windows Settings > Time & language > Speech > Add voices."
        )
        voice_hint.setObjectName("muted")
        voice_hint.setWordWrap(True)
        layout.addWidget(voice_hint)

        layout.addSpacing(8)
        system_title = QLabel("On this computer")
        system_title.setObjectName("title")
        layout.addWidget(system_title)
        self.startup_box = QCheckBox("Start Atom when I sign in to Windows")
        self.startup_box.setChecked(startup.is_enabled())
        self.startup_box.setEnabled(startup.supported())
        layout.addWidget(self.startup_box)
        hotkey_hint = QLabel(
            f"Press {(config.load_settings().get('hotkey') or config.HOTKEY).upper()} in any program to call Atom "
            "(change HOTKEY in config.py)."
        )
        hotkey_hint.setObjectName("muted")
        hotkey_hint.setWordWrap(True)
        layout.addWidget(hotkey_hint)
        keys_hint = QLabel(
            "With Atom in front: Ctrl+M talk, Ctrl+O add files, Ctrl+L type, Ctrl+D reminders and to-dos, "
            "Ctrl+B today's briefing, Ctrl+R status report, Ctrl+Shift+C call window, Ctrl+Shift+H hear a call, Ctrl+Shift+S pick a problem on screen, Ctrl+P my skills, "
            "Ctrl+, settings, Ctrl+H hide, Esc stop talking."
        )
        keys_hint.setObjectName("muted")
        keys_hint.setWordWrap(True)
        layout.addWidget(keys_hint)

        layout.addSpacing(8)
        spotify_title = QLabel("Spotify (lets Atom play music himself - needs Premium)")
        spotify_title.setObjectName("title")
        layout.addWidget(spotify_title)
        self.spotify_id_edit = QLineEdit(config.load_settings().get("spotify_client_id", ""))
        self.spotify_id_edit.setPlaceholderText("Client ID from developer.spotify.com/dashboard")
        layout.addWidget(self.spotify_id_edit)
        spotify_row = QHBoxLayout()
        self.spotify_btn = QPushButton("Connect Spotify")
        self.spotify_btn.clicked.connect(self._connect_spotify)
        self.spotify_status = QLabel()
        self.spotify_status.setObjectName("muted")
        self.spotify_status.setWordWrap(True)
        spotify_row.addWidget(self.spotify_btn)
        spotify_row.addWidget(self.spotify_status, 1)
        layout.addLayout(spotify_row)
        spotify_hint = QLabel(
            "In your Spotify app's settings, add this Redirect URI exactly:\n"
            + spotify.redirect_uri()
        )
        spotify_hint.setObjectName("muted")
        spotify_hint.setWordWrap(True)
        spotify_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(spotify_hint)
        self._show_spotify_status()

        layout.addSpacing(8)
        health_title = QLabel(f"Health and backup (Atom {version.VERSION})")
        health_title.setObjectName("title")
        layout.addWidget(health_title)
        health_row = QHBoxLayout()
        check_btn = QPushButton("Check my setup")
        check_btn.clicked.connect(self._check_setup)
        backup_btn = QPushButton("Back up now")
        backup_btn.clicked.connect(self._back_up)
        restore_btn = QPushButton("Restore backup...")
        restore_btn.clicked.connect(self._restore)
        for button in (check_btn, backup_btn, restore_btn):
            health_row.addWidget(button)
        layout.addLayout(health_row)
        self.health_status = QLabel()
        self.health_status.setObjectName("muted")
        self.health_status.setWordWrap(True)
        self.health_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.health_status)

        layout.addSpacing(8)
        call_title = QLabel("Calls and interviews")
        call_title.setObjectName("title")
        layout.addWidget(call_title)
        call_row = QHBoxLayout()
        call_btn = QPushButton("Call helper...")
        call_btn.clicked.connect(self._open_call)
        skills_btn = QPushButton("My skills and files...")
        skills_btn.clicked.connect(self._open_profile)
        call_row.addWidget(call_btn)
        call_row.addWidget(skills_btn)
        call_row.addStretch(1)
        layout.addLayout(call_row)
        call_hint = QLabel(
            "Atom listens to the sound of your call from your speakers, reads your screen, suggests answers from your own "
            "skills, and lists what you were asked to do. Only you see it. Use headphones, and check that recording the "
            "call is allowed (and that an interview's rules allow help)."
        )
        call_hint.setObjectName("muted")
        call_hint.setWordWrap(True)
        layout.addWidget(call_hint)

        saved_in = QLabel(f"Keys are saved on this computer in {config.SETTINGS_FILE}")
        saved_in.setObjectName("muted")
        saved_in.setWordWrap(True)
        layout.addWidget(saved_in)

        buttons = QHBoxLayout()
        quit_btn = QPushButton("Quit Atom")
        quit_btn.clicked.connect(self.quit_requested)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        buttons.addWidget(quit_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        buttons.addWidget(save_btn)
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(18, 8, 18, 14)
        footer_layout.addLayout(buttons)
        outer.addWidget(footer)

        self._show_provider(self._current)
        self.provider_box.currentIndexChanged.connect(self._provider_changed)

    # --- calls
    def _open_call(self) -> None:
        self.open_call.emit()
        self.reject()

    def _open_profile(self) -> None:
        self.open_profile.emit()
        self.reject()

    # --- health and backup
    def _check_setup(self) -> None:
        CheckupDialog(self).exec()

    def _back_up(self) -> None:
        try:
            made = backup.create()
        except Exception as error:
            atomlog.exception("backup", error)
            self.health_status.setText(f"I couldn't make the backup: {error}")
            return
        atomlog.log(f"backup made: {made}")
        self.health_status.setText(
            f"Backup saved: {made}\nCopy it to a USB stick or cloud drive for a safe copy. "
            "It contains your keys, so keep it private."
        )

    def _restore(self) -> None:
        start = backup.folder()
        start.mkdir(parents=True, exist_ok=True)
        chosen, _ = QFileDialog.getOpenFileName(self, "Choose an Atom backup", str(start), "Atom backup (*.zip)")
        if not chosen:
            return
        if not backup.is_backup(Path(chosen)):
            self.health_status.setText("That file isn't an Atom backup.")
            return
        answer = QMessageBox.question(
            self, "Restore backup",
            "Atom will close, and the next time he starts he swaps in this backup "
            "(a safety copy of what you have now is saved first).\n\nRestore and close Atom?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            count = backup.stage_restore(Path(chosen))
        except Exception as error:
            atomlog.exception("restore", error)
            self.health_status.setText(f"I couldn't read that backup: {error}")
            return
        atomlog.log(f"restore staged: {chosen} ({count} files)")
        self.quit_requested.emit()

    # --- Spotify
    def _show_spotify_status(self, message: str = "") -> None:
        if message:
            self.spotify_status.setText(message)
        elif spotify.connected():
            self.spotify_status.setText("Connected.")
        else:
            self.spotify_status.setText("Not connected.")

    def _connect_spotify(self) -> None:
        cid = self.spotify_id_edit.text().strip()
        if not cid:
            self._show_spotify_status("Paste your Client ID first.")
            return
        settings = config.load_settings()
        settings["spotify_client_id"] = cid
        config.save_settings(settings)  # connect() reads the ID from the settings file
        self.spotify_btn.setEnabled(False)
        self._show_spotify_status("Approve Atom in the browser that just opened...")
        worker = SpotifyConnectWorker()
        _RUNNING_WORKERS.append(worker)
        worker.done.connect(self._spotify_finished)
        worker.finished.connect(lambda: _RUNNING_WORKERS.remove(worker))
        worker.start()

    def _spotify_finished(self, worked: bool, message: str) -> None:
        self.spotify_btn.setEnabled(True)
        self._show_spotify_status(message)

    # --- switching providers keeps what you typed for the one you left
    def _remember_fields(self) -> None:
        self._keys[self._current] = self.key_edit.text().strip()
        self._models[self._current] = self.model_edit.text().strip()

    def _provider_changed(self) -> None:
        self._remember_fields()
        self._current = self.provider_box.currentData()
        self._show_provider(self._current)

    def _show_provider(self, provider_id: str) -> None:
        info = config.PROVIDERS[provider_id]
        link = f' <a href="{info["key_url"]}">Get a key / download</a>' if info.get("key_url") else ""
        self.note.setText(info["note"] + link)
        self.key_edit.setText(self._keys.get(provider_id, ""))
        self.key_edit.setEnabled(info["needs_key"])
        self.key_edit.setPlaceholderText(info.get("key_hint", ""))
        self.model_edit.setText(self._models.get(provider_id) or info["model"])
        if config.key_from_env(provider_id):
            self.key_hint.setText(
                f"The {info['env']} environment variable is set, so it is used instead of this box."
            )
        else:
            self.key_hint.setText("")
        self.key_hint.setVisible(bool(self.key_hint.text()))

    def _restore_voice(self, _result: int = 0) -> None:
        """Closing Settings: stop any test sound and go back to the saved voice (a cancelled test is forgotten)."""
        if self._speaker:
            self._speaker.stop()
            self._speaker.apply_settings()

    def _mode_changed(self) -> None:
        """Only the controls that matter for the chosen kind of voice are switched on."""
        mode = self.mode_box.currentData()
        self.boy_box.setVisible(mode == "boy")
        self.age_box.setVisible(mode == "boy")
        missing = kokovoice.problem() if mode == "boy" else ""
        self.boy_status.setText(f"Boy voice set-up: {missing}" if missing else "")
        self.boy_status.setVisible(bool(missing))
        self.style_box.setVisible(mode == "babble")
        self.fx_box.setVisible(mode == "robot")
        has_windows = bool(self._speaker and self._speaker.has_windows_voice)
        self.voice_box.setEnabled(mode != "babble" and has_windows)
        if not self._speaker:
            can_play = False
        elif mode == "babble":
            can_play = self._speaker.babbler.available
        elif mode == "robot":
            can_play = self._speaker.robot.available
        elif mode == "boy":
            can_play = self._speaker.boy.available
        else:
            can_play = has_windows
        self.test_voice_btn.setEnabled(can_play)

    def _voice_choice(self) -> tuple[str | None, str | None, float, float]:
        data = self.voice_box.currentData()
        name, _, locale = data.partition("|") if data else (None, None, None)
        return name, locale, self.rate_slider.value() / 10, self.pitch_slider.value() / 10

    def _test_voice(self) -> None:
        """Speak a sample with what is chosen right now (nothing is saved yet)."""
        if not self._speaker:
            return
        name, locale, rate, pitch = self._voice_choice()
        self._speaker.apply_settings(
            name or "", locale, rate, pitch, mode=self.mode_box.currentData(),
            style=self.style_box.currentData(), fx=self.fx_box.currentData(),
            boy_voice=self.boy_box.currentData(), age=self.age_box.currentData(),
        )
        self._speaker.say(self._speaker.SAMPLE)

    def _save(self) -> None:
        self._remember_fields()
        settings = config.load_settings()
        settings["provider"] = self._current
        settings["keys"] = {k: v for k, v in self._keys.items() if v}
        settings["models"] = {
            k: v for k, v in self._models.items()
            if v and k in config.PROVIDERS and v != config.PROVIDERS[k]["model"]
        }
        settings.pop("api_key", None)  # now stored under "keys"
        settings["speech_language"] = self.lang_edit.text().strip() or config.SPEECH_LANGUAGE
        settings["spotify_client_id"] = self.spotify_id_edit.text().strip()
        if self.google_only.isChecked():
            settings["speech_engine"] = "google"
        else:
            settings.pop("speech_engine", None)
        name, locale, rate, pitch = self._voice_choice()
        if name:
            settings["voice"] = {"name": name, "locale": locale}
        else:
            settings.pop("voice", None)
        settings["speech_rate"], settings["speech_pitch"] = rate, pitch
        settings["voice_mode"] = self.mode_box.currentData()
        settings["babble_style"] = self.style_box.currentData()
        settings["robot_style"] = self.fx_box.currentData()
        settings["boy_voice"] = self.boy_box.currentData()
        settings["boy_age"] = self.age_box.currentData()
        config.save_settings(settings)
        if self._speaker:
            self._speaker.apply_settings()  # use the choice from now on
        if startup.supported() and self.startup_box.isChecked() != startup.is_enabled():
            startup.set_enabled(self.startup_box.isChecked())
        self.saved.emit()
        self.accept()


# =============================================================== main window
class MainWindow(QMainWindow):
    file_changed = Signal()  # the watcher (a background thread) says a file was saved
    chunk_started = Signal(str, float)  # the voice (a background thread) starts a sentence: (its words, seconds)
    picked_text = Signal(str, str)   # (words, problem): the part of the screen you picked has been read (background thread)
    screen_hide = Signal()   # a screen reading (background thread) wants Atom's windows out of the picture
    screen_show = Signal()

    def __init__(self, store: FileStore, brain: Brain):
        super().__init__()
        self.store = store
        self.brain = brain
        self._watcher: FileWatcher | None = None
        self.speaker = Speaker()          # reads answers aloud (electric voice, cute babble or a Windows voice)
        self._via_voice = False           # was the current question spoken?
        self._streaming_voice = False     # is he already talking while the answer is still being written?
        self._reset_reveal()
        QTimer.singleShot(2500, self.speaker.warm_up)   # load the boy voice now, so his first sentence isn't slow
        self._reveal_timer = QTimer(self)  # shows the words at the pace of his voice
        self._reveal_timer.timeout.connect(self._reveal_tick)
        self.chunk_started.connect(self._on_chunk)
        self._pinned = config.ALWAYS_ON_TOP
        self._quitting = False
        self._tray_hint_shown = False
        self._worker: ReplyWorker | None = None
        self._voice_worker: TranscribeWorker | None = None
        self._drag_offset = None
        self._indexing: IndexWorker | None = None   # files being read in the background
        self._index_queue: list[tuple] = []         # more drops waiting their turn: (paths, folder)
        self.suggester = Suggester(store)
        self._suggest_worker: SuggestWorker | None = None
        self._last_activity = time.monotonic()      # when you last talked to Atom
        self._last_remark_at = time.monotonic()     # when he last said an idle remark
        self._last_remark_text: str | None = None
        self._chat_held = False                     # an answer of his is on show: he will not write over it on his own
        self._call_panel = None                     # Step 13: the call window, the skills window and the call engine
        self._call_ctl = None
        self._profile_dialog = None
        self._screen_hidden: list = []
        self._picker = None
        self.picked_text.connect(self._on_picked_text)
        self.screen_hide.connect(self._hide_for_screen)
        self.screen_show.connect(self._show_after_screen)
        if getattr(self.brain, "tools", None) is not None:
            self.brain.tools.screen_reader = self.read_screen_now   # "what's on my screen?" hides Atom first

        self.setWindowTitle(config.APP_NAME)
        self.setWindowIcon(make_icon())
        # see-through window with no title bar or border
        flags = Qt.WindowType.FramelessWindowHint
        if self._pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint  # stay in front of Spotify, Excel, ...
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(*(config.HUD_WINDOW_SIZE if IS_HUD else config.WINDOW_SIZE))
        self.setAcceptDrops(True)  # drop files anywhere on Atom

        self._build_ui()
        self._build_tray()
        self._refresh_files()
        self._move_to_corner()
        self._welcome()
        if CHARACTER_NOTE:
            QTimer.singleShot(2500, lambda: self._speak_up(CHARACTER_NOTE, mood="worried", notify=True))
        self._start_suggestions()
        self._start_daily()
        self._start_idle_life()
        self._start_hotkey()
        self.input.textChanged.connect(lambda _text: self._wake())  # typing wakes him and counts as activity

    # ------------------------------------------------------------ building
    def _build_ui(self) -> None:
        self.central = QWidget()
        self.central.setObjectName("central")
        self.setCentralWidget(self.central)
        root = QVBoxLayout(self.central)
        margins = (14, 12, 14, 10) if IS_HUD else (14, 14, 14, 14)
        root.setContentsMargins(*margins)
        root.setSpacing(8)

        # --- top menu bar
        self.menu_bar = QFrame()
        self.menu_bar.setObjectName("menuBar")
        bar = QHBoxLayout(self.menu_bar)
        bar.setContentsMargins(8, 4, 8, 4)
        bar.setSpacing(2)
        self.upload_btn = QPushButton("Upload files")
        self.upload_btn.clicked.connect(self.browse_files)
        self.files_btn = QPushButton("Files")
        self.files_btn.clicked.connect(self.show_files)
        self.report_btn = QPushButton("Report")
        self.report_btn.setToolTip("Atom reads your files and writes a status report")
        self.report_btn.clicked.connect(self.make_report)
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.show_settings)
        self.pin_btn = QPushButton("Pin")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("Keep Atom above all other windows")
        self.pin_btn.setChecked(self._pinned)  # before connecting, so it doesn't fire yet
        self.pin_btn.toggled.connect(self.set_pinned)
        self.hide_btn = QPushButton("×")
        self.hide_btn.setToolTip("Hide Atom (he stays in the tray)")
        self.hide_btn.clicked.connect(self.hide_to_tray)
        if IS_HUD:  # short labels so the bar is never crowded (the full names are in the tooltips)
            self.upload_btn.setText("+ Add")
            self.upload_btn.setToolTip("Upload files for Atom to read (Ctrl+O)")
            self.files_btn.setToolTip("See the files Atom has read")
            self.settings_btn.setText("\u2699")
            self.settings_btn.setToolTip("Settings")
        for button in (self.upload_btn, self.files_btn, self.report_btn, self.settings_btn, self.pin_btn, self.hide_btn):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            bar.addWidget(button)
        if IS_HUD:  # "ATOM" on the left, the buttons on the right
            title = QLabel("ATOM")
            title.setObjectName("hudTitle")
            title.setFont(hud_font(12, True, 3.0))
            bar.insertWidget(0, title)
            bar.insertStretch(1, 1)
            root.addWidget(self.menu_bar)
            root.addStretch(1)  # the rest sits at the bottom; the window around it is see-through
        else:
            menu_row = QHBoxLayout()
            menu_row.addStretch(1)
            menu_row.addWidget(self.menu_bar)
            menu_row.addStretch(1)
            root.addLayout(menu_row)
            root.addStretch(1)

        # --- your bubble (right) and Atom's bubble (centre, pointing at him)
        if IS_HUD:  # one chat box: your last line on top, Atom's reply below it
            self.atom_bubble = Bubble("atom", config.HUD_BUBBLE_MAX)
            self.user_bubble = _Quote(self.atom_bubble)
            self.user_row = _QuoteRow(self.atom_bubble)
            root.addWidget(self._wrap(self.atom_bubble, Qt.AlignmentFlag.AlignHCenter))
        else:
            self.user_bubble = Bubble("user", config.USER_BUBBLE_MAX)
            self.user_row = self._wrap(self.user_bubble, Qt.AlignmentFlag.AlignRight)
            self.user_row.hide()  # nothing to show until you say something
            root.addWidget(self.user_row)

            self.atom_bubble = Bubble("atom", config.ATOM_BUBBLE_MAX)
            root.addWidget(self._wrap(self.atom_bubble, Qt.AlignmentFlag.AlignHCenter))

        # --- the character
        self.character = make_character()
        if IS_PLATE:  # no box around him: he stands on the see-through window, the plate's tail points at him
            root.addWidget(self.character, 0, Qt.AlignmentFlag.AlignHCenter)
            self._plate_timer = QTimer(self)   # keeps the plate's colours and portrait in step with his mood
            self._plate_timer.timeout.connect(lambda: self.atom_bubble.sync(self.character))
            self._plate_timer.start(80)
        elif IS_HUD:
            root.addWidget(HudFrame(self.character), 0, Qt.AlignmentFlag.AlignHCenter)
        else:
            root.addWidget(self.character, 0, Qt.AlignmentFlag.AlignHCenter)
            extra = max(0, self.character.height() - 190)  # a taller character gets a taller window
            if extra:
                self.setFixedSize(config.WINDOW_SIZE[0], config.WINDOW_SIZE[1] + extra)

        # --- the box you type in
        self.input = QLineEdit()
        self.input.setObjectName("chatInput")
        self.input.setPlaceholderText("Talk to Atom..." if IS_HUD else "Message Atom...")
        self.input.setAcceptDrops(False)  # so drops reach the window, not the text box
        self.input.returnPressed.connect(self.send)

        self.mic_btn = QPushButton("\U0001F3A4")  # microphone emoji
        self.mic_btn.setObjectName("micBtn")
        self.mic_btn.setCheckable(True)
        self.mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mic_btn.setToolTip("Click and talk to Atom (Ctrl+M)")
        self.mic_btn.clicked.connect(self.toggle_mic)

        self.speak_btn = QPushButton("\U0001F50A")  # speaker emoji
        self.speak_btn.setObjectName("speakBtn")
        self.speak_btn.setCheckable(True)
        self.speak_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.speak_btn.setChecked(bool(config.load_settings().get("speak_replies", config.SPEAK_REPLIES)))
        self._refresh_speak_button()
        self.speak_btn.toggled.connect(self._on_speak_toggled)

        self.hear_btn = QPushButton("\U0001F4DE")  # telephone receiver: listen to a call
        self.hear_btn.setObjectName("hearBtn")
        self.hear_btn.setCheckable(True)
        self.hear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hear_btn.setToolTip("Hear: Atom listens to the call on your speakers and suggests answers (Ctrl+Shift+H). Click again to stop.")
        self.hear_btn.clicked.connect(self.toggle_hear)

        self.look_btn = QPushButton("\U0001F5A5")  # desktop computer: read the screen
        self.look_btn.setObjectName("lookBtn")
        self.look_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.look_btn.setToolTip("Screen: drag a box around ONE problem on your screen and Atom works on just that (Ctrl+Shift+S)")
        self.look_btn.clicked.connect(self.pick_screen_problem)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.hear_btn)
        input_row.addWidget(self.look_btn)
        input_row.addWidget(self.speak_btn)
        input_row.addWidget(self.mic_btn)
        if IS_HUD and not IS_PLATE:
            tag = QLabel("EN // SAY ATOM")
            tag.setObjectName("hudTag")
            tag.setFont(hud_font(7, True, 1.8))
            root.addWidget(tag)
        root.addLayout(input_row)
        if IS_HUD and not IS_PLATE:
            hint = QLabel("ENTER \u21B5 SEND   \u00B7   CTRL+M MIC")
            hint.setObjectName("hudHint")
            hint.setFont(hud_font(6.5, True, 1.4))
            hint.setAlignment(Qt.AlignmentFlag.AlignRight)
            root.addWidget(hint)

        self.recorder = Recorder(self)
        self.recorder.level_changed.connect(self.character.set_level)
        self.recorder.finished.connect(self._on_recorded)
        self.recorder.failed.connect(self._on_voice_failed)

        # dialogs (created now, shown from the menu bar)
        self.files_dialog = FilesDialog(self)
        self.files_dialog.files_dropped.connect(lambda paths: self.add_paths(paths, self.files_dialog.panel.current_folder()))
        panel = self.files_dialog.panel
        panel.move_requested.connect(self.move_files)
        panel.folder_created.connect(self.create_folder)
        panel.browse_requested.connect(self.browse_files)
        panel.remove_requested.connect(self.remove_files)
        panel.clear_requested.connect(self.clear_files)

        self.setStyleSheet(build_stylesheet())
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.browse_files)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.toggle_mic)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.show_settings)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.show_day)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self.show_call)
        QShortcut(QKeySequence("Ctrl+Shift+H"), self, activated=self.toggle_hear)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=self.pick_screen_problem)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.show_profile)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=lambda: self.show_briefing(force=True))
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.make_report)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: self.input.setFocus())
        QShortcut(QKeySequence("Ctrl+H"), self, activated=self.hide_to_tray)
        QShortcut(QKeySequence("Esc"), self, activated=lambda: self.speaker.stop())

    @staticmethod
    def _wrap(bubble: Bubble, align: Qt.AlignmentFlag) -> QWidget:
        """Put a bubble in a row so it can sit left, centre or right."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        if align == Qt.AlignmentFlag.AlignRight:
            layout.addStretch(1)
            layout.addWidget(bubble)
        else:
            layout.addStretch(1)
            layout.addWidget(bubble)
            layout.addStretch(1)
        return row

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip(config.APP_NAME)

        menu = QMenu()
        show_action = QAction("Show / hide Atom", menu)
        show_action.triggered.connect(self.toggle_visible)
        self.pin_action = QAction("Always on top", menu, checkable=True)
        self.pin_action.setChecked(self._pinned)
        self.pin_action.toggled.connect(self.pin_btn.setChecked)
        quit_action = QAction("Quit Atom", menu)
        quit_action.triggered.connect(self.quit_app)
        brief_action = QAction("Today's briefing", menu)
        brief_action.triggered.connect(lambda: self.show_briefing(force=True))
        day_action = QAction("Reminders and to-dos", menu)
        day_action.triggered.connect(self.show_day)
        menu.addAction(show_action)
        menu.addAction(brief_action)
        call_action = QAction("Call helper", menu)
        call_action.triggered.connect(self.show_call)
        profile_action = QAction("My skills and files", menu)
        profile_action.triggered.connect(self.show_profile)
        menu.addAction(day_action)
        menu.addAction(call_action)
        menu.addAction(profile_action)
        menu.addAction(self.pin_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        self._tray_menu = menu  # keep a reference or Qt may delete it
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.show()

    def _holds_chat(self) -> bool:
        return bool(getattr(config, "KEEP_LAST_CHAT", True) and self._chat_held)

    def _notify(self, text: str) -> bool:
        """A pop-up from the tray icon (instead of the chat box). False if there is no tray to show it."""
        if self.tray and config.TRAY_NOTIFICATIONS:
            self.tray.showMessage(config.APP_NAME, text[:240], QSystemTrayIcon.MessageIcon.Information, 8000)
            return True
        return False

    def _speak_up(self, text: str, mood: str = "curious", notify: bool = False) -> bool:
        """Something he says on his own, not as an answer to you. While his last answer is on show it stays: the words go
        to a pop-up (notify=True) or are dropped, and only his face reacts. Returns True if the words reached you."""
        if not self._holds_chat():
            self.say(text, mood=mood)
            return True
        self.character.set_state(mood, 1500)
        return bool(notify and self._notify(text))

    def _restore_last_chat(self) -> bool:
        """Put your last question and his last answer back in the chat box (instead of a hello)."""
        history = list(getattr(self.brain, "history", []) or [])
        for index in range(len(history) - 1, -1, -1):
            if history[index]["role"] != "assistant":
                continue
            question = history[index - 1]["content"] if index and history[index - 1]["role"] == "user" else ""
            if question:
                self.user_bubble.set_text(question)
                self.user_row.show()
            self.atom_bubble.set_text(history[index]["content"])
            self._chat_held = True
            self.character.set_state("happy", 1500)
            return True
        return False

    def _welcome(self) -> None:
        if getattr(config, "KEEP_LAST_CHAT", True) and self.brain.available and self._restore_last_chat():
            return
        if config.GREETING:
            text = personality.greeting(
                datetime.now(),
                name=self.brain.user_name(),
                last_talked=self.brain.last_talked,
                files=len(self.store.all()),
            )
        else:
            text = (
                "Hi, I'm Atom! Drop files on me, then type or click the mic and talk. "
                "I can also open your files and apps, like \"open Excel\"."
            )
        if not self.brain.available:
            text += "\n\n" + self.brain.status_text
        elif config.get_provider() == "gemini":
            text += (
                "\n\nHeads up: Gemini's free tier may use chats and file excerpts to "
                "improve Google's products, so keep private files out."
            )
        self.say(text, mood="happy")

    def _move_to_corner(self) -> None:
        screen = self.screen().availableGeometry()
        self.move(
            screen.right() - self.width() - config.SCREEN_MARGIN,
            screen.bottom() - self.height() - config.SCREEN_MARGIN,
        )

    # --------------------------------------------------------------- speech
    # how long each feeling shows on his face before and after he speaks (milliseconds)
    FEELING_MS = {
        "happy": 1300, "laughing": 1600, "proud": 1400, "worried": 1500, "sad": 1500,
        "surprised": 1100, "curious": 1300, "annoyed": 1300,
    }

    def say(self, text: str, mood: str | None = "talking", spoken: bool = False, live: bool = False) -> None:
        """Show `text` in Atom's bubble and act it out: first the feeling on his face,
        then the mouth moves while he "talks", then the feeling again as he finishes.
        `spoken` = his voice reads it out loud, so the mouth moves for as long as that takes.
        `live` = he is already talking (the voice started while the answer was being written): the text stays as it is
        and his mouth keeps moving until the voice is done."""
        self.atom_bubble.set_tag("")
        if live:
            self.atom_bubble.set_text(text)
            talk_ms = max(900, self.speaker.stream_remaining_ms() + 300)
            feeling_ms = self.FEELING_MS.get(mood or "")
            self.character.set_state("talking", talk_ms, then=[(mood, feeling_ms)] if feeling_ms else None)
            return
        talk_ms = estimate_ms(text, spoken)
        # when his voice reads it, the words appear at the pace of the voice (the babble or the Windows voice)
        cps = max(8.0, min(60.0, len(text) / max(1.0, talk_ms / 1000))) if spoken else 50
        self.atom_bubble.type_text(text, cps=cps)  # types out in the HUD look
        if mood is None:
            return
        feeling_ms = self.FEELING_MS.get(mood)
        if feeling_ms is None:  # plain answer: just talk
            self.character.set_state("talking", talk_ms)
        else:
            self.character.set_state(mood, feeling_ms, then=[("talking", talk_ms), (mood, feeling_ms)])

    # --------------------------------------------------------------- files
    def _refresh_files(self) -> None:
        records = self.store.all()
        self.files_dialog.panel.refresh(records, self.store.folders())
        label = f"Files {len(records)}" if IS_HUD else f"Files ({len(records)})"
        self.files_btn.setText(label if records else "Files")

    def add_paths(self, paths: list, folder: str | None = None) -> None:
        """Read the files in the background, so a big spreadsheet doesn't freeze Atom. `folder` = which Atom folder they go in."""
        self._index_queue.append((list(paths), folder))
        if self._indexing is None:
            self._start_indexing()

    def _start_indexing(self) -> None:
        if not self._index_queue:
            return
        paths, folder = self._index_queue.pop(0)
        self.say("Reading your files... big ones take a moment. You can keep chatting.", mood=None)
        self.character.set_state("thinking")
        worker = IndexWorker(self.store, paths, folder)
        self._indexing = worker
        _RUNNING_WORKERS.append(worker)
        worker.done.connect(self._on_indexed)
        worker.finished.connect(lambda: _RUNNING_WORKERS.remove(worker))
        worker.start()

    def _on_indexed(self, added: list, problems: list) -> None:
        self._indexing = None
        self._refresh_files()
        self.suggester.scan_soon([r.name for r in added])
        if self._watcher:
            self._watcher.watch(r.path for r in added)
        self._show_added(added, problems)
        self._start_indexing()  # the next batch, if you dropped more meanwhile

    def _show_added(self, added: list, problems: list) -> None:
        if added:
            names = ", ".join(r.name for r in added[:3])
            extra = f" and {len(added) - 3} more" if len(added) > 3 else ""
            plural = "s" if len(added) != 1 else ""
            ready = sum(1 for r in added if r.status == "ready")
            empty = sum(1 for r in added if r.status == "empty")
            failed = sum(1 for r in added if r.status == "error")
            msg = f"{personality.added_opener()} Added {len(added)} file{plural}: {names}{extra}."
            if ready:
                msg += f" Indexed {ready}."
            if empty:
                msg += f" {empty} had no searchable text."
            if failed:
                msg += f" {failed} failed to extract."
            self.say(msg, mood="happy")
        elif problems:
            self.say(problems[0], mood="worried")

    def browse_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files to Atom")
        if paths:
            looking = self.files_dialog.isVisible()           # the Files window is open: they go into the folder you are looking at
            self.add_paths(paths, self.files_dialog.panel.current_folder() if looking else None)

    def move_files(self, paths: list, folder: str) -> None:
        try:
            moved = self.store.set_folder(paths, folder)
        except ValueError as problem:
            self.say(str(problem), mood="worried")
            return
        self._refresh_files()
        about = " I'll use them to answer questions about you." if folder.lower() == "about me" else ""
        self.say(f"Moved {moved} file{'s' if moved != 1 else ''} to {folder}.{about}", mood="happy")

    def create_folder(self, name: str) -> None:
        try:
            made = self.store.create_folder(name)
        except ValueError as problem:
            self.say(str(problem), mood="worried")
            return
        self._refresh_files()
        self.say(f"The folder '{made}' is ready.", mood="happy")

    def remove_files(self, paths: list) -> None:
        removed = self.store.remove(paths)
        self._refresh_files()
        if removed:
            self.say(f"Removed {removed} file{'s' if removed != 1 else ''} from my list.")

    def clear_files(self) -> None:
        self.store.clear()
        self._refresh_files()
        self.say("Cleared my file list.")

    def show_files(self) -> None:
        self.files_dialog.show()
        self.files_dialog.raise_()
        self.files_dialog.activateWindow()

    def show_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.saved.connect(self._on_settings_saved)
        dialog.quit_requested.connect(self.quit_app)
        dialog.open_call.connect(lambda: QTimer.singleShot(50, self.show_call))
        dialog.open_profile.connect(lambda: QTimer.singleShot(50, self.show_profile))
        dialog.exec()

    def _refresh_speak_button(self) -> None:
        """The speaker button works when the chosen kind of voice (babble or a Windows voice) can make sound."""
        ok = self.speaker.available
        self.speak_btn.setEnabled(ok)
        self.speak_btn.setToolTip(
            "Atom reads his answers aloud" if ok
            else "No voice available for this setting, so Atom can't speak (see Settings > Atom's voice)"
        )

    def _on_settings_saved(self) -> None:
        self._refresh_speak_button()
        self.brain.reset_client()
        if self.brain.available:
            self.say("Saved! My AI brain is switched on.", mood="happy")
        else:
            self.say("Saved. " + self.brain.status_text)

    # ------------------------------------------------------- drag and drop
    def _set_dragging(self, on: bool) -> None:
        self.central.setProperty("dragging", on)
        self.central.style().unpolish(self.central)
        self.central.style().polish(self.central)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_dragging(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_dragging(False)

    def dropEvent(self, event) -> None:
        self._set_dragging(False)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.add_paths(paths)

    # ---------------------------------------------------- moving the window
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None

    # ---------------------------------------------------------------- chat
    def send(self) -> None:
        text = self.input.text().strip()
        if not text or self._busy():
            return
        self.input.clear()
        self._submit(text)

    def make_report(self) -> None:
        """The Report button: same as typing the request yourself."""
        if self._busy():
            return
        if len(self.store) == 0:
            self.say("Drop some files on me first, then I can write a report about them.")
            return
        self._submit("Make a status report from all my files and save it as a document.")

    def _busy(self) -> bool:
        return (
            self._worker is not None
            or self._voice_worker is not None
            or self.recorder.active
        )

    def _submit(self, text: str, spoken: bool = False, shown: str | None = None) -> None:
        """Show `text` (or `shown`, a shorter stand-in) as your bubble and ask the brain (typed or spoken)."""
        self.speaker.stop()  # a new question: stop reading the old answer
        self._via_voice = spoken
        # with a voice that can start early, he talks sentence by sentence while the answer is still being written
        wants_voice = self.speaker.available and (
            self.speak_btn.isChecked() or (spoken and config.SPEAK_AFTER_VOICE)
        )
        self._reveal_timer.stop()
        self._reset_reveal()
        self._streaming_voice = bool(wants_voice and self.speaker.can_stream()
                                     and self.speaker.begin_stream(self.chunk_started.emit))
        self._last_activity = time.monotonic()
        self.user_bubble.set_text(shown or text)
        self.user_row.show()
        self.atom_bubble.set_text(personality.thinking_line())
        self.character.set_state("thinking")
        self._worker = ReplyWorker(self.brain, text)
        self._worker.partial.connect(self._on_partial)
        self._worker.status.connect(self._on_status)
        self._worker.confirm_requested.connect(self._on_confirm)
        self._worker.done.connect(self._on_reply)
        self._worker.start()

    def _on_status(self, text: str) -> None:
        """Atom is using a tool (searching, opening...): say so in his bubble."""
        self.atom_bubble.set_text(text)
        self.atom_bubble.set_tag(text)   # plate look: shown after /// ATOM
        self.character.set_state("thinking")

    def _on_confirm(self, question: str) -> None:
        """Atom wants to open a file or an app. Nothing happens unless you click Yes."""
        box = QMessageBox(self)
        box.setWindowTitle("Atom asks")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(question)
        box.setInformativeText("Atom only does this when you say yes.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        yes = box.exec() == QMessageBox.StandardButton.Yes
        if self._worker is not None:
            self._worker.answer(yes)

    def _on_partial(self, text: str) -> None:
        """Words are arriving. With a voice that talks along, the words are shown as he says them (see _reveal_tick)
        and the finished sentences are handed to the voice; otherwise they appear right away."""
        if self._streaming_voice:
            self._reveal_raw = text
            self.speaker.feed(text)
            return
        self.atom_bubble.set_text(text, follow=True)   # a long answer keeps its newest words in view
        self.character.set_state("talking")

    def _on_reply(self, answer: str) -> None:
        worker, self._worker = self._worker, None
        if worker:
            worker.wait()
        self._last_activity = time.monotonic()
        self._chat_held = True                      # this answer now stays until you ask something else
        self._refresh_files()                       # he may have filed or moved files while answering
        speak = self.speaker.available and (
            self.speak_btn.isChecked() or (self._via_voice and config.SPEAK_AFTER_VOICE)
        )
        mood = personality.mood_for(answer)
        if self._streaming_voice and self.speaker.streaming:
            self.speaker.end_stream(answer)    # say whatever is left
            self.atom_bubble.set_tag("")
            self._reveal_raw, self._reveal_mood = answer, mood
            self._reveal_done, self._reveal_done_at = True, time.monotonic()
            if not self._reveal_timer.isActive():
                self._reveal_timer.start(40)
        else:
            self.say(answer, mood=mood, spoken=bool(speak))  # a face that fits the answer
            if speak:
                self.speaker.say(answer)
            self._streaming_voice = False
        self._via_voice = False
        self.raise_()  # an app Atom just opened may have covered him
        self.input.setFocus()

    # ------------------------------------------- words in step with his voice
    def _reset_reveal(self) -> None:
        self._reveal_raw = ""         # the answer as far as it has arrived
        self._reveal_mood: str | None = None
        self._reveal_done = False     # the whole answer has arrived
        self._reveal_done_at = 0.0
        self._reveal_said = 0         # characters of speech that came before the sentence being said now
        self._reveal_chars = 0        # characters in the sentence being said now
        self._reveal_t0 = 0.0         # when that sentence started
        self._reveal_secs = 1.0       # how long it takes
        self._reveal_started = False
        self._reveal_shown = -1

    def _on_chunk(self, text: str, seconds: float) -> None:
        """The voice has just started a sentence: from now on its words are shown at the pace he says them."""
        if not self._streaming_voice:
            return
        now = time.monotonic()
        if self._reveal_started:
            self._reveal_said += self._reveal_chars
        self._reveal_chars, self._reveal_secs, self._reveal_t0 = len(text) + 1, max(0.3, seconds), now
        self._reveal_started = True
        self.character.set_state("talking", int(seconds * 1000) + 500)
        if not self._reveal_timer.isActive():
            self._reveal_timer.start(40)

    def _finish_reveal(self) -> None:
        self._reveal_timer.stop()
        answer = self._reveal_raw
        if answer:
            self.atom_bubble.set_text(answer)
        mood = self._reveal_mood
        feeling_ms = self.FEELING_MS.get(mood or "")
        if feeling_ms:
            self.character.set_state(mood, feeling_ms)
        self._streaming_voice = False
        self._reset_reveal()

    def _reveal_tick(self) -> None:
        now = time.monotonic()
        if not self.speaker.streaming:                 # he was stopped (a new question, the mic...): show it all
            self._finish_reveal()
            return
        if self._reveal_done:
            quiet = self.speaker.stream_remaining_ms() == 0 and now >= self._reveal_t0 + self._reveal_secs
            if (self._reveal_started and quiet) or (not self._reveal_started and (
                    self.speaker.stream_remaining_ms() == 0 or now - self._reveal_done_at > 15)):
                self._finish_reveal()                  # he finished (or the voice never started): show everything
                return
        if not self._reveal_started or not self._reveal_raw:
            return
        said = self._reveal_said + self._reveal_chars * min(1.0, (now - self._reveal_t0) / self._reveal_secs)
        total = max(len(speakable(self._reveal_raw, 10**6)) + 1, self._reveal_said + self._reveal_chars, 1)
        shown = int(len(self._reveal_raw) * min(1.0, said / total))
        space = self._reveal_raw.find(" ", shown)      # never cut a word in half
        shown = len(self._reveal_raw) if space < 0 or (self._reveal_done and said >= total - 1) else space
        if shown != self._reveal_shown:
            self._reveal_shown = shown
            self.atom_bubble.set_text(self._reveal_raw[:shown], follow=True)

    # ----------------------------------------------------------- hotkey
    def _start_hotkey(self) -> None:
        """A key combination that calls Atom from any program (Windows)."""
        self._hotkey: GlobalHotkey | None = None
        combo = config.load_settings().get("hotkey") or config.HOTKEY
        if not combo or not startup.supported():
            return
        hotkey = GlobalHotkey(self.summon)
        if hotkey.register(combo):
            self._hotkey = hotkey
        else:
            QTimer.singleShot(
                3000,
                lambda: self.say(
                    f"I couldn't claim {combo.upper()} because another program uses it. "
                    "Change HOTKEY in config.py if you want it."
                ),
            )

    def summon(self, listen: bool = True) -> None:
        """The hotkey (or a second launch of Atom): bring him to the front.
        Press the hotkey again while he is in front to start or stop listening."""
        in_front = self.isVisible() and not self.isMinimized() and self.isActiveWindow()
        self.show_atom()
        self._wake()
        self.input.setFocus()
        if not listen:
            return
        if in_front or config.HOTKEY_LISTENS:
            self.toggle_mic()

    # ------------------------------------------------------ idle behavior
    def _start_idle_life(self) -> None:
        """When you're away Atom glances around, says something now and then,
        and finally falls asleep. Anything you do wakes him."""
        if not config.IDLE_BEHAVIOR:
            return
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._idle_tick)
        self._idle_timer.start(5000)

    def _idle_tick(self) -> None:
        if self._busy() or self._indexing is not None or not self.isVisible():
            return
        now = time.monotonic()
        idle = now - self._last_activity
        state = self.character.state
        if config.IDLE_SLEEP_SECONDS and idle >= config.IDLE_SLEEP_SECONDS:
            if state in ("idle", "looking"):
                self.character.set_state("sleepy")
            return
        if state != "idle":
            return  # busy being happy, worried, asleep...
        if (
            config.IDLE_CHATTER
            and idle >= config.IDLE_CHATTER_SECONDS
            and now - self._last_remark_at >= config.IDLE_CHATTER_SECONDS
        ):
            self._last_remark_at = now
            self._last_remark_text = personality.idle_remark(self._last_remark_text)
            self._speak_up(self._last_remark_text, mood="curious")      # words only if no answer is on show
        elif idle >= config.IDLE_LOOK_SECONDS and random.random() < 0.3:
            self.character.set_state("looking", 2600)

    def _wake(self) -> None:
        """You did something: he is not idle any more (and wakes up if he was asleep)."""
        self._last_activity = time.monotonic()
        if self.character.state == "sleepy":
            self._speak_up(personality.wake_line(), mood="happy")

    def enterEvent(self, event) -> None:
        self._wake()
        super().enterEvent(event)

    # -------------------------------------------------------- suggestions
    def _start_suggestions(self) -> None:
        """Every couple of minutes Atom checks for changed files and overdue work."""
        if not config.SUGGESTIONS:
            return
        self._suggest_timer = QTimer(self)
        self._suggest_timer.timeout.connect(self._check_suggestions)
        self._suggest_timer.start(config.SUGGESTION_EVERY_SECONDS * 1000)
        QTimer.singleShot(6000, self._check_suggestions)  # and once shortly after he starts
        self._start_watcher()

    def _start_watcher(self) -> None:
        """Listen to the folders your files live in, so a saved file is noticed in seconds."""
        if not config.WATCH_FILES:
            return
        watcher = FileWatcher(lambda path: self.file_changed.emit(), config.WATCH_DELAY_SECONDS)
        if not watcher.start():
            return  # watchdog isn't installed: the timer above still checks every couple of minutes
        self._watcher = watcher
        self.file_changed.connect(self._on_file_changed)
        watcher.watch(record.path for record in self.store.all())

    def _on_file_changed(self) -> None:
        if self._suggest_worker is not None or self._indexing is not None:
            QTimer.singleShot(5000, self._on_file_changed)  # busy right now: try again shortly
            return
        self._check_suggestions()

    def _check_suggestions(self) -> None:
        if self._suggest_worker is not None or self._indexing is not None:
            return
        worker = SuggestWorker(self.suggester)
        self._suggest_worker = worker
        worker.done.connect(self._on_suggestion)
        worker.start()

    def _on_suggestion(self, message: str) -> None:
        worker, self._suggest_worker = self._suggest_worker, None
        if worker:
            worker.wait()
        if not message:
            return
        self._refresh_files()  # a changed file was read again
        quiet = time.monotonic() - self._last_activity >= config.SUGGESTION_IDLE_SECONDS
        if self._busy() or self._indexing is not None or not quiet:
            return  # not now: he will offer it again at the next check
        if not self._speak_up(message, mood="curious", notify=True):
            return                                  # his last answer is on show and no pop-up is possible: offered again later
        self.suggester.acknowledge()
        # hidden in the tray? then a pop-up notification, so you still hear about it
        if (self.tray and config.TRAY_NOTIFICATIONS and not self._holds_chat()
                and (not self.isVisible() or self.isMinimized())):
            self.tray.showMessage(config.APP_NAME, message[:240], QSystemTrayIcon.MessageIcon.Information, 8000)

    # ------------------------------------------------------- daily helper
    def _start_daily(self) -> None:
        """Reminders ring on time, and once a day he gives a short briefing."""
        if not getattr(config, "DAILY", True) or getattr(self.brain, "daily", None) is None:
            return
        self._reminder_timer = QTimer(self)
        self._reminder_timer.timeout.connect(self._check_reminders)
        self._reminder_timer.start(max(5, int(getattr(config, "REMINDER_CHECK_SECONDS", 15))) * 1000)
        QTimer.singleShot(3000, self._check_reminders)       # ones that came due while Atom was closed
        if getattr(config, "MORNING_BRIEFING", True):
            QTimer.singleShot(14000, self.show_briefing)

    def _tell_hidden(self, message: str) -> None:
        """If Atom is tucked away in the tray, a pop-up makes sure you still hear it."""
        if self.tray and config.TRAY_NOTIFICATIONS and (not self.isVisible() or self.isMinimized()):
            self.tray.showMessage(config.APP_NAME, message[:240], QSystemTrayIcon.MessageIcon.Information, 10000)

    def _check_reminders(self) -> None:
        book = getattr(self.brain, "daily", None)
        if book is None or self._busy() or self._indexing is not None:
            return                                           # not now: the next check (seconds later) tries again
        try:
            due = book.due()
        except Exception as error:
            atomlog.exception("reminders", error)
            return
        if not due:
            return
        now = datetime.now()
        item = due[0]                                        # one at a time; the next check shows the next one
        late_minutes = (now - item.due).total_seconds() / 60
        text = f"Reminder: {item.text}"
        if late_minutes >= 10:
            text = f"Reminder (it was for {timeparse.nice(item.due, now)}): {item.text}"
        book.fire(item.id, now)
        atomlog.log(f"reminder shown: #{item.id} {item.text}")
        spoken = self.speak_btn.isChecked() and self.speaker.available
        shown = text if item.repeat else text + "\n(Say \"snooze 10 minutes\" and I'll remind you again.)"
        self.say(shown, mood="curious", spoken=spoken)
        if spoken:
            self.speaker.say(text)
        self._tell_hidden(text)
        day = getattr(self, "_day_dialog", None)
        if day is not None and day.isVisible():
            day.refresh()

    def show_day(self) -> None:
        """The reminders and to-do list window."""
        book = getattr(self.brain, "daily", None)
        if book is None:
            self.say("Reminders and the to-do list are turned off (DAILY in config.py).", mood="curious")
            return
        if getattr(self, "_day_dialog", None) is None:
            self._day_dialog = DayDialog(self, book)
        self._day_dialog.refresh()
        self._day_dialog.show()
        self._day_dialog.raise_()
        self._day_dialog.activateWindow()

    # ----------------------------------------------------------- Step 13: calls, screen, skills
    def show_profile(self) -> None:
        """The window where you list your skills and point Atom at the files about you."""
        book = getattr(self.brain, "profile", None)
        if book is None:
            self.say("The skills profile is turned off (PROFILE in config.py).", mood="curious")
            return
        if self._profile_dialog is None:
            self._profile_dialog = callpanel.ProfileDialog(self, book)
            self._profile_dialog.changed.connect(self._refresh_files)
        self._profile_dialog.refresh()
        self._profile_dialog.show()
        self._profile_dialog.raise_()
        self._profile_dialog.activateWindow()

    def _call_engine(self):
        """The call window and the engine behind it, made the first time they are needed."""
        if self._call_ctl is not None:
            return self._call_ctl
        import callmode
        brain = self.brain
        ctl = callmode.CallController(
            brain.calls, brain.profile,
            ask=lambda system, user: brain.ask_once(system, user),   # looked up at the moment of use: a key added later works
            screen=self._screen_words,
            who=lambda: brain.user_name() or "",
        )
        ctl.auto_answer = bool(config.CALL_AUTO_ANSWER)
        panel = callpanel.CallPanel(self)
        panel.attach(ctl)
        panel.start_requested.connect(self.start_call)
        panel.stop_requested.connect(self.stop_call)
        panel.screen_requested.connect(self._call_read_screen)
        panel.question_typed.connect(ctl.ask_now)
        panel.auto_changed.connect(lambda on: setattr(ctl, "auto_answer", bool(on)))
        panel.problem.connect(self._on_call_problem)
        panel.summary_ready.connect(self._on_call_summary)
        self._call_ctl, self._call_panel = ctl, panel
        return ctl

    def show_call(self) -> None:
        if getattr(self.brain, "calls", None) is None or getattr(self.brain, "profile", None) is None:
            self.say("The call helper is turned off (CALL_HELPER and PROFILE in config.py).", mood="curious")
            return
        self._call_engine()
        panel = self._call_panel
        panel.show()
        panel.raise_()
        panel.activateWindow()
        if self.brain.profile.is_empty():
            panel.problem.emit("Your skills list is empty, so I can't answer questions about you yet. "
                               "Press Ctrl+P and add your skills or a CV file first.")

    def start_call(self) -> None:
        ctl = self._call_engine()
        if ctl.active:
            return
        import loopback
        self.speaker.stop()
        self.speaker.muted = True                 # he must never talk into your call
        self._call_panel.begin_call()
        ctl.auto_answer = self._call_panel.auto.isChecked()
        try:
            ctl.start(lambda c: loopback.make_listeners(c), title=datetime.now().strftime("Call %d %b, %H:%M"))
        except Exception as error:
            self.speaker.muted = False
            atomlog.exception("call start", error)
            self._call_panel.problem.emit(f"I couldn't start listening: {error}")
            self._sync_hear_button()
            return
        atomlog.log("call helper: listening started")
        self._call_panel.set_running(True)
        self._sync_hear_button()
        self.say("I'm listening to your call and I'll stay quiet. Look at the Call helper window.", mood="curious", spoken=False)

    def stop_call(self) -> None:
        ctl = self._call_ctl
        if ctl is None or not ctl.active:
            return
        ctl.stop()
        self._call_panel.set_running(False)
        self._call_panel.status_changed.emit("Saving the call and writing the summary...")
        self.speaker.muted = False
        self._sync_hear_button()
        atomlog.log("call helper: listening stopped")

    def _on_call_problem(self, text: str) -> None:
        """If the audio could not be opened at all, don't pretend to be listening."""
        ctl = self._call_ctl
        if ctl is None or not ctl.active:
            return
        def check() -> None:
            if ctl.active and ctl.listeners and not any(l.is_alive() for l in ctl.listeners):
                self.stop_call()
        QTimer.singleShot(400, check)

    def _on_call_summary(self, text: str) -> None:
        atomlog.log("call helper: call saved")
        self.say("The call is saved. Ask me \"what did they ask me to do?\" any time.", mood="happy", spoken=False)

    def toggle_hear(self) -> None:
        """The Hear button: start or stop listening to the call."""
        if getattr(self.brain, "calls", None) is None or getattr(self.brain, "profile", None) is None:
            self.show_call()                                  # says that the call helper is turned off
            self._sync_hear_button()
            return
        ctl = self._call_ctl
        if ctl is not None and ctl.active:
            self.stop_call()
        else:
            self.show_call()
            self.start_call()
        self._sync_hear_button()

    def _sync_hear_button(self) -> None:
        button = getattr(self, "hear_btn", None)
        if button is not None:
            button.setChecked(bool(self._call_ctl is not None and self._call_ctl.active))

    def _call_read_screen(self) -> None:
        self.pick_screen_problem()

    # the Screen button: a frozen picture, you drag a box around the one problem, only that is read
    def pick_screen_problem(self) -> None:
        if self._picker is not None:
            return
        self._hide_for_screen()                               # Atom's own windows out of the picture
        QTimer.singleShot(250, self._open_picker)

    def _open_picker(self) -> None:
        try:
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            shot = screen.grabWindow(0)
            picker = RegionPicker(shot, screen.geometry())
        except Exception as error:
            atomlog.exception("screen picker", error)
            self._show_after_screen()
            self.say(f"I couldn't take a picture of the screen: {error}", mood="worried")
            return
        picker.picked.connect(self._region_picked)
        self._picker = picker
        picker.show()
        picker.raise_()
        picker.activateWindow()
        picker.setFocus()

    def _region_picked(self, image) -> None:
        self._picker = None
        self._show_after_screen()
        if image is None:
            return
        try:
            picture = qimage_to_pil(image)
        except Exception as error:
            self.say(f"I couldn't use that picture ({error}). Is Pillow installed? Run: python -m pip install Pillow", mood="worried")
            return
        if self._call_panel is not None and self._call_panel.isVisible():
            self._call_panel.status_changed.emit("Reading the part of the screen you picked...")
        else:
            self.say("Reading the part you picked...", mood="curious")

        def work() -> None:
            import screenreader
            result = screenreader.read_screen(image=picture)
            self.picked_text.emit(result.text if result.ok else "", "" if result.ok else result.error)

        threading.Thread(target=work, daemon=True).start()          # reading the picture takes a moment

    def _on_picked_text(self, text: str, problem: str) -> None:
        panel = self._call_panel
        use_panel = panel is not None and panel.isVisible()
        if problem or not text:
            if use_panel:
                panel.problem.emit(problem or "I found no readable text in that box.")
            else:
                self.say(problem or "I found no readable text in that box.", mood="worried")
            return
        if use_panel:
            self._call_engine().ask_screen(text)
            return
        if self._busy():
            self.say("I'm still busy with your last message. Pick the problem again in a moment.")
            return
        self._submit(
            "Help me with this problem from my screen. Focus only on it and ignore menus, tabs and ads. "
            "Give the simplest correct answer.\n\n" + text,
            shown="(the problem you picked on the screen)",
        )

    # reading the screen (runs on a background thread; Atom's own windows are made invisible for the picture)
    def read_screen_now(self):
        import screenreader
        return screenreader.read_screen(before=self.screen_hide.emit, after=self.screen_show.emit)

    def _screen_words(self) -> str:
        result = self.read_screen_now()
        if not result.ok:
            if self._call_panel is not None:
                self._call_panel.problem.emit(result.error)
            return ""
        return result.text

    def _hide_for_screen(self) -> None:
        self._screen_hidden = [w for w in (self, self._call_panel, self._profile_dialog) if w is not None and w.isVisible()]
        for w in self._screen_hidden:
            w.setWindowOpacity(0.0)
        QApplication.processEvents()

    def _show_after_screen(self) -> None:
        for w in self._screen_hidden:
            w.setWindowOpacity(1.0)
        self._screen_hidden = []

    def show_briefing(self, force: bool = False) -> None:
        """Once a day (or whenever you ask from the tray menu): reminders, to-do list, overdue work."""
        book = getattr(self.brain, "daily", None)
        if book is None:
            return
        settings = config.load_settings()
        today = date.today().isoformat()
        if not force:
            if settings.get("last_briefing") == today or datetime.now().hour < int(getattr(config, "BRIEFING_FROM_HOUR", 5)):
                return
            if self._busy():
                QTimer.singleShot(10000, self.show_briefing)
                return
        try:
            text = book.briefing(extra=self.suggester.overview_lines())
        except Exception as error:
            atomlog.exception("briefing", error)
            return
        if not force:
            settings["last_briefing"] = today
            config.save_settings(settings)
        if not force and self._holds_chat() and self._notify("Your briefing for today is ready. Press Ctrl+B to read it."):
            return                                  # his last answer stays on show; Ctrl+B opens the briefing when you want it
        spoken = self.speak_btn.isChecked() and self.speaker.available
        self.say(text, mood="happy", spoken=spoken)
        if spoken:
            self.speaker.say(text)
        self._tell_hidden(text)
        if force:
            self.show_atom()

    # --------------------------------------------------------------- voice
    def toggle_mic(self) -> None:
        """Click once to start talking; click again to stop early."""
        if self.recorder.active:
            self.recorder.stop()
        elif self._busy():
            self.say("I'm still busy with your last message. Give me a moment, then tap the mic again.")
        elif self.recorder.start():
            self.speaker.stop()  # so his own voice isn't recorded
            self.user_bubble.set_text("Listening...")
            self.user_row.show()
            self.atom_bubble.set_text("I'm listening. Go ahead!")
            self.character.set_state("listening")
        self.mic_btn.setChecked(self.recorder.active)

    def _on_recorded(self, raw, rate, channels, fmt, heard) -> None:
        self.mic_btn.setChecked(False)
        if not heard or not raw:
            self._voice_problem(
                "I didn't hear anything. Check that your mic isn't muted and that "
                "Windows lets desktop apps use it (Settings > Privacy & security > Microphone)."
            )
            return
        self.user_bubble.set_text("...")
        self.atom_bubble.set_text("Let me work out what you said...")
        self.character.set_state("thinking")
        names = [Path(r.name).stem for r in self.store.all()[:12]]
        self._voice_worker = TranscribeWorker(raw, rate, channels, fmt, hint=", ".join(names))
        self._voice_worker.done.connect(self._on_transcribed)
        self._voice_worker.start()

    def _on_transcribed(self, text: str, error: str) -> None:
        worker, self._voice_worker = self._voice_worker, None
        if worker:
            worker.wait()
        if error:
            self._voice_problem(error)
        elif not text:
            self._voice_problem("Sorry, I didn't catch that. Could you say it again?")
        else:
            self._submit(text, spoken=True)  # your words appear in your bubble, then Atom answers

    def _on_speak_toggled(self, on: bool) -> None:
        settings = config.load_settings()
        settings["speak_replies"] = bool(on)
        config.save_settings(settings)
        if not on:
            self.speaker.stop()

    def _on_voice_failed(self, message: str) -> None:
        self.mic_btn.setChecked(False)
        self._voice_problem(message)

    def _voice_problem(self, message: str) -> None:
        self.user_row.hide()
        self.character.set_state("idle")
        self.say(message)

    # ------------------------------------------------------ always on top
    def set_pinned(self, on: bool) -> None:
        self._pinned = on
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        if was_visible:
            self.show()  # changing window flags hides the window; bring it back
        if self.tray:
            self.pin_action.blockSignals(True)
            self.pin_action.setChecked(on)
            self.pin_action.blockSignals(False)

    # ------------------------------------------------------ tray / closing
    def show_atom(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def toggle_visible(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.show_atom()

    def hide_to_tray(self) -> None:
        if self.tray:
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(
                    config.APP_NAME,
                    "Atom is still running. Click the tray icon to bring him back.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
        else:
            self.showMinimized()

    def _tray_clicked(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visible()

    def quit_app(self) -> None:
        self._quitting = True
        self.recorder.stop(send=False)
        if self._call_ctl is not None and self._call_ctl.active:
            self._call_ctl.stop()
        if self._voice_worker is not None:
            self._voice_worker.wait(3000)
        if self._worker is not None:
            self._worker.wait(3000)
        for background in (self._indexing, self._suggest_worker):
            if background is not None:
                background.wait(3000)
        self.speaker.stop()
        if self._hotkey:
            self._hotkey.unregister()
        if self._watcher:
            self._watcher.stop()
        if self.tray:
            self.tray.hide()
        self.close()
        QApplication.quit()

    def closeEvent(self, event) -> None:
        # With a tray icon, closing hides Atom instead of quitting him.
        if self.tray and not self._quitting:
            event.ignore()
            self.hide_to_tray()
        else:
            event.accept()