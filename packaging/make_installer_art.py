"""Gera as imagens do instalador em ``installer/arte``.

    <python do motor> packaging/make_installer_art.py

- ``lateral.bmp``: a faixa escura das telas de boas-vindas e de conclusão, com o ganso no
  bloco branco e o nome do app.
- ``ganso-NN.bmp``: os quadros da animação "Parado" do mascote, para o canto de cima das
  outras telas (fundo branco, então sem bloco). O instalador troca um pelo outro com um
  temporizador (``[Code]`` em ``installer/morpho.iss``); o número de quadros que ele espera
  é o que este programa grava em ``arte/quadros.iss``.

As imagens ficam no repositório; só é preciso rodar de novo se o mascote mudar.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402

ART = os.path.join(HERE, "installer", "arte")
# A faixa lateral tem 164 x 314 na tela comum; esta é a medida para telas com 250% de escala,
# e o instalador reduz para as outras.
SIDE_SIZE = (410, 797)
SIDE_BACKGROUND = "#0b0b0c"
# O canto de cima tem 55 x 55 na tela comum (o instalador também ajusta o tamanho).
SMALL = 144
SMALL_FPS = 12           # metade dos quadros do mascote: mais leve e ainda fluido


def save_bmp(image: QImage, name: str) -> str:
    path = os.path.join(ART, name)
    if not image.convertToFormat(QImage.Format.Format_RGB888).save(path, "BMP"):
        raise SystemExit(f"Não consegui gravar {path}")
    return path


def side_image() -> QImage:
    from app.ui.widgets import paint_tile

    width, height = SIDE_SIZE
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(SIDE_BACKGROUND))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    tile = width * 0.56
    top = height * 0.30
    paint_tile(painter, QRectF((width - tile) / 2, top, tile, tile))
    font = QFont("Segoe UI")
    font.setPixelSize(int(width * 0.135))
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor("#f3f3f4"))
    painter.drawText(QRectF(0, top + tile + height * 0.035, width, height * 0.1),
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "Morpho")
    painter.end()
    return image


def small_frames() -> list:
    from app.ui.widgets import MASCOT_DIR, mascot_info

    info = mascot_info("parado")
    sheet = QImage(os.path.join(MASCOT_DIR, "parado.png"))
    if not info or sheet.isNull():
        raise SystemExit("Não achei a animação “parado” do mascote (rode packaging/make_mascot.py).")
    size, columns, step = info["size"], info["columns"], max(1, round(info["fps"] / SMALL_FPS))
    frames = []
    for index in range(0, info["frames"], step):
        cell = sheet.copy((index % columns) * size, (index // columns) * size, size, size)
        frame = QImage(SMALL, SMALL, QImage.Format.Format_RGB32)
        frame.fill(QColor("#ffffff"))
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(QRectF(0, 0, SMALL, SMALL), cell)
        painter.end()
        frames.append(frame)
    return frames, round(1000 * step / info["fps"])


def main() -> int:
    app = QGuiApplication(sys.argv[:1])   # noqa: F841  (o desenho precisa de um app Qt vivo)
    os.makedirs(ART, exist_ok=True)
    for name in os.listdir(ART):
        if name.startswith("ganso-") and name.endswith(".bmp"):
            os.remove(os.path.join(ART, name))
    save_bmp(side_image(), "lateral.bmp")
    frames, interval = small_frames()
    for index, frame in enumerate(frames):
        save_bmp(frame, f"ganso-{index:02d}.bmp")
    with open(os.path.join(ART, "quadros.iss"), "w", encoding="ascii", newline="\r\n") as f:
        f.write("; Gerado por packaging\\make_installer_art.py: quantos quadros tem a animacao do canto\n")
        f.write("; e de quantos em quantos milissegundos trocar.\n")
        f.write(f"#define GooseFrames {len(frames)}\n#define GooseInterval {interval}\n")
    total = sum(os.path.getsize(os.path.join(ART, name)) for name in os.listdir(ART))
    print(f"{ART}: lateral.bmp {SIDE_SIZE[0]}x{SIDE_SIZE[1]}, {len(frames)} quadros de {SMALL}x{SMALL} "
          f"a cada {interval} ms, {total / 2**20:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
