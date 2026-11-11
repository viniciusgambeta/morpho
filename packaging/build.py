"""Monta a pasta do app pronta para uso: tudo o que o Morpho precisa, num lugar só.

    <python do motor> packaging/build.py [--out PASTA] [--all-gpus] [--no-trt-cache]

O resultado é uma pasta que roda sozinha, sem depender do ambiente de
desenvolvimento:

    Morpho\\
      Morpho.exe     abre o app
      app\\           o código do app
      engine\\        o motor de troca de rosto (fork beekamai/DeepLiveCam) e os modelos
      python\\        o Python com as bibliotecas
      camera\\        a câmera virtual (Morpho Camera)
      licencas\\      licenças do que vai dentro

Antes de rodar: ``packaging\\launcher\\build.cmd`` (gera o Morpho.exe) e
``vendor\\morphocam\\build.cmd`` (gera os arquivos da câmera).

Por padrão o pacote é montado para ESTE computador, o que economiza uns 2 GB:

- leva só os recursos do TensorRT da família de placa de vídeo daqui (as
  outras famílias não conseguiriam otimizar os modelos). ``--all-gpus`` leva
  todos, para instalar em outros computadores;
- leva os modelos já otimizados para a placa daqui (``trt_cache``), para a
  primeira abertura não gastar minutos otimizando. ``--no-trt-cache`` deixa
  de fora.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

from app import paths  # noqa: E402

DEFAULT_OUT = r"C:\Users\vinic\dlc-lab\dist\Morpho"
LAUNCHER = r"C:\Users\vinic\dlc-lab\dist\launcher\Morpho.exe"

# O que o app usa do motor. O inswapper (outro modelo de troca, 550 MB) fica de fora.
ENGINE_FILES = ("run.py", "LICENSE")
ENGINE_FOLDERS = ("modules", "locales")
MODELS = ("hyperswap_1a_256.onnx", "1k3d68_192x192.onnx", "2d106det_192x192.onnx", "det_10g_640x640.onnx")
# Modelos otimizados (TensorRT) que não são do nosso modelo de troca: o do inswapper.
TRT_CACHE_SKIP = ("torch_jit_",)

# Do Python base: o que só serve para desenvolver ou testar o próprio Python.
PYTHON_SKIP_FOLDERS = ("__pycache__", "include", "libs", "Scripts", "BUILD", "site-packages", "test", "idlelib",
                       "ensurepip", "turtledemo")
# Das bibliotecas: ferramentas de instalação e partes do Qt que o app não usa
# (navegador embutido, PDF, editor de telas) — juntas passam de 350 MB.
PACKAGES_SKIP_FOLDERS = ("__pycache__", "pip", "pip-*.dist-info", "pyside6_webengine-*.dist-info",
                         "pyside6_pdf-*.dist-info", "qtwebengine_locales")
PACKAGES_SKIP_FILES = ("_virtualenv.pth", "_virtualenv.py", "Qt6WebEngine*.dll", "QtWebEngine*.py*", "QtWebEngineProcess.exe",
                       "qtwebengine*.pak", "qtwebengine*.bin", "v8_context_snapshot*.bin", "icudtl.dat",
                       "Qt6Pdf*.dll", "QtPdf*.py*", "Qt6Designer*.dll", "QtDesigner*.py*", "designer.exe",
                       "assistant.exe", "linguist.exe")
TRT_RESOURCE = "nvinfer_builder_resource_{}_10.dll"
TRT_FAMILIES = ("sm75", "sm80", "sm86", "sm89", "sm90", "sm100", "sm120")


def copy_tree(source: str, target: str, skip_folders=(), skip_files=()) -> None:
    """Cópia de pasta com o robocopy: rápida com muitos arquivos grandes."""
    command = ["robocopy", source, target, "/E", "/MT:16", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"]
    if skip_folders:
        command += ["/XD", *skip_folders]
    if skip_files:
        command += ["/XF", *skip_files]
    code = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).returncode
    if code >= 8:   # até 7 o robocopy está só contando o que copiou
        raise SystemExit(f"Falha ao copiar {source} -> {target} (robocopy {code})")


def copy_file(source: str, target: str) -> None:
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(source, target)


def folder_size(path: str) -> int:
    total = 0
    for root, _folders, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def gpu_family(cache: str) -> str | None:
    """A família da placa de vídeo daqui (``sm86`` numa RTX 30), lida do nome dos modelos já otimizados."""
    if not os.path.isdir(cache):
        return None
    for name in os.listdir(cache):
        for family in TRT_FAMILIES:
            if name.endswith(f"_{family}.engine"):
                return family
    return None


def base_python(engine: str) -> str:
    """O Python de onde o ambiente do motor foi criado (está escrito no pyvenv.cfg dele)."""
    with open(os.path.join(engine, "venv", "pyvenv.cfg"), encoding="utf-8") as f:
        for line in f:
            key, _, value = line.partition("=")
            if key.strip() == "home":
                return value.strip()
    raise SystemExit("Não achei o Python base do ambiente do motor.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--engine", default=paths.DEFAULT_ENGINE_ROOT, help="pasta do motor com o ambiente (venv)")
    parser.add_argument("--camera", default=paths.DEFAULT_CAMERA_ROOT, help="pasta com os arquivos da câmera virtual")
    parser.add_argument("--launcher", default=LAUNCHER)
    parser.add_argument("--all-gpus", action="store_true", help="leva os recursos do TensorRT de todas as placas")
    parser.add_argument("--no-trt-cache", action="store_true", help="não leva os modelos já otimizados para a placa daqui")
    args = parser.parse_args()

    out, engine = os.path.abspath(args.out), os.path.abspath(args.engine)
    for needed in (args.launcher, os.path.join(args.camera, "MorphoCamera64.dll"), os.path.join(engine, "run.py")):
        if not os.path.isfile(needed):
            raise SystemExit(f"Falta {needed}. Veja no começo deste arquivo o que compilar antes.")
    if os.path.isdir(out) and os.listdir(out):
        if not os.path.isfile(os.path.join(out, "Morpho.exe")):
            raise SystemExit(f"{out} já existe e não parece um pacote do Morpho; escolha outra pasta com --out.")
        print(f"Atualizando o pacote em {out}")
    started = time.time()

    def step(text: str) -> None:
        print(f"[{time.time() - started:5.0f} s] {text}", flush=True)

    step("Python")
    python = base_python(engine)
    copy_tree(python, os.path.join(out, "python"), PYTHON_SKIP_FOLDERS)

    step("bibliotecas (a parte grande: alguns minutos)")
    packages = os.path.join(out, "python", "Lib", "site-packages")
    family = gpu_family(os.path.join(engine, "models", "trt_cache"))
    skip_files = list(PACKAGES_SKIP_FILES)
    if not args.all_gpus:
        if family is None:
            raise SystemExit("Não descobri a família da placa de vídeo (não há modelos otimizados). Use --all-gpus.")
        skip_files += [TRT_RESOURCE.format(other) for other in TRT_FAMILIES if other != family]
    copy_tree(os.path.join(engine, "venv", "Lib", "site-packages"), packages, PACKAGES_SKIP_FOLDERS, skip_files)
    # Sobras de uma montagem anterior com outras opções.
    if not args.all_gpus:
        for other in TRT_FAMILIES:
            stale = os.path.join(packages, "tensorrt_libs", TRT_RESOURCE.format(other))
            if other != family and os.path.isfile(stale):
                os.remove(stale)

    # As bibliotecas de execução do C++ (msvcp140 e companhia): o ONNX Runtime precisa delas e nem
    # todo computador as tem instaladas. O PySide6 traz uma cópia redistribuível; ela vai para a
    # pasta do Python, onde todos os módulos a encontram.
    for name in os.listdir(os.path.join(packages, "PySide6")):
        if name.lower().startswith(("msvcp140", "concrt140")) and name.lower().endswith(".dll"):
            if not os.path.isfile(os.path.join(out, "python", name)):
                copy_file(os.path.join(packages, "PySide6", name), os.path.join(out, "python", name))

    step("motor e modelos")
    for name in ENGINE_FILES:
        copy_file(os.path.join(engine, name), os.path.join(out, "engine", name))
    for name in ENGINE_FOLDERS:
        copy_tree(os.path.join(engine, name), os.path.join(out, "engine", name), ("__pycache__",))
    for name in MODELS:
        source = os.path.join(engine, "models", name)
        target = os.path.join(out, "engine", "models", name)
        if not os.path.isfile(target) or os.path.getsize(target) != os.path.getsize(source):
            copy_file(source, target)
    pack = os.path.join(os.path.expanduser("~"), ".insightface", "models", "buffalo_l")
    if not os.path.isdir(pack):
        raise SystemExit(f"Não achei os modelos de rosto em {pack}.")
    copy_tree(pack, os.path.join(out, "engine", "models", "insightface", "buffalo_l"))
    cache_target = os.path.join(out, "engine", "models", "trt_cache")
    if args.no_trt_cache:
        shutil.rmtree(cache_target, ignore_errors=True)
    else:
        cache = os.path.join(engine, "models", "trt_cache")
        os.makedirs(cache_target, exist_ok=True)
        for name in os.listdir(cache):
            source, target = os.path.join(cache, name), os.path.join(cache_target, name)
            if any(part in name for part in TRT_CACHE_SKIP):
                continue
            if not os.path.isfile(target) or os.path.getsize(target) != os.path.getsize(source):
                copy_file(source, target)

    step("app, câmera virtual e Morpho.exe")
    copy_tree(os.path.join(PROJECT, "app"), os.path.join(out, "app"), ("__pycache__",))
    for bits in (64, 32):
        dll = os.path.join(args.camera, f"MorphoCamera{bits}.dll")
        if os.path.isfile(dll):
            copy_file(dll, os.path.join(out, "camera", f"MorphoCamera{bits}.dll"))
    copy_file(args.launcher, os.path.join(out, "Morpho.exe"))

    step("licenças")
    copy_tree(os.path.join(HERE, "licencas"), os.path.join(out, "licencas"))
    copy_file(os.path.join(engine, "LICENSE"), os.path.join(out, "licencas", "AGPL-3.0.txt"))
    copy_file(os.path.join(python, "LICENSE.txt"), os.path.join(out, "licencas", "Python.txt"))
    copy_tree(os.path.join(PROJECT, "vendor", "morphocam"), os.path.join(out, "licencas", "fonte-da-camera-virtual"))

    sizes = {name: folder_size(os.path.join(out, name)) for name in ("python", "engine", "app", "camera")}
    total = folder_size(out)
    step("pronto")
    print(f"\n{out}")
    for name, size in sizes.items():
        print(f"  {name:8s} {size / 2**30:6.2f} GB")
    print(f"  total    {total / 2**30:6.2f} GB"
          + ("" if args.all_gpus else f"  (só a família de placa {family}; --all-gpus leva todas)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
