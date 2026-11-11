"""Inicia o processo do motor e traduz a saída dele em sinais do Qt."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Signal

from app import paths
from app.engine import events
from app.engine.config import EngineConfig


class EngineProcess(QObject):
    event = Signal(dict)       # evento do motor (status, loaded, source, ready, stats, error, ...)
    output = Signal(str)       # linha comum da saída do motor (vai também para o log)
    exited = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._proc: Optional[subprocess.Popen] = None
        self.log_path = ""

    def start(self, cfg: EngineConfig) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        config_path = os.path.join(paths.data_dir(), "engine-config.json")
        cfg.save(config_path)
        self.log_path = os.path.join(paths.logs_dir(), f"engine-{stamp}.log")
        env = dict(os.environ)
        env["PYTHONPATH"] = paths.PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUNBUFFERED"] = "1"     # as mensagens do motor chegam na hora, não em blocos
        env["PYTHONIOENCODING"] = "utf-8"
        self._proc = subprocess.Popen(
            [paths.engine_python(cfg.engine_root), "-m", "app.engine", "--config", config_path],
            cwd=paths.PROJECT_ROOT, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._read, name="engine-output", daemon=True).start()

    def _read(self) -> None:
        try:
            self._pump()
        except RuntimeError:
            pass   # a janela foi fechada no meio de um aviso: não há mais quem ouvir

    def _pump(self) -> None:
        proc = self._proc
        with open(self.log_path, "w", encoding="utf-8") as log:
            for line in proc.stdout:
                line = line.rstrip("\r\n")
                evt = events.parse(line)
                if evt is not None:
                    if evt.get("evt") != "stats":
                        log.write(line + "\n")
                        log.flush()
                    self.event.emit(evt)
                elif line.strip():
                    log.write(line + "\n")
                    log.flush()
                    self.output.emit(line)
        self.exited.emit(proc.wait())

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def send(self, **command) -> bool:
        """Manda um comando ao motor; ``False`` se ele já não está lá."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        try:
            proc.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def stop(self, timeout: float = 5.0) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        self.send(cmd="quit")
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
