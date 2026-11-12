"""Prepara as imagens fixas da página: o símbolo, o ícone da aba, a imagem de compartilhamento
e, se houver, as capturas do app e do diagnóstico.

    <python do motor> site/tools/make_assets.py [PASTA_DAS_CAPTURAS]

O símbolo (o ganso de óculos) vem de ``mascote/ganso.svg`` e é a única fonte: daqui saem
``assets/logo.svg``, ``favicon.svg``, ``assets/og.png`` e o desenho embutido no topo de
``index.html`` e ``faq.html``. Em fundo escuro o símbolo vai sempre dentro de um bloco branco
de cantos arredondados; por isso o ícone da aba já traz o bloco.

O ícone da aba sai também nos formatos que o SVG não cobre: ``favicon.ico`` (16, 32 e 48, que
é o endereço que navegadores e buscadores pedem por conta própria), ``apple-touch-icon.png``
(180, quadrado cheio: o iPhone arredonda sozinho) e ``icon-192.png``.

Com a pasta de capturas (app_ao_vivo.png e diagnostico.png), grava também as versões leves
delas. As imagens e os vídeos da demonstração são feitos por ``make_demo_video.py``.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
PROJECT = os.path.dirname(SITE)
ASSETS = os.path.join(SITE, "assets")
MARK = os.path.join(PROJECT, "mascote", "ganso.svg")
# Onde o desenho fica dentro do quadro de 512 x 512 do arquivo: x, y, largura, altura.
MARK_BOX = (70, 134, 372, 286)
# O recorte quadrado do ícone (o ganso no bloco branco), tirado da imagem de referência dele:
# o desenho ocupa 80% da largura e fica um pouco abaixo do centro, com mais folga em cima.
TILE_BOX = (30.5, 29, 451, 451)
PAGES = ("index.html", "faq.html")


def mark_paths() -> str:
    with open(MARK, encoding="utf-8") as f:
        return "".join(re.findall(r"<path[^>]*/>", f.read()))


def write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"{os.path.relpath(path, SITE)}: {len(text) / 1024:.1f} KB")


def logos() -> None:
    paths = mark_paths()
    box = " ".join(str(v) for v in MARK_BOX)
    write(os.path.join(ASSETS, "logo.svg"),
          f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{box}" role="img" aria-label="Morpho">{paths}</svg>\n')
    tile = " ".join(f"{v:g}" for v in TILE_BOX)
    write(os.path.join(SITE, "favicon.svg"),
          f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{tile}">'
          f'<rect x="{TILE_BOX[0]:g}" y="{TILE_BOX[1]:g}" width="{TILE_BOX[2]:g}" height="{TILE_BOX[3]:g}" '
          f'rx="{TILE_BOX[2] * 0.235:g}" fill="#fff"/>{paths}</svg>\n')
    # Nas páginas o preto do desenho segue a cor do texto; o branco do bico e dos reflexos fica.
    inked = paths.replace('fill="#000"', 'fill="currentColor"')
    # "morpho" é o desenho justo (menu, rodapé); "morpho-tile" é o recorte para o bloco branco.
    symbol = (f'<symbol id="morpho" viewBox="{box}">{inked}</symbol>'
              f'<symbol id="morpho-tile" viewBox="{tile}">{inked}</symbol>')
    for name in PAGES:
        path = os.path.join(SITE, name)
        with open(path, encoding="utf-8") as f:
            page = f.read()
        changed, count = re.subn(r'<symbol id="morpho".*?</symbol>(<symbol id="morpho-tile".*?</symbol>)?',
                                 lambda _: symbol, page, flags=re.S)
        if count != 1:
            raise SystemExit(f"Não achei o símbolo em {name}.")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(changed)
        print(f"{name}: símbolo atualizado")


def icons() -> None:
    """O ícone da aba em .ico e em PNG, desenhado a partir de ``favicon.svg``."""
    import struct

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])   # noqa: F841
    renderer = QSvgRenderer(os.path.join(SITE, "favicon.svg"))

    def draw(size: int, square: bool = False) -> QImage:
        # Desenha grande e reduz: os tamanhos pequenos saem mais limpos assim.
        big = max(size * 4, 256)
        image = QImage(big, big, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ffffff") if square else Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, big, big))
        painter.end()
        return image.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def png(image: QImage) -> bytes:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        return bytes(data)

    sizes = (16, 32, 48)
    images = [png(draw(size)) for size in sizes]
    offset = 6 + 16 * len(sizes)
    ico = struct.pack("<HHH", 0, 1, len(sizes))
    for size, data in zip(sizes, images):
        ico += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(os.path.join(SITE, "favicon.ico"), "wb") as f:
        f.write(ico + b"".join(images))
    print(f"favicon.ico: {', '.join(str(size) for size in sizes)} px, {offset / 1024:.1f} KB")
    for name, size, square in (("apple-touch-icon.png", 180, True), ("icon-192.png", 192, False)):
        draw(size, square).save(os.path.join(SITE, name))
        print(f"{name}: {size}x{size}")


def og() -> None:
    """A imagem que aparece quando o link é compartilhado (1200 x 630): símbolo, nome e chamada."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])   # noqa: F841
    # Sem tela o Qt não enxerga as fontes do Windows: sem isto o texto sai em quadradinhos.
    fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in ("segoeui.ttf", "segoeuib.ttf"):
        if QFontDatabase.addApplicationFont(os.path.join(fonts, name)) < 0:
            raise SystemExit(f"Não consegui carregar a fonte {name}.")
    image = QImage(1200, 630, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    width = 300.0
    height = width * MARK_BOX[3] / MARK_BOX[2]
    QSvgRenderer(os.path.join(ASSETS, "logo.svg")).render(painter, QRectF((1200 - width) / 2, 78, width, height))
    font = QFont("Segoe UI", 62)
    font.setWeight(QFont.Weight.Bold)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 96)
    painter.setFont(font)
    painter.setPen(QColor("#1d1d1f"))
    painter.drawText(QRectF(0, 322, 1200, 110), Qt.AlignmentFlag.AlignCenter, "Morpho")
    font = QFont("Segoe UI", 27)
    painter.setFont(font)
    painter.setPen(QColor("#6e6e73"))
    painter.drawText(QRectF(0, 440, 1200, 56), Qt.AlignmentFlag.AlignCenter, "Troque de rosto ao vivo, na sua webcam.")
    painter.setFont(QFont("Segoe UI", 17))
    painter.setPen(QColor("#86868b"))
    painter.drawText(QRectF(0, 528, 1200, 40), Qt.AlignmentFlag.AlignCenter,
                     "Gratuito · Windows com placa NVIDIA · código aberto")
    painter.end()
    image.save(os.path.join(ASSETS, "og.png"))
    print("assets/og.png: 1200x630")


def webp(source: str, name: str, width: int | None = None, quality: int = 86) -> None:
    import cv2

    image = cv2.imread(source, cv2.IMREAD_UNCHANGED)
    assert image is not None, source
    if width and image.shape[1] > width:
        height = round(image.shape[0] * width / image.shape[1])
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    target = os.path.join(ASSETS, name)
    cv2.imwrite(target, image, [cv2.IMWRITE_WEBP_QUALITY, quality])
    print(f"assets/{name}: {image.shape[1]}x{image.shape[0]}, {os.path.getsize(target) // 1024} KB")


def main() -> int:
    os.makedirs(ASSETS, exist_ok=True)
    logos()
    icons()
    og()
    if len(sys.argv) > 1:
        captures = os.path.abspath(sys.argv[1])
        for source, name, width, quality in (("app_ao_vivo.png", "app.webp", None, 88),
                                             ("diagnostico.png", "diagnostico.webp", 1400, 90)):
            if os.path.isfile(os.path.join(captures, source)):
                webp(os.path.join(captures, source), name, width, quality)
    return 0


if __name__ == "__main__":
    sys.exit(main())
