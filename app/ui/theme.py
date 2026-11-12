"""Cores, medidas e a folha de estilo da janela.

A identidade é preto, branco e tons de cinza, com o verde reservado para o que está ligado,
escolhido ou pronto, e o vermelho só para parar. Há dois temas, escuro (o padrão) e claro;
``apply`` troca as cores deste módulo e refaz a folha de estilo. As peças desenhadas à mão
leem as cores daqui a cada pintura, então basta redesenhar a janela depois da troca.
"""
from __future__ import annotations

RADIUS = 12
SIDEBAR_WIDTH = 380

PALETTES = {
    "dark": dict(
        # Superfícies, da mais funda à mais alta.
        WINDOW="#0b0b0c", STAGE="#111112", SIDEBAR="#101011", CARD="#18181a", FIELD="#222225", WELL="#0a0a0b",
        BORDER="#29292d", BORDER_STRONG="#3e3e44",
        TEXT="#f3f3f4", MUTED="#a2a2a8", FAINT="#6c6c73",
        ACCENT="#2fd675", ACCENT_SOFT="#16311f",        # verde: ligado, escolhido, pronto
        GO="#2fd675", GO_HOVER="#4be38b", ON_GO="#04210f",
        STOP="#f0463c", STOP_HOVER="#f76157",
        WARN="#f2b24c", INFO="#d6d6da",
        BAR="#ffffff",                                   # a barra de progresso da abertura
        SELECTED="#303034", SWITCH_OFF="#3b3b40", KNOB="#ffffff",
        DETAILS_BG="#080809", DETAILS_TEXT="#c9c9cd", ERROR_TEXT="#ff8a80",
        TILE="#ffffff", TILE_BORDER="#ffffff", SHADOW=150,   # o bloco branco do mascote e a sombra dele
    ),
    "light": dict(
        WINDOW="#ededee", STAGE="#f8f8f8", SIDEBAR="#f6f6f7", CARD="#ffffff", FIELD="#efeff0", WELL="#e4e4e6",
        BORDER="#dedee1", BORDER_STRONG="#c2c2c7",
        TEXT="#161617", MUTED="#5d5d64", FAINT="#97979e",
        ACCENT="#129b4c", ACCENT_SOFT="#dff3e7",
        GO="#17a552", GO_HOVER="#139247", ON_GO="#ffffff",
        STOP="#e0362b", STOP_HOVER="#c92d23",
        WARN="#b97a10", INFO="#3a3a40",
        BAR="#161617",
        SELECTED="#e0e0e3", SWITCH_OFF="#c5c5ca", KNOB="#ffffff",
        DETAILS_BG="#e7e7e9", DETAILS_TEXT="#2c2c30", ERROR_TEXT="#c62a1f",
        TILE="#ffffff", TILE_BORDER="#d6d6da", SHADOW=40,
    ),
}
# Sobre o vídeo (selo, recados, botões) as cores não mudam com o tema: é sempre texto claro
# num fundo escuro translúcido, que se lê em cima de qualquer imagem.
OVERLAY_TEXT = "#f3f3f4"
OVERLAY_MUTED = "#b4b4ba"
OVERLAY_WARN = "#f2b24c"

NAME = "dark"
STYLE = ""


def _style() -> str:
    return f"""
QWidget {{ background: {WINDOW}; color: {TEXT}; font-family: "Segoe UI"; font-size: 10pt; }}
QWidget#sidebar {{ background: {SIDEBAR}; border-left: 1px solid {BORDER}; }}
QWidget#sidebarBody, QWidget#footer, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {SIDEBAR}; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px 4px 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 3px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QLabel {{ background: transparent; }}
QLabel#brand {{ font-size: 12.5pt; font-weight: 600; }}
QLabel#pageTitle {{ font-size: 12pt; font-weight: 600; }}
QLabel#cardTitle {{ color: {MUTED}; font-size: 8.5pt; font-weight: 600; letter-spacing: 1px; }}
QLabel#rowLabel {{ font-size: 10pt; }}
QLabel#rowHint, QLabel#note {{ color: {MUTED}; font-size: 9pt; }}
QLabel#noteError {{ color: {ERROR_TEXT}; font-size: 9pt; }}
QLabel#value {{ color: {MUTED}; font-size: 9pt; }}
QLabel#status {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#about {{ color: {FAINT}; font-size: 8.5pt; }}
QLabel#details {{ background: {DETAILS_BG}; color: {DETAILS_TEXT}; font-family: Consolas; font-size: 9pt;
                 padding: 10px 14px; border-top: 1px solid {BORDER}; }}

QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; }}
QFrame#card QWidget {{ background: transparent; }}

QComboBox {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 10px; }}
QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
QComboBox:disabled {{ color: {FAINT}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{ background: {FIELD}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; outline: none;
                               selection-background-color: {SELECTED}; selection-color: {TEXT}; padding: 4px; }}

QPushButton#ghost {{ background: transparent; border: none; color: {MUTED}; font-size: 9pt; padding: 4px 6px; }}
QPushButton#ghost:hover {{ color: {TEXT}; }}
QPushButton#small {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px;
                     font-size: 9pt; }}
QPushButton#small:hover {{ border-color: {BORDER_STRONG}; }}

QPushButton#overlay {{ background: rgba(11, 11, 12, 190); border: 1px solid rgba(255, 255, 255, 34);
                       border-radius: 15px; color: {OVERLAY_TEXT}; font-size: 9pt; padding: 6px 14px; }}
QPushButton#overlay:hover {{ background: rgba(40, 40, 44, 220); }}
QPushButton#overlay:checked {{ background: {OVERLAY_WARN}; color: #2a1a00; border-color: {OVERLAY_WARN}; font-weight: 600; }}

QPushButton#segment {{ background: transparent; border: none; border-radius: 7px; color: {MUTED};
                       padding: 6px 4px; font-size: 9.5pt; }}
QPushButton#segment:hover {{ color: {TEXT}; }}
QPushButton#segment:checked {{ background: {SELECTED}; color: {TEXT}; font-weight: 600; }}
QPushButton#segment:disabled {{ color: {FAINT}; }}
QFrame#segmented {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: 9px; }}

QSlider::groove:horizontal {{ height: 4px; background: {FIELD}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}

QMenu {{ background: {FIELD}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 4px; }}
QMenu::item {{ padding: 6px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SELECTED}; }}
QToolTip {{ background: {FIELD}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 6px 8px; }}
"""


def apply(name: str) -> str:
    """Passa a valer o tema pedido ("dark" ou "light"); devolve a folha de estilo dele."""
    global NAME, STYLE
    NAME = name if name in PALETTES else "dark"
    globals().update(PALETTES[NAME])
    STYLE = _style()
    return STYLE


apply("dark")
