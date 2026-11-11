"""Cores, medidas e a folha de estilo da janela."""
from __future__ import annotations

# Superfícies, da mais funda à mais alta.
WINDOW = "#0e1014"
STAGE = "#12151b"
SIDEBAR = "#14171d"
CARD = "#1a1e26"
FIELD = "#232834"
BORDER = "#262b37"
BORDER_STRONG = "#353c4c"

TEXT = "#e9ebf1"
MUTED = "#98a1b3"
FAINT = "#6b7385"

ACCENT = "#7c9cff"
GO = "#22c55e"
GO_HOVER = "#2ed46b"
STOP = "#ef4444"
STOP_HOVER = "#f65c5c"
WARN = "#f5b453"
INFO = "#60a5fa"

RADIUS = 12
SIDEBAR_WIDTH = 380

STYLE = f"""
QWidget {{ background: {WINDOW}; color: {TEXT}; font-family: "Segoe UI"; font-size: 10pt; }}
QWidget#sidebar {{ background: {SIDEBAR}; border-left: 1px solid {BORDER}; }}
QWidget#sidebarBody, QWidget#footer, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {SIDEBAR}; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px 4px 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 3px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QLabel {{ background: transparent; }}
QLabel#brand {{ font-size: 12pt; font-weight: 600; }}
QLabel#chip {{ color: {MUTED}; font-size: 9pt; }}
QLabel#cardTitle {{ color: {MUTED}; font-size: 8.5pt; font-weight: 600; letter-spacing: 1px; }}
QLabel#rowLabel {{ font-size: 10pt; }}
QLabel#rowHint, QLabel#note {{ color: {MUTED}; font-size: 9pt; }}
QLabel#noteError {{ color: #ff8a80; font-size: 9pt; }}
QLabel#value {{ color: {MUTED}; font-size: 9pt; }}
QLabel#status {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#details {{ background: #0b0d11; color: #c3c9d6; font-family: Consolas; font-size: 9pt; padding: 10px 14px;
                 border-top: 1px solid {BORDER}; }}

QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; }}
QFrame#card QWidget {{ background: transparent; }}

QComboBox {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 10px; }}
QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
QComboBox:disabled {{ color: {FAINT}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{ background: {FIELD}; border: 1px solid {BORDER_STRONG}; outline: none;
                               selection-background-color: #34405e; padding: 4px; }}

QPushButton#primary {{ background: {GO}; border: none; border-radius: {RADIUS}px; color: #06210f;
                       font-size: 12pt; font-weight: 700; padding: 13px; }}
QPushButton#primary:hover {{ background: {GO_HOVER}; }}
QPushButton#primary[live="true"] {{ background: {STOP}; color: white; }}
QPushButton#primary[live="true"]:hover {{ background: {STOP_HOVER}; }}
QPushButton#primary:disabled {{ background: {FIELD}; color: {FAINT}; }}

QPushButton#ghost {{ background: transparent; border: none; color: {MUTED}; font-size: 9pt; padding: 4px 6px; }}
QPushButton#ghost:hover {{ color: {TEXT}; }}
QPushButton#small {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px;
                     font-size: 9pt; }}
QPushButton#small:hover {{ border-color: {BORDER_STRONG}; }}

QPushButton#overlay {{ background: rgba(14, 16, 20, 190); border: 1px solid rgba(255, 255, 255, 34);
                       border-radius: 15px; color: {TEXT}; font-size: 9pt; padding: 6px 14px; }}
QPushButton#overlay:hover {{ background: rgba(34, 39, 50, 220); }}
QPushButton#overlay:checked {{ background: {WARN}; color: #2a1a00; border-color: {WARN}; font-weight: 600; }}

QPushButton#segment {{ background: transparent; border: none; border-radius: 7px; color: {MUTED};
                       padding: 6px 4px; font-size: 9.5pt; }}
QPushButton#segment:hover {{ color: {TEXT}; }}
QPushButton#segment:checked {{ background: #323a4d; color: {TEXT}; font-weight: 600; }}
QPushButton#segment:disabled {{ color: {FAINT}; }}
QFrame#segmented {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: 9px; }}

QPushButton#cardToggle {{ background: transparent; border: none; text-align: left; color: {MUTED};
                          font-size: 8.5pt; font-weight: 600; letter-spacing: 1px; padding: 0; }}
QPushButton#cardToggle:hover {{ color: {TEXT}; }}

QToolButton#face {{ border: 2px solid transparent; border-radius: 12px; background: transparent; padding: 1px; }}
QToolButton#face:hover {{ border-color: {BORDER_STRONG}; }}
QToolButton#face:checked {{ border-color: {ACCENT}; }}
QToolButton#addFace {{ border: 1.5px dashed {BORDER_STRONG}; border-radius: 12px; background: transparent;
                       color: {MUTED}; font-size: 18pt; }}
QToolButton#addFace:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}

QSlider::groove:horizontal {{ height: 4px; background: {FIELD}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: white; }}

QMenu {{ background: {FIELD}; border: 1px solid {BORDER_STRONG}; padding: 4px; }}
QMenu::item {{ padding: 6px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: #34405e; }}
QToolTip {{ background: {FIELD}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 6px 8px; }}
"""
