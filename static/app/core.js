/* Tayyorla Mini App — umumiy yadro: til, API, navigatsiya, oynalar, belgilar */
(() => {
  "use strict";
  const tg = window.Telegram && Telegram.WebApp;
  const initData = tg ? tg.initData : "";
  const App = (window.App = { views: {}, S: {}, tg, initData });
  const S = App.S;

  // ---------------------------------------------------------------- yordamchilar
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* xotira yopiq */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* xotira yopiq */ } },
    json(k) { try { return JSON.parse(this.get(k) || "null"); } catch { return null; } },
    put(k, v) { this.set(k, JSON.stringify(v)); },
  };
  const haptic = (t = "light") => { try { tg.HapticFeedback.impactOccurred(t); } catch { /* brauzer */ } };
  const notify = (t) => { try { tg.HapticFeedback.notificationOccurred(t); } catch { /* brauzer */ } };
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  Object.assign(App, { $, $$, esc, store, haptic, notify, debounce });

  // ---------------------------------------------------------------- til
  let DICT = {}, UZ = {};
  App.lang = "uz";
  const PLURAL = {
    ru: (n) => (n % 10 === 1 && n % 100 !== 11 ? 0 : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? 1 : 2),
    en: (n) => (n === 1 ? 0 : 1),
  };
  /** T("kalit", {n, name}) — topilmasa o'zbekcha, u ham bo'lmasa kalitning o'zi. «a|b|c» — son shakllari. */
  function T(k, p) {
    let s = DICT[k] ?? UZ[k] ?? k;
    if (s.includes("|") && p && p.n !== undefined) {
      const forms = s.split("|"), rule = PLURAL[App.lang];
      s = forms[Math.min(rule ? rule(Math.abs(+String(p.n).replace(/\D/g, ""))) : 0, forms.length - 1)];
    }
    return p ? s.replace(/\{(\w+)\}/g, (m, n) => (p[n] ?? m)) : s;
  }
  async function loadDict(lang, v) {
    const get = (l) => fetch(`/static/i18n/${l}.json?v=${v}`).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
    UZ = await get("uz");
    DICT = lang === "uz" ? UZ : await get(lang);
    App.lang = lang;
    document.documentElement.lang = { cy: "uz-Cyrl" }[lang] || lang;
  }
  App.T = T;
  App.loadDict = loadDict;
  /** Server o'zbekcha yuboradigan nomlar (katalog, yaqinlar): tarjimasi bo'lsa o'sha, bo'lmasa serverniki. */
  App.tx = (k, fallback) => DICT[k] ?? UZ[k] ?? fallback ?? k;

  const fmtNum = (n) => String(Math.round(+n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const money = (n) => T("money", { n: fmtNum(n) });
  const months = () => T("months").split(",");
  const weekdays = () => T("weekdays").split(",");  // dushanbadan
  const parseISO = (iso) => { const [y, m, d] = String(iso || "").slice(0, 10).split("-").map(Number); return y ? new Date(y, m - 1, d) : null; };
  function fmtDate(iso, opt = {}) {
    const d = parseISO(iso);
    if (!d) return "";
    const s = T(opt.year ? "date_dmy" : "date_dm", { d: d.getDate(), m: months()[d.getMonth()], y: d.getFullYear() });
    return opt.weekday ? `${s}, ${weekdays()[(d.getDay() + 6) % 7]}` : s;
  }
  const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
  const daysTo = (iso) => { const d = parseISO(iso); return d ? Math.round((d - today()) / 864e5) : null; };
  const leftText = (n) => (n === 0 ? T("left.today") : n === 1 ? T("left.tomorrow") : n < 0 ? T("left.past") : T("left.days", { n }));
  const initials = (s) => String(s || "").trim().split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("").toUpperCase() || "•";
  Object.assign(App, { fmtNum, money, fmtDate, months, weekdays, daysTo, leftText, initials, parseISO });

  // ---------------------------------------------------------------- API
  const ERR = {
    too_many_videos: "err.too_many", ai_failed: "err.ai", not_ready: "err.not_ready", bad_amount: "err.amount", no_guests: "err.no_guests",
    need_video: "err.need_video", bad_lang: "err.generic", too_big: "err.too_big", not_audio: "err.not_audio", card_number: "err.card",
  };
  function errText(status, d) {
    if (typeof d === "string") {
      if (ERR[d]) return T(ERR[d]);
      if (d.startsWith("max_guests:")) return T("err.max_guests", { n: d.split(":")[1] });
      if (d.startsWith("required:")) return T("err.required", { f: T("f." + d.split(":")[1]) });
      if (status < 500 && !/^[a-z_]+(:.*)?$/.test(d)) return d;  // serverning o'zbekcha xabari
    }
    if (status === 413) return T("err.too_big");
    if (status === 429) return T("err.slow_down");
    return T("err.generic");
  }
  async function api(path, body, opt = {}) {
    const o = { method: opt.method || (body != null ? "POST" : "GET"), headers: { "X-Init-Data": initData } };
    if (body instanceof FormData) o.body = body;
    else if (body != null) { o.body = JSON.stringify(body); o.headers["Content-Type"] = "application/json"; }
    let r;
    try { r = await fetch(path, o); } catch { throw Object.assign(new Error(T("err.network")), { status: 0 }); }
    if (!r.ok) {
      let d = null;
      try { d = (await r.json()).detail; } catch { /* matn emas */ }
      throw Object.assign(new Error(errText(r.status, d)), { status: r.status, detail: d });
    }
    return opt.raw ? r.text() : r.json();
  }
  App.api = api;
  App.refreshMe = async () => { S.me = await api("/api/me"); return S.me; };

  // ---------------------------------------------------------------- belgilar
  const I = {
    home: '<path d="M3.5 10.5 12 3.5l8.5 7V20a1 1 0 0 1-1 1H15v-6H9v6H4.5a1 1 0 0 1-1-1z"/>',
    video: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10 9.5v5l4.5-2.5z"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="m4 7 8 6 8-6"/>',
    user: '<circle cx="12" cy="8.5" r="4"/><path d="M4 20c1.5-3.6 4.4-5.5 8-5.5s6.5 1.9 8 5.5"/>',
    play: "F:M8 5.5v13l11-6.5z", pause: "F:M7 5h3.5v14H7zM13.5 5H17v14h-3.5z",
    back: '<path d="M15 5l-7 7 7 7"/>', chev: '<path d="m9 6 6 6-6 6"/>', check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>', close: '<path d="M6 6l12 12M18 6 6 18"/>',
    share: '<path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7"/><path d="M12 3v12M7.5 7.5 12 3l4.5 4.5"/>',
    send: '<path d="M21 3 10 14"/><path d="M21 3 14.5 21l-4-7.5L3 9.5z"/>',
    music: '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
    photo: '<rect x="3" y="5" width="18" height="15" rx="3"/><circle cx="9" cy="10.5" r="2"/><path d="m4 18 5-5 4 4 3-3 4 4"/>',
    pin: '<path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
    sparkle: '<path d="M12 3.5 13.8 9l5.7 1.8-5.7 1.8L12 18.2l-1.8-5.6-5.7-1.8L10.2 9z"/><path d="M19 3v3M17.5 4.5h3"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V5.5A1.5 1.5 0 0 0 14.5 4h-9A1.5 1.5 0 0 0 4 5.5v9A1.5 1.5 0 0 0 5.5 16H8"/>',
    qr: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h2v2h-2zM18 14h2M14 18h2M18 18h2v2"/>',
    cal: '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    card: '<rect x="3" y="5.5" width="18" height="13" rx="2.5"/><path d="M3 10h18M7 15h4"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    users: '<circle cx="9" cy="8.5" r="3.5"/><path d="M2.5 19.5c1.2-3 3.6-4.6 6.5-4.6s5.3 1.6 6.5 4.6"/><path d="M16 5.2a3.5 3.5 0 0 1 0 6.6M18 14.9c1.7.6 2.9 2 3.5 4.6"/>',
    gift: '<rect x="3.5" y="8.5" width="17" height="4" rx="1"/><path d="M5 12.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-7.5M12 8.5V21"/><path d="M12 8.5c-1-3-4.5-4.5-5.5-2.5S9 8.5 12 8.5zM12 8.5c1-3 4.5-4.5 5.5-2.5S15 8.5 12 8.5z"/>',
    wallet: '<rect x="3" y="6" width="18" height="14" rx="3"/><path d="M16 13h2M3 9h15a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3"/>',
    help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.7"/><path d="M12 17h.01"/>',
    channel: '<path d="M4 10v4a1 1 0 0 0 1 1h2l6 4V5L7 9H5a1 1 0 0 0-1 1z"/><path d="M17 9a4 4 0 0 1 0 6"/>',
    heart: '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
    upload: '<path d="M12 16V4M7.5 8.5 12 4l4.5 4.5"/><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
    eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    lock: '<rect x="5" y="10.5" width="14" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/><path d="M20 20v-4h-4"/>',
    sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    lang: '<path d="M4 6h9M8.5 4v2M6 6c.5 3 2.5 5.5 5.5 7M11 6c-.7 3.5-3 6.5-6.5 8"/><path d="m13 20 4-9 4 9M14.4 17h5.2"/>',
    toy: '<circle cx="9" cy="14" r="5.5"/><circle cx="15" cy="14" r="5.5"/><path d="m10.5 5 1.5-2 1.5 2-1.5 1.6z"/>',
    osh: '<ellipse cx="12" cy="16" rx="9" ry="3.5"/><path d="M5 15.5c.8-4 3.6-6.5 7-6.5s6.2 2.5 7 6.5"/><path d="M10 6.5c0-1 1-1.5 1-2.5M14 6.5c0-1 1-1.5 1-2.5"/>',
    gap: '<path d="M3 10h8l-1 5a3 3 0 0 1-3 2.4A3 3 0 0 1 4 15z"/><path d="M13 10h8l-1 5a3 3 0 0 1-3 2.4 3 3 0 0 1-3-2.4z"/><path d="M5 20.5h14"/>',
    choy: '<path d="M6 11h11v3a5.5 5.5 0 0 1-11 0z"/><path d="M17 12.5h1.5a2.5 2.5 0 0 1 0 5H16"/><path d="M6 13 3.5 10.5"/><path d="M9.5 11V9.5a2 2 0 0 1 4 0V11"/><path d="M11.5 7.5V6"/>',
    tk: '<path d="M4 20v-7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v7"/><path d="M4 16c1.3 1 2.7 1 4 0s2.7-1 4 0 2.7 1 4 0 2.7-1 4 0"/><path d="M12 11V8"/><path d="M12 6.2c-.8-.6-.8-1.6 0-2.7.8 1.1.8 2.1 0 2.7z"/><path d="M3 20h18"/>',
    sevgi: '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10z"/>',
    farzand: '<path d="M3 10h13a4 4 0 0 1-4 5H7a4 4 0 0 1-4-5z"/><path d="M3 10a6.5 6.5 0 0 1 6.5-6.5V10"/><path d="M16 10l1.5-4H20"/><circle cx="7" cy="19" r="1.6"/><circle cx="14" cy="19" r="1.6"/>',
    uzr: '<path d="M12 21v-8"/><path d="M8 5c0 4 1.5 7 4 8 2.5-1 4-4 4-8l-2 2-2-3-2 3z"/><path d="M12 17.5c-2-2-4.5-2.5-6.5-2 1 2.3 3.5 3.5 6.5 3.5M12 17.5c2-2 4.5-2.5 6.5-2-1 2.3-3.5 3.5-6.5 3.5"/>',
  };
  function icon(name, cls = "") {
    const p = I[name] || "";
    if (p.startsWith("F:")) return `<svg class="i ${cls}" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="${p.slice(2)}"/></svg>`;
    return `<svg class="i ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
  }
  App.icon = icon;

  // ---------------------------------------------------------------- navigatsiya
  const TABS = [["home", "home", "tab.home"], ["videos", "video", "tab.videos"], ["sites", "globe", "tab.sites"], ["events", "mail", "tab.events"], ["profile", "user", "tab.profile"]];
  const nav = [];
  let leave = [];
  const sheets = [];
  App.nav = nav;
  App.onLeave = (fn) => leave.push(fn);
  function cleanup() { leave.forEach((fn) => { try { fn(); } catch { /* e'tiborsiz */ } }); leave = []; }

  function drawTabs(active) {
    $("#tabs").innerHTML = TABS.map(([k, ic, label]) =>
      `<button type="button" data-tab="${k}" ${k === active ? 'aria-current="page"' : ""}><span class="pill">${icon(ic)}</span><b>${esc(T(label))}</b></button>`).join("");
    $$("#tabs [data-tab]").forEach((b) => (b.onclick = () => { haptic(); App.tab(b.dataset.tab); }));
  }
  /** Har bir ko'rinish o'z «ramka»sini aytadi: pastki menyu, sarlavha rangi. */
  App.chrome = ({ tabs = false, night = false, cta = false } = {}) => {
    document.body.classList.toggle("no-tabs", !tabs);
    document.body.classList.toggle("no-cta", !tabs && !cta);
    if (tabs) drawTabs(nav[0] && nav[0].v);
    try { tg.setHeaderColor(night ? (document.documentElement.dataset.theme === "dark" ? "#2A2468" : "#211C52") : (document.documentElement.dataset.theme === "dark" ? "#14112E" : "#F7F5FC")); } catch { /* eski Telegram */ }
  };
  function syncBack() {
    try { nav.length > 1 || sheets.length ? tg.BackButton.show() : tg.BackButton.hide(); } catch { /* brauzer */ }
  }
  function render(keepScroll) {
    cleanup();
    const top = nav[nav.length - 1];
    const el = $("#view");
    el.innerHTML = "";
    const fn = App.views[top.v];
    if (!fn) return App.tab("home");
    fn(top.p, el);
    window.scrollTo(0, keepScroll && top.y ? top.y : 0);
    syncBack();
  }
  App.render = () => { const top = nav[nav.length - 1]; if (top) top.y = window.scrollY; render(true); };
  App.go = (v, p) => { if (nav.length) nav[nav.length - 1].y = window.scrollY; nav.push({ v, p: p || {} }); render(); };
  App.replace = (v, p) => { nav[nav.length - 1] = { v, p: p || {} }; render(); };
  App.tab = (v, p) => { closeAllSheets(); nav.length = 0; nav.push({ v, p: p || {} }); render(); };
  App.back = () => {
    if (sheets.length) { sheets[sheets.length - 1].close(); return; }
    if (nav.length > 1) { nav.pop(); render(true); } else if (nav[0] && nav[0].v !== "home") App.tab("home");
  };
  App.current = () => nav[nav.length - 1];

  // ---------------------------------------------------------------- oynalar va xabarlar
  function sheet(html, { label = "", onClose } = {}) {
    const bg = document.createElement("div");
    bg.className = "sheet-bg";
    bg.innerHTML = `<section class="sheet" role="dialog" aria-modal="true" aria-label="${esc(label)}"><span class="grab"></span>${html}</section>`;
    document.body.appendChild(bg);
    const s = {
      el: bg.firstElementChild,
      close() {
        const i = sheets.indexOf(s);
        if (i < 0) return;
        sheets.splice(i, 1);
        bg.remove();
        syncBack();
        if (onClose) onClose();
      },
    };
    bg.addEventListener("click", (e) => { if (e.target === bg) s.close(); });
    sheets.push(s);
    syncBack();
    return s;
  }
  function closeAllSheets() { while (sheets.length) sheets[sheets.length - 1].close(); }
  let toastTimer;
  function toast(text, ms = 2600) {
    let el = $(".toast");
    if (!el) { el = document.createElement("div"); el.className = "toast"; el.setAttribute("role", "status"); document.body.appendChild(el); }
    el.textContent = text;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.remove(), ms);
  }
  const confirmBox = (text) => new Promise((res) => {
    try { tg.showConfirm(text, (ok) => res(!!ok)); } catch { res(window.confirm(text)); }
  });
  const alertBox = (text) => new Promise((res) => { try { tg.showAlert(text, res); } catch { window.alert(text); res(); } });
  function busy(btn, on, label) {
    if (!btn) return;
    if (on) { btn.dataset.html = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spin"></span>${label ? " " + esc(label) : ""}`; }
    else { btn.disabled = false; if (btn.dataset.html !== undefined) btn.innerHTML = btn.dataset.html; }
  }
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); }
    catch {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch { /* bo'lmadi */ }
      ta.remove();
    }
    notify("success");
    toast(T("copied"));
  }
  function openLink(url) {
    if (!url) return;
    try { /^https:\/\/t\.me\//.test(url) ? tg.openTelegramLink(url) : tg.openLink(url); } catch { window.open(url, "_blank", "noopener"); }
  }
  const shareUrl = (url, text) => openLink(`https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text || "")}`);
  const closeApp = () => { try { tg.close(); } catch { /* brauzer */ } };
  Object.assign(App, { sheet, closeAllSheets, toast, confirmBox, alertBox, busy, copyText, openLink, shareUrl, closeApp });

  /** Bo'sh holat yoki xato bloki. */
  App.errBox = (e) => (e ? `<div class="err" role="alert">${esc(e.message || e)}</div>` : "");
  App.switchHtml = (id, title, note, on) =>
    `<button type="button" class="switch" role="switch" id="${id}" aria-checked="${!!on}"><span><b>${esc(title)}</b>${note ? `<small>${esc(note)}</small>` : ""}</span><span class="track"></span></button>`;
  App.bindSwitch = (el, fn) => { if (el) el.onclick = () => { haptic(); const on = el.getAttribute("aria-checked") !== "true"; el.setAttribute("aria-checked", on); fn(on); }; };

  // ---------------------------------------------------------------- balansni to'ldirish (umumiy oyna)
  /** need — yetishmayotgan summa; amounts — tanlov; onSent — to'lov ko'rsatmasi botga ketgach. */
  App.topupSheet = ({ need = 0, title, text, onSent } = {}) => {
    const q = (S.me && S.me.quota) || {};
    const price = q.price || 9900;
    const base = (S.vm && S.vm.topups) || [9900, 29700, 49500, 99000];
    let amounts = base.filter((a) => a >= need);
    if (need && !amounts.includes(need) && need >= price) amounts = [need, ...amounts];
    if (need && need < price) amounts = [price, ...amounts.filter((a) => a > price)];
    amounts = [...new Set(amounts)].slice(0, 6);
    let pick = amounts[0];
    const count = (a) => (a % price === 0 ? T("topup.videos", { n: a / price }) : "");
    const s = sheet(`
      <div class="sh-head"><span class="sh-ic">${icon("wallet")}</span><div><h1>${esc(title || T("topup.title"))}</h1>
        <p>${esc(text || T("topup.text", { balance: money(q.balance || 0) }))}</p></div></div>
      <div class="amounts">${amounts.map((a) => `<button type="button" data-a="${a}" aria-pressed="${a === pick}"><b>${esc(money(a))}</b><small>${esc(count(a))}</small></button>`).join("")}</div>
      <button type="button" class="btn" id="tpGo">${esc(T("topup.pay", { sum: money(pick) }))}</button>
      <p class="hint" style="text-align:center">${esc(T("pay.note"))}</p>`, { label: T("topup.title") });
    $$("[data-a]", s.el).forEach((b) => (b.onclick = () => {
      haptic(); pick = +b.dataset.a;
      $$("[data-a]", s.el).forEach((x) => x.setAttribute("aria-pressed", x === b));
      $("#tpGo", s.el).textContent = T("topup.pay", { sum: money(pick) });
    }));
    $("#tpGo", s.el).onclick = async (e) => {
      busy(e.currentTarget, true);
      try {
        await api("/api/pay/topup", { amount: pick });
        notify("success");
        s.close();
        App.paySentSheet(onSent);
      } catch (err) { busy(e.currentTarget, false); toast(err.message); }
    };
    return s;
  };
  /** To'lov ko'rsatmasi botga yuborilgach: chatga o'tish. */
  App.paySentSheet = (after) => {
    const s = sheet(`
      <div class="sh-head"><span class="sh-ic" style="background:var(--emerald-soft);color:var(--emerald-ink)">${icon("send")}</span><div>
        <h1>${esc(T("paysent.title"))}</h1><p>${esc(T("paysent.text"))}</p></div></div>
      <button type="button" class="btn night" id="psChat">${esc(T("go_chat"))}</button>
      <button type="button" class="btn ghost" id="psStay">${esc(T("stay_here"))}</button>`);
    $("#psChat", s.el).onclick = () => closeApp();
    $("#psStay", s.el).onclick = () => { s.close(); if (after) after(); };
  };

  // ---------------------------------------------------------------- ishga tushirish
  function splash() {
    const el = $("#splash");
    return new Promise((res) => {
      if (!el) return res();
      if (matchMedia("(prefers-reduced-motion: reduce)").matches) { el.remove(); return res(); }
      const seen = store.get("tyr-seen");
      if (seen) el.classList.add("quick");
      store.set("tyr-seen", "1");
      let ended = false;
      const end = () => { if (ended) return; ended = true; el.classList.add("out"); setTimeout(() => el.remove(), 500); res(); };
      setTimeout(end, seen ? 1400 : 2600);
      el.onclick = end;
    });
  }

  /** Bot va eslatmalardagi havolalar: ?tab=videos, ?ev=slug, ?tosite=slug, ?v=dizayn, ?kimga=…, startapp=… */
  function route() {
    const Q = new URLSearchParams(location.search);
    const sp = (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) || "";
    const ev = Q.get("ev") || (sp.startsWith("ev_") ? sp.slice(3) : "");
    if (ev) { App.tab("events"); App.go("event", { slug: ev }); return true; }
    const tosite = Q.get("tosite") || (sp.startsWith("site_") ? sp.slice(5) : "");
    if (tosite) { App.tab("sites", { fromEvent: tosite }); return true; }
    const design = Q.get("v") || (sp.startsWith("v_") ? sp.slice(2) : "");
    if (design && S.vm.designs.some((d) => d.id === design)) { App.tab("videos"); App.go("editor", { design }); return true; }
    const tab = Q.get("tab") || (["videos", "sites", "events", "profile"].includes(sp) ? sp : "");
    if (tab === "wallet") { App.tab("profile"); App.go("wallet"); return true; }
    if (["videos", "sites", "events", "profile"].includes(tab)) { App.tab(tab, { section: Q.get("s") || "" }); return true; }
    if (Q.get("kimga")) {
      const pre = Object.fromEntries(["kimga", "sana", "tugilgan_sana"].filter((k) => Q.get(k)).map((k) => [k, Q.get(k)]));
      const p = (S.me.people || []).find((x) => x.name === pre.kimga);
      App.tab("home");
      App.go("rec", p ? { person: p.id } : { section: Q.get("s") || "tugilgan-kun", prefill: pre });
      return true;
    }
    return false;
  }

  App.start = async (v) => {
    if (tg) {
      tg.ready(); tg.expand();
      try { tg.disableVerticalSwipes(); } catch { /* eski Telegram */ }
      try { tg.BackButton.onClick(() => App.back()); } catch { /* eski Telegram */ }
      if (tg.colorScheme === "dark") document.documentElement.dataset.theme = "dark";
      try { tg.setBackgroundColor(tg.colorScheme === "dark" ? "#14112E" : "#F7F5FC"); tg.setBottomBarColor("#FFFFFF"); } catch { /* eski Telegram */ }
    }
    if (!initData) {
      const sp = $("#splash"); if (sp) sp.remove();
      $("#view").innerHTML = `<div class="done"><h1>Tayyorla</h1><p>Telegram → @tayyorla_aibot</p></div>`;
      return;
    }
    const intro = splash();
    try {
      S.me = await api("/api/me");
      await loadDict(S.me.lang || "uz", v);
      const tag = $("#splashTag"); if (tag) tag.textContent = T("splash.tag");
      const [vm, cm] = await Promise.all([api(`/api/video/meta?lang=${App.lang}`), api("/api/catalog")]);
      S.vm = vm; S.cm = cm;
      api("/api/stats/public").then((x) => {
        S.stats = x;
        const c = $("#statCount"), line = $("#statLine");
        if (c) c.textContent = T("home.counter", { n: fmtNum(x.created) });
        if (line) line.hidden = x.created < 10;
      }).catch(() => {});
      await intro;
      if (route()) return;
      if (!S.me.onboarded) { nav.length = 0; nav.push({ v: "onb", p: { step: 0 } }); render(); return; }
      App.tab("home");
    } catch (e) {
      await intro;
      $("#view").innerHTML = `<div class="wrap" style="padding-top:40px">${App.errBox(e)}<div style="height:12px"></div><button class="btn" onclick="location.reload()">${esc(T("retry"))}</button></div>`;
    }
  };
})();
