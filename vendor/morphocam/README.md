# Morpho Camera — filtro da câmera virtual

Filtro DirectShow que os programas de vídeo (Meet, Zoom, Discord, OBS) carregam quando a
pessoa escolhe a câmera "Morpho Camera". O app entrega os quadros a ele por memória
compartilhada (`app/engine/morphocam.py`).

## Origem e licença

Derivado do filtro do [Unity Capture](https://github.com/schellingb/UnityCapture)
(commit `3ed54c3`), de Bernhard Schelling, sob licença MIT; o aviso de direitos autorais
e o texto da licença estão no topo de `MorphoCameraFilter.cpp`. `streams.cpp` e
`streams.h` vieram sem alteração.

## O que mudou em relação ao original

- Nome ("Morpho Camera"), identificadores (CLSID) e nomes dos objetos de memória
  compartilhada próprios: convive com um Unity Capture instalado.
- Resoluções oferecidas até 1080p, com 720p como padrão.
- Sem imagem do app, mostra uma tela escura de "Câmera em pausa" no lugar dos padrões
  coloridos de erro; a página de propriedades (que configurava esses padrões) saiu.
- O tamanho que o programa de vídeo negociou é publicado na memória compartilhada, para o
  app já enviar o quadro nesse tamanho.
- A negociação de formato compara tamanho e tipo de pixel, em vez de exigir o tipo
  idêntico byte a byte (o original recusava a conexão do OpenCV), e pedidos de formato
  que o filtro não produz (YUY2, por exemplo) são recusados em vez de aceitos.
- Diagnóstico em arquivo, ligado pela variável de ambiente `MORPHO_CAMERA_LOG`.

## Compilar

    build.cmd [pasta de saída]

Precisa do Visual Studio 2019 Build Tools (C++). Gera `MorphoCamera64.dll` e
`MorphoCamera32.dll`; a pasta padrão é `C:\Users\vinic\dlc-lab\morphocam`, a mesma que o
app usa (`app/paths.py`).

## Registro no Windows

O app registra a câmera sozinho, para o usuário atual, sem pedir permissão de
administrador (`morphocam.ensure_registered`). Para registrar para a máquina toda, como um
instalador faria: `regsvr32 MorphoCamera64.dll` num terminal de administrador.
