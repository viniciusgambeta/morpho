"""Gera os vídeos de demonstração da página: uma gravação real passada pelo motor do app.

    <python do motor> site/tools/make_demo_video.py analyze VIDEO SAIDA.json
    <python do motor> site/tools/make_demo_video.py render  VIDEO PASTA --faces A.jpg B.jpg ...
                                                             [--start N] [--end N] [--crop X Y W H]
    <python do motor> site/tools/make_demo_video.py web     PASTA site/assets/demo --photos A.jpg B.jpg ...

Cada quadro da gravação passa pelo mesmo caminho do app ao vivo (``PipelineThread._loop``:
detecção, rastreamento, pose, troca, pós-processamento), com os ajustes padrão do app e na
resolução padrão dele (720p). A diferença é que nada é descartado: ao vivo o pipeline pula
quadros quando se atrasa; aqui o relógio é o do vídeo, então todo quadro é trocado e o
original e a troca ficam alinhados quadro a quadro.

``analyze`` não grava imagem nenhuma: só mede, quadro a quadro, se há rosto, onde ele está e
quanto a imagem mudou em relação ao quadro anterior (serve para achar vinhetas e cortes).

``render`` grava, para cada foto, um arquivo ``troca-N.mp4`` com o original em cima e a troca
embaixo (um quadro só, empilhado): a página desenha as duas metades do mesmo vídeo, e assim
elas nunca saem de sincronia. Esses arquivos são de alta qualidade.

``web`` faz a versão leve de cada um para a página (cerca de 3,7 MB), o quadro inicial de cada
metade (``antes.webp`` e ``depois-N.webp``, mostrados antes de o vídeo carregar) e a miniatura
quadrada de cada foto para o seletor de rostos (``rosto-N.webp``). Não usa o motor.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT)
VIDEO_ARGS = sys.argv[1:]        # o motor reescreve sys.argv ao ser preparado

WIDTH, HEIGHT = 1280, 720        # a resolução padrão do app


def prepare_engine():
    """Carrega o motor como o app faz (ver app/engine/__main__.py e pipeline._load)."""
    from app import paths
    from app.engine import bridge
    from app.engine.config import EngineConfig
    from app.ui.settings import Settings

    bridge.setup(EngineConfig(engine_root=paths.engine_root(), shm_name="demo"))
    from modules import head_geometry
    from modules.face_analyser import get_face_analyser

    bridge.ensure_swapper_model()
    get_face_analyser()
    bridge.load_swapper()
    head_geometry.get_provider()
    bridge.apply_options(Settings().engine_options())   # os ajustes de fábrica do app
    return bridge


class LivePath:
    """O laço do pipeline do app para uma sequência de quadros com relógio próprio."""

    def __init__(self, identity, fps: float) -> None:
        from modules.face_tracker import FaceTracker

        self.identity, self.fps = identity, fps
        self.tracker = FaceTracker()
        self.face = None
        self.last_detection = -1e9
        self.detections = self.swapped = self.hidden = self.missing = 0

    def step(self, index: int, frame):
        import modules.globals as G
        import modules.processors.frame.face_swapper as fs
        from modules import calibration, head_geometry
        from modules.face_analyser import detect_many_faces_fast, ensure_landmarks

        from app.engine.pipeline import (DETECT_PERIOD_TRACKED, DETECT_PERIOD_UNTRACKED, SWAP_HIDDEN_BELOW,
                                         choose_face)

        now = index / self.fps
        tracking = G.face_tracking
        period = DETECT_PERIOD_TRACKED if tracking else DETECT_PERIOD_UNTRACKED
        if tracking and self.tracker.unsettled:
            period = 0.0
        face = self.face
        if now - self.last_detection >= period - 1e-6:
            self.last_detection = now
            self.detections += 1
            tracked_bbox = getattr(face, "bbox", None) if face is not None else None
            face, same = choose_face(detect_many_faces_fast(frame) or [], tracked_bbox)
            if tracking and face is not None and tracked_bbox is not None and not same:
                self.tracker.reset()
            if tracking:
                face = self.tracker.observe(frame, face, now)
        elif tracking and face is not None:
            face = self.tracker.track(frame, face, now)

        if face is not None:
            face.track_alpha = 1.0     # "proteger" ligado, como no app
        faces = [face] if face is not None else None
        if faces and (G.mouth_mask or G.face_outline_mask or G.blink_reveal or G.eye_reveal > 0):
            ensure_landmarks(frame, faces)
        if faces:
            head_geometry.estimate(frame, faces)

        bboxes = []
        if face is not None:
            if float(calibration.swap_alpha(face)) > SWAP_HIDDEN_BELOW:
                self.swapped += 1
            else:
                self.hidden += 1
            frame = fs.swap_face(self.identity, face, frame)
            bbox = getattr(face, "bbox", None)
            if bbox is not None:
                bboxes.append(bbox.astype(int))
        else:
            self.missing += 1
        self.face = face
        return fs.apply_post_processing(frame, bboxes)


def frames(path: str, start: int, end: int, crop):
    """Os quadros da gravação, já recortados e na resolução do app."""
    import cv2

    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        raise SystemExit(f"Não consegui abrir {path}.")
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok or (end and index >= end):
            break
        if index >= start:
            if crop:
                x, y, w, h = crop
                frame = frame[y:y + h, x:x + w]
            if frame.shape[1] != WIDTH or frame.shape[0] != HEIGHT:
                frame = cv2.resize(frame, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
            yield index, frame
        index += 1
    capture.release()


def video_fps(path: str) -> float:
    import cv2

    capture = cv2.VideoCapture(path)
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    capture.release()
    return float(fps)


def analyze(args) -> int:
    import cv2
    import numpy as np

    prepare_engine()
    from modules.face_analyser import detect_many_faces_fast

    rows, previous = [], None
    for index, frame in frames(args.video, 0, 0, None):
        small = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        change = 0.0 if previous is None else float(np.abs(small - previous).mean())
        previous = small
        found = detect_many_faces_fast(frame) or []
        best = max(found, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), default=None)
        rows.append(dict(
            i=index, faces=len(found), change=round(change, 2), light=round(float(small.mean()), 1),
            score=None if best is None else round(float(getattr(best, "det_score", 0.0)), 3),
            bbox=None if best is None else [int(v) for v in best.bbox[:4]],
        ))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(dict(fps=video_fps(args.video), width=WIDTH, height=HEIGHT, frames=rows), f)
    with_face = sum(1 for r in rows if r["faces"])
    print(f"{len(rows)} quadros, {with_face} com rosto; gravado em {args.out}")
    return 0


def render(args) -> int:
    import numpy as np

    bridge = prepare_engine()
    fps = video_fps(args.video)
    os.makedirs(args.out, exist_ok=True)
    report = []
    for number, photo in enumerate(args.faces, 1):
        identity, skipped, padded = bridge.load_identity([photo])
        path = LivePath(identity, fps)
        target = os.path.join(args.out, f"troca-{number}.mp4")
        encoder = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-s", f"{WIDTH}x{HEIGHT * 2}", "-r", f"{fps:g}", "-i", "-",
             "-c:v", "libx264", "-preset", "medium", "-crf", "12", "-pix_fmt", "yuv420p", target],
            stdin=subprocess.PIPE)
        count = 0
        for index, frame in frames(args.video, args.start, args.end, args.crop):
            swapped = path.step(count, frame.copy())
            encoder.stdin.write(np.vstack((frame, swapped)).tobytes())
            count += 1
        encoder.stdin.close()
        if encoder.wait() != 0:
            raise SystemExit(f"O ffmpeg falhou ao gravar {target}.")
        row = dict(face=number, photo=os.path.basename(photo), file=target, frames=count, swapped=path.swapped,
                   hidden=path.hidden, no_face=path.missing, detections=path.detections, padded=bool(padded))
        report.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    with open(os.path.join(args.out, "relatorio.json"), "w", encoding="utf-8") as f:
        json.dump(dict(fps=fps, start=args.start, end=args.end, crop=args.crop, faces=report), f, indent=1)
    return 0


def face_square(image):
    """O quadrado da miniatura: em volta do rosto, com folga para o cabelo e o queixo."""
    import cv2

    height, width = image.shape[:2]
    finder = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
    found = finder.detectMultiScale(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 1.1, 6,
                                    minSize=(width // 5, width // 5))
    if len(found):
        x, y, w, h = max(found, key=lambda box: box[2] * box[3])
        cx, cy, side = x + w / 2, y + h * 0.46, max(w, h) * 1.5
    else:                                  # retrato comum: rosto no centro, um pouco acima do meio
        cx, cy, side = width / 2, height * 0.42, width * 0.8
    side = int(min(side, width, height))
    x0 = int(min(max(cx - side / 2, 0), width - side))
    y0 = int(min(max(cy - side / 2, 0), height - side))
    return image[y0:y0 + side, x0:x0 + side]


def web(args) -> int:
    """As versões leves para a página: vídeos, quadro inicial de cada metade e miniaturas dos rostos."""
    import cv2

    os.makedirs(args.out, exist_ok=True)
    total = 0
    for number, photo in enumerate(args.photos, 1):
        raw = os.path.join(args.raw, f"troca-{number}.mp4")
        target = os.path.join(args.out, f"troca-{number}.mp4")
        if not args.no_video:
            # Nível 4.1 com 4 quadros de referência: é o que os decodificadores de celular aceitam
            # para um quadro deste tamanho. Um quadro-chave a cada 2 s deixa a troca de rosto ágil.
            done = subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-i", raw, "-an", "-c:v", "libx264", "-preset", "slow",
                 "-crf", str(args.crf), "-pix_fmt", "yuv420p", "-profile:v", "high", "-level:v", "4.1",
                 "-refs", "4", "-g", "60", "-movflags", "+faststart", target])
            if done.returncode != 0:
                raise SystemExit(f"O ffmpeg falhou em {target}.")
        capture = cv2.VideoCapture(raw)
        ok, first = capture.read()
        capture.release()
        if not ok:
            raise SystemExit(f"Não consegui ler {raw}.")
        if number == 1:
            cv2.imwrite(os.path.join(args.out, "antes.webp"), first[:HEIGHT], [cv2.IMWRITE_WEBP_QUALITY, 82])
        cv2.imwrite(os.path.join(args.out, f"depois-{number}.webp"), first[HEIGHT:], [cv2.IMWRITE_WEBP_QUALITY, 82])
        image = cv2.imread(photo)
        if image is None:
            raise SystemExit(f"Não consegui ler {photo}.")
        thumb = cv2.resize(face_square(image), (192, 192), interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(args.out, f"rosto-{number}.webp"), thumb, [cv2.IMWRITE_WEBP_QUALITY, 84])
        size = os.path.getsize(target)
        total += size
        print(f"troca-{number}.mp4: {size / 2**20:.2f} MB", flush=True)
    print(f"total dos vídeos: {total / 2**20:.1f} MB; imagens gravadas em {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("analyze")
    one.add_argument("video")
    one.add_argument("out")
    two = commands.add_parser("render")
    two.add_argument("video")
    two.add_argument("out")
    two.add_argument("--faces", nargs="+", required=True)
    two.add_argument("--start", type=int, default=0, help="primeiro quadro da gravação a usar")
    two.add_argument("--end", type=int, default=0, help="quadro em que parar (0 = até o fim)")
    two.add_argument("--crop", type=int, nargs=4, metavar=("X", "Y", "W", "H"), default=None,
                     help="recorte na gravação original, antes de reduzir para 720p")
    three = commands.add_parser("web")
    three.add_argument("raw", help="pasta com os troca-N.mp4 gerados por render")
    three.add_argument("out", help="pasta da página (site/assets/demo)")
    three.add_argument("--photos", nargs="+", required=True, help="as mesmas fotos, na mesma ordem")
    three.add_argument("--crf", type=int, default=27)
    three.add_argument("--no-video", action="store_true", help="só refaz as imagens")
    args = parser.parse_args(VIDEO_ARGS)
    return {"analyze": analyze, "render": render, "web": web}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
