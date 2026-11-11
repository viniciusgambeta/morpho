"""Canal motor -> janela: uma linha JSON por evento na saída padrão.

As bibliotecas do motor também escrevem na saída padrão (insightface,
onnxruntime). Para a janela separar uma coisa da outra, cada evento começa
com um marcador; o resto vai para o log.
"""
from __future__ import annotations

import json
import sys
import threading

MARKER = "@@EVT "
_lock = threading.Lock()


def emit(evt: str, **fields) -> None:
    line = MARKER + json.dumps({"evt": evt, **fields}, ensure_ascii=False, default=float)
    with _lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def status(state: str, detail: str = "") -> None:
    """Estados: starting, loading, building, opening_camera, running, stopping."""
    emit("status", state=state, detail=detail)


def error(message: str, fatal: bool = False, code: str = "") -> None:
    emit("error", message=message, fatal=fatal, code=code)


def parse(line: str):
    """O evento contido na linha, ou ``None`` se for saída comum do motor."""
    if not line.startswith(MARKER):
        return None
    try:
        return json.loads(line[len(MARKER):])
    except ValueError:
        return None
