"""Thème visuel partagé de StellarDust."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

C = {
    "bg": "#0B1224", "panel": "#111A31", "panel2": "#0E172B", "line": "#243251",
    "text": "#EAF0FF", "muted": "#7F91B8", "dim": "#56678C", "accent": "#8C9EFF",
    "primary": "#7667E8", "ok": "#5CE1B9", "warn": "#F5C56B", "err": "#FF7A8A",
}


def label(text, color=None, size=None, bold=False, wrap=False):
    w = QLabel(text)
    css = []
    if color:
        css.append(f"color:{color};")
    if size:
        css.append(f"font-size:{size}px;")
    if bold:
        css.append("font-weight:700;")
    w.setStyleSheet("".join(css))
    w.setWordWrap(wrap)
    return w


class SectionTitle(QLabel):
    def __init__(self, text):
        super().__init__(text.upper())
        self.setStyleSheet(f"color:{C['muted']}; font-size:10px; font-weight:700; letter-spacing:1px; padding:10px 0 4px;")


STYLE = f"""
    * {{ font-family: Inter, "Noto Sans", Arial; }}
    QMainWindow, #root {{ background:{C['bg']}; color:{C['text']}; }}
    QWidget {{ color:#DCE4F7; }}
    QLabel {{ background:transparent; }}
    #toolbar {{ background:{C['panel']}; border-bottom:1px solid {C['line']}; }}
    #sidebar {{ background:{C['panel2']}; border-right:1px solid {C['line']}; }}
    #panel {{ background:{C['panel']}; border:1px solid {C['line']}; border-radius:10px; }}
    QPushButton {{ color:#A9B8D5; background:transparent; border:0; border-radius:7px; padding:8px 10px; text-align:left; font-size:12px; }}
    QPushButton:hover {{ background:#1A2947; color:#F4F7FF; }}
    QPushButton:disabled {{ color:#44557A; }}
    QPushButton[active="true"] {{ background:#24365B; color:#FFFFFF; }}
    #workflowStep {{ text-align:center; padding:6px 12px; border-radius:14px; }}
    QPushButton[activeStep="true"] {{ background:#263862; color:#FFFFFF; border:1px solid {C['accent']}; }}
    QPushButton[activeStep="false"] {{ color:{C['muted']}; }}
    #topButton {{ background:#182442; color:#C3D0EA; padding:6px 12px; margin-left:4px; text-align:center; }}
    #primary {{ background:{C['primary']}; color:#FFFFFF; font-weight:700; text-align:center; padding:9px 16px; }}
    #primary:hover {{ background:#8577F0; }}
    #primary:disabled {{ background:#2A2F55; color:#6B7299; }}
    #secondary {{ background:#1A2947; color:#C9D5ED; text-align:center; padding:7px 12px; }}
    #paletteButton {{ background:#131E38; margin:1px 0; padding:7px 8px; }}
    #paletteButton:hover {{ background:#1C2B4B; }}
    QLineEdit, QComboBox, QDoubleSpinBox, QTextEdit {{ background:{C['bg']}; border:1px solid #2A3A5A; border-radius:6px; color:#DCE4F7; padding:5px 7px; font-size:12px; }}
    QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {{ border:1px solid {C['accent']}; }}
    QComboBox QAbstractItemView {{ background:{C['panel']}; color:#DCE4F7; selection-background-color:#263862; }}
    QCheckBox {{ font-size:12px; color:#C3D0EA; spacing:8px; padding:3px 0; }}
    QSlider::groove:horizontal {{ height:4px; background:#2A3A5A; border-radius:2px; }}
    QSlider::handle:horizontal {{ width:14px; margin:-5px 0; border-radius:7px; background:{C['accent']}; }}
    QListWidget {{ background:{C['panel2']}; border:1px solid {C['line']}; border-radius:8px; color:#C3D0EA; font-size:12px; padding:4px; }}
    QListWidget::item {{ padding:7px; border-radius:6px; }}
    QListWidget::item:selected {{ background:#1C2B4B; color:#FFFFFF; }}
    QTabWidget::pane {{ border:0; border-left:1px solid {C['line']}; background:{C['panel']}; padding:10px; }}
    QTabBar::tab {{ background:{C['panel2']}; color:{C['muted']}; padding:9px 16px; border:0; }}
    QTabBar::tab:selected {{ background:{C['panel']}; color:#FFFFFF; border-bottom:2px solid {C['accent']}; }}
    QToolBox::tab {{ background:#152039; color:#C3D0EA; border-radius:6px; padding:6px; font-weight:700; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background:transparent; }}
    QScrollBar:vertical {{ background:transparent; width:8px; }}
    QScrollBar::handle:vertical {{ background:#2A3A5A; border-radius:4px; min-height:30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
    QMenu {{ background:{C['panel']}; border:1px solid {C['line']}; color:#DCE4F7; padding:4px; }}
    QMenu::item {{ padding:6px 18px; border-radius:4px; }}
    QMenuBar {{ background:{C['panel']}; color:#C3D0EA; border-bottom:1px solid {C['line']}; }}
    QMenuBar::item:selected {{ background:#263862; }}
    QMenu::separator {{ height:1px; background:{C['line']}; margin:4px 8px; }}
    QMenu::item:selected {{ background:#263862; }}
    QToolTip {{ background:{C['panel']}; color:#DCE4F7; border:1px solid {C['line']}; padding:6px; }}
    QStatusBar {{ background:{C['panel']}; color:#AAB9D6; border-top:1px solid {C['line']}; font-size:11px; }}
"""


