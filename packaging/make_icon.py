"""Gera o ícone do Morpho.exe (``launcher/morpho.ico``) a partir do símbolo do app.

    <python do motor> packaging/make_icon.py

O ícone é o mesmo da janela: o símbolo branco sobre o fundo azul, em vários
tamanhos dentro de um só arquivo.
"""
from __future__ import annotations

import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication(sys.argv[:1])   # noqa: F841  (o desenho precisa de um app Qt vivo)
    from app.ui.widgets import app_icon

    icon = app_icon()
    images = []
    for size in SIZES:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        icon.pixmap(size, size).toImage().save(buffer, "PNG")
        images.append(bytes(buffer.data()))
    # Arquivo .ico: cabeçalho, uma entrada por tamanho, e as imagens (PNG) em seguida.
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = len(header) + 16 * len(SIZES)
    entries = b""
    for size, data in zip(SIZES, images):
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    target = os.path.join(HERE, "launcher", "morpho.ico")
    with open(target, "wb") as f:
        f.write(header + entries + b"".join(images))
    print(f"{target}: {os.path.getsize(target)} bytes, tamanhos {SIZES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
