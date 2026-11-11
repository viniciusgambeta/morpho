"""Prepara as imagens da página a partir das capturas do app e do diagnóstico.

    <python do motor> site/tools/make_assets.py PASTA_DAS_CAPTURAS

Espera na pasta: antes.png e depois.png (o mesmo quadro, sem e com a troca), app_ao_vivo.png
e diagnostico.png. Grava em site/assets as versões leves (WebP), o ícone e a imagem de
compartilhamento (og.png).
"""
from __future__ import annotations

import os
import shutil
import sys

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
PROJECT = os.path.dirname(SITE)
ASSETS = os.path.join(SITE, "assets")
sys.path.insert(0, PROJECT)


def webp(source: str, name: str, width: int | None = None, quality: int = 86) -> None:
    image = cv2.imread(source, cv2.IMREAD_UNCHANGED)
    assert image is not None, source
    if width and image.shape[1] > width:
        height = round(image.shape[0] * width / image.shape[1])
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    target = os.path.join(ASSETS, name)
    cv2.imwrite(target, image, [cv2.IMWRITE_WEBP_QUALITY, quality])
    print(f"{name}: {image.shape[1]}x{image.shape[0]}, {os.path.getsize(target) // 1024} KB")


def og(captures: str) -> None:
    """A imagem que aparece quando o link é compartilhado (1200 x 630)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

    app = QGuiApplication(sys.argv[:1])   # noqa: F841
    from app.ui.widgets import paint_logo

    image = QImage(1200, 630, QImage.Format.Format_RGB32)
    image.fill(QColor("#0a0c10"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    glow = QLinearGradient(0, 0, 1200, 630)
    glow.setColorAt(0.0, QColor(124, 156, 255, 46))
    glow.setColorAt(0.6, QColor(10, 12, 16, 0))
    painter.fillRect(0, 0, 1200, 630, glow)
    photo = QImage(os.path.join(captures, "depois.png"))
    frame = QRectF(620, 95, 520, 440)
    shape = QPainterPath()
    shape.addRoundedRect(frame, 26, 26)
    painter.save()
    painter.setClipPath(shape)
    side = photo.height()
    painter.drawImage(frame, photo, QRectF((photo.width() - side * 520 / 440) / 2, 0, side * 520 / 440, side))
    painter.restore()
    painter.setPen(QColor(255, 255, 255, 40))
    painter.drawPath(shape)
    tile = QRectF(70, 150, 76, 76)
    tile_shape = QPainterPath()
    tile_shape.addRoundedRect(tile, 18, 18)
    shade = QLinearGradient(tile.topLeft(), tile.bottomRight())
    shade.setColorAt(0, QColor("#8fa9ff"))
    shade.setColorAt(1, QColor("#4f6ef0"))
    painter.fillPath(tile_shape, shade)
    paint_logo(painter, tile.adjusted(11, 11, -11, -11))
    font = QFont("Segoe UI", 30)
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor("#eceef4"))
    painter.drawText(QRectF(166, 150, 400, 76), Qt.AlignmentFlag.AlignVCenter, "Morpho")
    font = QFont("Segoe UI", 40)
    font.setWeight(QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(QRectF(70, 262, 520, 170), Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                     "Troque de rosto ao vivo, na sua webcam.")
    painter.setFont(QFont("Segoe UI", 19))
    painter.setPen(QColor("#9aa3b5"))
    painter.drawText(QRectF(70, 446, 520, 40), Qt.AlignmentFlag.AlignLeft, "Gratuito · Windows · código aberto")
    painter.end()
    image.save(os.path.join(ASSETS, "og.png"))
    print("og.png: 1200x630")


def main() -> int:
    captures = os.path.abspath(sys.argv[1])
    os.makedirs(ASSETS, exist_ok=True)
    webp(os.path.join(captures, "antes.png"), "antes.webp", 1280, 84)
    webp(os.path.join(captures, "depois.png"), "depois.webp", 1280, 84)
    webp(os.path.join(captures, "app_ao_vivo.png"), "app.webp", None, 88)
    webp(os.path.join(captures, "diagnostico.png"), "diagnostico.webp", 1400, 90)
    shutil.copyfile(os.path.join(PROJECT, "app", "ui", "assets", "morpho_simbolo.svg"), os.path.join(ASSETS, "logo.svg"))
    og(captures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
