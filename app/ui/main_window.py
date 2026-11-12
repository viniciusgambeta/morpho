"""A janela do app: escolher o rosto, conferir a câmera, trocar."""
from __future__ import annotations

import json
import math
import os
import re
import time
from typing import List, Optional

from PySide6.QtCore import QEvent, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from app import APP_NAME, paths
from app.engine.config import EngineConfig, SessionRequest
from app.shared_frame import FrameReader
from app.ui import diagnostics as diag
from app.ui import theme
from app.ui.engine_process import EngineProcess
from app.ui.settings import Settings
from app.ui.widgets import (
    CameraPreview, Card, FaceGallery, FrameView, IconButton, Mascot, PrimaryButton, Segmented, SideScroll,
    SliderRow, SwitchRow, app_icon, play_honk,
)

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
QUALITY_CHOICES = [("480p", "Leve"), ("720p", "Padrão"), ("1080p", "Nítida")]
THEME_CHOICES = [("dark", "Escuro"), ("light", "Claro")]
AUTOSAVE_SECONDS = 5     # intervalo de gravação das medições com a janela aberta
TOAST_SECONDS = 4.5      # tempo de um recado passageiro no palco
# Nomes que costumam ser câmera virtual ou de outro aparelho: ficam por último
# na hora de sugerir uma câmera, mas continuam na lista.
UNLIKELY_CAMERA = ("virtual", "quest", "broadcast", "obs", "iriun", "utility")
_TRT_BUILD = re.compile(r"TensorRT: preparing engine for (.+?) \(")
# Roteiro da gravação: (fração do tempo em que começa, o que fazer).
RECORD_SCRIPT = [
    (0.000, "Olhe para a câmera, parado"),
    (0.125, "Vire a cabeça devagar: esquerda, centro, direita, centro"),
    (0.325, "Incline devagar: para cima, centro, para baixo, centro"),
    (0.500, "Mexa a cabeça de um lado para o outro, mais rápido"),
    (0.700, "Aproxime e afaste o rosto da câmera"),
    (0.850, "Passe a mão na frente do rosto algumas vezes"),
]
LIVE_STATES = ("running", "stopping")
DEFAULT_LOAD_SECONDS = 14.0   # quanto a abertura costuma levar, até este computador ter a própria medida
# O motor avisa "preparando o modelo X" em toda abertura, com o modelo já otimizado ou não.
# Já otimizado, cada um carrega em poucos segundos; passando disto, é a otimização da
# primeira vez (minutos), e a tela passa a dizer isso.
OPTIMIZING_AFTER_SECONDS = 12.0


def suggest_camera(names: List[str], remembered: Optional[str]) -> Optional[str]:
    """A câmera lembrada, se ainda existe. Sem lembrança, só escolhe sozinho quando não há dúvida.

    Com mais de uma webcam de verdade ligada, quem escolhe é a pessoa: a lista fica em
    "Escolha a câmera" e as opções de qualidade só aparecem depois da escolha.
    """
    if remembered in names:
        return remembered
    if remembered:   # nome parcial, vindo da linha de comando
        partial = [name for name in names if str(remembered).lower() in name.lower()]
        if partial:
            return partial[0]
    likely = [name for name in names if not any(word in name.lower() for word in UNLIKELY_CAMERA)]
    return likely[0] if len(likely) == 1 else None


class MainWindow(QWidget):
    def __init__(self, args) -> None:
        super().__init__()
        self.args = args
        self.settings = Settings.load()
        self.setWindowTitle(APP_NAME)
        if getattr(args, "theme", None):
            self.settings.theme = args.theme
        self.setWindowIcon(app_icon())
        self.setStyleSheet(theme.apply(self.settings.theme))
        self.setAcceptDrops(True)
        self.setMinimumSize(980, 620)
        geometry = self.settings.window
        if geometry and len(geometry) == 4 and not args.offscreen and self._on_some_screen(geometry):
            self.setGeometry(*geometry)
        else:
            self.resize(1240, 760)

        # estado ----------------------------------------------------------------
        self.state = "starting"
        self.detail = ""
        self.error = ""
        self.engine_dead = False
        self.loaded = False
        self.face_ok = False
        self.good_face: Optional[str] = None       # última foto que o motor aceitou
        self.face_note = ""
        self.camera_info: Optional[dict] = None    # câmera aberta agora (prévia ou ao vivo)
        self.last_camera: Optional[dict] = None    # a da última sessão, para o relatório
        self.stats: Optional[dict] = None
        self.history: List[dict] = []
        self.display_history: List[float] = []
        self.shown = 0
        self.shown_since = time.perf_counter()
        self.display_fps: Optional[float] = None
        self.running_since: Optional[float] = None
        self.opened_at = time.perf_counter()
        self.autostarted = False
        self.stop_clicked = False
        self.pending_clicks = list(args.click)
        self.recording_since: Optional[float] = None
        self.recording_seconds = 0.0
        self.recorded: Optional[dict] = None
        self.vcam_available = False     # o motor diz ao carregar
        self.vcam_reason = ""
        self.vcam_device: Optional[str] = None
        self.vcam_backend: Optional[str] = None   # "morpho" (a nossa) ou "obs"
        self.vcam_on = False            # transmitindo agora
        self.vcam_watched: Optional[bool] = None  # algum programa está puxando a imagem? (só a nossa sabe)
        self.vcam_error = ""
        self.building = False           # primeira vez: os modelos estão sendo otimizados (minutos)
        self.preparing_since: Optional[float] = None   # quando o motor começou a preparar o modelo atual
        self.load_expected = self.settings.load_seconds or DEFAULT_LOAD_SECONDS
        self.painted_at = 0.0
        self.blur_now = False           # pausa de privacidade
        self.flash: Optional[tuple] = None   # (texto, cor, até quando) — recado passageiro
        self.reader: Optional[FrameReader] = None        # a saída (palco)
        self.camera_reader: Optional[FrameReader] = None # a câmera crua, pequena (barra lateral)
        # Melhor tempo da etapa de troca já medido neste computador, por modelo:
        # a régua para dizer "a máquina está ocupada com outra coisa".
        self.baseline_path = os.path.join(paths.data_dir(), "baseline.json")
        try:
            with open(self.baseline_path, encoding="utf-8") as f:
                self.baseline = json.load(f)
        except (OSError, ValueError):
            self.baseline = {}
        self.best_swap_ms: Optional[float] = self.baseline.get(args.model)

        if args.source:   # atalho de linha de comando: entra na galeria como se tivesse sido escolhida
            self.settings.remember_face(args.source[0])
        if args.camera:
            self.settings.camera = args.camera
        if args.resolution:
            self.settings.resolution = args.resolution
        if args.mirror:
            self.settings.mirror = True
        if args.virtual_camera:
            self.settings.virtual_camera = True
        if args.no_preview:
            self.settings.preview = False

        self.engine = EngineProcess()   # criado antes da tela: os textos consultam o caminho do log
        self._build()
        self._load_cameras()
        self.show_gallery()
        if self.settings.face:
            self.face_note = "Analisando a foto…"
        if getattr(args, "open_settings", False):
            self.pages.setCurrentIndex(1)

        self.engine.event.connect(self.on_event)
        self.engine.output.connect(self.on_output)
        self.engine.exited.connect(self.on_exit)
        options = {}
        for item in args.set:
            key, _, raw = item.partition("=")
            options[key] = json.loads(raw)
        self.engine.start(EngineConfig(
            engine_root=args.engine_root, shm_name=f"morpho_{os.getpid()}_{int(time.time())}",
            model=args.model, tensorrt=not args.no_tensorrt, options=options,
        ))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(8)
        self.save_timer = QTimer(self)
        self.save_timer.timeout.connect(self.write_report)
        self.save_timer.start(AUTOSAVE_SECONDS * 1000)
        self.option_timer = QTimer(self)        # junta os arrastos de um controle num envio só
        self.option_timer.setSingleShot(True)
        self.option_timer.timeout.connect(self.send_adjustments)
        if args.quit_after:
            QTimer.singleShot(int(args.quit_after * 1000), self.close)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.stop_live)
        QShortcut(QKeySequence("B"), self, activated=lambda: self.blur_button.click() if self.blur_button.isVisible() else None)
        QShortcut(QKeySequence("F"), self, activated=lambda: self.photo_button.click() if self.photo_button.isVisible() else None)
        self.refresh()

    @staticmethod
    def _on_some_screen(geometry: List[int]) -> bool:
        """A posição lembrada ainda cai num monitor ligado? (Evita abrir fora da tela
        depois de desconectar um monitor.)"""
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QGuiApplication

        x, y, w, h = geometry
        title_bar = QRect(x + 40, y, max(1, w - 80), 30)
        return any(screen.availableGeometry().intersects(title_bar) for screen in QGuiApplication.screens())

    # montagem ---------------------------------------------------------------------
    def _build(self) -> None:
        s = self.settings
        self.view = FrameView()
        self.view.intro_done.connect(self.refresh)
        self.photo_button = QPushButton("Tirar foto")
        self.photo_button.setObjectName("overlay")
        self.photo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.photo_button.setToolTip("Salva a imagem atual na pasta Imagens (tecla F)")
        self.photo_button.clicked.connect(self.take_photo)
        self.blur_button = QPushButton("Borrar agora")
        self.blur_button.setObjectName("overlay")
        self.blur_button.setCheckable(True)
        self.blur_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.blur_button.setToolTip("Borra tudo na hora, na janela e na câmera virtual, até clicar de novo (tecla B)")
        self.blur_button.toggled.connect(self.on_blur_toggled)
        self.view.add_button(self.photo_button)
        self.view.add_button(self.blur_button)

        self.details = QLabel()
        self.details.setObjectName("details")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setVisible(s.details)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        left.addWidget(self.view, 1)
        left.addWidget(self.details, 0)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_home())
        self.pages.addWidget(self._build_settings())

        self.button = PrimaryButton()
        self.button.clicked.connect(self.toggle)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        footer = QVBoxLayout()
        footer.setContentsMargins(16, 10, 16, 14)
        footer.setSpacing(8)
        footer.addWidget(self.button)
        footer.addWidget(self.status)
        footer_widget = QWidget()
        footer_widget.setObjectName("footer")
        footer_widget.setLayout(footer)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(0)
        side.addWidget(self.pages, 1)
        side.addWidget(footer_widget, 0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(theme.SIDEBAR_WIDTH)
        sidebar.setLayout(side)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(left, 1)
        root.addWidget(sidebar, 0)

    def _page(self, header: QHBoxLayout, cards: list) -> SideScroll:
        """Uma página da coluna: cabeçalho, cartões e o resto vazio, tudo rolável."""
        body = QVBoxLayout()
        body.setContentsMargins(SideScroll.MARGIN, 14, SideScroll.MARGIN, 8)
        body.setSpacing(12)
        body.addLayout(header)
        for card in cards:
            body.addWidget(card)
        body.addStretch(1)
        body_widget = QWidget()
        body_widget.setObjectName("sidebarBody")
        body_widget.setLayout(body)
        return SideScroll(body_widget)

    def _build_home(self) -> SideScroll:
        """A tela inicial: só o rosto e a câmera. O resto mora nas configurações."""
        s = self.settings
        # rosto
        self.gallery = FaceGallery()
        self.gallery.picked.connect(self.choose_face)
        self.gallery.none_picked.connect(self.choose_no_face)
        self.gallery.add_requested.connect(self.browse_face)
        self.gallery.remove_requested.connect(self.remove_face)
        self.face_label = QLabel()
        self.face_label.setObjectName("note")
        self.face_label.setWordWrap(True)
        face_card = Card("Rosto")
        face_card.add(self.gallery)
        face_card.add(self.face_label)

        # câmera
        self.cameras = QComboBox()
        # A largura da lista é a da coluna, não a do nome mais comprido.
        self.cameras.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cameras.setMinimumContentsLength(8)
        self.cameras.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.cameras.setPlaceholderText("Escolha a câmera")
        self.cameras.currentTextChanged.connect(self.on_camera_changed)
        refresh_cameras = QPushButton("Atualizar")
        refresh_cameras.setObjectName("small")
        refresh_cameras.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_cameras.setToolTip("Procurar câmeras de novo")
        refresh_cameras.clicked.connect(self._load_cameras)
        camera_row = QHBoxLayout()
        camera_row.setSpacing(8)
        camera_row.setContentsMargins(0, 0, 0, 0)
        camera_row.addWidget(self.cameras, 1)
        camera_row.addWidget(refresh_cameras, 0)
        camera_holder = QWidget()
        camera_holder.setLayout(camera_row)
        self.camera_view = CameraPreview()
        self.camera_view.setToolTip("A imagem da câmera, como ela chega. Aparece só aqui: não vai para a câmera virtual.")
        # A qualidade só aparece depois que há uma câmera escolhida.
        self.quality = Segmented(QUALITY_CHOICES, s.resolution)
        self.quality.setToolTip("Tamanho da imagem pedida à câmera. Leve = 480p, Padrão = 720p, Nítida = 1080p.")
        self.quality.changed.connect(self.on_camera_option_changed)
        camera_card = Card("Câmera")
        camera_card.add(camera_holder)
        camera_card.add(self.camera_view)
        camera_card.add(self.quality)

        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        self.logo = Mascot(30, "SIDEBAR", compact=True)
        self.logo.play("parado")
        gear = IconButton("gear", "Configurações")
        gear.clicked.connect(lambda: self.open_page(1))
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 0, 2)
        header.setSpacing(10)
        header.addWidget(self.logo, 0)
        header.addWidget(brand, 1)
        header.addWidget(gear, 0)
        return self._page(header, [face_card, camera_card])

    def _build_settings(self) -> SideScroll:
        """As configurações: saída, câmera, ajustes da troca, o que aparece na tela e a aparência."""
        s = self.settings
        # saída
        self.vcam_row = SwitchRow("Enviar para a câmera virtual", s.virtual_camera)
        self.vcam_row.switch.setEnabled(False)   # só depois que o motor disser se ela existe aqui
        self.vcam_row.toggled.connect(self.on_output_changed)
        self.protect_row = SwitchRow("Borrar se a troca falhar", s.protect)
        self.protect_row.setToolTip("Quando o rosto não é encontrado (mão na frente, cabeça muito virada, você fora\n"
                                    "do quadro), a imagem sai borrada em vez de mostrar o rosto real.\n"
                                    "Vale para a janela e para a câmera virtual.")
        self.protect_row.toggled.connect(self.on_output_changed)
        output_card = Card("Saída")
        output_card.add(self.vcam_row)
        output_card.add(self.protect_row)

        # câmera
        self.mirror = SwitchRow("Espelhar a imagem", s.mirror)
        self.mirror.toggled.connect(self.on_camera_option_changed)
        self.preview_row = SwitchRow("Mostrar a prévia da câmera", s.preview)
        self.preview_row.setToolTip("Com a prévia, a câmera fica ligada enquanto o app está aberto,\n"
                                    "para você conferir qual é a câmera e o enquadramento.\n"
                                    "Desligada, a câmera só liga quando a troca começa.")
        self.preview_row.toggled.connect(self.on_preview_toggled)
        camera_card = Card("Câmera")
        camera_card.add(self.mirror)
        camera_card.add(self.preview_row)

        # ajustes da troca
        self.sharpness = SliderRow("Nitidez", s.sharpness, "Realça os detalhes do rosto trocado.")
        self.intensity = SliderRow("Intensidade da troca", s.intensity,
                                   "100% mostra só o rosto escolhido. Abaixo disso ele se mistura com o seu.")
        self.mouth = SliderRow("Minha boca", s.mouth,
                               "Deixa a sua boca de verdade aparecer: a fala fica mais natural, mas é a sua boca.")
        self.eyes = SliderRow("Meus olhos", s.eyes,
                              "Deixa os seus olhos de verdade aparecerem: o olhar fica mais natural, mas são os seus.")
        reset = QPushButton("Restaurar o padrão")
        reset.setObjectName("ghost")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self.reset_adjustments)
        adjust_card = Card("Ajustes da troca")
        for row in (self.sharpness, self.intensity, self.mouth, self.eyes):
            row.changed.connect(self.on_adjustment_changed)
            adjust_card.add(row)
        adjust_card.body.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)

        # na tela
        self.fps_row = SwitchRow("Mostrar os quadros por segundo", s.show_fps)
        self.faces_row = SwitchRow("Mostrar quantos rostos há no enquadramento", s.show_faces)
        self.faces_row.setToolTip("Um quadro ou uma foto ao fundo também conta como rosto.\nA troca vai sempre no maior deles.")
        self.details_row = SwitchRow("Mostrar os detalhes técnicos", s.details)
        for row in (self.fps_row, self.faces_row, self.details_row):
            row.toggled.connect(self.on_display_changed)
        display_card = Card("Na tela")
        display_card.add(self.fps_row)
        display_card.add(self.faces_row)
        display_card.add(self.details_row)

        # aparência
        self.theme_choice = Segmented(THEME_CHOICES, s.theme)
        self.theme_choice.changed.connect(self.on_theme_changed)
        self.sound_row = SwitchRow("Grito do ganso ao abrir", s.sound)
        self.sound_row.toggled.connect(self.on_display_changed)
        look_card = Card("Aparência")
        look_card.add(self.theme_choice)
        look_card.add(self.sound_row)

        about = QLabel(f"{APP_NAME} · gratuito, para uso pessoal e não comercial")
        about.setObjectName("about")
        about.setWordWrap(True)

        back = IconButton("back", "Voltar")
        back.clicked.connect(lambda: self.open_page(0))
        title = QLabel("Configurações")
        title.setObjectName("pageTitle")
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 2)
        header.setSpacing(8)
        header.addWidget(back, 0)
        header.addWidget(title, 1)
        return self._page(header, [output_card, camera_card, adjust_card, display_card, look_card, about])

    def open_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.pages.currentWidget().verticalScrollBar().setValue(0)

    def show_gallery(self) -> None:
        self.gallery.set_faces(self.settings.faces, self.settings.face, self.settings.without_face)

    def _load_cameras(self) -> None:
        try:
            from app.engine.bridge import list_cameras

            names = [c["name"] for c in list_cameras() if not c["virtual_output"]]
        except Exception as error:   # sem câmera ou sem acesso ao DirectShow: a tela continua utilizável
            names = []
            self.error = f"Não consegui listar as câmeras: {error}"
        chosen = suggest_camera(names, self.settings.camera)
        self.cameras.blockSignals(True)
        self.cameras.clear()
        self.cameras.addItems(names)
        if chosen:
            self.cameras.setCurrentText(chosen)
        else:
            self.cameras.setCurrentIndex(-1)   # mostra "Escolha a câmera"
        self.cameras.blockSignals(False)
        changed = chosen != self.settings.camera
        self.settings.camera = chosen
        if hasattr(self, "status"):
            if changed:
                self.sync_camera()
            self.refresh()

    # câmera: prévia e sessão ------------------------------------------------------------
    def has_camera(self) -> bool:
        return bool(self.settings.camera or self.args.replay)

    def session_request(self, live: bool) -> SessionRequest:
        args = self.args
        record = None
        if live and args.record:
            record = os.path.join(paths.recordings_dir(), time.strftime("sessao-%Y%m%d-%H%M%S.avi"))
        return SessionRequest(
            camera=self.settings.camera, resolution=self.settings.resolution, mirror=self.settings.mirror,
            replay=os.path.abspath(args.replay) if args.replay else None, replay_fps=args.replay_fps,
            record_path=record, record_seconds=args.record_seconds,
            virtual_camera=(self.settings.virtual_camera and self.vcam_available) if live else None,
            protect=self.settings.protect if live else None,
        )

    def sync_camera(self) -> None:
        """Fora do ao vivo, deixa a câmera como a tela pede: em prévia ou desligada."""
        if not self.loaded or self.engine_dead or self.state in LIVE_STATES:
            return
        wants = self.settings.preview and self.has_camera() and not self.isMinimized()
        if wants:
            self.engine.send(**dict(self.session_request(live=False).to_command(), cmd="preview"))
        elif self.state in ("preview", "opening_camera"):
            self.engine.send(cmd="stop")

    def can_start(self) -> bool:
        return (self.loaded and not self.engine_dead and self.state in ("idle", "preview")
                and (self.face_ok or self.settings.without_face) and self.has_camera())

    def toggle(self) -> None:
        if self.state == "running":
            self.stop_live()
        elif self.can_start():
            self.start()
        self.refresh()

    def start(self) -> None:
        self.error = ""
        self.stats = None
        self.recorded = None
        self.engine.send(**self.session_request(live=True).to_command())
        if self.state != "preview":
            self.state, self.detail = "opening_camera", ""

    def stop_live(self) -> None:
        if self.state != "running":
            return
        if self.blur_now:
            self.blur_button.setChecked(False)
        if self.settings.preview and not self.isMinimized():
            self.engine.send(**dict(self.session_request(live=False).to_command(), cmd="preview"))
        else:
            self.engine.send(cmd="stop")
        self.state, self.detail = "stopping", ""
        self.refresh()

    def changeEvent(self, event) -> None:
        # Janela minimizada não precisa da câmera ligada só para a prévia.
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "status"):
            self.sync_camera()
        super().changeEvent(event)

    # ações do usuário -------------------------------------------------------------
    def choose_face(self, path: str) -> None:
        if (self.face_ok and self.settings.face
                and os.path.normcase(os.path.abspath(path)) == os.path.normcase(self.settings.face)):
            return   # já é o rosto em uso: nada a analisar de novo
        self.settings.remember_face(path)
        self.show_gallery()
        self.face_ok = False
        self.face_note = "Analisando a foto…"
        self.settings.save()
        if self.loaded:
            self.engine.send(cmd="set_source", paths=[self.settings.face])
        self.refresh()

    def choose_no_face(self) -> None:
        """Sem rosto: a câmera sai como é, sem troca. Vale na hora, também ao vivo."""
        self.settings.choose_no_face()
        self.show_gallery()
        self.face_ok = False
        self.face_note = ""
        self.settings.save()
        if self.loaded:
            self.engine.send(cmd="set_source", paths=[])
        self.refresh()

    def browse_face(self) -> None:
        start = os.path.dirname(self.settings.face) if self.settings.face else os.path.expanduser("~")
        pattern = "Imagens (" + " ".join("*" + e for e in IMAGE_EXTENSIONS) + ")"
        path, _selected = QFileDialog.getOpenFileName(self, "Escolha uma foto de rosto", start, pattern)
        if path:
            self.choose_face(path)

    def remove_face(self, path: str) -> None:
        was_selected = bool(self.settings.face) and os.path.normcase(self.settings.face) == os.path.normcase(path)
        if was_selected and self.state in LIVE_STATES:
            return   # a foto em uso ao vivo não sai da galeria (a galeria nem oferece o ×)
        self.settings.forget_face(path)
        self.show_gallery()
        if was_selected:
            # Fica sem nada escolhido: a tela volta a pedir um rosto (ou o "sem rosto").
            self.face_ok = False
            self.face_note = ""
        self.settings.save()
        self.refresh()

    def on_camera_changed(self, name: str) -> None:
        self.settings.camera = name or None
        self.settings.save()
        self.sync_camera()
        self.refresh()

    def on_camera_option_changed(self, *_args) -> None:
        self.settings.resolution = self.quality.value()
        self.settings.mirror = self.mirror.is_on()
        self.settings.save()
        self.sync_camera()

    def on_preview_toggled(self, shown: bool) -> None:
        self.settings.preview = shown
        self.settings.save()
        self.sync_camera()
        self.refresh()

    def on_output_changed(self, *_args) -> None:
        """Câmera virtual e proteção valem na hora, ao vivo ou não."""
        self.settings.virtual_camera = self.vcam_row.is_on()
        self.settings.protect = self.protect_row.is_on()
        self.settings.save()
        if self.settings.virtual_camera:
            self.vcam_error = ""   # nova tentativa
        if self.loaded:
            self.engine.send(cmd="set_output", protect=self.settings.protect,
                             virtual_camera=self.settings.virtual_camera and self.vcam_available)
        self.refresh()

    def on_adjustment_changed(self, *_args) -> None:
        s = self.settings
        s.sharpness, s.intensity, s.mouth, s.eyes = (self.sharpness.value(), self.intensity.value(),
                                                     self.mouth.value(), self.eyes.value())
        self.option_timer.start(60)

    def send_adjustments(self) -> None:
        self.settings.save()
        if self.loaded:
            self.engine.send(cmd="set_option", values=self.settings.engine_options())

    def reset_adjustments(self) -> None:
        self.settings.reset_adjustments()
        s = self.settings
        for row, value in ((self.sharpness, s.sharpness), (self.intensity, s.intensity),
                           (self.mouth, s.mouth), (self.eyes, s.eyes)):
            row.set_value(value)
        self.option_timer.start(0)

    def on_display_changed(self, *_args) -> None:
        """O que aparece na tela: quadros por segundo, contagem de rostos, detalhes e o som."""
        s = self.settings
        s.show_fps, s.show_faces = self.fps_row.is_on(), self.faces_row.is_on()
        s.details, s.sound = self.details_row.is_on(), self.sound_row.is_on()
        self.details.setVisible(s.details)
        s.save()
        self.refresh()

    def on_theme_changed(self, name: str) -> None:
        self.settings.theme = name
        self.settings.save()
        self.setStyleSheet(theme.apply(name))
        for widget in self.findChildren(QWidget):
            widget.update()
        self.refresh()

    def on_blur_toggled(self, on: bool) -> None:
        self.blur_now = on
        self.blur_button.setText("Borrado · voltar" if on else "Borrar agora")
        self.view._place_buttons()
        if self.loaded:
            self.engine.send(cmd="set_output", force_blur=on)
        self.refresh()

    def take_photo(self) -> None:
        image = self.view.current_image()
        if image is None or self.state != "running":
            return
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation) or os.path.expanduser("~")
        folder = self.args.photo_dir or os.path.join(base, APP_NAME)
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, time.strftime("foto-%Y%m%d-%H%M%S.png"))
            saved = image.save(path)
        except OSError:
            saved, path = False, folder
        self.say(f"Foto salva em {os.path.normpath(path)}" if saved
                 else f"Não consegui salvar a foto em {os.path.normpath(folder)}",
                 theme.GO if saved else theme.STOP)

    def say(self, text: str, colour: Optional[str] = None) -> None:
        """Recado passageiro sobre o vídeo."""
        self.flash = (text, colour or theme.OVERLAY_MUTED, time.perf_counter() + TOAST_SECONDS)
        self.refresh()

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if any(u.toLocalFile().lower().endswith(IMAGE_EXTENSIONS) for u in urls):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(IMAGE_EXTENSIONS):
                self.choose_face(path)
                break

    # eventos do motor -------------------------------------------------------------
    def on_event(self, evt: dict) -> None:
        kind = evt.get("evt")
        if kind == "status":
            previous = self.state
            self.state, self.detail = evt.get("state", ""), evt.get("detail", "")
            if self.state == "running" and self.running_since is None:
                self.running_since = time.perf_counter()
            if self.state != "running":
                self.vcam_on = False
                self.recording_since = None
                self.view.banner = ""
            if self.state not in LIVE_STATES:
                self.view.clear()   # fora do ao vivo o palco volta a mostrar as instruções
            if self.state == "idle":
                self.camera_info = None
                self.stats = None
                self.camera_view.clear()
            if self.state != previous and self.state in ("preview", "running"):
                self.stats = None   # as medições do modo anterior não valem para este
        elif kind == "loaded":
            self.loaded = True
            self.view.loading = None
            if not self.building:   # a otimização da primeira vez não serve de medida
                self.settings.load_seconds = round(time.perf_counter() - self.opened_at, 1)
            self.building = False
            self.preparing_since = None
            self.reader = FrameReader(evt["shm"])
            self.camera_reader = FrameReader(evt["shm_camera"])
            virtual = evt.get("virtual_camera") or {}
            self.vcam_available = bool(virtual.get("available"))
            self.vcam_device = virtual.get("device")
            self.vcam_backend = virtual.get("backend")
            self.vcam_reason = virtual.get("reason") or ""
            if virtual.get("installed_now"):
                self.say(f"A câmera virtual “{self.vcam_device}” foi instalada neste computador. "
                         "Os outros programas já a enxergam (os que estavam abertos, depois de reabrir).", theme.GO)
            self.vcam_row.switch.setEnabled(self.vcam_available)
            self.engine.send(cmd="set_output", protect=self.settings.protect, force_blur=False,
                             virtual_camera=self.settings.virtual_camera and self.vcam_available)
            self.engine.send(cmd="set_option", values=self.settings.engine_options())
            if self.settings.face:
                self.engine.send(cmd="set_source", paths=[self.settings.face])
            elif self.settings.without_face:
                self.engine.send(cmd="set_source", paths=[])
            self.state = "idle"
            self.sync_camera()
            # O mascote grita que terminou de carregar; o som sai junto com o bico abrindo.
            self.view.celebrate()
            if self.settings.sound and not self.args.offscreen:
                QTimer.singleShot(self.view.scream_delay_ms(), play_honk)
            if self.args.quit_after_load:
                QTimer.singleShot(int(self.args.quit_after_load * 1000), self.close)
        elif kind == "virtual_camera":
            self.vcam_on = bool(evt.get("on"))
            self.vcam_watched = evt.get("watched") if self.vcam_on else None
            if evt.get("device"):
                self.vcam_device = evt["device"]
            if evt.get("error"):
                # Não ligou: o interruptor volta a desligado e a explicação fica embaixo dele.
                self.vcam_error = evt["error"]
                self.settings.virtual_camera = False
                self.vcam_row.set_on(False, silent=True)
                self.engine.send(cmd="set_output", virtual_camera=False)
                self.settings.save()
        elif kind == "source":
            self.on_source(evt)
        elif kind == "ready":
            self.camera_info = self.last_camera = evt.get("camera")
        elif kind == "stats":
            self.on_stats(evt)
        elif kind == "recording":
            self.recording_since = time.perf_counter()
            self.recording_seconds = float(evt.get("seconds") or 0.0)
        elif kind == "recorded":
            self.recording_since = None
            self.recorded = evt
            self.view.banner = ""
            self.say(f"Gravação concluída: {evt['frames']} quadros em {evt['seconds']:.0f} s, salva só neste "
                     f"computador em {evt['path']}", theme.GO)
        elif kind == "error":
            self.error = evt.get("message", "erro no motor")
        self.refresh()

    def on_stats(self, evt: dict) -> None:
        self.stats = evt
        if evt.get("mode") != "live":
            return
        self.history.append(evt)
        if self.display_fps is not None:
            self.display_history.append(self.display_fps)
        swap_ms = (evt.get("stages", {}).get("swap") or {}).get("ms")
        # Só vale como régua um segundo em que a troca rodou de verdade em todos os quadros.
        swapping = (evt.get("swap_fps") or 0) > 0 and not (evt.get("swap_hidden_fps") or 0)
        if swap_ms and swapping and len(self.history) > diag.WARMUP_SECONDS:
            self.best_swap_ms = min(self.best_swap_ms or swap_ms, swap_ms)

    def on_source(self, evt: dict) -> None:
        requested = (evt.get("requested") or [""])[0]
        if not self.settings.face or os.path.normcase(requested) != os.path.normcase(self.settings.face):
            return   # resposta de um pedido antigo: o usuário já escolheu outra foto
        if evt.get("ok"):
            self.face_ok = True
            self.good_face = self.settings.face
            self.face_note = ("Foto em close: o rosto foi achado com uma margem extra em volta."
                              if evt.get("padded") else "")
            return
        # Foto sem rosto detectável: sai da galeria e a seleção volta para a última boa.
        bad = self.settings.face
        self.settings.forget_face(bad)
        if evt.get("kept_previous") and self.good_face and os.path.isfile(self.good_face):
            self.settings.remember_face(self.good_face)
            self.face_ok = True
            self.face_note = (f"Não achei um rosto em “{os.path.basename(bad)}”. Mantive o rosto anterior. "
                              "Use uma foto nítida, de frente, com o rosto inteiro.")
        else:
            self.face_ok = False
            self.face_note = (f"Não achei um rosto em “{os.path.basename(bad)}”. "
                              "Use uma foto nítida, de frente, com o rosto inteiro.")
        self.show_gallery()
        self.settings.save()

    def on_output(self, line: str) -> None:
        if _TRT_BUILD.search(line) and not self.loaded:
            self.preparing_since = time.perf_counter()

    def on_exit(self, code: int) -> None:
        if self.state != "closing":
            self.engine_dead = True
            if not self.error:
                self.error = f"O motor parou sozinho (código {code}). Feche e abra o app de novo."
            self.view.clear()
        self.refresh()

    # quadros ----------------------------------------------------------------------
    def tick(self) -> None:
        now = time.perf_counter()
        if self.reader is not None and self.state == "running":
            got = self.reader.read()
            if got is not None:
                first = not self.view.has_frame()
                self.view.show_frame(got[0])
                self.shown += 1
                if first:
                    self.refresh()   # saem as instruções, entram o selo e os botões
        if self.camera_reader is not None and self.settings.preview and self.state in ("running", "preview"):
            got = self.camera_reader.read()
            if got is not None:
                first = not self.camera_view.has_frame()
                self.camera_view.show_frame(got[0])
                if first:
                    self.refresh()
        if (not self.loaded and not self.building and self.preparing_since is not None
                and now - self.preparing_since > OPTIMIZING_AFTER_SECONDS):
            self.building = True
            self.refresh()
        if not self.loaded and not self.engine_dead and now - self.painted_at >= 1 / 30:
            self.painted_at = now   # a barra de progresso anda sozinha enquanto os modelos carregam
            self.view.loading = (self.load_progress(),)
            self.view.update()
        if self.recording_since is not None and self.recording_seconds > 0:
            elapsed = now - self.recording_since
            step = [text for start, text in RECORD_SCRIPT if elapsed >= start * self.recording_seconds][-1]
            banner = f"● GRAVANDO {min(elapsed, self.recording_seconds):.0f}/{self.recording_seconds:.0f} s — {step}"
            if banner != self.view.banner:
                self.view.banner = banner
                self.view.update()
        if self.flash and now >= self.flash[2]:
            self.flash = None
            self.refresh()
        if now - self.shown_since >= 1.0:
            self.display_fps = self.shown / (now - self.shown_since)
            self.shown, self.shown_since = 0, now
        args = self.args
        if args.autostart and not self.autostarted and self.can_start():
            self.autostarted = True
            self.start()
            self.refresh()
        for item in list(self.pending_clicks):   # cliques de teste: "segundos:botão"
            after, _, which = item.partition(":")
            if self.state == "running" and self.running_since and now - self.running_since >= float(after):
                self.pending_clicks.remove(item)
                {"foto": self.photo_button, "borrar": self.blur_button}[which].click()
        if (args.stop_after and not self.stop_clicked and self.state == "running" and self.running_since
                and now - self.running_since >= args.stop_after):
            self.stop_clicked = True
            self.toggle()   # o mesmo caminho do clique em Parar
        if args.run_seconds and self.running_since and now - self.running_since >= args.run_seconds:
            self.close()
        elif args.give_up_seconds and self.running_since is None and now - self.opened_at >= args.give_up_seconds:
            self.error = self.error or f"O motor não começou a rodar em {args.give_up_seconds:.0f} s."
            self.close()
        elif (args.run_seconds or args.give_up_seconds) and self.engine_dead:
            self.close()   # em modo de teste, não fica aberto depois de o motor cair

    # textos -----------------------------------------------------------------------
    def face_missing(self) -> bool:
        s = self.stats or {}
        return (s.get("processed_fps") or 0) > 0 and s.get("frames_without_face", 0) > s["processed_fps"] * 0.5

    def passing_through(self) -> bool:
        """Ao vivo sem troca: a pessoa escolheu "sem rosto" e a câmera está saindo como é."""
        s = self.stats or {}
        return self.settings.without_face and ((s.get("passthrough_fps") or 0) > 0 or not self.face_ok)

    def load_progress(self) -> Optional[float]:
        """Fração da abertura já cumprida, estimada pelo tempo que ela levou da última vez.

        Anda depressa no começo e desacelera perto do fim; se a abertura demorar
        mais que o esperado, continua avançando devagar em vez de parar em 100%.
        """
        if self.building:
            return None
        elapsed = time.perf_counter() - self.opened_at
        expected = max(4.0, self.load_expected)
        if elapsed <= expected:
            return 0.92 * (1 - (1 - elapsed / expected) ** 2)
        return min(0.99, 0.92 + 0.07 * (1 - math.exp(-(elapsed - expected) / expected)))

    def status_text(self) -> str:
        if self.engine_dead:
            return "O motor parou."
        if not self.loaded:
            return "Preparando…"
        if self.state == "stopping":
            return "Parando…"
        if self.state == "running":
            s = self.stats
            if not s or s.get("mode") != "live":
                return "Ao vivo."
            if self.blur_now:
                return "Ao vivo · imagem borrada por você."
            if self.passing_through():
                return "Ao vivo · sem troca: a câmera aparece como é."
            if self.face_missing():
                return "Ao vivo · rosto não encontrado" + (", imagem borrada." if (s.get("protected_fps") or 0) > 0 else ".")
            return f"Ao vivo · {s['swap_fps']:.0f} quadros por segundo." if self.settings.show_fps else "Ao vivo."
        without = self.settings.without_face
        if not self.settings.face and not without:
            return "Escolha uma foto de rosto para começar."
        if not self.face_ok and not without:
            return "Analisando a foto…" if self.face_note.startswith("Analisando") else "Escolha outra foto de rosto."
        if not self.has_camera():
            return "Escolha a câmera." if self.cameras.count() else "Nenhuma câmera encontrada."
        if self.state == "opening_camera":
            return "Abrindo a câmera…"
        return "Pronto para iniciar sem troca de rosto." if without else "Tudo pronto."

    def vcam_usable(self) -> bool:
        return self.settings.virtual_camera and self.vcam_available

    def vcam_text(self) -> str:
        if self.vcam_error:
            return self.vcam_error
        if not self.loaded:
            return ""
        if not self.vcam_available:
            return self.vcam_reason
        name = self.vcam_device or "Morpho Camera"
        if not self.settings.virtual_camera:
            return "Faz a troca aparecer como uma webcam no Meet, Zoom, Discord e OBS."
        if self.vcam_on and self.vcam_watched:
            return f"Em uso agora: outro programa está recebendo a imagem pela câmera “{name}”."
        if self.vcam_on:
            return f"Ligada. No outro programa, escolha a câmera “{name}”."
        if self.vcam_backend == "morpho":
            return (f"No outro programa, escolha a câmera “{name}”. "
                    "Ela mostra “Câmera em pausa” até você iniciar a troca.")
        return f"Ao iniciar, escolha a câmera “{name}” no outro programa."

    def guide(self) -> List[tuple]:
        """O passo a passo do palco, com o que já está feito."""
        name = self.vcam_device or "Morpho Camera"
        without = self.settings.without_face
        face_done = (bool(self.settings.face) and self.face_ok) or without
        if self.face_note.startswith("Analisando"):
            face_text = "Analisando a foto…"
        elif without:
            face_text = "Sem rosto escolhido: a câmera aparece como é. Para trocar, clique numa foto da galeria."
        elif face_done:
            face_text = "Para trocar, clique em outra foto da galeria. Vale na hora, mesmo com a troca ligada."
        else:
            face_text = "Clique no + da galeria, ou arraste uma foto para esta janela."
        if not self.has_camera():
            camera_done = False
            camera_text = ("Escolha a câmera na lista ao lado." if self.cameras.count()
                           else "Nenhuma câmera encontrada. Conecte uma e clique em Atualizar.")
        elif not self.settings.preview:
            camera_done, camera_text = True, "A prévia está desligada: a câmera só liga quando a troca começar."
        elif self.camera_view.has_frame():
            camera_done, camera_text = True, "A prévia ao lado mostra o que a câmera está vendo. Só você vê essa imagem."
        else:
            camera_done, camera_text = False, "Abrindo a câmera… A prévia aparece ao lado, embaixo do nome dela."
        steps = [
            [face_done, "Escolha um rosto", face_text],
            [camera_done, "Confira a câmera", camera_text],
            [False, "Clique em “Iniciar sem troca”" if without else "Clique em “Troque o meu rosto”",
             "O resultado aparece aqui, no lugar destas instruções."],
        ]
        if self.vcam_usable():
            steps.append([False, f"No Meet, Zoom ou Discord, escolha a câmera “{name}”",
                          "Pode fazer isso antes: enquanto a troca não começa, o outro programa "
                          "mostra só “Câmera em pausa”."])
        result, current_found = [], False
        for done, title, text in steps:
            state = "done" if done else ("todo" if current_found else "now")
            current_found = current_found or not done
            result.append((state, title, text))
        return result

    def paint_stage(self) -> None:
        """O que o palco mostra conforme o momento: carregamento, instruções ou o vídeo com selo e avisos."""
        view, s = self.view, self.stats or {}
        live = self.state == "running"
        view.badge = None
        view.steps = []
        view.loading = None
        if live and view.has_frame() and s.get("mode") == "live":
            if self.blur_now:
                view.badge = ("BORRADO", theme.OVERLAY_WARN, "por você")
            elif self.passing_through():
                view.badge = ("AO VIVO", theme.STOP, "sem troca")
            elif self.face_missing() and (s.get("protected_fps") or 0) > 0:
                view.badge = ("PROTEGIDO", theme.OVERLAY_WARN, "rosto não encontrado")
            else:
                extras = []
                if self.settings.show_fps:
                    extras.append(f"{s.get('swap_fps', 0):.0f} fps")
                seen = (s.get("faces_in_frame") or {}).get("max") or 0
                if self.settings.show_faces and seen:
                    extras.append("1 rosto" if seen == 1 else f"{seen:.0f} rostos")
                view.badge = ("AO VIVO", theme.STOP, " · ".join(extras))
        elif live and view.has_frame():
            view.badge = ("AO VIVO", theme.STOP, "")

        if self.engine_dead:
            view.empty_title, view.empty_text = "O motor parou", self.error
            view.mood = "dormindo"
        elif not self.loaded:
            view.loading = (self.load_progress(),)
            view.empty_title = f"Preparando o {APP_NAME}"
            if self.building:
                view.empty_text = ("Otimizando os modelos para a sua placa de vídeo. "
                                   "Só na primeira vez; leva alguns minutos.")
            else:
                view.empty_text = self.detail or "Carregando os modelos de troca de rosto."
        elif view.celebrating:
            view.empty_title, view.empty_text = "Tudo pronto!", ""
        elif self.state in LIVE_STATES:
            view.empty_title, view.empty_text = "Iniciando…", "O resultado aparece aqui em instantes."
            view.mood = "matrix"
        else:
            view.empty_title = "O resultado aparece aqui"
            view.empty_text = ("É esta a imagem que os outros programas recebem pela câmera virtual."
                               if self.vcam_usable() else
                               "Com a câmera virtual desligada, a imagem aparece só nesta janela.")
            view.steps = self.guide()
            # Pílulas enquanto falta escolher o rosto (a vermelha ou a azul?); depois, parado.
            view.mood = "parado" if (self.face_ok or self.settings.without_face) else "pilulas"

        toasts = []
        if self.error and not self.engine_dead:
            toasts.append((self.error, theme.STOP))
        if live:
            toasts += [(text, theme.OVERLAY_WARN)
                       for text in diag.warnings(self.stats, self.best_swap_ms, self.settings.show_faces)[:2]]
        elif self.state == "preview" and 0 < (s.get("capture_fps") or 0) < diag.LOW_CAMERA_FPS:
            toasts.append((f"Esta câmera entrega só {s['capture_fps']:.0f} quadros por segundo. "
                           "Mais luz ou a qualidade Leve costumam ajudar.", theme.OVERLAY_WARN))
        if self.flash:
            toasts.append((self.flash[0], self.flash[1]))
        view.toasts = toasts
        for button in (self.photo_button, self.blur_button):
            button.setVisible(live and view.has_frame())
        view._place_buttons()
        view.update()

    def paint_camera(self) -> None:
        """O recado da prévia pequena quando não há imagem nela."""
        view = self.camera_view
        # A prévia e a qualidade só ocupam lugar na tela inicial quando há uma câmera escolhida.
        chosen = self.has_camera()
        view.setVisible(chosen and self.settings.preview)
        self.quality.setVisible(chosen)
        if not self.loaded or self.isMinimized():
            text = ""
        else:
            text = "Abrindo a câmera…"
        if not self.settings.preview:
            view.clear()
        view.set_placeholder(text)

    def refresh(self) -> None:
        live = self.state in LIVE_STATES
        virtual = self.vcam_usable()
        if live:
            self.button.set_text("Parar", "e pausar a câmera virtual" if virtual else "", stop=True)
        elif self.settings.without_face:
            self.button.set_text("Iniciar sem troca", "preparando…" if not self.loaded else
                                 ("a câmera virtual mostra você como é" if virtual else "só nesta janela, sem câmera virtual"),
                                 stop=False)
        else:
            self.button.set_text("Troque o meu rosto", "preparando…" if not self.loaded else
                                 ("e inicie a câmera virtual" if virtual else "só nesta janela, sem câmera virtual"),
                                 stop=False)
        self.button.setEnabled(self.state == "running" or self.can_start())
        for widget in (self.cameras, self.quality, self.mirror.switch, self.preview_row.switch):
            widget.setEnabled(not live)   # mudam a câmera: só fora do ao vivo
        self.gallery.set_locked(self.settings.face if live else None)
        self.status.setText(self.status_text())
        face_note = self.face_note or ("" if self.settings.faces else "Clique no + ou arraste uma foto para a janela.")
        self.face_label.setText(face_note)
        self.face_label.setVisible(bool(face_note))
        self.vcam_row.set_hint(self.vcam_text(), error=bool(self.vcam_error))
        self.paint_camera()
        self.paint_stage()
        if self.settings.details:
            lines = [f"Estado do motor: {self.state}" + (f" — {self.detail}" if self.detail else "")]
            live_stats = self.stats if (self.state == "running" and (self.stats or {}).get("mode") == "live") else None
            lines += diag.technical_lines(live_stats, self.camera_info, self.display_fps)
            if live_stats:
                lines.append(
                    f"Saída: câmera virtual {'ligada como ' + str(self.vcam_device) if self.vcam_on else 'desligada'} · "
                    f"proteção {'ligada' if self.settings.protect else 'desligada'} · "
                    f"quadros protegidos {diag.fmt(live_stats.get('protected_fps'), 1)}/s"
                )
            elif self.state == "preview" and self.stats:
                lines.append(f"Prévia: câmera entrega {diag.fmt(self.stats.get('capture_fps'), 1)} fps")
            lines.append(f"Log do motor: {self.engine.log_path}")
            self.details.setText("\n".join(lines))

    # medições e encerramento ----------------------------------------------------------
    def write_report(self, closing: bool = False) -> None:
        """Grava as medições (resumo + segundo a segundo) para análise posterior.

        Roda a cada poucos segundos e ao fechar: assim o arquivo existe mesmo com
        a janela ainda aberta, ou se ela for fechada à força.
        """
        if not self.history:
            return
        report = dict(camera=self.last_camera, error=self.error,
                      still_running=not closing, saved_at=time.strftime("%H:%M:%S"),
                      warnings_at_close=diag.warnings(self.history[-1], self.best_swap_ms),
                      engine_log=self.engine.log_path,
                      summary=diag.summarize(self.history, self.display_history),
                      per_second=self.history[-900:])
        for path in filter(None, [self.args.report, os.path.join(paths.data_dir(), "last-run.json")]):
            try:
                temporary = path + ".tmp"
                with open(temporary, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=1)
                os.replace(temporary, path)   # quem lê nunca pega o arquivo pela metade
            except OSError:
                pass

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.save_timer.stop()
        if self.args.screenshot:
            self.grab().save(self.args.screenshot)
        self.write_report(closing=True)
        if self.best_swap_ms and self.best_swap_ms != self.baseline.get(self.args.model):
            self.baseline[self.args.model] = self.best_swap_ms
            try:
                with open(self.baseline_path, "w", encoding="utf-8") as f:
                    json.dump(self.baseline, f, indent=1)
            except OSError:
                pass
        if not self.isMinimized() and not self.isMaximized() and not self.args.offscreen:
            g = self.geometry()
            self.settings.window = [g.x(), g.y(), g.width(), g.height()]
        self.settings.save()
        self.state = "closing"
        self.engine.stop()
        for reader in (self.reader, self.camera_reader):
            if reader is not None:
                reader.close()
        event.accept()
