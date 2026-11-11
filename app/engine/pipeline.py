"""A thread do pipeline: detectar/rastrear -> landmarks -> pose -> trocar -> publicar.

Vive enquanto o motor vive. Carrega os modelos uma vez e depois alterna entre
duas situações: em espera (sem sessão, só atende pedidos de troca do rosto de
origem) e ao vivo (processa os quadros da sessão atual).

O laço segue o ``_ProcessingWorker`` do fork para um rosto só, sem Qt. Todo o
trabalho de GPU fica nesta thread, inclusive a carga dos modelos e a análise
das fotos de origem: os grafos CUDA do fork são capturados no primeiro uso e
quebram se outra thread estiver na GPU ao mesmo tempo.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import List, Optional

import numpy as np

from app.engine import bridge, events
from app.engine.capture import FrameHub
from app.engine.config import EngineConfig
from app.engine.output import OutputOptions
from app.engine.stats import Stats

# Com rastreamento, a detecção roda ~4x por segundo e o fluxo óptico leva o
# rosto entre uma e outra; sem ele, ~12x por segundo.
DETECT_PERIOD_TRACKED = 0.25
DETECT_PERIOD_UNTRACKED = 0.08
# Se o pipeline pulou este tanto de quadros de câmera, o fluxo já errou demais.
REDETECT_AFTER_SKIPPED = 3
# Mesmo corte do motor: abaixo disto ele devolve o quadro sem trocar.
SWAP_HIDDEN_BELOW = 0.01
# Com mais de um rosto no quadro, o que já está sendo seguido continua sendo o
# escolhido enquanto tiver pelo menos esta fração da área do maior. Evita ficar
# alternando entre dois rostos de tamanho parecido.
STICKY_AREA_RATIO = 0.6


def _area(face) -> float:
    x0, y0, x1, y1 = face.bbox[:4]
    return float(max(0.0, x1 - x0) * max(0.0, y1 - y0))


def choose_face(candidates, tracked_bbox):
    """O rosto a trocar: o maior do quadro, com preferência pelo já seguido.

    Devolve (rosto, se é o mesmo que vinha sendo seguido). O motor do fork pega
    o rosto mais à esquerda, o que faz um retrato na parede ou uma foto ao
    fundo "roubar" a troca. Numa webcam, quem está usando é quem aparece maior.
    """
    if not candidates:
        return None, False
    largest = max(candidates, key=_area)
    if tracked_bbox is None:
        return largest, False
    cx = (tracked_bbox[0] + tracked_bbox[2]) / 2.0
    cy = (tracked_bbox[1] + tracked_bbox[3]) / 2.0
    same = [f for f in candidates if f.bbox[0] <= cx <= f.bbox[2] and f.bbox[1] <= cy <= f.bbox[3]]
    if same:
        current = max(same, key=_area)
        if current is largest or _area(current) >= STICKY_AREA_RATIO * _area(largest):
            return current, True
    return largest, False


class PipelineThread(threading.Thread):
    def __init__(self, cfg: EngineConfig, stats: Stats, stop: threading.Event, options: OutputOptions,
                 dump=None) -> None:
        super().__init__(name="pipeline", daemon=True)
        self._cfg, self._stats, self._stop_event = cfg, stats, stop
        self._options = options
        self._dump = dump   # TrackDump opcional, só para medir o descolamento
        self.loaded = threading.Event()
        self.failure: Optional[bridge.EngineError] = None
        self.load_seconds = 0.0
        self._hub: Optional[FrameHub] = None            # sessão ao vivo atual, se houver
        self._source_requests: "queue.Queue[List[str]]" = queue.Queue()
        self._identity = None

    # chamados pela thread principal -----------------------------------------
    def attach(self, hub: FrameHub) -> None:
        self._hub = hub

    def detach(self) -> None:
        self._hub = None

    def request_source(self, paths: List[str]) -> None:
        self._source_requests.put(list(paths))

    @property
    def has_source(self) -> bool:
        return self._identity is not None

    # carga -------------------------------------------------------------------
    def _load(self) -> None:
        from modules import head_geometry
        from modules.face_analyser import get_face_analyser

        started = time.perf_counter()
        events.status("loading", "Preparando o modelo de troca de rosto")
        bridge.ensure_swapper_model()
        events.status("loading", "Carregando o detector de rosto")
        get_face_analyser()
        events.status("loading", "Carregando o modelo de troca de rosto")
        bridge.load_swapper()
        # Carregado já: senão o primeiro "Iniciar" engasga uns segundos nisto.
        head_geometry.get_provider()
        self.load_seconds = time.perf_counter() - started

    def _serve_source_requests(self) -> None:
        """Analisa as fotos pedidas; só o último pedido pendente interessa."""
        paths = None
        while True:
            try:
                paths = self._source_requests.get_nowait()
            except queue.Empty:
                break
        if paths is None:
            return
        try:
            identity, skipped, padded = bridge.load_identity(paths)
        except bridge.EngineError as error:
            # A foto não serve: o rosto anterior, se havia, continua valendo.
            events.emit("source", ok=False, requested=paths, message=str(error), code=error.code,
                        kept_previous=self._identity is not None)
            return
        except Exception as error:
            events.emit("source", ok=False, requested=paths, message=f"Não consegui ler a foto: {error}",
                        code="source_failed", kept_previous=self._identity is not None)
            return
        self._identity = identity
        events.emit("source", ok=True, requested=paths, used=list(identity.paths), skipped=skipped, padded=padded)

    # laço --------------------------------------------------------------------
    def run(self) -> None:
        try:
            self._load()
        except bridge.EngineError as error:
            self.failure = error
            self.loaded.set()
            return
        except Exception as error:  # falha inesperada do motor: mostra em vez de sumir
            self.failure = bridge.EngineError(f"Falha ao carregar o motor: {error}", "load_failed")
            self.loaded.set()
            return
        self.loaded.set()
        try:
            self._loop()
        except Exception as error:
            # Sem isto a thread morreria calada e a janela ficaria parada no último quadro.
            import traceback

            traceback.print_exc()
            events.error(f"O pipeline parou por um erro: {error}", fatal=True, code="pipeline_crash")
            self._stop_event.set()

    def _loop(self) -> None:
        import modules.globals as G
        import modules.processors.frame.face_swapper as fs
        from modules import calibration, head_geometry
        from modules.face_analyser import detect_many_faces_fast, ensure_landmarks
        from modules.face_tracker import FaceTracker
        from modules.reprojection import ProcessedFrame, collect_paste_alpha

        stats = self._stats
        tracker = FaceTracker()
        session_hub = None      # sessão para a qual o estado abaixo vale
        face = None
        last_detection = 0.0
        last_seq = -1

        while not self._stop_event.is_set():
            self._serve_source_requests()
            hub = self._hub
            if hub is None or self._identity is None:
                session_hub = None
                time.sleep(0.02)
                continue
            if hub is not session_hub:
                # Sessão nova: nada do rastreamento da anterior se aproveita.
                session_hub = hub
                tracker.reset()
                face = None
                last_detection = 0.0
                last_seq = -1
            try:
                seq, frame, captured_at = hub.queue.get(timeout=0.05)
            except queue.Empty:
                continue
            identity = self._identity
            with stats.stage("pipeline"):
                tracking = G.face_tracking
                period = DETECT_PERIOD_TRACKED if tracking else DETECT_PERIOD_UNTRACKED
                if tracking and tracker.unsettled:
                    # Cabeça rápida ou detecção que o fluxo não previu: detecta a
                    # cada quadro até o rastreador assentar.
                    period = 0.0
                detected = (time.perf_counter() - last_detection >= period
                            or seq - last_seq >= REDETECT_AFTER_SKIPPED)
                last_seq = seq
                if detected:
                    last_detection = time.perf_counter()
                    tracked_bbox = getattr(face, "bbox", None) if face is not None else None
                    with stats.stage("detect"):
                        candidates = detect_many_faces_fast(frame) or []
                    stats.sample("faces_in_frame", float(len(candidates)))
                    face, same = choose_face(candidates, tracked_bbox)
                    if tracking and face is not None and tracked_bbox is not None and not same:
                        # Passou para outro rosto: o rastreador recomeça, em vez de
                        # "deslizar" a suavização do rosto antigo até o novo.
                        tracker.reset()
                        stats.count("face_switches")
                    if tracking:
                        with stats.stage("track"):
                            face = tracker.observe(frame, face)
                elif tracking and face is not None:
                    with stats.stage("track"):
                        face = tracker.track(frame, face)

                if face is not None and self._options.protect:
                    # Quando o detector perde o rosto, o rastreador do fork ainda o
                    # carrega por 1 s com a troca esmaecendo — ou seja, o rosto real
                    # aparecendo por baixo. Com a proteção ligada a troca fica opaca
                    # enquanto é carregada; depois disso a saída é borrada.
                    face.track_alpha = 1.0
                faces = [face] if face is not None else None
                if faces and (G.mouth_mask or G.face_outline_mask or G.blink_reveal or G.eye_reveal > 0):
                    with stats.stage("landmarks"):
                        ensure_landmarks(frame, faces)
                if faces:
                    with stats.stage("head_pose"):
                        head_geometry.estimate(frame, faces)

                bboxes = []
                applied = False
                if face is not None:
                    # O motor esconde a troca (e nem roda o modelo) quando a
                    # "intensidade" cai a zero: rosto perdido pelo detector ou
                    # cabeça além dos limites de ângulo. Medimos isso, porque
                    # de fora o efeito é idêntico a "não funcionou".
                    strength = float(calibration.swap_alpha(face))
                    applied = strength > SWAP_HIDDEN_BELOW
                    stats.sample("swap_strength", strength)
                    head = getattr(face, "head_pose", None)
                    if head is not None:
                        stats.sample("head_yaw", float(head.yaw))
                        stats.sample("head_pitch", float(head.pitch))
                        stats.sample("head_roll", float(head.roll))
                    with stats.stage("swap"):
                        frame = fs.swap_face(identity, face, frame)
                    bbox = getattr(face, "bbox", None)
                    if bbox is not None:
                        bboxes.append(bbox.astype(int))
                        stats.sample("face_height", float(bbox[3] - bbox[1]))
                else:
                    stats.count("no_face")
                with stats.stage("post"):
                    frame = fs.apply_post_processing(frame, bboxes)

                record = ProcessedFrame(seq, frame, detected=detected)
                record.swapped = applied   # a composição decide o que fazer com um quadro sem troca
                if G.reprojection and face is not None:
                    paste = collect_paste_alpha(frame.shape)
                    if paste is not None:
                        record.kps = np.asarray(face.kps, dtype=np.float32).copy()
                        bbox = getattr(face, "bbox", None)
                        record.bbox = None if bbox is None else np.asarray(bbox, dtype=np.float32).copy()
                        record.box, record.alpha = paste
            if self._dump is not None:
                self._dump.write(k="swap", seq=seq, t=time.perf_counter(), det=detected, applied=applied,
                                 kps=self._dump.kps(getattr(face, "kps", None) if face is not None else None))
            hub.publish(record)
            stats.count("processed")
            if applied:
                stats.count("swapped")
            elif face is not None:
                stats.count("swap_hidden")
            stats.sample("swap_latency", (time.perf_counter() - captured_at) * 1000)
