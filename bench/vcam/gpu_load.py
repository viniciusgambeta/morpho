"""Ocupa a placa de vídeo como o motor ao vivo: detecta e troca o rosto num vídeo, em laço.

    <python do motor> bench/vcam/gpu_load.py VIDEO FOTO [--seconds 40] [--fps 30] [--start 0]

Serve para medir o que acontece com os OUTROS programas (o navegador numa reunião) enquanto o
motor trabalha. Não grava nem mostra nada; no fim diz quantas trocas por segundo conseguiu.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT)
ARGS = sys.argv[1:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("photo")
    parser.add_argument("--seconds", type=float, default=40.0)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--start", type=int, default=0)
    args = parser.parse_args(ARGS)

    import cv2

    from app import paths
    from app.engine import bridge
    from app.engine.config import EngineConfig
    from app.engine.pipeline import choose_face
    from app.ui.settings import Settings

    bridge.setup(EngineConfig(engine_root=paths.engine_root(), shm_name="carga"))
    import modules.processors.frame.face_swapper as fs
    from modules import head_geometry
    from modules.face_analyser import detect_many_faces_fast, ensure_landmarks, get_face_analyser

    bridge.ensure_swapper_model()
    get_face_analyser()
    bridge.load_swapper()
    head_geometry.get_provider()
    bridge.apply_options(Settings().engine_options())
    identity, _, _ = bridge.load_identity([args.photo])

    capture, frames = cv2.VideoCapture(args.video), []
    index = 0
    while len(frames) < 150:
        ok, frame = capture.read()
        if not ok:
            break
        if index >= args.start:
            frames.append(cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA))
        index += 1
    capture.release()
    if not frames:
        raise SystemExit("Não li nenhum quadro do vídeo.")

    print("CARGA PRONTA", flush=True)
    started, done, due = time.perf_counter(), 0, time.perf_counter()
    while time.perf_counter() - started < args.seconds:
        wait = due - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        frame = frames[done % len(frames)].copy()
        face, _ = choose_face(detect_many_faces_fast(frame) or [], None)
        if face is not None:
            face.track_alpha = 1.0
            ensure_landmarks(frame, [face])
            head_geometry.estimate(frame, [face])
            fs.swap_face(identity, face, frame)
        done += 1
        due = max(due + 1.0 / args.fps, time.perf_counter() - 0.1)
    print(f"CARGA FIM {done / (time.perf_counter() - started):.1f} trocas por segundo", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
