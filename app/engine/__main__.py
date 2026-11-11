"""Entrada do processo do motor.

    <python do motor> -m app.engine --config <arquivo.json>

O motor carrega os modelos uma vez e fica em espera, com a câmera desligada,
até receber comandos. Fala com quem o iniciou por linhas JSON: eventos na
saída padrão (ver ``events.py``) e comandos na entrada padrão:

    {"cmd": "set_source", "paths": ["foto.jpg"]}     rosto de origem
    {"cmd": "preview", "camera": "HD Webcam", ...}   liga a câmera só para a prévia da janela, sem troca
    {"cmd": "start", "camera": "HD Webcam", ...}     ao vivo: troca e câmera virtual (ver SessionRequest)
    {"cmd": "stop"}                                  desliga a câmera, volta à espera
    {"cmd": "set_output", "virtual_camera": true, "protect": true, "force_blur": false}
    {"cmd": "set_option", "values": {"sharpness": 1.0}}   ajustes da troca (ver bridge.apply_options)
    {"cmd": "quit"}

Se a entrada padrão fechar, o motor encerra — assim a câmera nunca fica ligada
depois que a janela some.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import sys
import threading
import time


def _take_command_channel():
    """Separa o canal de comandos da entrada padrão do processo.

    No Windows, enquanto uma thread está parada lendo um pipe, qualquer
    processo-filho que herde esse mesmo pipe como entrada padrão trava ao
    iniciar (o ``nvidia-smi`` que o motor chama, por exemplo). Por isso os
    comandos passam a ser lidos de uma cópia privada, não herdável, e a
    entrada padrão do processo vira NUL — é isso que os filhos herdam.
    """
    command_fd = os.dup(0)
    null_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null_fd, 0)
    os.close(null_fd)
    sys.stdin = open(os.devnull, "r")
    return os.fdopen(command_fd, "r", encoding="utf-8", errors="replace")


def _read_commands(channel, inbox: "queue.Queue[dict]") -> None:
    for line in channel:
        try:
            command = json.loads(line)
        except ValueError:
            continue
        if isinstance(command, dict):
            inbox.put(command)
    inbox.put({"cmd": "quit"})  # quem nos iniciou foi embora


class SessionMode:
    """Prévia (imagem crua, só para a janela) ou ao vivo (troca, câmera virtual)."""

    def __init__(self, live: bool) -> None:
        self.live = live


class Session:
    """A câmera ligada: em prévia ou ao vivo, até ser desligada."""

    def __init__(self, request, live, pipeline, writer, camera_writer, stats, options, vcam, dump) -> None:
        from app.engine import bridge, events
        from app.engine.capture import CameraSource, CaptureThread, FrameHub, Recorder, ReplaySource
        from app.engine.compose import ComposeThread
        from app.engine.config import RESOLUTIONS
        from app.engine.stats import GpuProbe

        self._pipeline, self._events, self._vcam, self._stats = pipeline, events, vcam, stats
        self.key = self.key_of(request)
        self.mode = SessionMode(live)
        self.stop = threading.Event()
        self.recorder = None
        if request.replay:
            replay = os.path.abspath(request.replay)
            fps = request.replay_fps
            if fps is None:
                # Uma gravação nossa traz o ritmo real da câmera no .json ao lado.
                try:
                    with open(replay + ".json", encoding="utf-8") as f:
                        fps = float(json.load(f)["fps"])
                except (OSError, ValueError, KeyError):
                    fps = 30.0
            self.source = ReplaySource(replay, fps)
        else:
            width, height = RESOLUTIONS.get(request.resolution, RESOLUTIONS["720p"])
            self.source = CameraSource(bridge.resolve_camera(request.camera), width, height)
        self.camera = self.source.open()   # pode levantar EngineError (câmera ocupada, etc.)

        self.hub = FrameHub()
        stats.snapshot()   # zera o que sobrou da sessão anterior
        self._capture = CaptureThread(self.source, self.hub, stats, self.stop, request.mirror, None)
        self._threads = [
            self._capture,
            ComposeThread(self.hub, writer, camera_writer, stats, self.stop, options, vcam,
                          float(self.camera["fps"] or 30.0), self.mode, dump),
            GpuProbe(stats, self.stop),
        ]
        if live:
            self._enter_live(request)
        for thread in self._threads:
            thread.start()

    @staticmethod
    def key_of(request) -> tuple:
        """O que identifica a câmera aberta: mudou isto, a câmera precisa ser reaberta."""
        source = ("replay", os.path.abspath(request.replay)) if request.replay else ("camera", str(request.camera))
        return source + (request.resolution, bool(request.mirror))

    def _enter_live(self, request) -> None:
        from app.engine.capture import Recorder

        if request.record_path and self.recorder is None:
            self.recorder = Recorder(os.path.abspath(request.record_path), request.record_seconds, self.camera)
            self.recorder.start()
            self._capture.recorder = self.recorder
        self.hub.clear_record()
        self._pipeline.attach(self.hub)
        self.mode.live = True

    def go_live(self, request) -> None:
        """Da prévia para ao vivo, sem reabrir a câmera."""
        self._stats.snapshot()
        self._enter_live(request)

    def go_preview(self) -> None:
        """De ao vivo para prévia: a câmera continua, a troca e a câmera virtual param."""
        self.mode.live = False
        self._pipeline.detach()
        self._vcam.close()
        self.hub.clear_record()

    def close(self) -> None:
        self.stop.set()
        self._pipeline.detach()
        for thread in self._threads:
            thread.join(2.0)
        self._vcam.close()   # câmera desligada: a câmera virtual também para de transmitir
        if self.recorder is not None:
            self.recorder.finish()   # parou antes do tempo: grava o que já tem
            self.recorder.join(10)
        self.source.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True)
    config_path = os.path.abspath(parser.parse_args().config)
    channel = _take_command_channel()

    # Importados antes de entrar na pasta do motor do fork.
    from app.engine import bridge, events
    from app.engine.config import EngineConfig, SessionRequest
    from app.engine.output import OutputOptions, VirtualCamera, probe_virtual_camera
    from app.engine.pipeline import PipelineThread
    from app.engine.stats import Stats, read_gpu
    from app.engine.trackdump import TrackDump
    from app.shared_frame import FrameWriter

    cfg = EngineConfig.load(config_path)
    inbox: "queue.Queue[dict]" = queue.Queue()
    threading.Thread(target=_read_commands, args=(channel, inbox), name="commands", daemon=True).start()

    events.status("starting", "Iniciando o motor")
    stop = threading.Event()
    writer = None
    camera_writer = None
    session = None
    dump = None
    try:
        if shutil.which("nvidia-smi") is None:
            # Sem o driver da NVIDIA a troca cairia para o processador: uns poucos quadros por
            # segundo, sem explicação. Melhor dizer logo o que falta.
            raise bridge.EngineError("Não encontrei uma placa de vídeo NVIDIA com o driver instalado. "
                                     "O Morpho precisa de uma para fazer a troca de rosto.", "no_gpu")
        bridge.setup(cfg)
        stats = Stats()
        dump = TrackDump.from_env()
        options = OutputOptions()
        vcam = VirtualCamera()
        pipeline = PipelineThread(cfg, stats, stop, options, dump)
        pipeline.start()
        quitting = False
        backlog: list = []   # comandos que chegaram durante a carga, na ordem
        while not pipeline.loaded.wait(0.2):
            # Durante a carga só "quit" é atendido na hora; o resto espera a vez.
            while True:
                try:
                    pending = inbox.get_nowait()
                except queue.Empty:
                    break
                if pending.get("cmd") == "quit":
                    return 0
                backlog.append(pending)
        if pipeline.failure is not None:
            raise pipeline.failure
        writer = FrameWriter(cfg.shm_name)                 # a saída: o que vai para a câmera virtual
        camera_writer = FrameWriter(cfg.shm_name + "_cam")   # a câmera crua, pequena, para a barra lateral
        events.emit("loaded", seconds=pipeline.load_seconds, shm=cfg.shm_name, shm_camera=cfg.shm_name + "_cam",
                    model=cfg.model,
                    tensorrt=cfg.tensorrt, gpu=read_gpu(), virtual_camera=probe_virtual_camera())
        events.status("idle")

        last_stats = time.perf_counter()
        while not quitting and not stop.is_set():
            if backlog:
                command = backlog.pop(0)
            else:
                try:
                    command = inbox.get(timeout=0.2)
                except queue.Empty:
                    command = None
            name = (command or {}).get("cmd")
            if name == "quit":
                quitting = True
            elif name == "set_source":
                pipeline.request_source([os.path.abspath(p) for p in command.get("paths", [])])
            elif name == "set_output":
                # Vale na hora, ao vivo ou em espera (aí fica valendo para o próximo Iniciar).
                if "virtual_camera" in command:
                    options.virtual_camera = bool(command["virtual_camera"])
                if "protect" in command:
                    options.protect = bool(command["protect"])
                if "force_blur" in command:
                    options.force_blur = bool(command["force_blur"])
            elif name == "set_option":
                events.emit("options", values=bridge.apply_options(command.get("values") or {}))
            elif name == "stop":
                if session is not None:
                    events.status("stopping")
                    session.close()
                    session = None
                events.status("idle")
            elif name in ("preview", "start"):
                # "preview" liga a câmera só para a janela; "start" liga a troca. Se a
                # câmera pedida já está aberta, a passagem é imediata, sem reabri-la.
                want_live = name == "start"
                request = SessionRequest.from_command(command)
                if want_live:
                    if request.virtual_camera is not None:
                        options.virtual_camera = request.virtual_camera
                    if request.protect is not None:
                        options.protect = request.protect
                if session is not None and session.key != Session.key_of(request):
                    events.status("stopping")
                    session.close()
                    session = None
                try:
                    if session is None:
                        events.status("opening_camera", "Abrindo a câmera")
                        session = Session(request, want_live, pipeline, writer, camera_writer, stats, options, vcam, dump)
                        events.emit("ready", camera=session.camera, has_source=pipeline.has_source)
                    elif want_live and not session.mode.live:
                        session.go_live(request)
                    elif not want_live and session.mode.live:
                        session.go_preview()
                except bridge.EngineError as error:
                    # A câmera não abriu, mas o motor segue pronto para outra tentativa.
                    events.error(str(error), fatal=False, code=error.code)
                    events.status("idle")
                else:
                    events.status("running" if want_live else "preview")
                    last_stats = time.perf_counter()

            if session is not None:
                if session.stop.is_set():
                    # A captura desistiu (câmera perdida): a sessão acaba, o motor não.
                    session.close()
                    session = None
                    events.status("idle")
                elif time.perf_counter() - last_stats >= 1.0:
                    last_stats = time.perf_counter()
                    events.emit("stats", camera_fps=session.camera["fps"],
                                mode="live" if session.mode.live else "preview", **stats.snapshot())
    except bridge.EngineError as error:
        events.error(str(error), fatal=True, code=error.code)
        return 2
    except Exception as error:
        import traceback

        traceback.print_exc()
        events.error(f"Erro inesperado no motor: {error}", fatal=True, code="unexpected")
        return 3
    finally:
        events.status("stopping")
        if session is not None:
            session.close()
        stop.set()
        time.sleep(0.1)  # deixa a thread do pipeline largar o que estiver fazendo
        for shared in (writer, camera_writer):
            if shared is not None:
                shared.close()
        if dump is not None:
            dump.close()
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)  # as sessões dos modelos e o Qt importado pelo fork não precisam de encerramento ordenado
