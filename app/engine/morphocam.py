"""A câmera virtual do próprio app: "Morpho Camera".

Duas metades:

- O **filtro** (``MorphoCamera64.dll`` / ``MorphoCamera32.dll``, código em
  ``vendor/morphocam``) é o que o Meet, o Zoom, o Discord e o OBS carregam
  quando a pessoa escolhe a câmera "Morpho Camera". Para eles a enxergarem,
  o filtro precisa estar registrado no Windows. Aqui o registro é feito para
  o usuário atual (``HKEY_CURRENT_USER``), o que não pede permissão de
  administrador.
- O **envio** dos quadros: o filtro e o app conversam por memória
  compartilhada. Quem cria a memória é o filtro; por isso só há para onde
  enviar enquanto algum programa está com a câmera aberta.

O filtro mostra uma tela escura de "Câmera em pausa" sempre que o app não
está enviando — nunca a imagem crua de ninguém.
"""
from __future__ import annotations

import ctypes
import os
import struct
import time
from ctypes import wintypes
from typing import Optional, Tuple

import cv2
import numpy as np

from app import paths

DEVICE_NAME = "Morpho Camera"
# Um identificador por arquitetura, como no filtro: os dois convivem.
CLSID = {64: "{6D5F5A88-69F6-47B0-B24B-22115FF96210}", 32: "{6D5F5A88-69F6-47B0-B24B-22115FF96220}"}
VIDEO_INPUT_CATEGORY = "{860BB310-5D01-11D0-BD3B-00A0C911CE86}"
# O que o Windows grava ao registrar um filtro de captura com um pino de saída
# de vídeo (o mesmo conteúdo das outras câmeras virtuais deste computador).
FILTER_DATA = bytes.fromhex(
    "02000000000020000100000000000000307069330800000000000000010000000000000000000000"
    "307479330000000038000000480000007669647300001000800000aa00389b71"
    "00000000000000000000000000000000")

MAX_WIDTH, MAX_HEIGHT = 1920, 1080          # o maior quadro que cabe na memória compartilhada
HEADER = struct.Struct("<I9i")              # maxSize, width, height, stride, format, resize, mirror, timeout, wantW, wantH
FRAME_FIELDS = struct.Struct("<7i")         # a parte que o app escreve: de width a timeout (a partir do byte 4)
STALE_AFTER_MS = 1000                       # sem quadro novo por este tempo, o filtro mostra a tela de pausa
RETRY_SECONDS = 0.25                        # intervalo entre tentativas de achar um programa com a câmera aberta


# ── registro ─────────────────────────────────────────────────────────────────────────────
def dll_path(bits: int) -> str:
    return os.path.join(paths.camera_root(), f"MorphoCamera{bits}.dll")


def _registered_dll(bits: int) -> Optional[str]:
    """O arquivo que o Windows carregaria para a câmera nesta arquitetura, se houver registro."""
    import winreg

    view = winreg.KEY_WOW64_64KEY if bits == 64 else winreg.KEY_WOW64_32KEY
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{CLSID[bits]}\InprocServer32", 0,
                            winreg.KEY_READ | view) as key:
            path = str(winreg.QueryValue(key, None))
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            rf"CLSID\{VIDEO_INPUT_CATEGORY}\Instance\{CLSID[bits]}", 0, winreg.KEY_READ | view):
            pass
    except OSError:
        return None
    return path


def is_registered(bits: int = 64) -> bool:
    current = _registered_dll(bits)
    return bool(current) and os.path.isfile(current)


def _register(bits: int, dll: str) -> None:
    import winreg

    view = winreg.KEY_WOW64_64KEY if bits == 64 else winreg.KEY_WOW64_32KEY
    access = winreg.KEY_WRITE | view
    root, classes, clsid = winreg.HKEY_CURRENT_USER, r"Software\Classes\CLSID", CLSID[bits]
    with winreg.CreateKeyEx(root, rf"{classes}\{clsid}", 0, access) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, DEVICE_NAME)
    with winreg.CreateKeyEx(root, rf"{classes}\{clsid}\InprocServer32", 0, access) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, dll)
        winreg.SetValueEx(key, "ThreadingModel", 0, winreg.REG_SZ, "Both")
    with winreg.CreateKeyEx(root, rf"{classes}\{VIDEO_INPUT_CATEGORY}\Instance\{clsid}", 0, access) as key:
        winreg.SetValueEx(key, "FriendlyName", 0, winreg.REG_SZ, DEVICE_NAME)
        winreg.SetValueEx(key, "CLSID", 0, winreg.REG_SZ, clsid)
        winreg.SetValueEx(key, "FilterData", 0, winreg.REG_BINARY, FILTER_DATA)
        winreg.SetValueEx(key, "DevicePath", 0, winreg.REG_SZ, "morpho:camera")


def ensure_registered() -> dict:
    """Deixa a câmera registrada para o usuário atual. Devolve ``ok`` e, se não, o motivo.

    Já registrada apontando para um arquivo que existe (por nós ou por um
    instalador, para a máquina toda), nada é alterado.
    """
    if not os.path.isfile(dll_path(64)):
        return dict(ok=False, reason="O arquivo da câmera virtual não foi encontrado.", changed=False)
    changed = False
    try:
        for bits in (64, 32):
            dll = dll_path(bits)
            if not os.path.isfile(dll):
                continue   # sem a versão de 32 bits, só os programas de 64 enxergam a câmera
            current = _registered_dll(bits)
            if current and os.path.isfile(current) and os.path.normcase(current) == os.path.normcase(dll):
                continue
            if current and os.path.isfile(current) and not _is_user_registration(bits):
                continue   # registro da máquina toda, feito por um instalador: fica como está
            _register(bits, dll)
            changed = True
    except OSError as error:
        return dict(ok=False, reason=f"Não consegui registrar a câmera virtual: {error}", changed=changed)
    return dict(ok=is_registered(64), reason="", changed=changed)


def _is_user_registration(bits: int) -> bool:
    import winreg

    view = winreg.KEY_WOW64_64KEY if bits == 64 else winreg.KEY_WOW64_32KEY
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\CLSID\{CLSID[bits]}", 0,
                            winreg.KEY_READ | view):
            return True
    except OSError:
        return False


def unregister() -> None:
    """Remove o registro feito para o usuário atual (a câmera some dos outros programas)."""
    import winreg

    for bits in (64, 32):
        view = winreg.KEY_WOW64_64KEY if bits == 64 else winreg.KEY_WOW64_32KEY
        for sub in (rf"Software\Classes\CLSID\{VIDEO_INPUT_CATEGORY}\Instance\{CLSID[bits]}",
                    rf"Software\Classes\CLSID\{CLSID[bits]}\InprocServer32",
                    rf"Software\Classes\CLSID\{CLSID[bits]}"):
            try:
                winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, sub, view, 0)
            except OSError:
                pass


# ── envio ────────────────────────────────────────────────────────────────────────────────
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenMutexW.restype = _k32.CreateEventW.restype = _k32.OpenEventW.restype = wintypes.HANDLE
_k32.OpenFileMappingW.restype = wintypes.HANDLE
_k32.OpenMutexW.argtypes = _k32.OpenEventW.argtypes = _k32.OpenFileMappingW.argtypes = (
    wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
_k32.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t)
_k32.UnmapViewOfFile.argtypes = (ctypes.c_void_p,)
_k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.ReleaseMutex.argtypes = _k32.SetEvent.argtypes = _k32.CloseHandle.argtypes = (wintypes.HANDLE,)

SYNCHRONIZE, EVENT_MODIFY_STATE, FILE_MAP_WRITE, WAIT_OBJECT_0 = 0x00100000, 0x0002, 0x0002, 0


def fit(size: Tuple[int, int], box: Tuple[int, int]) -> Tuple[int, int]:
    """O maior tamanho com a proporção de ``size`` que cabe em ``box`` (lados pares)."""
    (w, h), (bw, bh) = size, box
    scale = min(bw / w, bh / h)
    return max(2, int(round(w * scale)) & ~1), max(2, int(round(h * scale)) & ~1)


class Sender:
    """Entrega quadros ao filtro. Sem nenhum programa com a câmera aberta, ``send`` não faz nada."""

    def __init__(self) -> None:
        self._mutex = self._want = self._sent = self._mapping = None
        self._view: Optional[int] = None
        self._pixels: Optional[np.ndarray] = None
        self._header = None
        self._next_try = 0.0
        self._asked_at = 0.0        # última vez que o filtro pediu um quadro
        self._flipped: Optional[np.ndarray] = None

    @property
    def device(self) -> str:
        return DEVICE_NAME

    @property
    def watched(self) -> bool:
        """Algum programa está puxando imagem da câmera agora?"""
        return time.perf_counter() - self._asked_at < 1.5

    def _open(self) -> bool:
        if self._view:
            return True
        now = time.perf_counter()
        if now < self._next_try:
            return False
        self._next_try = now + RETRY_SECONDS
        # O filtro cria o mutex, o evento "enviado" e a memória; o app cria o evento "quero".
        if not self._mutex:
            self._mutex = _k32.OpenMutexW(SYNCHRONIZE, False, "MorphoCamera_Mutx")
            if not self._mutex:
                return False
        if not self._want:
            self._want = _k32.CreateEventW(None, False, False, "MorphoCamera_Want")
        if not self._sent:
            self._sent = _k32.OpenEventW(EVENT_MODIFY_STATE, False, "MorphoCamera_Sent")
        if not self._mapping:
            self._mapping = _k32.OpenFileMappingW(FILE_MAP_WRITE, False, "MorphoCamera_Data")
        if not (self._want and self._sent and self._mapping):
            return False
        view = _k32.MapViewOfFile(self._mapping, FILE_MAP_WRITE, 0, 0, 0)
        if not view:
            return False
        self._view = view
        self._header = (ctypes.c_ubyte * HEADER.size).from_address(view)
        capacity = MAX_WIDTH * MAX_HEIGHT * 4
        self._pixels = np.frombuffer((ctypes.c_ubyte * capacity).from_address(view + HEADER.size), dtype=np.uint8)
        return True

    def send(self, frame: np.ndarray) -> bool:
        """Envia um quadro BGR. Devolve se havia para onde enviar."""
        if not self._open():
            return False
        fields = HEADER.unpack_from(self._header)
        capacity, want = fields[0], (fields[8], fields[9])
        height, width = frame.shape[:2]
        # O filtro já entrega no tamanho que o outro programa pediu; reduzir aqui,
        # com filtro de área, fica bem mais limpo que a redução simples de lá.
        box = want if (want[0] > 0 and want[1] > 0) else (MAX_WIDTH, MAX_HEIGHT)
        box = (min(box[0], MAX_WIDTH), min(box[1], MAX_HEIGHT))
        target = fit((width, height), box) if (width > box[0] or height > box[1]) else (width, height)
        if target != (width, height):
            frame = cv2.resize(frame, target, interpolation=cv2.INTER_AREA)
            width, height = target
        if width * height * 4 > capacity:
            return False
        if self._flipped is None or self._flipped.shape != frame.shape:
            self._flipped = np.empty_like(frame)
        cv2.flip(frame, 0, dst=self._flipped)   # o DirectShow quer a imagem de baixo para cima
        if _k32.WaitForSingleObject(self._mutex, 100) != WAIT_OBJECT_0:
            return False
        try:
            # formato 0 = RGBA de 8 bits; redimensionar 1 = o filtro ajusta se ainda precisar; sem espelho
            FRAME_FIELDS.pack_into(self._header, 4, width, height, width, 0, 1, 0, STALE_AFTER_MS)
            cv2.cvtColor(self._flipped, cv2.COLOR_BGR2RGBA, dst=self._pixels[: width * height * 4].reshape(height, width, 4))
        finally:
            _k32.ReleaseMutex(self._mutex)
        _k32.SetEvent(self._sent)
        if _k32.WaitForSingleObject(self._want, 0) == WAIT_OBJECT_0:
            self._asked_at = time.perf_counter()
        return True

    def close(self) -> None:
        """Para de enviar: quem estiver com a câmera aberta passa a ver a tela de pausa."""
        if self._view:
            if _k32.WaitForSingleObject(self._mutex, 200) == WAIT_OBJECT_0:
                try:
                    # largura zero = "o app não está enviando"
                    FRAME_FIELDS.pack_into(self._header, 4, 0, 0, 0, 0, 1, 0, STALE_AFTER_MS)
                finally:
                    _k32.ReleaseMutex(self._mutex)
            self._pixels = self._header = None
            _k32.UnmapViewOfFile(self._view)
            self._view = None
        for name in ("_mapping", "_sent", "_want", "_mutex"):
            handle = getattr(self, name)
            if handle:
                _k32.CloseHandle(handle)
            setattr(self, name, None)
        self._asked_at = 0.0
