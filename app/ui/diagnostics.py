"""Transforma as medições do motor em texto: avisos, detalhes técnicos, resumo."""
from __future__ import annotations

from typing import List, Optional

STAGE_LABELS = [
    ("detect", "detectar"), ("track", "rastrear"), ("landmarks", "landmarks"), ("head_pose", "pose"),
    ("swap", "trocar"), ("post", "pós"), ("compose", "compor"), ("publish", "publicar"),
]
LOW_CAMERA_FPS = 24.0
WARMUP_SECONDS = 3       # segundos iniciais ignorados ao procurar o melhor momento
SLOWDOWN_FACTOR = 2.0    # etapa de troca este tanto mais lenta que o melhor já medido = máquina disputada


def fmt(value, digits: int = 0, dash: str = "–") -> str:
    return dash if value is None else f"{value:.{digits}f}"


def bottleneck(stats: dict) -> str:
    """Frase curta dizendo o que segura as trocas por segundo agora."""
    capture, done = stats.get("capture_fps") or 0.0, stats.get("processed_fps") or 0.0
    busy = (stats.get("stages", {}).get("pipeline") or {}).get("busy_pct")
    if capture <= 0:
        return "a câmera não está entregando quadros"
    if done >= capture * 0.93:
        if busy is not None and busy >= 85:
            return "a câmera, por pouco (o pipeline acompanha, mas já está quase no limite)"
        return "a câmera (o pipeline acompanha todos os quadros com folga)"
    if busy is not None and busy < 80:
        return f"indefinido (pipeline só {busy:.0f}% ocupado e mesmo assim perde quadros)"
    return "o processamento (o pipeline não acompanha a câmera)"


def warnings(stats: Optional[dict], best_swap_ms: Optional[float], show_faces: bool = True) -> List[str]:
    """Avisos sobre a sessão ao vivo, em linguagem de quem usa. Os mais importantes primeiro.

    ``show_faces`` é a opção "mostrar quantos rostos há no enquadramento" das configurações:
    desligada, o aviso de mais de um rosto não aparece (um pôster na parede o deixaria fixo).
    """
    if not stats:
        return []
    found = []
    gpu = stats.get("gpu")
    if gpu and gpu.get("throttled"):
        # É o que mais derruba a fluidez (corta os quadros por segundo quase pela metade) e a
        # pessoa resolve em dois cliques, então vem na frente dos outros avisos.
        found.append(f"A placa de vídeo está em modo de economia ({gpu['clock_mhz']:.0f} de "
                     f"{gpu['clock_max_mhz']:.0f} MHz) e a troca fica mais lenta. Escolha o modo de desempenho "
                     "no aplicativo do fabricante do notebook e deixe-o na tomada.")
    seen = (stats.get("faces_in_frame") or {}).get("max") or 0
    if show_faces and seen > 1:
        found.append(f"Há {seen:.0f} rostos no enquadramento (um quadro ou foto ao fundo também conta). "
                     "A troca vai no maior deles.")
    capture = stats.get("capture_fps") or 0.0
    if 0 < capture < LOW_CAMERA_FPS:
        found.append(f"A câmera entrega só {capture:.0f} quadros por segundo. Mais luz ou uma resolução menor "
                     "costumam ajudar; o app não passa desse teto.")
    swap_ms = (stats.get("stages", {}).get("swap") or {}).get("ms")
    if swap_ms and best_swap_ms and swap_ms > best_swap_ms * SLOWDOWN_FACTOR:
        found.append(f"O computador está ocupado com outra tarefa pesada: a troca está {swap_ms / best_swap_ms:.1f}x "
                     "mais lenta que o normal. Outro programa usando a placa de vídeo costuma ser a causa.")
    processed = stats.get("processed_fps") or 0.0
    hidden = stats.get("swap_hidden_fps") or 0.0
    if processed > 0 and hidden > processed * 0.2:
        found.append(f"O rosto foi achado, mas a troca está sendo escondida em {hidden / processed * 100:.0f}% dos quadros.")
    if processed > 0 and stats.get("frames_without_face", 0) > processed * 0.5:
        found.append("Não estou achando um rosto na imagem da câmera."
                     + (" A imagem está saindo borrada para não mostrar o rosto real."
                        if (stats.get("protected_fps") or 0) > 0 else ""))
    return found


def technical_lines(stats: Optional[dict], camera: Optional[dict], display_fps: Optional[float]) -> List[str]:
    """O painel de detalhes técnicos: os mesmos números que guiaram o desenvolvimento."""
    lines = []
    if camera:
        lines.append(f"Câmera: {camera['name']} · {camera['width']}x{camera['height']} · {camera['fps']:.0f} fps na abertura")
    s = stats
    if not s:
        return lines
    lat_s, lat_o = s["swap_latency_ms"], s["output_latency_ms"]
    lines.append(
        f"Câmera entrega {fmt(s['capture_fps'], 1)} fps · processados {fmt(s.get('processed_fps'), 1)}/s · "
        f"trocas aplicadas {fmt(s['swap_fps'], 1)}/s · saída {fmt(s['output_fps'], 1)} fps · "
        f"exibição {fmt(display_fps, 1)} fps"
    )
    head, strength = s.get("head") or {}, s.get("swap_strength") or {}
    if strength.get("p50") is not None:
        angles = " · ".join(
            f"{name} {fmt((head.get(key) or {}).get('p50'))}°"
            for key, name in (("yaw", "giro"), ("pitch", "inclinação"), ("roll", "rotação"))
        )
        lines.append(
            f"Cabeça: {angles} · intensidade da troca {strength['p50'] * 100:.0f}% · "
            f"rosto com {fmt((s.get('face_height_px') or {}).get('p50'))} px de altura"
        )
    lines.append(
        f"Latência: troca {fmt(lat_s['p50'])} ms (p95 {fmt(lat_s['p95'])}) · "
        f"imagem de saída {fmt(lat_o['p50'])} ms (p95 {fmt(lat_o['p95'])})"
    )
    stages = s.get("stages", {})
    busy = (stages.get("pipeline") or {}).get("busy_pct")
    lines.append(f"O que limita as trocas agora: {bottleneck(s)} · pipeline {fmt(busy)}% ocupado")
    parts = [f"{label} {stages[key]['ms']:.1f}" + (f" ×{stages[key]['per_s']:.0f}/s" if key == "detect" else "")
             for key, label in STAGE_LABELS if key in stages]
    lines.append("Etapas (ms): " + " · ".join(parts))
    g = s.get("gpu")
    if g:
        lines.append(
            f"GPU: {g['util_pct']:.0f}% · {g['clock_mhz']:.0f}/{g['clock_max_mhz']:.0f} MHz · {g['pstate']} · "
            f"{g['vram_used_mib'] / 1024:.1f}/{g['vram_total_mib'] / 1024:.1f} GB · "
            f"{g['power_w']:.0f} W · {g['temp_c']:.0f} °C"
        )
    return lines


def summarize(history: List[dict], display_fps: List[float]) -> dict:
    """Média das medições por segundo, descartando o aquecimento."""
    rows = history[WARMUP_SECONDS:] if len(history) > 2 * WARMUP_SECONDS else history
    if not rows:
        return {}

    def mean(values):
        values = [v for v in values if v is not None]
        return sum(values) / len(values) if values else None

    stages = {}
    for key, _label in STAGE_LABELS + [("pipeline", "")]:
        cells = [r["stages"][key] for r in rows if key in r.get("stages", {})]
        if cells:
            stages[key] = dict(ms=mean(c["ms"] for c in cells), per_s=mean(c["per_s"] for c in cells),
                               busy_pct=mean(c["busy_pct"] for c in cells))
    shown = display_fps[WARMUP_SECONDS:] if len(display_fps) > 2 * WARMUP_SECONDS else display_fps
    return dict(
        seconds=len(rows),
        capture_fps=mean(r["capture_fps"] for r in rows),
        processed_fps=mean(r.get("processed_fps") for r in rows),
        swap_fps=mean(r["swap_fps"] for r in rows),
        swap_hidden_fps=mean(r.get("swap_hidden_fps") for r in rows),
        swap_strength_p50=mean((r.get("swap_strength") or {}).get("p50") for r in rows),
        head_yaw_p50=mean(((r.get("head") or {}).get("yaw") or {}).get("p50") for r in rows),
        head_pitch_p50=mean(((r.get("head") or {}).get("pitch") or {}).get("p50") for r in rows),
        head_roll_p50=mean(((r.get("head") or {}).get("roll") or {}).get("p50") for r in rows),
        face_height_px=mean((r.get("face_height_px") or {}).get("p50") for r in rows),
        faces_in_frame_max=max(((r.get("faces_in_frame") or {}).get("max") or 0) for r in rows),
        face_switches=sum(r.get("face_switches", 0) for r in rows),
        output_fps=mean(r["output_fps"] for r in rows),
        output_writes_fps=mean(r.get("output_writes_fps") for r in rows),
        display_fps=mean(shown),
        swap_latency_p50_ms=mean(r["swap_latency_ms"]["p50"] for r in rows),
        swap_latency_p95_ms=mean(r["swap_latency_ms"]["p95"] for r in rows),
        output_latency_p50_ms=mean(r["output_latency_ms"]["p50"] for r in rows),
        output_latency_p95_ms=mean(r["output_latency_ms"]["p95"] for r in rows),
        frames_without_face=sum(r.get("frames_without_face", 0) for r in rows),
        stages=stages,
        gpu_last=rows[-1].get("gpu"),
        bottleneck=bottleneck(rows[-1]),
    )
