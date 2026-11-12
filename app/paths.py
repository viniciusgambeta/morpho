"""Onde ficam o motor, os dados e os logs.

O código do app mora na pasta do projeto (sincronizada pelo OneDrive). Tudo o
que é grande ou muda o tempo todo fica fora dela: o clone do motor com seu
ambiente Python e modelos, e a pasta de dados do app.
"""
from __future__ import annotations

import os

from app import APP_NAME

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Clone do fork beekamai/DeepLiveCam (commit 766b9ce) com venv e modelos.
# Enquanto o app não tem instalador, o motor é usado direto de lá.
DEFAULT_ENGINE_ROOT = r"C:\Users\vinic\dlc-lab\beekamai"
# Os arquivos da câmera virtual (MorphoCamera64-N.dll e MorphoCamera32-N.dll, N = revisão do filtro),
# compilados de vendor/morphocam. O registro no Windows aponta para lá, então a
# pasta precisa ser estável e ficar fora do OneDrive.
DEFAULT_CAMERA_ROOT = r"C:\Users\vinic\dlc-lab\morphocam"


def bundled(name: str) -> str | None:
    """A pasta ``name`` ao lado do código, quando o app roda do pacote instalado.

    O pacote (montado por ``packaging/build.py``) traz tudo junto: ``engine``
    (o motor e os modelos), ``python`` (o Python com as bibliotecas) e
    ``camera`` (a câmera virtual). Na pasta de desenvolvimento essas pastas
    não existem, e valem os caminhos do laboratório.
    """
    path = os.path.join(PROJECT_ROOT, name)
    return path if os.path.isdir(path) else None


def is_packaged() -> bool:
    return bundled("python") is not None and bundled("engine") is not None


def engine_root() -> str:
    return os.path.abspath(os.environ.get("MORPHO_ENGINE_ROOT") or bundled("engine") or DEFAULT_ENGINE_ROOT)


def camera_root() -> str:
    return os.path.abspath(os.environ.get("MORPHO_CAMERA_DIR") or bundled("camera") or DEFAULT_CAMERA_ROOT)


def engine_python(root: str | None = None) -> str:
    """O Python que roda o motor: o do pacote, se houver; senão o do ambiente do laboratório."""
    packaged = bundled("python")
    if packaged and os.path.isfile(os.path.join(packaged, "python.exe")):
        return os.path.join(packaged, "python.exe")
    return os.path.join(root or engine_root(), "venv", "Scripts", "python.exe")


def data_dir() -> str:
    """Configuração, medições e logs de cada execução.

    O padrão é ``%LOCALAPPDATA%``, mas ``MORPHO_DATA_DIR`` tem prioridade. Em
    desenvolvimento ela é necessária: programas empacotados (como o app
    Claude) enxergam uma cópia privada de ``AppData``, então um arquivo
    gravado por um terminal comum não aparece para eles, e vice-versa.
    """
    path = os.environ.get("MORPHO_DATA_DIR")
    if not path:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def recordings_dir() -> str:
    """Gravações da webcam para ajuste do rastreamento. Ficam só neste
    computador: nunca dentro da pasta do projeto, que o OneDrive sincroniza."""
    path = os.path.join(data_dir(), "recordings")
    os.makedirs(path, exist_ok=True)
    return path


def logs_dir() -> str:
    path = os.path.join(data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path
