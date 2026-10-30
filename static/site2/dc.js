/* Tayyorla v2 sayt dvigateli.
   Dizayn kanvasidagi .dc.html shablonini (<sc-for>, <sc-if>, {{ teshik }}, DCLogic) Preact orqali jonlantiradi.
   Mijoz ma'lumoti shablonga SITE obyekti orqali yetadi: d (maydonlar), p (suratlar), b (ko'rinadigan bloklar), has. */
(function () {
  "use strict";
  var P = window.preact, h = P.h;
  var CFG = JSON.parse(document.getElementById("site-config").textContent || "{}");
  var DW = 390, IH = 844; // dizayn kengligi va kirish sahnasining balandligi

  // ---------------------------------------------------------------- sana va vaqt (Toshkent, UTC+5)
  var OY = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"];
  var HAFTA = ["yakshanba", "dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba"];
  var pad = function (n) { return (n < 10 ? "0" : "") + n; };
  var cap = function (s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; };

  function moment(iso, time) {
    if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return null;
    var t = /^\d{1,2}:\d{2}$/.test(time || "") ? (time.length === 4 ? "0" + time : time) : "00:00";
    var d = new Date(iso.slice(0, 10) + "T" + t + ":00+05:00");
    return isNaN(d) ? null : d;
  }

  /** Sana bo'laklari: {day, month, monthNum, year, weekday, Weekday, date, dm, dots, time} */
  function when(iso, time) {
    var d = moment(iso, time);
    if (!d) return { day: "", month: "", monthNum: "", year: "", weekday: "", Weekday: "", date: "", dm: "", dots: "", time: time || "" };
    var t = new Date(d.getTime() + 5 * 3600e3);
    var day = t.getUTCDate(), m = t.getUTCMonth(), y = t.getUTCFullYear(), w = HAFTA[t.getUTCDay()];
    return {
      day: String(day), month: OY[m], monthNum: pad(m + 1), year: String(y), weekday: w, Weekday: cap(w),
      date: day + "-" + OY[m] + " " + y, dm: day + "-" + OY[m], dots: pad(day) + "." + pad(m + 1) + "." + y,
      time: time || "",
    };
  }

  /** Belgilangan vaqtgacha qolgan vaqt: {d, h, m, s, dd, hh, mm, ss, done} */
  function countdown(iso, time) {
    var d = moment(iso, time), ms = d ? Math.max(0, d.getTime() - Date.now()) : 0;
    var s = Math.floor(ms / 1000), o = { d: Math.floor(s / 86400), h: Math.floor(s / 3600) % 24, m: Math.floor(s / 60) % 60, s: s % 60, done: !!d && ms === 0, none: !d };
    o.dd = pad(o.d); o.hh = pad(o.h); o.mm = pad(o.m); o.ss = pad(o.s);
    return o;
  }

  /** Belgilangan kundan beri o'tgan vaqt: {days, years, months, rest, h, m, s, total} */
  function elapsed(iso, time) {
    var d = moment(iso, time);
    if (!d) return { days: 0, years: 0, months: 0, rest: 0, h: 0, m: 0, s: 0, none: true };
    var now = new Date(), ms = Math.max(0, now.getTime() - d.getTime()), s = Math.floor(ms / 1000);
    var a = new Date(d.getTime() + 5 * 3600e3), b = new Date(now.getTime() + 5 * 3600e3);
    var months = (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + b.getUTCMonth() - a.getUTCMonth();
    if (b.getUTCDate() < a.getUTCDate()) months--;
    months = Math.max(0, months);
    var anchor = new Date(Date.UTC(a.getUTCFullYear(), a.getUTCMonth() + months, a.getUTCDate()));
    var rest = Math.max(0, Math.floor((Date.UTC(b.getUTCFullYear(), b.getUTCMonth(), b.getUTCDate()) - anchor.getTime()) / 86400e3));
    return { days: Math.floor(s / 86400), years: Math.floor(months / 12), months: months % 12, rest: rest,
      h: Math.floor(s / 3600) % 24, m: Math.floor(s / 60) % 60, s: s % 60, totalMonths: months };
  }

  var num = function (n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " "); };

  // ---------------------------------------------------------------- javoblar
  function post(url, body) {
    if (!url || CFG.demo || CFG.preview) return new Promise(function (ok) { setTimeout(function () { ok({ ok: true }); }, 350); });
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.json(); });
  }
  var U = CFG.urls || {};

  // ---------------------------------------------------------------- musiqa
  var audio = null, inst = null;
  var music = {
    has: !!CFG.music, playing: false,
    play: function () {
      if (!CFG.music) return;
      if (!audio) {
        audio = new Audio(CFG.music); audio.loop = true;
        audio.addEventListener("play", function () { music.playing = true; refresh(); });
        audio.addEventListener("pause", function () { music.playing = false; refresh(); });
      }
      var p = audio.play(); if (p && p.catch) p.catch(function () {});
    },
    pause: function () { if (audio) audio.pause(); },
    toggle: function () { music.playing ? music.pause() : music.play(); },
  };
  function refresh() { if (inst) inst.forceUpdate(); }

  // ---------------------------------------------------------------- SITE
  var photos = (CFG.photos || []).filter(Boolean);
  var slots = Math.max(CFG.slots || 0, photos.length, 1), ph = [];
  for (var i = 0; i < slots; i++) ph.push(photos.length ? photos[i % photos.length] : "/static/site2/ph.svg");
  var guest = CFG.guest || null;

  var SITE = window.SITE = {
    d: CFG.data || {}, p: ph, b: CFG.b || {}, tier: CFG.tarif, demo: !!CFG.demo, preview: !!CFG.preview,
    has: { photo: photos.length > 0, photos: photos.length, music: !!CFG.music, guest: !!guest },
    guest: guest ? guest.n : "",
    when: when, countdown: countdown, elapsed: elapsed, num: num, pad: pad, cap: cap,
    music: music, refresh: refresh,
    /** Egasiga javob (Kechirdim, Tabrikladim, «Ha»…) — bot orqali yetadi. */
    reply: function (message, emoji) { return post(U.react, { emoji: emoji || "❤️", message: String(message || "").slice(0, 300) }); },
    /** To'y va bazmga javob: keladi/kelmaydi, necha kishi, ism, izoh. */
    rsvp: function (going, guests, name, note) {
      return post(U.rsvp, { attending: going ? "yes" : "no", guests: Math.max(1, Math.min(20, +guests || 1)),
        name: String(name || (guest && guest.n) || "").slice(0, 100), note: String(note || "").slice(0, 300), g: guest ? guest.t : null });
    },
    opened: function () { introDone(); },
    /** Jo'nalish qo'shimchasi: Bek → Bekka, Dilnoza → Dilnozaga */
    ga: function (name) { name = String(name || "").trim(); if (!name) return ""; var l = name.slice(-1).toLowerCase(); return name + (l === "k" ? "ka" : l === "q" ? "qa" : "ga"); },
  };

  // ---------------------------------------------------------------- shablon kompilyatori
  var HOLE = /\{\{\s*([^{}]*?)\s*\}\}/g;
  var BOOL = { checked: 1, disabled: 1, selected: 1, hidden: 1, required: 1, readonly: 1, multiple: 1, autofocus: 1, open: 1, novalidate: 1, playsinline: 1, muted: 1, autoplay: 1, loop: 1, controls: 1 };

  function lookup(path, scope) {
    if (path === "true") return true;
    if (path === "false") return false;
    if (path === "null" || path === "") return null;
    if (/^-?\d+(\.\d+)?$/.test(path)) return +path;
    var q = path.charAt(0);
    if ((q === "'" || q === '"') && path.charAt(path.length - 1) === q) return path.slice(1, -1);
    var segs = path.split("."), v = scope;
    for (var i = 0; i < segs.length; i++) { if (v == null) return undefined; v = v[segs[i]]; }
    return v;
  }
  function parts(str) {
    if (str.indexOf("{{") < 0) return null;
    var out = [], last = 0, m;
    HOLE.lastIndex = 0;
    while ((m = HOLE.exec(str))) { if (m.index > last) out.push(str.slice(last, m.index)); out.push({ p: m[1] }); last = HOLE.lastIndex; }
    if (last < str.length) out.push(str.slice(last));
    if (out.length === 1 && typeof out[0] === "object") return { whole: out[0].p };
    return out;
  }
  function interp(ps, scope) {
    if (ps.whole != null) return lookup(ps.whole, scope);
    var s = "";
    for (var i = 0; i < ps.length; i++) { var x = ps[i]; if (typeof x === "string") s += x; else { var v = lookup(x.p, scope); s += v == null ? "" : v; } }
    return s;
  }
  function textOf(ps, scope) { var v = interp(ps, scope); return v == null || v === false ? "" : String(v); }

  function compileList(nodes) {
    var fns = [];
    for (var i = 0; i < nodes.length; i++) { var f = compile(nodes[i]); if (f) fns.push(f); }
    return function (scope) {
      var out = [];
      for (var i = 0; i < fns.length; i++) {
        var r = fns[i](scope);
        if (r == null || r === false) continue;
        if (Array.isArray(r)) { for (var j = 0; j < r.length; j++) out.push(r[j]); } else out.push(r);
      }
      return out;
    };
  }

  function compile(node) {
    if (node.nodeType === 3) {
      var t = node.nodeValue, ps = parts(t);
      return ps ? function (scope) { return textOf(ps, scope); } : function () { return t; };
    }
    if (node.nodeType !== 1) return null;
    var tag = node.localName;
    if (tag === "helmet") return null;
    if (tag === "sc-if") {
      var cond = parts(node.getAttribute("value") || "") || { whole: (node.getAttribute("value") || "").trim() };
      var body = compileList(node.childNodes);
      return function (scope) { return interp(cond, scope) ? body(scope) : null; };
    }
    if (tag === "sc-for") {
      var lp = parts(node.getAttribute("list") || "") || { whole: "" }, as = node.getAttribute("as") || "item";
      var each = compileList(node.childNodes);
      return function (scope) {
        var arr = interp(lp, scope), out = [];
        if (!arr || !arr.length) return null;
        for (var i = 0; i < arr.length; i++) {
          var s = Object.create(scope); s[as] = arr[i]; s.$index = i;
          var r = each(s);
          for (var j = 0; j < r.length; j++) out.push(r[j]);
        }
        return out;
      };
    }
    var attrs = [];
    for (var i = 0; i < node.attributes.length; i++) {
      var a = node.attributes[i], name = a.name;
      if (name.indexOf("hint-") === 0) continue;
      var ps = parts(a.value);
      if (ps) attrs.push({ n: name, ps: ps });
      else attrs.push({ n: name, v: a.value === "" && BOOL[name] ? true : a.value });
    }
    var kids = compileList((tag === "template" ? node.content : node).childNodes);
    return function (scope) {
      var props = {};
      for (var i = 0; i < attrs.length; i++) { var a = attrs[i]; props[a.n] = a.ps ? interp(a.ps, scope) : a.v; }
      if (tag === "textarea" && props.value == null) { var c = kids(scope); props.defaultValue = c.join(""); return h(tag, props); }
      return h(tag, props, kids(scope));
    };
  }

  var tplEl = document.getElementById("dc-tpl");
  var TPL = compileList(tplEl ? tplEl.content.childNodes : []);
  var BASE = { d: SITE.d, p: SITE.p, b: SITE.b, has: SITE.has, guest: SITE.guest, tier: SITE.tier };

  // ---------------------------------------------------------------- DCLogic
  class DCLogic extends P.Component {
    render() {
      inst = this;
      var v = this.renderVals ? this.renderVals() : {}, scope = {}, k;
      for (k in BASE) scope[k] = BASE[k];
      for (k in v) scope[k] = v[k];
      return h(P.Fragment, null, TPL(scope));
    }
  }
  window.DCLogic = DCLogic;

  // ---------------------------------------------------------------- joylashuv: 390px dizaynni ekranga moslash
  var root = document.getElementById("dc-root"), zoom = 1;
  function fit() {
    var w = Math.min(window.innerWidth || DW, 520);
    zoom = w / DW;
    root.style.zoom = zoom;
    document.documentElement.style.setProperty("--vh", (window.innerHeight / zoom) + "px");
    fitIntro();
  }

  var intro = null, backdrop = null, introOpen = false;
  function fitIntro() {
    if (!intro || introOpen) return;
    var vh = window.innerHeight / zoom, k = Math.min(1, vh / IH);
    intro.style.zoom = k < 1 ? k : "";
    intro.style.left = k < 1 ? ((DW - DW * k) / 2 / k) + "px" : "";
    if (backdrop) backdrop.style.height = vh + "px";
  }
  function introDone() {
    if (introOpen) return;
    introOpen = true;
    document.documentElement.style.overflow = "";
    if (backdrop) {
      backdrop.style.transition = "opacity .9s ease .4s"; backdrop.style.opacity = "0";
      setTimeout(function () { if (backdrop) { backdrop.remove(); backdrop = null; } }, 1500);
    }
    if (CFG.music && music.has && !music.playing && CFG.autoplay !== false) music.play();
  }
  function setupIntro() {
    intro = root.querySelector("[data-intro]");
    if (!intro) return;
    window.scrollTo(0, 0);
    document.documentElement.style.overflow = "hidden";
    var cs = getComputedStyle(intro), bg = cs.backgroundImage !== "none" ? cs.background : cs.backgroundColor;
    if (bg === "rgba(0, 0, 0, 0)" && intro.firstElementChild) { var c2 = getComputedStyle(intro.firstElementChild); bg = c2.backgroundImage !== "none" ? c2.background : c2.backgroundColor; }
    backdrop = document.createElement("div");
    backdrop.setAttribute("aria-hidden", "true");
    backdrop.style.cssText = "position:absolute;left:0;top:0;width:" + DW + "px;pointer-events:none;z-index:" + Math.max(0, (parseInt(cs.zIndex, 10) || 1) - 1);
    backdrop.style.background = bg;
    root.insertBefore(backdrop, root.firstChild);
  }

  // ---------------------------------------------------------------- ishga tushirish
  window.DC = {
    boot: function (Component) {
      P.render(h(Component, CFG.props || {}), document.getElementById("dc-mount"));
      var first = document.querySelector("#dc-mount > *");
      if (first) { var bg = getComputedStyle(first).backgroundColor; if (bg && bg !== "rgba(0, 0, 0, 0)") document.body.style.background = bg; }
      setupIntro();
      fit();
      window.addEventListener("resize", fit);
    },
  };
})();
