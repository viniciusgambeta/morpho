"""Configuração do motor e o pedido de uma sessão ao vivo.

``EngineConfig`` vale pela vida do processo do motor (a janela grava num
arquivo, o motor lê ao iniciar). ``SessionRequest`` acompanha cada comando
``start``: é o que muda entre um "Iniciar" e outro.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Dict, Optional, Union

RESOLUTIONS = {
    "360p": (640, 360), "480p": (854, 480), "720p": (1280, 720), "1080p": (1920, 1080),
}
DEFAULT_MODEL = "hyperswap_1a_256"


@dataclass
class EngineConfig:
    engine_root: str
    shm_name: str
    model: str = DEFAULT_MODEL
    tensorrt: bool = True
    # Sobrescreve atributos de ``modules.globals`` do motor (face_tracking,
    # reprojection, head_pose, face_outline_mask, blink_reveal, ...).
    options: Dict[str, object] = field(default_factory=dict)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path: str) -> "EngineConfig":
        with open(path, encoding="utf-8") as f:
            return cls(**json.load(f))


@dataclass
class SessionRequest:
    # Câmera por nome (ou parte dele) ou índice; ignorada quando ``replay`` é dado.
    camera: Union[str, int, None] = None
    resolution: str = "720p"
    mirror: bool = False
    # Vídeo usado no lugar da câmera, em laço (testes). ``replay_fps`` ``None``
    # usa o ritmo da gravação (arquivo .json ao lado) ou 30.
    replay: Optional[str] = None
    replay_fps: Optional[float] = None
    # Grava os quadros crus da câmera (antes da troca) neste arquivo .avi, por
    # ``record_seconds``. Serve para ajustar o rastreamento com imagem real.
    record_path: Optional[str] = None
    record_seconds: float = 40.0
    # Saída: mandar também para a câmera virtual, e borrar a imagem quando a
    # troca não puder ser feita. ``None`` mantém o que estava valendo.
    virtual_camera: Optional[bool] = None
    protect: Optional[bool] = None

    @classmethod
    def from_command(cls, command: dict) -> "SessionRequest":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in command.items() if k in known})

    def to_command(self) -> dict:
        return {"cmd": "start", **asdict(self)}
