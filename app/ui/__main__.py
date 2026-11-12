"""Abre o app.

    python -m app.ui                      a janela normal
    python -m app.ui --list-cameras       lista as câmeras e sai
    python -m app.ui --remove-virtual-camera   desinstala a câmera virtual e sai

As opções abaixo existem para desenvolvimento e testes: pré-selecionam o que na
janela se escolhe com o mouse, trocam a câmera por um vídeo ou fecham a janela
sozinhas depois de um tempo.
"""
from __future__ import annotations

import argparse
import os
import sys

from app import paths
from app.engine.config import DEFAULT_MODEL, RESOLUTIONS


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list-cameras", action="store_true")
    p.add_argument("--remove-virtual-camera", action="store_true",
                   help="tira a câmera virtual “Morpho Camera” deste usuário do Windows e sai")
    choose = p.add_argument_group("pré-seleção")
    choose.add_argument("--source", nargs="+", help="foto do rosto de origem (entra na galeria)")
    choose.add_argument("--camera", help="nome (ou parte) ou índice da câmera")
    choose.add_argument("--resolution", choices=sorted(RESOLUTIONS))
    choose.add_argument("--mirror", action="store_true")
    choose.add_argument("--virtual-camera", action="store_true", help="liga a saída para a câmera virtual")
    choose.add_argument("--no-preview", action="store_true", help="não mostra a câmera antes de iniciar")
    choose.add_argument("--autostart", action="store_true", help="clica no botão de iniciar sozinho quando tudo estiver pronto")
    choose.add_argument("--theme", choices=("dark", "light"), help="abre com este tema (e passa a lembrá-lo)")
    choose.add_argument("--open-settings", action="store_true", help="abre já na página de configurações")
    engine = p.add_argument_group("motor")
    engine.add_argument("--model", default=DEFAULT_MODEL)
    engine.add_argument("--no-tensorrt", action="store_true")
    engine.add_argument("--set", action="append", default=[], metavar="CHAVE=JSON",
                        help="opção do motor (ex.: reprojection=true)")
    engine.add_argument("--engine-root", default=paths.engine_root())
    test = p.add_argument_group("testes e medições")
    test.add_argument("--replay", help="vídeo usado no lugar da câmera")
    test.add_argument("--replay-fps", type=float, default=None,
                      help="ritmo da reprodução (padrão: o da gravação, ou 30)")
    test.add_argument("--record", action="store_true",
                      help="grava os quadros crus da câmera, só neste computador, para ajustar o rastreamento")
    test.add_argument("--record-seconds", type=float, default=40.0)
    test.add_argument("--run-seconds", type=float, default=0.0, help="fecha depois de rodar ao vivo por este tempo")
    test.add_argument("--stop-after", type=float, default=0.0, help="clica em Parar depois de rodar por este tempo")
    test.add_argument("--quit-after", type=float, default=0.0, help="fecha este tempo depois de abrir")
    test.add_argument("--quit-after-load", type=float, default=0.0,
                      help="fecha este tempo depois de os modelos carregarem (para capturar o grito do mascote)")
    test.add_argument("--give-up-seconds", type=float, default=0.0,
                      help="fecha se não começar a rodar ao vivo neste tempo")
    test.add_argument("--offscreen", action="store_true", help="não abre janela na tela")
    test.add_argument("--report", help="grava um resumo das medições neste arquivo")
    test.add_argument("--screenshot", help="grava uma captura da janela neste arquivo ao fechar")
    test.add_argument("--photo-dir", help="pasta do botão Tirar foto (padrão: Imagens)")
    test.add_argument("--click", action="append", default=[], metavar="SEGUNDOS:BOTAO",
                      help="aperta um botão do palco depois de rodar por este tempo (foto, borrar)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_cameras:
        from app.engine.bridge import list_cameras

        for camera in list_cameras():
            note = "  (saída de câmera virtual — não serve de entrada)" if camera["virtual_output"] else ""
            print(f"{camera['index']:2d}  {camera['name']}{note}")
        return 0
    if args.remove_virtual_camera:
        from app.engine import morphocam

        morphocam.unregister()
        print("A câmera virtual foi removida. Ela volta a ser instalada na próxima abertura do app.")
        return 0
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    if os.path.basename(sys.executable).lower().startswith("python"):
        # Em desenvolvimento quem roda a janela é o python.exe: sem isto a barra de tarefas
        # mostraria o ícone do Python. No app instalado o processo já é o Morpho.exe.
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Morpho.App")
        except Exception:
            pass

    from PySide6.QtWidgets import QApplication

    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    window = MainWindow(args)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
