"""Mede o pipeline "ao vivo" de um projeto derivado do Deep-Live-Cam, sem câmera.

Reproduz um vídeo gravado pelo mesmo `_ProcessingWorker` que o modo Live do
projeto usa (as mesmas filas, os mesmos modelos), em duas passadas:

  1. vazão:   todos os quadros, o mais rápido que o pipeline conseguir.
              Resultado = trocas de rosto novas por segundo.
  2. ritmada: quadros entregues no ritmo da câmera (30 fps), descartando o
              mais antigo quando o pipeline não acompanha, como o app faz.
              Resultado = fps entregue e latência captura -> quadro pronto.

A metodologia das passadas segue o `tools/replay_bench.py` do fork beekamai,
para que o mesmo procedimento valha para o original e para o fork.

Roda com o Python do venv do projeto medido:

    <projeto>/venv/Scripts/python replay_bench.py --root <projeto> \
        --flavor upstream|fork --video clip.avi --source rosto.jpg \
        --tag nome --out resultados -- --execution-provider cuda

Tudo depois de `--` vai para a linha de comando do próprio projeto.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time

T_PROCESS_START = time.perf_counter()


def _split_argv() -> tuple[list, list]:
    argv = sys.argv[1:]
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1:]
    return argv, []


def _parse(own: list) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", required=True, help="pasta do projeto medido")
    p.add_argument("--flavor", required=True, choices=["upstream", "fork"])
    p.add_argument("--video", required=True)
    p.add_argument("--source", required=True, help="foto do rosto de origem")
    p.add_argument("--fps", type=float, default=30.0, help="ritmo de câmera do vídeo")
    p.add_argument("--warm", type=float, default=3.0, help="segundos iniciais descartados")
    p.add_argument("--rest", default="3:11", help="trecho parado, a:b em segundos")
    p.add_argument("--motion", default="11:24", help="trecho em movimento, a:b em segundos")
    p.add_argument("--set", action="append", default=[], metavar="CHAVE=JSON",
                   help="sobrescreve modules.globals.CHAVE depois de carregar as opções")
    p.add_argument("--enhancer", default=None, help="chave em fp_ui a ligar (ex.: face_enhancer_gpen256)")
    p.add_argument("--preload-dlls", action="store_true",
                   help="chama onnxruntime.preload_dlls() (CUDA/cuDNN vindos dos pacotes nvidia-*)")
    p.add_argument("--tag", default="run")
    p.add_argument("--out", default="results")
    return p.parse_args(own)


OWN, PASSTHROUGH = _split_argv()
ARGS = _parse(OWN)
OUT = os.path.abspath(ARGS.out)
VIDEO = os.path.abspath(ARGS.video)
SOURCE = os.path.abspath(ARGS.source)
ROOT = os.path.abspath(ARGS.root)
os.makedirs(OUT, exist_ok=True)


# --------------------------------------------------------------------------
# GPU: memória e uso amostrados pelo nvidia-smi (processo à parte).
# --------------------------------------------------------------------------
def _gpu_sample() -> tuple | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu,temperature.gpu,power.draw,clocks.gr",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip().splitlines()[0]
        return tuple(float(v) for v in out.split(","))
    except Exception:
        return None


class GpuSampler(threading.Thread):
    def __init__(self, period: float = 1.0):
        super().__init__(daemon=True)
        self.period = period
        self.samples: list = []
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            s = _gpu_sample()
            if s is not None:
                self.samples.append((time.perf_counter(),) + s)
            self._halt.wait(self.period)

    def stop(self) -> None:
        self._halt.set()

    def window(self, t0: float, t1: float) -> dict | None:
        rows = [s for s in self.samples if t0 <= s[0] <= t1]
        if not rows:
            return None
        n = len(rows)
        return dict(samples=n, vram_peak_mib=max(r[1] for r in rows),
                    gpu_util_mean_pct=sum(r[2] for r in rows) / n,
                    temp_max_c=max(r[3] for r in rows), power_mean_w=sum(r[4] for r in rows) / n,
                    # Frequência do núcleo da GPU: se o mínimo e o máximo diferem muito, o
                    # perfil de energia do notebook mudou no meio da passada.
                    clock_min_mhz=min(r[5] for r in rows), clock_max_mhz=max(r[5] for r in rows))


GPU_BASELINE = _gpu_sample()  # antes de qualquer modelo ser carregado
SAMPLER = GpuSampler()
SAMPLER.start()

# --------------------------------------------------------------------------
# Sobe o projeto exatamente como o app sobe, mas sem janela.
# --------------------------------------------------------------------------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.argv = ["run.py"] + PASSTHROUGH

import run  # noqa: E402,F401  (só o preâmbulo de DLLs; core.run fica sob __main__)

if ARGS.preload_dlls:
    import onnxruntime as _ort

    _ort.preload_dlls()

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import onnxruntime  # noqa: E402

import modules.globals as G  # noqa: E402
from modules import core, ui  # noqa: E402
import modules.processors.frame.face_swapper as fs  # noqa: E402
from modules.processors.frame.core import get_frame_processors_modules  # noqa: E402

core.parse_args()
for _fp in get_frame_processors_modules(G.frame_processors):
    _pre = getattr(_fp, "pre_check", None)
    if _pre is not None and not _pre():
        sys.exit(f"pre_check falhou em {_fp.NAME}")
core.limit_resources()
ui.init(lambda: None, lambda: None, "en")

# Mesma base para todos: um rosto, sem espelho, sem contador desenhado.
G.live_mirror = False
G.many_faces = False
G.map_faces = False
G.show_fps = False
for _k in list(G.fp_ui):
    G.fp_ui[_k] = False
if ARGS.enhancer:
    if ARGS.enhancer not in G.fp_ui:
        sys.exit(f"enhancer desconhecido: {ARGS.enhancer} (opções: {sorted(G.fp_ui)})")
    G.fp_ui[ARGS.enhancer] = True
    if ARGS.enhancer not in G.frame_processors:
        G.frame_processors.append(ARGS.enhancer)
OVERRIDES = {}
for _item in ARGS.set:
    _key, _, _raw = _item.partition("=")
    if not hasattr(G, _key):
        sys.exit(f"modules.globals não tem '{_key}'")
    OVERRIDES[_key] = json.loads(_raw)
    setattr(G, _key, OVERRIDES[_key])

if ARGS.flavor == "fork":
    if not ui._accept_source_paths([SOURCE]):
        sys.exit(f"nenhum rosto em {SOURCE}")
else:
    G.source_path = SOURCE
INIT_S = time.perf_counter() - T_PROCESS_START  # imports + janela offscreen + rosto de origem

# --------------------------------------------------------------------------
# Perfil por etapa (só na passada de vazão).
# --------------------------------------------------------------------------
PROF: dict = {}
RECORD = {"on": False}
CUR = {"seq": -1}


def _timed(name, fn):
    def wrapped(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            if RECORD["on"]:
                cell = PROF.setdefault(name, [0.0, 0])
                cell[0] += time.perf_counter() - t
                cell[1] += 1
    return wrapped


def _hook(obj, attr: str, name: str) -> None:
    fn = getattr(obj, attr, None)
    if callable(fn):
        setattr(obj, attr, _timed(name, fn))


def _hook_profile() -> None:
    _hook(ui, "detect_one_face_fast", "detect")
    _hook(ui, "ensure_landmarks", "landmarks106")
    _hook(fs, "swap_face", "swap_face_total")
    _hook(fs, "apply_post_processing", "post")
    _hook(fs, "_fast_paste_back", "paste")
    _hook(fs, "_apply_poisson_blend", "poisson")
    _hook(fs, "_swap_aligned_face", "swap_model")            # original
    try:
        from insightface.model_zoo.inswapper import INSwapper

        if "get" in INSwapper.__dict__:
            INSwapper.get = _timed("INSwapper.get", INSwapper.__dict__["get"])
    except Exception:
        pass
    if ARGS.flavor == "fork":
        for modname, attr, name in (
            ("modules.head_geometry", "estimate", "head_pose"),
            ("modules.face_occluder", "get_occlusion_mask", "occluder"),
        ):
            try:
                _hook(__import__(modname, fromlist=["x"]), attr, name)
            except Exception:
                pass
        try:
            import modules.face_tracker as ft

            ft.FaceTracker.track = _timed("flow_track", ft.FaceTracker.track)
        except Exception:
            pass
        try:
            import modules.processors.frame.swapper_models as sm

            for clsname in dir(sm):
                cls = getattr(sm, clsname)
                if isinstance(cls, type) and "get" in cls.__dict__:
                    cls.get = _timed(f"{clsname}.get", cls.__dict__["get"])
        except Exception:
            pass
        try:
            from modules.processors.frame import _enhancer_processor as ep

            for clsname in dir(ep):
                cls = getattr(ep, clsname)
                if isinstance(cls, type) and "process_frame" in cls.__dict__:
                    cls.process_frame = _timed("enhancer", cls.__dict__["process_frame"])
        except Exception:
            pass


_hook_profile()


# --------------------------------------------------------------------------
# Filas: o fork troca (seq, quadro) e devolve um registro com .seq/.frame;
# o original troca quadros crus. As duas classes abaixo dão ao original a
# mesma contabilidade por quadro, sem tocar no código dele.
# --------------------------------------------------------------------------
class Rec:
    __slots__ = ("seq", "frame")

    def __init__(self, seq, frame):
        self.seq, self.frame = seq, frame


BARE = ARGS.flavor == "upstream"


class CaptureQueue(queue.Queue):
    def get(self, *a, **k):  # chamado pelo worker
        seq, frame = super().get(*a, **k)
        CUR["seq"] = seq
        return frame if BARE else (seq, frame)

    def drop_oldest(self) -> None:  # chamado pelo alimentador; não mexe em CUR
        try:
            queue.Queue.get(self, False)
        except queue.Empty:
            pass


class ProcessedQueue(queue.Queue):
    def put_nowait(self, item):  # chamado pelo worker
        if BARE:
            item = Rec(CUR["seq"], item)
        queue.Queue.put(self, item, False)


print(f"[bench] lendo {VIDEO} ...", flush=True)
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
WARM = int(ARGS.warm * FPS)
SAMPLE_EVERY = 10
KEEP_JPG = {int(s * FPS) for s in (5, 13.4, 16.6, 20)}  # parado + três poses em movimento


def run_pass(paced: bool):
    cq = CaptureQueue(maxsize=1 if paced else 2)
    pq = ProcessedQueue(maxsize=4)
    stop = threading.Event()
    worker = ui._ProcessingWorker(cq, pq, stop, FPS)
    sent: dict = {}
    got: list = []
    samples: dict = {}
    done = threading.Event()

    def consumer():
        while not done.is_set() or not pq.empty():
            try:
                r = pq.get(timeout=0.05)
            except queue.Empty:
                continue
            got.append((r.seq, time.perf_counter()))
            if not paced and (r.seq % SAMPLE_EVERY == 0 or r.seq in KEEP_JPG):
                samples[r.seq] = r.frame.copy()

    ct = threading.Thread(target=consumer)
    t_begin = time.perf_counter()
    worker.start()
    ct.start()
    t0 = time.perf_counter()
    for seq, original in enumerate(FRAMES):
        frame = original.copy()  # o worker escreve no quadro; o original fica intacto
        if paced:
            target = t0 + seq / FPS
            while time.perf_counter() < target:
                time.sleep(0.0005)
            if cq.full():  # descarta o mais antigo, como o worker de captura do app
                cq.drop_oldest()
            try:
                cq.put_nowait((seq, frame))
                sent[seq] = time.perf_counter()
            except queue.Full:
                pass
        else:
            cq.put((seq, frame))
            sent[seq] = time.perf_counter()
    while not cq.empty():
        time.sleep(0.01)
    time.sleep(0.5)
    done.set()
    ct.join()
    stop.set()
    worker.wait(5000)
    return sent, got, samples, t_begin, time.perf_counter()


def _span(name: str) -> tuple:
    a, b = (float(v) for v in getattr(ARGS, name).split(":"))
    return int(a * FPS), int(b * FPS)


def _rate(got: list, sent: dict, lo: int, hi: int) -> float | None:
    """Quadros prontos por segundo dentro do trecho [lo, hi) do vídeo."""
    rows = sorted((s, t) for s, t in got if lo <= s < hi)
    starts = [sent[s] for s in sent if lo <= s < hi]
    if len(rows) < 2 or not starts:
        return None
    return len(rows) / (rows[-1][1] - min(starts))


# Passada 1: vazão.
RECORD["on"] = True
sent1, got1, samples1, p1_t0, p1_t1 = run_pass(paced=False)
RECORD["on"] = False
first_frame_s = min(t for _, t in got1) - p1_t0  # carga dos modelos + primeira inferência
n = len(FRAMES)
throughput = _rate(got1, sent1, WARM, n)

# Troca aplicada? Compara a saída com o quadro original na mesma posição.
changed = []
for seq, out_frame in samples1.items():
    if seq >= WARM and out_frame.shape == FRAMES[seq].shape:
        diff = cv2.absdiff(out_frame, FRAMES[seq])
        changed.append(float((diff.max(axis=2) > 12).mean() * 100))  # % de pixels alterados
for seq in sorted(KEEP_JPG & set(samples1)):
    cv2.imwrite(os.path.join(OUT, f"frame_{ARGS.tag}_{seq:04d}.jpg"), samples1[seq])

# Passada 2: no ritmo da câmera.
sent2, got2, _, p2_t0, p2_t1 = run_pass(paced=True)
lat = np.array([t - sent2[s] for s, t in got2 if s in sent2 and s >= WARM]) * 1000
paced_fps = _rate(got2, sent2, WARM, n)
SAMPLER.stop()


def _providers() -> dict:
    found = {}
    try:
        from modules.face_analyser import get_face_analyser

        fa = get_face_analyser()
        for task, model in getattr(fa, "models", {}).items():
            sess = getattr(model, "session", None)
            if sess is not None:
                found[f"analyser.{task}"] = sess.get_providers()
    except Exception as error:
        found["analyser"] = f"erro: {error}"
    try:
        sw = fs.get_face_swapper()
        sess = getattr(sw, "session", None)
        found["swapper.class"] = type(sw).__name__
        if sess is not None and hasattr(sess, "get_providers"):
            found["swapper"] = sess.get_providers()
        elif sess is not None:
            found["swapper.session_class"] = type(sess).__name__
    except Exception as error:
        found["swapper"] = f"erro: {error}"
    return found


def _git_head() -> str:
    try:
        return subprocess.run(["git", "-C", ROOT, "log", "-1", "--format=%h %ad", "--date=short"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return "?"


rest, motion = _span("rest"), _span("motion")
vram_peak = max((s[1] for s in SAMPLER.samples), default=None)
result = dict(
    tag=ARGS.tag, flavor=ARGS.flavor, commit=_git_head(), cli=PASSTHROUGH, overrides=OVERRIDES,
    enhancer=ARGS.enhancer, preload_dlls=ARGS.preload_dlls,
    python=sys.version.split()[0], onnxruntime=onnxruntime.__version__,
    ort_available=onnxruntime.get_available_providers(), session_providers=_providers(),
    swapper_model=getattr(G, "face_swapper_model", "inswapper_128 (fixo)"),
    video=dict(frames=n, fps=FPS, size=[FRAMES[0].shape[1], FRAMES[0].shape[0]]),
    cold_start=dict(init_s=INIT_S, first_frame_s=first_frame_s, total_s=INIT_S + first_frame_s),
    throughput_fps=throughput,
    throughput_rest_fps=_rate(got1, sent1, *rest),
    throughput_motion_fps=_rate(got1, sent1, *motion),
    paced=dict(
        fps=paced_fps, fps_rest=_rate(got2, sent2, *rest), fps_motion=_rate(got2, sent2, *motion),
        delivered_pct=100 * len([1 for s, _ in got2 if s >= WARM]) / max(1, n - WARM),
        latency_ms=dict(p50=float(np.percentile(lat, 50)), p95=float(np.percentile(lat, 95)),
                        max=float(lat.max())) if len(lat) else None,
    ),
    swap_check=dict(
        sampled=len(changed),
        frames_changed_pct=100 * sum(1 for c in changed if c > 0.5) / max(1, len(changed)),
        mean_pixels_changed_pct=float(np.mean(changed)) if changed else None,
    ),
    profile_ms_per_call={k: dict(ms=t * 1000 / max(c, 1), calls=c) for k, (t, c) in sorted(PROF.items())},
    gpu=dict(
        baseline_vram_mib=GPU_BASELINE[0] if GPU_BASELINE else None,
        peak_vram_mib=vram_peak,
        delta_vram_mib=(vram_peak - GPU_BASELINE[0]) if (GPU_BASELINE and vram_peak is not None) else None,
        throughput_pass=SAMPLER.window(p1_t0, p1_t1),
        paced_pass=SAMPLER.window(p2_t0, p2_t1),
    ),
)
with open(os.path.join(OUT, f"bench_{ARGS.tag}.json"), "w", encoding="utf-8") as f:
    json.dump(result, f, indent=1)
print("[bench] RESULT " + json.dumps(result), flush=True)
os._exit(0)  # o Qt offscreen e as sessões dos modelos não precisam de encerramento ordenado
