"""Peças da janela: palco do resultado, prévia da câmera, galeria de rostos e controles."""
from __future__ import annotations

import math
import os
import time
from typing import List, Optional, Tuple

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QIcon, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QToolButton, QVBoxLayout, QWidget,
)

from app.ui import theme

STAGE_MARGIN = 18
STAGE_RADIUS = 16


# ── marca ────────────────────────────────────────────────────────────────────────────────
LOGO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "morpho_simbolo.svg")
# O desenho ocupa só o miolo do arquivo (512 x 512); este recorte tira a margem,
# para o símbolo não ficar miúdo nos tamanhos pequenos.
LOGO_VIEW = QRectF(64, 64, 384, 384)
_logo = None


def paint_logo(painter: QPainter, box: QRectF) -> None:
    """O símbolo do Morpho, desenhado dentro de ``box``."""
    global _logo
    if _logo is None:
        from PySide6.QtSvg import QSvgRenderer

        _logo = QSvgRenderer(LOGO_FILE)
        if _logo.isValid():
            _logo.setViewBox(LOGO_VIEW)
    if not _logo.isValid():
        return
    side = min(box.width(), box.height())
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _logo.render(painter, QRectF(box.center().x() - side / 2, box.center().y() - side / 2, side, side))
    painter.restore()


def app_icon() -> QIcon:
    """O ícone da janela e da barra de tarefas: o símbolo sobre um fundo azul."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        tile = QPixmap(size, size)
        tile.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tile)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        shade = QLinearGradient(QPointF(0, 0), QPointF(size, size))
        shade.setColorAt(0.0, QColor("#8fa9ff"))
        shade.setColorAt(1.0, QColor("#4f6ef0"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shade)
        painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
        paint_logo(painter, QRectF(size * 0.14, size * 0.14, size * 0.72, size * 0.72))
        painter.end()
        icon.addPixmap(tile)
    return icon


class Logo(QWidget):
    def __init__(self, size: int = 22) -> None:
        super().__init__()
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        paint_logo(painter, QRectF(self.rect()))


# ── palco ────────────────────────────────────────────────────────────────────────────────
class FrameView(QWidget):
    """O palco: a imagem que sai para os outros programas.

    Com a troca ligada, mostra o vídeo e, por cima, o selo de estado, os avisos
    e os botões de ação. Sem vídeo, mostra o que a pessoa precisa saber naquele
    momento: o carregamento (com barra de progresso), o passo a passo para
    começar, ou um recado simples.
    """

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
        self.badge: Optional[Tuple[str, str, str]] = None      # (texto, cor do ponto, complemento)
        self.toasts: List[Tuple[str, str]] = []                 # (texto, cor da barra)
        self.banner = ""        # faixa de instrução por cima da imagem (gravação)
        self.buttons: List[QPushButton] = []
        self._content = QRectF()
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

    def paintEvent(self, _event) -> None:
        self._layout_content()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.WINDOW))
        shape = QPainterPath()
        shape.addRoundedRect(self._content, STAGE_RADIUS, STAGE_RADIUS)
        if self._image is None:
            painter.fillPath(shape, QColor(theme.STAGE))
            painter.setPen(QPen(QColor(theme.BORDER), 1))
            painter.drawPath(shape)
            if self.loading is not None:
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

    # sem vídeo ------------------------------------------------------------------------
    def _title_font(self) -> QFont:
        font = QFont("Segoe UI", 15)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def _paint_message(self, painter: QPainter) -> None:
        centre = self._content.center()
        painter.setFont(self._title_font())
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(QRectF(self._content.left() + 40, centre.y() - 44, self._content.width() - 80, 34),
                         Qt.AlignmentFlag.AlignCenter, self.empty_title)
        painter.setFont(QFont("Segoe UI", 10))
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(QRectF(self._content.left() + 60, centre.y() - 6, self._content.width() - 120, 70),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                         self.empty_text)

    def _paint_loading(self, painter: QPainter) -> None:
        """Marca, o que está acontecendo e uma barra que anda: a espera fica com cara de espera curta."""
        centre = self._content.center()
        width = min(360.0, self._content.width() - 80)
        left = centre.x() - width / 2
        paint_logo(painter, QRectF(centre.x() - 32, centre.y() - 128, 64, 64))
        painter.setFont(self._title_font())
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(QRectF(left - 60, centre.y() - 46, width + 120, 34), Qt.AlignmentFlag.AlignCenter,
                         self.empty_title)
        painter.setFont(QFont("Segoe UI", 10))
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(QRectF(left - 60, centre.y() - 8, width + 120, 44),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                         self.empty_text)
        track = QRectF(left, centre.y() + 50, width, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.FIELD))
        painter.drawRoundedRect(track, 3, 3)
        fraction = self.loading[0]
        painter.setBrush(QColor(theme.ACCENT))
        if fraction is None:
            # Sem estimativa (a otimização da primeira vez): um trecho que vai e volta.
            phase = (math.sin(time.perf_counter() * 2.2) + 1) / 2
            chunk = width * 0.28
            painter.drawRoundedRect(QRectF(left + (width - chunk) * phase, track.top(), chunk, 6), 3, 3)
        else:
            fraction = min(1.0, max(0.0, fraction))
            painter.drawRoundedRect(QRectF(left, track.top(), max(6.0, width * fraction), 6), 3, 3)
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
        y = self._content.center().y() - total / 2

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
                painter.setPen(QPen(QColor("#06210f"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                    Qt.PenJoinStyle.RoundJoin))
                tick = QPainterPath()
                tick.moveTo(circle.left() + 7.5, circle.top() + 13.5)
                tick.lineTo(circle.left() + 11.5, circle.top() + 17.5)
                tick.lineTo(circle.left() + 18.5, circle.top() + 9.5)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(tick)
            else:
                colour = QColor(theme.ACCENT if state == "now" else theme.BORDER_STRONG)
                painter.setPen(QPen(colour, 1.6))
                painter.setBrush(QColor(124, 156, 255, 36) if state == "now" else Qt.BrushStyle.NoBrush)
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
        painter.setBrush(QColor(14, 16, 20, 200))
        painter.drawRoundedRect(pill, 15, 15)
        painter.setBrush(QColor(colour))
        painter.drawEllipse(QRectF(pill.left() + 14, pill.center().y() - 4, 8, 8))
        painter.setFont(bold)
        painter.setPen(QColor(theme.TEXT))
        x = pill.left() + 30
        painter.drawText(QRectF(x, pill.top(), width, pill.height()), Qt.AlignmentFlag.AlignVCenter, text)
        if extra:
            x += QFontMetricsF(bold).horizontalAdvance(text) + 10
            painter.setFont(plain)
            painter.setPen(QColor(theme.MUTED))
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
            painter.setBrush(QColor(14, 16, 20, 214))
            painter.drawRoundedRect(rect, 10, 10)
            painter.setBrush(QColor(colour))
            painter.drawRoundedRect(QRectF(rect.left() + 8, rect.top() + 8, 3, rect.height() - 16), 1.5, 1.5)
            painter.setPen(QColor(theme.TEXT))
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
        painter.fillPath(shape, QColor("#0d0f13"))
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
                painter.setBrush(QColor(14, 16, 20, 190))
                painter.drawRoundedRect(pill, 10, 10)
                painter.setPen(QColor(theme.TEXT))
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
    """Miniatura quadrada da foto (recorte central), com cantos arredondados."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)   # respeita a rotação EXIF
    image = reader.read()
    result = QPixmap(THUMB_PIXELS, THUMB_PIXELS)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    shape = QPainterPath()
    shape.addRoundedRect(QRectF(0, 0, THUMB_PIXELS, THUMB_PIXELS), THUMB_PIXELS * 0.15, THUMB_PIXELS * 0.15)
    painter.setClipPath(shape)
    if image.isNull():
        painter.fillRect(0, 0, THUMB_PIXELS, THUMB_PIXELS, QColor(theme.FIELD))
    else:
        side = min(image.width(), image.height())
        square = image.copy((image.width() - side) // 2, (image.height() - side) // 2, side, side)
        painter.drawImage(QRectF(0, 0, THUMB_PIXELS, THUMB_PIXELS),
                          square.scaled(THUMB_PIXELS, THUMB_PIXELS, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
    painter.end()
    return result


class FaceGallery(QWidget):
    """As fotos de rosto já usadas, em miniaturas, mais o botão de adicionar.

    As miniaturas se ajustam à largura disponível: sempre ``COLUMNS`` por linha,
    do tamanho que couber. Assim a galeria nunca empurra a coluna para fora.
    """

    picked = Signal(str)
    add_requested = Signal()
    remove_requested = Signal(str)

    COLUMNS = 5
    GAP = 6
    SMALLEST, LARGEST = 40, 76

    def __init__(self) -> None:
        super().__init__()
        self._tiles: List[QToolButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
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
            button.setIconSize(QSize(tile - 8, tile - 8))

    def set_faces(self, paths: List[str], selected: Optional[str]) -> None:
        for button in self._tiles:
            self._group.removeButton(button)
            button.deleteLater()
        self._tiles = []
        for path in paths:
            tile = QToolButton(self)
            tile.setObjectName("face")
            tile.setCheckable(True)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setIcon(QIcon(thumbnail(path)))
            tile.setToolTip(f"{os.path.basename(path)}\nBotão direito: remover")
            tile.setChecked(bool(selected) and os.path.normcase(path) == os.path.normcase(selected))
            tile.clicked.connect(lambda _checked=False, p=path: self.picked.emit(p))
            tile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tile.customContextMenuRequested.connect(lambda _pos, p=path, t=tile: self._menu(p, t))
            self._group.addButton(tile)
            self._tiles.append(tile)
        add = QToolButton(self)
        add.setObjectName("addFace")
        add.setText("+")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setToolTip("Escolher uma foto de rosto")
        add.clicked.connect(self.add_requested.emit)
        self._tiles.append(add)
        self._place()
        for button in self._tiles:
            button.show()
        self.updateGeometry()

    def _menu(self, path: str, tile: QToolButton) -> None:
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


# ── botão principal ───────────────────────────────────────────────────────────────────────
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
            title, subtitle = QColor("#ffffff"), QColor(255, 255, 255, 205)
        else:
            fill = QColor(theme.GO_HOVER if hover else theme.GO)
            title, subtitle = QColor("#06210f"), QColor(6, 33, 15, 200)
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
        off, on = QColor("#3a4152"), QColor(theme.ACCENT)
        t = self._position
        track = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            track.setAlpha(90)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        painter.setBrush(QColor(255, 255, 255, 255 if self.isEnabled() else 120))
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
        self.hint = QLabel(hint)
        self.hint.setObjectName("rowHint")
        self.hint.setWordWrap(True)
        self.hint.setVisible(bool(hint))
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
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


class CollapsibleCard(QFrame):
    """Um bloco que abre e fecha ao clicar no título."""

    toggled = Signal(bool)

    def __init__(self, title: str, opened: bool) -> None:
        super().__init__()
        self.setObjectName("card")
        self._title = title.upper()
        self.header = QPushButton()
        self.header.setObjectName("cardToggle")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.clicked.connect(lambda: self.set_open(not self._content.isVisible()))
        self._content = QWidget()
        self.body = QVBoxLayout(self._content)
        self.body.setContentsMargins(0, 4, 0, 2)
        self.body.setSpacing(12)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(self.header)
        layout.addWidget(self._content)
        self.set_open(opened, announce=False)

    def set_open(self, opened: bool, announce: bool = True) -> None:
        self._content.setVisible(opened)
        self.header.setText(("▾  " if opened else "▸  ") + self._title)
        if announce:
            self.toggled.emit(opened)

    def add(self, widget: QWidget) -> None:
        self.body.addWidget(widget)
