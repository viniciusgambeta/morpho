# Morpho — troca de rosto ao vivo

App para Windows de troca de rosto ao vivo, com o motor do fork
[beekamai/DeepLiveCam](https://github.com/beekamai/DeepLiveCam) (HyperSwap 256 + TensorRT),
uma interface própria, mais simples, e uma câmera virtual própria ("Morpho Camera").
Uso pessoal, neste computador.

## Estado

**Os quatro marcos estão feitos:** o app tem a tela de escolher o rosto e a câmera, manda a
troca para a câmera virtual "Morpho Camera" (que o Meet, o Zoom, o Discord e o OBS
enxergam), existe como **pacote que roda sozinho, com `Morpho.exe`**, e tem **instalador**
(`MorphoSetup.exe`), para este e para outros computadores com placa NVIDIA.

| Marco | O que entrega | Estado |
|---|---|---|
| 1 | Motor em processo próprio, preview, medição por etapa | feito |
| 2 | Tela simples: escolher rosto, conferir a câmera, trocar; avisos | feito |
| 3 | Câmera virtual própria e proteção do rosto real | feito |
| 4 | Pacote com `Morpho.exe` e instalador | feito |

## Abrir

Depois de instalado (`C:\Users\vinic\dlc-lab\dist\instalador\MorphoSetup.exe`), pelo atalho
"Morpho" do menu Iniciar ou da área de trabalho. Sem instalar, dois cliques em `Morpho.exe`
na pasta do pacote (`C:\Users\vinic\dlc-lab\dist\Morpho`). Na pasta de desenvolvimento o
equivalente é `Morpho.bat`, que usa o ambiente do laboratório.
Enquanto os modelos carregam, o palco mostra uma barra de progresso (o ritmo dela vem de
quanto a abertura levou da última vez).

A janela tem dois lados. **O palco, à esquerda, é a saída:** a imagem com o rosto trocado,
a mesma que os outros programas recebem. Antes de a troca começar ele mostra um passo a
passo, com o que já está feito marcado. **A coluna, à direita, são as escolhas:**

1. **Rosto:** clique no `+` (ou arraste uma foto para a janela). As fotos usadas ficam
   numa galeria; clicar em outra troca o rosto na hora, mesmo ao vivo. Botão direito numa
   miniatura remove da galeria. Foto em close funciona; foto sem rosto é recusada com aviso.
2. **Câmera:** a lista mostra as câmeras do computador, e logo abaixo aparece a prévia da
   escolhida, pequena, com o selo "só você vê": a imagem crua, para saber qual câmera é
   qual e se enquadrar. Ela nunca vai para a câmera virtual, e continua ali com a troca
   ligada (o antes, ao lado do depois). Qualidade (Leve, Padrão, Nítida) e espelhamento
   ficam embaixo. "Mostrar a prévia da câmera" desligado deixa a câmera apagada até a
   troca começar; com a janela minimizada a prévia também desliga a câmera.
3. **Saída:**
   - *Câmera virtual:* com ela marcada, a troca aparece nos outros programas como a câmera
     **"Morpho Camera"**: é só escolhê-la no Meet, Zoom, Discord ou OBS. Enquanto a troca
     não está ligada, quem escolheu essa câmera vê uma tela escura de "Câmera em pausa",
     então dá para deixar o outro programa pronto antes. A coluna avisa quando algum
     programa está de fato recebendo a imagem. Pode ser ligada e desligada ao vivo.
   - *Borrar se a troca falhar:* se o rosto não for encontrado (mão na frente, cabeça
     muito virada, pessoa fora do quadro), a imagem sai borrada em vez de mostrar o rosto
     real. Vem ligado. Vale para o palco e para a câmera virtual.
4. **Ajustes** (cartão recolhido; valem na hora, mesmo ao vivo):
   - *Nitidez:* realça os detalhes do rosto trocado.
   - *Intensidade da troca:* 100% mostra só o rosto escolhido; abaixo disso ele se mistura
     com o seu.
   - *Minha boca* e *Meus olhos:* deixam a sua boca e os seus olhos de verdade aparecerem.
     A fala e o olhar ficam mais naturais, mas essas partes passam a ser as suas.
5. **Trocar rostos / Parar** (o botão grande, fixo embaixo): a troca e a câmera virtual só
   funcionam entre um e outro. A linha menor do botão diz o que mais ele faz ("e iniciar
   câmera virtual"). Como a câmera já está aberta na prévia, a troca começa na hora.
   Fechar a janela desliga tudo.

Com a troca ao vivo, dois botões aparecem sobre o vídeo:

- **Tirar foto** (tecla F): salva a imagem atual em `Imagens\Morpho`.
- **Borrar agora** (tecla B): borra tudo na hora, no palco e na câmera virtual, até
  clicar de novo. Para quando for preciso sair da frente da câmera.

`Esc` para a troca. As escolhas (galeria, câmera, qualidade, ajustes, posição da janela)
são lembradas.

Avisos aparecem sobre o vídeo, em linguagem simples: câmera lenta, placa de vídeo
limitada, mais de um rosto no quadro, computador ocupado com outra tarefa pesada.
"Detalhes", no rodapé, abre o painel com os números descritos mais abaixo.

Capturas da interface em `docs/telas/`.

## A câmera virtual "Morpho Camera"

É um filtro DirectShow próprio (`MorphoCamera64.dll` e `MorphoCamera32.dll`), derivado do
filtro do [Unity Capture](https://github.com/schellingb/UnityCapture) (licença MIT). O
código, com as mudanças, está em `vendor/morphocam`; `vendor\morphocam\build.cmd` compila
os dois arquivos para `C:\Users\vinic\dlc-lab\morphocam` (precisa do Visual Studio 2019
Build Tools).

- **Instalação:** na primeira abertura o app registra a câmera no Windows para o usuário
  atual (`HKEY_CURRENT_USER`), o que não pede permissão de administrador, e avisa na
  tela. Programas que já estavam abertos só passam a listá-la depois de reabertos, e
  programas executados como administrador não a enxergam (o instalador do marco 4 pode
  registrar para a máquina toda). `preview.bat --remove-virtual-camera` desfaz o registro.
- **Como funciona:** o filtro e o app conversam por memória compartilhada
  (`app/engine/morphocam.py`). O filtro oferece de 144p a 1080p e o app já envia no
  tamanho que o outro programa pediu; sem imagem do app, o filtro mostra "Câmera em
  pausa". O envio custa menos de 1 ms por quadro em 720p.
- **Diagnóstico:** com a variável de ambiente `MORPHO_CAMERA_LOG` apontando para um
  arquivo, o filtro anota ali o que o programa de vídeo pede (formatos, conexão).
- **Reserva:** se os arquivos da câmera não existirem, o app usa a câmera virtual do OBS
  Studio, se ele estiver instalado.

## O pacote (`Morpho.exe`) e o instalador

`packaging/build.py` monta uma pasta com tudo o que o app precisa: `Morpho.exe`, o código
(`app`), o motor e os modelos (`engine`), o Python com as bibliotecas (`python`) e a câmera
virtual (`camera`). Cerca de 6 GB, quase tudo bibliotecas da NVIDIA (CUDA, cuDNN, TensorRT).

    packaging\launcher\build.cmd                 compila o Morpho.exe (ícone em packaging\make_icon.py)
    vendor\morphocam\build.cmd                   compila a câmera virtual
    <python do motor> packaging\build.py         monta a pasta em C:\Users\vinic\dlc-lab\dist\Morpho
    <python do motor> packaging\make_installer.py   gera o instalador em C:\Users\vinic\dlc-lab\dist\instalador

- **`Morpho.exe`** carrega o Python do pacote dentro do próprio processo e roda a janela.
  Por isso o que aparece na barra de tarefas e no Gerenciador de Tarefas é "Morpho", e
  fixar na barra de tarefas funciona. As mesmas opções do `preview.bat` valem para ele.
- **Dados:** o app do pacote guarda preferências, galeria e logs em `%LOCALAPPDATA%\Morpho`
  (não na pasta do laboratório, que é só do desenvolvimento). A galeria começa vazia.
- **Para qual placa de vídeo:** sem opções, `build.py` leva só os recursos do TensorRT da
  família de placa daqui (RTX 30), cerca de 6 GB. Com `--all-gpus` (como o instalador
  atual foi feito) leva os de todas as placas NVIDIA, cerca de 8 GB. Os modelos já
  otimizados para a placa daqui (`engine\models\trt_cache`) vão junto nos dois casos e
  poupam os minutos de otimização da primeira abertura.
- **Bibliotecas do C++:** `msvcp140.dll` e companhia vão na pasta `python`, para o app
  funcionar em computadores sem o Visual C++ Redistributable.
- **Modelos de rosto:** a biblioteca insightface só os lê de `~\.insightface`; o pacote
  traz uma cópia e o motor a põe lá na primeira abertura, sem baixar nada.
- **Instalador:** `packaging/make_installer.py` chama o Inno Setup 6 (instalado em modo
  portátil em `C:\Users\vinic\dlc-lab\tools\InnoSetup`) com o roteiro
  `packaging/installer/morpho.iss`. Sai o `MorphoSetup.exe` e arquivos `MorphoSetup-N.bin`
  ao lado dele: um executável do Windows não pode passar de 4 GB, então os dados vão
  nesses arquivos, e **eles precisam andar juntos**. Instala para o usuário atual (sem
  administrador) em `AppData\Local\Programs\Morpho`, cria os atalhos e, ao desinstalar,
  tira a câmera virtual do Windows. Os modelos já otimizados só são instalados em
  computador com a mesma placa de vídeo em que foram criados; nos outros, o app otimiza
  na primeira abertura (alguns minutos, uma vez).

## A página e o diagnóstico

**Página:** https://morpho-cam.vercel.app (projeto `morpho-cam` na Vercel). É um site
estático, sem etapa de montagem, na pasta `site/`: `index.html`, `faq.html`, `styles.css`,
`app.js`. Para publicar uma mudança:

    cd site
    npx vercel deploy --prod --yes

- `site/download.json` é a lista de arquivos do instalador (nome, endereço, tamanho e
  SHA-256 de cada um). A página e o diagnóstico leem esse arquivo; com `files` vazio, os
  dois dizem que o instalador ainda não foi publicado. O lugar onde os arquivos grandes
  ficam hospedados pode mudar só editando esse arquivo.
- As imagens são capturas reais do app (`site/tools/make_assets.py` gera as versões leves);
  os rostos vieram do thispersondoesnotexist.com, ou seja, são gerados por IA.
- A dobra do aviso do Windows é uma animação em HTML/CSS (`#aviso`), não um vídeo.

**Diagnóstico** (`diagnostico/`, C++ puro, um `.exe` de ~290 KB sem instalação):
`diagnostico\build.cmd` gera `C:\Users\vinic\dlc-lab\dist\diagnostico\MorphoDiagnostico.exe`,
que é copiado para `site/downloads/` antes de publicar.

- Mede Windows, placa de vídeo (nome, memória, driver), processador (com um teste rápido),
  memória, disco e webcam, e dá uma nota de 0 a 100. A referência é o computador em que o
  Morpho foi medido (RTX 3060 de notebook); as outras placas entram por uma tabela de
  desempenho relativo em `src/probe.cpp`, que é **estimativa**.
- Com o PC aprovado, baixa o instalador para `Downloads\Morpho` (continua de onde parou e
  confere o SHA-256 de cada arquivo) e oferece abri-lo.
- Opções de teste: `--json ARQ`, `--shot ARQ.png`, `--fake referencia|top|fraco|sem-nvidia`,
  `--progress 0.4`, `--manifest URL`, `--auto-download ARQ`, `--folder PASTA`.

## Opções de desenvolvimento e teste

`preview.bat` abre o mesmo app com o terminal visível e aceita opções:

```
preview.bat --list-cameras
preview.bat --source "C:\caminho\foto.jpg" --camera "HD Webcam" --autostart
```

- `--source`, `--camera`, `--resolution`, `--mirror`: pré-selecionam o que na tela se
  escolhe com o mouse. `--autostart` clica em Trocar rostos sozinho.
- `--set chave=valor`: opção do motor, por exemplo `--set reprojection=true`.
- `--replay video.avi`: usa um vídeo no lugar da câmera.
- `--record`: grava 40 s dos quadros crus da câmera (antes da troca), com um roteiro de
  movimentos na tela, para ajustar o rastreamento com imagem real. O arquivo fica só neste
  computador, em `C:\Users\vinic\dlc-lab\app-data\recordings`, fora do OneDrive.
- `--run-seconds`, `--stop-after`, `--quit-after`, `--offscreen`, `--report`,
  `--screenshot`: para testes automáticos.

`bench/engine_protocol_test.py` exercita o motor sem janela (42 verificações, incluindo
ler a câmera virtual de volta como um app de chamada faria) e `bench/track_eval.py` mede
o descolamento numa gravação.

## O que os detalhes técnicos mostram

- **Câmera entrega / processados / trocas aplicadas / saída / exibição:** quadros por
  segundo em cada ponto. "Processados" é o que passou pelo pipeline; "trocas aplicadas" é
  onde o rosto foi de fato trocado. Nenhum ajuste faz isso passar do que a câmera entrega.
- **Cabeça:** giro, inclinação e rotação estimados, a intensidade da troca e o tamanho do
  rosto na imagem.
- **Latência:** da captura até a troca pronta, e até a imagem de saída.
- **O que limita as trocas agora:** a câmera ou o processamento.
- **Etapas (ms):** tempo de cada passo do pipeline.
- **GPU:** uso, frequência, memória. Avisa se a placa estiver limitada pelo perfil de
  energia do notebook.

Cada execução grava em `C:\Users\vinic\dlc-lab\app-data`: o log do motor em `logs\`, as
medições segundo a segundo em `last-run.json` e as preferências em `settings.json`.

## Diferenças de comportamento em relação ao fork

- **Com mais de um rosto no quadro, a troca vai no maior.** O fork pega o rosto mais à
  esquerda, então um retrato na parede ou uma foto ao fundo pode "roubar" a troca. O app
  segue o maior rosto e só muda se outro ficar bem maior; o painel avisa quando há mais
  de um.
- **Sem reprojeção.** O fork mostra cada quadro novo com a troca do quadro anterior
  arrastada para a posição atual. Numa gravação real isso fez o rosto "descolar" em
  movimento (erro médio de 12% da distância entre os olhos, contra 2% sem ela; ver
  `bench/RESULTADOS.md`). Para religar: `--set reprojection=true`.
- **A troca nunca é escondida por causa do ângulo da cabeça.** O fork mostra o rosto real
  quando estima a cabeça além de 55° de giro ou 35° de inclinação, para não exibir uma
  troca borrada. Aqui a prioridade é não revelar o rosto real sem a pessoa pedir. Para
  voltar ao comportamento do fork: `--set head_yaw_limit=55 --set head_pitch_limit=35`.
- **Foto de origem em close** é aceita (margem automática).
- **O rosto real não vaza quando a troca falha.** No fork, um quadro sem rosto detectado
  sai cru, e quando o detector perde o rosto a troca esmaece por 1 s com o rosto real
  aparecendo por baixo. Aqui a troca fica opaca enquanto o rastreador ainda a carrega; se
  a falha durar mais de 0,25 s, a imagem sai borrada até a troca voltar. Dá para desligar
  na tela.

## Como está organizado

```
app/
  engine/        processo do motor
    __main__.py    laço de comandos e sessões (set_source, preview, start, stop,
                   set_output, set_option, quit)
    bridge.py      ponte para o motor do fork (configuração, foto de origem, câmeras)
    capture.py     fonte de quadros (câmera ou vídeo), gravação, ponto de encontro das threads
    pipeline.py    escolher o rosto -> rastrear -> landmarks -> pose -> trocar
    compose.py     monta a saída no ritmo da câmera
    output.py      câmera virtual e proteção do rosto real
    morphocam.py   a câmera virtual própria: registro no Windows e envio dos quadros
    stats.py       taxas, latências, tempo por etapa, estado da GPU
    events.py      eventos do motor para a janela (linhas JSON)
    trackdump.py   registro opcional de posições, para medir o descolamento
  ui/            processo da janela
    main_window.py   a tela: rosto, câmera, saída, ajustes, Trocar rostos/Parar
    widgets.py       palco, prévia da câmera, galeria, botão principal, controles
    assets/          o símbolo do app
    theme.py         cores, medidas e folha de estilo
    diagnostics.py   avisos, detalhes técnicos e resumo das medições
    settings.py      o que é lembrado entre aberturas
    engine_process.py  inicia o motor e converte a saída dele em sinais
  shared_frame.py  o quadro mais recente em memória compartilhada
vendor/morphocam/  código do filtro da câmera virtual e script de compilação
packaging/         Morpho.exe (launcher), montagem do pacote (build.py) e roteiro do instalador
diagnostico/       o programa de diagnóstico de compatibilidade (e de download do instalador)
site/              a página do Morpho, publicada na Vercel
bench/           scripts e resultados de medição (ver bench/RESULTADOS.md)
Morpho.bat           abre o app com dois cliques
preview.bat          abre com terminal e opções de teste
```

Dois processos de propósito: a janela não disputa CPU com o pipeline, e a saída não
depende de nenhuma janela estar aberta (o que a câmera virtual precisa). O motor carrega
os modelos uma vez e fica em espera; por isso trocar de rosto e clicar em Trocar rostos
respondem na hora. São dois canais de imagem para a janela: a saída (o palco) e a câmera
crua em tamanho pequeno (a prévia da coluna). Na prévia só o segundo anda: não há troca
nem câmera virtual.

## Onde ficam as coisas grandes

Fora desta pasta, para o OneDrive não sincronizar gigabytes:

- `C:\Users\vinic\dlc-lab\beekamai`: clone do fork no commit `766b9ce`, com o ambiente
  Python 3.12 e os modelos. Em desenvolvimento o app usa o motor direto de lá
  (`MORPHO_ENGINE_ROOT` aponta para outro lugar); o pacote leva uma cópia.
- `C:\Users\vinic\dlc-lab\dist`: o pacote montado (`Morpho`) e o `Morpho.exe` compilado.
- `C:\Users\vinic\dlc-lab\app-data`: preferências, medições, logs e gravações (definido
  por `MORPHO_DATA_DIR` nos dois `.bat`; sem ela o padrão é `%LOCALAPPDATA%\Morpho`).
- `C:\Users\vinic\dlc-lab\morphocam`: os arquivos compilados da câmera virtual. O registro
  no Windows aponta para lá (`MORPHO_CAMERA_DIR` muda o lugar).

## Licenças

O motor é AGPL-3.0, então este app também é: se for distribuído, o código precisa ser
aberto sob a mesma licença. Os modelos de troca de rosto (inswapper, HyperSwap) são de uso
não comercial. O filtro da câmera virtual deriva do Unity Capture, sob licença MIT (o aviso
de direitos autorais está no topo de `vendor/morphocam/MorphoCameraFilter.cpp`). Use só com
o consentimento de quem aparece na foto de origem.
