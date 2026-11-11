"""Morpho: app de troca de rosto ao vivo.

Dois processos:

- ``app.engine``: captura a câmera, roda o pipeline de troca (motor do fork
  beekamai/DeepLiveCam) e publica cada quadro pronto em memória compartilhada.
- ``app.ui``: a janela. Só exibe quadros e estatísticas e manda comandos.

Separar os dois evita que a interface dispute CPU com o pipeline.
"""

APP_NAME = "Morpho"  # pasta de dados, pasta de fotos e título da janela
