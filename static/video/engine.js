/* Tayyorla video dvigateli.
 *
 * Rejimlar (window.__TV.mode):
 *   live   — Mini App ko'rinishi: aylanib o'ynaydi, ota oynadan postMessage bilan boshqariladi;
 *   render — renderer har bir kadr uchun window.__seek(ms) chaqiradi va skrinshot oladi;
 *   still  — bitta kadr (?t=7000) — dizayn rasmlari uchun.
 * Hamma CSS animatsiyalar pauzada turadi, vaqtni yagona soat beradi — shuning uchun kadrlar har gal bir xil.
 */
(function () {
  'use strict';
  var D = 20000;
  var root = document.documentElement;
  var boot = window.__TV || {};
  var mode = boot.mode || 'live';
  var P = boot.payload || null;
  var T = { t: +(boot.t || 0), playing: false, loop: true, t0: 0, last: 0 };

  // ------------------------------------------------------------ urug'li tasodif
  function rng(seed) {
    return function () {
      seed = seed + 0x6D2B79F5 | 0;
      var t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function hash(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }

  // ------------------------------------------------------------ standart qismlar
  var STD = {
    details:
      '<p class="d-msg a-rise" style="--d:.1s" data-t="message" data-if="message" data-fit="21,13"></p>' +
      '<div class="d-date a-rise" style="--d:.35s"><span class="d-day" data-t="day" data-fit="84,44"></span>' +
      '<span class="d-meta"><span class="d-month" data-t="month"></span><span class="d-wd" data-t="weekday"></span><b class="d-time" data-t="time"></b></span></div>' +
      '<div class="d-place a-rise" style="--d:.6s" data-if="venue"><p class="d-venue" data-t="venue" data-fit="24,14"></p><p class="d-addr" data-t="address" data-if="address"></p></div>' +
      '<div class="d-extra a-rise" style="--d:.8s" data-if="extra"><p data-t="reason" data-if="reason"></p><p data-t="turn" data-if="turn"></p><p data-t="kassa" data-if="kassa"></p></div>' +
      '<div class="d-qr a-rise" style="--d:1s" data-if="qr"><span class="d-qrbox" data-qr></span><span class="d-scan" data-t="scan"></span></div>' +
      '<p class="d-sign a-rise" style="--d:1.25s" data-if="signature"><span data-t="respect"></span>, <b data-t="signature"></b></p>',
    final:
      '<div class="f-photo a-pop" style="--d:.1s" data-if="photo" data-photo></div>' +
      '<p class="f-event a-fade" style="--d:.2s" data-t="event"></p>' +
      '<p class="f-names a-blur" style="--d:.3s" data-t="names_line" data-fit="40,20"></p>' +
      '<p class="f-date a-rise" style="--d:.6s" data-t="date"></p>' +
      '<div class="tv-bank a-rise" style="--d:.9s" data-if="toyona"><p class="b-title" data-t="card_title"></p>' +
      '<div class="b-card"><span class="b-logo"></span><span class="b-chip"></span><span class="b-num" data-t="card_number" data-fit="19,13"></span><span class="b-owner" data-t="card_owner"></span></div></div>' +
      '<p class="f-wait a-rise" style="--d:1.1s" data-t="waiting" data-if="!toyona"></p>',
    brand: '<span class="br-logo">T</span><span><b data-t="brand"></b><small data-t="bot"></small></span>'
  };

  function build() {
    var list = document.querySelectorAll('[data-std]');
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      if (el.getAttribute('data-built')) continue;
      el.innerHTML = STD[el.getAttribute('data-std')] || '';
      el.setAttribute('data-built', '1');
    }
    particles();
  }

  // ------------------------------------------------------------ zarrachalar
  var KINDS = {
    confetti: function (r, i, n) { return { left: (r() * 104 - 2) + '%', delay: r() * 1.6, dur: 2.6 + r() * 1.6, x: (r() - .5) * 120, rot: (r() - .5) * 900 }; },
    petal: function (r) { return { left: (r() * 100) + '%', delay: r() * 5, dur: 5 + r() * 3, x: (r() - .5) * 90, rot: (r() - .5) * 540 }; },
    spark: function (r) { return { left: (r() * 92 + 4) + '%', top: (r() * 92 + 4) + '%', delay: -r() * 2.4, dur: 1.8 + r() * 1.4, size: 4 + r() * 6 }; },
    star: function (r) { return { left: (r() * 100) + '%', top: (r() * 70) + '%', delay: -r() * 3, dur: 2 + r() * 2.5, size: 1.5 + r() * 2.5 }; },
    bokeh: function (r) { return { left: (r() * 100 - 10) + '%', top: (r() * 100) + '%', delay: -r() * 9, dur: 7 + r() * 6, size: 18 + r() * 46, x: (r() - .5) * 60 }; },
    steam: function (r) { return { left: (r() * 60 + 20) + '%', delay: -r() * 3.6, dur: 3 + r() * 1.6, x: (r() - .5) * 40 }; },
    dust: function (r) { return { left: (r() * 100) + '%', top: (60 + r() * 40) + '%', delay: -r() * 7, dur: 5 + r() * 4, x: (r() - .5) * 50 }; }
  };

  function particles() {
    var boxes = document.querySelectorAll('[data-particles]');
    for (var b = 0; b < boxes.length; b++) {
      var box = boxes[b];
      if (box.getAttribute('data-built')) continue;
      var kind = box.getAttribute('data-particles');
      var n = +box.getAttribute('data-n') || 40;
      var colors = (box.getAttribute('data-colors') || 'var(--accent),var(--accent2),var(--gold)').split(',');
      var at = parseFloat(box.getAttribute('data-at') || '0');
      var r = rng(hash(kind + n + (box.id || '') + b));
      var gen = KINDS[kind];
      if (!gen) continue;
      var html = '';
      for (var i = 0; i < n; i++) {
        var p = gen(r, i, n);
        var st = 'left:' + p.left + ';';
        if (p.top) st += 'top:' + p.top + ';';
        if (p.size) st += 'width:' + p.size.toFixed(1) + 'px;height:' + p.size.toFixed(1) + 'px;';
        if (p.x != null) st += '--x:' + p.x.toFixed(1) + 'px;';
        if (p.rot != null) st += '--r:' + p.rot.toFixed(0) + 'deg;';
        st += 'background:' + colors[i % colors.length] + ';';
        st += 'animation-duration:' + p.dur.toFixed(2) + 's;animation-delay:' + (at + p.delay).toFixed(2) + 's;';
        html += '<i class="p-' + kind + '" style="' + st + '"></i>';
      }
      box.innerHTML = html;
      box.setAttribute('data-built', '1');
    }
  }

  // ------------------------------------------------------------ ma'lumotni joylash
  var SAFE_PATH = /^[MmHhVvZz0-9 .\-]*$/;

  function apply(p) {
    if (p) P = p;
    if (!P) return;
    var t = P.t || {}, f = P.f || {}, i, el;
    if (P.vars) for (var k in P.vars) if (/^--[\w-]+$/.test(k)) root.style.setProperty(k, String(P.vars[k]).replace(/[;{}<>]/g, ''));
    root.lang = P.html_lang || 'uz';
    var txt = document.querySelectorAll('[data-t]');
    for (i = 0; i < txt.length; i++) { el = txt[i]; var v = t[el.getAttribute('data-t')]; el.textContent = v == null ? '' : String(v); }
    var cond = document.querySelectorAll('[data-if]');
    for (i = 0; i < cond.length; i++) {
      el = cond[i];
      var ok = el.getAttribute('data-if').split(' ').every(function (key) { return key.charAt(0) === '!' ? !f[key.slice(1)] : !!f[key]; });
      el.style.display = ok ? '' : 'none';
    }
    var qrs = document.querySelectorAll('[data-qr]');
    for (i = 0; i < qrs.length; i++) {
      var q = P.qr;
      qrs[i].innerHTML = q && SAFE_PATH.test(q.d) && +q.n ? '<svg viewBox="0 0 ' + (+q.n) + ' ' + (+q.n) + '" shape-rendering="crispEdges" aria-hidden="true"><path d="' + q.d + '"/></svg>' : '';
    }
    var ph = document.querySelectorAll('[data-photo]');
    for (i = 0; i < ph.length; i++) ph[i].style.backgroundImage = P.photo ? 'url("' + String(P.photo).replace(/["\\()\s]/g, '') + '")' : '';
    fitAll();
  }

  // Matnni ramkaga sig'diradi: data-fit="eng katta,eng kichik" (px)
  function fit(el) {
    if (!el.offsetParent && el.style.display === 'none') return;
    var spec = (el.getAttribute('data-fit') || '').split(',');
    var size = +spec[0] || 40, min = +spec[1] || 10;
    // bir qatorli matn eni bo'yicha, ko'p qatorli matn balandligi bo'yicha sig'diriladi
    var line = getComputedStyle(el).whiteSpace === 'nowrap';
    var over = function () { return line ? el.scrollWidth > el.clientWidth + 1 : el.scrollHeight > el.clientHeight + 1; };
    el.style.fontSize = size + 'px';
    var guard = 80;
    while (guard-- > 0 && size > min && over()) {
      size -= 1;
      el.style.fontSize = size + 'px';
    }
  }
  function fitAll() { var list = document.querySelectorAll('[data-fit]'); for (var i = 0; i < list.length; i++) fit(list[i]); }

  // ------------------------------------------------------------ soat
  function seek(ms) {
    T.t = Math.max(0, Math.min(D, +ms || 0));
    var list = document.getAnimations();
    for (var i = 0; i < list.length; i++) {
      var a = list[i];
      try { if (a.playState !== 'paused') a.pause(); a.currentTime = T.t; } catch (e) { /* tugagan animatsiya */ }
    }
  }
  function tick(now) {
    if (!T.playing) return;
    var t = now - T.t0;
    if (t >= D) {
      if (T.loop) { T.t0 = now - (t % D); t = t % D; } else { t = D; T.playing = false; }
    }
    seek(t);
    post(false);
    requestAnimationFrame(tick);
  }
  function play() { if (T.playing) return; if (T.t >= D - 50) T.t = 0; T.playing = true; T.t0 = performance.now() - T.t; requestAnimationFrame(tick); post(true); }
  function pause() { T.playing = false; post(true); }

  function post(force) {
    if (window.parent === window) return;
    var now = Date.now();
    if (!force && now - T.last < 120) return;
    T.last = now;
    window.parent.postMessage({ type: 'tv:time', t: Math.round(T.t), playing: T.playing, d: D }, '*');
  }

  window.addEventListener('message', function (e) {
    if (e.source !== window.parent) return;
    var m = e.data || {};
    if (m.type === 'tv:payload') { apply(m.payload); seek(T.t); }
    else if (m.type === 'tv:play') play();
    else if (m.type === 'tv:pause') pause();
    else if (m.type === 'tv:seek') { seek(m.ms); post(true); }
    else if (m.type === 'tv:loop') T.loop = !!m.on;
  });

  function imagesReady() {
    var urls = [];
    var ph = document.querySelectorAll('[data-photo]');
    for (var i = 0; i < ph.length; i++) if (ph[i].style.display !== 'none' && P && P.photo) urls.push(P.photo);
    var imgs = document.images;
    var waits = [];
    for (var j = 0; j < imgs.length; j++) if (!imgs[j].complete) waits.push(new Promise(function (res) { imgs[j].onload = imgs[j].onerror = res; }));
    urls.forEach(function (u) { waits.push(new Promise(function (res) { var im = new Image(); im.onload = im.onerror = res; im.src = u; })); });
    return Promise.all(waits);
  }

  window.TV = { seek: seek, play: play, pause: pause, apply: apply, fit: fitAll, D: D, state: T };
  window.__seek = function (ms) { seek(ms); return T.t; };
  window.__ready = false;

  build();
  apply();
  seek(T.t);
  var fontsReady = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
  Promise.all([fontsReady, imagesReady()]).then(function () {
    fitAll();
    seek(T.t);
    window.__ready = true;
    if (window.parent !== window) window.parent.postMessage({ type: 'tv:ready', d: D }, '*');
    if (mode === 'live' && boot.autoplay !== false) play();
  });
})();
