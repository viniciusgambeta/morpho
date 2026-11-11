"""Mede o "descolamento": a que distância do rosto real a troca é desenhada.

Trabalha sobre uma gravação da webcam (``preview.bat --record``) e só com
números: a posição dos cinco pontos do rosto (olhos, nariz, cantos da boca) em
cada quadro. Nenhuma imagem é exibida nem sai do computador.

Referência: o detector rodado em cada quadro da gravação, sem suavização. É a
melhor estimativa de onde o rosto está naquele quadro (ruído de 1 a 2 px).

O que é comparado com a referência, em cada imagem que o app mostraria:
  - saída "exata": o quadro N com a troca calculada para o próprio quadro N;
  - saída "reprojetada": o quadro mais novo com a troca de um quadro anterior
    arrastada para a posição atual.

Erro = distância média entre os pontos desenhados e os de referência, em % da
distância entre os olhos (1% ~ 1 px num rosto típico de webcam 720p).

    python track_eval.py gt    --recording sessao.avi
    python track_eval.py run   --recording sessao.avi --source rosto.jpg --tag padrao [--set chave=valor]
    python track_eval.py score --recording sessao.avi --dump arquivo.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import numpy as np

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WARMUP_SECONDS = 3.0
# Velocidade do rosto, em % da distância entre os olhos por quadro.
STILL_BELOW, FAST_ABOVE = 1.5, 5.0
BINS = ("parado", "lento", "rápido")
MAX_SHOWN_MS = 150.0   # teto do tempo de exibição atribuído a uma saída


def gt_path(recording: str) -> str:
    return recording + ".gt.json"


def compute_gt(recording: str, engine_root: str) -> dict:
    """Pontos do rosto principal em cada quadro, pelo detector do motor."""
    import cv2

    sys.path.insert(0, PROJECT)
    from app.engine import bridge
    from app.engine.config import EngineConfig
    from app.engine.pipeline import choose_face

    recording = os.path.abspath(recording)
    bridge.setup(EngineConfig(engine_root=engine_root, shm_name="gt"))
    from modules.face_analyser import detect_many_faces_fast

    cap = cv2.VideoCapture(recording)
    kps, faces_seen, bbox = [], [], None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        candidates = detect_many_faces_fast(frame) or []
        face, _same = choose_face(candidates, bbox)
        faces_seen.append(len(candidates))
        if face is None:
            kps.append(None)
            bbox = None
        else:
            kps.append([[round(float(x), 2), round(float(y), 2)] for x, y in face.kps])
            bbox = face.bbox
    cap.release()
    gt = dict(frames=len(kps), kps=kps, faces_seen_max=max(faces_seen, default=0),
              frames_without_face=sum(1 for k in kps if k is None))
    with open(gt_path(recording), "w", encoding="utf-8") as f:
        json.dump(gt, f)
    return gt


def _error(drawn, reference) -> float:
    """Distância média entre pontos, em % da distância entre os olhos da referência."""
    drawn, reference = np.asarray(drawn, np.float32), np.asarray(reference, np.float32)
    iod = float(np.linalg.norm(reference[1] - reference[0]))
    return float(np.linalg.norm(drawn - reference, axis=1).mean() / max(iod, 1.0) * 100.0)


def score(recording: str, dump: str) -> dict:
    with open(gt_path(recording), encoding="utf-8") as f:
        gt = json.load(f)
    with open(recording + ".json", encoding="utf-8") as f:
        meta = json.load(f)
    truth = [None if k is None else np.asarray(k, np.float32) for k in gt["kps"]]
    n, fps = len(truth), float(meta["fps"])
    warm = int(WARMUP_SECONDS * fps)

    # Velocidade do rosto em cada quadro, pela referência.
    speed = [0.0] * n
    for i in range(1, n):
        if truth[i] is not None and truth[i - 1] is not None:
            speed[i] = _error(truth[i], truth[i - 1])

    def bin_of(i: int) -> str:
        return BINS[0] if speed[i] < STILL_BELOW else BINS[2] if speed[i] > FAST_ABOVE else BINS[1]

    swaps, outs, pix = {}, [], {}
    with open(dump, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["k"] == "swap":
                swaps[row["seq"]] = row
            elif row["k"] == "out":
                outs.append(row)
            elif row["k"] == "pix":
                pix[row["seq"]] = row["diff"]
    outs.sort(key=lambda r: r["t"])

    def usable(seq: int) -> bool:   # só a primeira passada pela gravação, depois do aquecimento
        return warm <= seq < n and truth[seq] is not None

    # O alinhamento da troca no seu próprio quadro (independe de como é exibida).
    own = {b: [] for b in BINS}
    for seq, row in swaps.items():
        if usable(seq) and row.get("kps") and row.get("applied"):
            own[bin_of(seq)].append(_error(row["kps"], truth[seq]))

    # O que seria exibido, ponderado pelo tempo em que fica na tela.
    shown = {mode: {b: [] for b in BINS} for mode in ("exact", "reproj")}
    ages = []
    for row, nxt in zip(outs, outs[1:] + [None]):
        duration = MAX_SHOWN_MS if nxt is None else min(MAX_SHOWN_MS, (nxt["t"] - row["t"]) * 1000)
        if row["mode"] == "reproj":
            seq, drawn = row["seq"], row.get("kps")
        else:
            seq = row["src"]
            drawn = (swaps.get(seq) or {}).get("kps")
        if not usable(seq) or drawn is None:
            continue
        shown[row["mode"]][bin_of(seq)].append((_error(drawn, truth[seq]), duration))
        if row.get("age_ms") is not None:
            ages.append((row["age_ms"], duration))

    def weighted(pairs):
        if not pairs:
            return None
        values, weights = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
        order = np.argsort(values)
        cum = np.cumsum(weights[order]) / weights.sum()
        return dict(mean=float((values * weights).sum() / weights.sum()),
                    p95=float(values[order][min(len(values) - 1, int(np.searchsorted(cum, 0.95)))]),
                    time_ms=float(weights.sum()), n=len(pairs))

    def plain(values):
        return None if not values else dict(mean=float(np.mean(values)), p95=float(np.percentile(values, 95)), n=len(values))

    everything = [p for mode in shown.values() for b in BINS for p in mode[b]]
    moving = [p for mode in shown.values() for b in BINS[1:] for p in mode[b]]
    total_ms = sum(p[1] for p in everything) or 1.0
    pix_bins = {b: [d for s, d in pix.items() if usable(s) and bin_of(s) == b] for b in BINS}
    frames_bin = {b: sum(1 for i in range(warm, n) if truth[i] is not None and bin_of(i) == b) for b in BINS}
    return dict(
        recording=os.path.basename(recording), frames=n, fps=fps, frames_per_bin=frames_bin,
        displayed_all=weighted(everything), displayed_moving=weighted(moving),
        displayed={mode: {b: weighted(shown[mode][b]) for b in BINS} for mode in shown},
        reproj_time_share_pct=100 * sum(p[1] for b in BINS for p in shown["reproj"][b]) / total_ms,
        image_age_ms=weighted(ages),
        swap_own_frame={b: plain(own[b]) for b in BINS},
        reproj_vs_exact_pixel_diff={b: plain(pix_bins[b]) for b in BINS},
        processed_share_pct=100 * sum(1 for s in swaps if usable(s)) / max(1, sum(frames_bin.values())),
    )


def _f(cell, key="mean", digits=1):
    return "  –  " if not cell or cell.get(key) is None else f"{cell[key]:5.{digits}f}"


def report(result: dict, tag: str) -> None:
    d = result
    print(f"== {tag} | {d['recording']} | {d['frames']} quadros a {d['fps']:.1f} fps | "
          f"quadros por velocidade: {d['frames_per_bin']}")
    print(f"   erro do que aparece na tela (% dist. entre olhos): geral média {_f(d['displayed_all'])} "
          f"p95 {_f(d['displayed_all'], 'p95')} | em movimento média {_f(d['displayed_moving'])} "
          f"p95 {_f(d['displayed_moving'], 'p95')}")
    print(f"   imagem reprojetada ocupa {d['reproj_time_share_pct']:.0f}% do tempo de tela | "
          f"idade da imagem exibida: média {_f(d['image_age_ms'], 'mean', 0)} ms, p95 {_f(d['image_age_ms'], 'p95', 0)} ms | "
          f"quadros processados: {d['processed_share_pct']:.0f}%")
    for label, table in (("saída exata      ", d["displayed"]["exact"]), ("saída reprojetada", d["displayed"]["reproj"]),
                         ("troca no próprio quadro", d["swap_own_frame"])):
        print(f"   {label}: " + " | ".join(f"{b} {_f(table[b])} (p95 {_f(table[b], 'p95')})" for b in BINS))
    print("   reprojetada x exata, diferença de imagem (0-255): "
          + " | ".join(f"{b} {_f(d['reproj_vs_exact_pixel_diff'][b])}" for b in BINS))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["gt", "run", "score"])
    p.add_argument("--recording", required=True)
    p.add_argument("--source", help="foto do rosto de origem (run)")
    p.add_argument("--dump", help="arquivo .jsonl do motor (score)")
    p.add_argument("--tag", default="padrao")
    p.add_argument("--set", action="append", default=[], metavar="CHAVE=JSON")
    p.add_argument("--out", default=os.path.join(PROJECT, "bench", "results", "rastreamento"))
    p.add_argument("--engine-root", default=os.environ.get("MORPHO_ENGINE_ROOT") or r"C:\Users\vinic\dlc-lab\beekamai")
    args = p.parse_args()
    recording = os.path.abspath(args.recording)

    if args.command == "gt":
        gt = compute_gt(recording, args.engine_root)
        print(f"referência gravada: {gt['frames']} quadros, {gt['frames_without_face']} sem rosto, "
              f"até {gt['faces_seen_max']} rostos no quadro")
        sys.stdout.flush()
        os._exit(0)   # as sessões do detector não precisam de encerramento ordenado

    os.makedirs(args.out, exist_ok=True)
    if args.command == "run":
        if not os.path.exists(gt_path(recording)):
            sys.exit("rode primeiro: track_eval.py gt --recording ...")
        with open(recording + ".json", encoding="utf-8") as f:
            seconds = float(json.load(f)["seconds"])
        # Os dados da gravação e os números do motor ficam fora do OneDrive.
        work = os.path.join(os.path.dirname(recording), "eval")
        os.makedirs(work, exist_ok=True)
        dump = os.path.join(work, f"{args.tag}.jsonl")
        env = dict(os.environ, MORPHO_TRACK_DUMP=dump, PYTHONPATH=PROJECT,
                   MORPHO_DATA_DIR=os.path.join(work, "app-data"))
        command = [sys.executable, "-m", "app.ui", "--source", os.path.abspath(args.source), "--replay", recording,
                   "--autostart", "--run-seconds", str(seconds + 2), "--give-up-seconds", "150", "--offscreen"]
        for item in args.set:
            command += ["--set", item]
        code = subprocess.run(command, cwd=PROJECT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        if code != 0 or not os.path.exists(dump):
            sys.exit(f"a execução falhou (código {code})")
        args.dump = dump

    result = score(recording, args.dump)
    result["tag"], result["options"] = args.tag, args.set
    with open(os.path.join(args.out, f"{args.tag}.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    report(result, args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
