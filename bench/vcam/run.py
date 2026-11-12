"""Mede a câmera virtual como um programa de vídeo de verdade a recebe (Chrome, com os pedidos do Meet).

    <python do motor> bench/vcam/run.py --dll PASTA\\MorphoCamera64.dll [--pattern steady:30] [--mode meet]
                                         [--seconds 12] [--browser chrome|edge] [--window]

Usa uma câmera de TESTE ("Morpho Camera Teste"), compilada com /DMORPHO_TEST (ver
vendor/morphocam/build-one.cmd): outro nome, outro identificador e outra memória
compartilhada. A câmera que a pessoa usa, o app aberto e a webcam não são tocados.

O que acontece:
1. registra a câmera de teste para o usuário atual (e remove o registro no fim);
2. envia a ela um padrão em movimento com o número do quadro escrito em blocos, no ritmo
   pedido (``steady:30`` = 30 quadros por segundo certinhos; ``jitter:28`` = intervalos
   irregulares em torno de 28; ``steady:20`` etc.);
3. abre um Chrome à parte, com perfil temporário, na página ``page.html``. A página pega só a
   câmera de teste (pelo nome), com os mesmos pedidos que o Google Meet faz (``--mode meet``)
   ou um pedido simples de 720p a 30 (``--mode plain``), e mede:
     - local: os quadros que chegam à página (quando chegam, que carimbo de tempo trazem e
       qual o número de cada um);
     - remoto: a mesma imagem depois de enviada e recebida por uma chamada WebRTC dentro da
       própria página, que é o que as outras pessoas da reunião veem;
4. imprime o resumo e grava tudo em ``bench/results/vcam-*.json``.

``--use-fake-ui-for-media-stream`` vale só para esse Chrome temporário: dispensa o aviso de
permissão da câmera nele, e a página só pede a câmera de teste.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, PROJECT)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.engine import morphocam  # noqa: E402

TEST_NAME = "Morpho Camera Teste"
TEST_CLSID = "{6D5F5A88-69F6-47B0-B24B-22115FF96290}"
TEST_CHANNEL = "MorphoCamTest"
BROWSERS = {
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
}
BITS, BLOCKS = 16, 32          # o número do quadro: 16 blocos na metade esquerda da faixa de cima


def use_test_camera(dll: str) -> None:
    """Aponta o módulo da câmera para a câmera de teste e a registra."""
    morphocam.DEVICE_NAME, morphocam.CHANNEL = TEST_NAME, TEST_CHANNEL
    morphocam.DEVICE_PATH = "morpho:camera-teste"   # igual ao da câmera real, o Chrome abriria a real
    morphocam.CLSID = {64: TEST_CLSID}
    morphocam._register(64, dll)


def remove_test_camera() -> None:
    import winreg

    for sub in (rf"Software\Classes\CLSID\{morphocam.VIDEO_INPUT_CATEGORY}\Instance\{TEST_CLSID}",
                rf"Software\Classes\CLSID\{TEST_CLSID}\InprocServer32", rf"Software\Classes\CLSID\{TEST_CLSID}"):
        try:
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, sub, winreg.KEY_WOW64_64KEY, 0)
        except OSError:
            pass


class Pattern(threading.Thread):
    """Envia o padrão de teste no ritmo pedido e anota quando cada quadro saiu."""

    def __init__(self, spec: str, width: int = 1280, height: int = 720) -> None:
        super().__init__(daemon=True)
        kind, _, rate = spec.partition(":")
        self.kind, self.rate = kind, float(rate or 30)
        self.width, self.height = width, height
        self.sent = []            # (número, instante) dos quadros entregues ao filtro
        self.send_ms = []
        self.done = threading.Event()
        self._random = random.Random(7)

    def _interval(self) -> float:
        base = 1.0 / self.rate
        if self.kind == "jitter":      # como um pipeline que oscila: de 0,6x a 1,6x do intervalo médio
            return base * self._random.uniform(0.6, 1.4) * (1.6 if self._random.random() < 0.08 else 1.0)
        return base

    def frame(self, number: int) -> np.ndarray:
        w, h = self.width, self.height
        image = np.empty((h, w, 3), np.uint8)
        ramp = ((np.arange(w, dtype=np.int32) * 2 + number * 9) % 256).astype(np.uint8)
        image[:] = ramp[None, :, None]
        image[:, :, 1] = 90
        x = (number * 23) % (w - 80)
        cv2.rectangle(image, (x, h // 3), (x + 80, h * 2 // 3), (255, 255, 255), -1)     # barra que anda
        bw, bh = w // BLOCKS, h // 18
        image[:bh, : bw * BITS] = 0
        for bit in range(BITS):
            if (number >> bit) & 1:
                image[:bh, bit * bw:(bit + 1) * bw] = 255
        return image

    def run(self) -> None:
        sender = morphocam.Sender()
        number, due = 1, time.perf_counter()
        while not self.done.is_set():
            wait = due - time.perf_counter()
            if wait > 0.002:
                time.sleep(wait - 0.0015)
            while time.perf_counter() < due:
                pass                                   # acerta o instante do envio em microssegundos
            image = self.frame(number & 0xFFFF)
            started = time.perf_counter()
            if sender.send(image):
                self.sent.append((number, started))
                self.send_ms.append((time.perf_counter() - started) * 1000)
                number += 1
            due = max(due + self._interval(), time.perf_counter() - 0.05)
        sender.close()


class EngineFeed:
    """O motor de verdade trocando o rosto num vídeo gravado e enviando para a câmera de teste."""

    def __init__(self, dll: str, replay: str, photo: str, resolution: str = "720p") -> None:
        from app import paths
        from app.engine import events
        from app.engine.config import EngineConfig

        self._events, self._replay, self._photo, self._resolution = events, replay, photo, resolution
        self.stats, self.seen, self.log = [], {}, []
        self._lock = threading.Condition()
        folder = self._folder = tempfile.mkdtemp(prefix="morpho-vcam-engine-")
        config = os.path.join(folder, "engine.json")
        EngineConfig(engine_root=paths.engine_root(), shm_name=f"vcamtest_{os.getpid()}").save(config)
        env = dict(os.environ, MORPHO_CAMERA_DIR=os.path.dirname(dll), PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8",
                   MORPHO_DATA_DIR=os.environ.get("MORPHO_DATA_DIR") or r"C:\Users\vinic\dlc-lab\app-data-test")
        self.process = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "engine_test_camera.py"), "--config", config], cwd=PROJECT, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace")
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.process.stdout:
            event = self._events.parse(line.rstrip("\n"))
            if event is None:
                self.log.append(line.rstrip())
                continue
            with self._lock:
                if event["evt"] == "stats":
                    self.stats.append(event)
                self.seen[event["evt"] + (":" + str(event.get("state")) if event["evt"] == "status" else "")] = event
                self._lock.notify_all()

    def _send(self, **command) -> None:
        self.process.stdin.write(json.dumps(command) + "\n")
        self.process.stdin.flush()

    def _wait(self, key: str, seconds: float) -> dict:
        deadline = time.time() + seconds
        with self._lock:
            while key not in self.seen:
                left = deadline - time.time()
                if left <= 0 or self.process.poll() is not None:
                    raise SystemExit(f"O motor não chegou a '{key}'. Fim do registro:\n" + "\n".join(self.log[-15:]))
                self._lock.wait(min(left, 0.5))
            return self.seen[key]

    def start(self) -> None:
        self._wait("loaded", 180)
        self._send(cmd="set_source", paths=[self._photo])
        if not self._wait("source", 30).get("ok"):
            raise SystemExit("O motor recusou a foto de origem.")
        self._send(cmd="start", replay=self._replay, resolution=self._resolution, virtual_camera=True, protect=True)
        self._wait("status:running", 60)

    def stop(self) -> None:
        try:
            self._send(cmd="quit")
            self.process.wait(10)
        except Exception:
            self.process.kill()
        shutil.rmtree(self._folder, ignore_errors=True)


class Results:
    def __init__(self) -> None:
        self.ready = threading.Event()
        self.data = None
        self.log = []


def serve(results: Results) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: D401, N802
            pass

        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] not in ("/", "/page.html"):
                self.send_error(404)
                return
            with open(os.path.join(HERE, "page.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path == "/log":
                results.log.append(body.decode("utf-8", "replace"))
            elif self.path == "/result":
                results.data = json.loads(body)
                results.ready.set()
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def summarize(series: dict, label: str) -> dict:
    """Ritmo de uma série de quadros: ``t`` (chegada, ms), ``ts`` (carimbo, ms), ``n`` (número do quadro)."""
    arrival, stamps, numbers = series.get("t") or [], series.get("ts") or [], series.get("n") or []
    if len(arrival) < 5:
        return dict(label=label, frames=len(arrival))
    gaps = [b - a for a, b in zip(arrival, arrival[1:])]
    stamp_gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    median = statistics.median(gaps)
    span = arrival[-1] - arrival[0]
    known = [n for n in numbers if n > 0]
    repeats = sum(1 for a, b in zip(numbers, numbers[1:]) if a == b and a > 0)
    distinct = len(set(known))
    skipped = sum(max(0, ((b - a) & 0xFFFF) - 1) for a, b in zip(known, known[1:]) if b != a)
    return dict(
        label=label, frames=len(arrival), seconds=round(span / 1000, 2), fps=round((len(arrival) - 1) / span * 1000, 2),
        gap_median=round(median, 1), gap_p95=round(sorted(gaps)[int(len(gaps) * 0.95)], 1), gap_max=round(max(gaps), 1),
        stalls_over_50ms=sum(1 for g in gaps if g > 50), stalls_over_100ms=sum(1 for g in gaps if g > 100),
        stalls_over_2x=sum(1 for g in gaps if g > 2 * median + 5),
        stamp_gap_median=round(statistics.median(stamp_gaps), 2) if stamp_gaps else None,
        stamp_gap_max=round(max(stamp_gaps), 1) if stamp_gaps else None,
        # quanto o relógio dos carimbos anda para cada segundo real (1.00 = certo)
        clock_ratio=round((stamps[-1] - stamps[0]) / span, 3) if stamps and span else None,
        distinct=distinct, repeated=repeats, skipped=skipped,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dll", required=True, help="MorphoCamera64.dll compilada com /DMORPHO_TEST")
    parser.add_argument("--pattern", default="steady:30")
    parser.add_argument("--mode", default="meet", choices=("meet", "plain"))
    parser.add_argument("--seconds", type=float, default=12.0)
    parser.add_argument("--browser", default="chrome", choices=sorted(BROWSERS))
    parser.add_argument("--window", action="store_true", help="abre a janela do navegador (padrão: sem janela)")
    parser.add_argument("--label", default="")
    parser.add_argument("--replay", default=r"C:\Users\vinic\dlc-lab\demo-lp\replay-720.mp4",
                        help="com --pattern engine: o vídeo que faz as vezes da webcam")
    parser.add_argument("--photo", default=r"C:\Users\vinic\dlc-lab\fixtures\source.jpg",
                        help="com --pattern engine: a foto do rosto de origem")
    parser.add_argument("--resolution", default="720p")
    args = parser.parse_args()

    dll = os.path.abspath(args.dll)
    if not os.path.isfile(dll):
        raise SystemExit(f"Não achei {dll}.")
    results = Results()
    server = serve(results)
    port = server.server_address[1]
    profile = tempfile.mkdtemp(prefix="morpho-vcam-")
    use_test_camera(dll)
    pattern = engine = None
    if args.pattern == "engine":
        engine = EngineFeed(dll, os.path.abspath(args.replay), os.path.abspath(args.photo), args.resolution)
        engine.start()
        time.sleep(3.0)     # deixa o motor entrar em regime antes de abrir o navegador
    else:
        pattern = Pattern(args.pattern)
        pattern.start()
    command = [BROWSERS[args.browser], f"--user-data-dir={profile}", "--use-fake-ui-for-media-stream",
               "--no-first-run", "--no-default-browser-check", "--disable-search-engine-choice-screen",
               "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-pings",
               "--autoplay-policy=no-user-gesture-required", "--window-size=1100,760",
               f"http://127.0.0.1:{port}/page.html?mode={args.mode}&seconds={args.seconds:g}"]
    if not args.window:
        command.insert(1, "--headless=new")
    browser = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        arrived = results.ready.wait(args.seconds + 45)
    finally:
        subprocess.run(["taskkill", "/PID", str(browser.pid), "/T", "/F"], capture_output=True)
        if pattern is not None:
            pattern.done.set()
            pattern.join(3)
        if engine is not None:
            engine.stop()
        time.sleep(1.0)
        remove_test_camera()
        shutil.rmtree(profile, ignore_errors=True)
        server.shutdown()
    if not arrived:
        print("A página não devolveu resultado. Registro da página:")
        print("\n".join(results.log[-20:]))
        return 1

    data = results.data
    if data.get("error"):
        print("ERRO na página:", data["error"])
        print("\n".join(results.log[-20:]))
        return 1
    if engine is not None:
        # Os últimos segundos do motor, que são os da medição: média de cada número que ele publica.
        recent = engine.stats[-int(args.seconds):] or engine.stats
        sent = dict(source="motor")
        for key in sorted({k for row in recent for k, v in row.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}):
            values = [row[key] for row in recent if isinstance(row.get(key), (int, float))]
            sent[key] = round(statistics.mean(values), 2)
    else:
        sent_gaps = [(b[1] - a[1]) * 1000 for a, b in zip(pattern.sent, pattern.sent[1:])]
        sent = dict(frames=len(pattern.sent), fps=round(1000 / statistics.mean(sent_gaps), 2) if sent_gaps else 0,
                    gap_max=round(max(sent_gaps), 1) if sent_gaps else 0,
                    send_ms=round(statistics.mean(pattern.send_ms), 2) if pattern.send_ms else 0)
    summary = dict(label=args.label, dll=dll, pattern=args.pattern, mode=args.mode, browser=args.browser,
                   settings=data.get("settings"), sent=sent,
                   local=summarize(data.get("local") or {}, "local"),
                   remote=summarize(data.get("remote") or {}, "remoto"),
                   shown=summarize(data.get("shown") or {}, "exibido (remoto)"),
                   shown_local=summarize(data.get("shownLocal") or {}, "exibido (local)"),
                   paint=summarize(data.get("paint") or {}, "desenho da página"),
                   inbound=data.get("inbound"), outbound=data.get("outbound"))
    out = os.path.join(PROJECT, "bench", "results")
    os.makedirs(out, exist_ok=True)
    name = f"vcam-{args.label or 'run'}-{args.mode}-{args.pattern.replace(':', '')}-{time.strftime('%H%M%S')}.json"
    with open(os.path.join(out, name), "w", encoding="utf-8") as f:
        json.dump(dict(summary=summary, raw=data, page_log=results.log,
                       engine_stats=engine.stats if engine is not None else None), f)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
