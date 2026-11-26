/* Tayyorla admin paneli: Umumiy, Voronka, Trafik manbalari, Sotuvlar, To'lovlar, Foydalanuvchilar, Xabar yuborish, Tizim */
(() => {
  "use strict";
  const tg = window.Telegram && window.Telegram.WebApp;
  const TZ = "Asia/Tashkent";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => (n == null ? "—" : Math.round(n).toLocaleString("ru-RU").replace(/\u00a0/g, " "));
  const som = (n) => (n == null ? "—" : `${fmt(n)} so'm`);
  const pctOf = (a, b) => (b ? Math.round((1000 * a) / b) / 10 : 0);
  const S = { tab: "overview", token: "", me: null, period: { preset: "7", from: "", to: "" }, metric: "new_users", pending: 0 };

  // ---------------------------------------------------------------- kirish
  try {
    const t = new URLSearchParams(location.search).get("t");
    // kalit faqat shu oynada saqlanadi (sessionStorage): boshqa sahifalar yoki keyingi ochilishda qolmaydi
    try { localStorage.removeItem("adm_t"); } catch (e) { /* eski versiyadan qolgan */ }
    if (t) { sessionStorage.setItem("adm_t", t); history.replaceState(null, "", location.pathname + location.hash); }
    S.token = sessionStorage.getItem("adm_t") || "";
  } catch (e) { S.token = new URLSearchParams(location.search).get("t") || ""; }
  if (tg) {
    tg.ready(); tg.expand();
    if (tg.colorScheme) document.documentElement.dataset.theme = tg.colorScheme;
    if (tg.BackButton && document.referrer.includes("/app")) { tg.BackButton.show(); tg.BackButton.onClick(() => (location.href = "/app")); }
  }

  async function api(path, body, method) {
    const headers = {};
    if (tg && tg.initData) headers["X-Init-Data"] = tg.initData;
    if (S.token) headers["X-Admin-Token"] = S.token;
    const opt = { method: method || (body ? "POST" : "GET"), headers };
    if (body instanceof FormData) opt.body = body; // fayl yuklash: brauzer o'zi multipart qiladi
    else if (body) { headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    const r = await fetch(path, opt);
    if (!r.ok) {
      let msg = `Xato ${r.status}`;
      try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : msg; } catch (e) { /* matn emas */ }
      if (r.status === 401 || r.status === 403) { try { sessionStorage.removeItem("adm_t"); } catch (e) { /* */ } }
      const err = new Error(msg); err.status = r.status; throw err;
    }
    return r.json();
  }
  const withT = (url) => `${url}${url.includes("?") ? "&" : "?"}t=${encodeURIComponent(S.me ? S.me.token : S.token)}`;

  function toast(msg, err) {
    const el = $("#toast");
    el.textContent = msg; el.className = "toast" + (err ? " err" : ""); el.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => (el.hidden = true), 2600);
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); toast("Nusxa olindi"); }
    catch (e) { prompt("Nusxa oling:", text); }
  }
  function openExternal(url) { if (tg && tg.openLink) tg.openLink(url); else window.open(url, "_blank", "noopener"); }
  function download(url) {
    const full = location.origin + withT(url);
    if (tg && tg.platform && tg.platform !== "unknown") openExternal(full); else location.href = full;
  }

  // ---------------------------------------------------------------- sana
  const localISO = (d) => d.toLocaleDateString("en-CA", { timeZone: TZ });
  const addDays = (iso, n) => { const d = new Date(iso + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const fromUTC = (s) => (s ? new Date(/Z|[+-]\d\d:\d\d$/.test(s) ? s : s + "Z") : null);
  const dt = (s) => { const d = fromUTC(s); return d ? d.toLocaleString("ru-RU", { timeZone: TZ, day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"; };
  const day = (s) => { const d = fromUTC(s); return d ? d.toLocaleDateString("ru-RU", { timeZone: TZ, day: "2-digit", month: "2-digit", year: "numeric" }) : "—"; };
  const MONTHS = ["yan", "fev", "mar", "apr", "may", "iyun", "iyul", "avg", "sen", "okt", "noy", "dek"];
  const shortDay = (iso) => { const [, m, d] = iso.split("-"); return `${+d} ${MONTHS[+m - 1]}`; };
  const ago = (s) => {
    const d = fromUTC(s); if (!d) return "—";
    const m = Math.round((Date.now() - d) / 60000);
    if (m < 2) return "hozir"; if (m < 60) return `${m} daqiqa oldin`;
    const h = Math.round(m / 60); if (h < 24) return `${h} soat oldin`;
    const dd = Math.round(h / 24); return dd < 31 ? `${dd} kun oldin` : day(s);
  };

  const PRESETS = [
    ["0", "Bugun"], ["1", "Kecha"], ["7", "7 kun"], ["30", "30 kun"], ["month", "Bu oy"], ["prev", "O'tgan oy"], ["90", "90 kun"],
  ];
  function range(p = S.period) {
    const t = localISO(new Date());
    if (p.preset === "custom") return [p.from || t, p.to || t];
    if (p.preset === "0") return [t, t];
    if (p.preset === "1") { const y = addDays(t, -1); return [y, y]; }
    if (p.preset === "month") return [t.slice(0, 8) + "01", t];
    if (p.preset === "prev") { const end = addDays(t.slice(0, 8) + "01", -1); return [end.slice(0, 8) + "01", end]; }
    if (p.preset === "all") return ["", t];
    return [addDays(t, -(+p.preset - 1)), t];
  }
  function periodBar(extra = []) {
    const [f, t] = range();
    return `<div class="period" role="group" aria-label="Davr">
      ${[...PRESETS, ...extra].map(([k, l]) => `<button type="button" class="chip" data-preset="${k}" aria-pressed="${S.period.preset === k}">${l}</button>`).join("")}
      <input type="date" id="p-from" value="${f}" aria-label="Boshlanish sanasi"> <span class="muted">—</span>
      <input type="date" id="p-to" value="${t}" aria-label="Tugash sanasi">
    </div>`;
  }
  function bindPeriod(root, rerender) {
    $$("[data-preset]", root).forEach((b) => (b.onclick = () => { S.period = { preset: b.dataset.preset, from: "", to: "" }; rerender(); }));
    const onDate = () => { S.period = { preset: "custom", from: $("#p-from", root).value, to: $("#p-to", root).value }; rerender(); };
    $("#p-from", root).onchange = onDate; $("#p-to", root).onchange = onDate;
  }
  const qs = () => { const [f, t] = range(); return `from=${f}&to=${t}`; };
  const periodLabel = () => { const [f, t] = range(); return f === t ? day(f) : `${day(f)} — ${day(t)}`; };

  // ---------------------------------------------------------------- belgilar
  const IC = {
    overview: '<path d="M4 19V10M10 19V5M16 19v-7M22 19H2"/>',
    funnel: '<path d="M3 4h18l-7 8.5V20l-4-2v-5.5L3 4Z"/>',
    sources: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
    sales: '<path d="M3 7h18l-2 12H5L3 7Z"/><path d="M8 7a4 4 0 0 1 8 0"/>',
    payments: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/>',
    users: '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0M17 4a4 4 0 0 1 0 8M22 21a6 6 0 0 0-4-5.6"/>',
    broadcast: '<path d="M3 11v2a1 1 0 0 0 1 1h3l6 5V5L7 10H4a1 1 0 0 0-1 1ZM17 8a5 5 0 0 1 0 8M20 5a9 9 0 0 1 0 14"/>',
    nudges: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8ZM10 20a2 2 0 0 0 4 0"/>',
    pricing: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8Z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
    system: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 2.9-1.2V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
  };
  const icon = (k) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${IC[k]}</svg>`;
  const TABS = [
    ["overview", "Umumiy"], ["funnel", "Voronka"], ["sources", "Trafik manbalari"], ["sales", "Sotuvlar"], ["payments", "To'lovlar"],
    ["users", "Foydalanuvchilar"], ["broadcast", "Xabar yuborish"], ["nudges", "Progrev"], ["pricing", "Narxlar"], ["system", "Tizim"],
  ];
  function nav() {
    $("#nav").innerHTML = TABS.map(([k, l]) => `<button type="button" data-tab="${k}" aria-current="${S.tab === k ? "page" : "false"}">${icon(k)}<span>${l}</span>${k === "payments" && S.pending ? `<span class="badge">${S.pending}</span>` : ""}</button>`).join("");
    $$("#nav button").forEach((b) => (b.onclick = () => go(b.dataset.tab)));
  }
  function go(tab) {
    S.tab = tab;
    try { history.replaceState(null, "", "#" + tab); } catch (e) { /* */ }
    nav(); render();
    $("#main").focus({ preventScroll: true }); window.scrollTo(0, 0);
  }

  const main = () => $("#main");
  const loading = (title) => { main().innerHTML = `<div class="head"><div><h1>${title}</h1></div></div><p class="boot">Yuklanmoqda…</p>`; };
  const failed = (e) => { main().insertAdjacentHTML("beforeend", `<p class="note">${esc(e.message)}</p>`); };
  let seq = 0;
  async function render() {
    const my = ++seq;
    const fn = VIEWS[S.tab] || VIEWS.overview;
    try { await fn(() => my === seq); } catch (e) { if (my === seq) failed(e); }
  }

  // ---------------------------------------------------------------- yordamchi bloklar
  function delta(cur, prev, invert) {
    if (prev == null || cur == null) return "";
    if (!prev && !cur) return "";
    if (!prev) return `<span class="delta up" title="Oldingi davrda 0">yangi</span>`;
    const p = Math.round(((cur - prev) / prev) * 100);
    if (p === 0) return `<span class="delta flat" title="Oldingi davr: ${fmt(prev)}">0%</span>`;
    const good = invert ? p < 0 : p > 0;
    return `<span class="delta ${good ? "up" : "down"}" title="Oldingi davr: ${fmt(prev)}">${p > 0 ? "+" : "−"}${Math.abs(p)}%</span>`;
  }
  const kpi = (v, label, hint, prev, opts = {}) => `<div class="kpi${opts.open ? " click" : ""}${opts.cls ? " " + opts.cls : ""}"${opts.open ? ` role="button" tabindex="0" data-kpi="${opts.open}"` : ""}><div class="v">${opts.money ? `${fmt(v)}<small>so'm</small>` : fmt(v)}${opts.suffix || ""} ${delta(v, prev, opts.invert)}</div>
    <div class="l">${label}${opts.open ? ` <span class="more">Batafsil ›</span>` : ""}</div>${hint ? `<div class="h">${hint}</div>` : ""}</div>`;
  const table = (head, rows, empty = "Ma'lumot yo'q", cls = "") => `<div class="tbl-wrap${cls ? " " + cls : ""}"><table><thead><tr>${head.map((h) => `<th${h.startsWith(">") ? ' class="r"' : ""}>${h.replace(/^>/, "")}</th>`).join("")}</tr></thead>
    <tbody>${rows.length ? rows.join("") : `<tr><td colspan="${head.length}" class="empty">${empty}</td></tr>`}</tbody></table></div>`;
  const tag = (txt, kind = "") => `<span class="tag ${kind}">${esc(txt)}</span>`;
  const userLink = (u) => `${esc(u.name || "—")}${u.username ? ` <span class="sub">@${esc(u.username)}</span>` : `<span class="sub">id ${u.user_id || u.owner || u.id}</span>`}`;

  // ---------------------------------------------------------------- grafik (bitta qator, kunlik ustunlar)
  function barChart(days, values, fmtv, width) {
    const W = Math.max(280, Math.round(width || 900)), H = 220, L = 44, B = 26, T = 8, n = values.length;
    const max = Math.max(1, ...values);
    const step = niceStep(max);
    const top = Math.ceil(max / step) * step;
    const y = (v) => T + (H - T - B) * (1 - v / top);
    const bw = (W - L) / n, gap = Math.min(2 + bw * 0.25, 10);
    const ticks = []; for (let v = 0; v <= top; v += step) ticks.push(v);
    const every = Math.ceil(n / Math.max(2, Math.floor((W - L) / 64)));
    const bars = values.map((v, i) => {
      const x = L + i * bw + gap / 2, w = Math.max(1, bw - gap), h = Math.max(0, H - B - y(v));
      const r = Math.min(4, w / 2, h);
      const path = h > 0 ? `<path class="bar" d="M${x},${H - B} v${-(h - r)} q0,${-r} ${r},${-r} h${w - 2 * r} q${r},0 ${r},${r} v${h - r} z" fill="var(--bar)" data-i="${i}"/>` : "";
      return path;
    }).join("");
    const hits = values.map((v, i) => `<rect class="hit" x="${L + i * bw}" y="${T}" width="${bw}" height="${H - T}" data-i="${i}"/>`).join("");
    const labels = days.map((d, i) => (i % every === 0 ? `<text x="${L + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle">${shortDay(d)}</text>` : "")).join("");
    const grid = ticks.map((v) => `<line x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/>`).join("");
    const tl = ticks.map((v) => `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${fmtShort(v)}</text>`).join("");
    const html = `<div class="chart-wrap"><svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Kunlik grafik">
      <g class="grid">${grid}</g><g class="axis">${tl}${labels}</g><g class="bars">${bars}</g><g>${hits}</g></svg><div class="tip" hidden></div></div>`;
    return { html, bind(root) {
      const svg = $("svg.chart", root), tip = $(".tip", root);
      $$("rect.hit", svg).forEach((r) => {
        const show = () => {
          const i = +r.dataset.i;
          svg.classList.add("hovering");
          $$("path.bar", svg).forEach((p) => p.classList.toggle("on", +p.dataset.i === i));
          tip.innerHTML = `${shortDay(days[i])}: <b>${fmtv(values[i])}</b>`;
          const box = svg.getBoundingClientRect();
          tip.style.left = `${((L + i * bw + bw / 2) / W) * box.width}px`;
          tip.style.top = `${(y(values[i]) / H) * box.height}px`;
          tip.hidden = false;
        };
        r.addEventListener("mouseenter", show); r.addEventListener("click", show);
      });
      svg.addEventListener("mouseleave", () => { svg.classList.remove("hovering"); tip.hidden = true; });
    } };
  }
  function niceStep(max) {
    const raw = max / 4, mag = 10 ** Math.floor(Math.log10(raw)), f = raw / mag;
    return Math.max(1, (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * mag);
  }
  const fmtShort = (v) => (v >= 1e6 ? `${Math.round(v / 1e5) / 10} mln` : v >= 1e4 ? `${Math.round(v / 1e3)} ming` : fmt(v));

  // ---------------------------------------------------------------- 1. Umumiy
  const METRICS = [
    ["new_users", "Yangi foydalanuvchilar", fmt], ["app_users", "Ilovaga kirganlar", fmt], ["starts", "Start bosishlar", fmt],
    ["sites", "Yasalgan taklifnomalar", fmt], ["sites_paid", "Sotilgan taklifnomalar", fmt],
    ["videos_free", "Bepul videolar", fmt], ["videos_paid", "Pullik videolar", fmt], ["revenue", "Tushum (to'ldirishlar)", som],
  ];
  async function overview(alive) {
    loading("Umumiy ko'rinish");
    const d = await api(`/api/admin/overview?${qs()}`);
    if (!alive()) return;
    const c = d.cur, p = d.prev, now = d.now;
    S.pending = now.pending; nav();
    const prevLabel = d.days === 1 ? "kechagiga nisbatan" : `oldingi ${d.days} kunga nisbatan`;
    main().innerHTML = `
      <div class="head"><div><h1>Umumiy ko'rinish</h1><p>${periodLabel()} · foizlar ${prevLabel}</p></div></div>
      ${periodBar()}
      <section class="blk"><div class="now">
        <div class="${now.pending ? "alert" : ""}"><b>${fmt(now.pending)}</b><span>To'lov kutmoqda${now.pending ? ` · ${som(now.pending_sum)}` : ""}</span>
          ${now.pending ? `<br><button type="button" class="link" data-go="payments">Ko'rib chiqish</button>` : ""}</div>
        <div><b>${now.channel == null ? "—" : fmt(now.channel)}</b><span>Kanal obunachilari ${esc(now.channel_name || "")}${now.channel_growth ? ` · ${now.channel_growth > 0 ? "+" : ""}${fmt(now.channel_growth)} shu davrda` : ""}</span></div>
        <div><b>${fmt(c.users.total)}</b><span>Bot foydalanuvchilari jami · ${fmt(now.blocked)} tasi botni bloklagan</span></div>
        <div><b>${fmt(now.queue)}</b><span>Video navbatda</span></div>
      </div></section>
      <section class="blk"><div class="groups">
        <div class="group"><h2><i></i>Foydalanuvchilar</h2><div class="kpis">
          ${kpi(c.users.new, "Yangi foydalanuvchilar", "botga birinchi marta kirganlar", p.users.new)}
          ${kpi(c.users.active, "Faol foydalanuvchilar", `${fmt(c.users.returning)} tasi qaytib kelganlar`, p.users.active)}
          ${kpi(c.users.app_users, "Ilovaga kirganlar", `${fmt(c.users.app_opens)} marta kirish (kuniga 1 tadan)`, p.users.app_users)}
          ${kpi(c.users.starts, "Start bosishlar", `${fmt(c.users.start_users)} kishi`, p.users.starts)}
        </div></div>
        <div class="group"><h2><i></i>Taklifnomalar (web-sayt)</h2><div class="kpis">
          ${kpi(c.sites.created, "Yasaldi", `${fmt(c.sites.creators)} kishi yasadi`, p.sites.created)}
          ${kpi(c.sites.unpaid, "Yasaldi, ammo sotib olinmadi", `konversiya ${c.sites.conv}%`, p.sites.unpaid, { invert: true })}
          ${kpi(c.sites.sold, "Sotildi", som(c.sites.sold_sum), p.sites.sold)}
          ${kpi(c.sites.upgrades, "Tarifni oshirishlar", som(c.sites.upgrades_sum), p.sites.upgrades)}
        </div></div>
        <div class="group"><h2><i></i>Video taklifnomalar</h2><div class="kpis">
          ${kpi(c.videos.free + c.videos.bonus, "Bepul videolar", `${fmt(c.videos.free_users)} kishi · ${fmt(c.videos.bonus)} tasi bonus`, p.videos.free + p.videos.bonus)}
          ${kpi(c.videos.paid, "Pullik videolar", som(c.videos.paid_sum), p.videos.paid)}
          ${kpi(c.videos.unpaid, "Yasaldi, ammo to'lanmadi", "to'lov kutayotgan videolar", p.videos.unpaid, { invert: true })}
          ${kpi(c.videos.guest, "Mehmonlarga shaxsiy videolar", `${fmt(c.videos.packages)} paket · ${som(c.videos.packages_sum)}`, p.videos.guest)}
        </div><p class="h muted" style="font-size:12px;padding:0 0 10px">Bepul videodan keyin pul to'laganlar: ${c.videos.free_to_paid}%${c.videos.failed ? ` · xato bilan tugagan: ${fmt(c.videos.failed)}` : ""}</p></div>
        ${c.songs ? `<div class="group"><h2><i></i>Shaxsiy qo'shiqlar</h2><div class="kpis">
          ${kpi(c.songs.created, "She'r yozildi", `${fmt(c.songs.previews)} ta namuna eshitildi`, p.songs ? p.songs.created : 0)}
          ${kpi(c.songs.sold, "Sotildi", som(c.songs.sold_sum), p.songs ? p.songs.sold : 0)}
          ${kpi(c.songs.created - c.songs.paid_of_created, "Yozildi, ammo sotib olinmadi", `konversiya ${c.songs.conv}%`, p.songs ? p.songs.created - p.songs.paid_of_created : 0, { invert: true })}
          ${kpi(c.songs.failed, "Xato bilan tugagan", c.songs.failed ? `namuna ${fmt(c.songs.failed_sample)} · to'liq qo'shiq ${fmt(c.songs.failed_full)} · ${fmt(c.songs.failed_people)} kishi` : "namuna va to'liq qo'shiq xatolari", p.songs ? p.songs.failed : 0, { invert: true, open: "errors" })}
          ${c.costs ? kpi(c.costs.song_profit, "Qo'shiqdan sof natija", `sotuv ${som(c.songs.sold_sum)} − xarajat ${som(c.costs.song)} · ${fmt(c.costs.demo_n)} ta demo`, p.costs ? p.costs.song_profit : 0, { money: true, open: "costs" }) : ""}
        </div></div>` : ""}
        <div class="group"><h2><i></i>Pul</h2><div class="kpis">
          ${kpi(c.money.topup, "Hisobga tushgan pul", `${fmt(c.money.topups)} ta to'lov · o'rtacha ${som(c.money.avg_check)}`, p.money.topup, { money: true, cls: "money-in" })}
          ${kpi(c.money.payers, "To'lov qilganlar", `${fmt(c.money.new_payers)} tasi birinchi marta`, p.money.payers)}
          ${kpi(c.money.spent, "Xizmatlarga sarflandi", `${fmt(c.money.buyers)} xaridor`, p.money.spent, { money: true, open: "spend" })}
          ${c.costs ? kpi(c.costs.total, "Taxminiy xarajat (AI va musiqa)", `qo'shiqlar ${som(c.costs.song)} · matnlar ${som(c.costs.other)}`, p.costs ? p.costs.total : 0, { money: true, invert: true, open: "costs" }) : ""}
          ${kpi(c.money.refunds, "Qaytarilgan", c.money.admin ? `admin tuzatishlari: ${som(c.money.admin)}` : "video tayyorlanmaganda", p.money.refunds, { money: true, invert: true })}
        </div></div>
      </div></section>
      <section class="blk"><div class="bh"><h2>Kunlar bo'yicha</h2></div>
        <div class="chart-card"><div class="metric-tabs" role="group" aria-label="Ko'rsatkich">${METRICS.map(([k, l]) => `<button type="button" class="chip" data-metric="${k}" aria-pressed="${S.metric === k}">${l}</button>`).join("")}</div>
        <div id="chart"></div></div></section>
      <section class="blk"><div class="bh"><h2>Voronka: shu davrda kelgan yangi foydalanuvchilar</h2>
          <p>Keyin nima qilishgan (hozirgacha) · <button type="button" class="link" data-go="funnel">To'liq voronka: filtrlar va namunasiz qolganlar ›</button></p></div>
        <div class="period" role="group" aria-label="Mahsulot" style="margin-bottom:10px">${FN_PRODUCTS.map(([k, l]) => `<button type="button" class="chip" data-ovf="${k}" aria-pressed="${(S.ovf || "song") === k}">${l}</button>`).join("")}</div>
        <div class="chart-card funnel" id="ov-funnel"><p class="boot">Yuklanmoqda…</p></div></section>`;
    bindPeriod(main(), render);
    $$("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
    const SHEETS = { spend: () => spendSheet(), costs: () => costsSheet(), errors: () => go("system") };
    // voronka: Qo'shiq / Sayt / Video (qo'shiq — standart ko'rinish), kogorta bo'yicha
    const drawFunnel = async () => {
      const o = { product: S.ovf || "song", mode: "cohort", src: "" };
      try { o.data = await api(`/api/admin/funnel?${fnQuery(o)}`); }
      catch (e) { if (alive() && $("#ov-funnel")) $("#ov-funnel").innerHTML = `<p class="note">${esc(e.message)}</p>`; return; }
      if (!alive() || !$("#ov-funnel") || o.product !== (S.ovf || "song")) return;
      $("#ov-funnel").innerHTML = funnelSteps(o.data) + `<p class="muted" style="font-size:12.5px">Foizlar — oldingi qadamdan o'tganlar ulushi. Tushib qolganlar soniga bosilsa, o'sha odamlar ro'yxati ochiladi.</p>`;
      bindFunnel($("#ov-funnel"), o);
    };
    $$("[data-ovf]").forEach((b) => (b.onclick = () => {
      S.ovf = b.dataset.ovf; $$("[data-ovf]").forEach((x) => x.setAttribute("aria-pressed", x === b));
      $("#ov-funnel").innerHTML = `<p class="boot">Yuklanmoqda…</p>`; drawFunnel();
    }));
    drawFunnel();
    $$("[data-kpi]").forEach((b) => { const open = SHEETS[b.dataset.kpi]; if (!open) return; b.onclick = open; b.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } }; });
    const drawChart = () => {
      const m = METRICS.find((x) => x[0] === S.metric);
      const vals = c.series[S.metric];
      const ch = barChart(c.series.days, vals, m[2], $("#chart").clientWidth);
      $("#chart").innerHTML = ch.html + `<p class="chart-sum">${m[1]}: jami ${m[2](vals.reduce((a, b) => a + b, 0))}</p>`;
      ch.bind($("#chart"));
    };
    $$("[data-metric]").forEach((b) => (b.onclick = () => { S.metric = b.dataset.metric; $$("[data-metric]").forEach((x) => x.setAttribute("aria-pressed", x === b)); drawChart(); }));
    drawChart();
    window.onresize = () => { clearTimeout(drawChart.t); drawChart.t = setTimeout(() => $("#chart") && drawChart(), 150); };
  }

  // ---------------------------------------------------------------- 1b. Voronka: qo'shiq, sayt, video (statistika TZ, 1 va 2-bandlar)
  const FN_PRODUCTS = [["song", "Qo'shiq"], ["site", "Sayt"], ["video", "Video"]];
  const FN_MODES = [["cohort", "Shu davrda kelgan yangi odamlar (kogorta)"], ["period", "Shu davrdagi harakatlar"]];
  const dayISO = (iso) => (iso || "").slice(0, 10).split("-").reverse().join(".");
  const fnQuery = (o) => {
    const [f, t] = range();
    return `${S.period.preset === "all" ? "all_time=1" : `from=${f}&to=${t}`}&product=${o.product}&mode=${o.mode}&src=${encodeURIComponent(o.src || "")}`;
  };
  // qadamlar ustma-ust: odamlar soni, oldingi qadamdan o'tganlar foizi, tushib qolganlar (bosilsa ro'yxat) va qadamlar orasidagi vaqt
  function funnelSteps(d) {
    const top = d.steps[0].n || 1;
    return d.steps.map((s, i) => `<div class="fstep fx"><span class="t"><b class="num">${i + 1}.</b> ${esc(s.label)}${s.since ? `<small class="sub">hisob ${day(s.since)} dan</small>` : ""}</span>
      <div class="track"><div class="fill" style="width:${Math.max(0.5, (100 * s.n) / top)}%"></div></div>
      <span class="n num">${fmt(s.n)}<small>${i ? `${s.pct}%` : ""}</small></span>
      <span class="d">${!i ? "" : s.lost ? `<button type="button" class="link" data-lost="${s.lost_at}" title="Shu qadamga yetmay to'xtaganlar ro'yxati">−${fmt(s.lost)} tushib qoldi</button>` : `<span class="muted">hamma o'tdi</span>`}
        ${s.time && s.time.n ? `<small class="sub" title="Oldingi qadamdan shu qadamgacha: ikkalasi ham yozilgan ${fmt(s.time.n)} kishi bo'yicha">oldingi qadamdan o'rtacha ${dur(s.time.avg_s)} keyin · mediana ${dur(s.time.median_s)}</small>` : ""}</span></div>
      ${d.side.filter((x) => x.under === s.key && x.n).map((x) => `<div class="fside">↳ ${esc(x.label)}: <b>${fmt(x.n)}</b> kishi</div>`).join("")}`).join("");
  }
  function bindFunnel(root, o) {
    $$("[data-lost]", root).forEach((b) => (b.onclick = () => {
      const st = o.data.steps.find((x) => x.key === b.dataset.lost);
      peopleSheet(`«${st.label}» qadamida to'xtaganlar`, `${fnQuery(o)}&step=${b.dataset.lost}`);
    }));
  }
  // tushib qolganlar ro'yxati: mijoz kartasiga o'tish va to'liq CSV
  async function peopleSheet(title, query) {
    sheet(`<p class="boot">Yuklanmoqda…</p>`);
    let d;
    try { d = await api(`/api/admin/funnel/people?${query}`); } catch (e) { $("#sheet-body").innerHTML = `<p class="note">${esc(e.message)}</p>`; return; }
    $("#sheet-body").innerHTML = `<h2 class="big" id="sheet-title">${esc(title)}</h2>
      <p class="muted">${fmt(d.total)} kishi${d.total > d.rows.length ? ` · oxirgi ${fmt(d.rows.length)} tasi ko'rsatildi` : ""} · vaqt Toshkent bo'yicha</p>
      <div class="row" style="margin:10px 0"><button type="button" class="btn sm" id="pp-csv">To'liq ro'yxat CSV</button></div>
      ${table(["Mijoz", "Manba", "Qachon"], d.rows.map((u) => `<tr class="click" data-user="${u.id}"><td>${userLink(u)}${u.blocked ? ` ${tag("bloklagan", "bad")}` : ""}</td>
        <td>${esc(u.source)}</td><td class="num">${dt(u.at)}<span class="sub">oxirgi faollik: ${ago(u.last_seen)}</span></td></tr>`), "Hech kim yo'q")}`;
    $("#pp-csv").onclick = () => download(`/api/admin/export/funnelpeople.csv?${query}`);
    $$("[data-user]", $("#sheet")).forEach((tr) => (tr.onclick = () => userSheet(+tr.dataset.user)));
  }
  // «Namunasiz qolganlar»: she'ri bor, namunasi yo'q odamlar — sabab bo'yicha
  function nosampleBlock(ns) {
    const rows = ns.groups.filter((g) => g.n || !["pending", "old"].includes(g.key)).map((g) => `<tr${g.n ? ` class="click" data-nsg="${g.key}"` : ""}>
      <td><b>${esc(g.label)}</b><span class="sub">${esc(g.about)}</span>${g.sub.length ? `<span class="sub">${g.sub.map((x) => `${esc(x.label)}: ${fmt(x.n)}`).join(" · ")}</span>` : ""}</td>
      <td class="r num"><b>${fmt(g.n)}</b></td><td class="r num">${g.pct}%<div class="mini-bar"><i style="width:${Math.min(100, g.pct)}%"></i></div></td>
      <td>${esc(g.todo)}</td></tr>`);
    return `<section class="blk"><div class="bh"><h2>Namunasiz qolganlar</h2><div class="row"><button type="button" class="btn sm" id="ns-csv">CSV</button></div></div>
      <div class="now">
        <div><b>${fmt(ns.lyrics)}</b><span>kishida she'r tayyor</span></div>
        <div><b>${fmt(ns.with_sample)}</b><span>kishi namunasini oldi (${pctOf(ns.with_sample, ns.lyrics)}%)</span></div>
        <div class="${ns.none ? "alert" : ""}"><b>${fmt(ns.none)}</b><span>kishi namunasiz qoldi (${pctOf(ns.none, ns.lyrics)}%)</span></div>
        <div><b>${fmt(ns.bought)}</b><span>kishi namunasiz sotib oldi</span></div>
      </div>
      <div style="margin-top:12px">${table(["Nega namunasiz", ">Kishi", ">Ulushi", "Nima qilinadi"], rows)}</div>
      <p class="muted" style="font-size:12.5px;margin-top:8px">Har bir odam bitta guruhda: bir necha to'siq bo'lsa, eng oxirgisi sanaladi. Qatorga bosilsa, odamlar ro'yxati ochiladi.
        «Kutib o'tirmagan» — namuna tayyor bo'lganda ilovada yo'q edi va keyin ham eshitmadi; bot har bir tayyor namuna haqida bir marta xabar yuboradi (botni bloklaganlarga emas)${ns.notified ? ` — shu guruhdan ${fmt(ns.notified)} kishiga xabar yetgan` : ""}.
        ${ns.since ? `Tugma bosilgani, limit va xato sabablari <b>${dt(ns.since)}</b> dan beri yoziladi; undan oldingi she'rlar «Sababi yozilmagan (eski)» qatorida.` : "Sabablar hali yozila boshlamagan (server qayta ishga tushgach boshlanadi)."}</p></section>`;
  }
  async function funnelPage(alive) {
    loading("Voronka");
    const o = (S.fn = S.fn || { product: "song", mode: "cohort", src: "" });
    const d = await api(`/api/admin/funnel?${fnQuery(o)}`);
    if (!alive()) return;
    o.data = d;
    const q = fnQuery(o), span = S.period.preset === "all" ? "Butun davr" : periodLabel();
    const detail = d.steps.map((s, i) => `<tr><td><b>${i + 1}. ${esc(s.label)}</b>${s.event ? `<span class="sub">${esc(s.event)}${s.since ? ` · hisob ${dt(s.since)} dan` : ""}</span>` : ""}</td>
      <td class="r num"><b>${fmt(s.n)}</b></td><td class="r num">${i ? `${s.pct}%` : "—"}</td><td class="r num">${s.of_first}%</td>
      <td class="r num">${i ? fmt(s.lost) : "—"}</td><td class="r num">${fmt(s.exact)}</td>
      <td class="r num">${s.time && s.time.n ? `${dur(s.time.avg_s)}<span class="sub">mediana ${dur(s.time.median_s)} · ${fmt(s.time.n)} kishi</span>` : "—"}</td></tr>`)
      .concat(d.side.map((x) => `<tr><td class="muted">↳ ${esc(x.label)}<span class="sub">${esc(x.key)}${x.since ? ` · hisob ${dt(x.since)} dan` : ""}</span></td>
        <td></td><td></td><td></td><td></td><td class="r num">${fmt(x.n)}</td><td></td></tr>`));
    const spans = d.spans.map((x) => `<tr><td>${esc(x.label)}</td><td class="r num">${fmt(x.n)}</td><td class="r num"><b>${dur(x.avg_s)}</b></td><td class="r num">${dur(x.median_s)}</td></tr>`);
    main().innerHTML = `
      <div class="head"><div><h1>Voronka</h1><p>${span} · odamlar qaysi qadamda to'xtab qolyapti. Sanash odam bo'yicha: bir kishi besh marta boshlasa ham bitta.</p></div>
        <button type="button" class="btn" id="fn-csv">Voronka CSV</button></div>
      ${periodBar([["all", "Butun davr"]])}
      <div class="period" role="group" aria-label="Mahsulot" style="margin-top:10px">
        ${d.products.map((x) => `<button type="button" class="chip" data-fprod="${x.key}" aria-pressed="${o.product === x.key}">${esc(x.label)}</button>`).join("")}</div>
      <div class="period" role="group" aria-label="Ko'rinish va manba" style="margin-top:10px">
        ${FN_MODES.map(([k, l]) => `<button type="button" class="chip" data-fmode="${k}" aria-pressed="${o.mode === k}">${l}</button>`).join("")}
        <select class="in" id="fn-src" style="width:auto;max-width:280px" aria-label="Manba">${d.sources.map((x) => `<option value="${esc(x.key)}"${x.key === o.src ? " selected" : ""}>${esc(x.label)}</option>`).join("")}</select></div>
      <section class="blk"><div class="bh"><h2>${esc(d.label)} voronkasi</h2><p>${o.mode === "cohort" ? "shu davrda botga birinchi marta kelganlar va ularning keyingi (hozirgacha) harakatlari" : "kim qachon kelganidan qat'i nazar, shu davr ichidagi harakatlar"}</p></div>
        <div class="chart-card funnel">${funnelSteps(d)}</div>
        <p class="muted" style="font-size:12.5px;margin-top:8px">Har bir qatorda: shu qadamga yetib kelgan odamlar, oldingi qadamdan o'tganlar foizi va tushib qolganlar — soniga bosilsa, o'sha odamlar ro'yxati ochiladi.
          Keyingi qadamga yetgan odam oldingi qadamlardan ham o'tgan hisoblanadi (masalan, namunasiz sotib olgan yoki balansidagi puldan to'lagan), shuning uchun sonlar faqat kamayadi; aynan shu hodisasi yozilgan odamlar soni pastdagi jadvalda.
          Admin va sinov akkauntlari (${fmt(d.excluded)} ta) sanalmaydi. Vaqtlar Toshkent bo'yicha.
          ${d.product === "song" ? (d.since ? `«hisob … dan» belgili qadamlar <b>${dt(d.since)}</b> dan beri yoziladi; undan oldingi davr mavjud Qo'shiqlar, Hodisalar va To'lovlar jadvallaridan tiklangan (she'r, namuna so'rovi, tayyor namuna, saqlanib qolgan xatolar, to'lov, to'liq qo'shiq).` : "Yangi qadamlar hali yozila boshlamagan (server qayta ishga tushgach boshlanadi).")
            : "Bu voronka mavjud jadvallardan (saytlar, videolar, to'lovlar, balans harakati) olinadi — butun tarix uchun bor."}</p></section>
      <section class="blk"><details open><summary><b>Qadamlar jadvali</b> <span class="muted">— bazadagi sonlar bilan solishtirish uchun</span></summary><div style="margin-top:10px">
        ${table(["Qadam", ">Yetib kelgan", ">Oldingidan", ">Boshidan", ">Tushib qoldi", ">Hodisasi yozilgan", ">Oldingi qadamdan beri (o'rtacha)"], detail)}</div></details></section>
      <section class="blk"><div class="bh"><h2>Qadamlar orasidagi vaqt</h2><p>birinchi hodisadan birinchi hodisagacha, ikkalasi ham bor odamlar bo'yicha</p></div>
        ${table(["Oraliq", ">Kishi", ">O'rtacha", ">Mediana"], spans, "Ma'lumot yo'q")}</section>
      ${d.nosample ? nosampleBlock(d.nosample) : ""}`;
    bindPeriod(main(), render);
    bindFunnel(main(), o);
    $$("[data-fprod]").forEach((b) => (b.onclick = () => { o.product = b.dataset.fprod; render(); }));
    $$("[data-fmode]").forEach((b) => (b.onclick = () => { o.mode = b.dataset.fmode; render(); }));
    $("#fn-src").onchange = (e) => { o.src = e.target.value; render(); };
    $("#fn-csv").onclick = () => download(`/api/admin/export/funnel.csv?${q}`);
    if ($("#ns-csv")) $("#ns-csv").onclick = () => download(`/api/admin/export/nosample.csv?${q}`);
    $$("[data-nsg]").forEach((tr) => (tr.onclick = () => {
      const g = d.nosample.groups.find((x) => x.key === tr.dataset.nsg);
      peopleSheet(`Namunasiz qolganlar: ${g.label}`, `${q}&group=${g.key}`);
    }));
  }

  // ---------------------------------------------------------------- 2. Trafik manbalari (statistika TZ, 4-band)
  // nomlash qoidasi kampaniya_video_lending: formadagi uch maydondan kod (server ham xuddi shunday yig'adi va tekshiradi)
  function composeCode(c, v, l) {
    c = (c || "").trim().toLowerCase().replace(/[\s-]+/g, "_").replace(/^_+|_+$/g, "");
    v = (v || "").trim().toLowerCase(); l = (l || "").trim().toLowerCase();
    if (!c && !v && !l) return "";
    const vm = v.match(/^v?(\d{1,4}[a-z]?)$/), lm = l.match(/^l?(\d{1,4}[a-z]?)$/);
    return `${c || "kampaniya"}_v${vm ? vm[1] : v || "?"}${l ? `_l${lm ? lm[1] : l}` : ""}`;
  }
  const money = (n) => (n ? fmt(n) : "—");
  const roiTag = (r) => (r == null ? "—" : tag(`${r > 0 ? "+" : ""}${r}%`, r >= 0 ? "good" : "bad"));
  const srcQuery = () => { const [f, t] = range(); return S.period.preset === "all" ? "all_time=1" : `from=${f}&to=${t}`; };
  const NO_CLICK = "Start bor, lekin bosish yozilmagan: reklama yoki lending t.me havolasiga to'g'ridan-to'g'ri olib boryapti. Tugmaga kuzatuv havolasini (/go/…) qo'ying.";
  // jadval katakchalari: havola qatori va kampaniya jami qatori uchun bir xil
  function srcCells(x, link) {
    const how = link ? (x.spend_src === "daily" ? `${fmt(x.spend_days)} kun` : x.spend_src === "total" ? "umumiy narx" : "") : "";
    return `<td class="r num">${fmt(x.clicks)}${link && !x.clicks && x.starts ? `<span class="sub c-warn" title="${esc(NO_CLICK)}">t.me havolasi</span>` : ""}</td>
      <td class="r num">${fmt(x.starts)}</td><td class="r num"><b>${fmt(x.users)}</b></td><td class="r num">${fmt(x.app)}</td>
      <td class="r num">${fmt(x.played)}</td><td class="r num">${fmt(x.buy_click)}</td><td class="r num">${fmt(x.pay_open)}</td>
      <td class="r num"><b>${fmt(x.bought)}</b><span class="sub">${x.conv}%</span></td><td class="r num">${money(x.revenue)}</td>
      <td class="r num">${money(x.spend)}${how ? `<span class="sub">${how}</span>` : ""}${link ? `<button type="button" class="link sm" data-spend="${x.id}">+ kiritish</button>` : ""}</td>
      <td class="r num">${money(x.cps)}</td><td class="r num">${money(x.cpb)}</td>
      <td class="r num">${roiTag(x.roi)}${x.ai_cost ? `<span class="sub" title="AI va musiqa xarajati (ROI dan ayirilgan)">AI ${fmt(x.ai_cost)}</span>` : ""}</td>
      <td class="r num">${x.users ? `${x.block_pct}%` : "—"}${x.blocked ? `<span class="sub">${fmt(x.blocked)} kishi</span>` : ""}</td>`;
  }
  // «Sayt/video» va «Qo'shiq» (yasaganlar) — havola kartasida va CSV da: jadval ekranga sig'ishi uchun
  const SRC_HEAD = ["Havola", ">Bosish", ">Start", ">Yangi", ">Ilovaga kirdi", ">Namuna eshitdi", ">Sotib olish bosdi",
    ">To'lov oynasi", ">Sotib oldi", ">Tushum, so'm", ">Xarajat, so'm", ">Start narxi", ">Xaridor narxi", ">ROI", ">Blok"];
  const pctCell = (n, p) => `<td class="r num"><b>${fmt(n)}</b><span class="sub">${p}%</span></td>`;
  const cohortCells = (x) => `<td class="r num"><b>${fmt(x.users)}</b></td>${pctCell(x.d1, x.d1_pct)}${pctCell(x.d3, x.d3_pct)}${pctCell(x.d7, x.d7_pct)}
    <td class="r num"><b>${fmt(x.bought)}</b><span class="sub">${x.bought_pct}%</span><div class="mini-bar"><i style="width:${Math.min(100, x.bought_pct)}%"></i></div></td>
    <td class="r num">${x.young ? fmt(x.young) : "—"}</td>`;

  async function sources(alive) {
    loading("Trafik manbalari");
    const q = srcQuery();
    const d = await api(`/api/admin/sources?${q}${S.showArchived ? "&archived=1" : ""}`);
    if (!alive()) return;
    const byId = Object.fromEntries(d.links.map((x) => [x.id, x]));
    const grouped = d.campaigns.some((c) => c.key);
    const linkName = (x) => `<b>${esc(x.name)}</b>${x.archived ? " " + tag("arxivda") : ""}${x.urls.report ? " " + tag(x.share_pct ? `hisobot ochiq, ${x.share_pct}%` : "hisobot ochiq", "pink") : ""}<span class="sub">${esc(x.code)}${x.note ? ` · ${esc(x.note)}` : ""}</span>`;
    // kampaniya qatori — jami; qoidaga mos kelmagan havolalar guruhida jami yo'q (ular bir-biriga aloqasiz)
    const campHead = (c, cells, ncol) => (!grouped ? "" : c.key
      ? `<tr class="camp"><td><b>${esc(c.label)}</b><span class="sub">kampaniya · ${c.links.length} ta havola · jami</span></td>${cells}</tr>`
      : `<tr class="camp"><td><b>${esc(c.label)}</b><span class="sub">kod nomlash qoidasiga mos emas</span></td><td colspan="${ncol - 1}"></td></tr>`);
    const linkRow = (id, cells) => `<tr class="click${grouped ? " in" : ""}" data-link="${id}"><td>${linkName(byId[id])}</td>${cells}</tr>`;
    const rows = d.campaigns.flatMap((c) => [campHead(c, srcCells(c, false), SRC_HEAD.length),
      ...c.links.map((id) => linkRow(id, srcCells(byId[id], true)))]).filter(Boolean);
    const cohort = d.campaigns.flatMap((c) => [campHead(c, cohortCells(c), 7), ...c.links.map((id) => linkRow(id, cohortCells(byId[id])))])
      .concat(d.groups.filter((g) => g.users).map((g) => `<tr><td>${esc(g.name)}<span class="sub">havolasiz</span></td>${cohortCells(g)}</tr>`)).filter(Boolean);
    const groups = d.groups.filter((g) => g.users).map((g) => `<tr><td>${esc(g.name)}</td><td class="r num"><b>${fmt(g.users)}</b></td><td class="r num">${fmt(g.app)}</td>
      <td class="r num">${fmt(g.created)}</td><td class="r num">${fmt(g.songs)}${g.song_bought ? `<span class="sub">${fmt(g.song_bought)} sotib oldi</span>` : ""}</td>
      <td class="r num">${fmt(g.played)}</td><td class="r num">${fmt(g.buy_click)}</td><td class="r num">${fmt(g.pay_open)}</td>
      <td class="r num"><b>${fmt(g.bought)}</b><span class="sub">${g.conv}%</span></td><td class="r num">${money(g.revenue)}</td>
      <td class="r num">${g.ai_cost ? fmt(g.ai_cost) : "—"}</td><td class="r num">${g.block_pct}%<span class="sub">${fmt(g.blocked)} kishi</span></td></tr>`);
    const sn = d.since || {};
    const sinceNote = sn.played ? `«Namuna eshitdi» va «Sotib olish bosdi» <b>${dt(sn.played)}</b> dan beri yoziladi — undan oldin kelganlarda bu ustunlar to'liq emas.`
      : "«Namuna eshitdi» va «Sotib olish bosdi» hali yozila boshlamagan (server qayta ishga tushgach boshlanadi).";
    main().innerHTML = `
      <div class="head"><div><h1>Trafik manbalari</h1><p>Har bir reklama videosi va lending o'z havolasi bilan: kim bosdi, Start bosdi, namunani eshitdi, sotib oldi — va reklama puli qaytyaptimi.</p></div>
        <div class="row"><button type="button" class="btn" id="src-csv">Jadval CSV</button><button type="button" class="btn" id="coh-csv">Kogorta CSV</button>
          <button type="button" class="btn" id="sp-csv">Xarajatlar CSV</button></div></div>
      ${periodBar([["all", "Butun davr"]])}
      <section class="blk"><div class="bh"><h2>Yangi havola</h2><p>Nomlash qoidasi: <b>kampaniya_video_lending</b> — masalan <code>qoshiq_v3_l1</code>, <code>qoshiq_v3_l2</code>, <code>tabrik_v1_l1</code></p></div>
        <form class="form" id="new-link">
          <div class="fields f4">
            <label class="f">Kampaniya <small>nomi, lotincha</small><input class="in" name="campaign" maxlength="18" placeholder="qoshiq" autocomplete="off"></label>
            <label class="f">Video <small>raqami</small><input class="in" name="video" maxlength="6" placeholder="3" autocomplete="off"></label>
            <label class="f">Lending <small>raqami, ixtiyoriy</small><input class="in" name="landing" maxlength="6" placeholder="1" autocomplete="off"></label>
            <label class="f">Kod <small id="nl-code-h">o'zi yig'iladi</small><input class="in" name="code" maxlength="24" pattern="[a-z0-9_]{2,24}" placeholder="qoshiq_v3_l1" autocomplete="off"></label>
          </div>
          <div class="fields">
            <label class="f">Nomi <small>ixtiyoriy — bo'sh bo'lsa kod</small><input class="in" name="name" maxlength="100" placeholder="Masalan: Qo'shiq reklamasi, 3-video, 1-lending"></label>
            <label class="f">Umumiy reklama narxi <small>so'm, ixtiyoriy</small><input class="in" name="cost" type="number" min="0" step="1000" placeholder="0"></label>
            <label class="f">Izoh <small>ixtiyoriy</small><input class="in" name="note" maxlength="255" placeholder="Qayerda, qachon joylandi"></label>
          </div>
          <div class="row"><button class="btn primary" type="submit">Havola yaratish</button><span class="muted" style="font-size:12.5px">Har bir video va har bir lending uchun alohida havola yarating — shunda qaysi biri xaridor olib kelayotgani ko'rinadi.
            Lending kodni botga Start parametri orqali uzatadi: lendingdagi tugmaga <b>kuzatuv havolasini</b> qo'ying — u bosishni ham sanaydi. Kunlik xarajat havola yaratilgach kiritiladi.</span></div>
        </form></section>
      <section class="blk"><div class="bh"><h2>Havolalar</h2><p>Odamlar — shu havola orqali botga birinchi marta kelganlar; ularning keyingi harakatlari va xaridlari ham shu manbaga yoziladi.
        <label style="margin-left:10px"><input type="checkbox" id="arch" ${S.showArchived ? "checked" : ""}> arxivdagilar</label></p></div>
        ${table(SRC_HEAD, rows, "Hali havola yo'q. Yuqorida birinchisini yarating.", "dense")}
        <p class="muted" style="font-size:12.5px;margin-top:8px"><b>Bosish</b> — kuzatuv havolasi (/go/…) orqali o'tganlar; t.me havolasi to'g'ridan-to'g'ri ochilgani uchun bosishni sanamaydi (Start va keyingi ustunlar baribir to'g'ri).
          <b>Start</b> — shu davrda shu havola bilan Start bosgan odamlar. <b>Xarajat</b> — tanlangan davrdagi kunlik yozuvlar yig'indisi (kunlik yozuv bo'lmasa — umumiy «Reklama narxi»).
          <b>Start narxi</b> = xarajat / Start bosganlar · <b>Xaridor narxi</b> = xarajat / sotib olganlar · <b>ROI</b> = (tushum − xarajat − AI va musiqa xarajati) / xarajat.
          <b>Blok</b> — shu manbadan kelganlardan hozir botni bloklab turganlar. Hammasi odam bo'yicha, takrorlarsiz; admin va sinov akkauntlari (${fmt(d.excluded)} ta) sanalmaydi.
          ${sinceNote} «To'lov oynasi» eski to'lovlardan tiklangan — butun tarix uchun bor. Sayt/video va qo'shiq yasaganlar — havolaga bosilganda ochiladigan kartada va «Jadval CSV» da.</p></section>
      <section class="blk"><div class="bh"><h2>Kogorta: kelgandan keyin qancha vaqtda sotib oldi</h2><p>shu davrda kelgan odamlardan birinchi xaridini kelgandan 1, 3 va 7 kun (24, 72, 168 soat) ichida qilganlar</p></div>
        ${table(["Manba", ">Kelgan", ">1 kun ichida", ">3 kun ichida", ">7 kun ichida", ">Hozirgacha", ">7 kuni to'lmagan"], cohort, "Bu davrda hech kim kelmagan", "dense")}
        <p class="muted" style="font-size:12.5px;margin-top:8px">«Odamlar 1–2 kun o'rganib, keyin sotib oladi» degan taxminni tekshirish uchun: 1 kun va 3 kun ustunlari orasidagi farq — o'ylab yurib sotib olganlar.
          Xarid — tasdiqlangan to'lov yoki balansdan xizmat sotib olish (qaysi biri oldin bo'lsa). «7 kuni to'lmagan» — 7 kundan kam oldin kelganlar: ular uchun 7 kunlik raqam hali o'sishi mumkin.</p></section>
      <section class="blk"><div class="bh"><h2>Boshqa manbalar</h2><p>Havolasiz kelganlar</p></div>
        ${table(["Manba", ">Yangi", ">Ilovaga kirdi", ">Sayt/video", ">Qo'shiq", ">Namuna eshitdi", ">Sotib olish bosdi", ">To'lov oynasi", ">Sotib oldi", ">Tushum, so'm", ">AI xarajati", ">Blok"], groups, "Ma'lumot yo'q", "dense")}</section>`;
    bindPeriod(main(), render);
    $("#arch").onchange = (e) => { S.showArchived = e.target.checked; render(); };
    $("#src-csv").onclick = () => download(`/api/admin/export/sources.csv?${q}`);
    $("#coh-csv").onclick = () => download(`/api/admin/export/sourcecohort.csv?${q}`);
    $("#sp-csv").onclick = () => download(`/api/admin/export/adspend.csv?${q}`);
    const form = $("#new-link");
    const fe = form.elements;
    const syncCode = () => {
      const c = composeCode(fe.campaign.value, fe.video.value, fe.landing.value);
      if (fe.code.readOnly && !c) fe.code.value = "";
      fe.code.readOnly = !!c; if (c) fe.code.value = c;
      $("#nl-code-h").textContent = c ? "o'zi yig'iladi" : "ixtiyoriy, eski usul";
    };
    ["campaign", "video", "landing"].forEach((k) => (fe[k].oninput = syncCode));
    form.onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(form), rule = !!(fd.get("campaign") || fd.get("video") || fd.get("landing"));
      if (rule && !(fd.get("campaign") && fd.get("video"))) { toast("Kampaniya va video raqamini kiriting (lending ixtiyoriy)", true); return; }
      const code = String(fd.get("code") || "").trim();
      const name = String(fd.get("name") || "").trim() || code;
      if (!name) { toast("Nomini yoki kampaniya va videoni kiriting", true); return; }
      const body = { name, cost: +fd.get("cost") || 0, note: fd.get("note") || "" };
      if (rule) Object.assign(body, { campaign: fd.get("campaign"), video: fd.get("video"), landing: fd.get("landing") || "" });
      else body.code = code;
      try {
        const r = await api("/api/admin/links", body);
        toast(r.campaign ? `Havola yaratildi: ${r.code}` : `Havola yaratildi: ${r.code} (nomlash qoidasiga mos emas)`); await render();
        const x = (await api(`/api/admin/sources?all_time=1&archived=1`)).links.find((l) => l.id === r.id);
        if (x) linkSheet(x);
      } catch (err) { toast(err.message, true); }
    };
    $$("[data-link]").forEach((tr) => (tr.onclick = () => linkSheet(byId[+tr.dataset.link])));
    $$("[data-spend]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); adSpendSheet(byId[+b.dataset.spend]); }));
  }
  function linkSheet(x) {
    const how = x.spend_src === "daily" ? `kunlik yozuvlar, ${fmt(x.spend_days)} kun` : x.spend_src === "total" ? "umumiy «Reklama narxi»" : "";
    sheet(`<h2 class="big" id="sheet-title">${esc(x.name)}</h2><p class="muted">Kod: ${esc(x.code)}${x.campaign ? ` · kampaniya <b>${esc(x.campaign)}</b> · video ${esc(x.video)} · ${x.landing ? `lending ${esc(x.landing)}` : "lendingsiz"}` : " · nomlash qoidasiga mos emas"} · yaratilgan ${day(x.created_at)}</p>
      <section><h3>Havolalar</h3>
        <div class="copy"><span>Kuzatuv havolasi:</span><code>${esc(x.urls.go)}</code><button type="button" data-copy="${esc(x.urls.go)}">Nusxa</button></div>
        <div class="copy" style="margin-top:6px"><span>Bot havolasi:</span><code>${esc(x.urls.bot)}</code><button type="button" data-copy="${esc(x.urls.bot)}">Nusxa</button></div>
        <p class="muted" style="font-size:12.5px;margin-top:8px"><b>Kuzatuv havolasini</b> lendingdagi «Botga o'tish» tugmasiga, reklama, kanal posti va bannerlarga qo'ying: u bosishni yozadi va darhol botni
          shu kod bilan ochadi (Start parametri <code>src_${esc(x.code)}</code>). <b>Bot havolasi</b> (t.me/…) botni to'g'ridan-to'g'ri ochadi — bosish sanalmaydi, lekin Start va keyingi harakatlar baribir shu havolaga yoziladi.</p>
        ${x.starts && !x.clicks ? `<p class="note" style="margin-top:8px">Bu davrda ${fmt(x.starts)} kishi Start bosgan, lekin birorta bosish yozilmagan — reklama yoki lending t.me havolasiga to'g'ridan-to'g'ri olib boryapti. Tugmani kuzatuv havolasiga almashtiring.</p>` : ""}</section>
      <section><h3>Natija (tanlangan davr)</h3><div class="stat-line">
        <div><b>${fmt(x.clicks)}</b><span>bosish</span></div><div><b>${fmt(x.starts)}</b><span>start</span></div>
        <div><b>${fmt(x.users)}</b><span>yangi foydalanuvchi</span></div><div><b>${fmt(x.app)}</b><span>ilovaga kirdi</span></div>
        <div><b>${fmt(x.created)}</b><span>sayt/video yasadi</span></div><div><b>${fmt(x.songs)}</b><span>qo'shiq tayyorladi${x.song_bought ? ` · ${fmt(x.song_bought)} sotib oldi` : ""}</span></div>
        <div><b>${fmt(x.played)}</b><span>namunani eshitdi</span></div><div><b>${fmt(x.buy_click)}</b><span>«sotib olish»ni bosdi</span></div>
        <div><b>${fmt(x.pay_open)}</b><span>to'lov oynasini ochdi</span></div><div><b>${fmt(x.bought)}</b><span>sotib oldi</span></div>
        <div><b>${som(x.revenue)}</b><span>tushum</span></div><div><b>${x.block_pct}%</b><span>botni bloklagan (${fmt(x.blocked)} kishi)</span></div></div>
        ${x.spend ? `<p style="margin-top:10px">Xarajat: <b>${som(x.spend)}</b> <span class="muted">(${how})</span> · Start narxi: <b>${som(x.cps)}</b> · bir foydalanuvchi: <b>${som(x.cpu)}</b> · bir xaridor: <b>${som(x.cpb)}</b>
          · AI va musiqa: <b>${som(x.ai_cost)}</b> · ROI: <b>${x.roi}%</b></p>` : `<p class="muted" style="margin-top:10px">Xarajat kiritilmagan — Start narxi, xaridor narxi va ROI hisoblanmaydi.</p>`}</section>
      <section><h3>Reklama xarajati</h3><p class="muted" style="font-size:13px;margin-bottom:8px">Kunma-kun, so'mda yoki dollarda. Tanlangan davrdagi kunlar yig'indisi «Xarajat» ustuniga tushadi.</p>
        <button type="button" class="btn primary" id="ls-spend">Kunlik xarajatni kiritish</button></section>
      <section><h3>Hamkor uchun hisobot</h3>
        <p class="muted" style="font-size:13px;margin-bottom:8px">Kanal egasi yoki bloger faqat shu havola natijalarini ko'radi: bosish, start, yangi foydalanuvchi, ilovaga kirgan, yasagan, sotib olgan va tushum. Hamkor ulushi (%) yozilsa, uning daromadi ham hisoblab ko'rsatiladi. Ismlar va shaxsiy ma'lumotlar ko'rinmaydi.</p>
        ${x.urls.report ? `<div class="copy"><code>${esc(x.urls.report)}</code><button type="button" data-copy="${esc(x.urls.report)}">Nusxa</button><button type="button" data-open="${esc(x.urls.report)}">Ochish</button></div>
          <div class="row" style="margin-top:8px"><button type="button" class="btn sm" id="sh-renew">Yangi havola (eskisi ishlamay qoladi)</button><button type="button" class="btn sm bad" id="sh-off">Hisobotni o'chirish</button></div>`
          : `<button type="button" class="btn" id="sh-on">Hisobot havolasini yaratish</button>`}</section>
      <section><h3>Tahrirlash</h3><form class="form" id="edit-link">
        <label class="f">Nomi<input class="in" name="name" value="${esc(x.name)}" maxlength="100" required></label>
        <label class="f">Umumiy reklama narxi (so'm) <small>kunlik xarajat umuman kiritilmagan bo'lsa, hisobda shu ishlatiladi</small><input class="in" name="cost" type="number" min="0" step="1000" value="${x.cost || ""}"></label>
        <label class="f">Izoh<input class="in" name="note" value="${esc(x.note || "")}" maxlength="255"></label>
        <label class="f">Hamkor ulushi, % <small>tushumdan hamkorga beriladigan foiz; hisobotda «Sizning ulushingiz» bo'lib chiqadi</small><input class="in" name="share_pct" type="number" min="0" max="100" step="1" value="${x.share_pct || ""}" placeholder="0"></label>
        <div class="row"><button class="btn primary" type="submit">Saqlash</button>
          <button class="btn" type="button" id="arch-link">${x.archived ? "Arxivdan chiqarish" : "Arxivga olish"}</button></div>
      </form></section>`);
    $$("[data-copy]", $("#sheet")).forEach((b) => (b.onclick = () => copy(b.dataset.copy)));
    $$("[data-open]", $("#sheet")).forEach((b) => (b.onclick = () => openExternal(b.dataset.open)));
    $("#ls-spend").onclick = () => adSpendSheet(x);
    const share = async (body, msg, copyAfter) => {
      try {
        const r = await api(`/api/admin/links/${x.id}/share`, body);
        x.urls = r.urls; toast(msg); linkSheet(x);
        if (copyAfter && r.urls.report) copy(r.urls.report);
      } catch (err) { toast(err.message, true); }
    };
    if ($("#sh-on")) $("#sh-on").onclick = () => share({ enable: true }, "Hisobot havolasi yaratildi", true);
    if ($("#sh-renew")) $("#sh-renew").onclick = () => confirm("Eski havola ishlamay qoladi. Davom etasizmi?") && share({ enable: true, renew: true }, "Yangi havola tayyor", true);
    if ($("#sh-off")) $("#sh-off").onclick = () => confirm("Hamkor hisobotni ko'ra olmay qoladi. O'chirasizmi?") && share({ enable: false }, "Hisobot o'chirildi");
    $("#edit-link").onsubmit = async (e) => {
      e.preventDefault(); const fd = new FormData(e.target);
      try { await api(`/api/admin/links/${x.id}`, { name: fd.get("name"), cost: +fd.get("cost") || 0, note: fd.get("note") || "", share_pct: Math.min(100, Math.max(0, Math.round(+fd.get("share_pct") || 0))) }, "PATCH"); toast("Saqlandi"); closeSheet(); render(); }
      catch (err) { toast(err.message, true); }
    };
    $("#arch-link").onclick = async () => {
      try { await api(`/api/admin/links/${x.id}`, { archived: !x.archived }, "PATCH"); closeSheet(); render(); } catch (err) { toast(err.message, true); }
    };
  }
  // kunlik reklama xarajati: sana + summa + valyuta (so'm yoki dollar, kurs — umumiy sozlama); bir kun — bitta yozuv
  async function adSpendSheet(x) {
    sheet(`<p class="boot">Yuklanmoqda…</p>`);
    let d;
    try { d = await api(`/api/admin/links/${x.id}/spend`); } catch (e) { $("#sheet-body").innerHTML = `<p class="note">${esc(e.message)}</p>`; return; }
    const usd = (n) => `$${Number(n).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
    const draw = (keep) => {
      const today = localISO(new Date());
      $("#sheet-body").innerHTML = `<button type="button" class="link" id="sp-back">‹ ${esc(x.name)}</button>
        <h2 class="big" id="sheet-title" style="margin-top:6px">Reklama xarajati</h2>
        <p class="muted">${esc(x.code)} · kunma-kun, qo'lda. Bir kun uchun bitta yozuv: shu kunni qayta kiritsangiz, summa yangilanadi.</p>
        <form class="form" id="sp-form" style="margin-top:14px">
          <div class="fields"><label class="f">Sana<input class="in" type="date" name="day" value="${keep ? keep.day : today}" max="${today}" required></label>
            <label class="f">Summa<input class="in" name="amount" type="number" min="0" step="any" required placeholder="0" inputmode="decimal"></label>
            <label class="f">Valyuta<select class="in" name="currency"><option value="som">so'm</option><option value="usd"${keep && keep.currency === "usd" ? " selected" : ""}>dollar ($)</option></select></label></div>
          <div class="row"><button class="btn primary" type="submit">Saqlash</button>
            <span class="muted" style="font-size:12.5px">Dollar kursi: 1 $ = <b>${fmt(d.usd_som)}</b> so'm · <button type="button" class="link" id="sp-rate">o'zgartirish</button></span></div>
        </form>
        <section><h3>Kiritilgan kunlar</h3>
          ${table(["Sana", ">Summa", ">So'mda", ""], d.rows.map((r) => `<tr><td class="num">${dayISO(r.day)}</td>
            <td class="r num">${r.currency === "usd" ? `${usd(r.amount)}<span class="sub">kurs ${fmt(r.rate)}</span>` : `${fmt(r.amount)} so'm`}</td>
            <td class="r num"><b>${fmt(r.som)}</b></td><td class="r"><button type="button" class="link" data-del="${r.id}">O'chirish</button></td></tr>`), "Hali kiritilmagan")}
          <p class="muted" style="font-size:12.5px;margin-top:8px">Jami: <b>${som(d.total)}</b>.
            ${!d.rows.length && d.cost ? `Kunlik yozuv yo'q — hisobda eski umumiy «Reklama narxi» (${som(d.cost)}) ishlatilyapti; birinchi kunlik yozuvdan keyin faqat kunliklar sanaladi.` : ""}
            Dollar kursi o'zgarsa, oldin kiritilgan kunlar o'z kursida qoladi (kerak bo'lsa o'sha kunni qayta kiriting).</p></section>`;
      $("#sp-back").onclick = async () => {  // havola kartasi yangi xarajat bilan
        try { x = (await api(`/api/admin/sources?${srcQuery()}&archived=1`)).links.find((l) => l.id === x.id) || x; } catch (e) { /* eskisi qoladi */ }
        linkSheet(x);
      };
      $("#sp-rate").onclick = async () => {
        const v = prompt("1 dollar necha so'm? (Bu kurs AI xarajatlari hisobida ham ishlatiladi)", d.usd_som);
        if (v == null) return;
        const n = Math.round(+String(v).replace(/[\s,]/g, ""));
        if (!(n >= 1000 && n <= 100000)) { toast("Kurs 1 000 va 100 000 so'm oralig'ida bo'lsin", true); return; }
        try { const r = await api("/api/admin/costs/rates", { usd_som: n }); d.usd_som = Math.round(r.rates.usd_som); toast("Kurs saqlandi"); draw(); } catch (err) { toast(err.message, true); }
      };
      $("#sp-form").onsubmit = async (e) => {
        e.preventDefault(); const fd = new FormData(e.target);
        const body = { day: fd.get("day"), amount: +String(fd.get("amount")).replace(",", "."), currency: fd.get("currency") };
        if (!(body.amount > 0)) { toast("Summani kiriting", true); return; }
        try {
          const r = await api(`/api/admin/links/${x.id}/spend`, body);
          d = r; toast(r.saved.updated ? `${dayISO(r.saved.day)} yangilandi` : "Saqlandi"); draw({ day: addDays(body.day, 1) > today ? body.day : addDays(body.day, 1), currency: body.currency }); render();
        } catch (err) { toast(err.message, true); }
      };
      $$("[data-del]", $("#sheet")).forEach((b) => (b.onclick = async () => {
        if (!confirm("Shu kunning xarajatini o'chirasizmi?")) return;
        try { d = await api(`/api/admin/links/${x.id}/spend/${b.dataset.del}`, null, "DELETE"); toast("O'chirildi"); draw(); render(); } catch (err) { toast(err.message, true); }
      }));
    };
    draw();
  }

  // ---------------------------------------------------------------- 3. Sotuvlar
  async function sales(alive) {
    loading("Sotuvlar");
    const d = await api(`/api/admin/sales?${qs()}`);
    if (!alive()) return;
    const maxPaid = Math.max(1, ...d.templates.map((x) => x.created));
    const tpl = d.templates.slice(0, 40).map((x) => `<tr>
      <td>${x.thumb ? `<img class="thumb" src="${esc(x.thumb)}" alt="" loading="lazy">` : ""}<b>${esc(x.name)}</b><span class="sub">${esc(x.section)} · ${esc(x.tier)}</span></td>
      <td class="r num">${fmt(x.created)}<div class="mini-bar"><i style="width:${(100 * x.created) / maxPaid}%"></i></div></td>
      <td class="r num"><b>${fmt(x.paid)}</b></td><td class="r num">${x.conv}%</td><td class="r num">${som(x.revenue)}</td></tr>`);
    const secs = d.sections.sort((a, b) => b.created - a.created).map((x) => `<tr><td>${esc(x.name)}</td><td class="r num">${fmt(x.created)}</td><td class="r num"><b>${fmt(x.paid)}</b></td><td class="r num">${x.conv}%</td><td class="r num">${som(x.revenue)}</td></tr>`);
    const tiers = d.tiers.sort((a, b) => b.paid - a.paid).map((x) => `<tr><td>${esc(x.name)}</td><td class="r num">${fmt(x.created)}</td><td class="r num"><b>${fmt(x.paid)}</b></td><td class="r num">${som(x.revenue)}</td></tr>`);
    const des = d.designs.slice(0, 30).map((x) => `<tr><td><b>${esc(x.name)}</b><span class="sub">${esc(x.section)}</span></td><td class="r num">${fmt(x.free)}</td><td class="r num"><b>${fmt(x.paid)}</b></td><td class="r num">${fmt(x.unpaid)}</td></tr>`);
    const vs = d.video_sections.map((x) => `<tr><td>${esc(x.name)}</td><td class="r num">${fmt(x.free)}</td><td class="r num"><b>${fmt(x.paid)}</b></td><td class="r num">${fmt(x.unpaid)}</td></tr>`);
    const LANGS = { uz: "O'zbekcha (lotin)", cy: "Ўзбекча (кирилл)", ru: "Ruscha", en: "Inglizcha", kaa: "Qoraqalpoqcha", tg: "Tojikcha", kk: "Qozoqcha" };
    const totalL = d.langs.reduce((a, b) => a + b.n, 0);
    const langs = d.langs.map((x) => `<tr><td>${esc(LANGS[x.lang] || x.lang)}</td><td class="r num">${fmt(x.n)}</td><td class="r num">${pctOf(x.n, totalL)}%</td></tr>`);
    const unpaid = d.unpaid.map((x) => `<tr><td><b>${esc(x.title)}</b><span class="sub">${esc(x.tier)} · ${som(x.price)}${x.status === "pending" ? " · to'lov tekshirilmoqda" : ""}</span></td>
      <td>${userLink(x)}</td><td class="num">${ago(x.created_at)}</td>
      <td class="r"><a class="btn sm" href="${esc(x.url)}" target="_blank" rel="noopener">Ko'rish</a> <button type="button" class="btn sm" data-user="${x.owner}">Mijoz</button></td></tr>`);
    main().innerHTML = `
      <div class="head"><div><h1>Sotuvlar</h1><p>${periodLabel()} · qaysi shablonlar yasaladi va sotiladi</p></div>
        <button type="button" class="btn" id="exp-sites">Taklifnomalar CSV</button></div>
      ${periodBar()}
      <section class="blk"><div class="bh"><h2>Web-sayt shablonlari</h2><p>Yasalgan va sotib olingan taklifnomalar</p></div>
        ${table(["Shablon", ">Yasaldi", ">Sotildi", ">Konversiya", ">Tushum"], tpl)}</section>
      <section class="blk two">
        <div><div class="bh"><h2>Bo'limlar</h2></div>${table(["Bo'lim", ">Yasaldi", ">Sotildi", ">Konv.", ">Tushum"], secs)}</div>
        <div><div class="bh"><h2>Tariflar</h2></div>${table(["Tarif", ">Yasaldi", ">Sotildi", ">Tushum"], tiers)}</div>
      </section>
      <section class="blk two">
        <div><div class="bh"><h2>Video dizaynlar</h2></div>${table(["Dizayn", ">Bepul", ">Pullik", ">To'lanmagan"], des)}</div>
        <div><div class="bh"><h2>Video bo'limlari</h2></div>${table(["Bo'lim", ">Bepul", ">Pullik", ">To'lanmagan"], vs)}
          <div class="bh" style="margin-top:20px"><h2>Foydalanuvchilar tili</h2></div>${table(["Til", ">Kishi", ">Ulush"], langs)}</div>
      </section>
      <section class="blk"><div class="bh"><h2>Yasalgan, ammo sotib olinmagan taklifnomalar</h2><p>Bu odamlarga yozib, yordam taklif qilish mumkin (oxirgi 100 ta)</p></div>
        ${table(["Taklifnoma", "Mijoz", "Qachon", ""], unpaid, "Bu davrda sotib olinmagan taklifnoma yo'q")}</section>`;
    bindPeriod(main(), render);
    $("#exp-sites").onclick = () => download("/api/admin/export/sites.csv");
    $$("[data-user]").forEach((b) => (b.onclick = () => userSheet(+b.dataset.user)));
  }

  // ---------------------------------------------------------------- 4. To'lovlar
  // «new» — mijoz to'lov oynasini ochgan, lekin pul to'lamagan (Click tugallanmagan). Pul tushmagan, tasdiqlanmaydi.
  const PST = { pending: ["Chekni tekshirish", "warn"], new: ["To'lanmagan", ""], approved: ["To'landi", "good"], rejected: ["Rad etilgan", "bad"], cancelled: ["Bekor qilingan", "bad"] };
  const pstOf = (p) => p.status === "approved" ? [p.provider === "click" ? "To'landi · Click" : p.provider === "card" ? (p.auto ? "Karta · avtomatik" : "Karta · qo'lda") : "Tasdiqlangan (chek)", "good"]
    : p.status === "new" ? [p.provider === "click" ? "Click'da to'lanmadi" : "To'lanmagan", ""] : PST[p.status] || [p.status, ""];
  // vaqt oralig'i: soniyadan kungacha, qisqa ko'rinishda
  const dur = (s) => (s == null ? "—" : s < 90 ? `${Math.round(s)} soniya` : s < 5400 ? `${Math.round(s / 60)} daqiqa` : s < 172800 ? `${Math.round(s / 360) / 10} soat` : `${Math.round(s / 8640) / 10} kun`);
  const hm = (s) => { const d = fromUTC(s); return d ? d.toLocaleTimeString("ru-RU", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }) : ""; };
  // «To'lovlar» tepasidagi xulosa (TZ 3-band): hammasi ODAMLAR soni, Toshkent vaqti
  function payStatsBlock(d) {
    const t = d.total, rp = d.repeat, tm = d.time, sv = d.survey, st = d.settings, sh = d.sheet;
    const share = (n, of) => `${pctOf(n, of)}%<div class="mini-bar"><i style="width:${Math.min(100, pctOf(n, of))}%"></i></div>`;
    const cut = (title, rows) => `<div><div class="bh"><h2>${title}</h2></div>${table(["", ">Oynani ochdi", ">To'ladi", ">Ulushi"], rows.map((x) => `<tr>
      <td>${esc(x.label)}${x.attempts > x.people ? `<span class="sub">${fmt(x.attempts)} ta urinish</span>` : ""}</td>
      <td class="r num">${fmt(x.people)}</td><td class="r num">${fmt(x.paid)}</td><td class="r num">${share(x.paid, x.people)}</td></tr>`), "Bu davrda to'lov oynasi ochilmagan")}</div>`;
    const stops = (title, s) => `<div><div class="bh"><h2>${title}</h2><p>${fmt(s.people)} kishi shu usulni tanladi</p></div>${table(["Eng uzoq yetgan qadami", ">Kishi", ">Ulushi"], s.steps.map((x) => `<tr>
      <td>${x.key === "paid" ? tag(x.label, "good") : esc(x.label)}</td><td class="r num">${fmt(x.n)}</td><td class="r num">${share(x.n, s.people)}</td></tr>`))}</div>`;
    const since = d.since ? `Qadamlar vaqti («Click sahifasiga o'tdi», «qaytdi», «karta raqami ko'rsatildi», summa tanlash oynasi) va so'rov <b>${dt(d.since)}</b> dan beri yoziladi; undan oldingi to'lovlarda nima uchunligi, usuli, cheki va natijasi mavjud yozuvlardan tiklangan.`
      : "Qadamlar hali yozila boshlamagan (server qayta ishga tushgach boshlanadi).";
    return `
      <section class="blk"><div class="bh"><h2>To'lov bosqichi: kim ochdi, kim to'ladi</h2>
        <div class="row"><button type="button" class="btn sm" data-pexp="paystats">Xulosa CSV</button></div></div>
        <div class="now">
          <div><b>${fmt(t.people)}</b><span>kishi to'lov oynasini ochdi · ${fmt(t.attempts)} ta urinish</span></div>
          <div class="${t.people && !t.paid ? "alert" : ""}"><b>${fmt(t.paid)} <small style="font-size:14px;font-weight:600">(${t.conv}%)</small></b><span>kishi to'ladi · ${som(t.paid_sum)}</span></div>
          <div><b>${dur(tm.median_s)}</b><span>oynani ochishdan to'lovgacha (mediana) · o'rtacha ${dur(tm.avg_s)}${tm.click.n ? ` · Click ${dur(tm.click.median_s)}` : ""}${tm.card.n ? ` · karta ${dur(tm.card.median_s)}` : ""}</span></div>
          <div><b>${String(rp.avg).replace(".", ",")}</b><span>urinish bir odamga · ${fmt(rp.multi)} kishi qayta urindi, ${fmt(rp.multi_unpaid)} tasi baribir to'lamadi</span></div>
        </div>
        <p class="muted" style="font-size:12.5px;margin-top:8px">Sanash odam bo'yicha: bir kishi besh marta urinsa ham bitta. Admin va sinov akkauntlari (${fmt(d.excluded)} ta) hisobga kirmaydi. ${since}
          ${sh.people ? `<br>Ilovada summa tanlash oynasini <b>${fmt(sh.people)}</b> kishi ko'rdi, shundan <b>${fmt(sh.chose)}</b> tasi (${pctOf(sh.chose, sh.people)}%) summani tanlab, to'lov oynasini ochdi.` : ""}</p>
      </section>
      <section class="blk two">
        ${stops("Click: qaysi qadamda to'xtashdi", d.stops.click)}
        ${stops("Karta: qaysi qadamda to'xtashdi", d.stops.card)}
      </section>
      <p class="muted" style="font-size:12.5px;margin-top:8px">Usul tanlamay chiqib ketganlar (oynani ochdi, Click'ni ham, kartani ham bosmadi): <b>${fmt(d.stops.none)}</b> kishi (${pctOf(d.stops.none, t.people)}%).
        Bir kishi ikkala usulni ham sinagan bo'lsa, ikkala jadvalda sanaladi.</p>
      <section class="blk two">${cut("Mahsulot bo'yicha", d.by_product)}${cut("To'lov usuli bo'yicha", d.by_method)}</section>
      <section class="blk two">${cut("Summa bo'yicha", d.by_amount)}
        <div><div class="bh"><h2>Takroriy urinishlar</h2></div>${table(["Bir odam necha marta urindi", ">Kishi", ">Ulushi"], rp.dist.map((x) => `<tr>
          <td>${esc(x.label)}</td><td class="r num">${fmt(x.n)}</td><td class="r num">${share(x.n, t.people)}</td></tr>`))}
          <p class="muted" style="font-size:12.5px;margin-top:8px">Eng ko'pi ${fmt(rp.max)} marta.${rp.paid_avg_try ? ` To'laganlar o'rtacha ${String(rp.paid_avg_try).replace(".", ",")}-urinishda to'lagan; ${fmt(rp.paid_first_try)} tasi birinchi urinishdayoq.` : ""}</p></div>
      </section>
      <section class="blk"><details><summary><b>Kunlar bo'yicha</b> <span class="muted">— oynani ochganlar va to'laganlar</span></summary><div style="margin-top:10px">
        ${table(["Kun", ">Oynani ochdi", ">To'ladi", ">Ulushi"], d.by_day.slice().reverse().map((x) => `<tr><td class="num">${esc(x.label.split("-").reverse().join("."))}</td>
          <td class="r num">${fmt(x.people)}</td><td class="r num">${fmt(x.paid)}</td><td class="r num">${share(x.paid, x.people)}</td></tr>`), "Bu davrda to'lov oynasi ochilmagan")}</div></details></section>
      <section class="blk two">
        <div><div class="bh"><h2>Balans to'ldirib, hech narsa sotib olmaganlar</h2><div class="row"><button type="button" class="btn sm" data-pexp="payidle">CSV</button></div></div>
          <div class="stat-line" style="margin-bottom:10px"><div><b>${fmt(d.idle.people)}</b><span>kishi (${fmt(d.idle.payers)} to'lovchidan)</span></div>
            <div><b class="c-warn">${som(d.idle.balance)}</b><span>balansida turgan qoldiq pul</span></div></div>
          ${table(["Mijoz", ">To'lagan", ">Qoldiq balans"], d.idle.rows.slice(0, 12).map((x) => `<tr class="click" data-user="${x.id}">
            <td>${userLink(x)}<span class="sub">oxirgi to'lov: ${dt(x.last_paid_at)}</span></td><td class="r num">${som(x.paid_sum)}</td><td class="r num"><b>${som(x.balance)}</b></td></tr>`), "Bunday mijoz yo'q")}
          ${d.idle.people > 12 ? `<p class="muted" style="font-size:12.5px;margin-top:8px">Qoldig'i eng ko'p 12 kishi ko'rsatildi — to'liq ro'yxat CSV da.</p>` : ""}
          <p class="muted" style="font-size:12.5px;margin-top:8px">Shu davrda pul to'lab, to'lovdan keyin birorta ham xarid qilmaganlar. Qoldiq — hozirgi balans.</p></div>
        <div><div class="bh"><h2>«Nega to'lamadingiz» so'rovi</h2><div class="row"><button type="button" class="btn sm" data-pexp="paywhy">Javoblar CSV</button></div></div>
          <label class="row sw"><input type="checkbox" id="ps-survey" ${st.survey_on ? "checked" : ""}> So'rov yoqilgan</label>
          <p class="muted" style="font-size:12.5px;margin:6px 0 10px">To'lov oynasini ochib, ${st.delay_min} daqiqa ichida to'lamagan odamga bot bitta savol yuboradi. Bir odamga umrida bir marta; faqat ${st.from_hour}:00–${st.to_hour}:00 (Toshkent) oralig'ida — tunda ochgan bo'lsa ertalab; botni bloklagan, shu orada to'lagan yoki cheki tekshiruvda turganlarga yuborilmaydi.</p>
          <div class="stat-line" style="margin-bottom:10px"><div><b>${fmt(sv.sent)}</b><span>kishiga yuborildi${sv.failed ? ` · ${fmt(sv.failed)} tasiga yetmadi` : ""}</span></div>
            <div><b>${fmt(sv.answered)}</b><span>kishi javob berdi (${sv.answer_rate}%)</span></div></div>
          ${table(["Javob", ">Kishi", ">Ulushi"], sv.answers.map((x) => `<tr><td>${esc(x.label)}</td><td class="r num">${fmt(x.n)}</td><td class="r num">${share(x.n, sv.answered)}</td></tr>`))}
          <div class="row" style="margin-top:10px"><button type="button" class="btn sm" id="ps-test">O'zimga sinov yuborish</button>
            <span class="muted" style="font-size:12.5px">${sv.last_run ? `oxirgi tekshiruv: ${ago(sv.last_run)}` : ""}</span></div></div>
      </section>
      <section class="blk"><details><summary><b>Statistika sozlamalari</b> <span class="muted">— sinov akkauntlari: ${fmt(st.test_ids.length)} ta · Click kuzatuvi ${st.click_track ? "yoqilgan" : "o'chirilgan"}</span></summary>
        <form class="form" id="ps-set" style="margin-top:12px">
          <label class="f">Sinov akkauntlari (Telegram id) <small>vergul, bo'sh joy yoki yangi qator bilan ajrating. Adminlar (${esc(st.admins.join(", ") || "yo'q")}) o'zi chiqarib tashlangan.</small>
            <textarea class="in" name="test_ids" rows="2" maxlength="4000" style="min-height:64px" placeholder="123456789, 987654321">${esc(st.test_ids.join(", "))}</textarea></label>
          <label class="row" style="font-size:13px"><input type="checkbox" name="click_track" ${st.click_track ? "checked" : ""}> Click havolasi kuzatuv orqali ochilsin: «Click sahifasiga o'tdi» va «qaytdi» qadamlari yoziladi</label>
          <p class="muted" style="font-size:12.5px">Kuzatuv yoqilganda bot va ilovadagi Click tugmasi avval saytimizga, u yerdan darhol Click sahifasiga o'tkazadi${st.click_tracked ? "" : " (hozir ishlamayapti: Click sozlanmagan yoki sayt HTTPS da emas)"}. Click sahifasi ochilmay qolsa — o'chirib qo'ying: mijoz to'g'ridan-to'g'ri Click'ka o'tadi, faqat bu ikki qadam sanalmaydi.
            Ro'yxatdagi akkauntlar shu xulosada sanalmaydi va ularga so'rov yuborilmaydi; jadvalda «sinov» belgisi bilan ko'rinadi.</p>
          <div class="row"><button class="btn primary" type="submit">Saqlash</button></div>
        </form></details></section>`;
  }
  async function payments(alive) {
    loading("To'lovlar");
    S.payStatus = S.payStatus || "approved";
    const [f, t] = range();
    const pq = S.period.preset === "all" ? "all_time=1" : `from=${f}&to=${t}`;
    const [d, cp, ps] = await Promise.all([api(`/api/admin/payments?status=${S.payStatus}&limit=300&${pq}`), api("/api/admin/cardpay").catch(() => null),
      api(`/api/admin/paystats?${pq}`).catch((e) => ({ error: e.message }))]);
    if (!alive()) return;
    if (S.payStatus === "pending") { S.pending = d.payments.length; nav(); }
    const stepCell = (p) => `${p.step === "paid" ? tag("To'ladi", "good") : esc(p.step_label)}
      <span class="sub">${p.timeline.map((x) => `${hm(x.at)} ${esc(x.label)}`).join(" → ")}${p.took_s != null ? ` · ${dur(p.took_s)}da` : ""}</span>`;
    const rows = d.payments.map((p) => `<tr>
      <td class="num">#${p.id}<span class="sub">${dt(p.created_at)}</span></td>
      <td>${userLink(p)}${p.test ? ` ${tag("sinov", "warn")}` : ""}</td>
      <td class="r num"><b>${som(p.amount)}</b><span class="sub">${p.provider === "click" ? `Click${p.ext_id ? ` ${esc(p.ext_id)}` : ""}` : p.provider === "card" ? `karta${p.ext_id ? ` ${esc(p.ext_id)}` : ""}` : p.method === "click" ? "Click" : ""}</span></td>
      <td>${esc(p.purpose_label)}${p.purpose_detail ? `<span class="sub">${esc(p.purpose_detail)}</span>` : ""}</td>
      <td style="min-width:200px">${stepCell(p)}</td>
      <td>${tag(...pstOf(p))}${p.decided_at ? `<span class="sub">${dt(p.decided_at)}${p.admin ? ` · ${esc(p.admin)}` : ""}</span>` : ""}</td>
      <td class="r"><div class="row" style="justify-content:flex-end">
        ${p.receipt ? `<button type="button" class="btn sm" data-receipt="${p.id}">Chek</button>` : ""}
        ${p.status === "pending" ? `<button type="button" class="btn sm good" data-ok="${p.id}">Tasdiqlash</button><button type="button" class="btn sm bad" data-no="${p.id}">Rad etish</button>` : ""}
        ${p.status === "approved" && p.provider === "card" ? `<button type="button" class="btn sm bad" data-rev="${p.id}" title="Soxta chek bo'lsa: pul balansdan qaytarib yechiladi">Bekor qilish</button>` : ""}
        <button type="button" class="btn sm" data-user="${p.user_id}">Mijoz</button></div></td></tr>`);
    main().innerHTML = `
      <div class="head"><div><h1>To'lovlar</h1><p>${S.period.preset === "all" ? "Butun davr" : periodLabel()} · Click orqali to'lovlar avtomatik tushadi. Karta raqamiga o'tkazmalarda mijoz chek yuboradi: AI o'qiydi, shartlar bajarilsa avtomatik tasdiqlanadi, aks holda «Chekni tekshirish»ga tushadi. «To'lanmagan» — mijoz to'lov oynasini ochgan, lekin to'lamagan.</p></div>
        <button type="button" class="btn" id="exp-pay">To'lovlar CSV</button></div>
      ${periodBar([["all", "Butun davr"]])}
      ${ps.error ? `<p class="note" style="margin-top:14px">Xulosani yuklab bo'lmadi: ${esc(ps.error)}</p>` : payStatsBlock(ps)}
      ${cp ? cardBlock(cp) : ""}
      <section class="blk"><div class="bh"><h2>To'lov urinishlari</h2><p>${S.payStatus === "pending" ? "tekshirilishi kerak bo'lgan cheklar — davrdan qat'i nazar hammasi" : "tanlangan davrda ochilganlar"} · vaqt Toshkent bo'yicha</p></div>
      <div class="period" role="group" aria-label="Holat" style="margin-bottom:10px">${[["approved", "To'langan"], ["new", "To'lanmagan"], ["pending", `Chekni tekshirish${S.pending ? ` (${S.pending})` : ""}`], ["rejected", "Rad etilgan"], ["all", "Hammasi"]]
        .map(([k, l]) => `<button type="button" class="chip" data-st="${k}" aria-pressed="${S.payStatus === k}">${l}</button>`).join("")}</div>
      ${table(["To'lov", "Mijoz", ">Summa", "Nima uchun", "Qaysi qadamda to'xtadi", "Holat", ""], rows, S.payStatus === "pending" ? "Tekshirilishi kerak bo'lgan to'lov yo'q" : "Bu davrda to'lov yo'q")}
      ${d.payments.length >= d.limit ? `<p class="muted" style="font-size:12.5px;margin-top:8px">Oxirgi ${fmt(d.limit)} ta urinish ko'rsatildi — to'liq ro'yxat «To'lovlar CSV» da.</p>` : ""}</section>`;
    bindPeriod(main(), render);
    $$("[data-st]").forEach((b) => (b.onclick = () => { S.payStatus = b.dataset.st; render(); }));
    $("#exp-pay").onclick = () => download(`/api/admin/export/payments.csv?${pq}`);
    $$("[data-pexp]").forEach((b) => (b.onclick = () => download(`/api/admin/export/${b.dataset.pexp}.csv?${pq}`)));
    $$("[data-user]").forEach((b) => (b.onclick = () => userSheet(+b.dataset.user)));
    const saveStats = async (body, okMsg) => {
      try { await api("/api/admin/paystats/settings", body); toast(okMsg); render(); } catch (err) { toast(err.message, true); render(); }
    };
    if ($("#ps-survey")) $("#ps-survey").onchange = (e) => saveStats({ survey_on: e.target.checked }, e.target.checked ? "So'rov yoqildi" : "So'rov o'chirildi");
    if ($("#ps-test")) $("#ps-test").onclick = async (e) => {
      const btn = e.currentTarget; btn.disabled = true;
      try { await api("/api/admin/paystats/survey-test", {}); toast("Botga yuborildi — chatni tekshiring"); } catch (err) { toast(err.message, true); }
      btn.disabled = false;
    };
    if ($("#ps-set")) $("#ps-set").onsubmit = (e) => {
      e.preventDefault();
      const f = e.target; f.querySelector("button[type=submit]").disabled = true;
      saveStats({ test_ids: f.test_ids.value, click_track: f.click_track.checked }, "Saqlandi");
    };
    $$("[data-receipt]").forEach((b) => (b.onclick = () => receiptSheet(d.payments.find((p) => p.id === +b.dataset.receipt))));
    const decide = async (id, approve, btn) => {
      const p = d.payments.find((x) => x.id === id);
      if (!confirm(`${approve ? "Tasdiqlaysizmi" : "Rad etasizmi"}: #${id}, ${som(p.amount)}, ${p.name || p.user_id}?`)) return;
      btn.disabled = true;
      try { const r = await api(`/api/admin/payments/${id}`, { approve }); toast(r.already ? "Allaqachon ko'rib chiqilgan" : approve ? "Tasdiqlandi, balans to'ldirildi" : "Rad etildi"); closeSheet(); render(); }
      catch (err) { toast(err.message, true); btn.disabled = false; }
    };
    $$("[data-ok]").forEach((b) => (b.onclick = () => decide(+b.dataset.ok, true, b)));
    $$("[data-rev]").forEach((b) => (b.onclick = async () => {
      const p = d.payments.find((x) => x.id === +b.dataset.rev);
      if (!confirm(`Bekor qilasizmi: #${p.id}, ${som(p.amount)}, ${p.name || p.user_id}? Pul mijoz balansidan qaytarib yechiladi.`)) return;
      b.disabled = true;
      try { const r = await api(`/api/admin/payments/${p.id}/revert`, {}); toast(r.partial ? "Bekor qilindi — pulning bir qismi ishlatib bo'lingan" : "Bekor qilindi, balansdan yechildi"); render(); }
      catch (err) { toast(err.message, true); b.disabled = false; }
    }));
    if ($("#cardpay")) $("#cardpay").onsubmit = async (e) => {
      e.preventDefault();
      const f = e.target, btn = f.querySelector("button[type=submit]");
      btn.disabled = true;
      try {
        await api("/api/admin/cardpay", { on: f.on.checked, card: f.card.value, owner: f.owner.value, auto: f.auto.checked,
          auto_max: +f.auto_max.value || 0, window_min: +f.window_min.value || 180, daily_auto: +f.daily_auto.value || 0 });
        toast("Saqlandi"); render();
      } catch (err) { toast(err.message, true); btn.disabled = false; }
    };
    $$("[data-no]").forEach((b) => (b.onclick = () => decide(+b.dataset.no, false, b)));
    main().decide = decide;
  }
  function cardBlock(c) {
    return `<section class="blk"><details${c.enabled ? "" : " open"}><summary><b>Karta raqamiga to'lov</b> — ${c.enabled ? tag("yoqilgan", "good") : tag("o'chirilgan", "")}
        ${c.enabled ? `<span class="muted"> · ${esc(c.card)} · ${c.auto ? `avtomatik ${som(c.auto_max)} gacha` : "faqat qo'lda"}</span>` : ""}</summary>
      <form class="form" id="cardpay" style="margin-top:12px">
        <label class="row" style="font-size:13px"><input type="checkbox" name="on" ${c.on ? "checked" : ""}> Mijozlarga «Karta raqamiga o'tkazish» usulini ko'rsatish</label>
        <div class="fields">
          <label class="f">Karta raqami<input class="in" name="card" maxlength="30" inputmode="numeric" value="${esc(c.card)}" placeholder="9860 0000 0000 0000"></label>
          <label class="f">Karta egasi <small>mijozga ko'rinadi</small><input class="in" name="owner" maxlength="60" value="${esc(c.owner)}" placeholder="Ism Familiya"></label>
        </div>
        <label class="row" style="font-size:13px"><input type="checkbox" name="auto" ${c.auto ? "checked" : ""}> Chekni AI tekshirib, shartlar bajarilsa admin kutmasdan avtomatik tasdiqlasin</label>
        <div class="fields">
          <label class="f">Avtomatik chegara <small>so'm, bundan kattasi qo'lda</small><input class="in" name="auto_max" type="number" min="0" step="1000" value="${c.auto_max}"></label>
          <label class="f">Chek muddati <small>daqiqa</small><input class="in" name="window_min" type="number" min="10" max="1440" value="${c.window_min}"></label>
          <label class="f">Bir kishiga kuniga <small>avtomatik tasdiq</small><input class="in" name="daily_auto" type="number" min="0" max="50" value="${c.daily_auto}"></label>
        </div>
        <p class="muted" style="font-size:12.5px">Avtomatik tasdiq shartlari: chekda «muvaffaqiyatli», summa aynan to'g'ri, qabul qiluvchi karta oxiri ${esc((c.card || "").slice(-4) || "····")}, vaqt to'lov ochilgandan keyin va muddat ichida, tranzaksiya raqami va chek fayli takrorlanmagan. Bittasi bajarilmasa — chek sizga botda va «Chekni tekshirish»da keladi. Avtomatik tasdiqlangan har bir chek ham botga keladi: pul kartaga tushmagan bo'lsa «Bekor qilish»ni bosing.</p>
        <div class="row"><button class="btn primary" type="submit">Saqlash</button></div>
      </form></details></section>`;
  }
  function receiptSheet(p) {
    sheet(`<h2 class="big" id="sheet-title">Chek #${p.id}</h2><p class="muted">${esc(p.name || "")} · ${som(p.amount)} · ${dt(p.created_at)}</p>
      <section><img class="receipt" src="${withT(`/api/admin/payments/${p.id}/receipt`)}" alt="To'lov cheki"
        onerror="this.replaceWith(Object.assign(document.createElement('p'),{className:'note',textContent:'Chekni ochib bo\\'lmadi (PDF bo\\'lishi mumkin) — Telegramdagi xabardan ko\\'ring.'}))"></section>
      ${p.status === "pending" ? `<section class="row"><button type="button" class="btn good" id="r-ok">Tasdiqlash</button><button type="button" class="btn bad" id="r-no">Rad etish</button></section>` : ""}`);
    if ($("#r-ok")) {
      $("#r-ok").onclick = (e) => main().decide(p.id, true, e.target);
      $("#r-no").onclick = (e) => main().decide(p.id, false, e.target);
    }
  }

  // ---------------------------------------------------------------- 5. Foydalanuvchilar
  const U_FILTERS = [["", "Hammasi"], ["played", "Namuna eshitgan"], ["payopen", "To'lov oynasini ochib, to'lamagan"],
    ["idle", "Balansi bor, xarid qilmagan"], ["blocked", "Botni bloklagan"]];
  async function users(alive) {
    S.uq = S.uq || ""; S.usort = S.usort || "new"; S.upage = S.upage || 0; S.uflt = S.uflt || "";
    if (!$("#u-list")) {
      main().innerHTML = `<div class="head"><div><h1>Foydalanuvchilar</h1><p>Qidiring, mijoz kartasini oching: manbasi, xaridlari, balansi. Balansni tuzatish va xabar yozish mumkin.</p></div>
        <button type="button" class="btn" id="exp-users">Foydalanuvchilar CSV</button></div>
        <div class="row"><input class="in search" id="u-q" type="search" placeholder="Ism, @username yoki ID" value="${esc(S.uq)}" aria-label="Qidiruv">
          <select class="in" id="u-sort" style="width:auto" aria-label="Tartib"><option value="new">Yangi qo'shilganlar</option><option value="seen">Oxirgi faollik</option><option value="balance">Balans</option></select>
          <select class="in" id="u-flt" style="width:auto" aria-label="Filtr">${U_FILTERS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></div>
        <section class="blk" id="u-list"><p class="boot">Yuklanmoqda…</p></section>`;
      $("#u-sort").value = S.usort; $("#u-flt").value = S.uflt;
      $("#u-flt").onchange = (e) => { S.uflt = e.target.value; S.upage = 0; render(); };
      let t;
      $("#u-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { S.uq = e.target.value; S.upage = 0; render(); }, 300); };
      $("#u-sort").onchange = (e) => { S.usort = e.target.value; S.upage = 0; render(); };
      $("#exp-users").onclick = () => download(`/api/admin/export/users.csv${S.uflt ? `?flt=${S.uflt}` : ""}`);
    }
    const d = await api(`/api/admin/users?q=${encodeURIComponent(S.uq)}&sort=${S.usort}&page=${S.upage}&flt=${S.uflt}`);
    if (!alive()) return;
    const rows = d.users.map((u) => `<tr class="click" data-user="${u.id}">
      <td>${userLink(u)}</td><td>${esc(u.source)}</td>
      <td class="r num">${fmt(u.sites)}</td><td class="r num">${fmt(u.videos)}</td>
      <td class="r num">${u.songs ? `${fmt(u.songs)}${u.songs_paid ? `<span class="sub">${fmt(u.songs_paid)} sotib olingan</span>` : ""}` : "—"}</td>
      <td class="r num">${u.spent ? som(u.spent) : "—"}</td>
      <td class="r num hide-m">${som(u.balance)}</td><td class="num hide-m">${day(u.created_at)}<span class="sub">${ago(u.last_seen)}</span></td>
      <td>${u.blocked ? tag("bloklagan", "bad") : ""}</td></tr>`);
    const pages = Math.ceil(d.total / d.size);
    $("#u-list").innerHTML = `<p class="muted" style="margin-bottom:8px">${fmt(d.total)} ta topildi</p>
      ${table(["Foydalanuvchi", "Manba", ">Sayt", ">Video", ">Qo'shiq", ">Sarflagan", ">Balans", "Qo'shilgan", ""], rows, "Hech kim topilmadi")}
      ${pages > 1 ? `<div class="row" style="margin-top:10px"><button class="btn sm" id="pg-prev" ${S.upage ? "" : "disabled"}>Oldingi</button>
        <span class="muted">${S.upage + 1} / ${pages}</span><button class="btn sm" id="pg-next" ${S.upage + 1 < pages ? "" : "disabled"}>Keyingi</button></div>` : ""}`;
    $$("[data-user]", $("#u-list")).forEach((tr) => (tr.onclick = () => userSheet(+tr.dataset.user)));
    if ($("#pg-prev")) { $("#pg-prev").onclick = () => { S.upage--; render(); }; $("#pg-next").onclick = () => { S.upage++; render(); }; }
  }
  const TX = { topup: "To'ldirish", video: "Video", site: "Taklifnoma", package: "Mehmon paketi", refund: "Qaytarildi", upgrade: "Tarifni oshirish", admin: "Admin tuzatishi", bonus: "Bonus" };
  const SITE_ST = { draft: ["namuna", "warn"], pending: ["to'lov tekshirilmoqda", "warn"], paid: ["sotib olingan", "good"] };
  const JOB = { free: "Bepul", bonus: "Bonus", paid: "Pullik", package: "Paket", refunded: "Qaytarilgan" };
  const JST = { done: "tayyor", awaiting_payment: "to'lov kutilmoqda", failed: "xato", queued: "navbatda", rendering: "tayyorlanmoqda" };
  // «Xizmatlarga sarflandi» tafsiloti: xizmatlar, xaridorlar, pul manbasi va har bir xarid
  async function spendSheet() {
    sheet(`<p class="boot">Yuklanmoqda…</p>`);
    let d;
    try { d = await api(`/api/admin/spend?${qs()}`); } catch (e) { $("#sheet-body").innerHTML = `<p class="note">${esc(e.message)}</p>`; return; }
    const pctOf = (x) => (d.total ? Math.round((100 * x) / d.total) : 0);
    const src = (real, amount) => (real >= amount ? tag("to'langan pul", "good") : real <= 0 ? tag("admin/bonus balansi", "warn") : tag(`aralash: ${fmt(real)} to'langan`, "warn"));
    $("#sheet-body").innerHTML = `
      <h2 class="big" id="sheet-title">Xizmatlarga sarflandi</h2>
      <p class="muted">${periodLabel()} · ${fmt(d.count)} ta xarid · ${fmt(d.buyers)} xaridor</p>
      <section><div class="stat-line">
        <div><b>${som(d.total)}</b><span>jami sarflandi</span></div>
        <div><b class="c-good">${som(d.real)}</b><span>mijozlar to'lagan puldan</span></div>
        <div><b class="c-warn">${som(d.gift)}</b><span>admin yoki bonus bergan balansdan</span></div></div>
        <div class="split" aria-hidden="true"><i style="width:${pctOf(d.real)}%"></i></div>
        <p class="muted" style="font-size:12.5px;margin-top:8px">Sarf — mijozlar balansidan xizmat uchun yechilgan pul. U tushumdan farq qiladi:
          admin panel orqali qo'shilgan yoki bonus balans ham shu yerda sarflanadi. Har bir mijozda avval o'zi to'lagan pul sarflangan deb hisoblanadi.</p></section>
      <section><h3>Qaysi xizmatlarga</h3>${table(["Xizmat", ">Soni", ">Summa", ">Ulushi"], d.kinds.map((k) => `<tr><td>${esc(k.label)}<span class="sub">to'langan puldan: ${som(k.real)}</span></td>
        <td class="r num">${fmt(k.n)}</td><td class="r num">${som(k.sum)}</td><td class="r num">${pctOf(k.sum)}%</td></tr>`), "Bu davrda xarid yo'q")}</section>
      <section><h3>Kim sarfladi</h3>${table(["Mijoz", ">Sarfladi"], d.users.map((u) => `<tr data-user="${u.id}" class="click">
        <td>${userLink({ ...u, user_id: u.id })}<span class="sub">hammasi bo'lib to'lagan: ${som(u.paid_life)}${u.gift_life ? ` · admin/bonus olgan: ${som(u.gift_life)}` : ""}</span></td>
        <td class="r num">${som(u.spent)}<span class="sub">${u.real ? `to'langan: ${som(u.real)}` : ""}${u.real && u.gift ? "<br>" : ""}${u.gift ? `<span class="c-warn">admin/bonus: ${som(u.gift)}</span>` : ""}</span></td></tr>`))}</section>
      <section><h3>Har bir xarid</h3>${table(["Mijoz · nima uchun", ">Summa"], d.items.map((i) => `<tr>
        <td><button type="button" class="link" data-user="${i.user_id}">${esc(i.user)}</button> · ${esc(i.label)}
          <span class="sub">${i.url ? `<a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a>` : esc(i.title)}<br>${dt(i.created_at)}</span></td>
        <td class="r num">${som(i.amount)}<span class="sub">${src(i.real, i.amount)}</span></td></tr>`))}
        ${d.count > d.items.length ? `<p class="muted" style="font-size:12px">Oxirgi ${d.items.length} ta xarid ko'rsatildi.</p>` : ""}</section>`;
    $$("[data-user]", $("#sheet")).forEach((b) => (b.onclick = () => userSheet(+b.dataset.user)));
  }
  // Taxminiy tashqi xarajatlar (ElevenLabs musiqasi, Claude) va qo'shiqlar o'zini oqlayaptimi
  const RATE_FIELDS = [["usd_som", "1 dollar, so'm", "1"], ["credits_per_sec", "1 soniya musiqa, kredit", "0.1"], ["usd_per_1k_credits", "1000 kredit narxi, $", "0.01"],
    ["ai_in_per_m", "Claude: 1 mln kirish tokeni, $", "0.1"], ["ai_out_per_m", "Claude: 1 mln chiqish tokeni, $", "0.1"], ["lyria_usd_per_song", "Google Lyria: 1 qo'shiq, $", "0.01"]];
  async function costsSheet() {
    sheet(`<p class="boot">Yuklanmoqda…</p>`);
    let d;
    try { d = await api(`/api/admin/costs?${qs()}`); } catch (e) { $("#sheet-body").innerHTML = `<p class="note">${esc(e.message)}</p>`; return; }
    const g = d.songs, good = g.profit >= 0;
    const vol = (i) => (i.kind === "music" ? `${fmt(i.units_in)} s · ${fmt(i.credits)} kredit` : i.kind === "lyria" ? `${fmt(i.units_in)} ta qo'shiq (Lyria)` : `${fmt(i.units_in + i.units_out)} token`);
    $("#sheet-body").innerHTML = `
      <h2 class="big" id="sheet-title">Taxminiy xarajatlar</h2>
      <p class="muted">${periodLabel()} · ElevenLabs musiqasi va Claude (she'r, taklifnoma matni, tarjima)</p>
      <section><h3>Qo'shiqlar o'zini oqlayaptimi?</h3><div class="stat-line">
        <div><b>${som(g.revenue)}</b><span>${fmt(g.sold)} ta qo'shiq sotildi</span></div>
        <div><b>${som(g.cost)}</b><span>qo'shiqlarga xarajat (demolar ham)</span></div>
        <div><b class="${good ? "c-good" : "c-bad"}">${good ? "+" : "−"}${som(Math.abs(g.profit))}</b><span>${good ? "foyda" : "zarar"}</span></div></div>
        <p class="muted" style="font-size:12.5px;margin-top:8px">${fmt(g.created)} ta she'r yozildi · ${fmt(d.demo_n)} ta demo yaratildi (o'rtacha ${som(d.demo_avg)} dan)${g.sold ? ` · bitta sotilgan qo'shiqqa ${som(g.cost_per_sold)} xarajat to'g'ri keladi` : ""}.
          Muhim: har bir demo uchun ElevenLabs to'liq qo'shiq yaratadi va undan ${"20"} soniya kesib olinadi, shuning uchun demo deyarli to'liq qo'shiq narxida.</p></section>
      <section><h3>Nimaga ketdi</h3>${table(["Xarajat", ">So'm"], d.items.map((i) => `<tr><td>${esc(i.label)}<span class="sub">${fmt(i.n)} ta · ${vol(i)}</span></td>
        <td class="r num">${som(i.som)}</td></tr>`), "Bu davrda xarajat yo'q")}
        <p style="margin-top:8px">Jami: <b>${som(d.total)}</b> · shundan qo'shiqlar ${som(d.song)}, boshqa matnlar ${som(d.other)}</p></section>
      <section><h3>Narxlar</h3><p class="muted" style="font-size:12.5px">Xarajat har bir so'rovning haqiqiy hajmidan (soniya, token) shu narxlar bilan hisoblanadi.
        Narxni o'zgartirsangiz eski yozuvlar ham qayta hisoblanadi. 1000 kredit narxini ElevenLabs tarifingizdan oling (masalan, $22 / 100 000 kredit = $0.22).</p>
        <form class="form" id="rates"><div class="fields">${RATE_FIELDS.map(([k, l, st]) => `<label class="f">${l}<input class="in" name="${k}" type="number" step="${st}" min="0" value="${d.rates[k]}"></label>`).join("")}</div>
        <div><button class="btn primary" type="submit">Saqlash</button></div></form></section>`;
    $("#rates").onsubmit = async (e) => {
      e.preventDefault(); const fd = new FormData(e.target);
      try { await api("/api/admin/costs/rates", Object.fromEntries(RATE_FIELDS.map(([k]) => [k, +fd.get(k)]))); toast("Narxlar saqlandi"); costsSheet(); }
      catch (err) { toast(err.message, true); }
    };
  }
  const histTable = (items) => table(["Vaqt", "Hodisa"], items.map((h) => `<tr><td class="num" style="white-space:nowrap">${dt(h.at)}</td>
    <td${/block|failed/.test(h.kind) ? ' class="c-bad"' : h.kind === "pay_success" ? ' class="c-good"' : ""}>${esc(h.label)}${h.detail ? `<span class="sub">${esc(h.detail)}</span>` : ""}</td></tr>`));
  async function userSheet(id) {
    sheet(`<p class="boot">Yuklanmoqda…</p>`);
    let d;
    try { d = await api(`/api/admin/users/${id}`); } catch (e) { $("#sheet-body").innerHTML = `<p class="note">${esc(e.message)}</p>`; return; }
    const u = d.user;
    const act = Object.fromEntries(d.activity.map((a) => [a.kind, a]));
    $("#sheet-body").innerHTML = `
      <h2 class="big" id="sheet-title">${esc(u.name || "Ismsiz")}</h2>
      <p class="muted">${u.username ? `@${esc(u.username)} · ` : ""}id ${u.id} · ${esc(u.lang)}${u.blocked ? " · botni bloklagan" : ""}</p>
      <div class="row" style="margin-top:10px">${u.username ? `<button type="button" class="btn sm" data-open="https://t.me/${esc(u.username)}">Telegramda yozish</button>` : ""}
        <button type="button" class="btn sm" data-copy="${u.id}">ID nusxa</button></div>
      <section><div class="stat-line">
        <div><b>${som(u.balance)}</b><span>balans</span></div><div><b>${fmt(u.bonus)}</b><span>bonus video</span></div>
        <div><b>${fmt(d.invited)}</b><span>taklif qilgan do'st</span></div>
        <div><b>${act.app ? fmt(act.app.n) : 0}</b><span>kun ilovaga kirgan</span></div></div>
        <p style="margin-top:10px">Manba: <b>${esc(u.source)}</b>${u.ref && !u.source.includes(u.ref) ? ` <span class="muted">(${esc(u.ref)})</span>` : ""}</p>
        <p class="muted">Qo'shilgan: ${dt(u.created_at)} · oxirgi faollik: ${ago(u.last_seen)}</p></section>
      <section><h3>Taklifnomalar va tadbirlar</h3>${d.sites.length ? table(["Nomi", "Holat", ">Ko'rildi"], d.sites.map((x) => `<tr><td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a><span class="sub">${x.kind === "video" ? "video tadbir" : `${esc(x.tier)} · ${som(x.price)}`} · ${day(x.created_at)}</span></td>
        <td>${tag(...(SITE_ST[x.status] || [x.status]))}</td><td class="r num">${fmt(x.views)}</td></tr>`)) : `<p class="muted">Yo'q</p>`}</section>
      <section><h3>Qo'shiqlar</h3>${(d.songs || []).length ? d.songs.map((g) => `<div class="song-row">
          <div class="song-h"><b>${esc(g.title)}</b> ${tag(g.paid ? "sotib olingan" : g.status === "preview_ready" ? "namuna tayyor" : g.status === "lyrics" ? "faqat she'r" : g.status, g.paid ? "good" : "")}
            <span class="sub">${esc(g.recipient || "")}${g.style ? ` · ${esc(g.style)}` : ""} · ${day(g.created_at)}${g.paid && g.price ? ` · ${som(g.price)}` : ""}</span></div>
          ${g.files.map((f, i) => `<div class="song-a"><span>${g.files.length > 1 ? `${i + 1}-variant` : "To'liq qo'shiq"}</span><audio controls preload="none" src="${esc(f)}"></audio></div>`).join("")}
          ${g.preview ? `<div class="song-a"><span>Namuna (20 s)</span><audio controls preload="none" src="${esc(g.preview)}"></audio></div>` : ""}
          ${g.lyrics ? `<details><summary>She'r</summary><pre class="lyr">${esc(g.lyrics)}</pre></details>` : ""}</div>`).join("") : `<p class="muted">Yo'q</p>`}</section>
      <section><h3>Videolar</h3>${d.videos.length ? `<p>${d.videos.map((v) => `${JOB[v.charge] || v.charge}, ${JST[v.status] || v.status}: <b>${v.n}</b>`).join("<br>")}</p>` : `<p class="muted">Yo'q</p>`}</section>
      <section><h3>Hodisalar tarixi</h3><p class="muted" style="font-size:12.5px;margin-bottom:6px">Yangisi tepada, Toshkent vaqti bilan: botdagi va ilovadagi qadamlari, to'lovlar, olgan progrev va chegirma xabarlari.</p>
        ${(d.history || []).length ? histTable(d.history.slice(0, 60)) + (d.history.length > 60 ? `<details style="margin-top:6px"><summary>Yana ${fmt(d.history.length - 60)} ta hodisa</summary>${histTable(d.history.slice(60))}</details>` : "") : `<p class="muted">Yo'q</p>`}</section>
      <section><h3>Balans tarixi</h3>${d.tx.length ? table(["Sana", "Turi", ">Summa"], d.tx.map((t) => `<tr><td class="num">${dt(t.created_at)}</td><td>${esc(TX[t.kind] || t.kind)}</td>
        <td class="r num" style="color:var(${t.amount > 0 ? "--good" : "--ink"})">${t.amount > 0 ? "+" : "−"}${som(Math.abs(t.amount))}</td></tr>`)) : `<p class="muted">Yo'q</p>`}</section>
      <section><h3>Balansni tuzatish</h3><form class="form" id="bal">
        <div class="fields"><label class="f">Summa <small>+ qo'shish, − ayirish</small><input class="in" name="amount" type="number" step="100" placeholder="10000"></label>
          <label class="f">Bonus video <small>+/−</small><input class="in" name="bonus" type="number" min="-100" max="100" placeholder="0"></label>
          <label class="f">Sabab<input class="in" name="note" maxlength="40" placeholder="kompensatsiya"></label></div>
        <label class="row" style="font-size:13px"><input type="checkbox" name="notify" checked> Qo'shilganda mijozga xabar yuborish</label>
        <div><button class="btn primary" type="submit">Saqlash</button></div></form></section>
      <section><h3>Bot orqali xabar yozish</h3><form class="form" id="msg">
        <textarea class="in" name="text" maxlength="3500" required placeholder="Assalomu alaykum! Taklifnomangizni tayyorlashda yordam kerakmi?"></textarea>
        <div><button class="btn primary" type="submit">Yuborish</button></div></form></section>`;
    $$("[data-open]", $("#sheet")).forEach((b) => (b.onclick = () => openExternal(b.dataset.open)));
    $$("[data-copy]", $("#sheet")).forEach((b) => (b.onclick = () => copy(b.dataset.copy)));
    $("#bal").onsubmit = async (e) => {
      e.preventDefault(); const fd = new FormData(e.target);
      const amount = Math.round(+fd.get("amount") || 0), bonus = Math.round(+fd.get("bonus") || 0);
      if (!amount && !bonus) return toast("Summa yoki bonus kiriting", true);
      if (!confirm(`${u.name || u.id}: balans ${amount > 0 ? "+" : ""}${fmt(amount)} so'm, bonus ${bonus > 0 ? "+" : ""}${bonus}. Tasdiqlaysizmi?`)) return;
      try { await api(`/api/admin/users/${id}/balance`, { amount, bonus, note: fd.get("note") || "", notify: !!fd.get("notify") }); toast("Saqlandi"); userSheet(id); }
      catch (err) { toast(err.message, true); }
    };
    $("#msg").onsubmit = async (e) => {
      e.preventDefault(); const text = new FormData(e.target).get("text").trim();
      if (!text || !confirm("Xabar yuborilsinmi?")) return;
      try { await api(`/api/admin/users/${id}/message`, { text }); toast("Yuborildi"); e.target.reset(); } catch (err) { toast(err.message, true); }
    };
  }

  // ---------------------------------------------------------------- 6. Xabar yuborish
  async function broadcast(alive) {
    loading("Xabar yuborish");
    const [d, src] = await Promise.all([api("/api/admin/broadcast"), api("/api/admin/sources?all_time=1")]);
    if (!alive()) return;
    const st = d.state || {};
    main().innerHTML = `
      <div class="head"><div><h1>Xabar yuborish</h1><p>Tanlangan guruhga bot orqali xabar. Masalan, taklifnoma yasab sotib olmaganlarga eslatma.</p></div></div>
      ${st.total != null ? `<p class="note" id="bc-state">${st.running ? "Yuborilmoqda" : "Oxirgi tarqatma"}: ${esc(st.segment)} — ${fmt(st.sent)} yetdi, ${fmt(st.failed)} yetmadi${st.blocked ? ` (${fmt(st.blocked)} kishi bloklagan)` : ""}, jami ${fmt(st.total)}.</p>` : ""}
      <section class="blk"><form class="form" id="bc">
        <label class="f">Kimga<select class="in" name="segment">${d.segments.map((s) => `<option value="${s.key}">${esc(s.name)}</option>`).join("")}</select></label>
        <label class="f" id="bc-src" hidden>Manba<select class="in" name="code">${src.links.map((l) => `<option value="${esc(l.code)}">${esc(l.name)}</option>`).join("")}</select></label>
        <p class="muted" id="bc-n">Hisoblanmoqda…</p>
        <div class="f">Rasm yoki video <small>ixtiyoriy · rasm 10 MB, video (MP4) 20 MB gacha</small>
          <div class="row" style="margin-top:6px"><label class="btn" style="cursor:pointer">Fayl tanlash<input type="file" id="bc-file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime" hidden></label>
            <button type="button" class="btn" id="bc-rm" hidden>Olib tashlash</button><span class="muted" id="bc-fs" style="font-size:12.5px"></span></div>
          <div id="bc-prev" style="margin-top:8px"></div></div>
        <label class="f">Matn <small id="bc-lim">3500 belgigacha</small><textarea class="in" name="text" maxlength="3500" placeholder="Xabar matni"></textarea></label>
        <label class="row" style="font-size:13px"><input type="checkbox" name="button" checked> Xabar ostida «Ilovani ochish» tugmasi bo'lsin</label>
        <div class="row"><button class="btn primary" type="submit" ${st.running ? "disabled" : ""}>Yuborish</button>
          <span class="muted" style="font-size:12.5px">Avval «Faqat o'zim (sinov)» bilan tekshirib ko'ring.</span></div>
      </form></section>`;
    const form = $("#bc");
    const count = async () => {
      const fd = new FormData(form);
      $("#bc-src").hidden = fd.get("segment") !== "src";
      try { const r = await api("/api/admin/broadcast/count", { segment: fd.get("segment"), code: fd.get("code") || "" }); $("#bc-n").textContent = `${fmt(r.n)} kishiga yetkaziladi`; form.dataset.n = r.n; }
      catch (e) { $("#bc-n").textContent = e.message; }
    };
    form.segment.onchange = count; if (form.code) form.code.onchange = count;
    count();
    let media = null; // {media, kind} — Telegramga yuklangan fayl
    const setLimit = () => {
      const lim = media ? 1024 : 3500;
      form.text.maxLength = lim;
      $("#bc-lim").textContent = media ? "rasm/video izohi — 1024 belgigacha" : "3500 belgigacha";
    };
    $("#bc-file").onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return;
      const isV = f.type.startsWith("video/");
      if (f.size > (isV ? 20 : 10) * 1024 * 1024) { toast(`Fayl juda katta: ${isV ? "video 20" : "rasm 10"} MB gacha`, true); e.target.value = ""; return; }
      const url = URL.createObjectURL(f);
      $("#bc-prev").innerHTML = isV ? `<video src="${url}" controls muted playsinline style="max-width:320px;max-height:320px;border-radius:12px"></video>`
        : `<img src="${url}" alt="Tanlangan rasm" style="max-width:320px;max-height:320px;border-radius:12px">`;
      $("#bc-fs").textContent = "Telegramga yuklanmoqda…"; media = null;
      const fd = new FormData(); fd.append("file", f);
      try {
        media = await api("/api/admin/broadcast/media", fd);
        $("#bc-fs").textContent = `${isV ? "Video" : "Rasm"} tayyor (${(f.size / 1048576).toFixed(1)} MB) — namunasi botda sizga yuborildi`;
        $("#bc-rm").hidden = false;
      } catch (err) { toast(err.message, true); $("#bc-fs").textContent = ""; $("#bc-prev").innerHTML = ""; e.target.value = ""; }
      setLimit();
    };
    $("#bc-rm").onclick = () => { media = null; $("#bc-file").value = ""; $("#bc-prev").innerHTML = ""; $("#bc-fs").textContent = ""; $("#bc-rm").hidden = true; setLimit(); };
    form.onsubmit = async (e) => {
      e.preventDefault(); const fd = new FormData(form);
      if (!media && !String(fd.get("text") || "").trim()) { toast("Matn yozing yoki rasm/video yuklang", true); return; }
      if ($("#bc-fs").textContent.endsWith("…")) { toast("Fayl hali yuklanmoqda", true); return; }
      if (!confirm(`Xabar ${fmt(+form.dataset.n || 0)} kishiga yuborilsinmi? Buni ortga qaytarib bo'lmaydi.`)) return;
      try { const r = await api("/api/admin/broadcast", { segment: fd.get("segment"), code: fd.get("code") || "", text: fd.get("text"), button: !!fd.get("button"), ...(media || {}) }); toast(`Boshlandi: ${fmt(r.total)} kishi`); poll(); }
      catch (err) { toast(err.message, true); }
    };
    if (st.running) poll();
    function poll() {
      clearTimeout(poll.t);
      poll.t = setTimeout(async () => { if (S.tab !== "broadcast") return; render(); }, 3000);
    }
  }

  // ---------------------------------------------------------------- 6b. Progrev (eslatma xabarlari ketma-ketligi)
  async function nudgesPage(alive) {
    loading("Progrev");
    const msq = () => { const [f, t] = range(); return `${S.period.preset === "all" ? "all_time=1" : `from=${f}&to=${t}`}&src=${encodeURIComponent(S.ngsrc || "")}`; };
    const [d, m0, b0] = await Promise.all([api("/api/admin/nudges"), api(`/api/admin/msgstats?${msq()}`), api(`/api/admin/blocks?${msq()}`)]);
    if (!alive()) return;
    let cfg = d.config, m = m0, bl = b0;
    // bloklar: kunlar, manba, oxirgi xabar, Start → blok (statistika TZ, 5-band)
    const blockDays = () => {
      const [f, t] = range(), first = f || (bl.by_day[0] || {}).day || t;
      const days = []; for (let x = first; x <= t && days.length < 800; x = addDays(x, 1)) days.push(x);
      const by = Object.fromEntries(bl.by_day.map((x) => [x.day, x.n]));
      return [days, days.map((x) => by[x] || 0)];
    };
    const blocksHtml = () => {
      const sb = bl.start_to_block;
      return `<section class="blk" id="ng-blocks"><div class="bh"><h2>Bloklar</h2><button type="button" class="btn sm" id="bl-csv">CSV</button></div>
        <div class="now">
          <div class="alert"><b>${fmt(bl.blocked_now)}</b><span>hozir botni bloklab turibdi — ${bl.blocked_pct}% (${fmt(bl.users)} kishidan)</span></div>
          <div><b>${fmt(bl.in_period)}</b><span>tanlangan davrda bloklagan (vaqti yozilgan)</span></div>
          <div><b>${fmt(bl.unknown)}</b><span>bloklagan, vaqti noma'lum (hisob boshlanishidan oldin)</span></div>
          <div><b>${sb.n ? `${sb.h1_pct}%` : "—"}</b><span>Start bosgandan 1 soat ichida bloklagan</span></div>
        </div>
        <div class="two" style="margin-top:12px">
          <div><h3 style="margin-bottom:6px">Kunlar bo'yicha</h3><div id="bl-chart"></div></div>
          <div><h3 style="margin-bottom:6px">Start bosgandan blokgacha</h3>${table(["Qancha vaqtda", ">Kishi", ">Ulushi"], [["1 soat ichida", "h1"], ["1 kun ichida", "d1"], ["Keyinroq", "later"]]
            .map(([l, k]) => `<tr><td>${l}</td><td class="r num"><b>${fmt(sb[k])}</b></td><td class="r num">${sb[`${k}_pct`]}%<div class="mini-bar"><i style="width:${Math.min(100, sb[`${k}_pct`])}%"></i></div></td></tr>`), "Bu davrda vaqti yozilgan blok yo'q")}</div>
        </div>
        <div class="two" style="margin-top:12px">
          <div><h3 style="margin-bottom:6px">Blokdan oldin oxirgi olingan xabar</h3>${table(["Xabar", ">Kishi", ">Ulushi"], bl.last_msg.map((x) => `<tr><td>${esc(x.label)}${x.key ? `<span class="sub">${esc(x.key)}</span>` : ""}</td>
            <td class="r num"><b>${fmt(x.n)}</b></td><td class="r num">${x.pct}%</td></tr>`), "Ma'lumot yo'q")}
            <p class="muted" style="font-size:12px;margin-top:6px">${bl.last_scope === "now" ? "Butun davr: hozir bloklab turgan hamma odam (eski bloklar ham) — bloklagan odamga keyin hech narsa yetmaydi, demak jurnaldagi oxirgi yetgan xabar blokdan oldingi oxirgisi." : "Tanlangan davrda bloklaganlar (vaqti yozilgan bloklar)."}</p></div>
          <div><h3 style="margin-bottom:6px">Manba bo'yicha</h3>${table(["Manba (shu davrda kelganlar)", ">Kelgan", ">Bloklagan", ">Blok %"], bl.by_source.filter((x) => x.users).map((x) => `<tr><td>${esc(x.label)}</td>
            <td class="r num">${fmt(x.users)}</td><td class="r num">${fmt(x.blocked)}</td><td class="r num"><b>${x.pct}%</b></td></tr>`), "Bu davrda yangi odam yo'q")}</div>
        </div>
        <p class="muted" style="font-size:12.5px;margin-top:8px">Botni bloklagan vaqt alohida yoziladi: Telegram o'zi xabar berganda (aniq vaqt) yoki bot xabar yubora olmaganda.
          ${bl.since ? `Kunlar va «Start bosgandan blokgacha» <b>${dt(bl.since)}</b> dan beri hisoblanadi — undan oldingi bloklarning vaqti bazada yo'q (${fmt(bl.unknown)} kishi).` : "Blok vaqti hali yozila boshlamagan."}
          Manba bo'yicha blok foizi — shu davrda kelganlardan hozir bloklab turganlar.</p></section>`;
    };
    const st = d.stats;
    const mrow = (key) => m.rows.find((x) => x.key === key);
    const share = (n, p) => `${fmt(n)} <span class="muted">(${p}%)</span>`;
    const reasons = (items, max = 4) => items.slice(0, max).map((r) => `${esc(r.label)}: ${fmt(r.n)}`).join("<br>");
    // har bir xabar: yetdi → tugma → ilovaga qaytdi → sotib oldi, blok va o'tkazib yuborish sabablari (tanlangan davr)
    const msgTable = () => {
      const rows = m.rows.filter((x) => x.group === "progrev" || x.sent || x.failed || x.skipped).map((x) => `<tr>
        <td><b>${esc(x.label)}</b><span class="sub">${esc(x.key)}${x.about ? ` · ${esc(x.about)}` : ""}</span></td>
        <td class="r num"><b>${fmt(x.sent)}</b></td>
        <td class="r num">${x.failed ? fmt(x.failed) : "—"}${x.fails.length ? `<span class="sub">${reasons(x.fails)}</span>` : ""}</td>
        <td class="r num">${share(x.clicked, x.pct.clicked)}</td><td class="r num">${share(x.returned, x.pct.returned)}</td>
        <td class="r num"><b>${fmt(x.bought)}</b> <span class="muted">(${x.pct.bought}%)</span></td>
        <td class="r num">${x.blocked ? `<span class="c-bad">${fmt(x.blocked)}</span>` : "0"} <span class="muted">(${x.pct.blocked}%)</span></td>
        <td class="r num">${x.skipped ? `<b>${fmt(x.skipped)}</b>` : "—"}${x.skips.length ? `<span class="sub">${reasons(x.skips)}</span>` : ""}</td></tr>`);
      return table(["Xabar", ">Yetdi", ">Yetmadi", ">Tugmani bosdi", `>Ilovaga qaytdi (${m.windows.return_h} s)`, `>Sotib oldi (${m.windows.buy_h} s)`,
        `>Blokladi (${m.windows.block_h} s)`, ">O'tkazib yuborildi"], rows, "Bu davrda xabar yo'q", "dense");
    };
    const WON = { site: "sotib oldi", song: "sotib oldi", new: "biror narsa yasadi" };
    const ANCHOR = { site: "sayt yaratilgandan", song: "namuna yoki she'r tayyor bo'lgandan", new: "botga qo'shilgandan" };
    const when = (h) => (h < 24 ? `${h} soat` : h % 24 === 0 ? `${h / 24} kun` : `${Math.floor(h / 24)} kun ${h % 24} soat`);
    const stepStat = (k, i) => {
      const x = (st.steps[k] || {})[i], r = mrow(`${k}.${i}`);
      const all = x ? `Butun davr: yuborildi ${fmt(x.sent)}${x.failed ? ` · yetmadi ${fmt(x.failed)}` : ""}${x.skipped ? ` · o'tkazib yuborildi ${fmt(x.skipped)}` : ""}` : "Hali yuborilmagan";
      const per = r && (r.sent || r.failed || r.skipped) ? `<div class="step-m">Tanlangan davrda: yetdi <b>${fmt(r.sent)}</b>${r.failed ? ` · yetmadi ${fmt(r.failed)}` : ""}
        · tugmani bosdi <b>${fmt(r.clicked)}</b> (${r.pct.clicked}%) · ilovaga qaytdi ${fmt(r.returned)} (${r.pct.returned}%)
        · sotib oldi <b>${fmt(r.bought)}</b> (${r.pct.bought}%) · blokladi ${fmt(r.blocked)} (${r.pct.blocked}%)
        ${r.skipped ? `<br>O'tkazib yuborildi <b>${fmt(r.skipped)}</b>: ${r.skips.map((y) => `${esc(y.label)} — ${fmt(y.n)}`).join("; ")}` : ""}</div>` : "";
      const warn = (d.diagnose || []).filter((w) => w.seq === k && w.step === i && w.level !== "info").map((w) => `<p class="note" style="margin-top:6px">${esc(w.text)}</p>`).join("");
      return `<span class="muted">${all}</span>${per}${warn}`;
    };
    const stepHtml = (k, s, i) => `
      <fieldset class="step" data-step="${i}">
        <legend>${i + 1}-xabar</legend>
        <div class="step-top">
          <label class="f">Necha soatdan keyin<input class="in" type="number" min="1" max="720" name="after" value="${esc(s.after)}"><small>${ANCHOR[k]} <b data-when>${when(+s.after || 0)}</b> o'tib</small></label>
          ${k === "new" ? `<label class="f">Tugma nimani ochadi<select class="in" name="target">${d.targets.map((t) => `<option value="${t.key}" ${t.key === (s.target || "app") ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select><small>shu narsani yasab bo'lganlarga yuborilmaydi</small></label>` : ""}
          <label class="f">Tugma yozuvi<input class="in" name="button" maxlength="40" value="${esc(s.button || "")}"><small>bo'sh qolsa tugmasiz ketadi</small></label>
        </div>
        <label class="f">Matn<textarea class="in" name="text" maxlength="3500" rows="5">${esc(s.text)}</textarea></label>
        <div class="row"><button type="button" class="btn sm" data-test>O'zimga sinov yuborish</button>
          <button type="button" class="btn sm bad" data-del>O'chirish</button>${stepStat(k, i)}</div>
      </fieldset>`;
    const seqHtml = (q) => {
      const sq = cfg.seqs[q.key], reached = st.reached[q.key] || 0, won = st.won[q.key] || 0;
      return `<section class="blk seq" data-seq="${q.key}">
        <div class="bh"><h2>${esc(q.name)}</h2><p>${reached ? `${fmt(reached)} kishiga yetdi · ${fmt(won)} tasi ${WON[q.key]} (${pctOf(won, reached)}%)` : "Hali xabar yuborilmagan"}</p></div>
        <div class="form">
          <label class="row sw"><input type="checkbox" name="on" ${sq.on ? "checked" : ""}> Shu ketma-ketlik yoqilgan</label>
          ${sq.steps.map((s, i) => stepHtml(q.key, s, i)).join("")}
          ${sq.steps.length < d.max_steps ? `<div><button type="button" class="btn sm" data-add>+ Xabar qo'shish</button></div>` : ""}
        </div></section>`;
    };
    const read = () => {
      const out = { on: $("#ng-on").checked, from_hour: +$("#ng-from").value, to_hour: +$("#ng-to").value, gap_hours: +$("#ng-gap").value, seqs: {} };
      $$(".seq").forEach((el) => {
        out.seqs[el.dataset.seq] = {
          on: $('[name="on"]', el).checked,
          steps: $$(".step", el).map((x) => ({ after: +$('[name="after"]', x).value, text: $('[name="text"]', x).value, button: $('[name="button"]', x).value,
            ...($('[name="target"]', x) ? { target: $('[name="target"]', x).value } : {}) })),
        };
      });
      return out;
    };
    const draw = () => {
      main().innerHTML = `
        <div class="head"><div><h1>Progrev</h1><p>Ishni boshlab, oxiriga yetkazmaganlarga va yangi qo'shilganlarga bot o'zi eslatma yuboradi.</p></div>
          <div class="row"><button class="btn" id="ng-reset" type="button">Standart matnlar</button><button class="btn primary" id="ng-save" type="button">Saqlash</button></div></div>
        <section class="blk"><div class="now">
          <div class="${cfg.on ? "" : "alert"}"><b>${cfg.on ? "Yoqilgan" : "O'chirilgan"}</b><span>hozirgi holat</span></div>
          <div><b>${fmt(st.sent_24h)}</b><span>oxirgi 24 soatda yuborildi</span></div>
          <div><b>${st.last_run ? ago(st.last_run) : "—"}</b><span>oxirgi tekshiruv${st.last_run ? ` · ${fmt(st.last_sent)} ta xabar` : ""}</span></div>
          <div><b>${cfg.from_hour}:00–${cfg.to_hour}:00</b><span>yuborish vaqti (Toshkent)</span></div>
        </div></section>
        <section class="blk"><div class="bh"><h2>Umumiy qoidalar</h2></div>
          <div class="form"><label class="row sw"><input type="checkbox" id="ng-on" ${cfg.on ? "checked" : ""}> Progrev yoqilgan (o'chirilsa, hech qanday eslatma ketmaydi)</label>
            <div class="fields">
              <label class="f">Xabarlar orasidagi tanaffus, soat<input class="in" type="number" id="ng-gap" min="1" max="168" value="${cfg.gap_hours}"><small>bitta odam bundan tez-tez xabar olmaydi</small></label>
              <label class="f">Qaysi soatdan<input class="in" type="number" id="ng-from" min="0" max="23" value="${cfg.from_hour}"></label>
              <label class="f">Qaysi soatgacha<input class="in" type="number" id="ng-to" min="1" max="24" value="${cfg.to_hour}"></label>
            </div>
            <p class="muted" style="font-size:12.5px">Matnda ishlatish mumkin: ${d.placeholders.map((p) => `<code>${esc(p.key)}</code> — ${esc(p.name)}`).join(", ")}. Sotib olgan yoki botni bloklagan odamga xabar yuborilmaydi. ${d.grace_hours} soatdan ko'p kechikkan xabar o'tkazib yuboriladi.</p>
          </div></section>
        <section class="blk" id="ng-stats"><div class="bh"><h2>Xabarlar natijasi</h2>
            <div class="row"><button type="button" class="btn sm" id="ng-csv">CSV</button><button type="button" class="btn sm" id="ng-csv2">Sabablar CSV</button></div></div>
          ${periodBar([["all", "Butun davr"]])}
          <div class="row" style="margin:10px 0"><select class="in" id="ng-src" style="width:auto;max-width:280px" aria-label="Manba">${m.sources.map((x) => `<option value="${esc(x.key)}"${x.key === (S.ngsrc || "") ? " selected" : ""}>${esc(x.label)}</option>`).join("")}</select></div>
          ${(d.diagnose || []).length ? `<div style="margin-bottom:10px">${d.diagnose.map((w) => `<p class="note" style="margin-top:6px">${w.level === "info" ? "ℹ️" : "⚠️"} ${esc(w.text)}</p>`).join("")}</div>` : ""}
          ${msgTable()}
          <p class="muted" style="font-size:12.5px;margin-top:8px">Sanash odam bo'yicha. «Yetdi» — xabar yetkazilgan odamlar; foizlar shulardan. «Tugmani bosdi» — xabardagi tugma orqali ilova ochilgan.
            «Ilovaga qaytdi» — xabardan keyin ${m.windows.return_h} soat ichida ilovada bo'lgan; «Sotib oldi» — ${m.windows.buy_h} soat ichida pul to'lagan yoki balansdan xarid qilgan;
            «Blokladi» — ${m.windows.block_h} soat ichida botni bloklagan. Admin va sinov akkauntlari (${fmt(m.excluded)} ta) sanalmaydi.
            ${m.since ? `Tugma bosilishi, blok vaqti va o'tkazib yuborish sabablari <b>${dt(m.since)}</b> dan beri yoziladi — undan oldingi xabarlarda bu ustunlar to'liq emas, sababi esa «eski yozuv» deb ko'rsatiladi.` : "Tugma, blok va sabablar hali yozila boshlamagan (server qayta ishga tushgach boshlanadi)."}</p>
          <details style="margin-top:8px"><summary><b>O'tkazib yuborish sabablari nimani anglatadi</b></summary>
            ${table(["Sabab", "Izoh"], m.skip_reasons.map((r) => `<tr><td><b>${esc(r.label)}</b></td><td>${esc(r.about)}</td></tr>`))}</details></section>
        ${blocksHtml()}
        ${d.seqs.map(seqHtml).join("")}`;
      const [bd, bv] = blockDays(), ch = barChart(bd, bv, fmt, $("#bl-chart").clientWidth);
      $("#bl-chart").innerHTML = ch.html; ch.bind($("#bl-chart"));
      $("#bl-csv").onclick = () => download(`/api/admin/export/blocks.csv?${msq()}`);
      bindPeriod($("#ng-stats"), reload);
      $("#ng-src").onchange = (e) => { S.ngsrc = e.target.value; reload(); };
      $("#ng-csv").onclick = () => download(`/api/admin/export/msgstats.csv?${msq()}`);
      $("#ng-csv2").onclick = () => download(`/api/admin/export/msgskips.csv?${msq()}`);
      $("#ng-save").onclick = async (e) => {
        const btn = e.currentTarget; btn.disabled = true;
        try { const r = await api("/api/admin/nudges", { config: read() }); cfg = r.config; toast("Saqlandi"); draw(); }
        catch (err) { toast(err.message, true); btn.disabled = false; }
      };
      $("#ng-reset").onclick = () => {
        if (!confirm("Barcha matn va vaqtlar standart holatga qaytsinmi? «Saqlash»ni bosmaguningizcha kuchga kirmaydi.")) return;
        cfg = JSON.parse(JSON.stringify(d.defaults)); draw(); toast("Standart matnlar qo'yildi — «Saqlash»ni bosing");
      };
      $$(".seq").forEach((el) => {
        const k = el.dataset.seq;
        const add = $("[data-add]", el);
        if (add) add.onclick = () => {
          cfg = read(); const steps = cfg.seqs[k].steps, last = steps[steps.length - 1];
          steps.push({ after: last ? last.after + 24 : 2, text: "", button: "Ilovani ochish", ...(k === "new" ? { target: "app" } : {}) }); draw();
          const all = $$(`.seq[data-seq="${k}"] .step`); all[all.length - 1].scrollIntoView({ block: "center" });
        };
        $$(".step", el).forEach((x) => {
          const i = +x.dataset.step;
          $('[name="after"]', x).oninput = (e) => { $("[data-when]", x).textContent = when(+e.target.value || 0); };
          $("[data-del]", x).onclick = () => { if (!confirm(`${i + 1}-xabar o'chirilsinmi?`)) return; cfg = read(); cfg.seqs[k].steps.splice(i, 1); draw(); };
          $("[data-test]", x).onclick = async (e) => {
            const btn = e.currentTarget; btn.disabled = true;
            try {
              await api("/api/admin/nudges/test", { seq: k, step: i, text: $('[name="text"]', x).value, button: $('[name="button"]', x).value,
                target: $('[name="target"]', x) ? $('[name="target"]', x).value : "app" });
              toast("Botga yuborildi — chatni tekshiring");
            } catch (err) { toast(err.message, true); }
            btn.disabled = false;
          };
        });
      });
    };
    // davr yoki manba o'zgardi: faqat statistika qayta olinadi, saqlanmagan sozlamalar yo'qolmaydi
    const reload = async () => {
      cfg = read();
      try { [m, bl] = await Promise.all([api(`/api/admin/msgstats?${msq()}`), api(`/api/admin/blocks?${msq()}`)]); } catch (e) { toast(e.message, true); return; }
      if (alive()) { const y = window.scrollY; draw(); window.scrollTo(0, y); }
    };
    draw();
  }

  // ---------------------------------------------------------------- 7. Tizim
  async function system(alive) {
    loading("Tizim");
    const songsRow = (sg) => {
      if (!sg) return "";
      if (!sg.on) return `<tr><td>Qo'shiq xizmati</td><td class="r">${tag("kalit yo'q", "")}</td></tr>`;
      const c = sg.credits;
      if (!c) return `<tr><td>ElevenLabs krediti</td><td class="r">${tag("o'qib bo'lmadi", "warn")}<span class="sub">kalitga «User: read» ruxsatini bering</span></td></tr>`;
      const low = c.remaining < sg.alert;
      return `<tr><td>ElevenLabs krediti</td><td class="r num">${low ? tag(fmt(c.remaining), "bad") : `<b>${fmt(c.remaining)}</b>`}<span class="sub">≈ ${fmt(c.songs_left)} ta qo'shiq · ${esc(c.tier || "")}${c.usage_based ? " · avtomatik to'ldirish yoqilgan" : ""}</span></td></tr>`;
    };
    const d = await api("/api/admin/system");
    if (!alive()) return;
    const q = d.queue;
    const sf = d.songflow;
    // oxirgi xatolar: video, qo'shiq namunasi va to'liq qo'shiq — bitta ro'yxatda, yangisi tepada
    const errRows = [
      ...d.errors.map((e) => ({ at: e.at || "", html: `<tr><td class="num">Video #${e.id}<span class="sub">${esc(e.design)}</span></td>
        <td style="max-width:520px;word-break:break-word">${esc(e.error) || "—"}</td><td class="num">${dt(e.at)}</td></tr>` })),
      ...((sf && sf.errors) || []).map((e) => ({ at: e.at || "", html: `<tr${e.user_id ? ` class="click" data-user="${e.user_id}"` : ""}>
        <td class="num">${esc(e.kind_label)}${e.song_id ? ` #${e.song_id}` : ""}<span class="sub">${esc([e.title, e.name].filter(Boolean).join(" · "))}${e.test ? " · sinov akkaunt" : ""}${e.old ? " · eski yozuvdan tiklangan" : ""}</span></td>
        <td style="max-width:520px;word-break:break-word"><b>${esc(e.reason_label)}</b>${e.error ? `<span class="sub">${esc(e.error)}</span>` : ""}</td><td class="num">${dt(e.at)}</td></tr>` })),
    ].sort((x, y) => y.at.localeCompare(x.at)).slice(0, 25).map((x) => x.html);
    const songflowBlock = () => {
      const w = sf.wait, h = sf.hour, al = sf.alert, last = Object.entries(al.last || {});
      const days = sf.by_day.map((x) => `<tr><td class="num">${dayISO(x.day)}</td><td class="r num">${fmt(x.asked)}</td><td class="r num">${fmt(x.ready)}</td>
        <td class="r num">${x.avg_s == null ? "—" : dur(x.avg_s)}</td><td class="r num">${x.max_s == null ? "—" : dur(x.max_s)}</td>
        <td class="r num">${x.failed ? tag(fmt(x.failed), "bad") : "0"}<span class="sub">${x.fail_pct}%</span></td></tr>`);
      return `<section class="blk"><div class="bh"><h2>Qo'shiq: namuna tayyorlash vaqti va xatolar</h2><p>oxirgi ${sf.days} kun · Toshkent vaqti</p>
          <div class="row"><button type="button" class="btn sm" data-exp="sampletime">Kunlar bo'yicha CSV</button></div></div>
        <div class="now">
          <div><b>${w.avg_s == null ? "—" : dur(w.avg_s)}</b><span>namuna o'rtacha shuncha vaqtda tayyor bo'ladi · ${fmt(w.n)} ta namuna</span></div>
          <div><b>${w.max_s == null ? "—" : dur(w.max_s)}</b><span>eng uzun kutish</span></div>
          <div class="${sf.samples.failed ? "alert" : ""}"><b>${fmt(sf.samples.failed)} <small style="font-size:14px;font-weight:600">(${sf.samples.fail_pct}%)</small></b><span>namuna xato bilan tugadi · to'liq qo'shiq xatosi: ${fmt(sf.full.failed)}${sf.full.retried ? ` (mijoz ${fmt(sf.full.retried)} marta qayta urindi)` : ""}</span></div>
          <div><b>${fmt(sf.retries.auto)}</b><span>marta namuna avtomatik qayta urinildi · xatodan keyin mijoz o'zi qayta so'radi: ${fmt(sf.retries.manual)}</span></div>
        </div>
        <p class="muted" style="font-size:12.5px;margin-top:8px">Avtomatik qayta urinish faqat server qayta ishga tushganda yarim qolgan namunalar uchun bo'ladi. Musiqa xizmati xato qaytarganda namuna o'zi qayta so'ralmaydi (har bir urinish pullik): mijozga xato ko'rsatiladi, bepul namunasi qaytariladi va u o'zi qayta so'raydi.
          ${sf.reasons.length ? `Xato sabablari: ${sf.reasons.map((x) => `${esc(x.label)} — <b>${fmt(x.n)}</b>`).join("; ")}.` : ""}
          ${sf.since ? `Kutish vaqti va xato sabablari ${dt(sf.since)} dan beri to'liq yoziladi; undan oldingi namunalar mavjud yozuvlardan tiklangan (kutish vaqti faqat hozir ham tayyor turgan namunalarda bor).` : ""}</p>
        <div style="margin-top:12px">${table(["Kun", ">So'raldi", ">Tayyor bo'ldi", ">O'rtacha kutish", ">Eng uzun kutish", ">Xato"], days, "Bu davrda namuna so'ralmagan")}</div>
        <form class="form" id="sf-alert" style="margin-top:14px">
          <label class="row sw"><input type="checkbox" name="on" ${al.on ? "checked" : ""}> Xatolar ko'payganda yoki musiqa xizmati javob bermaganda adminlarga Telegram orqali xabar berilsin</label>
          <div class="fields">
            <label class="f">Xatolar ulushi, %<input class="in" type="number" name="pct" min="1" max="100" value="${al.pct}"><small>bir soatda shundan oshsa</small></label>
            <label class="f">Kamida necha urinish<input class="in" type="number" name="min" min="1" max="1000" value="${al.min}"><small>shu soatda shuncha urinish bo'lgandagina</small></label>
            <div class="row"><button class="btn primary" type="submit">Saqlash</button><button class="btn" type="button" id="sf-test">O'zimga sinov yuborish</button></div></div>
          <p class="muted" style="font-size:12.5px">Hozir: oxirgi 1 soatda ${fmt(h.attempts)} ta urinish, ${fmt(h.errors)} tasi xato (${h.pct}%)${h.stuck ? ` · ${fmt(h.stuck)} ta qo'shiq ${al.stuck_min} daqiqadan beri navbatda` : ""}.
            Musiqa xizmati javob bermasa (vaqt tugashi, ulanib bo'lmasligi, so'rovni rad etishi yoki qo'shiq ${al.stuck_min} daqiqada tayyor bo'lmasligi) — ulushga qaramay xabar keladi. Har bir sabab bo'yicha soatiga ko'pi bilan bitta xabar.
            ${last.length ? `Oxirgi xabar: ${last.map(([k, v]) => `${k === "down" ? "xizmat javob bermadi" : "xatolar ulushi"} — ${dt(v)}`).join(", ")}.` : ""}</p>
        </form></section>`;
    };
    main().innerHTML = `
      <div class="head"><div><h1>Tizim</h1><p>Video navbati, qo'shiq namunasi vaqti, xatolar, server joyi va eksport.</p></div></div>
      <section class="blk"><div class="now">
        <div class="${q.queued > 5 ? "alert" : ""}"><b>${fmt(q.queued)}</b><span>navbatda${d.oldest_wait_min ? ` · eng eskisi ${d.oldest_wait_min} daqiqa` : ""}</span></div>
        <div><b>${fmt(q.rendering)}</b><span>hozir tayyorlanmoqda</span></div>
        <div><b>${fmt(q.done_24h)}</b><span>24 soatda tayyor · o'rtacha ${d.avg_render_s ?? "—"} s</span></div>
        <div class="${q.failed_24h ? "alert" : ""}"><b>${fmt(q.failed_24h)}</b><span>24 soatda xato</span></div>
      </div></section>
      <section class="blk two">
        <div><div class="bh"><h2>Ma'lumotlar bazasi</h2></div>${table(["Jadval", ">Yozuvlar"], Object.entries(d.tables).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="r num">${fmt(v)}</td></tr>`))}</div>
        <div><div class="bh"><h2>Server</h2></div>${table(["Ko'rsatkich", ">Qiymat"], [
          `<tr><td>Diskda bo'sh joy</td><td class="r num">${d.disk.free_gb} / ${d.disk.total_gb} GB</td></tr>`,
          `<tr><td>Ishlab turibdi</td><td class="r num">${d.uptime_h} soat</td></tr>`,
          `<tr><td>Bot</td><td class="r">${d.bot ? tag("ulangan", "good") : tag("ulanmagan", "bad")}</td></tr>`,
          `<tr><td>To'lov kutayotgan videolar</td><td class="r num">${fmt(q.awaiting_payment)}</td></tr>`,
          `<tr><td>Narxlar</td><td class="r num">${som(d.prices.standart)} / ${som(d.prices.premium)} / ${som(d.prices.vip)}<span class="sub">video ${som(d.prices.video)} · kuniga ${d.prices.free_per_day} bepul</span></td></tr>`,
          songsRow(d.songs)])}</div>
      </section>
      ${d.songs && d.songs.on ? `<section class="blk"><div class="bh"><h2>Qo'shiq: bepul namunalar</h2><p>Bugun ${fmt(d.songs.previews_today)} ta bepul namuna so'raldi${d.songs.daily_previews ? ` (chegara ${fmt(d.songs.daily_previews)})` : ""}. Har bir namuna ${d.music && d.music.provider === "lyria" ? "Google Lyria hisobidan (≈ $0.08)" : "ElevenLabs kreditidan"} sarflanadi.</p></div>
        <form class="form" id="sg-lim"><div class="fields">
          <label class="f">Bir kishiga kuniga<input class="in" type="number" name="per_user" min="0" max="20" value="${d.songs.per_user}"><small>0 — bepul namuna yo'q</small></label>
          <label class="f">Hamma uchun kuniga jami<input class="in" type="number" name="per_day" min="0" max="100000" value="${d.songs.daily_previews}"><small>xarajat chegarasi · 0 — cheklovsiz</small></label>
          <label class="f">Bir kishiga jami namuna<input class="in" type="number" name="pv_total" min="0" max="1000" value="${(d.song_limits || {}).pv_total ?? 5}"><small>umr bo'yi · 0 — cheklovsiz</small></label>
          <label class="f">She'r yozish: kuniga<input class="in" type="number" name="ly_day" min="0" max="100" value="${(d.song_limits || {}).ly_day ?? 1}"><small>yangi she'r va AI bilan qayta yozish</small></label>
          <label class="f">She'r yozish: jami<input class="in" type="number" name="ly_total" min="0" max="1000" value="${(d.song_limits || {}).ly_total ?? 5}"><small>bir kishiga · balansi bor mijozga cheklanmaydi</small></label>
          <div><button class="btn primary" type="submit">Saqlash</button></div></div></form></section>` : ""}
      ${d.ai ? (() => { const A = d.ai, opt = (p, cur) => A.models[p].map((m) => `<option value="${m.id}"${m.id === cur ? " selected" : ""}>${esc(m.name)} · $${m.in}/$${m.out}</option>`).join("");
        return `<section class="blk"><div class="bh"><h2>AI xizmati (she'r va matnlar)</h2><p>Hozir <b>${A.provider === "gemini" ? "Google Gemini" : "Anthropic Claude"}</b> ishlayapti.${A.wanted === "gemini" && !A.gemini_key ? " Gemini tanlangan, lekin Google kaliti yo'q — kalitni «Musiqa xizmati» bo'limida kiriting." : ""} Narx — 1 mln token uchun, kirish/chiqish.</p></div>
        <form class="form" id="aicfg"><div class="fields">
          <label class="f">Xizmat<select class="in" name="provider"><option value="anthropic"${A.wanted !== "gemini" ? " selected" : ""}>Anthropic (Claude)</option><option value="gemini"${A.wanted === "gemini" ? " selected" : ""}>Google (Gemini)</option></select><small>Google kaliti Lyria bilan bir xil</small></label>
          <label class="f">Claude: asosiy<select class="in" name="anthropic_main">${opt("anthropic", A.anthropic.main)}</select><small>she'r, sayt matni, tahrir</small></label>
          <label class="f">Claude: yengil<select class="in" name="anthropic_light">${opt("anthropic", A.anthropic.light)}</select><small>video matni, tarjima</small></label>
          <label class="f">Gemini: asosiy<select class="in" name="gemini_main">${opt("gemini", A.gemini.main)}</select><small>she'r, sayt matni, tahrir</small></label>
          <label class="f">Gemini: yengil<select class="in" name="gemini_light">${opt("gemini", A.gemini.light)}</select><small>video matni, tarjima</small></label>
          <div class="row"><button class="btn primary" type="submit">Saqlash</button><button class="btn" type="button" id="aitest">Asosiy modelni sinash</button></div></div></form></section>`; })() : ""}
      ${d.music ? `<section class="blk"><div class="bh"><h2>Musiqa xizmati</h2><p>Qo'shiqlarni hozir <b>${d.music.provider === "lyria" ? "Google Lyria" : "ElevenLabs"}</b> tayyorlayapti.${d.music.wanted === "lyria" && !d.music.lyria_key ? " Lyria tanlangan, lekin kaliti yo'q — shuning uchun ElevenLabs ishlayapti." : ""}</p></div>
        <form class="form" id="mus"><div class="fields">
          <label class="f">Xizmat<select class="in" name="provider"><option value="elevenlabs"${d.music.wanted !== "lyria" ? " selected" : ""}>ElevenLabs</option><option value="lyria"${d.music.wanted === "lyria" ? " selected" : ""}>Google Lyria</option></select><small>Lyria: bir qo'shiq ≈ $0.08, sotilganda qo'shimcha xarajat yo'q</small></label>
          <label class="f">Lyria kaliti<input class="in" type="password" name="gemini_key" autocomplete="new-password" data-lpignore="true" data-1p-ignore spellcheck="false" placeholder="${d.music.lyria_key ? "saqlangan ✓ — almashtirish uchun yangisini qo'ying" : "aistudio.google.com dagi API kalit"}"><small>Kalit hech qayerda ko'rsatilmaydi</small></label>
          <label class="f">Ovoz va musiqa balansi<select class="in" name="mix">${[["soft", "Ovoz oldinda (tavsiya)"], ["strong", "Ovoz kuchli oldinda"], ["off", "Ishlovsiz"]]
            .map(([k, l]) => `<option value="${k}"${(d.music.mix || "soft") === k ? " selected" : ""}>${l}</option>`).join("")}</select><small>So'zlar aniq eshitilishi uchun musiqa ovoz ortiga suriladi</small></label>
          <label class="f">Ko'rsatma tili<select class="in" name="lang"><option value="uz"${d.music.lang !== "en" ? " selected" : ""}>O'zbekcha</option><option value="en"${d.music.lang === "en" ? " selected" : ""}>Inglizcha</option></select><small>Sinovda qaysi biri yaxshi kuylasa</small></label>
          <div><button class="btn primary" type="submit">Saqlash</button></div></div></form>
        ${(() => { const r = d.music.remix || {}; const lv = { soft: "me'yorida", strong: "kuchli", off: "ishlovsiz" };
          return `<div class="row" style="margin-top:12px;align-items:center">${r.running
            ? `<button class="btn bad" id="remix-stop">To'xtatish</button><span class="muted" style="font-size:12.5px">Mavjud qo'shiqlar qayta ishlanmoqda: ${fmt(r.done)} / ${fmt(r.total)}${r.failed ? ` · xato ${fmt(r.failed)}` : ""} — sahifani yangilab kuzating</span>`
            : `<button class="btn" id="remix-go">Mavjud namuna va qo'shiqlarga qo'llash</button><span class="muted" style="font-size:12.5px">${r.finished ? `Oxirgi marta: ${fmt(r.done)} ta qo'shiq (${lv[r.level] || r.level}), ${dt(r.finished)}. ` : ""}Havolalar o'zgarmaydi — saytdagi qo'shiqlar ham yangilanadi. Tayyor videolar o'zgarmaydi.</span>`}</div>`; })()}
        <div class="row" style="margin-top:12px"><button class="btn" id="mus-test"${d.music.lyria_key ? "" : " disabled"}>Lyria sinovi: 2 ta qo'shiq (≈ 2 000 so'm)</button><span class="muted" style="font-size:12.5px">Bitta she'r o'zbekcha va inglizcha ko'rsatma bilan — natija 2–5 daqiqada botga keladi</span></div></section>` : ""}
      ${sf ? songflowBlock() : ""}
      <section class="blk"><div class="bh"><h2>Oxirgi xatolar</h2><p>video, qo'shiq namunasi va to'liq qo'shiq — sababi bilan</p>
          <div class="row"><button type="button" class="btn sm" data-exp="songerrors">Qo'shiq xatolari CSV</button></div></div>
        ${table(["Nima", "Xato", "Qachon"], errRows, "Xato yo'q")}</section>
      <section class="blk"><div class="bh"><h2>Eksport</h2><p>Excel'da ochiladigan CSV fayllar</p></div>
        <div class="row"><button class="btn" data-exp="users">Foydalanuvchilar</button><button class="btn" data-exp="payments">To'lovlar</button><button class="btn" data-exp="sites">Taklifnomalar</button></div></section>`;
    $$("[data-exp]").forEach((b) => (b.onclick = () => download(`/api/admin/export/${b.dataset.exp}.csv`)));
    $$("tr[data-user]").forEach((tr) => (tr.onclick = () => userSheet(+tr.dataset.user)));
    const sfa = $("#sf-alert");
    if (sfa) {
      sfa.onsubmit = async (e) => {
        e.preventDefault();
        try { await api("/api/admin/songflow/settings", { alert_on: sfa.on.checked, alert_pct: +sfa.pct.value || 5, alert_min: +sfa.min.value || 1 }); toast("Saqlandi"); render(); }
        catch (err) { toast(err.message, true); }
      };
      $("#sf-test").onclick = async (e) => {
        const btn = e.currentTarget; btn.disabled = true;
        try { await api("/api/admin/songflow/alert-test", {}); toast("Botga yuborildi — chatni tekshiring"); } catch (err) { toast(err.message, true); }
        btn.disabled = false;
      };
    }
    const aic = $("#aicfg");
    if (aic) {
      const val = () => { const fd = new FormData(aic); return { provider: fd.get("provider"),
        anthropic: { main: fd.get("anthropic_main"), light: fd.get("anthropic_light") }, gemini: { main: fd.get("gemini_main"), light: fd.get("gemini_light") } }; };
      aic.onsubmit = async (e) => {
        e.preventDefault(); const body = val();
        try { const r = await api("/api/admin/ai", body); toast(r.provider === body.provider ? "Saqlandi" : "Saqlandi, lekin Google kaliti yo'q — Claude ishlayapti"); render(); }
        catch (err) { toast(err.message, true); }
      };
      $("#aitest").onclick = async () => {
        const v = val(), model = v[v.provider].main;
        sheet(`<p class="boot">${esc(model)} yozmoqda…</p>`);
        try {
          const r = await api("/api/admin/ai/test", { provider: v.provider, model });
          $("#sheet-body").innerHTML = `<h2>${esc(r.model)}</h2><p class="muted">${r.seconds} s · ${fmt(r.tokens_in)} + ${fmt(r.tokens_out)} token · ≈ ${som(r.som)}</p>
            <div class="note" style="white-space:pre-wrap;margin-top:12px">${esc(r.text)}</div><p class="muted" style="margin-top:10px">Sinov matni: onaga tug'ilgan kun tabrigi. Boshqa modelni tanlab, yana sinab solishtiring.</p>`;
        } catch (err) { $("#sheet-body").innerHTML = `<p class="note">${esc(err.message)}</p>`; }
      };
    }
    const mus = $("#mus");
    if (mus) mus.onsubmit = async (e) => {
      e.preventDefault(); const fd = new FormData(mus); const key = (fd.get("gemini_key") || "").trim();
      const body = { provider: fd.get("provider"), lang: fd.get("lang"), mix: fd.get("mix") };
      if (key) body.gemini_key = key;
      try { const r = await api("/api/admin/song-provider", body); toast(r.provider === body.provider ? "Saqlandi" : "Saqlandi, lekin Lyria kaliti yo'q"); render(); }
      catch (err) { toast(err.message, true); }
    };
    const rg = $("#remix-go"), rs = $("#remix-stop");
    if (rg) rg.onclick = async () => {
      if (!confirm("Barcha mavjud namuna va sotilgan qo'shiqlar tanlangan balans bilan qayta ishlansinmi? Fonda bittadan bajariladi.")) return;
      rg.disabled = true;
      try { await api("/api/admin/song-remix", { on: true }); toast("Boshlandi — sahifani yangilab kuzating"); render(); } catch (err) { toast(err.message, true); rg.disabled = false; }
    };
    if (rs) rs.onclick = async () => { try { await api("/api/admin/song-remix", { on: false }); toast("To'xtatildi"); render(); } catch (err) { toast(err.message, true); } };
    const mt = $("#mus-test");
    if (mt) mt.onclick = async () => {
      mt.disabled = true;
      try { await api("/api/admin/song-provider/test", {}); toast("Sinov boshlandi — natija botga keladi"); }
      catch (err) { toast(err.message, true); mt.disabled = false; }
    };
    const lim = $("#sg-lim");
    if (lim) lim.onsubmit = async (e) => {
      e.preventDefault(); const fd = new FormData(lim);
      try { await api("/api/admin/song-limits", { per_user: +fd.get("per_user"), per_day: +fd.get("per_day"), pv_total: +fd.get("pv_total"), ly_day: +fd.get("ly_day"), ly_total: +fd.get("ly_total") }); toast("Saqlandi"); render(); }
      catch (err) { toast(err.message, true); }
    };
  }


  // ---------------------------------------------------------------- Narxlar, paketlar, chegirma
  async function pricingPage(alive) {
    loading("Narxlar va chegirmalar");
    let d = await api("/api/admin/pricing");
    if (!alive()) return;
    const P = [["song", "Qo'shiq (1 ta)", "so'm"], ["video", "Video taklifnoma", "bepul limitdan keyin"],
      ["standart", "Sayt — Standart", ""], ["premium", "Sayt — Premium", ""], ["vip", "Sayt — VIP", ""]];
    const each = (x, one) => ({ each: Math.floor(x.price / x.n), off: Math.max(0, Math.round(100 - (100 * x.price) / (one * x.n))) });
    const draw = () => {
      const one = d.prices.song, st = d.stats, bf = d.backfill || {};
      const sold = st.packs_sold || {};
      const conv = st.offered ? Math.round((100 * st.used) / st.offered) : 0;
      main().innerHTML = `
        <div class="head"><div><h1>Narxlar va chegirmalar</h1><p>Narxlar shu yerdan o'zgaradi — ilova, bot va oferta sahifasi darhol yangilanadi.</p></div>
          <button type="button" class="btn primary" id="pr-save">Saqlash</button></div>
        <section class="blk"><div class="bh"><h2>Asosiy narxlar</h2></div>
          <div class="form"><div class="fields">${P.map(([k, l, h]) => `<label class="f">${l}<input class="in" type="number" min="1000" step="100" data-price="${k}" value="${d.prices[k]}">${h ? `<small>${h}</small>` : ""}</label>`).join("")}</div></div></section>
        <section class="blk"><div class="bh"><h2>Qo'shiq paketlari</h2><span class="sub">«Har biri» va tejash foizi o'zi hisoblanadi</span></div>
          ${table(["Soni", ">Narxi, so'm", ">Har biri", ">Tejash", "Belgi", "Holat", ">Sotildi", ""], d.packs.map((x, i) => {
            const e = each(x, one);
            return `<tr data-i="${i}"><td><input class="in sm" type="number" min="2" max="50" data-k="n" value="${x.n}" aria-label="Paketdagi qo'shiqlar soni"></td>
              <td class="r"><input class="in sm" type="number" min="1000" step="1000" data-k="price" value="${x.price}" aria-label="Paket narxi"></td>
              <td class="r num">${fmt(e.each)}</td><td class="r num">${e.off ? `−${e.off}%` : "—"}</td>
              <td><input class="in sm" data-k="label" maxlength="20" value="${esc(x.label)}" placeholder="—" aria-label="Belgi"></td>
              <td><label class="row sw"><input type="checkbox" data-k="on" ${x.on ? "checked" : ""}> ${x.on ? "Faol" : "O'chiq"}</label></td>
              <td class="r num">${fmt(sold[x.n] || 0)}</td>
              <td class="r"><button type="button" class="btn sm bad" data-del="${i}" aria-label="O'chirish">✕</button></td></tr>`;
          }), "Paket yo'q")}
          <div class="row" style="margin-top:10px"><button type="button" class="btn sm" id="pk-add">+ Paket qo'shish</button></div></section>
        <section class="blk"><div class="bh"><h2>Namunadan keyingi chegirma</h2>${tag(d.promo.on ? "Yoqilgan" : "O'chirilgan", d.promo.on ? "good" : "")}</div>
          <div class="form">
            <label class="row sw"><input type="checkbox" id="pm-on" ${d.promo.on ? "checked" : ""}> Namuna olib, sotib olmaganlarga 1 ta qo'shiq uchun chegirma taklif qilish</label>
            <div class="fields">
              <label class="f">Chegirma narxi<input class="in" type="number" min="1000" step="1000" id="pm-price" value="${d.promo.price}"><small>oddiy narx ${fmt(one)} → −${Math.max(0, Math.round(100 - (100 * d.promo.price) / one))}%</small></label>
              <label class="f">Amal qilish muddati, soat<input class="in" type="number" min="1" max="168" id="pm-hours" value="${d.promo.hours}"><small>shundan keyin narx qaytadi</small></label>
              <label class="f">Qachon taklif qilinsin, soat<input class="in" type="number" min="0" max="72" id="pm-delay" value="${d.promo.delay}"><small>namuna tayyor bo'lgandan necha soat keyin</small></label>
            </div>
            <div class="fields">
              <label class="f">Tugashidan oldin eslatmalar, soat qolganda<input class="in" id="pm-rem" value="${esc((d.promo.reminders || []).map((m) => +(m / 60).toFixed(2)).join(", "))}" placeholder="6, 2, 0.5">
                <small>vergul bilan, ko'pi 5 ta. 0.5 = 30 daqiqa. Bo'sh qoldirilsa — eslatma yuborilmaydi</small></label>
            </div>
            <p class="muted" style="font-size:12.5px">Har bir qo'shiqqa bir marta, faqat bitta qo'shiq xaridiga. Botga xabar yuboriladi, ilovada vaqt sanog'i chiqadi. Xabarlar progrev soatlarida yuboriladi; chegirma tunda tugaydigan bo'lsa, eslatmalar yetib borishi uchun ertasi kunga suriladi. Sotib olgan yoki paketi bor mijozga yuborilmaydi.</p>
          </div>
          <div class="kpis pr-kpi"><div><b>${fmt(st.offered)}</b><span>chegirma taklif qilindi</span></div>
            <div><b>${fmt(st.used)}</b><span>chegirmada sotib oldi · ${conv}%</span></div>
            <div><b>${fmt(st.revenue)}</b><span>chegirmadan tushum, so'm</span></div></div></section>
        <section class="blk"><div class="bh"><h2>Chegirma — kunlar bo'yicha</h2><span class="sub">oxirgi 14 kun, Toshkent vaqti</span></div>
          ${table(["Kun", ">Yangi namunalarga", ">Eski namunalarga", ">Eslatmalar", ">Chegirmada sotib oldi", ">Tushum, so'm"], (d.daily || []).map((r) => {
            const sent = r.offer + r.bf;
            return `<tr><td class="num">${day(r.day)}</td><td class="r num">${fmt(r.offer)}</td><td class="r num">${fmt(r.bf)}</td><td class="r num">${fmt(r.rem)}</td>
              <td class="r num"><b>${fmt(r.buy)}</b>${sent && r.buy ? `<span class="sub">${Math.round((100 * r.buy) / sent)}%</span>` : ""}</td><td class="r num">${r.revenue ? fmt(r.revenue) : "—"}</td></tr>`;
          }), "Hali ma'lumot yo'q")}
          <p class="muted" style="font-size:12.5px;margin-top:8px">«Yangi» va «eski namunalarga» — nechta kishiga taklif yuborilgani (bir kishi kuniga bir marta sanaladi). Hisob shu yangilanishdan boshlab yuritiladi.</p></section>
        <section class="blk"><div class="bh"><h2>Eski namunalarga chegirma</h2>${tag(bf.on ? "Yuborilmoqda" : bf.finished ? "Tugadi" : "To'xtatilgan", bf.on ? "warn" : bf.finished ? "good" : "")}</div>
          <div class="form">
            <p>Kimga yuborilishini tizim o'zi hisoblaydi — sonini kiritish shart emas. Shart: namunasi <b>tayyor</b> bo'lgan, sotib olmagan,
              48 soatdan oldin namuna olgan odam. Har bir odamga bitta xabar.</p>
            ${table(["Sotib olinmagan qo'shiqlar — odamlar bo'yicha", ">Kishi"], [
              ["Sotib olinmagan qo'shig'i bor (jami " + fmt(bf.songs_unpaid || 0) + " ta qo'shiq)", bf.people_unpaid],
              ["— namunasi tayyor", bf.people_ready],
              ["&nbsp;&nbsp;· oxirgi 48 soatda — ularga chegirma <b>avtomatik</b> boradi (bu yerda emas)", bf.people_fresh],
              ["— namunasi yo'q: faqat she'r yoki namuna xato bilan tugagan (chegirma yuborilmaydi)", bf.people_lyrics],
              ["Allaqachon chegirma olgan", bf.people_promo],
              ["Botni bloklagan", bf.people_blocked],
              ["<b>Shu tugma bilan yuboriladi</b>", bf.eligible],
            ].map(([l, n]) => `<tr><td>${l}</td><td class="r num"><b>${fmt(n || 0)}</b></td></tr>`))}
            <div class="fields">
              <label class="f">Har 3 daqiqada nechta xabar<input class="in" type="number" min="10" max="500" id="bf-batch" value="${bf.batch}">
                <small>100 → soatiga ~2 000 ta. Faqat progrev soatlarida yuboriladi</small></label>
            </div>
            <div class="row">${bf.on ? `<button type="button" class="btn bad" id="bf-stop">To'xtatish</button>`
              : `<button type="button" class="btn primary" id="bf-start" ${bf.eligible ? "" : "disabled"}>${fmt(bf.eligible)} kishiga yuborishni boshlash</button>`}</div>
          </div>
          <div class="kpis pr-kpi"><div><b>${fmt(bf.eligible)}</b><span>hali yuborilmagan (kishi)</span></div>
            <div><b>${fmt(bf.sent || 0)}</b><span>yuborildi</span></div>
            <div><b>${bf.on && bf.eligible ? `~${fmt(Math.ceil(bf.eligible / Math.max(1, bf.batch) * 3 / 60 * 10) / 10)} soat` : "—"}</b><span>qolgan vaqt (taxminan, ish soatlarida)</span></div></div></section>`;
      const bfGo = async (on, btn) => {
        btn.disabled = true;
        try { d.backfill = await api("/api/admin/pricing/backfill", { on, batch: +$("#bf-batch").value || 100 }); toast(on ? "Boshlandi — xabarlar bo'lib-bo'lib yuboriladi" : "To'xtatildi"); read(); draw(); }
        catch (err) { toast(err.message, true); btn.disabled = false; }
      };
      if ($("#bf-start")) $("#bf-start").onclick = (e) => { if (confirm(`${fmt(bf.eligible)} kishiga chegirma xabari yuborilsinmi? Narx: ${fmt(d.promo.price)} so'm, ${d.promo.hours} soat.`)) bfGo(true, e.currentTarget); };
      if ($("#bf-stop")) $("#bf-stop").onclick = (e) => bfGo(false, e.currentTarget);
      $$("[data-del]").forEach((b) => (b.onclick = () => { read(); d.packs.splice(+b.dataset.del, 1); draw(); }));
      $("#pk-add").onclick = () => { read(); const n = Math.max(1, ...d.packs.map((x) => x.n)) + 1; d.packs.push({ n, price: one * n, label: "", on: true }); draw(); };
      $("#pr-save").onclick = async (e) => {
        const btn = e.currentTarget; btn.disabled = true;
        try { read(); d = await api("/api/admin/pricing", { prices: d.prices, packs: d.packs, promo: d.promo }); toast("Saqlandi — yangi narxlar ishlayapti"); draw(); }
        catch (err) { toast(err.message, true); btn.disabled = false; }
      };
    };
    const read = () => {
      $$("[data-price]").forEach((x) => (d.prices[x.dataset.price] = +x.value || 0));
      $$("tr[data-i]").forEach((tr) => {
        const x = d.packs[+tr.dataset.i];
        x.n = +$("[data-k=n]", tr).value || 0; x.price = +$("[data-k=price]", tr).value || 0;
        x.label = $("[data-k=label]", tr).value.trim(); x.on = $("[data-k=on]", tr).checked;
      });
      d.promo = { on: $("#pm-on").checked, price: +$("#pm-price").value || 0, hours: +$("#pm-hours").value || 0, delay: +$("#pm-delay").value || 0,
        reminders: $("#pm-rem").value.split(/[,;\s]+/).map((x) => parseFloat(x.replace(",", "."))).filter((x) => x > 0).map((x) => Math.round(x * 60)) };
    };
    draw();
  }
  const VIEWS = { overview, funnel: funnelPage, sources, sales, payments, users, broadcast, nudges: nudgesPage, pricing: pricingPage, system };

  // ---------------------------------------------------------------- oyna
  function sheet(html) {
    $("#sheet-body").innerHTML = html;
    $("#sheet").hidden = false;
    document.body.style.overflow = "hidden";
    $(".sheet .x").focus();
  }
  function closeSheet() { $("#sheet").hidden = true; document.body.style.overflow = ""; }
  $$("[data-close]").forEach((el) => (el.onclick = closeSheet));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#sheet").hidden) closeSheet(); });

  // ---------------------------------------------------------------- boshlash
  (async () => {
    try {
      S.me = await api("/api/admin/whoami");
    } catch (e) {
      $("#nav").innerHTML = "";
      main().innerHTML = `<div class="head"><div><h1>Kirish kerak</h1></div></div>
        <p class="note">${e.status === 403 ? "Bu sahifa faqat adminlar uchun." : "Botda <b>/admin</b> buyrug'ini yuboring va kelgan havola orqali kiring."}</p>`;
      return;
    }
    $("#who").textContent = `${S.me.name || "Admin"} · id ${S.me.id}`;
    const h = location.hash.slice(1);
    if (VIEWS[h]) S.tab = h;
    nav(); render();
  })();
})();
