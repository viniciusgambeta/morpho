"""O quadro mais recente, em memória compartilhada entre o motor e a janela.

Um único bloco: cabeçalho + pixels BGR. O motor escreve, a janela lê. Não há
fila: quem lê sempre pega o quadro mais novo, e um leitor lento só perde
quadros, nunca atrasa o motor.

Consistência por contador (seqlock): o escritor deixa o contador ímpar
enquanto escreve e par quando termina. O leitor copia e confere que o
contador era par e não mudou; se mudou, descarta a leitura.
"""
from __future__ import annotations

import struct
from multiprocessing import shared_memory
from typing import Optional, Tuple

import numpy as np

MAGIC = 0x444C5346  # "DLSF"
# magic, contador, largura, altura, seq do quadro de câmera, instante da captura (time.time)
_HEADER = struct.Struct("<IQIIqd")
HEADER_SIZE = 64
MAX_WIDTH, MAX_HEIGHT = 2560, 1440
_COUNTER_OFFSET = 4


class FrameWriter:
    def __init__(self, name: str) -> None:
        size = HEADER_SIZE + MAX_WIDTH * MAX_HEIGHT * 3
        self._shm = shared_memory.SharedMemory(name=name, create=True, size=size)
        self.name = name
        self._counter = 0
        self._pixels = np.frombuffer(self._shm.buf, dtype=np.uint8, offset=HEADER_SIZE)
        _HEADER.pack_into(self._shm.buf, 0, MAGIC, 0, 0, 0, -1, 0.0)

    def write(self, frame: np.ndarray, seq: int, captured_at: float) -> None:
        height, width = frame.shape[:2]
        if width > MAX_WIDTH or height > MAX_HEIGHT or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(f"quadro {frame.shape} não cabe no bloco compartilhado")
        self._counter += 1  # ímpar: escrita em andamento
        struct.pack_into("<Q", self._shm.buf, _COUNTER_OFFSET, self._counter)
        n = width * height * 3
        self._pixels[:n] = frame.reshape(-1)
        self._counter += 1  # par: quadro completo
        _HEADER.pack_into(self._shm.buf, 0, MAGIC, self._counter, width, height, seq, captured_at)

    def close(self) -> None:
        self._pixels = None
        try:
            self._shm.close()
            self._shm.unlink()
        except Exception:
            pass


class FrameReader:
    def __init__(self, name: str) -> None:
        self._shm = shared_memory.SharedMemory(name=name, create=False)
        self._pixels = np.frombuffer(self._shm.buf, dtype=np.uint8, offset=HEADER_SIZE)
        self._last = 0

    def read(self) -> Optional[Tuple[np.ndarray, int, float]]:
        """(quadro, seq, instante da captura) se há quadro novo; senão ``None``."""
        magic, counter, width, height, seq, captured_at = _HEADER.unpack_from(self._shm.buf, 0)
        if magic != MAGIC or counter == self._last or counter % 2 or width == 0:
            return None
        frame = self._pixels[: width * height * 3].reshape(height, width, 3).copy()
        (after,) = struct.unpack_from("<Q", self._shm.buf, _COUNTER_OFFSET)
        if after != counter:
            return None  # o motor escreveu por cima durante a cópia; o próximo tick pega
        self._last = counter
        return frame, seq, captured_at

    def close(self) -> None:
        self._pixels = None
        try:
            self._shm.close()
        except Exception:
            pass
