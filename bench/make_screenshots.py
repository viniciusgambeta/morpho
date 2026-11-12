"""Gera as capturas de ``docs/telas`` com a janela de verdade, sem mostrá-la.

    <python do motor> bench/make_screenshots.py --replay VIDEO --faces FOTO [FOTO ...] --out PASTA
                                                [--camera NOME]

Abre o app com um vídeo no lugar da webcam e grava em PASTA: ``carregando``, ``configuracoes``
e várias opções de ``instrucoes-N``, ``tema-claro-N`` e ``ao-vivo-F-N`` (uma série por foto da
galeria), tiradas em momentos diferentes do vídeo. É só escolher a melhor de cada e copiá-la
para ``docs/telas`` sem o número. ``--camera`` é só o nome mostrado no campo da câmera: com
``--replay`` a webcam não é aberta.

A janela aparece como no uso comum, com a câmera virtual ligada nas configurações, mas nenhum
quadro é enviado a ela: o pedido é desligado antes de chegar ao motor, para o vídeo de teste
não aparecer numa chamada que esteja aberta neste computador.

Usa a pasta de dados de teste (``MORPHO_DATA_DIR``) e a deixa como a encontrou. Em material
público, só gravações e fotos de quem autorizou.
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

SIZE = (1240, 760)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--replay", required=True, help="vídeo usado no lugar da câmera")
    parser.add_argument("--faces", nargs="+", required=True, help="fotos da galeria, na ordem em que aparecem")
    parser.add_argument("--out", required=True, help="pasta das capturas")
    parser.add_argument("--camera", help="nome que aparece no campo da câmera (a webcam não é aberta)")
    parser.add_argument("--ready-shots", type=int, default=6, help="opções de instrucoes e de tema-claro")
    parser.add_argument("--live-shots", type=int, default=4, help="capturas ao vivo por foto")
    options = parser.parse_args()
    os.makedirs(options.out, exist_ok=True)

    from app import paths
    settings_file = os.path.join(paths.data_dir(), "settings.json")
    backup = settings_file + ".antes-das-capturas"
    if os.path.isfile(settings_file):
        shutil.copyfile(settings_file, backup)
    faces = [os.path.abspath(p) for p in options.faces]
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(dict(faces=faces, face=faces[0], virtual_camera=True, preview=True, theme="dark",
                       show_fps=True, show_faces=False), f)

    sys.argv = [sys.argv[0], "--offscreen", "--replay", options.replay]
    if options.camera:
        sys.argv += ["--camera", options.camera]
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from app.ui.__main__ import parse_args
    from app.ui.engine_process import EngineProcess
    from app.ui.main_window import MainWindow

    # A tela mostra a câmera virtual ligada, mas o motor nunca recebe o pedido de transmitir.
    real_send = EngineProcess.send

    def send_without_camera(self, **command):
        if command.get("virtual_camera"):
            command["virtual_camera"] = False
        return real_send(self, **command)

    EngineProcess.send = send_without_camera

    app = QApplication(sys.argv[:1])
    window = MainWindow(parse_args())
    window.resize(*SIZE)
    window.show()

    def wait(condition, seconds: float) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            app.processEvents()
            if condition():
                return True
            time.sleep(0.01)
        return False

    def pause(seconds: float) -> None:
        wait(lambda: False, seconds)

    def shot(name: str) -> None:
        window.grab().save(os.path.join(options.out, name + ".png"))
        print("  " + name, flush=True)

    def face_tiles():
        return [t for t in window.gallery._tiles if t.kind == "face"]

    def swap_fps() -> float:
        stats = window.stats if (window.stats or {}).get("mode") == "live" else {}
        return stats.get("swap_fps") or 0

    transmitted = False
    try:
        # carregando: fica com a captura do meio da espera
        loading = []
        next_grab = time.time() + 0.6
        deadline = time.time() + 240
        while not window.loaded and time.time() < deadline:
            app.processEvents()
            if time.time() >= next_grab:
                loading.append(window.grab())
                next_grab = time.time() + 0.4
            time.sleep(0.01)
        if not window.loaded:
            print("o motor não carregou")
            return 1
        if loading:
            loading[len(loading) // 2].save(os.path.join(options.out, "carregando.png"))
            print(f"  carregando ({len(loading)} opções, ficou a do meio)", flush=True)

        ready = (wait(lambda: window.face_ok, 30) and wait(lambda: not window.view.celebrating, 10)
                 and wait(lambda: bool(window.view.steps), 3)
                 and wait(lambda: window.view.mascot.current() == "parado", 5))
        pause(2.0)   # a prévia da câmera chega
        print(f"pronto: {ready}; tamanho {window.width()}x{window.height()}", flush=True)
        for number in range(1, options.ready_shots + 1):
            shot(f"instrucoes-{number}")
            pause(1.4)

        window.theme_choice._group.buttons()[1].click()
        pause(0.4)
        for number in range(1, options.ready_shots + 1):
            shot(f"tema-claro-{number}")
            pause(1.4)
        window.theme_choice._group.buttons()[0].click()
        pause(0.4)

        window.open_page(1)
        pause(0.4)
        shot("configuracoes")
        window.open_page(0)
        pause(0.3)

        QTest.mouseClick(window.button, Qt.MouseButton.LeftButton)
        live = wait(lambda: window.state == "running" and window.view.has_frame(), 40) and wait(lambda: swap_fps() > 15, 30)
        print(f"ao vivo: {live}, {swap_fps():.0f} trocas por segundo", flush=True)
        for index in range(len(face_tiles())):
            if index:
                QTest.mouseClick(face_tiles()[index], Qt.MouseButton.LeftButton)
                window.refresh()
            wait(lambda: window.face_ok and swap_fps() > 15, 20)
            pause(2.5)
            for number in range(1, options.live_shots + 1):
                transmitted = transmitted or window.vcam_on
                shot(f"ao-vivo-{index + 1}-{number}")
                pause(1.3)
            print(f"    foto {index + 1}: {swap_fps():.0f} trocas por segundo", flush=True)
        transmitted = transmitted or window.vcam_on
        QTest.mouseClick(window.button, Qt.MouseButton.LeftButton)
        wait(lambda: window.state in ("idle", "preview"), 20)
    finally:
        window.close()
        app.processEvents()
        if os.path.isfile(backup):
            shutil.move(backup, settings_file)
    print("câmera virtual transmitiu durante as capturas: " + ("SIM (não devia)" if transmitted else "não"))
    return 1 if transmitted else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
