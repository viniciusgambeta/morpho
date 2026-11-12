"""A thread de composição: monta o quadro de saída no ritmo da câmera.

A troca de um quadro fica pronta dezenas de milissegundos depois da captura,
e a cabeça já se moveu. Em vez de mostrar o quadro antigo, a reprojeção do
fork leva a última troca pronta para onde o rosto está no quadro mais novo
(rastreando por fluxo óptico nos quadros crus). A posição fica com no máximo
um quadro de atraso; só a expressão carrega a latência do pipeline.

No fork isso roda na thread da interface. Aqui roda no motor, para a saída
(janela, e depois a câmera virtual) não depender de nenhuma janela.
"""
from __future__ import annotations

import threading
import time

import cv2
import numpy as np

from app.engine.capture import FrameHub
from app.engine.output import FaceGuard, OutputOptions, VirtualCamera, blurred
from app.engine.stats import Stats
from app.shared_frame import FrameWriter


CAMERA_VIEW_WIDTH = 480      # largura da imagem da câmera mostrada na barra lateral
CAMERA_VIEW_LIVE_FPS = 15    # ao vivo, a prévia da câmera não precisa de todos os quadros


def camera_view(raw: np.ndarray) -> np.ndarray:
    """O quadro cru reduzido para a prévia pequena da janela."""
    height, width = raw.shape[:2]
    step = max(1, width // (CAMERA_VIEW_WIDTH * 2))   # descarta linhas e colunas antes de filtrar: barato
    if step > 1:
        raw = raw[::step, ::step]
        height, width = raw.shape[:2]
    if width <= CAMERA_VIEW_WIDTH:
        return np.ascontiguousarray(raw)
    size = (CAMERA_VIEW_WIDTH, max(2, int(round(height * CAMERA_VIEW_WIDTH / width))))
    return cv2.resize(raw, size, interpolation=cv2.INTER_AREA)


class ComposeThread(threading.Thread):
    def __init__(self, hub: FrameHub, writer: FrameWriter, camera_writer: FrameWriter, stats: Stats,
                 stop: threading.Event, options: OutputOptions, vcam: VirtualCamera, camera_fps: float,
                 mode, dump=None) -> None:
        super().__init__(name="compose", daemon=True)
        self._hub, self._writer, self._stats, self._stop_event = hub, writer, stats, stop
        self._camera_writer = camera_writer   # a imagem crua, pequena, que só a janela mostra
        self._options, self._vcam, self._camera_fps = options, vcam, camera_fps
        self._mode = mode   # .live: False = prévia (só a imagem da câmera, sem troca e sem saída)
        self._dump = dump   # TrackDump opcional, só para medir o descolamento

    def run(self) -> None:
        try:
            self._loop()
        except Exception as error:
            import traceback

            from app.engine import events

            traceback.print_exc()
            events.error(f"A composição da saída parou por um erro: {error}", fatal=False, code="compose_crash")
            self._stop_event.set()

    def _loop(self) -> None:
        import modules.globals as G
        from modules.reprojection import Reprojector

        hub, stats, options, vcam = self._hub, self._stats, self._options, self._vcam
        reprojector = Reprojector()
        guard = FaceGuard()
        shown_seq = -1
        newest_out = -1
        previewed = -1

        previewed_at = 0.0

        while not self._stop_event.is_set():
            if not hub.wake.wait(0.05):
                continue
            hub.wake.clear()
            # A imagem crua da câmera vai, pequena, só para a barra lateral da janela:
            # serve para reconhecer a câmera e se enquadrar. Nunca para a câmera virtual.
            seq = hub.latest_seq
            now = time.perf_counter()
            if seq != previewed and (not self._mode.live or now - previewed_at >= 1.0 / CAMERA_VIEW_LIVE_FPS):
                raw = hub.raw(seq)
                if raw is not None:
                    previewed, previewed_at = seq, now
                    self._camera_writer.write(camera_view(raw), seq, time.time())
                    stats.count("previewed")
            if not self._mode.live:
                # Prévia: sem troca e sem saída.
                if vcam.active:
                    vcam.close()
                shown_seq = newest_out = -1
                guard.reset()
                continue
            record, fresh = hub.take_record()
            if record is None:
                continue  # nada sai antes da primeira troca: a saída nunca mostra o rosto cru sozinho
            latest_seq = hub.latest_seq
            if G.reprojection and record.kps is not None:
                if not fresh and latest_seq <= shown_seq:
                    continue
                with stats.stage("compose"):
                    frame = reprojector.compose(record, hub.ring_view(), latest_seq)
                # compose devolve o próprio quadro processado quando não há o que mover
                out_seq = record.seq if frame is record.frame else max(latest_seq, record.seq)
                shown_seq = max(latest_seq, record.seq)
            else:
                if not fresh:
                    continue
                frame = record.frame
                out_seq = shown_seq = record.seq
            captured_at = hub.captured_at(out_seq)
            now = time.perf_counter()
            if self._dump is not None:
                moved = frame is not record.frame
                shown = None
                if moved:
                    # Onde a reprojeção desenhou o rosto: posição rastreada + correção em curso.
                    tracked = getattr(getattr(reprojector, "_face", None), "kps", None)
                    if tracked is not None:
                        shown = np.asarray(tracked, dtype=np.float32) + reprojector._applied
                    self._dump.reprojected(out_seq, frame)
                else:
                    self._dump.exact(record.seq, frame, record.box)
                self._dump.write(k="out", seq=out_seq, src=record.seq, mode="reproj" if moved else "exact",
                                 t=now, age_ms=None if captured_at is None else (now - captured_at) * 1000,
                                 kps=self._dump.kps(shown))
            if options.force_blur:
                # Pausa de privacidade pedida na tela: tudo borrado até segunda ordem.
                frame = blurred(frame)
                stats.count("protected")
            elif getattr(record, "passthrough", False):
                # "Sem rosto", escolhido pela pessoa: a imagem sai como é, de propósito.
                guard.reset()
            elif options.protect:
                # Sem troca neste quadro, o que sai não pode ser o rosto real: vale
                # para a janela também, que mostra exatamente o que os outros veem.
                frame, protected = guard.filter(frame, bool(getattr(record, "swapped", False)))
                if protected:
                    stats.count("protected")
            with stats.stage("publish"):
                wall = time.time() - (now - captured_at) if captured_at is not None else time.time()
                self._writer.write(frame, out_seq, wall)
            if options.virtual_camera:
                with stats.stage("virtual_camera"):
                    vcam.send(frame, self._camera_fps)
            elif vcam.active:
                vcam.close()
            stats.count("output_writes")
            if out_seq > newest_out:
                # Um mesmo quadro de câmera pode sair duas vezes (quando chega e
                # quando a troca seguinte fica pronta). A taxa e a latência de
                # saída contam só a primeira vez que cada quadro aparece.
                newest_out = out_seq
                stats.count("output")
                if captured_at is not None:
                    stats.sample("output_latency", (time.perf_counter() - captured_at) * 1000)
