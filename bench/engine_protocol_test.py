"""Teste do protocolo do motor, sem janela: comandos entram, eventos saem.

Sobe o processo do motor como a janela faz e percorre o que o usuário pode
fazer: iniciar sem rosto, escolher foto ruim, escolher foto boa, trocar de
rosto ao vivo, parar, iniciar de novo, pedir câmera que não existe, sair.
Usa um vídeo no lugar da câmera; nenhuma câmera é ligada.

    <python do motor> engine_protocol_test.py --video clip.avi --face rosto.jpg --closeup close.jpg
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from app import paths  # noqa: E402
from app.engine import events  # noqa: E402
from app.engine.config import EngineConfig, SessionRequest  # noqa: E402
from app.shared_frame import FrameReader  # noqa: E402

RESULTS: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(ok)
    print(f"{'ok  ' if ok else 'FALHOU'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)


class Engine:
    def __init__(self, work: str) -> None:
        self.shm = f"morpho_test_{os.getpid()}"
        config = os.path.join(work, "engine-config.json")
        EngineConfig(engine_root=paths.engine_root(), shm_name=self.shm).save(config)
        env = dict(os.environ, PYTHONPATH=PROJECT, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(
            [paths.engine_python(), "-m", "app.engine", "--config", config], cwd=PROJECT, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self.events: "queue.Queue[dict]" = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            evt = events.parse(line.rstrip("\r\n"))
            if evt is not None:
                self.events.put(evt)

    def send(self, **command) -> None:
        self.proc.stdin.write(json.dumps(command) + "\n")
        self.proc.stdin.flush()

    def wait_for(self, predicate, timeout: float):
        """O primeiro evento que satisfaz ``predicate``; os anteriores são descartados."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                evt = self.events.get(timeout=0.2)
            except queue.Empty:
                continue
            if predicate(evt):
                return evt
        return None

    def stats_after(self, seconds: float):
        """A última medição depois de deixar rodar por ``seconds``."""
        time.sleep(seconds)
        last = None
        while True:
            try:
                evt = self.events.get_nowait()
            except queue.Empty:
                break
            if evt.get("evt") == "stats":
                last = evt
        return last


def is_status(state):
    return lambda e: e.get("evt") == "status" and e.get("state") == state


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", required=True)
    p.add_argument("--face", required=True, help="foto com um rosto detectável")
    p.add_argument("--closeup", required=True, help="foto em close (rosto ocupando o quadro)")
    p.add_argument("--gap-video", help="vídeo em que o rosto some por um trecho (testa a proteção)")
    p.add_argument("--vcam-snapshot", help="grava aqui um quadro lido da câmera virtual")
    args = p.parse_args()

    import cv2
    import numpy as np

    work = tempfile.mkdtemp(prefix="dls-protocol-")
    blank = os.path.join(work, "sem_rosto.jpg")
    cv2.imwrite(blank, np.full((600, 800, 3), 120, np.uint8))
    replay = SessionRequest(replay=os.path.abspath(args.video)).to_command()

    engine = Engine(work)
    loaded = engine.wait_for(lambda e: e.get("evt") in ("loaded", "error"), 400)
    check("carrega os modelos e avisa", bool(loaded) and loaded.get("evt") == "loaded",
          f"{(loaded or {}).get('seconds', 0):.1f} s" if loaded else "sem resposta")
    if not loaded or loaded.get("evt") != "loaded":
        engine.proc.kill()
        return 1
    check("fica em espera depois de carregar", engine.wait_for(is_status("idle"), 5) is not None)

    engine.send(**replay)
    ready = engine.wait_for(lambda e: e.get("evt") == "ready", 30)
    check("inicia mesmo sem rosto escolhido", bool(ready) and ready.get("has_source") is False)
    stats = engine.stats_after(3.5)
    check("sem rosto escolhido, nada vai para a saída",
          bool(stats) and stats["capture_fps"] > 5 and stats["processed_fps"] == 0 and stats["output_fps"] == 0,
          f"câmera {stats['capture_fps']:.0f} fps, saída {stats['output_fps']:.0f}" if stats else "sem medição")

    engine.send(cmd="set_source", paths=[blank])
    source = engine.wait_for(lambda e: e.get("evt") == "source", 20)
    check("foto sem rosto é recusada com mensagem", bool(source) and source.get("ok") is False and bool(source.get("message")),
          (source or {}).get("code", ""))

    engine.send(cmd="set_source", paths=[os.path.abspath(args.face)])
    source = engine.wait_for(lambda e: e.get("evt") == "source", 20)
    check("foto boa é aceita", bool(source) and source.get("ok") is True)
    stats = engine.stats_after(4)
    check("com o rosto escolhido, a troca aparece na hora (sem reiniciar)",
          bool(stats) and stats["swap_fps"] > 10, f"{stats['swap_fps']:.0f} trocas/s" if stats else "sem medição")
    reader = FrameReader(engine.shm)
    frame = None
    for _ in range(50):
        got = reader.read()
        if got is not None:
            frame = got[0]
            break
        time.sleep(0.02)
    check("o quadro de saída chega pela memória compartilhada", frame is not None,
          f"{frame.shape[1]}x{frame.shape[0]}" if frame is not None else "")
    reader.close()

    engine.send(cmd="set_source", paths=[os.path.abspath(args.closeup)])
    source = engine.wait_for(lambda e: e.get("evt") == "source", 20)
    check("trocar de rosto ao vivo: foto em close aceita com margem",
          bool(source) and source.get("ok") is True and bool(source.get("padded")))
    stats = engine.stats_after(3)
    check("a troca continua depois de mudar o rosto", bool(stats) and stats["swap_fps"] > 10,
          f"{stats['swap_fps']:.0f} trocas/s" if stats else "sem medição")

    engine.send(cmd="set_source", paths=[blank])
    source = engine.wait_for(lambda e: e.get("evt") == "source", 20)
    check("foto ruim ao vivo mantém o rosto anterior", bool(source) and source.get("ok") is False
          and source.get("kept_previous") is True)

    engine.send(cmd="stop")
    check("parar volta à espera", engine.wait_for(is_status("idle"), 15) is not None)
    check("parado, não há mais medições", engine.stats_after(2.5) is None)

    engine.send(**replay)
    check("inicia de novo", engine.wait_for(is_status("running"), 30) is not None)
    stats = engine.stats_after(4)
    check("a segunda sessão troca normalmente", bool(stats) and stats["swap_fps"] > 10,
          f"{stats['swap_fps']:.0f} trocas/s" if stats else "sem medição")

    # --- ajustes da troca, aplicados ao vivo ---
    engine.send(cmd="set_option", values={"sharpness": 99, "opacity": 0.8, "mouth_mask_size": 40, "desconhecido": 1})
    opts = engine.wait_for(lambda e: e.get("evt") == "options", 5)
    applied = (opts or {}).get("values") or {}
    check("ajustes são aplicados ao vivo, dentro dos limites",
          applied.get("sharpness") == 5.0 and applied.get("opacity") == 0.8 and applied.get("mouth_mask_size") == 40.0
          and "desconhecido" not in applied, json.dumps(applied))
    stats = engine.stats_after(3)
    check("a troca segue rodando com os ajustes", bool(stats) and stats["swap_fps"] > 10,
          f"{stats['swap_fps']:.0f} trocas/s" if stats else "sem medição")
    engine.send(cmd="set_option", values={"sharpness": 0, "opacity": 1, "mouth_mask_size": 0, "eye_reveal": 0})
    engine.wait_for(lambda e: e.get("evt") == "options", 5)

    # --- pausa de privacidade: borra tudo na hora ---
    engine.send(cmd="set_output", force_blur=True)
    stats = engine.stats_after(3)
    check("pausa de privacidade borra todos os quadros", bool(stats) and stats["protected_fps"] > 10,
          f"{stats['protected_fps']:.0f} protegidos/s" if stats else "sem medição")
    engine.send(cmd="set_output", force_blur=False)
    stats = engine.stats_after(3)
    check("e volta ao normal ao desligar", bool(stats) and stats["protected_fps"] == 0 and stats["swap_fps"] > 10)

    # --- prévia: câmera ligada só para a janela, sem troca e sem câmera virtual ---
    virtual = (loaded.get("virtual_camera") or {})
    engine.send(cmd="stop")
    engine.wait_for(is_status("idle"), 15)
    preview = dict(replay, cmd="preview")
    engine.send(**preview)
    check("prévia liga a câmera", engine.wait_for(is_status("preview"), 30) is not None)
    stats = engine.stats_after(3.5)
    check("na prévia a imagem crua vai para a janela e nada é trocado",
          bool(stats) and stats.get("mode") == "preview" and stats["preview_fps"] > 10 and stats["processed_fps"] == 0,
          f"prévia {stats['preview_fps']:.0f} fps, processados {stats['processed_fps']:.0f}" if stats else "sem medição")
    # A prévia tem canal próprio (imagem pequena, para a barra lateral); o canal da saída fica parado.
    output_reader, camera_reader = FrameReader(engine.shm), FrameReader(loaded["shm_camera"])
    output_reader.read()   # descarta o último quadro da sessão ao vivo anterior
    time.sleep(0.6)
    small = camera_reader.read()
    check("a prévia chega pequena, pelo canal da câmera", small is not None and small[0].shape[1] <= 480,
          f"{small[0].shape[1]}x{small[0].shape[0]}" if small else "nada")
    check("e o canal da saída fica parado durante a prévia", output_reader.read() is None)
    output_reader.close()
    if virtual.get("available"):
        engine.send(cmd="set_output", virtual_camera=True)
        leaked = engine.wait_for(lambda e: e.get("evt") == "virtual_camera" and e.get("on"), 3)
        check("na prévia a câmera virtual não transmite, mesmo marcada", leaked is None)
    engine.send(**replay)   # Iniciar com a mesma câmera
    seen = []
    going = engine.wait_for(lambda e: (seen.append(e.get("state")) or False) if e.get("evt") == "status" and e.get("state") != "running"
                            else e.get("evt") == "status", 15)
    check("Iniciar a partir da prévia não reabre a câmera", bool(going) and "opening_camera" not in seen, " ".join(map(str, seen)) or "direto")
    stats = engine.stats_after(4)
    check("e a troca começa", bool(stats) and stats.get("mode") == "live" and stats["swap_fps"] > 10,
          f"{stats['swap_fps']:.0f} trocas/s" if stats else "sem medição")
    time.sleep(0.5)
    check("ao vivo a prévia da câmera continua chegando", camera_reader.read() is not None)
    engine.send(**preview)   # Parar mantendo a prévia
    check("voltar para a prévia", engine.wait_for(is_status("preview"), 10) is not None)
    stats = engine.stats_after(3)
    check("de volta à prévia, a troca para", bool(stats) and stats.get("mode") == "preview" and stats["processed_fps"] == 0)
    camera_reader.close()
    engine.send(cmd="set_output", virtual_camera=False)
    engine.send(**replay)
    engine.wait_for(is_status("running"), 15)
    engine.stats_after(2)

    # --- câmera virtual: ligada ao vivo, lida de volta como um app de chamada faria ---
    check("o motor informa se há câmera virtual neste computador", "available" in virtual,
          virtual.get("device") or virtual.get("reason", ""))
    if virtual.get("available"):
        engine.send(cmd="set_output", virtual_camera=True)
        on = engine.wait_for(lambda e: e.get("evt") == "virtual_camera", 15)
        check("câmera virtual liga ao vivo", bool(on) and on.get("on") is True, (on or {}).get("device") or (on or {}).get("error", ""))
        if on and on.get("on"):
            from pygrabber.dshow_graph import FilterGraph

            names = FilterGraph().get_input_devices()
            cap = cv2.VideoCapture(names.index(on["device"]), cv2.CAP_DSHOW)   # sem parâmetros, como um app comum
            got = []
            deadline = time.time() + 6
            while time.time() < deadline and len(got) < 40:
                ok, frame = cap.read()
                if ok and frame is not None:
                    got.append(frame)
            cap.release()
            alive = len(got) >= 10 and float(got[-1].std()) > 20
            moving = alive and float(np.abs(got[-1].astype(int) - got[len(got) // 2].astype(int)).mean()) > 0.3
            check("outro programa recebe imagem pela câmera virtual", alive,
                  f"{len(got)} quadros, {got[-1].shape[1]}x{got[-1].shape[0]}, contraste {got[-1].std():.0f}" if got else "nada")
            check("e a imagem está viva (muda de um quadro para o outro)", bool(moving))
            if on.get("backend") == "morpho":
                used = engine.wait_for(lambda e: e.get("evt") == "virtual_camera" and e.get("watched"), 3)
                check("o motor percebe que outro programa está usando a câmera", used is not None)
            if got and args.vcam_snapshot:
                cv2.imwrite(args.vcam_snapshot, got[-1])
        engine.send(cmd="set_output", virtual_camera=False)
        off = engine.wait_for(lambda e: e.get("evt") == "virtual_camera" and not e.get("on"), 10)
        check("câmera virtual desliga ao vivo", bool(off) and off.get("on") is False)

    # --- proteção: quando não há rosto para trocar, a imagem sai borrada ---
    if args.gap_video:
        gap = SessionRequest(replay=os.path.abspath(args.gap_video), protect=True).to_command()
        engine.send(**gap)
        check("inicia o vídeo em que o rosto some", engine.wait_for(is_status("running"), 30) is not None)
        seen = {"protected": 0.0, "no_face": 0, "swapped": 0.0}
        deadline = time.time() + 14
        while time.time() < deadline:
            evt = engine.wait_for(lambda e: e.get("evt") == "stats", 2)
            if evt:
                seen["protected"] = max(seen["protected"], evt.get("protected_fps") or 0)
                seen["no_face"] += evt.get("frames_without_face", 0)
                seen["swapped"] = max(seen["swapped"], evt.get("swap_fps") or 0)
        check("com o rosto na frente, a troca é aplicada", seen["swapped"] > 10, f"{seen['swapped']:.0f}/s")
        check("quando o rosto some, os quadros saem protegidos", seen["no_face"] > 20 and seen["protected"] > 10,
              f"{seen['no_face']} quadros sem rosto, até {seen['protected']:.0f} protegidos/s")
        engine.send(cmd="set_output", protect=False)
        time.sleep(1.0)
        seen_off = 0.0
        deadline = time.time() + 26   # dá uma volta inteira no vídeo, passando pelo trecho sem rosto
        while time.time() < deadline:
            evt = engine.wait_for(lambda e: e.get("evt") == "stats", 2)
            if evt:
                seen_off = max(seen_off, evt.get("protected_fps") or 0)
        check("com a proteção desligada, nada é borrado", seen_off == 0, f"{seen_off:.0f} protegidos/s")
        engine.send(cmd="set_output", protect=True)

    engine.send(**SessionRequest(camera="câmera que não existe").to_command())
    error = engine.wait_for(lambda e: e.get("evt") == "error", 20)
    check("câmera inexistente dá erro sem derrubar o motor",
          bool(error) and error.get("fatal") is False and error.get("code") == "camera_not_found")
    check("e o motor volta à espera", engine.wait_for(is_status("idle"), 10) is not None)

    engine.send(cmd="quit")
    try:
        code = engine.proc.wait(10)
    except subprocess.TimeoutExpired:
        engine.proc.kill()
        code = None
    check("sair encerra o processo", code == 0, f"código {code}")

    print(f"\n{sum(RESULTS)} de {len(RESULTS)} verificações passaram")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
