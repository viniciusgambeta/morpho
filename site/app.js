// Morpho — comportamento da página: efeitos de rolagem, a demonstração em vídeo (comparação
// antes/depois com escolha de rosto e a maquete dos três passos), animação do aviso do
// Windows e a lista de arquivos do instalador.
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (id) { return document.getElementById(id); };
  var clamp = function (value, low, high) { return Math.max(low, Math.min(high, value)); };
  var smooth = function (t) { return t * t * (3 - 2 * t); };

  // ---- entrada das seções ---------------------------------------------------------------
  var reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !reduced) {
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { entry.target.classList.add("in"); seen.unobserve(entry.target); }
      });
    }, { threshold: 0.14, rootMargin: "0px 0px -50px 0px" });
    reveals.forEach(function (el) { seen.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add("in"); });
  }

  // ---- efeitos ligados à rolagem -----------------------------------------------------------
  // 1) imagens que crescem ao entrar na tela; 2) a frase que acende palavra por palavra.
  var nav = $("nav");
  var scaled = Array.prototype.slice.call(document.querySelectorAll("[data-scale]"));
  var scrub = $("scrub"), words = [];
  if (scrub) {
    // cada palavra vira um trecho próprio; os destaques (<em>) ganham cor
    var pieces = [];
    scrub.childNodes.forEach(function (node) {
      var highlight = node.nodeType === 1;
      (node.textContent || "").split(/(\s+)/).forEach(function (part) {
        if (part) pieces.push({ text: part, hi: highlight, space: /^\s+$/.test(part) });
      });
    });
    scrub.textContent = "";
    pieces.forEach(function (piece) {
      if (piece.space) { scrub.appendChild(document.createTextNode(" ")); return; }
      var span = document.createElement("span");
      span.textContent = piece.text;
      if (piece.hi) span.className = "hi";
      scrub.appendChild(span);
      words.push(span);
    });
    if (reduced) words.forEach(function (w) { w.style.opacity = 1; });
  }
  var ticking = false;
  function frame() {
    ticking = false;
    var height = window.innerHeight;
    if (nav) nav.classList.toggle("stuck", window.scrollY > 6);
    if (reduced) return;
    scaled.forEach(function (el) {
      var box = el.getBoundingClientRect();
      // 0 quando o topo ainda está bem embaixo na tela; 1 quando chega a um terço dela
      var p = clamp((height * 0.98 - box.top) / (height * 0.62), 0, 1);
      el.style.setProperty("--p", smooth(p).toFixed(4));
    });
    if (scrub && words.length) {
      var box = scrub.getBoundingClientRect();
      var p = clamp((height * 0.82 - box.top) / (box.height + height * 0.36), 0, 1);
      var lit = p * (words.length + 2);
      for (var i = 0; i < words.length; i++) words[i].style.opacity = clamp(lit - i, 0.14, 1);
    }
  }
  function onScroll() { if (!ticking) { ticking = true; requestAnimationFrame(frame); } }
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
  frame();

  // ---- a gravação da demonstração --------------------------------------------------------------
  // Cada arquivo traz o original em cima e a troca embaixo, no mesmo quadro. As duas metades são
  // desenhadas a partir de um vídeo só, então nunca saem de sincronia. Há um arquivo por rosto:
  // o do rosto marcado na página é carregado de início; assim que ele toca, os outros são
  // baixados inteiros em segundo plano, para a troca de rosto ser na hora. Com "reduzir
  // movimento" ligado nenhum vídeo é carregado e a página mostra o quadro inicial.
  var demo = (function () {
    var WIDE = 1280, HALF = 720;
    var chosen = document.querySelector("#pick button.on");
    var videos = {}, active = null, wanted = 0, current = chosen ? parseInt(chosen.getAttribute("data-face"), 10) : 1;
    var files = {}, fetches = {}, warmed = false;   // arquivos já inteiros na memória e os que estão a caminho
    var views = [], listeners = [], looping = false, dirty = true, drawn = -1;
    var quiet = function () {};
    function emit(what, face) { listeners.forEach(function (fn) { fn(what, face); }); }
    function start(video) { var playing = video.play(); if (playing && playing.catch) playing.catch(quiet); }
    function wantsPlay() {
      return !reduced && !document.hidden && views.some(function (view) { return view.visible; });
    }
    function paint() {
      if (!active || active.readyState < 2) return;
      dirty = false;
      drawn = active.currentTime;
      views.forEach(function (view) { if (view.visible) view.draw(active); });
    }
    function tick() {
      if (!active || !wantsPlay()) { looping = false; return; }
      if (dirty || active.currentTime !== drawn) paint();
      requestAnimationFrame(tick);
    }
    // O vídeo fica dentro da tela que está à vista (invisível, embaixo do desenho): celulares
    // pausam vídeo automático que não está na página ou que saiu da tela.
    function mount(video) {
      var host = null;
      for (var i = 0; i < views.length && !host; i++) if (views[i].visible && views[i].host) host = views[i].host;
      host = host || video.parentNode || (views[0] && views[0].host);
      if (host && video.parentNode !== host) host.insertBefore(video, host.firstChild);
    }
    function sync() {
      if (!active) return;
      if (wantsPlay()) {
        mount(active);                                  // mudar de lugar pausa o vídeo; a linha abaixo retoma
        if (active.paused) start(active);
        if (!looping) { looping = true; requestAnimationFrame(tick); }
      } else if (!active.paused) {
        active.pause();
      }
    }
    function adopt(video, face) {
      var old = active;
      active = video;
      current = face;
      if (old && old !== video) old.pause();
      dirty = true;
      sync();
      paint();
      emit("ready", face);
    }
    function source(face) { return "/assets/demo/troca-" + face + ".mp4"; }
    // Baixa o arquivo inteiro e o guarda na memória: o vídeo feito a partir dele abre e acha
    // qualquer ponto sem voltar à rede.
    function fetchFile(face) {
      if (!fetches[face]) {
        fetches[face] = fetch(source(face)).then(function (response) {
          if (!response.ok) throw new Error(response.status);
          return response.blob();
        }).then(function (blob) {
          files[face] = URL.createObjectURL(blob);
          return true;
        }).catch(function () { delete fetches[face]; return false; });
      }
      return fetches[face];
    }
    // Os outros rostos, um arquivo por vez, a começar pelos vizinhos do que está tocando.
    function warm(faces) {
      var slow = navigator.connection && /2g|3g/.test(navigator.connection.effectiveType || "");
      if (warmed || !api.auto || slow || !window.fetch || !window.URL) return;
      warmed = true;
      var order = faces.filter(function (face) { return face !== current; });
      order.sort(function (a, b) { return Math.abs(a - current) - Math.abs(b - current) || a - b; });
      var next = function () {
        if (!order.length) return;
        var face = order.shift();
        if (videos[face] || files[face]) next(); else fetchFile(face).then(next);
      };
      setTimeout(next, 600);
    }
    function make(face) {
      var video = document.createElement("video");
      video.muted = true; video.defaultMuted = true; video.loop = true; video.playsInline = true;
      video.setAttribute("muted", ""); video.setAttribute("playsinline", "");
      video.setAttribute("aria-hidden", "true"); video.setAttribute("disableremoteplayback", "");
      video.tabIndex = -1; video.disablePictureInPicture = true;
      video.style.cssText = "position:absolute;inset:0;width:100%;height:100%;opacity:0;pointer-events:none";
      video.preload = "auto";
      video.src = files[face] || source(face);
      videos[face] = video;
      mount(video);
      return video;
    }
    function use(face, silent) {
      if (reduced) { wanted = current = face; emit("ready", face); return; }
      if (face === wanted && (videos[face] || fetches[face])) return;   // já é o atual, ou já está a caminho
      wanted = face;
      if (!silent) emit("loading", face);
      // O arquivo deste rosto está no meio do download em segundo plano: espera por ele em vez
      // de pedir de novo. (Se o download falhar, o vídeo é aberto direto da rede.)
      if (!videos[face] && fetches[face] && !files[face]) {
        fetches[face].then(function () { if (wanted === face && !videos[face]) attach(face); });
        return;
      }
      attach(face);
    }
    function attach(face) {
      var video = videos[face] || make(face);
      var ready = function () {
        if (wanted !== face) return;
        var time = active && active !== video ? active.currentTime : null;
        if (time === null || Math.abs(video.currentTime - time) < 0.05) { adopt(video, face); return; }
        var land = function () {
          video.removeEventListener("seeked", land);
          if (wanted === face) adopt(video, face);
        };
        video.addEventListener("seeked", land);
        // Um pouco à frente: o vídeo atual continua andando enquanto o novo procura o ponto.
        video.currentTime = Math.min(time + 0.1, Math.max(0, (video.duration || 17.9) - 0.1));
      };
      if (video.readyState >= 2) { ready(); return; }
      video.addEventListener("loadeddata", ready, { once: true });
      video.addEventListener("error", function () {
        delete videos[face];
        if (video.parentNode) video.parentNode.removeChild(video);
        if (wanted === face) { wanted = active ? current : 0; emit("failed", face); }
      }, { once: true });
      // Tocar já, dentro do clique: navegadores que seguram vídeo automático aceitam assim.
      start(video);
    }
    document.addEventListener("visibilitychange", sync);
    var api = {
      WIDE: WIDE, HALF: HALF,
      use: use,
      warm: warm,
      // com "economia de dados" ligada o vídeo só é baixado quando o visitante toca na demonstração
      auto: !reduced && !(navigator.connection && navigator.connection.saveData),
      face: function () { return current; },
      on: function (fn) { listeners.push(fn); },
      view: function (view) { views.push(view); return view; },
      // algo mudou (a barra andou, uma tela entrou ou saiu de vista): redesenha e toca ou pausa
      refresh: function () { dirty = true; sync(); if (active && (active.paused || !looping)) paint(); },
      // um toque do visitante: se o navegador tinha segurado o vídeo, agora ele pode tocar
      poke: function () { var video = active || videos[wanted]; if (video && video.paused && wantsPlay()) start(video); }
    };
    return api;
  })();

  // ---- antes e depois ------------------------------------------------------------------------
  var compare = $("compare");
  if (compare) {
    var touched = false;
    var canvas = $("compare-canvas"), pen = canvas ? canvas.getContext("2d") : null;
    var after = $("compare-after"), pick = $("pick");
    var cut = 0.5;
    var hero = demo.view({
      visible: false,
      host: compare,
      draw: function (video) {
        if (!pen) return;
        var w = canvas.width, h = canvas.height, x = Math.round(w * cut), sx = x / w * demo.WIDE;
        // esquerda: metade de cima do arquivo (original); direita: metade de baixo (troca)
        if (x > 0) pen.drawImage(video, 0, 0, sx, demo.HALF - 1, 0, 0, x, h);
        if (x < w) pen.drawImage(video, sx, demo.HALF + 1, demo.WIDE - sx, demo.HALF - 1, x, 0, w - x, h);
        compare.classList.add("playing");
      }
    });
    var fit = function () {
      if (!canvas) return;
      var width = Math.min(demo.WIDE, Math.round(compare.offsetWidth * Math.min(window.devicePixelRatio || 1, 2)));
      if (width < 2 || width === canvas.width) return;
      canvas.width = width;
      canvas.height = Math.round(width * 9 / 16);
      demo.refresh();
    };
    fit();
    window.addEventListener("resize", fit);
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          hero.visible = entry.isIntersecting;
          if (entry.isIntersecting && demo.auto) demo.use(demo.face(), true);
          demo.refresh();
        });
      }, { threshold: 0.05 }).observe(compare);
    } else {
      hero.visible = true;
      if (demo.auto) demo.use(demo.face(), true);
    }
    // o seletor de rostos
    var buttons = pick ? Array.prototype.slice.call(pick.querySelectorAll("button")) : [];
    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        demo.use(parseInt(button.getAttribute("data-face"), 10));
        demo.poke();
      });
    });
    var faces = buttons.map(function (button) { return parseInt(button.getAttribute("data-face"), 10); });
    demo.on(function (what, face) {
      if (what === "ready") demo.warm(faces);        // o primeiro vídeo está tocando: busca os outros
      buttons.forEach(function (button) {
        var mine = parseInt(button.getAttribute("data-face"), 10) === face;
        if (what === "loading") button.classList.toggle("wait", mine);
        else button.classList.remove("wait");
        if (what === "ready") {
          button.classList.toggle("on", mine);
          button.setAttribute("aria-pressed", mine ? "true" : "false");
        }
      });
      if (what === "ready" && after) after.src = "/assets/demo/depois-" + face + ".webp";
    });
    var setCut = function (percent) {
      percent = clamp(percent, 2, 98);
      cut = percent / 100;
      compare.style.setProperty("--cut", percent + "%");
      compare.setAttribute("aria-valuenow", Math.round(percent));
      demo.refresh();
    };
    var fromEvent = function (event) {
      var box = compare.getBoundingClientRect();
      setCut((event.clientX - box.left) / box.width * 100);
    };
    compare.addEventListener("pointerdown", function (event) {
      touched = true;
      compare.setPointerCapture(event.pointerId);
      fromEvent(event);
      if (!reduced) demo.use(demo.face(), true);     // não faz nada se o vídeo já está aí ou a caminho
      demo.poke();
    });
    compare.addEventListener("pointermove", function (event) {
      if (event.buttons || event.pointerType === "touch") fromEvent(event);
    });
    compare.addEventListener("keydown", function (event) {
      var now = parseFloat(compare.getAttribute("aria-valuenow")) || 50;
      if (event.key === "ArrowLeft") { touched = true; setCut(now - 5); }
      if (event.key === "ArrowRight") { touched = true; setCut(now + 5); }
    });
    // Ao abrir, a linha passeia sozinha uma vez para mostrar que dá para arrastar.
    if (!reduced) {
      var start = null;
      var path = [[0, 50], [1200, 50], [2500, 14], [4100, 82], [5200, 44]];
      var tour = function (time) {
        if (touched) return;
        if (start === null) start = time;
        var t = time - start, i = 0;
        while (i < path.length - 2 && t > path[i + 1][0]) i++;
        var a = path[i], b = path[i + 1];
        setCut(a[1] + (b[1] - a[1]) * smooth(clamp((t - a[0]) / (b[0] - a[0]), 0, 1)));
        if (t < path[path.length - 1][0]) requestAnimationFrame(tour);
      };
      requestAnimationFrame(tour);
    } else {
      setCut(44);
    }
  }

  // ---- os quatro passos, na maquete da janela do app e na chamada --------------------------------
  // Estados do app: 0 nada escolhido; 1 rosto escolhido; 2 câmera escolhida (a prévia aparece);
  // 3 no ar (o palco mostra a troca). O passo 4 acontece numa chamada: uma janela do Meet sobe
  // por cima do app (data-call: "webcam", "menu", "switch" e "morpho") e a câmera é trocada lá.
  // Sem animação, a maquete fica parada no estado 3, sem a chamada.
  // As duas janelas são filmadas por uma "câmera": o conteúdo é aproximado e deslocado dentro da
  // lente para mostrar de perto o que importa em cada passo, com desfoque na direção do movimento.
  // (num escopo próprio: são muitos nomes, e nenhum pode trombar com os do resto da página)
  (function () {
    var mock = $("mock");
    if (!mock) return;
    var live = $("mock-live"), cam = $("mock-cam"), pointer = $("mock-cursor"), ping = $("mock-ping");
    var livePen = live.getContext("2d"), camPen = cam.getContext("2d");
    var thumbs = Array.prototype.slice.call($("mock-faces").querySelectorAll("[data-face]"));
    var select = $("mock-select"), go = $("mock-button"), mockAfter = $("mock-after"), statusLine = $("mock-status");
    var faceCard = $("mock-faces").parentNode, cameraCard = select.parentNode.parentNode, foot = go.parentNode;
    var blurNode = $("mock-blur-node");
    var callLive = $("meet-live"), callPen = callLive ? callLive.getContext("2d") : null;
    var callCaret = $("meet-caret"), callMenu = $("meet-menu"), callOption = $("meet-morpho"), callTile = $("meet-tile");
    // cada janela tem a sua lente e o seu conteúdo; a câmera trabalha sobre a que for pedida
    var APP = { lens: $("mock-lens"), body: $("mock-body"), view: { x: 0, y: 0, z: 1 }, shot: 0 };
    var CALL = { lens: $("meet-lens"), body: $("meet-body"), view: { x: 0, y: 0, z: 1 }, shot: 0 };
    // a frase embaixo do botão, como no app
    var STATUS = ["Escolha uma foto de rosto para começar.", "Escolha a câmera.", "Tudo pronto.", "Ao vivo · 30 quadros por segundo."];
    var stepList = $("steps") ? $("steps").children : [];
    var state = 3, call = "", waits = [], running = false;
    var wait = function (fn, ms) { waits.push(setTimeout(fn, ms)); };
    // preenche a tela com a metade pedida do arquivo (0 = original, 1 = troca), recortando as sobras
    var cover = function (context, target, video, half) {
      var w = target.width, h = target.height, sw = demo.WIDE, sh = sw * h / w, room = demo.HALF - 2;
      if (sh > room) { sh = room; sw = sh * w / h; }
      context.drawImage(video, (demo.WIDE - sw) / 2, half * demo.HALF + 1 + (room - sh) / 2, sw, sh, 0, 0, w, h);
    };
    var window3 = demo.view({
      visible: false,
      host: live.parentNode,
      draw: function (video) {
        if (state >= 2) { cover(camPen, cam, video, 0); cam.classList.add("on"); }
        if (state >= 3) { cover(livePen, live, video, 1); live.classList.add("on"); }
        // na chamada: a webcam como ela é, até a "Morpho Camera" ser escolhida
        if (call && callPen) { cover(callPen, callLive, video, call === "morpho" ? 1 : 0); callLive.classList.add("on"); }
      }
    });
    // os passos escritos em cima da maquete: qual está em curso e quantos já foram
    var marks = function (now, done) {
      for (var i = 0; i < stepList.length; i++) {
        stepList[i].classList.toggle("now", i === now);
        stepList[i].classList.toggle("done", i < done);
      }
    };
    var show = function (next, animated) {
      state = next;
      mock.setAttribute("data-state", next);
      if (statusLine) statusLine.textContent = STATUS[next];
      thumbs.forEach(function (thumb) {
        thumb.classList.toggle("on", next >= 1 && parseInt(thumb.getAttribute("data-face"), 10) === demo.face());
      });
      if (animated) marks(next, next); else marks(-1, 0);
      if (next < 2) cam.classList.remove("on");
      if (next < 3) live.classList.remove("on");
      demo.refresh();
    };
    // a chamada: "" fecha a janela do Meet
    var ring = function (next) {
      call = next;
      if (next) mock.setAttribute("data-call", next); else mock.removeAttribute("data-call");
      if (!next && callLive) callLive.classList.remove("on");
      demo.refresh();
    };

    // -- a câmera -------------------------------------------------------------------------------
    var FULL = { x: 0, y: 0, z: 1 };
    var place = function (rig, c) {
      rig.body.style.transform = "translate(" + c.x.toFixed(2) + "px," + c.y.toFixed(2) + "px) scale(" + c.z.toFixed(4) + ")";
    };
    // onde a peça está dentro do conteúdo, sem contar aproximação nenhuma
    var spot = function (rig, el) {
      var x = 0, y = 0, node = el;
      while (node && node !== rig.body) { x += node.offsetLeft; y += node.offsetTop; node = node.offsetParent; }
      return { x: x, y: y, w: el.offsetWidth, h: el.offsetHeight };
    };
    // onde a lente fica dentro da moldura da maquete (é nas medidas dela que o cursor anda)
    var origin = function (rig) {
      var x = 0, y = 0, node = rig.lens;
      while (node && node !== mock) { x += node.offsetLeft; y += node.offsetTop; node = node.offsetParent; }
      return { x: x, y: y };
    };
    // a câmera que põe a peça no centro, ocupando `fill` da lente (sem mostrar nada fora da janela)
    var frameOn = function (rig, el, fill, most, least) {
      var W = rig.body.offsetWidth, H = rig.body.offsetHeight, b = spot(rig, el);
      var z = clamp(fill * Math.min(W / b.w, H / b.h), least || 1, most);
      return {
        x: clamp(W / 2 - (b.x + b.w / 2) * z, W - W * z, 0),
        y: clamp(H / 2 - (b.y + b.h / 2) * z, H - H * z, 0),
        z: z
      };
    };
    // um ponto da peça, visto pela câmera `c`, nas medidas da moldura (é onde o cursor vai)
    var seen = function (rig, el, c, fx, fy) {
      var b = spot(rig, el), o = origin(rig);
      return { x: o.x + (b.x + b.w * fx) * c.z + c.x, y: o.y + (b.y + b.h * fy) * c.z + c.y };
    };
    var swing = function (t) { return t < 0.5 ? 16 * t * t * t * t * t : 1 - Math.pow(-2 * t + 2, 5) / 2; };
    // leva a câmera até `to`. Nos movimentos rápidos a imagem borra na direção em que anda,
    // tanto quanto a velocidade do quadro; nos lentos (`calm`) não há desfoque.
    var fly = function (rig, to, ms, calm) {
      var from = { x: rig.view.x, y: rig.view.y, z: rig.view.z }, mine = ++rig.shot, began = null, last = from, before = null;
      var body = rig.body;
      if (!calm && blurNode) body.style.filter = "url(#mock-blur)";
      var step = function (time) {
        if (mine !== rig.shot) return;
        if (began === null) { began = time; before = time; }
        var t = clamp((time - began) / ms, 0, 1), k = calm ? smooth(t) : swing(t);
        var now = { x: from.x + (to.x - from.x) * k, y: from.y + (to.y - from.y) * k, z: from.z + (to.z - from.z) * k };
        place(rig, now);
        rig.view = now;
        if (!calm && blurNode) {
          var frames = Math.max(0.25, (time - before) / 16.7);          // quantos quadros de 60 Hz se passaram
          var grow = Math.abs(now.z - last.z);
          var bx = (Math.abs(now.x - last.x) * 0.5 + grow * body.offsetWidth * 0.06) / frames / now.z;
          var by = (Math.abs(now.y - last.y) * 0.5 + grow * body.offsetHeight * 0.06) / frames / now.z;
          blurNode.setAttribute("stdDeviation", Math.min(26, bx).toFixed(1) + " " + Math.min(26, by).toFixed(1));
        }
        last = now;
        before = time;
        if (t < 1) { requestAnimationFrame(step); return; }
        body.style.filter = "";
        if (blurNode) blurNode.setAttribute("stdDeviation", "0 0");
      };
      requestAnimationFrame(step);
    };
    var wide = function (rig) {          // volta ao plano geral sem movimento
      rig.shot++;
      rig.view = { x: 0, y: 0, z: 1 };
      place(rig, rig.view);
      rig.body.style.filter = "";
      if (blurNode) blurNode.setAttribute("stdDeviation", "0 0");
    };
    var aim = function (at) { pointer.style.transform = "translate(" + at.x.toFixed(1) + "px," + at.y.toFixed(1) + "px)"; };
    var press = function (el, at) {
      pointer.classList.remove("tap");
      void pointer.offsetWidth;
      pointer.classList.add("tap");
      if (ping) {
        ping.style.transform = "translate(" + at.x.toFixed(1) + "px," + at.y.toFixed(1) + "px)";
        ping.classList.remove("go");
        void ping.offsetWidth;
        ping.classList.add("go");
      }
      el.classList.add("press");
      wait(function () { el.classList.remove("press"); }, 240);
    };
    // um passo no app: a câmera vai até `area`, o cursor chega em `el`, clica, e a tela muda de estado
    var beat = function (at, area, el, next, fx) {
      var narrow = APP.body.offsetWidth < 560;
      // em tela estreita o cartão já ocupa a largura toda: a câmera só encosta, sem cortar nada
      var to = frameOn(APP, area, narrow ? 0.98 : 0.82, narrow ? 1.45 : 2.15, narrow ? 1 : 1.5), target = seen(APP, el, to, fx, 0.6);
      wait(function () { fly(APP, to, 780); aim(target); }, at);
      wait(function () { press(el, target); show(next, true); }, at + 1000);
    };
    // o passo 4, na chamada: a janela do Meet sobe com a webcam, a câmera chega perto do menu de
    // câmeras, o cursor escolhe a "Morpho Camera" e o plano abre para mostrar o rosto trocado
    var dial = function (at) {
      var near = FULL, caret, option;
      wait(function () { ring("webcam"); }, at);
      wait(function () {
        var narrow = CALL.body.offsetWidth < 560;
        near = frameOn(CALL, callMenu, narrow ? 0.72 : 0.42, narrow ? 1.5 : 2.1, narrow ? 1.1 : 1.3);
        caret = seen(CALL, callCaret, near, 0.5, 0.55);
        pointer.style.opacity = "1";
        aim({ x: caret.x + mock.offsetWidth * 0.12, y: caret.y - mock.offsetHeight * 0.2 });
      }, at + 900);
      wait(function () { fly(CALL, near, 820); aim(caret); }, at + 1300);
      wait(function () { press(callCaret, caret); ring("menu"); }, at + 2350);
      wait(function () { option = seen(CALL, callOption, near, 0.32, 0.55); aim(option); }, at + 2950);
      wait(function () { press(callOption, option); ring("switch"); }, at + 3900);
      wait(function () { ring("morpho"); marks(-1, stepList.length); pointer.style.opacity = "0"; }, at + 4550);
      wait(function () { fly(CALL, FULL, 950); }, at + 5050);
      wait(function () {                                  // e chega um pouco mais perto, devagar, sem perder os botões de vista
        var z = 1.035;
        fly(CALL, { x: -CALL.body.offsetWidth * (z - 1) / 2, y: 0, z: z }, 4300, true);
      }, at + 6100);
    };
    var act = function () {
      var thumb = thumbs[demo.face() - 1] || thumbs[0];
      wide(APP);
      ring("");
      wait(function () { wide(CALL); }, 1000);            // só depois de a janela da chamada descer
      show(0, true);
      pointer.style.opacity = "1";
      aim({ x: mock.offsetWidth * 0.5, y: mock.offsetHeight * 0.62 });
      beat(700, faceCard, thumb, 1, 0.5);                 // 1. o rosto
      beat(2500, cameraCard, select, 2, 0.4);             // 2. a câmera (a prévia aparece)
      beat(4700, foot, go, 3, 0.5);                       // 3. o botão
      wait(function () { pointer.style.opacity = "0"; }, 6000);
      wait(function () { fly(APP, FULL, 900); }, 6150);   // abre o plano: a troca no palco
      wait(function () { fly(APP, frameOn(APP, live.parentNode, 1.06, 1.22, 1.08), 3200, true); }, 7250);   // e chega perto, devagar
      if (callPen) { dial(9900); wait(act, 20600); }      // 4. a chamada
      else wait(act, 13900);
    };
    demo.on(function (what, face) {
      if (what !== "ready") return;
      if (mockAfter) mockAfter.src = "/assets/demo/depois-" + face + ".webp";
      if ($("meet-after")) $("meet-after").src = "/assets/demo/depois-" + face + ".webp";
      thumbs.forEach(function (thumb) {
        thumb.classList.toggle("on", state >= 1 && parseInt(thumb.getAttribute("data-face"), 10) === face);
      });
    });
    pointer.style.opacity = "0";
    show(3, false);
    if (!reduced && "IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          window3.visible = entry.isIntersecting;
          if (entry.isIntersecting && !running) {
            running = true;
            if (demo.auto) demo.use(demo.face(), true);
            act();
          } else if (!entry.isIntersecting && running) {
            running = false;
            waits.forEach(clearTimeout);
            waits = [];
            wide(APP);
            wide(CALL);
            ring("");
            pointer.style.opacity = "0";
          }
          demo.refresh();
        });
      }, { threshold: 0.3 }).observe(mock);
      window.addEventListener("resize", function () { if (!running) { wide(APP); wide(CALL); } });
    }
  })();

  // ---- o diagnóstico rodando --------------------------------------------------------------------
  // A página já traz o resultado final. A animação apaga tudo e confere item por item, com a nota
  // subindo junto, como o programa faz. Com "reduzir movimento" fica o resultado, parado.
  (function () {
    var box = $("diag");
    if (!box || reduced || !("IntersectionObserver" in window)) return;
    var rows = Array.prototype.slice.call($("diag-list").children);
    var arc = $("diag-arc"), num = $("diag-num"), verdict = $("diag-verdict"), detail = $("diag-detail");
    var SCORE = parseInt(num.textContent, 10), FINAL = [verdict.textContent, detail.textContent];
    var timers = [], playing = false, shown = SCORE, counting = 0;
    var later = function (fn, ms) { timers.push(setTimeout(fn, ms)); };
    // o anel anda pelo CSS; o número conta até o mesmo valor
    var score = function (value) {
      var from = shown, began = null;
      arc.style.strokeDashoffset = 100 - value;
      cancelAnimationFrame(counting);
      var step = function (time) {
        if (began === null) began = time;
        var t = clamp((time - began) / 380, 0, 1);
        shown = Math.round(from + (value - from) * smooth(t));
        num.textContent = shown;
        if (t < 1) counting = requestAnimationFrame(step);
      };
      counting = requestAnimationFrame(step);
    };
    var settle = function () {           // o resultado final, como veio na página
      cancelAnimationFrame(counting);
      box.classList.remove("run");
      rows.forEach(function (row) { row.className = ""; });
      verdict.textContent = FINAL[0];
      detail.textContent = FINAL[1];
      shown = SCORE;
      num.textContent = SCORE;
      arc.style.strokeDashoffset = "";
    };
    var play = function () {
      cancelAnimationFrame(counting);
      box.classList.remove("done");
      box.classList.add("run");
      rows.forEach(function (row) { row.className = "wait"; });
      verdict.textContent = "Conferindo o seu computador…";
      detail.textContent = "Leva só alguns segundos.";
      shown = 0;
      num.textContent = "0";
      arc.style.strokeDashoffset = 100;
      rows.forEach(function (row, i) {
        later(function () { row.className = "busy"; }, 800 + i * 540);
        later(function () { row.className = "ok"; score(Math.round(SCORE * (i + 1) / rows.length)); }, 800 + i * 540 + 400);
      });
      var end = 800 + rows.length * 540 + 250;
      later(function () {
        box.classList.remove("run");
        box.classList.add("done");
        verdict.textContent = FINAL[0];
        detail.textContent = FINAL[1];
      }, end);
      later(play, end + 5400);
    };
    new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !playing) { playing = true; play(); }
        else if (!entry.isIntersecting && playing) {
          playing = false;
          timers.forEach(clearTimeout);
          timers = [];
          settle();
        }
      });
    }, { threshold: 0.35 }).observe(box);
  })();

  // ---- animação do aviso do Windows ------------------------------------------------------------
  var stage = $("ss");
  if (stage) {
    var cursor = $("ss-cursor"), more = $("ss-more"), run = $("ss-run");
    var steps = $("ss-steps") ? $("ss-steps").children : [];
    var timers = [], playing = false;
    var later = function (fn, ms) { timers.push(setTimeout(fn, ms)); };
    var mark = function (step) {
      stage.setAttribute("data-step", step);
      for (var i = 0; i < steps.length; i++) {
        steps[i].classList.toggle("now", i === step);
        steps[i].classList.toggle("done", i < step);
      }
    };
    var moveTo = function (el) {
      var box = stage.getBoundingClientRect(), target = el.getBoundingClientRect();
      var x = target.left - box.left + Math.min(target.width * 0.5, 60);
      var y = target.top - box.top + target.height * 0.55;
      cursor.style.transform = "translate(" + x + "px," + y + "px)";
    };
    var park = function () {
      cursor.style.transform = "translate(" + stage.clientWidth * 0.8 + "px," + stage.clientHeight * 0.18 + "px)";
    };
    var tap = function (el) {
      cursor.classList.remove("tap");
      void cursor.offsetWidth;
      cursor.classList.add("tap");
      el.classList.add("ss-press");
      later(function () { el.classList.remove("ss-press"); }, 260);
    };
    var play = function () {
      mark(0);
      cursor.style.opacity = "1";
      park();
      later(function () { moveTo(more); }, 900);
      later(function () { tap(more); }, 1950);
      later(function () { mark(1); }, 2250);
      later(function () { moveTo(run); }, 2900);
      later(function () { tap(run); }, 3950);
      later(function () { mark(2); cursor.style.opacity = "0"; }, 4300);
      later(play, 7600);
    };
    if (reduced) {
      mark(1);
      cursor.style.display = "none";
    } else if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting && !playing) { playing = true; play(); }
          else if (!entry.isIntersecting && playing) {
            playing = false;
            timers.forEach(clearTimeout);
            timers = [];
          }
        });
      }, { threshold: 0.35 }).observe(stage);
    } else {
      play();
    }
  }

  // ---- quem não está no Windows ------------------------------------------------------------------
  // O aviso embaixo do botão já diz que é só para NVIDIA; aqui ele se ajusta a quem abre a
  // página fora do Windows, e o download pede confirmação.
  var fine = $("fine");
  var isWindows = /Windows/i.test(navigator.userAgent) && !/Windows Phone/i.test(navigator.userAgent);
  var mobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  if (!isWindows) {
    if (fine) {
      fine.textContent = mobile
        ? "Exclusivo para computador com Windows e placa NVIDIA. Abra esta página no seu PC para baixar."
        : "Exclusivo para Windows com placa NVIDIA. O instalador verifica a compatibilidade antes de baixar o programa.";
    }
    document.querySelectorAll("[data-download]").forEach(function (button) {
      button.addEventListener("click", function (event) {
        if (!confirm("O Morpho só funciona no Windows. Baixar mesmo assim?")) event.preventDefault();
      });
    });
  }

  // ---- arquivos do instalador ----------------------------------------------------------------------
  var list = $("files"), manualText = $("manual-text");
  function size(bytes) {
    return bytes >= 1073741824 ? (bytes / 1073741824).toFixed(1).replace(".", ",") + " GB"
      : Math.round(bytes / 1048576) + " MB";
  }
  if (list) {
    fetch("/download.json", { cache: "no-store" }).then(function (response) { return response.json(); }).then(function (data) {
      var files = (data && data.files) || [];
      if (!files.length) throw new Error("vazio");
      if (data.source && $("source")) { $("source").href = data.source; $("source").hidden = false; }
      files.forEach(function (file) {
        var item = document.createElement("li");
        var link = document.createElement("a");
        link.href = file.url;
        link.textContent = file.name;
        var weight = document.createElement("span");
        weight.className = "size";
        weight.textContent = size(file.size);
        var hash = document.createElement("code");
        hash.textContent = "SHA-256: " + file.sha256;
        item.appendChild(link);
        item.appendChild(weight);
        item.appendChild(hash);
        list.appendChild(item);
      });
    }).catch(function () {
      // O instalador ainda não foi publicado: a página diz isso em vez de prometer o download.
      if (manualText) manualText.textContent = "Os arquivos do instalador ainda não foram publicados.";
      if ($("soon")) $("soon").hidden = false;
    });
  }
})();
