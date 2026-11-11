"""Gera o instalador do Morpho (MorphoSetup.exe) a partir do pacote montado por build.py.

    <python do motor> packaging/make_installer.py [--source PASTA] [--out PASTA]

Precisa do Inno Setup 6 (o compilador ISCC.exe). O resultado são o
``MorphoSetup.exe`` e arquivos ``MorphoSetup-N.bin`` ao lado dele: o pacote tem
vários GB e um executável do Windows não pode passar de 4 GB, então os dados
vão nesses arquivos. Para instalar em outro computador, leve todos juntos.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = r"C:\Users\vinic\dlc-lab\dist\Morpho"
DEFAULT_OUT = r"C:\Users\vinic\dlc-lab\dist\instalador"
DEFAULT_ISCC = r"C:\Users\vinic\dlc-lab\tools\InnoSetup\ISCC.exe"
# Arquivos de texto que o Inno Setup lê: precisam da marca de UTF-8 no começo, senão os acentos saem trocados.
TEXT_FILES = ("installer/morpho.iss", "installer/antes-de-instalar.txt")


def gpu_name() -> str | None:
    """A placa de vídeo daqui, como o Windows a chama: é para ela que os modelos otimizados servem."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                             text=True, timeout=20, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    names = [line.strip() for line in out.splitlines() if line.strip()]
    return names[0] if names else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--iscc", default=DEFAULT_ISCC)
    args = parser.parse_args()
    source, out = os.path.abspath(args.source), os.path.abspath(args.out)
    if not os.path.isfile(os.path.join(source, "Morpho.exe")):
        raise SystemExit(f"{source} não é um pacote do Morpho (rode packaging/build.py antes).")
    if not os.path.isfile(args.iscc):
        raise SystemExit(f"Não achei o compilador do Inno Setup em {args.iscc}.")

    # Sobras de execuções de teste do pacote não vão para o instalador.
    for root, folders, _files in os.walk(source):
        for name in list(folders):
            if name == "__pycache__":
                shutil.rmtree(os.path.join(root, name), ignore_errors=True)
                folders.remove(name)
    for name in TEXT_FILES:
        path = os.path.join(HERE, name)
        with open(path, "rb") as f:
            data = f.read()
        if not data.startswith(b"\xef\xbb\xbf"):
            with open(path, "wb") as f:
                f.write(b"\xef\xbb\xbf" + data)

    command = [args.iscc, "/Qp", f"/DSource={source}", f"/DOutput={out}"]
    cache = os.path.join(source, "engine", "models", "trt_cache")
    gpu = gpu_name() if os.path.isdir(cache) and os.listdir(cache) else None
    if gpu:
        command.append(f"/DGpuName={gpu}")
        print(f"Modelos otimizados: só serão instalados em computadores com a placa “{gpu}”.")
    command.append(os.path.join(HERE, "installer", "morpho.iss"))
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(out):   # um instalador antigo com mais pedaços deixaria .bin sobrando
        if name.startswith("MorphoSetup"):
            os.remove(os.path.join(out, name))
    started = time.time()
    print("Comprimindo (vários GB: leva alguns minutos)…", flush=True)
    code = subprocess.run(command).returncode
    if code != 0:
        raise SystemExit(f"O Inno Setup falhou (código {code}).")
    total = 0
    print(f"\nPronto em {time.time() - started:.0f} s:")
    for name in sorted(os.listdir(out)):
        if name.startswith("MorphoSetup"):
            size = os.path.getsize(os.path.join(out, name))
            total += size
            print(f"  {os.path.join(out, name)}   {size / 2**20:8.0f} MB")
    print(f"  total {total / 2**30:.2f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
