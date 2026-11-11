"""Ponte para o motor de troca de rosto (fork beekamai/DeepLiveCam, AGPL-3.0).

O fork guarda o estado em ``modules.globals`` e resolve caminhos a partir da
pasta atual; por isso o processo do motor entra na pasta do fork e põe ela no
``sys.path``. Nada do fork é importado antes de ``setup()``.

O que usamos de lá: detecção e landmarks, rastreador por fluxo óptico, pose da
cabeça, o swapper (com TensorRT) e a reprojeção. O laço do pipeline, a captura
e a saída são nossos.
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import List, Optional, Tuple

import cv2

from app.engine.config import EngineConfig

# Onde o nosso padrão difere do padrão do fork (``cfg.options`` ainda pode mudar).
#
# O fork mede o ângulo da cabeça e, passando de 55° de giro ou 35° de
# inclinação, esconde a troca e mostra o rosto real (some de vez pouco depois:
# 71,5° e 45,5°). É uma escolha estética: num giro extremo a troca borra. Para
# este app o desfecho pior é o outro — mostrar o rosto real sem a pessoa pedir —
# então o limite fica em 360°: o ângulo continua sendo medido (ele também
# desenha o contorno da máscara), mas nunca esconde a troca.
#
# A reprojeção do fork mostra cada quadro novo da câmera com a troca do quadro
# anterior arrastada para a posição atual, para ganhar alguns milissegundos.
# Medido numa gravação real a 20 fps (bench/RESULTADOS.md): em movimento rápido
# essa imagem aproximada fica em média a 26% da distância entre os olhos do
# lugar certo, contra 2% da troca exata — é o "rosto descolando". Vale a pena
# só quando o pipeline é bem mais lento que a câmera, o que não é o caso aqui.
APP_DEFAULTS = {
    "head_yaw_limit": 360,
    "head_pitch_limit": 360,
    "reprojection": False,
}

# Margem (fração do maior lado) acrescentada a uma foto em que nenhum rosto foi
# achado: o detector não enxerga um rosto que ocupa o quadro inteiro.
CLOSE_UP_MARGINS = (0.25, 0.5)


class EngineError(RuntimeError):
    """Falha que o usuário precisa ver (motor ausente, modelo, foto sem rosto)."""

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


def seed_face_models(root: str) -> None:
    """Põe os modelos de detecção de rosto onde a biblioteca que os usa procura.

    O insightface só lê esses modelos da pasta do usuário (``~/.insightface``)
    e, se não achar, baixa da internet. O pacote instalado traz uma cópia em
    ``engine/models/insightface``; na primeira abertura ela vai para lá, e o
    app funciona sem baixar nada.
    """
    source = os.path.join(root, "models", "insightface", "buffalo_l")
    if not os.path.isdir(source):
        return
    target = os.path.join(os.path.expanduser("~"), ".insightface", "models", "buffalo_l")
    try:
        os.makedirs(target, exist_ok=True)
        for name in os.listdir(source):
            origin, copy = os.path.join(source, name), os.path.join(target, name)
            if os.path.isfile(copy) and os.path.getsize(copy) == os.path.getsize(origin):
                continue
            shutil.copyfile(origin, copy + ".tmp")
            os.replace(copy + ".tmp", copy)   # nunca deixa um modelo pela metade no lugar
    except OSError as error:
        raise EngineError(f"Não consegui preparar os modelos de rosto em {target}: {error}", "models_seed") from error


def setup(cfg: EngineConfig) -> None:
    root = cfg.engine_root
    if not os.path.isfile(os.path.join(root, "modules", "globals.py")):
        raise EngineError(f"Motor não encontrado em {root}.", "engine_missing")
    seed_face_models(root)
    sys.path.insert(0, root)
    os.chdir(root)
    argv = ["run.py", "--execution-provider", "cuda", "--face-swapper-model", cfg.model]
    if not cfg.tensorrt:
        argv.append("--no-tensorrt")
    sys.argv = argv

    import run  # noqa: F401  (registra as DLLs CUDA/cuDNN/TensorRT; não inicia o app do fork)
    import modules.globals as G
    from modules import core

    core.parse_args()
    G.headless = True            # mensagens do fork vão para a saída, não para a janela dele
    G.frame_processors = ["face_swapper"]
    G.many_faces = False
    G.map_faces = False
    G.live_mirror = False        # o espelhamento é feito na nossa captura
    G.show_fps = False
    G.virtual_camera = False
    for key, value in APP_DEFAULTS.items():
        setattr(G, key, value)
    for key, value in cfg.options.items():
        if not hasattr(G, key):
            raise EngineError(f"Opção desconhecida do motor: {key}", "bad_option")
        setattr(G, key, value)
    core.limit_resources()


# Ajustes da troca que a tela pode mudar ao vivo: nome -> (mínimo, máximo).
# São atributos de ``modules.globals`` que o motor relê a cada quadro.
ADJUSTABLE = {
    "sharpness": (0.0, 5.0),        # nitidez aplicada sobre o rosto trocado
    "opacity": (0.0, 1.0),          # 1 = só o rosto trocado; menos que isso mistura com o real
    "mouth_mask_size": (0.0, 100.0),  # quanto da boca real aparece (0 = nada)
    "eye_reveal": (0.0, 1.0),       # quanto dos olhos reais aparece (0 = olhos trocados)
}


def apply_options(values: dict) -> dict:
    """Aplica os ajustes pedidos, dentro dos limites; devolve o que ficou valendo."""
    import modules.globals as G

    applied = {}
    for key, value in values.items():
        if key not in ADJUSTABLE:
            continue
        low, high = ADJUSTABLE[key]
        try:
            number = min(high, max(low, float(value)))
        except (TypeError, ValueError):
            continue
        setattr(G, key, number)
        applied[key] = number
    if "mouth_mask_size" in applied:
        G.mouth_mask = applied["mouth_mask_size"] > 0   # o motor usa as duas: a chave e o tamanho
    return applied


def ensure_swapper_model() -> None:
    """Garante o arquivo do modelo de troca (o fork baixa se faltar)."""
    import modules.processors.frame.face_swapper as fs

    if not fs.pre_check():
        raise EngineError(
            "Não consegui obter o modelo de troca de rosto. Verifique a conexão; "
            "o detalhe está no log do motor.", "model_download",
        )


def load_swapper() -> None:
    import modules.processors.frame.face_swapper as fs

    if fs.get_face_swapper() is None:
        raise EngineError("O modelo de troca de rosto não carregou; veja o log do motor.", "model_load")


def load_identity(paths: List[str]) -> Tuple[object, List[str], List[str]]:
    """Analisa as fotos de origem.

    Devolve (identidade, fotos ignoradas, fotos que só funcionaram com margem).
    Levanta ``EngineError`` se nenhuma foto mostrar um rosto.
    """
    from modules import imread_unicode
    from modules.face_analyser import get_many_faces
    from modules.source_identity import SourceIdentity, pick_face

    def find(image) -> Optional[object]:
        face = pick_face(get_many_faces(image), "")
        return face if face is not None and getattr(face, "embedding", None) is not None else None

    faces, kept, skipped, padded = [], [], [], []
    for path in paths:
        image = imread_unicode(path) if path and os.path.exists(path) else None
        face = None
        if image is not None:
            face = find(image)
            if face is None:
                for ratio in CLOSE_UP_MARGINS:
                    margin = int(max(image.shape[:2]) * ratio)
                    canvas = cv2.copyMakeBorder(image, margin, margin, margin, margin,
                                                cv2.BORDER_CONSTANT, value=(128, 128, 128))
                    face = find(canvas)
                    if face is not None:
                        padded.append(path)
                        break
        if face is None:
            skipped.append(path)
        else:
            faces.append(face)
            kept.append(path)
    if not faces:
        raise EngineError(
            "Nenhum rosto encontrado na foto de origem. Use uma foto nítida, de frente, "
            "com o rosto inteiro visível.", "no_source_face",
        )
    return SourceIdentity(faces, kept), skipped, padded


def list_cameras() -> List[dict]:
    """Câmeras do DirectShow: índice, nome e se é uma saída virtual (a nossa ou a do OBS)."""
    from pygrabber.dshow_graph import FilterGraph

    obs_name = None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            r"CLSID\{A3FCE0F5-3493-419F-958A-ABA1250EC20B}") as key:
            obs_name = str(winreg.QueryValue(key, None)) or None
    except OSError:
        pass
    from app.engine.morphocam import DEVICE_NAME

    outputs = {DEVICE_NAME, obs_name}   # as saídas virtuais: nunca servem de webcam de entrada
    return [dict(index=i, name=name, virtual_output=name in outputs)
            for i, name in enumerate(FilterGraph().get_input_devices())]


def resolve_camera(spec) -> dict:
    cameras = list_cameras()
    if not cameras:
        raise EngineError("Nenhuma câmera encontrada.", "no_camera")
    if spec is None or spec == "":
        usable = [c for c in cameras if not c["virtual_output"]]
        raise EngineError("Escolha uma câmera: " + "; ".join(c["name"] for c in usable), "camera_not_chosen")
    if isinstance(spec, int) or str(spec).isdigit():
        match = [c for c in cameras if c["index"] == int(spec)]
    else:
        wanted = str(spec).lower()
        match = [c for c in cameras if c["name"].lower() == wanted] or \
                [c for c in cameras if wanted in c["name"].lower()]
    if not match:
        raise EngineError(f"Câmera '{spec}' não encontrada. Disponíveis: "
                          + "; ".join(c["name"] for c in cameras), "camera_not_found")
    camera = match[0]
    if camera["virtual_output"]:
        # Abrir a saída virtual do OBS como webcam derruba o processo.
        raise EngineError(f"'{camera['name']}' é a saída da câmera virtual, não uma webcam.", "camera_is_output")
    return camera
