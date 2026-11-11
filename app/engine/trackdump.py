"""Registro opcional, quadro a quadro, de onde a troca foi desenhada.

Só existe para medir o "descolamento" (ver ``bench/track_eval.py``): com a
variável ``MORPHO_TRACK_DUMP`` apontando para um arquivo, o pipeline e a
composição escrevem uma linha JSON por evento. Guarda números (pontos do
rosto, instantes), nunca imagem.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional

import cv2
import numpy as np

# Lado, em pixels, da miniatura em tons de cinza usada para comparar a imagem
# reprojetada com a troca exata do mesmo quadro.
THUMB_WIDTH = 320


class TrackDump:
    def __init__(self, path: str) -> None:
        self._file = open(path, "w", encoding="utf-8")
        self._lock = threading.Lock()
        self._pending: dict = {}   # seq -> miniatura da saída reprojetada

    @classmethod
    def from_env(cls) -> Optional["TrackDump"]:
        path = os.environ.get("MORPHO_TRACK_DUMP")
        return cls(path) if path else None

    def write(self, **row) -> None:
        with self._lock:
            self._file.write(json.dumps(row, default=float) + "\n")

    @staticmethod
    def kps(points) -> Optional[list]:
        if points is None:
            return None
        return [[round(float(x), 2), round(float(y), 2)] for x, y in np.asarray(points, dtype=np.float32)]

    @staticmethod
    def _thumb(frame: np.ndarray) -> np.ndarray:
        height = max(1, int(round(frame.shape[0] * THUMB_WIDTH / frame.shape[1])))
        return cv2.cvtColor(cv2.resize(frame, (THUMB_WIDTH, height), interpolation=cv2.INTER_AREA),
                            cv2.COLOR_BGR2GRAY)

    def reprojected(self, seq: int, frame: np.ndarray) -> None:
        """Guarda a saída reprojetada do quadro ``seq`` até a troca exata chegar."""
        with self._lock:
            self._pending[seq] = self._thumb(frame)
            for old in [k for k in self._pending if k < seq - 30]:
                del self._pending[old]

    def exact(self, seq: int, frame: np.ndarray, box) -> None:
        """A troca exata de ``seq`` chegou: quão diferente era a reprojetada?

        Diferença absoluta média, em níveis de cinza (0-255), dentro da caixa
        onde o rosto foi colado. Zero = a aproximação mostrada antes era igual.
        """
        with self._lock:
            before = self._pending.pop(seq, None)
        if before is None or box is None:
            return
        after = self._thumb(frame)
        scale = THUMB_WIDTH / frame.shape[1]
        x0, y0, x1, y1 = (int(round(v * scale)) for v in box)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return
        diff = cv2.absdiff(before[y0:y1, x0:x1], after[y0:y1, x0:x1])
        self.write(k="pix", seq=seq, diff=float(diff.mean()))

    def close(self) -> None:
        with self._lock:
            self._file.close()
