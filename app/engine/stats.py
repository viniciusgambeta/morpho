"""Medição contínua do motor: taxas, latências, tempo por etapa e estado da GPU.

Tudo é acumulado por janela e zerado a cada ``snapshot()`` (uma vez por
segundo), para os números refletirem o agora e não a média desde o início.
"""
from __future__ import annotations

import subprocess
import threading
import time
from contextlib import contextmanager
from typing import Dict, List, Optional

_GPU_FIELDS = (
    "utilization.gpu,clocks.gr,clocks.max.gr,pstate,memory.used,memory.total,power.draw,temperature.gpu,"
    "clocks_event_reasons.sw_thermal_slowdown,clocks_event_reasons.sw_power_cap,clocks_event_reasons.hw_slowdown"
)
# Com carga de verdade e o clock abaixo desta fração do máximo, a placa está
# sendo segurada (perfil de energia do notebook, bateria, temperatura).
THROTTLE_CLOCK_RATIO = 0.6
THROTTLE_MIN_UTIL = 50.0


def _percentile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q / 100.0 * (len(ordered) - 1))))]


class Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._since = time.perf_counter()
        self._counts: Dict[str, int] = {}
        self._stage: Dict[str, List[float]] = {}     # etapa -> [segundos, chamadas]
        self._samples: Dict[str, List[float]] = {}   # nome -> amostras em ms
        self.gpu: Optional[dict] = None

    def count(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + n

    def sample(self, name: str, milliseconds: float) -> None:
        with self._lock:
            self._samples.setdefault(name, []).append(milliseconds)

    @contextmanager
    def stage(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            with self._lock:
                cell = self._stage.setdefault(name, [0.0, 0])
                cell[0] += elapsed
                cell[1] += 1

    def snapshot(self) -> dict:
        """Os números da janela que passou; zera os acumuladores."""
        now = time.perf_counter()
        with self._lock:
            span = max(now - self._since, 1e-6)
            counts, stages, samples = self._counts, self._stage, self._samples
            self._counts, self._stage, self._samples = {}, {}, {}
            self._since = now
        def spread(name: str) -> Optional[dict]:
            values = samples.get(name)
            if not values:
                return None
            return dict(p50=_percentile(values, 50), min=min(values), max=max(values))

        return dict(
            span_s=span,
            capture_fps=counts.get("captured", 0) / span,
            processed_fps=counts.get("processed", 0) / span,   # quadros que passaram pelo pipeline
            swap_fps=counts.get("swapped", 0) / span,          # quadros em que a troca foi de fato aplicada
            swap_hidden_fps=counts.get("swap_hidden", 0) / span,  # rosto achado, mas troca escondida pelo motor
            passthrough_fps=counts.get("passthrough", 0) / span,  # "sem rosto": quadros que saíram como vieram
            swap_strength=spread("swap_strength"),
            head=dict(yaw=spread("head_yaw"), pitch=spread("head_pitch"), roll=spread("head_roll")),
            face_height_px=spread("face_height"),
            faces_in_frame=spread("faces_in_frame"),            # rostos vistos pelo detector
            face_switches=counts.get("face_switches", 0),       # vezes em que o rosto escolhido mudou
            output_fps=counts.get("output", 0) / span,                # quadros de câmera distintos na saída
            output_writes_fps=counts.get("output_writes", 0) / span,  # inclui recomposições do mesmo quadro
            protected_fps=counts.get("protected", 0) / span,          # quadros sem troca, enviados borrados ou repetidos
            preview_fps=counts.get("previewed", 0) / span,            # quadros crus mostrados na prévia
            frames_without_face=counts.get("no_face", 0),
            capture_misses=counts.get("capture_miss", 0),
            swap_latency_ms=dict(p50=_percentile(samples.get("swap_latency", []), 50),
                                 p95=_percentile(samples.get("swap_latency", []), 95)),
            output_latency_ms=dict(p50=_percentile(samples.get("output_latency", []), 50),
                                   p95=_percentile(samples.get("output_latency", []), 95)),
            # ms por chamada e chamadas por segundo de cada etapa
            stages={name: dict(ms=cell[0] * 1000 / max(cell[1], 1), per_s=cell[1] / span,
                               busy_pct=cell[0] / span * 100)
                    for name, cell in sorted(stages.items())},
            gpu=self.gpu,
        )


def read_gpu() -> Optional[dict]:
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={_GPU_FIELDS}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip().splitlines()[0]
        v = [x.strip() for x in out.split(",")]
        gpu = dict(
            util_pct=float(v[0]), clock_mhz=float(v[1]), clock_max_mhz=float(v[2]), pstate=v[3],
            vram_used_mib=float(v[4]), vram_total_mib=float(v[5]), power_w=float(v[6]), temp_c=float(v[7]),
            sw_thermal_slowdown=v[8] == "Active", sw_power_cap=v[9] == "Active", hw_slowdown=v[10] == "Active",
        )
        ratio = gpu["clock_mhz"] / max(gpu["clock_max_mhz"], 1.0)
        gpu["throttled"] = bool(
            gpu["sw_thermal_slowdown"] or gpu["hw_slowdown"]
            or (gpu["util_pct"] >= THROTTLE_MIN_UTIL and ratio < THROTTLE_CLOCK_RATIO)
        )
        return gpu
    except Exception:
        return None


class GpuProbe(threading.Thread):
    """Lê o estado da GPU a cada poucos segundos, fora das threads do pipeline."""

    def __init__(self, stats: Stats, stop: threading.Event, period: float = 2.0) -> None:
        super().__init__(name="gpu-probe", daemon=True)
        self._stats, self._stop_event, self._period = stats, stop, period

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._stats.gpu = read_gpu()
            self._stop_event.wait(self._period)
