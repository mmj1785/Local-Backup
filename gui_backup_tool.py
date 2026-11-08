"""
BackupTool – واجهة رسومية PyQt6  v3.0  (Modern Redesign)
Developed by: Mohammed Eydan
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QPropertyAnimation,
    QEasingCurve, QRect, QPoint, QSize,
)
from PyQt6.QtGui import (
    QColor, QFont, QIcon, QPainter, QPen, QBrush,
    QLinearGradient, QRadialGradient, QPixmap, QPainterPath,
    QFontMetrics,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame,
    QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
    QLabel, QLineEdit, QPushButton, QCheckBox,
    QTreeWidget, QTreeWidgetItem, QProgressBar,
    QGroupBox, QFileDialog, QMessageBox, QDialog,
    QListWidget, QListWidgetItem, QDialogButtonBox,
    QSizePolicy, QScrollArea, QGraphicsDropShadowEffect,
    QHeaderView,
)

import yaml
import backup_tool as core

# ─────────────────────────────────────────────────────────────────────────────
# Design Tokens
# ─────────────────────────────────────────────────────────────────────────────
C = {
    "bg":           "#080D1A",   # خلفية رئيسية
    "sidebar":      "#0D1225",   # الشريط الجانبي
    "card":         "#111827",   # البطاقات
    "card2":        "#1A2235",   # بطاقات أفتح قليلاً
    "border":       "#1F2937",   # حدود البطاقات
    "border_lit":   "#2D3F5E",   # حدود مضاءة
    "accent":       "#3B82F6",   # أزرق كهربائي
    "accent2":      "#60A5FA",   # أزرق فاتح
    "accent_glow":  "#1D4ED8",   # توهج
    "success":      "#10B981",   # أخضر
    "success_bg":   "#064E3B",
    "danger":       "#EF4444",   # أحمر
    "danger_bg":    "#450A0A",
    "warn":         "#F59E0B",   # برتقالي
    "warn_bg":      "#451A03",
    "text":         "#F9FAFB",   # نص رئيسي
    "text2":        "#9CA3AF",   # نص ثانوي
    "text3":        "#4B5563",   # نص خافت
    "input_bg":     "#0F172A",   # خلفية الإدخال
}

GLOBAL_SS = f"""
* {{
    font-family: "Segoe UI", "Tahoma", sans-serif;
    font-size: 10pt;
    color: {C['text']};
}}
QWidget {{ background: transparent; }}
QMainWindow, QDialog {{ background-color: {C['bg']}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    background: {C['card']}; width: 6px; border-radius: 3px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C['border_lit']}; border-radius: 3px; min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {C['card']}; height: 6px; border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {C['border_lit']}; border-radius: 3px; min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QToolTip {{
    background: {C['card2']}; color: {C['text']};
    border: 1px solid {C['border_lit']}; border-radius: 6px; padding: 5px 10px;
}}
"""

# ─────────────────────────────────────────────────────────────────────────────
# Reusable styled widgets
# ─────────────────────────────────────────────────────────────────────────────

def shadow(widget: QWidget, radius=20, color="#000000", offset=(0, 4)):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(radius)
    eff.setColor(QColor(color))
    eff.setOffset(*offset)
    widget.setGraphicsEffect(eff)
    return eff


class Card(QFrame):
    """بطاقة بخلفية داكنة وحافة مضيئة"""
    def __init__(self, parent=None, accent_top=False):
        super().__init__(parent)
        self._accent_top = accent_top
        self.setStyleSheet(f"""
            Card {{
                background-color: {C['card']};
                border: 1px solid {C['border']};
                border-radius: 12px;
            }}
        """)
        shadow(self, radius=24, color="#000000", offset=(0, 6))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._accent_top:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            grad = QLinearGradient(0, 0, self.width(), 0)
            grad.setColorAt(0, QColor(C['accent']))
            grad.setColorAt(1, QColor(C['accent2']))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(0, 0, self.width(), 3, 1, 1)


class ModernInput(QLineEdit):
    def __init__(self, placeholder="", password=False, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        if password:
            self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setMinimumHeight(38)
        self.setStyleSheet(f"""
            ModernInput {{
                background-color: {C['input_bg']};
                border: 1px solid {C['border']};
                border-radius: 8px;
                padding: 0 12px;
                color: {C['text']};
                selection-background-color: {C['accent']};
            }}
            ModernInput:focus {{
                border: 1.5px solid {C['accent']};
                background-color: #0C1526;
            }}
            ModernInput:read-only {{
                color: {C['text2']};
            }}
        """)


class ModernButton(QPushButton):
    """زر رئيسي متدرج"""
    def __init__(self, text="", icon_char="", variant="primary", parent=None):
        super().__init__(parent)
        lbl = f"{icon_char}  {text}" if icon_char else text
        self.setText(lbl)
        self.setMinimumHeight(38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if variant == "primary":
            ss = f"""
                ModernButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 {C['accent']}, stop:1 {C['accent2']});
                    border: none; border-radius: 9px;
                    color: white; font-weight: 700; padding: 0 20px;
                }}
                ModernButton:hover {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 {C['accent2']}, stop:1 #93C5FD);
                }}
                ModernButton:pressed {{
                    background: {C['accent_glow']};
                }}
                ModernButton:disabled {{
                    background: {C['border']}; color: {C['text3']};
                }}
            """
        elif variant == "success":
            ss = f"""
                ModernButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 #059669, stop:1 {C['success']});
                    border: none; border-radius: 9px;
                    color: white; font-weight: 700; padding: 0 20px;
                }}
                ModernButton:hover {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 {C['success']}, stop:1 #34D399);
                }}
                ModernButton:pressed {{ background: #047857; }}
                ModernButton:disabled {{ background: {C['border']}; color: {C['text3']}; }}
            """
        elif variant == "danger":
            ss = f"""
                ModernButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 #DC2626, stop:1 {C['danger']});
                    border: none; border-radius: 9px;
                    color: white; font-weight: 700; padding: 0 20px;
                }}
                ModernButton:hover {{ background: #EF4444; }}
                ModernButton:pressed {{ background: #B91C1C; }}
            """
        elif variant == "ghost":
            ss = f"""
                ModernButton {{
                    background: transparent;
                    border: 1.5px solid {C['border_lit']};
                    border-radius: 9px;
                    color: {C['text2']}; font-weight: 600; padding: 0 16px;
                }}
                ModernButton:hover {{
                    border-color: {C['accent']};
                    color: {C['accent2']};
                    background: rgba(59,130,246,0.08);
                }}
                ModernButton:pressed {{ background: rgba(59,130,246,0.15); }}
            """
        elif variant == "icon":
            ss = f"""
                ModernButton {{
                    background: {C['card2']};
                    border: 1px solid {C['border']};
                    border-radius: 8px;
                    color: {C['accent2']}; font-size: 9pt;
                    padding: 0 10px;
                }}
                ModernButton:hover {{
                    background: rgba(59,130,246,0.15);
                    border-color: {C['accent']};
                }}
            """
        else:
            ss = ""

        self.setStyleSheet(ss)


class SectionLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            color: {C['text2']};
            font-size: 8.5pt;
            font-weight: 700;
            letter-spacing: 1.5px;
            text-transform: uppercase;
            padding: 4px 0;
        """)


class DividerLine(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background-color: {C['border']}; border: none;")


class StatusBadge(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"""
            background: {C['card2']};
            border: 1px solid {C['border']};
            border-radius: 14px;
            padding: 0 14px;
            font-size: 9pt;
            font-weight: 600;
            color: {C['text2']};
        """)
        self.setText("● غير متصل")

    def set_ok(self, msg):
        self.setText(f"✔  {msg}")
        self.setStyleSheet(f"""
            background: {C['success_bg']};
            border: 1px solid {C['success']};
            border-radius: 14px; padding: 0 14px;
            font-size: 9pt; font-weight: 600; color: {C['success']};
        """)

    def set_error(self, msg="غير متصل"):
        self.setText(f"✘  {msg}")
        self.setStyleSheet(f"""
            background: {C['danger_bg']};
            border: 1px solid {C['danger']};
            border-radius: 14px; padding: 0 14px;
            font-size: 9pt; font-weight: 600; color: {C['danger']};
        """)

    def set_warn(self, msg):
        self.setText(f"⟳  {msg}")
        self.setStyleSheet(f"""
            background: {C['warn_bg']};
            border: 1px solid {C['warn']};
            border-radius: 14px; padding: 0 14px;
            font-size: 9pt; font-weight: 600; color: {C['warn']};
        """)


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar Nav Button
# ─────────────────────────────────────────────────────────────────────────────
class NavButton(QPushButton):
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._icon = icon
        self._label = label
        self.setStyleSheet(self._ss(False))
        self.toggled.connect(lambda c: self.setStyleSheet(self._ss(c)))

    def _ss(self, checked: bool) -> str:
        if checked:
            return f"""
                NavButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 rgba(59,130,246,0.22), stop:1 rgba(59,130,246,0.04));
                    border: none;
                    border-right: 3px solid {C['accent']};
                    border-radius: 0;
                    color: {C['accent2']};
                }}
            """
        return f"""
            NavButton {{
                background: transparent;
                border: none;
                border-right: 3px solid transparent;
                border-radius: 0;
                color: {C['text3']};
            }}
            NavButton:hover {{
                background: rgba(255,255,255,0.04);
                color: {C['text2']};
            }}
        """

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # background via stylesheet
        super().paintEvent(event)

        # draw icon + label centered
        painter.setPen(QColor(C['accent2'] if self.isChecked() else C['text3']))
        icon_font = QFont("Segoe UI Emoji", 17)
        painter.setFont(icon_font)
        icon_rect = QRect(0, 8, self.width(), 28)
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, self._icon)

        lbl_font = QFont("Segoe UI", 8, QFont.Weight.Bold if self.isChecked() else QFont.Weight.Normal)
        painter.setFont(lbl_font)
        lbl_rect = QRect(0, 38, self.width(), 20)
        painter.drawText(lbl_rect, Qt.AlignmentFlag.AlignCenter, self._label)

    def sizeHint(self):
        return QSize(80, 64)


# ─────────────────────────────────────────────────────────────────────────────
# Modern tree widget
# ─────────────────────────────────────────────────────────────────────────────
TREE_SS = f"""
    QTreeWidget {{
        background: {C['input_bg']};
        border: 1px solid {C['border']};
        border-radius: 10px;
        alternate-background-color: rgba(255,255,255,0.02);
        outline: 0;
        padding: 4px;
    }}
    QTreeWidget::item {{
        padding: 8px 6px;
        border-radius: 6px;
        margin: 1px 4px;
    }}
    QTreeWidget::item:selected {{
        background: rgba(59,130,246,0.25);
        color: {C['accent2']};
    }}
    QTreeWidget::item:hover:!selected {{
        background: rgba(255,255,255,0.04);
    }}
    QHeaderView {{
        border: none;
        border-radius: 0;
    }}
    QHeaderView::section {{
        background: {C['card2']};
        color: {C['text3']};
        padding: 8px 8px;
        border: none;
        border-bottom: 1px solid {C['border']};
        font-size: 8.5pt;
        font-weight: 700;
        letter-spacing: 0.5px;
    }}
    QHeaderView::section:first {{
        border-top-right-radius: 10px;
    }}
    QHeaderView::section:last {{
        border-top-left-radius: 10px;
    }}
"""

# ─────────────────────────────────────────────────────────────────────────────
# Network helpers
# ─────────────────────────────────────────────────────────────────────────────
def _decode_bytes(b: bytes) -> str:
    for enc in ("utf-8", "cp720", "cp864", "cp1256", "cp437"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def _get_subprocess_kwargs():
    """خيارات إخفاء أي شاشة سوداء للأوامر المنفذة في ويندوز تماماً"""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000
        )
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs


def net_use_connect(ip, username, password, timeout=20):
    unc = f"\\\\{ip}\\IPC$"
    net_use_disconnect(ip)
    cmd = ["net", "use", unc]
    if username:
        cmd += [f"/user:{username}", password]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                **_get_subprocess_kwargs())
        out_b, err_b = proc.communicate(timeout=timeout)
        ok = proc.returncode == 0
        msg = (_decode_bytes(out_b) + _decode_bytes(err_b)).strip() or f"رمز: {proc.returncode}"
        return ok, msg
    except FileNotFoundError:
        return False, "أمر net غير متوفر على هذا الجهاز."
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return False, "انتهت مهلة الاتصال."
    except Exception as e:
        return False, str(e)


def net_use_disconnect(ip):
    try:
        subprocess.run(["net", "use", f"\\\\{ip}\\IPC$", "/delete", "/y"],
                       capture_output=True, timeout=10, **_get_subprocess_kwargs())
    except Exception:
        pass


def list_shares(ip, timeout=15):
    proc = None
    try:
        proc = subprocess.Popen(["net", "view", f"\\\\{ip}"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                **_get_subprocess_kwargs())
        out_b, err_b = proc.communicate(timeout=timeout)
        if proc.returncode != 0:
            return False, _decode_bytes(err_b or out_b)
        shares, started = [], False
        for line in _decode_bytes(out_b).splitlines():
            s = line.strip()
            if s.startswith("---"):
                started = True; continue
            if not started: continue
            if not s or "the command completed" in s.lower() or "اكتمل الأمر" in s:
                break
            parts = s.split()
            if parts: shares.append(parts[0])
        return True, shares
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
            proc.communicate()
        return False, "انتهت مهلة البحث عن المشاركات."
    except Exception as e:
        return False, str(e)


def list_admin_drives(ip, candidates=("C", "D", "E", "F", "G", "H"), timeout=3):
    found = []
    for letter in candidates:
        path = f"\\\\{ip}\\{letter}$"
        holder: dict = {}
        def _check(p=path, h=holder):
            try: h["ok"] = os.path.isdir(p)
            except: h["ok"] = False
        t = threading.Thread(target=_check, daemon=True)
        t.start(); t.join(timeout)
        if holder.get("ok"): found.append(f"{letter}$")
    return found


# ─────────────────────────────────────────────────────────────────────────────
# Share Picker Dialog – modern
# ─────────────────────────────────────────────────────────────────────────────
class SharePickerDialog(QDialog):
    def __init__(self, entries, ip, parent=None):
        super().__init__(parent)
        self.setWindowTitle("اختر المشاركة")
        self.setMinimumSize(460, 340)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet(f"QDialog {{ background: {C['bg']}; }}")
        self.selected_share = None
        self._entries = entries

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        title = QLabel(f"المشاركات المتاحة على  {ip}")
        title.setStyleSheet(f"color: {C['text']}; font-size: 11pt; font-weight: 700;")
        lay.addWidget(title)

        self.lst = QListWidget()
        self.lst.setStyleSheet(f"""
            QListWidget {{
                background: {C['input_bg']};
                border: 1px solid {C['border']};
                border-radius: 10px;
                padding: 6px;
                outline: 0;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-radius: 6px;
                color: {C['text']};
            }}
            QListWidget::item:selected {{
                background: rgba(59,130,246,0.3);
                color: {C['accent2']};
            }}
            QListWidget::item:hover:!selected {{
                background: rgba(255,255,255,0.04);
            }}
        """)
        for display, _ in entries:
            self.lst.addItem(QListWidgetItem(display))
        if self.lst.count():
            self.lst.setCurrentRow(0)
        lay.addWidget(self.lst)

        btn_row = QHBoxLayout()
        btn_ok  = ModernButton("فتح",    "📂", "primary")
        btn_can = ModernButton("إلغاء", "✕",  "ghost")
        btn_ok.clicked.connect(self._on_ok)
        btn_can.clicked.connect(self.reject)
        btn_row.addWidget(btn_can)
        btn_row.addStretch()
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)
        self.lst.itemDoubleClicked.connect(lambda _: self._on_ok())

    def _on_ok(self):
        row = self.lst.currentRow()
        if row >= 0:
            self.selected_share = self._entries[row][1]
        self.accept()


# ─────────────────────────────────────────────────────────────────────────────
# Background workers
# ─────────────────────────────────────────────────────────────────────────────
class ConnectionWorker(QThread):
    result = pyqtSignal(bool, str, str)

    def __init__(self, ip, username, password, parent=None):
        super().__init__(parent)
        self.ip, self.username, self.password = ip, username, password

    def run(self):
        ok, message = net_use_connect(self.ip, self.username, self.password)
        self.result.emit(ok, message, self.ip)


class ShareDiscoveryWorker(QThread):
    result = pyqtSignal(bool, object)

    def __init__(self, ip, parent=None):
        super().__init__(parent)
        self.ip = ip

    def run(self):
        ok, shares_or_error = list_shares(self.ip)
        entries = [(share, share) for share in shares_or_error] if ok else []
        # فحص الأقراص الإدارية بطيء بطبيعته، ولذلك يبقى خارج خيط الواجهة.
        admin = list_admin_drives(self.ip)
        entries.extend((f"{drive}  (قرص كامل – إداري)", drive) for drive in admin)
        self.result.emit(bool(entries), entries if entries else shares_or_error)


class BackupWorker(QThread):
    progress   = pyqtSignal(str, int)
    status_msg = pyqtSignal(str)
    finished   = pyqtSignal(bool)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg

    def run(self):
        logger = logging.getLogger("backup_tool_gui")
        logger.setLevel(logging.DEBUG)
        for handler in logger.handlers[:]:
            handler.close()
        logger.handlers.clear()
        fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s",
                                datefmt="%H:%M:%S")
        try:
            log_dir = Path(self.cfg["logging"]["log_dir"])
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                log_dir / f"backup_{datetime.now():%Y%m%d}.log",
                maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception:
            pass

        last_update = [0.0, -2]

        def cb(name, pct, fname=""):
            # Robocopy قد يبلغ عن آلاف الملفات في الثانية. تقييد التحديثات هنا
            # يبقي الواجهة ناعمة بدون إبطاء النسخ الفعلي.
            now = time.monotonic()
            should_emit = pct in (-1, 100) or (now - last_update[0] >= 0.15 and pct != last_update[1])
            if not should_emit:
                return
            last_update[:] = [now, pct]
            self.progress.emit(name, pct)
            if pct == -1:
                self.status_msg.emit(f"⚙ جاري التحقق: {name}")
            elif fname:
                self.status_msg.emit(f"📋 نسخ: {name} → {fname}")
            else:
                self.status_msg.emit(f"📋 نسخ: {name}  ({pct}%)")

        try:
            ok, _, _ = core.run_backup(self.cfg, logger, False, cb)
            self.finished.emit(ok)
        except Exception as e:
            self.status_msg.emit(f"خطأ: {e}")
            self.finished.emit(False)


# ─────────────────────────────────────────────────────────────────────────────
# Modern Progress Bar
# ─────────────────────────────────────────────────────────────────────────────
class GlowProgressBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(10)
        self.setTextVisible(False)
        self.setStyleSheet(f"""
            QProgressBar {{
                background: {C['card2']};
                border: none;
                border-radius: 5px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C['accent']}, stop:0.6 {C['accent2']}, stop:1 #93C5FD);
                border-radius: 5px;
            }}
        """)
        shadow(self, radius=14, color=C['accent'], offset=(0, 0))


# ─────────────────────────────────────────────────────────────────────────────
# Result Card (shown after backup)
# ─────────────────────────────────────────────────────────────────────────────
class ResultCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self.setVisible(False)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(20, 0, 20, 0)
        self.icon_lbl = QLabel()
        self.icon_lbl.setFont(QFont("Segoe UI Emoji", 26))
        self.icon_lbl.setFixedWidth(50)
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lay.addWidget(self.icon_lbl)
        self.text_lbl = QLabel()
        self.text_lbl.setWordWrap(True)
        self._lay.addWidget(self.text_lbl, stretch=1)

    def show_ok(self):
        self.setVisible(True)
        self.icon_lbl.setText("✅")
        self.text_lbl.setText(
            f'<span style="color:{C["success"]};font-size:13pt;font-weight:700;">'
            'تمت عملية النسخ الاحتياطي بنجاح</span><br>'
            f'<span style="color:{C["text2"]};font-size:9pt;">اللوجات محفوظة في  C:\\BackupTool\\logs</span>')
        self.setStyleSheet(f"""
            ResultCard {{
                background: {C['success_bg']};
                border: 1.5px solid {C['success']};
                border-radius: 12px;
            }}
        """)
        shadow(self, radius=20, color=C['success'], offset=(0, 0))

    def show_fail(self):
        self.setVisible(True)
        self.icon_lbl.setText("❌")
        self.text_lbl.setText(
            f'<span style="color:{C["danger"]};font-size:13pt;font-weight:700;">'
            'فشلت عملية النسخ</span><br>'
            f'<span style="color:{C["text2"]};font-size:9pt;">راجع ملف اللوج في  C:\\BackupTool\\logs  لمزيد من التفاصيل</span>')
        self.setStyleSheet(f"""
            ResultCard {{
                background: {C['danger_bg']};
                border: 1.5px solid {C['danger']};
                border-radius: 12px;
            }}
        """)
        shadow(self, radius=20, color=C['danger'], offset=(0, 0))

    def clear(self):
        self.setVisible(False)


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_ROBOCOPY = {"retries": 3, "wait_seconds": 5, "threads": 8,
                    "mirror": False, "backup_mode": False}
DEFAULT_JOB = {"job_retries": 3, "job_retry_wait_seconds": 60, "retention_days": 30}

COL_NAME = 0
COL_SRC  = 1
COL_DST  = 2


def get_resource_path(filename: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / filename
        if p.exists():
            return p
    return Path(__file__).parent / filename


class BackupMainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Backup Tool")
        self.setMinimumSize(800, 520)
        self.resize(1000, 640)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet(f"QMainWindow {{ background: {C['bg']}; }}")

        self.connected_ip = None
        self.worker: BackupWorker | None = None
        self._connection_worker: ConnectionWorker | None = None
        self._share_worker: ShareDiscoveryWorker | None = None
        self._run_start = 0.0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self._build_ui()

    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root_widget = QWidget()
        root_widget.setStyleSheet(f"background: {C['bg']};")
        self.setCentralWidget(root_widget)
        root_h = QHBoxLayout(root_widget)
        root_h.setContentsMargins(0, 0, 0, 0)
        root_h.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(88)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background: {C['sidebar']};
                border-right: 1px solid {C['border']};
            }}
        """)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(0)

        # Logo area
        logo = QLabel()
        logo.setFixedHeight(72)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"background: {C['bg']}; border-bottom: 1px solid {C['border']};")
        _ico_p = get_resource_path("icon.png")
        if not _ico_p.exists():
            _ico_p = get_resource_path("icon.ico")
        if _ico_p.exists():
            _pm = QPixmap(str(_ico_p)).scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo.setPixmap(_pm)
        else:
            logo.setFont(QFont("Segoe UI Emoji", 26))
            logo.setText("🛡")
        sb_lay.addWidget(logo)

        sb_lay.addSpacing(12)

        nav_items = [
            ("🔗", "الاتصال"),
            ("📋", "المسارات"),
            ("▶", "التشغيل"),
        ]
        self._nav_btns: list[NavButton] = []
        for icon, label in nav_items:
            btn = NavButton(icon, label, sidebar)
            btn.clicked.connect(lambda _, i=len(self._nav_btns): self._switch_page(i))
            sb_lay.addWidget(btn)
            self._nav_btns.append(btn)

        sb_lay.addStretch()

        ver = QLabel("v3.0")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setFixedHeight(32)
        ver.setStyleSheet(f"color: {C['text3']}; font-size: 8pt;")
        sb_lay.addWidget(ver)

        root_h.addWidget(sidebar)

        # ── Main content ──────────────────────────────────────────────────────
        content_area = QWidget()
        content_area.setStyleSheet(f"background: {C['bg']};")
        content_v = QVBoxLayout(content_area)
        content_v.setContentsMargins(0, 0, 0, 0)
        content_v.setSpacing(0)

        # Top header
        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"""
            QFrame {{
                background: {C['sidebar']};
                border-bottom: 1px solid {C['border']};
            }}
        """)
        header_h = QHBoxLayout(header)
        header_h.setContentsMargins(24, 0, 24, 0)

        self._page_title = QLabel("الاتصال بالسيرفر")
        self._page_title.setStyleSheet(
            f"color: {C['text']}; font-size: 13pt; font-weight: 700; background: transparent;")
        header_h.addWidget(self._page_title)
        header_h.addStretch()

        self._conn_badge = StatusBadge()
        header_h.addWidget(self._conn_badge)

        self._time_badge = QLabel("")
        self._time_badge.setStyleSheet(f"color: {C['text2']}; font-size: 9pt; background: transparent;")
        header_h.addWidget(self._time_badge)

        content_v.addWidget(header)

        # Stacked pages
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        content_v.addWidget(self._stack, stretch=1)

        self._build_page_connection()
        self._build_page_sources()
        self._build_page_run()

        root_h.addWidget(content_area, stretch=1)

        # Activate first page
        self._switch_page(0)

    # ─────────────────────────────────────────────────────────────────────────
    # Pages
    # ─────────────────────────────────────────────────────────────────────────
    def _make_scroll_page(self) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(18)
        scroll.setWidget(inner)
        self._stack.addWidget(scroll)
        return scroll, lay

    # PAGE 0 – Connection
    def _build_page_connection(self):
        _, lay = self._make_scroll_page()

        # ── Card: Server ──────────────────────────────────────────────────────
        card = Card(accent_top=True)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(22, 18, 22, 18)
        card_lay.setSpacing(14)

        card_lay.addWidget(SectionLabel("بيانات الاتصال بالسيرفر"))
        card_lay.addWidget(DividerLine())

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(5, 1)

        def lbl(t):
            l = QLabel(t)
            l.setStyleSheet(f"color: {C['text2']}; font-size: 9pt; font-weight: 600;")
            return l

        grid.addWidget(lbl("عنوان IP"),       0, 0, Qt.AlignmentFlag.AlignRight)
        self.entry_ip = ModernInput("")
        grid.addWidget(self.entry_ip, 0, 1)

        grid.addWidget(lbl("اسم المستخدم"),   0, 2, Qt.AlignmentFlag.AlignRight)
        self.entry_user = ModernInput("")
        grid.addWidget(self.entry_user, 0, 3)

        grid.addWidget(lbl("كلمة المرور"),    0, 4, Qt.AlignmentFlag.AlignRight)
        self.entry_pass = ModernInput("", password=True)
        grid.addWidget(self.entry_pass, 0, 5)

        card_lay.addLayout(grid)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.btn_conn = ModernButton("اتصال",       "🔗", "primary")
        btn_disc = ModernButton("قطع الاتصال", "⛔", "danger")
        self.btn_conn.clicked.connect(self._connect_server)
        btn_disc.clicked.connect(self._disconnect_server)
        btn_row.addStretch()
        btn_row.addWidget(btn_disc)
        btn_row.addWidget(self.btn_conn)
        card_lay.addLayout(btn_row)

        lay.addWidget(card)
        lay.addStretch()

        # Info card
        info = Card()
        info_lay = QVBoxLayout(info)
        info_lay.setContentsMargins(18, 14, 18, 14)
        tip = QLabel(
            f"💡  <span style='color:{C['text2']}'>"
            "بعد الاتصال يمكنك تصفح مجلدات السيرفر مباشرةً من صفحة <b>المسارات</b>."
            "<br>إذا كان المجلد محلياً على جهازك لا تحتاج للاتصال.</span>")
        tip.setTextFormat(Qt.TextFormat.RichText)
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {C['accent2']}; font-size: 9.5pt;")
        info_lay.addWidget(tip)
        lay.addWidget(info)

    # PAGE 1 – Sources / Destinations
    def _build_page_sources(self):
        _, lay = self._make_scroll_page()

        # ── Input card ────────────────────────────────────────────────────────
        in_card = Card(accent_top=True)
        in_lay = QVBoxLayout(in_card)
        in_lay.setContentsMargins(22, 18, 22, 18)
        in_lay.setSpacing(12)

        in_lay.addWidget(SectionLabel("إضافة مسار جديد"))
        in_lay.addWidget(DividerLine())

        def lbl(t):
            l = QLabel(t)
            l.setStyleSheet(f"color: {C['text2']}; font-size: 9pt; font-weight: 600;")
            return l

        # Row 1: Name + Source
        r1 = QHBoxLayout(); r1.setSpacing(10)
        r1.addWidget(lbl("الاسم:"))
        self.entry_src_name = ModernInput("")
        self.entry_src_name.setMaximumWidth(190)
        r1.addWidget(self.entry_src_name)

        r1.addSpacing(8)
        r1.addWidget(lbl("مجلد المصدر:"))
        self.entry_src_path = ModernInput("")
        r1.addWidget(self.entry_src_path)

        b_sl = ModernButton("محلي", "📁", "icon")
        b_ss = ModernButton("سيرفر","🌐","icon")
        b_sl.clicked.connect(lambda: self._browse_source_path(False))
        b_ss.clicked.connect(lambda: self._browse_source_path(True))
        r1.addWidget(b_sl); r1.addWidget(b_ss)
        in_lay.addLayout(r1)

        # Row 2: Destination + buttons
        r2 = QHBoxLayout(); r2.setSpacing(10)
        r2.addWidget(lbl("مجلد الوجهة:"))
        self.entry_dst_path = ModernInput("")
        r2.addWidget(self.entry_dst_path)

        b_dl = ModernButton("محلي", "📁", "icon")
        b_ds = ModernButton("سيرفر","🌐","icon")
        b_dl.clicked.connect(lambda: self._browse_into(self.entry_dst_path, False))
        b_ds.clicked.connect(lambda: self._browse_into(self.entry_dst_path, True))
        r2.addWidget(b_dl); r2.addWidget(b_ds)

        btn_add = ModernButton("إضافة", "➕", "primary")
        btn_add.setMinimumWidth(110)
        btn_add.clicked.connect(self._add_source)
        r2.addWidget(btn_add)

        in_lay.addLayout(r2)

        hint = QLabel("ℹ  اضغط على أي صف في الجدول لتحميل بياناته وتعديلها")
        hint.setStyleSheet(f"color: {C['text3']}; font-size: 8.5pt;")
        hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        in_lay.addWidget(hint)
        lay.addWidget(in_card)

        # ── Tree card ─────────────────────────────────────────────────────────
        tree_card = Card()
        tree_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tree_lay = QVBoxLayout(tree_card)
        tree_lay.setContentsMargins(16, 14, 16, 14)
        tree_lay.setSpacing(10)

        tree_header = QHBoxLayout()
        tree_header.addWidget(SectionLabel("قائمة المسارات المضافة"))
        tree_header.addStretch()
        btn_del = ModernButton("حذف المحدد", "🗑", "danger")
        btn_del.setMinimumWidth(130)
        btn_del.clicked.connect(self._remove_selected)
        tree_header.addWidget(btn_del)
        tree_lay.addLayout(tree_header)

        self.src_tree = QTreeWidget()
        self.src_tree.setHeaderLabels(["الاسم", "مجلد المصدر", "مجلد الوجهة"])
        self.src_tree.setAlternatingRowColors(True)
        self.src_tree.setRootIsDecorated(False)
        self.src_tree.setMinimumHeight(220)
        self.src_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.src_tree.setStyleSheet(TREE_SS)
        self.src_tree.itemClicked.connect(self._tree_item_clicked)

        hdr = self.src_tree.header()
        hdr.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(COL_SRC, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_DST, QHeaderView.ResizeMode.Stretch)
        self.src_tree.setColumnWidth(COL_NAME, 160)
        tree_lay.addWidget(self.src_tree)
        lay.addWidget(tree_card)

        # ── Config buttons ────────────────────────────────────────────────────
        cfg_row = QHBoxLayout(); cfg_row.setSpacing(10)
        cfg_row.addStretch()
        btn_load = ModernButton("تحميل إعدادات", "📂", "ghost")
        btn_save = ModernButton("حفظ الإعدادات", "💾", "ghost")
        btn_load.clicked.connect(self._load_config)
        btn_save.clicked.connect(self._save_config)
        cfg_row.addWidget(btn_load)
        cfg_row.addWidget(btn_save)
        lay.addLayout(cfg_row)

    # PAGE 2 – Run
    def _build_page_run(self):
        _, lay = self._make_scroll_page()

        # ── Start card ────────────────────────────────────────────────────────
        run_card = Card(accent_top=True)
        run_lay = QVBoxLayout(run_card)
        run_lay.setContentsMargins(28, 22, 28, 22)
        run_lay.setSpacing(16)

        run_lay.addWidget(SectionLabel("تشغيل النسخ الاحتياطي"))
        run_lay.addWidget(DividerLine())

        desc = QLabel(
            f"<span style='color:{C['text2']}'>"
            "اضغط الزر أدناه لبدء النسخ الاحتياطي لجميع المسارات المضافة.<br>"
            "تأكد أولاً من إضافة المسارات في صفحة <b>المسارات</b>."
            "</span>")
        desc.setTextFormat(Qt.TextFormat.RichText)
        desc.setWordWrap(True)
        run_lay.addWidget(desc)

        self._run_mode = QLabel("✦  نسخة ذكية وآمنة  •  تعمل بصمت في الخلفية")
        self._run_mode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._run_mode.setStyleSheet(f"""
            background: rgba(59,130,246,0.12); color: {C['accent2']};
            border: 1px solid rgba(96,165,250,0.35); border-radius: 13px;
            padding: 6px 14px; font-size: 9pt; font-weight: 600;
        """)
        run_lay.addWidget(self._run_mode, alignment=Qt.AlignmentFlag.AlignCenter)

        run_btn_row = QHBoxLayout()
        run_btn_row.addStretch()
        self.btn_run = ModernButton("بدء النسخ الاحتياطي الآن", "▶", "success")
        self.btn_run.setFixedSize(250, 42)
        self.btn_run.setStyleSheet(self.btn_run.styleSheet() +
                                    "font-size: 11pt; border-radius: 9px; padding: 0 16px;")
        self.btn_run.clicked.connect(self._start_backup)
        run_btn_row.addWidget(self.btn_run)
        run_btn_row.addStretch()
        run_lay.addLayout(run_btn_row)

        lay.addWidget(run_card)

        # ── Progress card ─────────────────────────────────────────────────────
        prog_card = Card()
        prog_lay = QVBoxLayout(prog_card)
        prog_lay.setContentsMargins(24, 18, 24, 18)
        prog_lay.setSpacing(14)

        prog_header = QHBoxLayout()
        self.lbl_prog_src = QLabel("في انتظار البدء...")
        self.lbl_prog_src.setStyleSheet(f"color: {C['text2']}; font-size: 10pt; font-weight: 600;")
        prog_header.addWidget(self.lbl_prog_src)
        prog_header.addStretch()
        self.lbl_elapsed = QLabel("")
        self.lbl_elapsed.setStyleSheet(f"color: {C['text3']}; font-size: 9pt;")
        prog_header.addWidget(self.lbl_elapsed)
        prog_lay.addLayout(prog_header)

        self.progress_bar = GlowProgressBar()
        prog_lay.addWidget(self.progress_bar)

        self.lbl_pct = QLabel("0%")
        self.lbl_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_pct.setStyleSheet(f"color: {C['text3']}; font-size: 8.5pt;")
        prog_lay.addWidget(self.lbl_pct)

        lay.addWidget(prog_card)

        # ── Result card ───────────────────────────────────────────────────────
        self.result_card = ResultCard()
        lay.addWidget(self.result_card)

        lay.addStretch()

        footer = QLabel("Developed by : Mohammed Eydan")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet(f"color: {C['text3']}; font-size: 8.5pt;")
        lay.addWidget(footer)

    # ─────────────────────────────────────────────────────────────────────────
    # Navigation
    # ─────────────────────────────────────────────────────────────────────────
    PAGE_TITLES = ["الاتصال بالسيرفر", "إدارة المسارات", "التشغيل والمتابعة"]

    def _switch_page(self, idx: int):
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
        self._stack.setCurrentIndex(idx)
        self._page_title.setText(self.PAGE_TITLES[idx])

    # ─────────────────────────────────────────────────────────────────────────
    # Network
    # ─────────────────────────────────────────────────────────────────────────
    def _connect_server(self):
        ip   = self.entry_ip.text().strip()
        user = self.entry_user.text().strip()
        pw   = self.entry_pass.text()
        if not ip:
            QMessageBox.warning(self, "تنبيه", "أدخل IP السيرفر أولاً.")
            return
        if self._connection_worker and self._connection_worker.isRunning():
            return
        self._conn_badge.set_warn("جاري الاتصال...")
        self.btn_conn.setEnabled(False)
        self._connection_worker = ConnectionWorker(ip, user, pw, self)
        self._connection_worker.result.connect(self._on_connection_finished)
        self._connection_worker.finished.connect(self._on_connection_thread_finished)
        self._connection_worker.start()

    def _on_connection_thread_finished(self):
        worker = self.sender()
        if self._connection_worker is worker:
            self._connection_worker = None
        worker.deleteLater()

    def _on_connection_finished(self, ok, msg, ip):
        self.btn_conn.setEnabled(True)
        if ok:
            self.connected_ip = ip
            self._conn_badge.set_ok(f"متصل بـ {ip}")
        else:
            self.connected_ip = None
            self._conn_badge.set_error("فشل الاتصال")
            QMessageBox.critical(self, "فشل الاتصال", msg)

    def _disconnect_server(self):
        if self.connected_ip:
            net_use_disconnect(self.connected_ip)
        self.connected_ip = None
        self._conn_badge.set_error("غير متصل")

    # ─────────────────────────────────────────────────────────────────────────
    # Browse
    # ─────────────────────────────────────────────────────────────────────────
    def _browse_into(self, entry: QLineEdit, remote: bool) -> str:
        if remote:
            if not self.connected_ip:
                QMessageBox.warning(self, "تنبيه", "اتصل بالسيرفر أولاً.")
                return ""
            self._discover_remote_share(entry)
            return ""
        else:
            initial = entry.text().strip() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "اختر المجلد", initial)
        if chosen:
            entry.setText(chosen)
        return chosen or ""

    def _browse_source_path(self, remote: bool):
        if remote:
            if not self.connected_ip:
                QMessageBox.warning(self, "تنبيه", "اتصل بالسيرفر أولاً.")
                return
            self._discover_remote_share(self.entry_src_path, set_source_name=True)
            return
        chosen = self._browse_into(self.entry_src_path, remote)
        if chosen and not self.entry_src_name.text().strip():
            self.entry_src_name.setText(os.path.basename(os.path.normpath(chosen)))

    def _discover_remote_share(self, entry: QLineEdit, set_source_name=False):
        if self._share_worker and self._share_worker.isRunning():
            QMessageBox.information(self, "جاري البحث", "البحث عن المشاركات يعمل بالفعل.")
            return
        self._conn_badge.set_warn("جاري البحث عن المشاركات...")
        self._share_worker = ShareDiscoveryWorker(self.connected_ip, self)
        self._share_worker.result.connect(
            lambda ok, data: self._on_shares_found(ok, data, entry, set_source_name))
        self._share_worker.finished.connect(self._on_share_thread_finished)
        self._share_worker.start()

    def _on_share_thread_finished(self):
        worker = self.sender()
        if self._share_worker is worker:
            self._share_worker = None
        worker.deleteLater()

    def _on_shares_found(self, ok, data, entry, set_source_name):
        self._conn_badge.set_ok(f"متصل بـ {self.connected_ip}")
        entries = data if ok else []
        if not entries:
            QMessageBox.information(self, "لا مشاركات",
                f"لم يُعثر على مشاركات على {self.connected_ip}.\n{data if isinstance(data, str) else ''}")
            return
        dlg = SharePickerDialog(entries, self.connected_ip, self)
        dlg.exec()
        if not dlg.selected_share:
            return
        initial = f"\\\\{self.connected_ip}\\{dlg.selected_share}"
        chosen = QFileDialog.getExistingDirectory(self, "اختر المجلد", initial)
        if chosen:
            entry.setText(chosen)
            if set_source_name and not self.entry_src_name.text().strip():
                self.entry_src_name.setText(os.path.basename(os.path.normpath(chosen)))

    # ─────────────────────────────────────────────────────────────────────────
    # Sources tree
    # ─────────────────────────────────────────────────────────────────────────
    def _add_source(self):
        name = self.entry_src_name.text().strip()
        src  = self.entry_src_path.text().strip()
        dst  = self.entry_dst_path.text().strip()
        if not all([name, src, dst]):
            QMessageBox.warning(self, "تنبيه",
                                "أدخل الاسم + المصدر + الوجهة قبل الإضافة.")
            return
        item = QTreeWidgetItem([name, src, dst])
        item.setToolTip(COL_SRC, src)
        item.setToolTip(COL_DST, dst)
        self.src_tree.addTopLevelItem(item)
        for e in (self.entry_src_name, self.entry_src_path, self.entry_dst_path):
            e.clear()

    def _remove_selected(self):
        for item in self.src_tree.selectedItems():
            self.src_tree.takeTopLevelItem(
                self.src_tree.indexOfTopLevelItem(item))

    def _tree_item_clicked(self, item: QTreeWidgetItem, _col):
        self.entry_src_name.setText(item.text(COL_NAME))
        self.entry_src_path.setText(item.text(COL_SRC))
        self.entry_dst_path.setText(item.text(COL_DST))

    def _get_sources(self):
        return [{"name": self.src_tree.topLevelItem(i).text(COL_NAME),
                 "path": self.src_tree.topLevelItem(i).text(COL_SRC),
                 "destination": self.src_tree.topLevelItem(i).text(COL_DST)}
                for i in range(self.src_tree.topLevelItemCount())]

    # ─────────────────────────────────────────────────────────────────────────
    # Config
    # ─────────────────────────────────────────────────────────────────────────
    def _build_config(self):
        sources = self._get_sources()
        if not sources:
            raise ValueError("أضف مصدراً واحداً على الأقل.")
        return {
            "sources": sources,
            "target_root": sources[0]["destination"],
            "timestamped_backup": False,
            "robocopy": DEFAULT_ROBOCOPY,
            **DEFAULT_JOB,
            "verification": {"compare_file_count_and_size": True,
                             "checksum_verify_sources": []},
            "logging": {"log_dir": r"C:\BackupTool\logs", "keep_log_days": 60},
            "email": {"enabled": False},
        }

    def _save_config(self):
        try:
            cfg = self._build_config()
        except ValueError as ex:
            QMessageBox.warning(self, "تنبيه", str(ex)); return
        cfg["connection"] = {"ip": self.entry_ip.text().strip(),
                             "username": self.entry_user.text().strip()}
        path, _ = QFileDialog.getSaveFileName(self, "حفظ الإعدادات",
                                              "config.yaml", "YAML (*.yaml *.yml)")
        if not path: return
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        QMessageBox.information(self, "تم", f"تم الحفظ في:\n{path}")

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "تحميل إعدادات",
                                              "", "YAML (*.yaml *.yml)")
        if not path: return
        try:
            cfg = yaml.safe_load(open(path, encoding="utf-8"))
            self.src_tree.clear()
            for s in cfg.get("sources", []):
                self.src_tree.addTopLevelItem(
                    QTreeWidgetItem([s.get("name",""), s.get("path",""),
                                     s.get("destination","")]))
            conn = cfg.get("connection", {})
            if conn.get("ip"): self.entry_ip.setText(conn["ip"])
            if conn.get("username"): self.entry_user.setText(conn["username"])
            QMessageBox.information(self, "تم", "تم تحميل الإعدادات.")
        except Exception as ex:
            QMessageBox.critical(self, "خطأ", str(ex))

    # ─────────────────────────────────────────────────────────────────────────
    # Backup
    # ─────────────────────────────────────────────────────────────────────────
    def _start_backup(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "تنبيه", "عملية نسخ تعمل بالفعل.")
            return
        try:
            cfg = self._build_config()
        except ValueError as ex:
            QMessageBox.warning(self, "تنبيه", str(ex)); return

        self.result_card.clear()
        self.progress_bar.setValue(0)
        self.lbl_pct.setText("0%")
        self.lbl_prog_src.setText("جاري البدء...")
        self.btn_run.setEnabled(False)
        self._run_start = time.time()
        self._elapsed_timer.start()

        # Switch to run page
        self._switch_page(2)

        self.worker = BackupWorker(cfg, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.status_msg.connect(
            lambda m: self.lbl_prog_src.setText(m))
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _tick_elapsed(self):
        e = int(time.time() - self._run_start)
        mm, ss = divmod(e, 60)
        self.lbl_elapsed.setText(f"⏱  {mm:02d}:{ss:02d}")
        self._time_badge.setText(f"⏱  {mm:02d}:{ss:02d}")

    def _on_progress(self, name, pct):
        if pct >= 0:
            self.progress_bar.setValue(pct)
            self.lbl_pct.setText(f"{pct}%")
            self.lbl_prog_src.setText(f"📋 نسخ: {name}")
        else:
            self.lbl_prog_src.setText(f"⚙ تحقق من: {name}")

    def _on_finished(self, ok: bool):
        self._elapsed_timer.stop()
        self._time_badge.setText("")
        self.btn_run.setEnabled(True)
        self.progress_bar.setValue(100 if ok else self.progress_bar.value())
        self.lbl_pct.setText("100%" if ok else f"{self.progress_bar.value()}%")
        self.lbl_prog_src.setText("اكتملت العملية" if ok else "انتهت بفشل")
        if ok:
            self.result_card.show_ok()
        else:
            self.result_card.show_fail()

    def closeEvent(self, event):
        """لا تسمح بإغلاق Qt بينما خيط النسخ ما زال يكتب على القرص."""
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(
                self, "نسخ جارٍ", "لا يمكن إغلاق التطبيق أثناء النسخ الاحتياطي. انتظر حتى تظهر النتيجة.")
            event.ignore()
            return
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("BackupTool")
    app.setOrganizationName("MohammedEydan")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setStyleSheet(GLOBAL_SS)

    # تحميل الأيقونة
    icon_path = get_resource_path("icon.ico")
    if not icon_path.exists():
        icon_path = get_resource_path("icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = BackupMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
