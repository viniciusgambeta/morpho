"""Mede a pilha "ao vivo" COMPLETA do fork beekamai com uma câmera simulada.

`replay_bench.py` mede só o worker de processamento. Aqui roda tudo o que o
modo Live roda: thread de captura, worker de processamento e a janela de
preview com a reprojeção feita na thread da interface. A câmera é trocada por
uma que entrega os quadros do vídeo de teste no ritmo certo.

Serve para responder: quanto do FPS se perde só por a interface, a
reprojeção e a captura dividirem o processo com o pipeline?

    <fork>/venv/Scripts/python live_stack_bench.py --root <fork> \
        --video clip.avi --source rosto.jpg --tag nome --out resultados \
        -- --execution-provider cuda --face-swapper-model hyperswap_1a_256
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time


def _split_argv() -> tuple[list, list]:
    argv = sys.argv[1:]
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1:]
    return argv, []


OWN, PASSTHROUGH = _split_argv()
_p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
_p.add_argument("--root", required=True)
_p.add_argument("--video", required=True)
_p.add_argument("--source", required=True)
_p.add_argument("--fps", type=float, default=30.0, help="ritmo da câmera simulada")
_p.add_argument("--seconds", type=float, default=24.0, help="duração medida, depois do aquecimento")
_p.add_argument("--warm", type=float, default=6.0, help="segundos iniciais descartados")
_p.add_argument("--platform", default="offscreen", choices=["offscreen", "windows"],
                help="'windows' abre a janela de verdade na tela")
_p.add_argument("--window", default="960x540", help="tamanho da janela de preview")
_p.add_argument("--set", action="append", default=[], metavar="CHAVE=JSON")
_p.add_argument("--tag", default="live")
_p.add_argument("--out", default="results")
ARGS = _p.parse_args(OWN)
OUT, VIDEO, SOURCE, ROOT = (os.path.abspath(p) for p in (ARGS.out, ARGS.video, ARGS.source, ARGS.root))
os.makedirs(OUT, exist_ok=True)

os.environ["QT_QPA_PLATFORM"] = ARGS.platform
sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.argv = ["run.py"] + PASSTHROUGH

import run  # noqa: E402,F401

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import psutil  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402

import modules.globals as G  # noqa: E402
from modules import core, ui  # noqa: E402
import modules.reprojection as rp  # noqa: E402
from modules.processors.frame.core import get_frame_processors_modules  # noqa: E402

core.parse_args()
for _fp in get_frame_processors_modules(G.frame_processors):
    _pre = getattr(_fp, "pre_check", None)
    if _pre is not None and not _pre():
        sys.exit(f"pre_check falhou em {_fp.NAME}")
core.limit_resources()
ui.init(lambda: None, lambda: None, "en")

# Mesma base do replay_bench, independente do switch_states.json salvo pelo uso manual.
G.live_mirror = False
G.many_faces = False
G.map_faces = False
G.show_fps = False
G.virtual_camera = False
G.max_fps = 0
for _k in list(G.fp_ui):
    G.fp_ui[_k] = False
OVERRIDES = {}
for _item in ARGS.set:
    _key, _, _raw = _item.partition("=")
    if not hasattr(G, _key):
        sys.exit(f"modules.globals não tem '{_key}'")
    OVERRIDES[_key] = json.loads(_raw)
    setattr(G, _key, OVERRIDES[_key])
if not ui._accept_source_paths([SOURCE]):
    sys.exit(f"nenhum rosto em {SOURCE}")

print(f"[live-bench] lendo {VIDEO} ...", flush=True)
_cap = cv2.VideoCapture(VIDEO)
FRAMES: list = []
while True:
    _ok, _frame = _cap.read()
    if not _ok:
        break
    FRAMES.append(_frame)
_cap.release()
if not FRAMES:
    sys.exit(f"vídeo vazio: {VIDEO}")
FPS = ARGS.fps
T_READ: dict = {}      # seq -> instante em que a "câmera" entregou o quadro
RECORDS: list = []     # (seq, instante) de cada troca pronta
TICKS: list = []       # (instante, duração, seq exibido ou None)
STAGE: dict = {}       # etapa da thread da interface -> [tempo total, chamadas]


class FakeCapturer:
    """Entrega o vídeo em laço, um quadro a cada 1/FPS, como uma webcam."""

    def __init__(self, device_index):
        self.device_index = device_index
        self.actual_width = FRAMES[0].shape[1]
        self.actual_height = FRAMES[0].shape[0]
        self.actual_fps = FPS
        self._n = 0
        self._t0 = None

    def start(self, width=0, height=0, fps=0, on_wait=None) -> bool:
        self._t0 = time.perf_counter()
        return True

    def read(self):
        target = self._t0 + self._n / FPS
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        frame = FRAMES[self._n % len(FRAMES)].copy()
        T_READ[self._n] = time.perf_counter()
        self._n += 1
        return True, frame

    def release(self) -> None:
        pass


def _timed(name, fn):
    def wrapped(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            cell = STAGE.setdefault(name, [0.0, 0])
            cell[0] += time.perf_counter() - t
            cell[1] += 1
    return wrapped


class _Record(rp.ProcessedFrame):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        RECORDS.append((self.seq, time.perf_counter()))


ui.VideoCapturer = FakeCapturer
ui.is_virtual_output = lambda index: False
ui.ProcessedFrame = _Record
ui.fit_image_to_size = _timed("ui.redimensionar", ui.fit_image_to_size)
ui._bgr_to_qpixmap = _timed("ui.para_pixmap", ui._bgr_to_qpixmap)
rp.Reprojector.compose = _timed("ui.reprojecao", rp.Reprojector.compose)

_orig_tick = ui.WebcamPreviewWindow._tick


def _tick(self):
    before = self._shown_seq
    t = time.perf_counter()
    _orig_tick(self)
    now = time.perf_counter()
    TICKS.append((now, now - t, self._shown_seq if self._shown_seq != before else None))


ui.WebcamPreviewWindow._tick = _tick

GPU_ROWS: list = []


def _gpu_loop(halt: threading.Event) -> None:
    import subprocess

    while not halt.wait(1.0):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,clocks.gr,memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip().splitlines()[0]
            GPU_ROWS.append((time.perf_counter(),) + tuple(float(v) for v in out.split(",")))
        except Exception:
            pass


_halt = threading.Event()
threading.Thread(target=_gpu_loop, args=(_halt,), daemon=True).start()

proc = psutil.Process()
w, h = (int(v) for v in ARGS.window.split("x"))
window = ui.WebcamPreviewWindow(0)
window.resize(w, h)
window.show()
T_START = time.perf_counter()
CPU = {}


def _mark_warm() -> None:
    CPU["t0"] = time.perf_counter()
    CPU["cpu0"] = sum(proc.cpu_times()[:2])
    CPU["threads0"] = {t.id: t.user_time + t.system_time for t in proc.threads()}


def _finish() -> None:
    t1 = time.perf_counter()
    lo, hi = CPU["t0"], t1
    span = hi - lo
    cpu_total = sum(proc.cpu_times()[:2]) - CPU["cpu0"]
    per_thread = sorted(
        ((t.user_time + t.system_time - CPU["threads0"].get(t.id, 0.0)) / span * 100 for t in proc.threads()),
        reverse=True,
    )
    recs = [(s, t) for s, t in RECORDS if lo <= t <= hi]
    ticks = [x for x in TICKS if lo <= x[0] <= hi]
    shown = [x for x in ticks if x[2] is not None]
    swap_lat = np.array([t - T_READ[s] for s, t in recs if s in T_READ]) * 1000
    # Idade, ao ser exibido, do quadro de câmera sobre o qual a imagem foi montada.
    show_lat = np.array([x[0] - T_READ[x[2]] for x in shown if x[2] in T_READ]) * 1000
    gpu = [r for r in GPU_ROWS if lo <= r[0] <= hi]

    def pct(a, q):
        return float(np.percentile(a, q)) if len(a) else None

    result = dict(
        tag=ARGS.tag, cli=PASSTHROUGH, overrides=OVERRIDES, platform=ARGS.platform, window=ARGS.window,
        swapper_model=getattr(G, "face_swapper_model", None), camera_fps=FPS, measured_s=span,
        swap_fps=len(recs) / span,
        display_fps=len(shown) / span,
        swap_latency_ms=dict(p50=pct(swap_lat, 50), p95=pct(swap_lat, 95)),
        display_latency_ms=dict(p50=pct(show_lat, 50), p95=pct(show_lat, 95)),
        ui_tick=dict(
            ticks_per_s=len(ticks) / span,
            busy_pct=100 * sum(x[1] for x in ticks) / span,
            ms_when_showing=float(np.mean([x[1] for x in shown]) * 1000) if shown else None,
        ),
        ui_stage_ms_per_call={k: dict(ms=t * 1000 / max(c, 1), calls=c) for k, (t, c) in sorted(STAGE.items())},
        process_cpu_pct_of_one_core=100 * cpu_total / span,
        top_threads_cpu_pct=[round(v, 1) for v in per_thread[:8]],
        gpu=dict(util_mean_pct=float(np.mean([r[1] for r in gpu])) if gpu else None,
                 clock_min_mhz=min((r[2] for r in gpu), default=None),
                 clock_max_mhz=max((r[2] for r in gpu), default=None)),
    )
    with open(os.path.join(OUT, f"live_{ARGS.tag}.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    print("[live-bench] RESULT " + json.dumps(result), flush=True)
    os._exit(0)


QTimer.singleShot(int(ARGS.warm * 1000), _mark_warm)
QTimer.singleShot(int((ARGS.warm + ARGS.seconds) * 1000), _finish)
ui._APP.exec()
