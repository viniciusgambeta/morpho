"""O motor de verdade, mas enviando para a câmera de TESTE (ver run.py).

    <python do motor> bench/vcam/engine_test_camera.py --config <arquivo.json>

Mesmos comandos e eventos de ``python -m app.engine``. A pasta da câmera de teste vem de
``MORPHO_CAMERA_DIR``.
"""
import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT)

from app.engine import morphocam  # noqa: E402

morphocam.DEVICE_NAME = "Morpho Camera Teste"
morphocam.CHANNEL = "MorphoCamTest"
morphocam.DEVICE_PATH = "morpho:camera-teste"
morphocam.CLSID = {64: "{6D5F5A88-69F6-47B0-B24B-22115FF96290}"}

from app.engine.__main__ import main  # noqa: E402

if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
