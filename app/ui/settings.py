"""O que o app lembra entre uma abertura e outra: rostos, câmera, ajustes."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from typing import List, Optional

from app import paths

MAX_FACES = 12   # fotos guardadas na galeria; as mais antigas saem


@dataclass
class Settings:
    faces: List[str] = field(default_factory=list)   # mais recente primeiro
    face: Optional[str] = None                       # a selecionada
    camera: Optional[str] = None
    resolution: str = "720p"
    mirror: bool = False
    preview: bool = True                             # mostrar a prévia da câmera na barra lateral
    virtual_camera: bool = True                      # mandar a saída também para a câmera virtual
    protect: bool = True                             # borrar a imagem quando a troca não puder ser feita
    # Ajustes da troca, todos de 0 a 100.
    sharpness: int = 0                               # nitidez extra no rosto trocado
    intensity: int = 100                             # 100 = só o rosto trocado; menos mistura com o real
    mouth: int = 0                                   # quanto da boca real aparece
    eyes: int = 0                                    # quanto dos olhos reais aparece
    adjustments_open: bool = False                   # cartão "Ajustes" aberto
    details: bool = False                            # painel de detalhes técnicos aberto
    window: Optional[List[int]] = None               # x, y, largura, altura da janela
    load_seconds: float = 0.0                        # quanto a última abertura levou (ritmo da barra de progresso)

    def engine_options(self) -> dict:
        """Os ajustes na escala que o motor espera (ver ``bridge.ADJUSTABLE``)."""
        return {
            "sharpness": self.sharpness / 100 * 2.0,   # acima disso a nitidez vira halo
            "opacity": self.intensity / 100,
            "mouth_mask_size": float(self.mouth),
            "eye_reveal": self.eyes / 100,
        }

    def reset_adjustments(self) -> None:
        self.sharpness, self.intensity, self.mouth, self.eyes = 0, 100, 0, 0

    @staticmethod
    def _path() -> str:
        return os.path.join(paths.data_dir(), "settings.json")

    @classmethod
    def load(cls) -> "Settings":
        try:
            with open(cls._path(), encoding="utf-8") as f:
                raw = json.load(f)
            known = {f.name for f in fields(cls)}
            settings = cls(**{k: v for k, v in raw.items() if k in known})
        except (OSError, ValueError, TypeError):
            settings = cls()
        # Fotos apagadas ou movidas somem da galeria em vez de virar um quadrado quebrado.
        settings.faces = [p for p in settings.faces if os.path.isfile(p)][:MAX_FACES]
        if settings.face not in settings.faces:
            settings.face = None
        return settings

    def save(self) -> None:
        try:
            temporary = self._path() + ".tmp"
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=1)
            os.replace(temporary, self._path())
        except OSError:
            pass

    def remember_face(self, path: str) -> None:
        path = os.path.abspath(path)
        self.faces = [path] + [p for p in self.faces if os.path.normcase(p) != os.path.normcase(path)]
        self.faces = self.faces[:MAX_FACES]
        self.face = path

    def forget_face(self, path: str) -> None:
        self.faces = [p for p in self.faces if os.path.normcase(p) != os.path.normcase(path)]
        if self.face and os.path.normcase(self.face) == os.path.normcase(path):
            self.face = None
