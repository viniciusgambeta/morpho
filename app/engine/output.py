"""A saída do motor além da janela: câmera virtual e proteção do rosto real.

A câmera virtual é a do próprio app, "Morpho Camera" (ver ``morphocam.py``):
os outros programas (Meet, Zoom, Discord, OBS) passam a listar essa câmera e
recebem a imagem já com o rosto trocado. Se os arquivos dela não estiverem
no computador, o app usa a câmera virtual do OBS Studio, se houver.

A proteção existe porque essa imagem vai para outras pessoas: num quadro em
que a troca não pôde ser feita (rosto não detectado, mão na frente, cabeça
muito virada), mandar o quadro cru mostraria o rosto real.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import cv2
import numpy as np

from app.engine import events

OBS_VIRTUALCAM_CLSID = r"CLSID\{A3FCE0F5-3493-419F-958A-ABA1250EC20B}"
# Numa falha curta da troca, repete-se a última imagem boa por até este tempo;
# depois disso a imagem ao vivo sai borrada até a troca voltar.
HOLD_LAST_GOOD_SECONDS = 0.25
BLUR_DIVISOR = 28    # a imagem é reduzida por este fator e ampliada de volta


class OutputOptions:
    """O que a janela pediu para a saída; lido pelas threads do motor."""

    def __init__(self) -> None:
        self.virtual_camera = False
        self.protect = True
        self.force_blur = False   # pausa de privacidade: borra tudo, com ou sem troca


def probe_virtual_camera() -> dict:
    """Qual câmera virtual pode ser usada neste computador: a nossa ou, na falta dela, a do OBS."""
    from app.engine import morphocam

    own = morphocam.ensure_registered()
    if own["ok"]:
        return dict(available=True, backend="morpho", device=morphocam.DEVICE_NAME, reason="",
                    installed_now=bool(own["changed"]))
    try:
        import pyvirtualcam  # noqa: F401
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, OBS_VIRTUALCAM_CLSID) as key:
            device = str(winreg.QueryValue(key, None)) or "OBS Virtual Camera"
    except (ImportError, OSError):
        return dict(available=False, backend=None, device=None, installed_now=False,
                    reason=own["reason"] or "A câmera virtual não está disponível neste computador.")
    return dict(available=True, backend="obs", device=device, reason="", installed_now=False)


def blurred(frame: np.ndarray) -> np.ndarray:
    """O quadro irreconhecível: nenhum traço de rosto sobrevive."""
    height, width = frame.shape[:2]
    small = cv2.resize(frame, (max(1, width // BLUR_DIVISOR), max(1, height // BLUR_DIVISOR)),
                       interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 1.5)
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)


class FaceGuard:
    """Decide o que sai num quadro em que a troca não foi aplicada."""

    def __init__(self) -> None:
        self._last_good: Optional[np.ndarray] = None
        self._last_good_at = 0.0

    def reset(self) -> None:
        self._last_good = None

    def filter(self, frame: np.ndarray, swapped: bool) -> tuple:
        """(quadro a enviar, se foi protegido)."""
        now = time.perf_counter()
        if swapped:
            self._last_good, self._last_good_at = frame, now
            return frame, False
        if self._last_good is not None and now - self._last_good_at <= HOLD_LAST_GOOD_SECONDS:
            return self._last_good, True
        return blurred(frame), True


class VirtualCamera:
    """Envia os quadros de saída para a câmera virtual (a nossa, ou a do OBS)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._camera = None            # morphocam.Sender ou pyvirtualcam.Camera
        self._backend: Optional[str] = None
        self._size: Optional[tuple] = None
        self._failed = False
        self._watched: Optional[bool] = None
        self.device: Optional[str] = None

    @property
    def active(self) -> bool:
        return self._camera is not None

    def _open(self, width: int, height: int, fps: float) -> bool:
        probe = probe_virtual_camera()
        try:
            if probe["backend"] == "morpho":
                from app.engine import morphocam

                self._camera = morphocam.Sender()
            elif probe["backend"] == "obs":
                import pyvirtualcam

                self._camera = pyvirtualcam.Camera(
                    width=width, height=height, fps=max(1, int(round(fps))),
                    fmt=pyvirtualcam.PixelFormat.BGR, print_fps=False, backend="obs",
                )
            else:
                raise RuntimeError(probe["reason"])
        except Exception as error:
            self._failed = True
            events.emit("virtual_camera", on=False, device=None, detail=str(error)[:200], error=(
                "Não consegui ligar a câmera virtual." if probe["backend"] != "obs" else
                "Não consegui ligar a câmera virtual. Se o OBS estiver aberto com a câmera "
                "virtual dele ligada, desligue-a lá e tente de novo."))
            return False
        self._backend = probe["backend"]
        self._size = (width, height)
        self._watched = False if self._backend == "morpho" else None
        self.device = str(self._camera.device)
        events.emit("virtual_camera", on=True, device=self.device, backend=self._backend,
                    watched=self._watched, width=width, height=height)
        return True

    def send(self, frame: np.ndarray, fps: float) -> None:
        """Abre o dispositivo no primeiro quadro. Uma falha desliga a saída e avisa uma vez."""
        if self._failed:
            return
        height, width = frame.shape[:2]
        with self._lock:
            if self._camera is None and not self._open(width, height, fps):
                return
            try:
                if self._backend == "morpho":
                    # Só há para onde enviar enquanto algum programa está com a câmera aberta;
                    # a janela mostra quando isso muda.
                    self._camera.send(frame)
                    watched = self._camera.watched
                    if watched != self._watched:
                        self._watched = watched
                        events.emit("virtual_camera", on=True, device=self.device, backend=self._backend,
                                    watched=watched)
                    return
                if (width, height) != self._size:
                    frame = cv2.resize(frame, self._size, interpolation=cv2.INTER_AREA)
                self._camera.send(np.ascontiguousarray(frame))
            except Exception as error:
                self._failed = True
                self._close_locked()
                events.emit("virtual_camera", on=False, device=None, detail=str(error)[:200],
                            error="A câmera virtual parou de aceitar imagem.")

    def _close_locked(self) -> None:
        if self._camera is not None:
            try:
                self._camera.close()
            except Exception:
                pass
        self._camera = None
        self._size = None
        self._watched = None

    def close(self, announce: bool = True) -> None:
        """Para de enviar; quem estiver com a câmera aberta passa a ver a tela de pausa."""
        with self._lock:
            was_active = self._camera is not None
            self._close_locked()
            self._failed = False
        if was_active and announce:
            events.emit("virtual_camera", on=False, device=None)
