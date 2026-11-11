"""Gera um vídeo de teste sintético e determinístico a partir de uma foto de rosto.

O vídeo imita uma webcam 720p30 em MJPG: um rosto sobre um fundo fixo, com
três trechos:

    0-3 s    aquecimento (parado; descartado nas medições)
    3-11 s   "rest":   rosto quase parado (deriva de poucos pixels)
    11-24 s  "motion": translação, zoom, rotação no plano e variação de brilho

Não substitui uma gravação real de webcam (não há mudança de expressão nem
oclusão por mão), mas dá a mesma entrada, quadro a quadro, para todos os
projetos comparados.

    python make_clip.py --face rosto.jpg --out clip.avi
"""
from __future__ import annotations

import argparse
import math

import cv2
import numpy as np

W, H, FPS = 1280, 720, 30
WARM_END, REST_END, TOTAL = 3.0, 11.0, 24.0
BASE_SIZE = 470  # lado do retrato no quadro; o rosto fica com ~300 px de altura


def background(rng: np.random.Generator) -> np.ndarray:
    """Um "cômodo" desfocado: gradiente + manchas de baixa frequência."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    base = np.stack([
        90 + 40 * xx / W + 20 * yy / H,
        100 + 25 * yy / H,
        110 - 30 * xx / W + 35 * yy / H,
    ], axis=-1)
    blobs = rng.normal(0, 1, (H // 40, W // 40, 3)).astype(np.float32)
    blobs = cv2.resize(blobs, (W, H), interpolation=cv2.INTER_CUBIC) * 22
    return np.clip(cv2.GaussianBlur(base + blobs, (0, 0), 6), 0, 255)


def portrait_layer(face_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Retrato quadrado + máscara elíptica suave (cabeça e cabelo)."""
    side = min(face_bgr.shape[:2])
    y0 = (face_bgr.shape[0] - side) // 2
    x0 = (face_bgr.shape[1] - side) // 2
    square = cv2.resize(face_bgr[y0:y0 + side, x0:x0 + side], (BASE_SIZE, BASE_SIZE),
                        interpolation=cv2.INTER_AREA).astype(np.float32)
    mask = np.zeros((BASE_SIZE, BASE_SIZE), np.float32)
    c = BASE_SIZE // 2
    cv2.ellipse(mask, (c, c), (int(BASE_SIZE * 0.40), int(BASE_SIZE * 0.47)), 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), BASE_SIZE * 0.035)
    return square, mask


def pose(t: float) -> tuple[float, float, float, float, float]:
    """(dx, dy, escala, ângulo em graus, ganho de brilho) no instante t."""
    if t < WARM_END:
        return 0.0, 0.0, 1.0, 0.0, 1.0
    if t < REST_END:
        u = t - WARM_END
        return 3 * math.sin(u * 1.3), 2 * math.sin(u * 0.9 + 1), 1 + 0.005 * math.sin(u * 0.7), 0.3 * math.sin(u), 1.0
    u = t - REST_END
    ramp = min(1.0, u / 1.5)  # entra no movimento sem salto
    dx = ramp * 260 * math.sin(2 * math.pi * u / 3.2)
    dy = ramp * 70 * math.sin(2 * math.pi * u / 2.1)
    scale = 1 + ramp * (0.05 + 0.25 * math.sin(2 * math.pi * u / 5.0))
    angle = ramp * 14 * math.sin(2 * math.pi * u / 2.7)
    gain = 1 + ramp * 0.12 * math.sin(2 * math.pi * u / 4.3)
    return dx, dy, scale, angle, gain


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--face", required=True, help="foto com um rosto (o 'usuário da webcam')")
    p.add_argument("--out", required=True, help="arquivo .avi de saída (MJPG)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--decoy", help="foto de outro rosto, colada pequena e parada à esquerda "
                                   "(imita um retrato na parede ao fundo)")
    p.add_argument("--gap", help="a:b em segundos: trecho em que o rosto some do quadro "
                                 "(imita a pessoa saindo da frente da câmera)")
    args = p.parse_args()
    gap = tuple(float(v) for v in args.gap.split(":")) if args.gap else None

    face = cv2.imdecode(np.fromfile(args.face, np.uint8), cv2.IMREAD_COLOR)
    if face is None:
        raise SystemExit(f"não consegui ler {args.face}")
    rng = np.random.default_rng(args.seed)
    bg = background(rng)
    if args.decoy:
        decoy = cv2.imdecode(np.fromfile(args.decoy, np.uint8), cv2.IMREAD_COLOR)
        if decoy is None:
            raise SystemExit(f"não consegui ler {args.decoy}")
        size = 150  # um "quadro" de 150 px, bem menor que o rosto principal
        frame_px = 8
        x0, y0 = 70, 110
        bg[y0 - frame_px:y0 + size + frame_px, x0 - frame_px:x0 + size + frame_px] = (40, 60, 90)  # moldura
        bg[y0:y0 + size, x0:x0 + size] = cv2.resize(decoy, (size, size), interpolation=cv2.INTER_AREA)
    square, mask = portrait_layer(face)
    writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    writer.set(cv2.VIDEOWRITER_PROP_QUALITY, 92)
    if not writer.isOpened():
        raise SystemExit(f"não consegui abrir {args.out} para escrita")

    half = BASE_SIZE / 2
    for i in range(int(TOTAL * FPS)):
        dx, dy, scale, angle, gain = pose(i / FPS)
        m = cv2.getRotationMatrix2D((half, half), angle, scale)
        m[0, 2] += W / 2 - half + dx
        m[1, 2] += H / 2 - half + 20 + dy
        layer = cv2.warpAffine(square, m, (W, H), flags=cv2.INTER_LINEAR)
        alpha = cv2.warpAffine(mask, m, (W, H), flags=cv2.INTER_LINEAR)[..., None]
        if gap and gap[0] <= i / FPS < gap[1]:
            alpha = alpha * 0.0   # só o fundo: ninguém na frente da câmera
        frame = (bg * (1 - alpha) + layer * alpha) * gain
        frame += rng.normal(0, 2.0, frame.shape).astype(np.float32)  # ruído de sensor
        writer.write(np.clip(frame, 0, 255).astype(np.uint8))
    writer.release()
    print(f"ok: {args.out}  {W}x{H}@{FPS}  {TOTAL:.0f}s  rest={WARM_END:.0f}:{REST_END:.0f} motion={REST_END:.0f}:{TOTAL:.0f}")


if __name__ == "__main__":
    main()
