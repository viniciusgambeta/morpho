"""Captura: a fonte de quadros e a thread que os distribui.

``FrameHub`` é o ponto de encontro das três threads do motor:

- a captura numera cada quadro, guarda uma cópia crua num anel curto e deixa o
  mais novo numa fila de um lugar só (o pipeline é mais lento que a câmera, e
  um segundo quadro na fila seria só atraso);
- o pipeline tira da fila e publica o resultado em ``record``;
- a composição acorda a cada quadro novo ou resultado novo.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from app.engine import events
from app.engine.bridge import EngineError
from app.engine.stats import Stats

RING_SIZE = 16            # quadros crus guardados para a reprojeção ancorar
TIMES_KEPT = 900          # instantes de captura lembrados, para medir latência
MAX_MISSES = 90           # leituras falhas seguidas até considerar a câmera perdida


class FrameHub:
    def __init__(self) -> None:
        self.queue: "queue.Queue[Tuple[int, np.ndarray, float]]" = queue.Queue(maxsize=1)
        self.wake = threading.Event()
        self._lock = threading.Lock()
        self._ring: Dict[int, np.ndarray] = {}
        self._times: Dict[int, float] = {}
        self.latest_seq = -1
        self._record = None
        self._record_fresh = False

    # captura ---------------------------------------------------------------
    def push(self, seq: int, frame: np.ndarray, captured_at: float) -> None:
        with self._lock:
            self._ring[seq] = frame.copy()   # o pipeline desenha em ``frame``; o anel fica limpo
            self._times[seq] = captured_at
            for old in [k for k in self._ring if k <= seq - RING_SIZE]:
                del self._ring[old]
            if len(self._times) > TIMES_KEPT:
                for old in [k for k in self._times if k <= seq - TIMES_KEPT]:
                    del self._times[old]
            self.latest_seq = seq
        item = (seq, frame, captured_at)
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(item)
            except queue.Full:
                pass
        self.wake.set()

    # pipeline --------------------------------------------------------------
    def publish(self, record) -> None:
        with self._lock:
            self._record = record
            self._record_fresh = True
        self.wake.set()

    # composição ------------------------------------------------------------
    def take_record(self):
        """(último resultado, se é novo desde a última chamada)."""
        with self._lock:
            fresh, self._record_fresh = self._record_fresh, False
            return self._record, fresh

    def clear_record(self) -> None:
        """Esquece o último resultado: ao entrar ou sair do modo ao vivo, uma
        troca antiga não pode reaparecer."""
        with self._lock:
            self._record = None
            self._record_fresh = False

    def ring_view(self) -> Dict[int, np.ndarray]:
        with self._lock:
            return dict(self._ring)

    def raw(self, seq: int) -> Optional[np.ndarray]:
        """O quadro cru da câmera, como chegou (para a prévia)."""
        with self._lock:
            return self._ring.get(seq)

    def captured_at(self, seq: int) -> Optional[float]:
        with self._lock:
            return self._times.get(seq)


class ReplaySource:
    """Um vídeo no lugar da câmera: em laço, um quadro a cada 1/fps."""

    def __init__(self, path: str, fps: float) -> None:
        self._path, self._fps = path, fps
        self._frames: list = []
        self._n = 0
        self._t0 = 0.0

    def open(self) -> dict:
        cap = cv2.VideoCapture(self._path)
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            self._frames.append(frame)
        cap.release()
        if not self._frames:
            raise EngineError(f"Vídeo vazio ou ilegível: {self._path}", "replay_empty")
        self._t0 = time.perf_counter()
        height, width = self._frames[0].shape[:2]
        return dict(name=f"replay: {self._path}", width=width, height=height, fps=self._fps)

    def read(self):
        delay = self._t0 + self._n / self._fps - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        frame = self._frames[self._n % len(self._frames)].copy()
        self._n += 1
        return True, frame

    def close(self) -> None:
        self._frames = []


class CameraSource:
    """Webcam pelo capturador do fork (DirectShow com MJPG negociado na abertura)."""

    def __init__(self, camera: dict, width: int, height: int) -> None:
        self._camera, self._width, self._height = camera, width, height
        self._cap = None

    def open(self) -> dict:
        from modules.video_capture import VideoCapturer

        self._cap = VideoCapturer(self._camera["index"])
        if not self._cap.start(self._width, self._height, 60):
            self._cap = None
            raise EngineError(
                f"Não consegui abrir a câmera '{self._camera['name']}'. Ela provavelmente está em uso "
                "por outro programa (chamada de vídeo, aba do navegador, câmera virtual).", "camera_busy",
            )
        return dict(name=self._camera["name"], width=self._cap.actual_width,
                    height=self._cap.actual_height, fps=float(self._cap.actual_fps or 30.0))

    def read(self):
        return self._cap.read()

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None


class Recorder(threading.Thread):
    """Grava os quadros crus da câmera num .avi (MJPG) por um tempo fixo.

    Roda em thread própria, com fila: a compressão não pode atrasar a captura.
    Ao lado do vídeo fica um .json com o instante de cada quadro, para a
    reprodução usar o mesmo ritmo que a câmera teve.
    """

    QUALITY = 95

    def __init__(self, path: str, seconds: float, camera: dict) -> None:
        super().__init__(name="recorder", daemon=True)
        self.path, self._seconds, self._camera = path, seconds, camera
        self._queue: "queue.Queue" = queue.Queue(maxsize=120)
        self._started_at: Optional[float] = None
        self._done = threading.Event()
        self._dropped = 0

    @property
    def finished(self) -> bool:
        return self._done.is_set()

    def push(self, frame: np.ndarray, captured_at: float) -> None:
        """Chamado pela captura a cada quadro; ``frame`` já é uma cópia nossa."""
        if self._done.is_set():
            return
        if self._started_at is None:
            self._started_at = captured_at
            events.emit("recording", path=self.path, seconds=self._seconds)
        if captured_at - self._started_at >= self._seconds:
            self.finish()
            return
        try:
            self._queue.put_nowait((frame, captured_at - self._started_at))
        except queue.Full:
            self._dropped += 1

    def finish(self) -> None:
        if not self._done.is_set():
            self._done.set()
            self._queue.put(None)

    def run(self) -> None:
        import json
        import os

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        writer = None
        times: list = []
        while True:
            item = self._queue.get()
            if item is None:
                break
            frame, at = item
            if writer is None:
                height, width = frame.shape[:2]
                writer = cv2.VideoWriter(self.path, cv2.VideoWriter_fourcc(*"MJPG"),
                                         float(self._camera.get("fps") or 30.0), (width, height))
                writer.set(cv2.VIDEOWRITER_PROP_QUALITY, self.QUALITY)
            writer.write(frame)
            times.append(round(at, 4))
        if writer is not None:
            writer.release()
        duration = times[-1] if times else 0.0
        fps = (len(times) - 1) / duration if duration > 0 and len(times) > 1 else float(self._camera.get("fps") or 30.0)
        with open(self.path + ".json", "w", encoding="utf-8") as f:
            json.dump(dict(camera=self._camera, frames=len(times), seconds=duration, fps=fps,
                           dropped=self._dropped, times=times), f)
        events.emit("recorded", path=self.path, frames=len(times), seconds=duration, fps=fps,
                    dropped=self._dropped)


class CaptureThread(threading.Thread):
    def __init__(self, source, hub: FrameHub, stats: Stats, stop: threading.Event, mirror: bool,
                 recorder: Optional[Recorder] = None) -> None:
        super().__init__(name="capture", daemon=True)
        self._source, self._hub, self._stats, self._stop_event, self._mirror = source, hub, stats, stop, mirror
        self.recorder = recorder   # pode ser ligado depois, quando a prévia vira sessão ao vivo

    def run(self) -> None:
        seq = 0
        misses = 0
        while not self._stop_event.is_set():
            ok, frame = self._source.read()
            if not ok or frame is None:
                # Uma leitura falha costuma ser soluço (USB, outro app sondando
                # o dispositivo); só uma sequência delas significa câmera perdida.
                misses += 1
                self._stats.count("capture_miss")
                if misses >= MAX_MISSES:
                    # Encerra a sessão, não o motor: dá para tentar de novo.
                    events.error("A câmera parou de entregar quadros; outro programa pode tê-la tomado.",
                                 fatal=False, code="camera_lost")
                    self._stop_event.set()
                    break
                time.sleep(0.01)
                continue
            misses = 0
            now = time.perf_counter()
            recorder = self.recorder
            if recorder is not None and not recorder.finished:
                # Cópia própria e antes do espelhamento: o pipeline desenha em
                # ``frame`` logo em seguida, e a gravação guarda o que a câmera viu.
                recorder.push(frame.copy(), now)
            if self._mirror:
                frame = cv2.flip(frame, 1)
            self._hub.push(seq, frame, now)
            self._stats.count("captured")
            seq += 1
