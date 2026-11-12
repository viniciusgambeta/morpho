"""Usa a janela de verdade, sem mostrá-la, clicando como uma pessoa clicaria.

    <python do motor> bench/ui_smoke_test.py [--replay VIDEO] [--faces FOTO FOTO]

Abre o app com um vídeo no lugar da webcam e confere, uma a uma, as coisas que só dá para
saber mexendo na tela: o "sem rosto" (a câmera sai como é, sem troca e sem borrão), a volta
para um rosto com a troca ligada, o × que tira fotos da galeria (e que some na foto em uso
ao vivo), a página de configurações e a troca de tema.

Não toca na webcam nem nas configurações da pessoa: usa a pasta de dados de teste
(``MORPHO_DATA_DIR``) e a deixa como a encontrou.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.environ.setdefault("MORPHO_DATA_DIR", r"C:\Users\vinic\dlc-lab\app-data-test")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("  ok    " if ok else "  FALHA ") + name + (f"  ({detail})" if detail else ""), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--replay", default=r"C:\Users\vinic\dlc-lab\fixtures\clip_720p30.avi")
    parser.add_argument("--faces", nargs=2, default=[r"C:\Users\vinic\dlc-lab\fixtures\source.jpg",
                                                     r"C:\Users\vinic\dlc-lab\fixtures\source_identity.jpg"])
    parser.add_argument("--shots", help="pasta para gravar capturas de cada etapa")
    options = parser.parse_args()

    from app import paths
    settings_file = os.path.join(paths.data_dir(), "settings.json")
    backup = settings_file + ".antes-do-teste"
    if os.path.isfile(settings_file):
        shutil.copyfile(settings_file, backup)
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(dict(faces=[os.path.abspath(p) for p in options.faces], face=os.path.abspath(options.faces[0]),
                       virtual_camera=False, preview=True, theme="dark", show_fps=True, show_faces=False), f)

    sys.argv = [sys.argv[0], "--offscreen", "--replay", options.replay]
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from app.ui import theme
    from app.ui.__main__ import parse_args
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    window = MainWindow(parse_args())
    window.show()

    def wait(condition, seconds: float) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            app.processEvents()
            if condition():
                return True
            time.sleep(0.01)
        return False

    def shot(name: str) -> None:
        if options.shots:
            os.makedirs(options.shots, exist_ok=True)
            window.grab().save(os.path.join(options.shots, name + ".png"))

    def tiles(kind: str):
        return [t for t in window.gallery._tiles if t.kind == kind]

    def live_stats() -> dict:
        return window.stats if (window.stats or {}).get("mode") == "live" else {}

    try:
        check("o motor carrega", wait(lambda: window.loaded, 180))
        check("o mascote grita ao terminar de carregar", window.view.celebrating
              and window.view.mascot.current() == "gritando")
        check("a foto lembrada é aceita", wait(lambda: window.face_ok, 30))
        check("o grito termina e o passo a passo aparece", wait(lambda: not window.view.celebrating, 8)
              and wait(lambda: bool(window.view.steps), 2))
        check("mascote parado com tudo pronto", wait(lambda: window.view.mascot.current() == "parado", 3),
              str(window.view.mascot.current()))
        check("botão com o texto novo", window.button._title == "Troque o meu rosto", window.button._title)
        check("qualidade visível com a câmera escolhida", window.quality.isVisible())
        shot("1-pronto")

        # sem rosto ---------------------------------------------------------------------
        QTest.mouseClick(tiles("none")[0], Qt.MouseButton.LeftButton)
        check("clicar em “sem rosto” desmarca a foto", window.settings.without_face and window.settings.face is None)
        check("o botão passa a dizer “Iniciar sem troca”", window.button._title == "Iniciar sem troca", window.button._title)
        check("dá para iniciar sem rosto", wait(window.can_start, 5))
        QTest.mouseClick(window.button, Qt.MouseButton.LeftButton)
        check("entra ao vivo", wait(lambda: window.state == "running" and window.view.has_frame(), 30), window.state)
        check("sem rosto: os quadros saem sem troca", wait(lambda: (live_stats().get("passthrough_fps") or 0) > 5, 10),
              str(live_stats().get("passthrough_fps")))
        stats = live_stats()
        check("sem rosto: nada é borrado", (stats.get("protected_fps") or 0) == 0, str(stats.get("protected_fps")))
        check("selo “sem troca” no vídeo", bool(window.view.badge) and window.view.badge[2] == "sem troca",
              str(window.view.badge))
        shot("2-sem-rosto-ao-vivo")

        # volta a um rosto, com a troca ligada ----------------------------------------------
        first, second = tiles("face")[0], tiles("face")[1]
        QTest.mouseClick(first, Qt.MouseButton.LeftButton)
        check("escolher uma foto ao vivo liga a troca", wait(lambda: (live_stats().get("swap_fps") or 0) > 5, 20),
              str(live_stats().get("swap_fps")))
        check("selo com os quadros por segundo", bool(window.view.badge) and "fps" in window.view.badge[2],
              str(window.view.badge))
        window.refresh()
        first, second = tiles("face")[0], tiles("face")[1]
        check("ao vivo, a foto em uso não tem ×", not first.removable and second.removable)
        before = list(window.settings.faces)
        QTest.mouseClick(first, Qt.MouseButton.LeftButton, pos=QPoint(first.width() - 12, 12))
        check("clicar no canto da foto em uso não a remove", window.settings.faces == before)
        QTest.mouseClick(second, Qt.MouseButton.LeftButton, pos=QPoint(second.width() - 12, 12))
        check("o × tira a outra foto da galeria", len(window.settings.faces) == len(before) - 1,
              f"{len(before)} -> {len(window.settings.faces)}")
        check("a troca continua depois de remover a outra",
              wait(lambda: window.state == "running" and window.face_ok and (live_stats().get("swap_fps") or 0) > 5, 10))

        # configurações ------------------------------------------------------------------
        window.open_page(1)
        check("página de configurações abre", window.pages.currentIndex() == 1)
        window.fps_row.switch.setChecked(False)
        app.processEvents()
        check("sem mostrar quadros por segundo, o selo fica limpo",
              bool(window.view.badge) and "fps" not in window.view.badge[2] and "quadros" not in window.status.text(),
              f"{window.view.badge} / {window.status.text()}")
        window.faces_row.switch.setChecked(True)
        check("contagem de rostos aparece no selo", wait(lambda: bool(window.view.badge) and "rosto" in window.view.badge[2], 5),
              str(window.view.badge))
        shot("3-configuracoes-ao-vivo")
        window.theme_choice._group.buttons()[1].click()
        app.processEvents()
        check("tema claro aplicado", theme.NAME == "light" and window.settings.theme == "light")
        shot("4-claro-ao-vivo")
        window.theme_choice._group.buttons()[0].click()
        app.processEvents()
        check("tema escuro de volta", theme.NAME == "dark")
        window.open_page(0)

        # parar e remover a foto escolhida -------------------------------------------------
        QTest.mouseClick(window.button, Qt.MouseButton.LeftButton)
        check("para", wait(lambda: window.state in ("idle", "preview"), 20), window.state)
        only = tiles("face")[0]
        QTest.mouseClick(only, Qt.MouseButton.LeftButton, pos=QPoint(only.width() - 12, 12))
        check("parado, o × tira a foto escolhida", window.settings.faces == [] and window.settings.face is None)
        check("sem foto e sem “sem rosto”, não dá para iniciar", not window.can_start())
        check("mascote das pílulas enquanto falta escolher", wait(lambda: window.view.mascot.current() == "pilulas", 3),
              str(window.view.mascot.current()))
        shot("5-sem-foto")
    finally:
        window.close()
        app.processEvents()
        if os.path.isfile(backup):
            shutil.move(backup, settings_file)

    failed = [name for name, ok, _detail in results if not ok]
    print(f"\n{len(results) - len(failed)} de {len(results)} conferências passaram" + (": FALHAS: " + "; ".join(failed) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
