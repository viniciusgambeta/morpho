// Morpho — comportamento da página: efeitos de rolagem, comparação antes/depois,
// animação do aviso do Windows, checagem rápida da placa de vídeo e a lista de
// arquivos do instalador.
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

  // ---- número que conta até o valor ---------------------------------------------------------
  var counters = document.querySelectorAll("[data-count]");
  if ("IntersectionObserver" in window && !reduced) {
    var counted = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        counted.unobserve(entry.target);
        var target = parseInt(entry.target.getAttribute("data-count"), 10), start = null;
        var step = function (time) {
          if (start === null) start = time;
          var t = clamp((time - start) / 1300, 0, 1);
          entry.target.textContent = Math.round(target * (1 - Math.pow(1 - t, 3)));
          if (t < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      });
    }, { threshold: 0.6 });
    counters.forEach(function (el) { el.textContent = "0"; counted.observe(el); });
  }

  // ---- antes e depois ------------------------------------------------------------------------
  var compare = $("compare");
  if (compare) {
    var touched = false;
    var setCut = function (percent) {
      percent = clamp(percent, 2, 98);
      compare.style.setProperty("--cut", percent + "%");
      compare.setAttribute("aria-valuenow", Math.round(percent));
    };
    var fromEvent = function (event) {
      var box = compare.getBoundingClientRect();
      setCut((event.clientX - box.left) / box.width * 100);
    };
    compare.addEventListener("pointerdown", function (event) {
      touched = true;
      compare.setPointerCapture(event.pointerId);
      fromEvent(event);
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

  // ---- checagem rápida da placa de vídeo ---------------------------------------------------------
  // O navegador sabe o nome da placa que está desenhando a página. É só uma pista: em
  // notebook com duas placas ele costuma usar a mais fraca. O veredito é do diagnóstico.
  var pill = $("gpu"), pillText = $("gpu-text"), fine = $("fine");
  var isWindows = /Windows/i.test(navigator.userAgent) && !/Windows Phone/i.test(navigator.userAgent);
  var mobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  function say(good, html) {
    if (!pill) return;
    pill.classList.toggle("good", good);
    pillText.innerHTML = html;
  }
  function renderer() {
    try {
      var canvas = document.createElement("canvas");
      var gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
      if (!gl) return "";
      var info = gl.getExtension("WEBGL_debug_renderer_info");
      return String(info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)) || "";
    } catch (error) { return ""; }
  }
  if (!isWindows) {
    say(false, mobile
      ? "Para computador com Windows e placa <b>NVIDIA</b>. Abra esta página no seu PC."
      : "Só para Windows, com placa de vídeo <b>NVIDIA</b>.");
    if (fine) fine.textContent = "Grátis. Disponível para Windows 10 e 11.";
    document.querySelectorAll("[data-download]").forEach(function (button) {
      button.addEventListener("click", function (event) {
        if (!confirm("O Morpho só funciona no Windows. Baixar mesmo assim?")) event.preventDefault();
      });
    });
  } else {
    var name = renderer();
    var model = (name.match(/(GeForce\s+)?((RTX|GTX)\s*(A?\d{3,4})(\s*Ti)?(\s*SUPER)?(\s*Laptop GPU)?)/i) || [])[2];
    if (/NVIDIA/i.test(name) && model) {
      if (/GTX\s*(9|10)\d{2}\b/i.test(model)) say(false, "Este PC tem uma <b>" + model.trim() + "</b>, mais antiga que o recomendado. O diagnóstico diz se dá.");
      else say(true, "Este PC tem uma <b>NVIDIA " + model.trim() + "</b>. Parece compatível.");
    } else if (/NVIDIA/i.test(name)) {
      say(true, "Este PC tem uma placa <b>NVIDIA</b>. O diagnóstico confirma se ela dá conta.");
    } else if (name) {
      say(false, "Requer placa de vídeo <b>NVIDIA</b>. O navegador está usando outra; se o seu PC tiver as duas, o diagnóstico encontra.");
    }
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
