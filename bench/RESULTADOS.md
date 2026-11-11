# Benchmark: Deep-Live-Cam original × fork beekamai

Medido em 10/11/2026 no Avell C62 MOB (RTX 3060 Laptop 6 GB, i7-11800H, 64 GB RAM),
Windows 11, driver NVIDIA 591.74, Python 3.12.13, onnxruntime-gpu 1.26.0.

- Original: `hacksider/Deep-Live-Cam` no commit `08896a5` (08/11/2026).
- Fork: `beekamai/DeepLiveCam` no commit `766b9ce` (16/09/2026, versão 3.2.0).

## Resultado com a placa destravada

Seis execuções em sequência (18:47–18:56), todas com a GPU entre 1500 e 1980 MHz.
Arquivos em `results/desempenho/`.

| Configuração | Trocas/s (vazão) | Entregue a 30 fps | Latência p50 / p95 | Modelo de troca | VRAM a mais |
|---|---|---|---|---|---|
| Original, só `requirements.txt` | 15,5 | 17,3 fps | 75 / 97 ms | 47 ms | 1,9 GB |
| Original + PyTorch (instalação NVIDIA documentada) | 24,7 | 23,5 fps | 58 / 82 ms | 27 ms | 2,3 GB |
| Fork, CUDA sem TensorRT | 9,2 | 11,1 fps | 101 / 158 ms | 72 ms | 3,2 GB |
| Fork, TensorRT + inswapper 128 | 18,1 | 18,2 fps | 72 / 91 ms | 33 ms | 1,8 GB |
| **Fork, TensorRT + HyperSwap 256** | **32,2** | **28,2 fps** | **42 / 68 ms** | **10 ms** | **1,4 GB** |
| Fork, TensorRT + HyperSwap 256, extras desligados | 40,2 | 30,0 fps | 28 / 36 ms | 10 ms | 1,3 GB |

"Extras desligados" = sem pose 3D da cabeça, máscara por contorno, devolução do piscar
e fade por ângulo (`head_pose`, `face_outline_mask`, `blink_reveal`, `head_outline`,
`pose_fade`).

Com o HyperSwap a GPU fica em cerca de 34% de uso: o limite passa a ser o trabalho de
CPU em volta do modelo (detecção, colagem, landmarks).

## Resultado com a placa travada (estado em que o notebook estava)

Antes de o serviço do Control Center voltar a rodar, a GPU ficava presa em 960 MHz e
cerca de 40 W sob carga, com `SW Thermal Slowdown: Active` a 59 °C.

| Configuração | Trocas/s | Latência p50 |
|---|---|---|
| Original, só `requirements.txt` | 9,5 | 123 ms |
| Original + PyTorch | 14,3 | 88 ms |
| Fork, CUDA sem TensorRT | 8,7 | 140 ms |
| Fork, TensorRT + inswapper 128 | 10,2 | 128 ms |
| Fork, TensorRT + HyperSwap 256 | 18,3 | 73 ms |

Só as três primeiras linhas têm arquivo preservado (`results/placa-travada/`). As duas
do TensorRT foram medidas, mas os arquivos foram sobrescritos por um lote que pegou a
mudança de estado no meio.

## Como foi medido

`replay_bench.py` passa o mesmo vídeo pelo `_ProcessingWorker` que o modo Live de cada
projeto usa, em duas passadas:

1. **Vazão:** todos os quadros o mais rápido possível. Cada quadro de saída é uma troca
   nova, então o número é trocas de rosto por segundo.
2. **Ritmada:** quadros entregues a 30 fps, descartando o mais antigo quando o pipeline
   não acompanha (como o app faz). Dá o fps entregue e a latência captura → quadro pronto.

Os 3 primeiros segundos são descartados. O script confere que a troca foi de fato
aplicada comparando a saída com o quadro original (100% dos quadros em todas as execuções).

O vídeo (`make_clip.py`) é sintético: 1280×720, 30 fps, 24 s, MJPG, com um rosto gerado
por IA sobre fundo fixo, um trecho parado e um trecho com translação, zoom e rotação.

## Limites desta medição

- **Vídeo sintético.** Sem mudança de expressão, sem mão na frente do rosto, sem
  iluminação real. Compara os motores; não valida a qualidade ao vivo.
- **Não mede a tela.** O fork reprojeta a última troca sobre cada quadro novo da câmera,
  então a imagem exibida fica a 30 fps mesmo com menos trocas por segundo. Isso acontece
  na janela de preview, fora do que o script mede.
- **Uma execução por configuração.** A repetição entre lotes variou até uns 10%.
- **GPU compartilhada.** Outros programas ocupavam de 2,0 a 2,5 GB de VRAM durante tudo.
- **Qualidade visual** foi só conferida a olho em quadros de amostra
  (`results/comparacao_rostos.jpg`: vídeo original, original+PyTorch, fork+inswapper,
  fork+HyperSwap). Não há métrica de semelhança.

## O que apareceu no caminho

- **Caminho rápido do original depende do PyTorch.** O modelo fp16 e o CUDA graph só
  ligam se `torch` com CUDA estiver instalado, e ele não está no `requirements.txt`.
- **Foto de origem em close falha em silêncio.** Um retrato 1024×1024 com o rosto
  ocupando o quadro não é detectado; o original segue rodando sem trocar e sem avisar.
  Com 200 px de margem em volta, funciona.
- **Primeira execução com TensorRT levou 4 minutos** compilando quatro motores. Depois
  disso a partida fica em 15–30 s.
- **TensorRT sem HyperSwap não compensa.** O fork compila o inswapper em fp32 (em fp16 o
  autor relata artefatos), e fica mais lento que o fp16 do original com CUDA graph.
- **Perfil de energia do notebook corta o desempenho quase pela metade** e é detectável
  pelo `nvidia-smi` (clock, estado P e `SW Thermal Slowdown`).
- **`insightface` não tem pacote pronto para Windows.** Foi compilado do código-fonte do
  PyPI com o MSVC; o fork traz um `.whl` próprio, que não foi usado.

## Pilha ao vivo completa: fork × nosso app (marco 1)

O que foi medido acima é só o worker de processamento. Ao vivo rodam também a captura,
a reprojeção e a janela. Aqui o mesmo vídeo entra no ritmo de uma câmera de 30 fps
(`live_stack_bench.py` para o fork, `python -m app.ui --replay` para o nosso app), com
HyperSwap 256 + TensorRT, todos os extras ligados e a placa destravada.

| | Trocas/s | Latência da troca (p50) | Quadros de câmera na saída/s | Latência da imagem (p50) |
|---|---|---|---|---|
| Fork, pilha ao vivo completa | 24,2 e 24,6 | 60 ms | 29,3 e 29,1 | 19–20 ms |
| Nosso app, motor em processo próprio | 25,9 · 27,9 · 26,8 | 45–47 ms | 29,0 a 29,8 | 22–24 ms |

- O teto é 30: a câmera simulada entrega 30 fps e o worker isolado faz 32.
- No nosso app o pipeline fica 91–92% ocupado: ele está no limite da CPU, não da GPU
  (que fica em ~31–39%).
- Uma execução do fork deu 4,3 trocas/s e foi descartada: a GPU estava em 88% de uso por
  outro programa naquele momento, e nenhum motor TensorRT foi recompilado.
- As duas medições rodaram sem janela na tela (`offscreen`), então não incluem o custo de
  pintar a imagem. A latência da imagem não é medida no mesmo ponto: no fork é quando a
  janela exibe; no nosso app é quando o motor publica o quadro (a janela soma até ~8 ms).
- **A pilha ao vivo sozinha não explica os 8 a 13 fps vistos no teste manual com câmera
  real:** com câmera simulada o fork faz 24.
- **Causa provável: outros programas pesados na mesma máquina.** Às 20:34 uma transcrição
  Whisper `large-v3` em CUDA e um script de edição de vídeo (de outro trabalho em
  andamento neste computador) começaram no meio de um teste do nosso app. No mesmo teste
  as trocas caíram de 30 para 7–12 por segundo, e a etapa de troca foi de 17 para 49–60 ms;
  numa execução inteira sob essa carga ficaram em 2–4 por segundo (troca em 120–220 ms).
  A execução descartada do fork acima tem a mesma assinatura. Não há como provar que algo
  assim rodava durante o teste manual, mas a faixa é a mesma.
- O preview agora grava o segundo a segundo de cada execução em
  `%LOCALAPPDATA%\DeepLiveSimple\last-run.json` e avisa quando a etapa de troca passa do
  dobro do melhor tempo já medido neste computador.
- O caminho de câmera real do nosso app ainda não foi exercitado: todos os testes usaram
  o vídeo no lugar da câmera.

Arquivos em `results/ao-vivo/`.

## Descolamento do rosto ao mexer a cabeça (gravação real)

Queixa no uso real: ao mexer a cabeça, o rosto trocado "descola". Medido em 10/11/2026
sobre uma gravação de 40 s da webcam embutida (785 quadros, 19,6 fps, 1280×720) com
roteiro de movimentos: parado, giro, inclinação, movimento rápido, aproximar/afastar, mão
na frente do rosto. Em 60% dos quadros o rosto se move mais de 5% da distância entre os
olhos de um quadro para o outro.

`track_eval.py` reproduz a gravação pelo app e compara, em cada imagem que iria para a
tela, onde a troca foi desenhada com onde o rosto está de fato naquele quadro (o detector
rodado quadro a quadro, sem suavização). Erro em % da distância entre os olhos, que nessa
gravação vale cerca de 100 px; ponderado pelo tempo em que cada imagem fica na tela.

| Configuração | Erro em movimento (média / p95) | Erro geral (média / p95) | Idade da imagem (média) |
|---|---|---|---|
| Com reprojeção (padrão do fork) | 12,7% / 68% e 11,4% / 71% | 10,8% / 66% e 9,7% / 63% | 25–26 ms |
| **Sem reprojeção (padrão do app)** | **1,9% / 4,0% e 1,9% / 4,1%** | **1,7% / 3,8% e 1,7% / 3,9%** | 33–34 ms |

Duas execuções de cada. Detalhe da execução com reprojeção:

| Tipo de imagem | Parado | Lento | Rápido |
|---|---|---|---|
| Troca exata (calculada para o próprio quadro) | 1,0% | 1,4% | 2,1% |
| Reprojetada (troca do quadro anterior arrastada) | 2,2% | 3,8% | 26,0% (p95 93%) |

- **A causa é a reprojeção.** A troca calculada para o próprio quadro fica a 1–2% do lugar
  certo em qualquer velocidade. A imagem reprojetada, que ocupa de 46% a 55% do tempo de
  tela, erra em média 26% em movimento rápido.
- **Desligar custa cerca de 8 ms** a mais na idade média da imagem e nenhum quadro: nas
  duas configurações 100% dos quadros da câmera foram processados.
- A reprojeção faz sentido quando o pipeline é bem mais lento que a câmera. Aqui ele
  acompanha, então ela só troca precisão por alguns milissegundos.

Limites: uma gravação, uma câmera, a 20 fps. A referência é o detector, com ruído de
1 a 2 px e menos confiável em giro extremo e com a mão na frente. O erro mede a posição
de cinco pontos do rosto, não a qualidade visual da troca: num giro grande o modelo de
troca em si se degrada, e isso não muda com este ajuste. Falta a confirmação a olho.

A gravação e os pontos quadro a quadro ficam em `C:\Users\vinic\dlc-lab\app-data\recordings`,
fora do OneDrive; em `results/rastreamento/` só há os números agregados.

## Reproduzir

Clones, ambientes e modelos ficam em `C:\Users\vinic\dlc-lab` (fora do OneDrive).
`run-batch.sh` nessa pasta roda as seis configurações; `summarize.py` imprime o resumo
de qualquer `bench_*.json`.
