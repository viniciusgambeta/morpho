"""Gera as animações do mascote que o app usa, a partir de ``mascote/ganso.js``.

    <python> packaging/make_mascot.py [--size 240] [--fps 24]

O mascote é desenhado por código JavaScript num canvas (ver ``mascote/index.html``). O app é
feito em Qt e não leva um navegador junto, então cada animação vira uma imagem só, com todos
os quadros de um ciclo lado a lado e fundo transparente (``app/ui/assets/mascote/<nome>.png``),
mais um índice (``mascote.json``) com o tamanho do quadro, quantos são e o ritmo.

Quem desenha é o Chrome instalado, sem janela e com um perfil temporário, abrindo
``packaging/mascot/export.html`` de um servidor local; nada sai do computador.

Só entram as animações que o Vinicius liberou para o app: Parado, Dormindo e Gritando em
preto e branco; Matrix e Pílulas com cor. Todas na versão de fundo claro: no app elas
aparecem sempre dentro de um bloco branco de cantos arredondados.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
SOURCE = os.path.join(PROJECT, "mascote", "ganso.js")
PAGE = os.path.join(HERE, "mascot", "export.html")
OUT = os.path.join(PROJECT, "app", "ui", "assets", "mascote")
ANIMATIONS = [("parado", True), ("dormindo", True), ("gritando", True), ("matrix", False), ("pilulas", False)]
BROWSERS = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--size", type=int, default=240, help="lado de cada quadro, em pixels")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--columns", type=int, default=12)
    args = parser.parse_args()
    browser = next((path for path in BROWSERS if os.path.isfile(path)), None)
    if browser is None:
        raise SystemExit("Preciso do Chrome ou do Edge instalado para desenhar as animações.")
    os.makedirs(OUT, exist_ok=True)
    finished = threading.Event()
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # noqa: N802
            pass

        def do_GET(self):  # noqa: N802
            path = urlparse(self.path).path
            source = {"/export.html": PAGE, "/ganso.js": SOURCE}.get(path)
            if source is None:
                self.send_error(404)
                return
            with open(source, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8" if path.endswith(".html") else "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if url.path == "/save":
                name = parse_qs(url.query)["name"][0]
                if name not in dict(ANIMATIONS):
                    self.send_error(400)
                    return
                with open(os.path.join(OUT, name + ".png"), "wb") as f:
                    f.write(body)
                print(f"  {name}.png  {len(body) / 1024:.0f} KB", flush=True)
            elif url.path == "/done":
                result.update(json.loads(body))
                finished.set()
            elif url.path == "/fail":
                result["error"] = body.decode("utf-8", "replace")
                finished.set()
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    profile = tempfile.mkdtemp(prefix="morpho-mascote-")
    url = (f"http://127.0.0.1:{server.server_address[1]}/export.html?size={args.size}&fps={args.fps}"
           f"&columns={args.columns}&anims={quote(json.dumps(ANIMATIONS))}")
    process = subprocess.Popen([browser, "--headless=new", f"--user-data-dir={profile}", "--no-first-run",
                                "--no-default-browser-check", "--disable-background-networking",
                                "--disable-component-update", "--disable-sync", url],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ok = finished.wait(120)
    finally:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        shutil.rmtree(profile, ignore_errors=True)
        server.shutdown()
    if not ok or result.get("error"):
        raise SystemExit("Não consegui desenhar as animações: " + (result.get("error") or "o navegador não respondeu."))
    with open(os.path.join(OUT, "mascote.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"pronto: {len(result['animations'])} animações em {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
