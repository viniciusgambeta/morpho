"""Peças da janela: mascote, palco do resultado, prévia da câmera, galeria de rostos e controles."""
from __future__ import annotations

import json
import math
import os
import time
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QIcon, QImage, QImageReader, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QVBoxLayout, QWidget,
)

from app.ui import theme

STAGE_MARGIN = 18
STAGE_RADIUS = 16
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


# ── marca ────────────────────────────────────────────────────────────────────────────────
# O símbolo é o ganso de óculos, em preto e branco. Em fundo escuro ele aparece sempre dentro
# de um bloco branco de cantos arredondados; é esse bloco o ícone do app.
GOOSE_FILE = os.path.join(ASSETS, "ganso.svg")
# O desenho ocupa só o miolo do arquivo (512 x 512). Este recorte quadrado o centraliza e
# deixa o ganso com uns três quartos da largura do bloco.
GOOSE_VIEW = QRectF(23, 44.5, 465, 465)
TILE_ROUNDING = 0.235      # raio dos cantos do bloco, como fração do lado
_goose = None


def paint_goose(painter: QPainter, box: QRectF) -> None:
    """O ganso, desenhado dentro de ``box`` (sem o bloco)."""
    global _goose
    if _goose is None:
        from PySide6.QtSvg import QSvgRenderer

        _goose = QSvgRenderer(GOOSE_FILE)
        if _goose.isValid():
            _goose.setViewBox(GOOSE_VIEW)
    if not _goose.isValid():
        return
    side = min(box.width(), box.height())
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _goose.render(painter, QRectF(box.center().x() - side / 2, box.center().y() - side / 2, side, side))
    painter.restore()


def paint_tile(painter: QPainter, box: QRectF, border: Optional[QColor] = None) -> None:
    """O bloco branco de cantos arredondados com o ganso dentro."""
    side = min(box.width(), box.height())
    tile = QRectF(box.center().x() - side / 2, box.center().y() - side / 2, side, side)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(border, 1) if border is not None else Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    inset = 0.5 if border is not None else 0.0
    painter.drawRoundedRect(tile.adjusted(inset, inset, -inset, -inset), side * TILE_ROUNDING, side * TILE_ROUNDING)
    paint_goose(painter, tile)
    painter.restore()


def app_icon() -> QIcon:
    """O ícone da janela e da barra de tarefas: o ganso no bloco branco."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        tile = QPixmap(size, size)
        tile.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tile)
        # A borda cinza clara só aparece quando o fundo também é branco (barra de tarefas clara).
        paint_tile(painter, QRectF(0, 0, size, size), QColor(0, 0, 0, 46))
        painter.end()
        icon.addPixmap(tile)
    return icon


def play_honk() -> None:
    """O grito do ganso. Toca sem travar a janela; sem som disponível, não faz nada."""
    try:
        import winsound

        winsound.PlaySound(os.path.join(ASSETS, "honk.wav"),
                           winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass


# ── mascote ──────────────────────────────────────────────────────────────────────────────
# As animações vêm prontas de packaging/make_mascot.py: uma imagem por animação, com todos os
# quadros de um ciclo numa grade. Só as que o Vinicius liberou para o app: parado, dormindo,
# gritando, matrix e pilulas.
MASCOT_DIR = os.path.join(ASSETS, "mascote")
_mascot_index: Optional[dict] = None
_mascot_frames: Dict[Tuple[str, int], List[QPixmap]] = {}


def mascot_info(name: str) -> Optional[dict]:
    global _mascot_index
    if _mascot_index is None:
        try:
            with open(os.path.join(MASCOT_DIR, "mascote.json"), encoding="utf-8") as f:
                _mascot_index = json.load(f)["animations"]
        except (OSError, ValueError, KeyError):
            _mascot_index = {}
    return _mascot_index.get(name)


def mascot_frames(name: str, pixels: int) -> List[QPixmap]:
    """Os quadros de uma animação, já no tamanho em que vão ser desenhados."""
    key = (name, pixels)
    if key not in _mascot_frames:
        info, frames = mascot_info(name), []
        sheet = QImage(os.path.join(MASCOT_DIR, name + ".png")) if info else QImage()
        if info and not sheet.isNull():
            size, columns = info["size"], info["columns"]
            for index in range(info["frames"]):
                cell = sheet.copy((index % columns) * size, (index // columns) * size, size, size)
                if pixels != size:
                    cell = cell.scaled(pixels, pixels, Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                frames.append(QPixmap.fromImage(cell))
        _mascot_frames[key] = frames
    return _mascot_frames[key]


def release_mascot(*names: str) -> None:
    """Solta da memória os quadros de animações que não vão mais aparecer (as da abertura)."""
    for key in [k for k in _mascot_frames if k[0] in names]:
        del _mascot_frames[key]


def _ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


class Mascot(QWidget):
    """O ganso animado dentro do bloco branco.

    ``play`` troca a animação na hora. ``switch`` faz a passagem com um pulinho: o bloco se
    abaixa, salta e troca no ar, com uma fusão curta entre a animação que sai e a que entra.
    Uma animação sem laço para no último quadro e avisa por ``finished``.
    """

    finished = Signal(str)
    HOP_SECONDS = 0.46
    HOP_SWAP_AT = 0.45       # fração do pulo em que a animação troca (o ponto mais alto)
    FADE_SECONDS = 0.16
    FPS = 30

    def __init__(self, side: int = 132, backdrop: str = "STAGE", compact: bool = False, floating: bool = False) -> None:
        super().__init__()
        self._side, self._backdrop, self._compact, self._floating = side, backdrop, compact, floating
        self._name: Optional[str] = None
        self._loop, self._speed, self._clock = True, 1.0, 0.0
        self._done = False
        self._next: Optional[tuple] = None          # (nome, laço, velocidade) à espera do ponto alto do pulo
        self._hop_at: Optional[float] = None
        self._fade: Optional[tuple] = None          # (nome que sai, instante dele, quando a fusão começou)
        self._last = time.perf_counter()
        self._born = self._last
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / self.FPS))
        self._timer.timeout.connect(self._advance)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setFixedSize(self.sizeHint())

    # tamanho: o bloco, mais a folga do pulo em cima e a da sombra embaixo
    def _rooms(self) -> Tuple[float, float, float]:
        if self._compact:
            return 0.0, 0.0, 0.0
        return self._side * 0.18, self._side * 0.20, self._side * 0.10    # em cima, embaixo, dos lados

    def sizeHint(self) -> QSize:
        top, bottom, sides = self._rooms()
        return QSize(int(math.ceil(self._side + 2 * sides)), int(math.ceil(self._side + top + bottom)))

    def set_side(self, side: int) -> None:
        if side != self._side:
            self._side = side
            self.setFixedSize(self.sizeHint())
            self.update()

    def side(self) -> int:
        return self._side

    def tile_top(self) -> float:
        """Distância do topo da peça ao topo do bloco (para quem alinha por ele)."""
        return self._rooms()[0]

    # animação -------------------------------------------------------------------------
    def current(self) -> Optional[str]:
        return self._next[0] if self._next else self._name

    def play(self, name: str, loop: bool = True, speed: float = 1.0) -> None:
        self._name, self._loop, self._speed, self._clock, self._done = name, loop, speed, 0.0, False
        self._next = self._hop_at = self._fade = None
        self._last = time.perf_counter()
        self.update()

    def switch(self, name: str, loop: bool = True, speed: float = 1.0) -> None:
        if self.current() == name:
            return
        if self._name is None or not self.isVisible():
            self.play(name, loop, speed)
            return
        self._next = (name, loop, speed)
        if self._hop_at is None:
            self._hop_at = time.perf_counter()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._last = time.perf_counter()
        self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _advance(self) -> None:
        now = time.perf_counter()
        step, self._last = min(0.25, now - self._last), now
        info = mascot_info(self._name) if self._name else None
        if info and not self._done:
            self._clock += step * self._speed
            if self._clock >= info["seconds"]:
                if self._loop:
                    self._clock %= info["seconds"]
                else:
                    self._clock, self._done = info["seconds"] - 1e-3, True
                    self.finished.emit(self._name)
        if self._hop_at is not None:
            progress = (now - self._hop_at) / self.HOP_SECONDS
            if self._next and progress >= self.HOP_SWAP_AT:
                self._fade = (self._name, self._clock, now)
                self._name, self._loop, self._speed = self._next
                self._clock, self._done, self._next = 0.0, False, None
            if progress >= 1.0:
                self._hop_at = None
        if self._fade and now - self._fade[2] >= self.FADE_SECONDS:
            self._fade = None
        self.update()

    def _pose(self, now: float) -> Tuple[float, float, float]:
        """(esticar na largura, esticar na altura, subida em fração do lado) do bloco agora."""
        lift = 0.016 * math.sin((now - self._born) * 1.7) + 0.016 if self._floating else 0.0   # flutua de leve
        if self._hop_at is None:
            return 1.0, 1.0, lift
        u = min(1.0, (now - self._hop_at) / self.HOP_SECONDS)
        if u < 0.28:                                   # abaixa para pegar impulso
            k = _ease(u / 0.28)
            return 1 + 0.06 * k, 1 - 0.10 * k, lift * (1 - k)
        if u < 0.62:                                   # no ar: estica na subida, volta ao normal na descida
            v = (u - 0.28) / 0.34
            arc = math.sin(math.pi * v)
            launch = 1 - min(1.0, v * 4)
            return 1 - 0.04 * arc + 0.06 * launch, 1 + 0.07 * arc - 0.10 * launch, 0.13 * arc
        w = (u - 0.62) / 0.38                          # pousa, amassa um pouco e assenta
        settle = (1 - w) ** 2 * math.cos(w * math.pi * 1.6)
        return 1 + 0.05 * settle, 1 - 0.08 * settle, lift * _ease(w)

    def _frame(self, name: Optional[str], clock: float, pixels: int) -> Optional[QPixmap]:
        info = mascot_info(name) if name else None
        frames = mascot_frames(name, pixels) if info else []
        if not frames:
            return None
        return frames[min(len(frames) - 1, int(clock * info["fps"]))]

    def paintEvent(self, _event) -> None:
        now = time.perf_counter()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor(getattr(theme, self._backdrop)))
        side = float(self._side)
        top, _bottom, _sides = self._rooms()
        sx, sy, lift = self._pose(now)
        centre_x, ground = self.width() / 2, top + side
        if not self._compact:
            # A sombra no chão: encolhe e clareia quando o bloco sobe.
            spread = 1 - min(0.5, lift * 2.6)
            shadow = QRectF(0, 0, side * 0.66 * spread * sx, side * 0.085 * spread)
            shadow.moveCenter(QPointF(centre_x, ground + side * 0.105))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, int(theme.SHADOW * spread)))
            painter.drawEllipse(shadow)
        painter.save()
        painter.translate(centre_x, ground - lift * side)     # o bloco estica e amassa a partir da base
        painter.scale(sx, sy)
        tile = QRectF(-side / 2, -side, side, side)
        shape = QPainterPath()
        shape.addRoundedRect(tile, side * TILE_ROUNDING, side * TILE_ROUNDING)
        painter.fillPath(shape, QColor(theme.TILE))
        pixels = max(16, int(round(side * self.devicePixelRatioF())))
        painter.setClipPath(shape)
        current = self._frame(self._name, self._clock, pixels)
        leaving = self._frame(self._fade[0], self._fade[1], pixels) if self._fade else None
        if leaving is not None and current is not None:
            # Fusão de verdade: a animação que sai fica inteira por baixo e a que entra vai
            # cobrindo, já sobre o branco do bloco. Duas imagens meio transparentes, uma sobre
            # a outra, deixariam o preto cinza no meio do caminho.
            mix = min(1.0, (now - self._fade[2]) / self.FADE_SECONDS)
            painter.drawPixmap(tile, leaving, QRectF(leaving.rect()))
            solid = QPixmap(current.size())
            solid.fill(QColor(theme.TILE))
            brush = QPainter(solid)
            brush.drawPixmap(0, 0, current)
            brush.end()
            painter.setOpacity(mix)
            painter.drawPixmap(tile, solid, QRectF(solid.rect()))
        elif current is not None:
            painter.drawPixmap(tile, current, QRectF(current.rect()))
        elif self._name is None:
            painter.setClipping(False)
            paint_goose(painter, tile)
        painter.setOpacity(1.0)
        painter.setClipping(False)
        if theme.TILE_BORDER != theme.TILE:
            painter.setPen(QPen(QColor(theme.TILE_BORDER), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(shape)
        painter.restore()


# ── palco ────────────────────────────────────────────────────────────────────────────────
class FrameView(QWidget):
    """O palco: a imagem que sai para os outros programas.

    Com a troca ligada, mostra o vídeo e, por cima, o selo de estado, os avisos
    e os botões de ação. Sem vídeo, mostra o que a pessoa precisa saber naquele
    momento, com o mascote: a abertura (Matrix, barra de progresso e, no fim, o
    grito), o passo a passo para começar, ou um recado simples.
    """

    intro_done = Signal()      # o grito de "terminei de carregar" acabou
    LOADING_SIDE, SMALL_SIDE = 132, 84
    CELEBRATION_SECONDS = 2.3  # o grito inteiro: fôlego, berro e bico fechando

    def __init__(self) -> None:
        super().__init__()
        self._frame = None      # mantém vivo o buffer que o QImage aponta
        self._image: Optional[QImage] = None
        self.empty_title = ""
        self.empty_text = ""
        # Passo a passo: (estado, título, explicação); estado é "done", "now" ou "todo".
        self.steps: List[Tuple[str, str, str]] = []
        # Carregamento: None = não está carregando; senão (fração de 0 a 1, ou None se não dá para estimar).
        self.loading: Optional[Tuple[Optional[float]]] = None
        self.celebrating = False
        self.mood = "matrix"    # a animação do mascote fora da abertura: parado, pilulas, dormindo, matrix
        self.badge: Optional[Tuple[str, str, str]] = None      # (texto, cor do ponto, complemento)
        self.toasts: List[Tuple[str, str]] = []                 # (texto, cor da barra)
        self.banner = ""        # faixa de instrução por cima da imagem (gravação)
        self.buttons: List[QPushButton] = []
        self._content = QRectF()
        self._mascot_spot: Optional[QPointF] = None             # onde o topo do bloco do mascote deve ficar
        self.mascot = Mascot(self.LOADING_SIDE, "STAGE", floating=True)
        self.mascot.setParent(self)
        self.mascot.play("matrix")
        self.mascot.hide()
        self._celebration = QTimer(self)
        self._celebration.setSingleShot(True)
        self._celebration.timeout.connect(self._end_celebration)
        self.setMinimumSize(520, 320)

    def show_frame(self, frame) -> None:
        height, width = frame.shape[:2]
        self._frame = frame
        self._image = QImage(frame.data, width, height, 3 * width, QImage.Format.Format_BGR888)
        self.update()

    def has_frame(self) -> bool:
        return self._image is not None

    def current_image(self) -> Optional[QImage]:
        return None if self._image is None else self._image.copy()

    def clear(self) -> None:
        self._frame = None
        self._image = None
        self.update()

    # a abertura termina com o grito ---------------------------------------------------
    def celebrate(self) -> None:
        """Os modelos carregaram: o mascote passa do Matrix para o grito, uma vez."""
        if self.celebrating:
            return
        self.celebrating = True
        self.mascot.switch("gritando", loop=False)
        self._celebration.start(int((Mascot.HOP_SECONDS * Mascot.HOP_SWAP_AT + self.CELEBRATION_SECONDS) * 1000))
        self.update()

    def _end_celebration(self) -> None:
        self.celebrating = False
        release_mascot("matrix", "gritando")
        self.intro_done.emit()

    def scream_delay_ms(self) -> int:
        """Quanto falta, a partir de ``celebrate``, para o bico abrir (a hora do som)."""
        return int((Mascot.HOP_SECONDS * Mascot.HOP_SWAP_AT + 0.42) * 1000)

    def add_button(self, button: QPushButton) -> None:
        button.setParent(self)
        self.buttons.append(button)
        self._place_buttons()

    def _place_buttons(self) -> None:
        x = self._content.right() - 12
        for button in reversed(self.buttons):
            if not button.isVisible():
                continue
            size = button.sizeHint()
            x -= size.width()
            button.setGeometry(int(x), int(self._content.top() + 12), size.width(), size.height())
            x -= 8

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_content()

    def _layout_content(self) -> None:
        area = QRectF(self.rect()).adjusted(STAGE_MARGIN, STAGE_MARGIN, -STAGE_MARGIN, -STAGE_MARGIN)
        if self._image is not None and self._image.width() > 0:
            scale = min(area.width() / self._image.width(), area.height() / self._image.height())
            w, h = self._image.width() * scale, self._image.height() * scale
            content = QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)
        else:
            content = area
        if content != self._content:
            self._content = content
            self._place_buttons()

    def _is_loading(self) -> bool:
        return self.loading is not None or self.celebrating

    def _place_mascot(self) -> None:
        """Põe o mascote onde a última pintura pediu; some quando há vídeo ou não cabe."""
        spot = None if self._image is not None else self._mascot_spot
        if spot is None:
            if self.mascot.isVisible():
                self.mascot.hide()
            return
        if not self._is_loading():
            self.mascot.switch(self.mood)
        size = self.mascot.sizeHint()
        x, y = int(round(spot.x() - size.width() / 2)), int(round(spot.y() - self.mascot.tile_top()))
        if (self.mascot.x(), self.mascot.y()) != (x, y):
            self.mascot.move(x, y)
        if not self.mascot.isVisible():
            self.mascot.show()

    def _with_mascot(self, body: float, side: int) -> Tuple[float, bool]:
        """Centraliza no palco um bloco de altura ``body`` com o mascote em cima, se couber.

        Devolve o topo do bloco (já descontado o mascote) e se ele coube."""
        self.mascot.set_side(side)
        gap = 22 + side * 0.20        # a sombra do mascote mais um respiro
        fits = side + gap + body <= self._content.height() - 24
        total = body + (side + gap if fits else 0)
        top = self._content.center().y() - total / 2
        if fits:
            self._mascot_spot = QPointF(self._content.center().x(), top)
            return top + side + gap, True
        self._mascot_spot = None
        return top, False

    def paintEvent(self, _event) -> None:
        self._layout_content()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.WINDOW))
        shape = QPainterPath()
        shape.addRoundedRect(self._content, STAGE_RADIUS, STAGE_RADIUS)
        self._mascot_spot = None
        if self._image is None:
            painter.fillPath(shape, QColor(theme.STAGE))
            painter.setPen(QPen(QColor(theme.BORDER), 1))
            painter.drawPath(shape)
            if self._is_loading():
                self._paint_loading(painter)
            elif self.steps:
                self._paint_guide(painter)
            else:
                self._paint_message(painter)
        else:
            painter.save()
            painter.setClipPath(shape)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(self._content, self._image)
            if self.banner:
                strip = QRectF(self._content.left(), self._content.top(), self._content.width(), 52)
                painter.fillRect(strip, QColor(150, 20, 20, 215))
                font = QFont("Segoe UI", 14)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(strip, Qt.AlignmentFlag.AlignCenter, self.banner)
            painter.restore()
            painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
            painter.drawPath(shape)
        if self.badge and not self.banner:
            self._paint_badge(painter)
        self._paint_toasts(painter)
        painter.end()
        self._place_mascot()

    # sem vídeo ------------------------------------------------------------------------
    def _title_font(self) -> QFont:
        font = QFont("Segoe UI", 15)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def _paint_message(self, painter: QPainter) -> None:
        width = min(460.0, self._content.width() - 80)
        left = self._content.center().x() - width / 2
        wrap = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)
        text = QFont("Segoe UI", 10)
        text_height = QFontMetricsF(text).boundingRect(QRectF(0, 0, width, 300), wrap, self.empty_text).height()
        y, _fits = self._with_mascot(34 + 8 + text_height, self.SMALL_SIDE)
        painter.setFont(self._title_font())
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(QRectF(left - 30, y, width + 60, 34), Qt.AlignmentFlag.AlignCenter, self.empty_title)
        painter.setFont(text)
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(QRectF(left, y + 42, width, text_height + 4), wrap, self.empty_text)

    def _paint_loading(self, painter: QPainter) -> None:
        """O mascote, o que está acontecendo e uma barra grossa que anda."""
        width = min(360.0, self._content.width() - 80)
        left = self._content.center().x() - width / 2
        y, _fits = self._with_mascot(34 + 6 + 40 + 16 + 10 + 28, self.LOADING_SIDE)
        painter.setFont(self._title_font())
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(QRectF(left - 60, y, width + 120, 34), Qt.AlignmentFlag.AlignCenter, self.empty_title)
        painter.setFont(QFont("Segoe UI", 10))
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(QRectF(left - 60, y + 40, width + 120, 40),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                         self.empty_text)
        track = QRectF(left, y + 96, width, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.FIELD))
        painter.drawRoundedRect(track, 5, 5)
        fraction = 1.0 if self.celebrating else (self.loading[0] if self.loading else 0.0)
        painter.setBrush(QColor(theme.BAR))
        if fraction is None:
            # Sem estimativa (a otimização da primeira vez): um trecho que vai e volta.
            phase = (math.sin(time.perf_counter() * 2.2) + 1) / 2
            chunk = width * 0.28
            painter.drawRoundedRect(QRectF(left + (width - chunk) * phase, track.top(), chunk, 10), 5, 5)
        else:
            fraction = min(1.0, max(0.0, fraction))
            painter.drawRoundedRect(QRectF(left, track.top(), max(10.0, width * fraction), 10), 5, 5)
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor(theme.FAINT))
            painter.drawText(QRectF(left, track.bottom() + 8, width, 20), Qt.AlignmentFlag.AlignCenter,
                             f"{fraction * 100:.0f}%")

    def _paint_guide(self, painter: QPainter) -> None:
        """O passo a passo de antes de iniciar: o que já está feito, o que falta."""
        width = min(470.0, self._content.width() - 80)
        left = self._content.center().x() - width / 2
        title, text = self._title_font(), QFont("Segoe UI", 10)
        step_title = QFont("Segoe UI", 10)
        step_title.setWeight(QFont.Weight.DemiBold)
        detail = QFont("Segoe UI", 9)
        wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)
        centre_wrap = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)
        text_height = QFontMetricsF(text).boundingRect(QRectF(0, 0, width, 200), centre_wrap, self.empty_text).height()
        rows = []
        for _state, name, explanation in self.steps:
            height = 20.0
            if explanation:
                height += 2 + QFontMetricsF(detail).boundingRect(QRectF(0, 0, width - 42, 200), wrap, explanation).height()
            rows.append(max(28.0, height))
        total = 34 + 6 + text_height + 26 + sum(rows) + 14 * max(0, len(rows) - 1)
        y, _fits = self._with_mascot(total, self.SMALL_SIDE)

        painter.setFont(title)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(QRectF(left - 40, y, width + 80, 34), Qt.AlignmentFlag.AlignCenter, self.empty_title)
        y += 34 + 6
        painter.setFont(text)
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(QRectF(left, y, width, text_height + 2), centre_wrap, self.empty_text)
        y += text_height + 26

        for index, ((state, name, explanation), height) in enumerate(zip(self.steps, rows)):
            circle = QRectF(left, y, 26, 26)
            if state == "done":
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(theme.GO))
                painter.drawEllipse(circle)
                painter.setPen(QPen(QColor(theme.ON_GO), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                    Qt.PenJoinStyle.RoundJoin))
                tick = QPainterPath()
                tick.moveTo(circle.left() + 7.5, circle.top() + 13.5)
                tick.lineTo(circle.left() + 11.5, circle.top() + 17.5)
                tick.lineTo(circle.left() + 18.5, circle.top() + 9.5)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(tick)
            else:
                colour = QColor(theme.TEXT if state == "now" else theme.BORDER_STRONG)
                painter.setPen(QPen(colour, 1.6))
                painter.setBrush(QColor(theme.FIELD) if state == "now" else Qt.BrushStyle.NoBrush)
                painter.drawEllipse(circle.adjusted(1, 1, -1, -1))
                number = QFont("Segoe UI", 9)
                number.setBold(True)
                painter.setFont(number)
                painter.setPen(QColor(theme.TEXT if state == "now" else theme.FAINT))
                painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(index + 1))
            painter.setFont(step_title)
            painter.setPen(QColor(theme.TEXT if state != "todo" else theme.MUTED))
            painter.drawText(QRectF(left + 42, y + 2, width - 42, 20), Qt.AlignmentFlag.AlignVCenter, name)
            if explanation:
                painter.setFont(detail)
                painter.setPen(QColor(theme.MUTED if state != "todo" else theme.FAINT))
                painter.drawText(QRectF(left + 42, y + 24, width - 42, height), wrap, explanation)
            y += height + 14

    # sobre o vídeo --------------------------------------------------------------------
    def _paint_badge(self, painter: QPainter) -> None:
        text, colour, extra = self.badge
        bold = QFont("Segoe UI", 9)
        bold.setBold(True)
        bold.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        plain = QFont("Segoe UI", 9)
        width = 14 + 8 + 8 + QFontMetricsF(bold).horizontalAdvance(text) + 14
        if extra:
            width += 10 + QFontMetricsF(plain).horizontalAdvance(extra)
        pill = QRectF(self._content.left() + 12, self._content.top() + 12, width, 30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(11, 11, 12, 200))
        painter.drawRoundedRect(pill, 15, 15)
        painter.setBrush(QColor(colour))
        painter.drawEllipse(QRectF(pill.left() + 14, pill.center().y() - 4, 8, 8))
        painter.setFont(bold)
        painter.setPen(QColor(theme.OVERLAY_TEXT))
        x = pill.left() + 30
        painter.drawText(QRectF(x, pill.top(), width, pill.height()), Qt.AlignmentFlag.AlignVCenter, text)
        if extra:
            x += QFontMetricsF(bold).horizontalAdvance(text) + 10
            painter.setFont(plain)
            painter.setPen(QColor(theme.OVERLAY_MUTED))
            painter.drawText(QRectF(x, pill.top(), width, pill.height()), Qt.AlignmentFlag.AlignVCenter, extra)

    def _paint_toasts(self, painter: QPainter) -> None:
        if not self.toasts:
            return
        font = QFont("Segoe UI", 9)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        max_width = min(560.0, self._content.width() - 24)
        bottom = self._content.bottom() - 12
        flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap
        for text, colour in reversed(self.toasts[-3:]):
            box = metrics.boundingRect(QRectF(0, 0, max_width - 30, 400), int(flags), text)
            rect = QRectF(self._content.left() + 12, bottom - box.height() - 16, box.width() + 30, box.height() + 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(11, 11, 12, 220))
            painter.drawRoundedRect(rect, 10, 10)
            painter.setBrush(QColor(colour))
            painter.drawRoundedRect(QRectF(rect.left() + 8, rect.top() + 8, 3, rect.height() - 16), 1.5, 1.5)
            painter.setPen(QColor(theme.OVERLAY_TEXT))
            painter.drawText(QRectF(rect.left() + 20, rect.top(), box.width() + 4, rect.height()), int(flags), text)
            bottom = rect.top() - 8


# ── prévia da câmera ──────────────────────────────────────────────────────────────────────
class CameraPreview(QWidget):
    """A imagem crua da câmera, pequena, dentro do cartão da câmera. Só quem usa o app vê."""

    RADIUS = 10

    def __init__(self) -> None:
        super().__init__()
        self._frame = None
        self._image: Optional[QImage] = None
        self.placeholder = ""
        self.note = "só você vê"
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumWidth(120)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return max(60, int(round(width * 9 / 16)))

    def sizeHint(self) -> QSize:
        return QSize(308, self.heightForWidth(308))

    def minimumSizeHint(self) -> QSize:
        return QSize(120, 68)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        wanted = self.heightForWidth(self.width())
        if self.height() != wanted:
            self.setFixedHeight(wanted)

    def show_frame(self, frame) -> None:
        height, width = frame.shape[:2]
        self._frame = frame
        self._image = QImage(frame.data, width, height, 3 * width, QImage.Format.Format_BGR888)
        self.update()

    def has_frame(self) -> bool:
        return self._image is not None

    def clear(self) -> None:
        if self._image is not None:
            self._frame = self._image = None
            self.update()

    def set_placeholder(self, text: str) -> None:
        if text != self.placeholder:
            self.placeholder = text
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        shape = QPainterPath()
        shape.addRoundedRect(box, self.RADIUS, self.RADIUS)
        painter.fillPath(shape, QColor(theme.WELL))
        if self._image is not None and self._image.width() > 0:
            painter.save()
            painter.setClipPath(shape)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            scale = min(box.width() / self._image.width(), box.height() / self._image.height())
            w, h = self._image.width() * scale, self._image.height() * scale
            painter.drawImage(QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h), self._image)
            painter.restore()
            if self.note:
                font = QFont("Segoe UI", 8)
                painter.setFont(font)
                width = QFontMetricsF(font).horizontalAdvance(self.note) + 16
                pill = QRectF(box.left() + 8, box.top() + 8, width, 20)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(11, 11, 12, 190))
                painter.drawRoundedRect(pill, 10, 10)
                painter.setPen(QColor(theme.OVERLAY_TEXT))
                painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, self.note)
        else:
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor(theme.FAINT))
            painter.drawText(box.adjusted(12, 8, -12, -8),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.placeholder)
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(shape)


# ── galeria de rostos ───────────────────────────────────────────────────────────────────
THUMB_PIXELS = 144   # as miniaturas são guardadas maiores que o desenho, para telas de alta densidade


def thumbnail(path: str) -> QPixmap:
    """Miniatura quadrada da foto (recorte central)."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)   # respeita a rotação EXIF
    image = reader.read()
    result = QPixmap(THUMB_PIXELS, THUMB_PIXELS)
    result.fill(Qt.GlobalColor.transparent)
    if image.isNull():
        return result
    side = min(image.width(), image.height())
    square = image.copy((image.width() - side) // 2, (image.height() - side) // 2, side, side)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawImage(QRectF(0, 0, THUMB_PIXELS, THUMB_PIXELS),
                      square.scaled(THUMB_PIXELS, THUMB_PIXELS, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
    painter.end()
    return result


class FaceTile(QAbstractButton):
    """Um quadradinho da galeria: uma foto, o "sem rosto" ou o botão de adicionar.

    Com o mouse em cima de uma foto aparece um × no canto: clicar nele tira a foto da galeria.
    """

    removed = Signal()
    CROSS = 20

    def __init__(self, parent: QWidget, kind: str, picture: Optional[QPixmap] = None) -> None:
        super().__init__(parent)
        self.kind, self._picture = kind, picture     # kind: "face", "none" ou "add"
        self.removable = kind == "face"
        self._on_cross = False
        self._cross_pressed = False
        self.setCheckable(kind != "add")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)

    def _cross(self) -> QRectF:
        return QRectF(self.width() - self.CROSS - 4, 4, self.CROSS, self.CROSS)

    def _over_cross(self, position) -> bool:
        return self.removable and self._cross().adjusted(-3, -3, 3, 3).contains(QPointF(position))

    def mouseMoveEvent(self, event) -> None:
        over = self._over_cross(event.position())
        if over != self._on_cross:
            self._on_cross = over
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._on_cross = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._over_cross(event.position()):
            self._cross_pressed = True      # o clique é no ×, não na foto
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._cross_pressed:
            self._cross_pressed = False
            if self._over_cross(event.position()):
                self.removed.emit()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        box = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        radius = max(6.0, box.width() * 0.17)
        shape = QPainterPath()
        shape.addRoundedRect(box, radius, radius)
        hover = self.underMouse() and self.isEnabled()
        if self.kind == "face":
            painter.fillPath(shape, QColor(theme.FIELD))
            if self._picture is not None:
                painter.save()
                painter.setClipPath(shape)
                painter.drawPixmap(box, self._picture, QRectF(self._picture.rect()))
                painter.restore()
        elif self.kind == "none":
            painter.fillPath(shape, QColor(theme.FIELD))
            # um rosto vazio riscado: "sem rosto"
            ink = QColor(theme.TEXT if (self.isChecked() or hover) else theme.MUTED)
            painter.setPen(QPen(ink, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = box.width() * 0.24
            centre = box.center()
            painter.drawEllipse(centre, r, r)
            painter.drawLine(QPointF(centre.x() - r * 1.25, centre.y() + r * 1.25),
                             QPointF(centre.x() + r * 1.25, centre.y() - r * 1.25))
        else:
            ink = QColor(theme.TEXT if hover else theme.MUTED)
            painter.setPen(QPen(QColor(theme.TEXT if hover else theme.BORDER_STRONG), 1.4, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(shape)
            painter.setPen(QPen(ink, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            arm = box.width() * 0.16
            painter.drawLine(QPointF(box.center().x() - arm, box.center().y()), QPointF(box.center().x() + arm, box.center().y()))
            painter.drawLine(QPointF(box.center().x(), box.center().y() - arm), QPointF(box.center().x(), box.center().y() + arm))
        if self.kind != "add":
            if self.isChecked():
                painter.setPen(QPen(QColor(theme.ACCENT), 2.6))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(self.rect()).adjusted(1.3, 1.3, -1.3, -1.3), radius + 2, radius + 2)
            elif hover:
                painter.setPen(QPen(QColor(theme.BORDER_STRONG), 1.6))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(self.rect()).adjusted(1.3, 1.3, -1.3, -1.3), radius + 2, radius + 2)
        if self.removable and hover:
            cross = self._cross()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.STOP) if self._on_cross else QColor(11, 11, 12, 215))
            painter.drawEllipse(cross)
            painter.setPen(QPen(QColor("#ffffff"), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            arm = self.CROSS * 0.2
            painter.drawLine(QPointF(cross.center().x() - arm, cross.center().y() - arm),
                             QPointF(cross.center().x() + arm, cross.center().y() + arm))
            painter.drawLine(QPointF(cross.center().x() - arm, cross.center().y() + arm),
                             QPointF(cross.center().x() + arm, cross.center().y() - arm))


class FaceGallery(QWidget):
    """As fotos de rosto já usadas, em miniaturas, mais o "sem rosto" e o botão de adicionar.

    As miniaturas se ajustam à largura disponível: sempre ``COLUMNS`` por linha,
    do tamanho que couber. Assim a galeria nunca empurra a coluna para fora.
    """

    picked = Signal(str)
    none_picked = Signal()
    add_requested = Signal()
    remove_requested = Signal(str)

    COLUMNS = 5
    GAP = 4
    SMALLEST, LARGEST = 40, 78

    def __init__(self) -> None:
        super().__init__()
        self._tiles: List[FaceTile] = []
        self._by_path: Dict[str, FaceTile] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._locked: Optional[str] = None
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _tile(self, width: int) -> int:
        return max(self.SMALLEST, min(self.LARGEST, (width - self.GAP * (self.COLUMNS - 1)) // self.COLUMNS))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        rows = max(1, math.ceil(len(self._tiles) / self.COLUMNS))
        return rows * self._tile(width) + (rows - 1) * self.GAP

    def sizeHint(self) -> QSize:
        return QSize(308, self.heightForWidth(308))

    def minimumSizeHint(self) -> QSize:
        width = self.COLUMNS * self.SMALLEST + self.GAP * (self.COLUMNS - 1)
        return QSize(width, self.heightForWidth(width))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()

    def _place(self) -> None:
        tile = self._tile(self.width())
        for index, button in enumerate(self._tiles):
            row, column = divmod(index, self.COLUMNS)
            button.setGeometry(column * (tile + self.GAP), row * (tile + self.GAP), tile, tile)

    def set_faces(self, paths: List[str], selected: Optional[str], none_selected: bool = False) -> None:
        for button in self._tiles:
            self._group.removeButton(button)
            button.hide()
            button.deleteLater()
        self._tiles, self._by_path = [], {}

        none = FaceTile(self, "none")
        none.setToolTip("Sem rosto: a câmera aparece como é, sem troca")
        none.setChecked(none_selected and not selected)
        none.clicked.connect(lambda _checked=False: self.none_picked.emit())
        self._group.addButton(none)
        self._tiles.append(none)
        for path in paths:
            tile = FaceTile(self, "face", thumbnail(path))
            tile.setChecked(bool(selected) and os.path.normcase(path) == os.path.normcase(selected))
            tile.clicked.connect(lambda _checked=False, p=path: self.picked.emit(p))
            tile.removed.connect(lambda p=path: self.remove_requested.emit(p))
            tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tile.customContextMenuRequested.connect(lambda _pos, p=path, t=tile: self._menu(p, t))
            self._group.addButton(tile)
            self._tiles.append(tile)
            self._by_path[os.path.normcase(path)] = tile
        add = FaceTile(self, "add")
        add.setToolTip("Adicionar uma foto de rosto")
        add.clicked.connect(lambda _checked=False: self.add_requested.emit())
        self._tiles.append(add)
        self._apply_lock()
        self._place()
        for button in self._tiles:
            button.show()
        self.updateGeometry()

    def set_locked(self, path: Optional[str]) -> None:
        """A foto que não pode sair da galeria agora (a que está em uso ao vivo)."""
        path = os.path.normcase(path) if path else None
        if path != self._locked:
            self._locked = path
            self._apply_lock()

    def _apply_lock(self) -> None:
        for path, tile in self._by_path.items():
            tile.removable = path != self._locked
            name = os.path.basename(path)
            tile.setToolTip(f"{name}\nEm uso agora: para tirar da galeria, pare a troca ou escolha outro rosto antes."
                            if not tile.removable else f"{name}\nO × no canto tira a foto da galeria.")
            tile.update()

    def _menu(self, path: str, tile: FaceTile) -> None:
        if not tile.removable:
            return
        menu = QMenu(self)
        remove = menu.addAction("Remover da galeria")
        if menu.exec(tile.mapToGlobal(tile.rect().center())) is remove:
            self.remove_requested.emit(path)


# ── coluna rolável ────────────────────────────────────────────────────────────────────────
class SideScroll(QScrollArea):
    """A coluna de opções: rola só na vertical, e o conteúdo tem sempre a largura visível.

    Sem isto, qualquer peça com largura mínima maior que a coluna (um nome de
    câmera comprido, por exemplo) fazia o conteúdo rolar para os lados e
    aparecer cortado. O espaço da barra de rolagem é compensado na margem, para
    os cartões não mudarem de largura quando ela aparece.
    """

    MARGIN = 16

    def __init__(self, content: QWidget) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidget(content)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        content = self.widget()
        if content is None:
            return
        visible = self.viewport().width()
        gutter = max(0, self.width() - visible)   # largura tomada pela barra de rolagem, se ela apareceu
        layout = content.layout()
        if layout is not None:
            margins = layout.contentsMargins()
            right = max(4, self.MARGIN - gutter)
            if margins.right() != right:
                layout.setContentsMargins(margins.left(), margins.top(), right, margins.bottom())
        if content.minimumWidth() != visible or content.maximumWidth() != visible:
            content.setFixedWidth(visible)

    def wheelEvent(self, event) -> None:
        if abs(event.angleDelta().x()) > abs(event.angleDelta().y()):
            event.accept()   # gesto lateral do touchpad: aqui não há para onde rolar
            return
        super().wheelEvent(event)


# ── botões ────────────────────────────────────────────────────────────────────────────────
class PrimaryButton(QAbstractButton):
    """O botão de iniciar e parar: um título e, embaixo, menor, o que mais ele faz."""

    def __init__(self) -> None:
        super().__init__()
        self._title, self._subtitle, self._stop = "", "", False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_text(self, title: str, subtitle: str, stop: bool) -> None:
        if (title, subtitle, stop) != (self._title, self._subtitle, self._stop):
            self._title, self._subtitle, self._stop = title, subtitle, stop
            self.setAccessibleName(f"{title} {subtitle}".strip())
            self.updateGeometry()
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(200, 62 if self._subtitle else 50)

    def minimumSizeHint(self) -> QSize:
        return QSize(120, self.sizeHint().height())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = QRectF(self.rect())
        hover = self.underMouse() and self.isEnabled()
        if not self.isEnabled():
            fill, title, subtitle = QColor(theme.FIELD), QColor(theme.FAINT), QColor(theme.FAINT)
        elif self._stop:
            fill = QColor(theme.STOP_HOVER if hover else theme.STOP)
            title, subtitle = QColor("#ffffff"), QColor(255, 255, 255, 215)
        else:
            fill = QColor(theme.GO_HOVER if hover else theme.GO)
            title = QColor(theme.ON_GO)
            subtitle = QColor(title)
            subtitle.setAlpha(205)
        if self.isDown():
            fill = fill.darker(112)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(box, theme.RADIUS, theme.RADIUS)
        big = QFont("Segoe UI", 12)
        big.setBold(True)
        small = QFont("Segoe UI", 9)
        if not self._subtitle:
            painter.setFont(big)
            painter.setPen(title)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._title)
            return
        painter.setFont(big)
        painter.setPen(title)
        painter.drawText(QRectF(box.left() + 8, box.top() + 9, box.width() - 16, 24), Qt.AlignmentFlag.AlignCenter,
                         self._title)
        painter.setFont(small)
        painter.setPen(subtitle)
        painter.drawText(QRectF(box.left() + 8, box.top() + 34, box.width() - 16, 18), Qt.AlignmentFlag.AlignCenter,
                         self._subtitle)


class IconButton(QAbstractButton):
    """Um botão só com um desenho: a engrenagem das configurações ou a seta de voltar."""

    def __init__(self, kind: str, tip: str) -> None:
        super().__init__()
        self._kind = kind            # "gear" ou "back"
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip(tip)
        self.setAccessibleName(tip)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        hover = self.underMouse()
        if hover or self.isDown():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.SELECTED if self.isDown() else theme.FIELD))
            painter.drawRoundedRect(QRectF(self.rect()), 9, 9)
        ink = QColor(theme.TEXT if hover else theme.MUTED)
        centre = QPointF(self.width() / 2, self.height() / 2)
        if self._kind == "gear":
            painter.setPen(QPen(ink, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for tooth in range(8):                      # os dentes
                angle = tooth * math.pi / 4
                direction = QPointF(math.cos(angle), math.sin(angle))
                painter.drawLine(centre + direction * 6.6, centre + direction * 8.4)
            painter.setPen(QPen(ink, 1.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, 6.0, 6.0)
            painter.drawEllipse(centre, 2.3, 2.3)
        else:
            painter.setPen(QPen(ink, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(QPointF(centre.x() - 6.5, centre.y()), QPointF(centre.x() + 6.5, centre.y()))
            head = QPainterPath()
            head.moveTo(centre.x() - 1.5, centre.y() - 5.5)
            head.lineTo(centre.x() - 7, centre.y())
            head.lineTo(centre.x() - 1.5, centre.y() + 5.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(head)


# ── controles ───────────────────────────────────────────────────────────────────────────
class Switch(QAbstractButton):
    """Interruptor deslizante."""

    def __init__(self, checked: bool = False) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._position = 1.0 if checked else 0.0
        self.setChecked(checked)
        self._slide = QPropertyAnimation(self, b"position", self)
        self._slide.setDuration(140)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, checked: bool) -> None:
        self._slide.stop()
        self._slide.setStartValue(self._position)
        self._slide.setEndValue(1.0 if checked else 0.0)
        self._slide.start()

    def _get_position(self) -> float:
        return self._position

    def _set_position(self, value: float) -> None:
        self._position = value
        self.update()

    position = Property(float, _get_position, _set_position)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        off, on = QColor(theme.SWITCH_OFF), QColor(theme.ACCENT)
        t = self._position
        track = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            track.setAlpha(90)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        knob = QColor(theme.KNOB)
        knob.setAlpha(255 if self.isEnabled() else 120)
        painter.setBrush(knob)
        painter.drawEllipse(QRectF(3 + 18 * t, 3, 16, 16))


class SwitchRow(QWidget):
    """Um interruptor com rótulo e, opcionalmente, uma linha de explicação embaixo."""

    toggled = Signal(bool)

    def __init__(self, label: str, checked: bool = False, hint: str = "") -> None:
        super().__init__()
        self.switch = Switch(checked)
        self.switch.toggled.connect(self.toggled.emit)
        self.label = QLabel(label)
        self.label.setObjectName("rowLabel")
        self.label.setWordWrap(True)
        self.hint = QLabel(hint)
        self.hint.setObjectName("rowHint")
        self.hint.setWordWrap(True)
        self.hint.setVisible(bool(hint))
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        top.addWidget(self.label, 1)
        top.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addWidget(self.hint)

    def set_hint(self, text: str, error: bool = False) -> None:
        name = "noteError" if error else "rowHint"
        if self.hint.objectName() != name:
            self.hint.setObjectName(name)
            self.hint.style().unpolish(self.hint)
            self.hint.style().polish(self.hint)
        self.hint.setText(text)
        self.hint.setVisible(bool(text))

    def is_on(self) -> bool:
        return self.switch.isChecked()

    def set_on(self, value: bool, silent: bool = False) -> None:
        if silent:
            self.switch.blockSignals(True)
        self.switch.setChecked(value)
        if silent:
            self.switch.blockSignals(False)
            self.switch._set_position(1.0 if value else 0.0)

    def mousePressEvent(self, event) -> None:   # clicar no rótulo também alterna
        if self.switch.isEnabled() and event.position().y() <= self.label.geometry().bottom() + 4:
            self.switch.toggle()


class Segmented(QFrame):
    """Escolha entre poucas opções, lado a lado."""

    changed = Signal(object)

    def __init__(self, options: List[Tuple[object, str]], current: object) -> None:
        super().__init__()
        self.setObjectName("segmented")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._values = {}
        for value, label in options:
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(value == current)
            button.clicked.connect(lambda _checked=False, v=value: self.changed.emit(v))
            self._group.addButton(button)
            self._values[button] = value
            layout.addWidget(button, 1)
        if self._group.checkedButton() is None and self._group.buttons():
            self._group.buttons()[0].setChecked(True)

    def value(self):
        return self._values.get(self._group.checkedButton())


class SliderRow(QWidget):
    """Um ajuste de 0 a 100, com o valor à direita."""

    changed = Signal(int)

    def __init__(self, label: str, value: int, hint: str = "") -> None:
        super().__init__()
        self.title = QLabel(label)
        self.title.setObjectName("rowLabel")
        self.number = QLabel()
        self.number.setObjectName("value")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(value)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.setFixedHeight(22)   # sem isto, numa coluna apertada o Qt amassa o botão do controle
        self.slider.valueChanged.connect(self._on_change)
        if hint:
            self.setToolTip(hint)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.title, 1)
        top.addWidget(self.number, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(top)
        layout.addWidget(self.slider)
        self._on_change(value, announce=False)

    def _on_change(self, value: int, announce: bool = True) -> None:
        self.number.setText(f"{value}%")
        if announce:
            self.changed.emit(value)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int) -> None:
        self.slider.setValue(value)


class Card(QFrame):
    """Um bloco da barra lateral, com título."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(14, 12, 14, 14)
        self.body.setSpacing(10)
        heading = QLabel(title.upper())
        heading.setObjectName("cardTitle")
        self.body.addWidget(heading)

    def add(self, widget: QWidget) -> None:
        self.body.addWidget(widget)
