"""Publica o instalador no GitHub (Releases) e gera a lista de arquivos da página.

    <python do motor> packaging/publish_release.py [--tag v1.0.0] [--only-manifest]

Envia o MorphoSetup.exe e os arquivos .bin para a versão indicada, um por vez, e tenta de
novo se a internet cair: o envio para o GitHub não continua de onde parou, por isso o
instalador é dividido em pedaços pequenos (ver DiskSliceSize em installer/morpho.iss) e uma
queda só perde o pedaço que estava a caminho. O que já está lá com a impressão digital
certa não é reenviado, então dá para interromper e rodar de novo.

No fim grava ``download.json`` (nome, endereço, tamanho e SHA-256 de cada arquivo), que é
o que a página e o diagnóstico leem. Copiar para ``site/download.json`` e publicar a página
só depois de a versão estar publicada no GitHub.

Precisa da ferramenta ``gh`` com login feito.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

REPO = "viniciusgambeta/morpho"
DEFAULT_FOLDER = r"C:\Users\vinic\dlc-lab\dist\instalador"
DEFAULT_GH = r"C:\Users\vinic\dlc-lab\tools\gh\bin\gh.exe"
ATTEMPTS = 8


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def order(name: str):
    """O instalador primeiro, depois os pedaços na ordem dos números."""
    number = re.search(r"-(\d+)\.bin$", name)
    return (1, int(number.group(1))) if number else (0, 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--folder", default=DEFAULT_FOLDER)
    parser.add_argument("--tag", default="v1.0.0")
    parser.add_argument("--gh", default=DEFAULT_GH)
    parser.add_argument("--manifest", default=r"C:\Users\vinic\dlc-lab\dist\download.pronto.json")
    parser.add_argument("--only-manifest", action="store_true", help="só gera a lista, sem enviar nada")
    args = parser.parse_args()

    names = sorted((n for n in os.listdir(args.folder) if n.startswith("MorphoSetup")), key=order)
    if not names:
        raise SystemExit(f"Não há instalador em {args.folder}.")
    print(f"{len(names)} arquivos; calculando as impressões digitais…", flush=True)
    files = []
    for name in names:
        path = os.path.join(args.folder, name)
        files.append(dict(name=name, size=os.path.getsize(path), sha256=sha256(path),
                          url=f"https://github.com/{REPO}/releases/download/{args.tag}/{name}"))
    version = args.tag.lstrip("v")
    with open(args.manifest, "w", encoding="utf-8") as f:
        json.dump(dict(version=version, source=f"https://github.com/{REPO}",
                       files=[dict(name=x["name"], url=x["url"], size=x["size"], sha256=x["sha256"]) for x in files]),
                  f, indent=2)
    total = sum(x["size"] for x in files)
    print(f"lista gravada em {args.manifest} ({total / 2**30:.2f} GB)", flush=True)
    if args.only_manifest:
        return 0

    def published() -> dict:
        """O que já está no GitHub: nome -> impressão digital (só os envios concluídos)."""
        out = subprocess.run([args.gh, "release", "view", args.tag, "--repo", REPO, "--json", "assets"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        if out.returncode != 0:
            return {}
        try:
            assets = json.loads(out.stdout)["assets"]
        except (ValueError, KeyError):
            return {}
        return {a["name"]: (a.get("digest") or "").replace("sha256:", "") for a in assets if a.get("state") == "uploaded"}

    started, sent = time.time(), 0
    for index, item in enumerate(files, 1):
        for attempt in range(1, ATTEMPTS + 1):
            if published().get(item["name"]) == item["sha256"]:
                break
            stamp = time.strftime("%H:%M:%S")
            print(f"{stamp} [{index}/{len(files)}] {item['name']} ({item['size'] / 2**20:.0f} MB), tentativa {attempt}", flush=True)
            begun = time.time()
            done = subprocess.run([args.gh, "release", "upload", args.tag, os.path.join(args.folder, item["name"]),
                                   "--repo", REPO, "--clobber"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if done.returncode == 0:
                sent += item["size"]
                rate = item["size"] / max(1.0, time.time() - begun) / 2**20
                left = sum(x["size"] for x in files[index:]) / 2**20 / max(0.01, rate) / 60
                print(f"         ok, {rate:.2f} MB/s; faltam cerca de {left:.0f} min", flush=True)
            else:
                print("         falhou: " + (done.stderr or done.stdout).strip().splitlines()[-1][:160], flush=True)
                time.sleep(30)
        else:
            print(f"DESISTI de {item['name']} depois de {ATTEMPTS} tentativas.", flush=True)
            return 1
    there = published()
    missing = [x["name"] for x in files if there.get(x["name"]) != x["sha256"]]
    print(f"\nfim em {(time.time() - started) / 60:.0f} min; conferidos no GitHub: {len(files) - len(missing)} de {len(files)}", flush=True)
    if missing:
        print("faltam: " + ", ".join(missing))
        return 1
    print("TUDO NO GITHUB com as impressões digitais certas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
