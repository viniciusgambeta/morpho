# -*- coding: utf-8 -*-
"""Gera as formas da animação "transformando" do Ganso Morpho e grava dentro de ../ganso.js.

Cada forma (ganso, jacaré, cachorro, passarinho, gente) é desenhada em camadas, só em preto e branco.
Cada camada tem o MESMO número de pontos em todas as formas, na mesma ordem, e é isso que permite
deslizar de uma forma para a outra (morph).

Os desenhos são construídos como um logo: discos, cápsulas e "cascos" (o contorno esticado em volta de
alguns discos), somados, recortados e com as emendas arredondadas. Para mexer num desenho, altere os
números em FORMAS, lá embaixo, e rode de novo.

Uso:      python mascote/ferramentas/gerar_formas.py            (grava em ganso.js)
          python mascote/ferramentas/gerar_formas.py --previa   (grava também mascote/_formas.html)
Precisa:  numpy e opencv-python
"""
import os
import re
import sys

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
GANSO_JS = os.path.join(AQUI, '..', 'ganso.js')
CX = 256.0        # eixo de simetria do desenho
TRACO = 18.8      # traço das partes brancas; metade fica para fora (9.4), como no desenho original
R = 6             # pixels por unidade nas contas feitas com imagem
N = 512 * R

# camadas, de trás para a frente: (nome, pontos por contorno, nº de contornos, cor, traço)
CAMADAS = [
    ('ex1', 24, 1, 'papel', TRACO),      # extras atrás dos óculos: orelhas, topete
    ('ex2', 24, 1, 'papel', TRACO),
    ('baixo', 40, 1, 'tinta', 0),        # parte de baixo, sempre preta (mandíbula, boca aberta)
    ('dentes', 4, 12, 'papel', 2.6),     # doze dentes, cada um com quatro pontos
    ('lingua', 16, 1, 'papel', 9),
    ('cima', 72, 1, 'papel', TRACO),     # parte de cima, branca (bico, focinho, nariz)
    ('narE', 12, 1, 'tinta', 0),
    ('narD', 12, 1, 'tinta', 0),
    ('det', 8, 8, 'tinta', 0),           # oito detalhes pretos por cima (escamas, pintas, bigode, sobrancelhas)
]


# ------------------------------------------------------------------ leitura do ganso original
def caminhos_do_ganso():
    js = open(GANSO_JS, encoding='utf-8').read()
    bloco = js[js.index('var P = {'):]
    return dict(re.findall(r'(\w+): "([^"]+)"', bloco[:bloco.index('};')]))


def poli(d, por_curva=24):
    """Caminho SVG (só M, C, L, Z absolutos) -> lista de pontos."""
    tok = re.findall(r'[MCLZ]|-?\d+(?:\.\d+)?', d)
    i, cur, pts = 0, None, []
    while i < len(tok):
        c = tok[i]; i += 1
        if c in 'ML':
            cur = np.array([float(tok[i]), float(tok[i + 1])]); i += 2; pts.append(cur)
        elif c == 'C':
            b = np.array([float(v) for v in tok[i:i + 6]]).reshape(3, 2); i += 6
            t = np.linspace(0, 1, por_curva + 1)[1:, None]
            pts.extend(((1 - t) ** 3) * cur + 3 * ((1 - t) ** 2) * t * b[0] + 3 * (1 - t) * t * t * b[1] + t ** 3 * b[2])
            cur = b[2]
    return np.array(pts)


# ------------------------------------------------------------------ desenho com discos e cascos
def tela():
    return np.zeros((N, N), np.uint8)


def _px(v):
    return int(round(v * R))


def disco(x, y, r):
    m = tela(); cv2.circle(m, (_px(x), _px(y)), _px(r), 1, -1); return m


def oval(x, y, rx, ry, giro=0.0):
    m = tela(); cv2.ellipse(m, (_px(x), _px(y)), (_px(rx), _px(ry)), giro, 0, 360, 1, -1); return m


def casco(*discos):
    """A forma esticada em volta de vários discos (x, y, raio): dois dão uma cápsula, três um triângulo redondo."""
    a = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    pts = np.vstack([np.c_[x + r * np.cos(a), y + r * np.sin(a)] for x, y, r in discos])
    m = tela(); cv2.fillConvexPoly(m, cv2.convexHull(np.round(pts * R).astype(np.int32)), 1); return m


def cadeia(*discos):
    """Cascos emendados de disco em disco: um tubo que engrossa e afina."""
    return uniao(*[casco(a, b) for a, b in zip(discos, discos[1:])])


def mascara(p):
    m = tela(); cv2.fillPoly(m, [np.round(np.asarray(p) * R).astype(np.int32)], 1); return m


def uniao(*ms):
    o = ms[0].copy()
    for m in ms[1:]:
        o |= m
    return o


def inter(a, b): return a & b
def menos(a, b): return a & (1 - b)
def espelha_m(m): return m[:, ::-1].copy()
def abaixo(y): m = tela(); m[_px(y):, :] = 1; return m
def acima(y): m = tela(); m[:_px(y), :] = 1; return m
def a_direita(x): m = tela(); m[:, _px(x):] = 1; return m
def a_esquerda(x): m = tela(); m[:, :_px(x)] = 1; return m


def cresce(m, r):
    return (cv2.distanceTransform(1 - m, cv2.DIST_L2, 5) <= r * R).astype(np.uint8)


def encolhe(m, r):
    return (cv2.distanceTransform(m, cv2.DIST_L2, 5) > r * R).astype(np.uint8)


def alisa(m, dentro, fora=0.0):
    """Arredonda as emendas: 'dentro' enche os cantos reentrantes; 'fora' gasta as pontas."""
    if dentro:
        m = encolhe(cresce(m, dentro), dentro)
    if fora:
        m = cresce(encolhe(m, fora), fora)
    return m


def contorno(m):
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea)[:, 0, :].astype(float) / R
    k = 7
    pad = np.vstack([c[-k:], c, c[:k]]); ker = np.ones(k) / k
    return np.c_[np.convolve(pad[:, 0], ker, 'same'), np.convolve(pad[:, 1], ker, 'same')][k:-k]


# ------------------------------------------------------------------ mesmos pontos em todas as formas
def horario(p):
    x, y = p[:, 0], p[:, 1]
    return (x * np.roll(y, -1) - np.roll(x, -1) * y).sum() > 0


def _reparte(p, n):
    """n pontos de p[0] (incluído) a p[-1] (excluído), mais juntos onde a curva vira mais."""
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    total = s[-1]
    if total < 1e-6:
        return np.repeat(p[:1], n, axis=0)
    pos = lambda u: np.c_[np.interp(u, s, p[:, 0]), np.interp(u, s, p[:, 1])]
    ss = np.linspace(0, total, max(80, int(total * 3)))
    j = min(4.0, total / 8)
    v1 = pos(ss) - pos(np.clip(ss - j, 0, total))
    v2 = pos(np.clip(ss + j, 0, total)) - pos(ss)
    vira = np.abs(np.arctan2(v1[:, 0] * v2[:, 1] - v1[:, 1] * v2[:, 0], (v1 * v2).sum(1))) / j
    peso = 1 + 1.3 * np.minimum(vira * 14.0, 3.0)
    custo = np.r_[0, np.cumsum((peso[1:] + peso[:-1]) / 2 * np.diff(ss))]
    return pos(np.interp(np.linspace(0, custo[-1], n, endpoint=False), custo, ss))


class Forma(object):
    """Um contorno com dois marcos: o começo (ponto 0) e o meio (ponto n/2). São esses marcos que
    alinham uma forma com a outra e evitam que o desenho 'torça' durante o morph."""

    def __init__(self, p, eixo=True):
        p = np.asarray(p, float)
        if not horario(p):
            p = p[::-1]
        m = len(p)
        if eixo:      # marcos onde o contorno cruza o eixo de simetria: o de cima e o de baixo
            cruz = [i for i in range(m) if (p[i, 0] - CX) * (p[(i + 1) % m, 0] - CX) <= 0 and p[i, 0] != p[(i + 1) % m, 0]]
            self.i0, self.im = min(cruz, key=lambda i: p[i, 1]), max(cruz, key=lambda i: p[i, 1])
        else:         # marcos no ponto mais alto e no mais baixo
            self.i0, self.im = int(np.argmin(p[:, 1])), int(np.argmax(p[:, 1]))
        self.p = p

    def pontos(self, n):
        p, m = self.p, len(self.p)
        ida = np.array([p[(self.i0 + k) % m] for k in range(((self.im - self.i0) % m) + 1)])
        volta = np.array([p[(self.im + k) % m] for k in range(((self.i0 - self.im) % m) + 1)])
        return np.vstack([_reparte(ida, n // 2), _reparte(volta, n - n // 2)])


def forma(m, eixo=True):
    """Máscara -> contorno com marcos."""
    return Forma(contorno(m), eixo)


def some(x, y):
    """Parte que não existe nesta forma: encolhe até sumir num ponto escondido."""
    a = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    return Forma(np.c_[x + 0.5 * np.cos(a), y + 0.5 * np.sin(a)], eixo=False)


class Dentes(object):
    """Doze dentes. Cada um nasce num trecho de gengiva (de p0 a p1) e cresce 'altura' para fora.
    ponta: 1 = dente quadrado (de gente); perto de 0 = pontudo (de jacaré)."""

    def __init__(self, lista, esconde):
        self.lista, self.esconde = lista, esconde

    def pontos(self, n):
        pts = []
        for i in range(12):
            if i < len(self.lista):
                p0, p1, alt, ponta = self.lista[i]
                p0, p1 = np.array(p0, float), np.array(p1, float)
                d = p1 - p0; comp = np.linalg.norm(d) or 1.0; d /= comp
                nor = np.array([-d[1], d[0]])           # para baixo de quem anda da esquerda para a direita
                meio = (p0 + p1) / 2 + nor * alt
                pts += [p0, p1, meio + d * comp / 2 * ponta, meio - d * comp / 2 * ponta]
            else:
                e = np.array(self.esconde, float) + [i * 0.4, 0]
                pts += [e, e + [0.3, 0], e + [0.3, 0.3], e + [0, 0.3]]
        return np.array(pts)


def gengiva(m, de, ate, quantos, largura, altura, ponta):
    """Dentes espalhados ao longo do contorno de uma máscara, entre as frações 'de' e 'ate' do trecho de baixo."""
    c = contorno(m)
    if horario(c):
        c = c[::-1]                                     # anti-horário: desce pela esquerda, sobe pela direita
    i0 = int(np.argmin(c[:, 1]))
    c = np.roll(c, -i0, axis=0)
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))]
    pos = lambda u: np.array([np.interp(u, s, c[:, 0]), np.interp(u, s, c[:, 1])])
    out = []
    for k in range(quantos):
        u = s[-1] * (de + (ate - de) * (k + 0.5) / quantos)
        out.append((pos(u - largura / 2), pos(u + largura / 2), altura, ponta))
    return out


# ------------------------------------------------------------------ as formas
G = caminhos_do_ganso()
GANSO_BRANCO = mascara(poli(G['bicoBranco']))
TOPO = inter(GANSO_BRANCO, acima(262))       # o alto do bico original: jacaré e cachorro nascem dele
ATRAS_E, ATRAS_D = (150, 205), (360, 205)    # esconderijos atrás das lentes
SOME_DET = [some(132 + 9 * i, 200 + 4 * (i % 3)) for i in range(4)] + [some(338 + 9 * i, 200 + 4 * (i % 3)) for i in range(4)]


def par(m):
    """(esquerda, direita): a máscara e o seu espelho."""
    return m, espelha_m(m)


def bolinha(x, y, r):
    return Forma(contorno(disco(x, y, r)), eixo=False)


FORMAS = {}

# ---- ganso: o bico original. O que não existe nele fica guardado atrás do branco ou atrás das lentes.
FORMAS['ganso'] = dict(
    ex1=some(*ATRAS_E), ex2=some(*ATRAS_D),
    baixo=Forma(poli(G['mandibula'])),
    dentes=Dentes([], (236, 344)),
    lingua=some(256, 346),
    cima=Forma(poli(G['bicoBranco'])),
    narE=Forma(poli(G['narinaE']), eixo=False), narD=Forma(poli(G['narinaD']), eixo=False),
    det=SOME_DET,
)

# ---- jacaré, visto de frente e de cima: cabeça larga atrás dos óculos, focinho comprido que estreita e
#      termina num nariz de dois gomos, mandíbula preta aparecendo em volta, dentes para fora e escamas no meio.
ponta = uniao(disco(CX - 29, 422, 27), disco(CX + 29, 422, 27))
focinho = uniao(cadeia((CX, 262, 72), (CX, 328, 56), (CX, 394, 62)), ponta, disco(CX - 50, 268, 46), disco(CX + 50, 268, 46))
jac_cima = alisa(uniao(TOPO, focinho), 18)
jac_baixo = cresce(uniao(cadeia((CX, 344, 56), (CX, 394, 62)), ponta), 9.4 + 17)
jac_borda = cresce(uniao(cadeia((CX, 318, 56), (CX, 394, 62)), ponta), 8.8)         # onde os dentes nascem


def escama(y, larg):
    return forma(casco((CX - larg, y + 4.5, 2.4), (CX, y - 4.5, 2.4), (CX + larg, y + 4.5, 2.4)))


FORMAS['jacare'] = dict(
    ex1=some(*ATRAS_E), ex2=some(*ATRAS_D),
    baixo=forma(jac_baixo),
    dentes=Dentes(gengiva(jac_borda, 0.17, 0.83, 12, 17, 15, 0.1), (256, 330)),
    lingua=some(256, 330),
    cima=forma(jac_cima),
    narE=forma(oval(CX - 27, 420, 10, 6.2, 28), eixo=False), narD=forma(oval(CX + 27, 420, 10, 6.2, -28), eixo=False),
    det=[escama(284, 15), escama(310, 13.5), escama(336, 12), escama(362, 10.5)] + SOME_DET[4:],
)

# ---- cachorro, de frente: focinho de duas bochechas, nariz grande (as narinas se juntam), boca aberta,
#      língua de fora com o risco do meio, pintas do bigode e orelhas caídas.
bochechas = uniao(disco(CX - 36, 320, 50), disco(CX + 36, 320, 50))
cao_cima = alisa(uniao(TOPO, cadeia((CX, 250, 36), (CX, 300, 44)), bochechas), 16)
nariz_cao = casco((CX - 21, 256, 10.5), (CX + 21, 256, 10.5), (CX, 279, 9.5))
orelha_e = casco((104, 160, 14), (68, 206, 30), (54, 288, 33))
FORMAS['cachorro'] = dict(
    ex1=forma(orelha_e, eixo=False), ex2=forma(espelha_m(orelha_e), eixo=False),
    baixo=forma(inter(disco(CX, 364, 46), abaixo(330))),
    dentes=Dentes([], (236, 340)),
    lingua=forma(casco((CX + 5, 372, 17.5), (CX + 10, 414, 16)), eixo=False),
    cima=forma(cao_cima),
    narE=forma(inter(nariz_cao, a_esquerda(CX + 1.5)), eixo=False), narD=forma(inter(nariz_cao, a_direita(CX - 1.5)), eixo=False),
    det=[forma(casco((CX, 289, 2.5), (CX, 352, 2.5)), eixo=False),            # risco do meio do focinho
         forma(casco((CX + 6.5, 388, 1.8), (CX + 9.5, 410, 1.8)), eixo=False),  # risco da língua
         bolinha(CX - 52, 316, 3.5), bolinha(CX - 67, 330, 3.5), bolinha(CX - 50, 339, 3.5),
         bolinha(CX + 52, 316, 3.5), bolinha(CX + 67, 330, 3.5), bolinha(CX + 50, 339, 3.5)],
)

# ---- passarinho, de frente: bico pequeno em triângulo redondo, parte de baixo preta e topete de três penas.
def pena(ang, comp, larg, curva=0.0):
    """Uma pena que sai do alto da cabeça: fina na base, larga no meio, fina na ponta."""
    a = np.radians(ang); d = np.array([np.sin(a), -np.cos(a)]); lado = np.array([d[1], -d[0]])
    base = np.array([CX, 184.0]); meio = base + d * comp * 0.58 + lado * curva; fim = base + d * comp + lado * curva * 2.2
    return cadeia((base[0], base[1], 4.5), (meio[0], meio[1], larg), (fim[0], fim[1], 3.2))


topete = alisa(uniao(pena(-31, 86, 9.5, -5), pena(0, 110, 10.5), pena(31, 86, 9.5, 5)), 2.5)
FORMAS['passarinho'] = dict(
    ex1=forma(topete), ex2=some(*ATRAS_D),
    baixo=forma(casco((CX - 23, 292, 9), (CX + 23, 292, 9), (CX, 333, 7))),
    dentes=Dentes([], (246, 266)),
    lingua=some(256, 272),
    cima=forma(casco((CX - 33, 252, 11), (CX + 33, 252, 11), (CX, 306, 8))),
    narE=forma(oval(CX - 10, 264, 3, 4.2, 12), eixo=False), narD=forma(oval(CX + 10, 264, 3, 4.2, -12), eixo=False),
    det=[bolinha(CX - 84, 306, 13), bolinha(CX + 84, 306, 13)] + SOME_DET[2:],     # bochechas
)

# ---- gente, de frente: nariz, bigode, sorriso com dentes, orelhas e sobrancelhas por cima dos óculos.
nariz = alisa(uniao(cadeia((CX, 244, 9), (CX, 294, 19)), disco(CX - 19, 302, 11), disco(CX + 19, 302, 11)), 8)
bigode_e = cadeia((CX - 3, 331, 7), (CX - 27, 338, 11), (CX - 53, 337, 8), (CX - 74, 323, 3.2))
sobr_e = casco((206, 117, 7.5), (150, 103, 7), (100, 121, 3.6))
orelha_gente = casco((60, 197, 22), (66, 233, 15))
boca = alisa(inter(disco(CX, 322, 72), abaixo(357)), 0, 3.5)
FORMAS['gente'] = dict(
    ex1=forma(orelha_gente, eixo=False), ex2=forma(espelha_m(orelha_gente), eixo=False),
    baixo=forma(boca),
    dentes=Dentes([((CX - 55 + 14 * i, 358), (CX - 55 + 14 * i + 12, 358), 11.5, 0.86) for i in range(8)], (250, 298)),
    lingua=some(256, 298),
    cima=forma(nariz),
    narE=forma(oval(CX - 11, 305, 5, 3, -15), eixo=False), narD=forma(oval(CX + 11, 305, 5, 3, 15), eixo=False),
    det=[forma(bigode_e, eixo=False), forma(espelha_m(bigode_e), eixo=False),
         forma(sobr_e, eixo=False), forma(espelha_m(sobr_e), eixo=False)] + SOME_DET[4:],
)

ORDEM = ['ganso', 'jacare', 'cachorro', 'passarinho', 'gente']
# quanto as curvas são arredondadas em cada camada (0 = cantos vivos); o padrão é 1/6
VIVA = {('jacare', 'dentes'): 0.03, ('gente', 'dentes'): 0.12}


# ------------------------------------------------------------------ saída
def pontos(nome, camada, n, k):
    f = FORMAS[nome][camada]
    if camada == 'dentes':
        return f.pontos(n)
    if k == 1:
        return f.pontos(n)
    return np.vstack([g.pontos(n) for g in f])


def caminho_svg(pts, n, tensao=1 / 6.0):
    d = ''
    for a in range(0, len(pts), n):
        p = pts[a:a + n]
        d += 'M%.1f %.1f' % tuple(p[0])
        for i in range(n):
            p0, p1, p2, p3 = p[i - 1], p[i], p[(i + 1) % n], p[(i + 2) % n]
            d += 'C%.1f %.1f %.1f %.1f %.1f %.1f' % (tuple(p1 + (p2 - p0) * tensao) + tuple(p2 - (p3 - p1) * tensao) + tuple(p2))
        d += 'Z'
    return d


def main():
    dados = {nome: {c: pontos(nome, c, n, k) for c, n, k, _, _ in CAMADAS} for nome in ORDEM}
    for nome in ORDEM:
        for c, n, k, _, _ in CAMADAS:
            assert len(dados[nome][c]) == n * k, (nome, c, len(dados[nome][c]))

    lin = ['  /*MORFO-INICIO (gerado por ferramentas/gerar_formas.py; não editar à mão)*/', '  var MORFO = {',
           '    camadas: [%s],' % ', '.join("['%s', %d, %d, '%s', %g]" % c for c in CAMADAS),
           '    viva: {%s},' % ', '.join("'%s/%s': %g" % (a, b, v) for (a, b), v in VIVA.items()),
           '    formas: {']
    for nome in ORDEM:
        lin.append('      %s: {' % nome)
        for c, n, k, _, _ in CAMADAS:
            lin.append('        %s: [%s],' % (c, ','.join('%d' % round(v * 10) for v in dados[nome][c].ravel())))
        lin.append('      },')
    lin += ['    }', '  };', '  /*MORFO-FIM*/']
    bloco = '\n'.join(lin)

    if '--so-previa' not in sys.argv:
        js = open(GANSO_JS, encoding='utf-8').read()
        ini, fim = js.index('  /*MORFO-INICIO'), js.index('/*MORFO-FIM*/') + len('/*MORFO-FIM*/')
        open(GANSO_JS, 'w', encoding='utf-8', newline='\n').write(js[:ini] + bloco + js[fim:])
        print('%d formas, %.1f KB gravados em ganso.js' % (len(ORDEM), len(bloco) / 1024.0))

    if '--previa' in sys.argv or '--so-previa' in sys.argv:
        oculos = ''.join('<path d="%s"/>' % G[k] for k in ('ponte', 'lenteE', 'lenteD')) + \
                 ''.join('<path fill="#fff" d="%s"/>' % G[k] for k in ('brilhoE', 'brilhoD'))
        h = ['<!doctype html><meta charset="utf-8"><title>formas</title><style>body{margin:6px;font:12px system-ui}'
             'div{display:inline-block;width:388px;border:1px solid #ddd;margin:2px}svg{display:block}</style>']
        for nome in ORDEM:
            corpo = ''
            for c, n, k, cor, traco in CAMADAS:
                estilo = 'fill="%s"' % ('#fff' if cor == 'papel' else '#000')
                if traco:
                    estilo += ' stroke="#000" stroke-width="%g" stroke-linejoin="round" paint-order="stroke"' % traco
                corpo += '<path %s d="%s"/>' % (estilo, caminho_svg(dados[nome][c], n, VIVA.get((nome, c), 1 / 6.0)))
            h.append('<div data-f="%s">%s<svg viewBox="16 60 480 440">%s<g%s>%s</g></svg></div>' % (
                nome, nome, corpo, ' opacity=".35"' if '--transparente' in sys.argv else '', oculos))
        # ?f=jacare,gente mostra só essas; ?w=300 muda a largura de cada quadro
        h.append('<script>var q=new URLSearchParams(location.search),f=q.get("f"),w=q.get("w");'
                 'document.querySelectorAll("div").forEach(function(d){if(f&&f.split(",").indexOf(d.dataset.f)<0)d.remove();'
                 'else if(w)d.style.width=w+"px"})</script>')
        open(os.path.join(AQUI, '..', '_formas.html'), 'w', encoding='utf-8').write('\n'.join(h))
        print('prévia em mascote/_formas.html')


if __name__ == '__main__':
    main()
