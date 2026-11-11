/* Tayyorla admin paneli: Umumiy, Trafik manbalari, Sotuvlar, To'lovlar, Foydalanuvchilar, Xabar yuborish, Tizim */
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
    if (t) { localStorage.setItem("adm_t", t); history.replaceState(null, "", location.pathname + location.hash); }
    S.token = localStorage.getItem("adm_t") || "";
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
    if (body) { headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    const r = await fetch(path, opt);
    if (!r.ok) {
      let msg = `Xato ${r.status}`;
      try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : msg; } catch (e) { /* matn emas */ }
      if (r.status === 401 || r.status === 403) { try { localStorage.removeItem("adm_t"); } catch (e) { /* */ } }
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
    sources: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
    sales: '<path d="M3 7h18l-2 12H5L3 7Z"/><path d="M8 7a4 4 0 0 1 8 0"/>',
    payments: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/>',
    users: '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0M17 4a4 4 0 0 1 0 8M22 21a6 6 0 0 0-4-5.6"/>',
    broadcast: '<path d="M3 11v2a1 1 0 0 0 1 1h3l6 5V5L7 10H4a1 1 0 0 0-1 1ZM17 8a5 5 0 0 1 0 8M20 5a9 9 0 0 1 0 14"/>',
    system: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 2.9-1.2V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
  };
  const icon = (k) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${IC[k]}</svg>`;
  const TABS = [
    ["overview", "Umumiy"], ["sources", "Trafik manbalari"], ["sales", "Sotuvlar"], ["payments", "To'lovlar"],
    ["users", "Foydalanuvchilar"], ["broadcast", "Xabar yuborish"], ["system", "Tizim"],
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
  const kpi = (v, label, hint, prev, opts = {}) => `<div class="kpi"><div class="v">${opts.money ? `${fmt(v)}<small>so'm</small>` : fmt(v)}${opts.suffix || ""} ${delta(v, prev, opts.invert)}</div>
    <div class="l">${label}</div>${hint ? `<div class="h">${hint}</div>` : ""}</div>`;
  const table = (head, rows, empty = "Ma'lumot yo'q") => `<div class="tbl-wrap"><table><thead><tr>${head.map((h) => `<th${h.startsWith(">") ? ' class="r"' : ""}>${h.replace(/^>/, "")}</th>`).join("")}</tr></thead>
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
        <div class="group"><h2><i></i>Pul</h2><div class="kpis">
          ${kpi(c.money.topup, "Tushum", `${fmt(c.money.topups)} ta to'lov · o'rtacha ${som(c.money.avg_check)}`, p.money.topup, { money: true })}
          ${kpi(c.money.payers, "To'lov qilganlar", `${fmt(c.money.new_payers)} tasi birinchi marta`, p.money.payers)}
          ${kpi(c.money.spent, "Xizmatlarga sarflandi", `${fmt(c.money.buyers)} xaridor`, p.money.spent, { money: true })}
          ${kpi(c.money.refunds, "Qaytarilgan", c.money.admin ? `admin tuzatishlari: ${som(c.money.admin)}` : "video tayyorlanmaganda", p.money.refunds, { money: true, invert: true })}
        </div></div>
      </div></section>
      <section class="blk"><div class="bh"><h2>Kunlar bo'yicha</h2></div>
        <div class="chart-card"><div class="metric-tabs" role="group" aria-label="Ko'rsatkich">${METRICS.map(([k, l]) => `<button type="button" class="chip" data-metric="${k}" aria-pressed="${S.metric === k}">${l}</button>`).join("")}</div>
        <div id="chart"></div></div></section>
      <section class="blk"><div class="bh"><h2>Voronka: shu davrda kelgan yangi foydalanuvchilar</h2><p>Keyin nima qilishgan (hozirgacha)</p></div>
        <div class="chart-card funnel">${funnel(c.funnel)}</div></section>`;
    bindPeriod(main(), render);
    $$("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
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
  function funnel(steps) {
    const top = steps[0].n || 1;
    return steps.map((s, i) => `<div class="fstep"><span class="t">${esc(s.label)}</span>
      <div class="track"><div class="fill" style="width:${Math.max(0.5, (100 * s.n) / top)}%"></div></div>
      <span class="n num">${fmt(s.n)}<small>${i ? `${pctOf(s.n, steps[i - 1].n)}%` : ""}</small></span></div>`).join("") +
      `<p class="muted" style="font-size:12.5px">Foizlar — oldingi bosqichdan o'tganlar ulushi.</p>`;
  }

  // ---------------------------------------------------------------- 2. Trafik manbalari
  async function sources(alive) {
    loading("Trafik manbalari");
    const allTime = S.period.preset === "all";
    const [f, t] = range();
    const d = await api(`/api/admin/sources?${allTime ? "all_time=1" : `from=${f}&to=${t}`}${S.showArchived ? "&archived=1" : ""}`);
    if (!alive()) return;
    const rows = d.links.map((x) => `<tr class="click" data-link="${x.id}">
      <td><b>${esc(x.name)}</b>${x.archived ? " " + tag("arxivda") : ""}${x.urls.report ? " " + tag(x.share_pct ? `hisobot ochiq, ${x.share_pct}%` : "hisobot ochiq", "pink") : ""}<span class="sub">${esc(x.code)}${x.note ? ` · ${esc(x.note)}` : ""}</span></td>
      <td class="r num">${fmt(x.clicks)}</td><td class="r num">${fmt(x.starts)}</td><td class="r num"><b>${fmt(x.users)}</b></td>
      <td class="r num">${fmt(x.app)}</td><td class="r num">${fmt(x.created)}</td><td class="r num"><b>${fmt(x.bought)}</b><span class="sub">${x.conv}%</span></td>
      <td class="r num">${som(x.revenue)}</td>
      <td class="r num hide-m">${x.cost ? som(x.cost) : "—"}${x.cpu ? `<span class="sub">1 kishi: ${som(x.cpu)}</span>` : ""}</td>
      <td class="r num hide-m">${x.roi == null ? "—" : tag(`${x.roi > 0 ? "+" : ""}${x.roi}%`, x.roi >= 0 ? "good" : "bad")}</td></tr>`);
    const groups = d.groups.filter((g) => g.users).map((g) => `<tr><td>${esc(g.name)}</td><td class="r num"><b>${fmt(g.users)}</b></td><td class="r num">${fmt(g.app)}</td>
      <td class="r num">${fmt(g.created)}</td><td class="r num"><b>${fmt(g.bought)}</b><span class="sub">${g.conv}%</span></td><td class="r num">${som(g.revenue)}</td></tr>`);
    main().innerHTML = `
      <div class="head"><div><h1>Trafik manbalari</h1><p>Reklama uchun alohida havola yarating: kim bosdi, kim start bosdi, ilovaga kirdi va sotib oldi — hammasi shu yerda.</p></div></div>
      ${periodBar([["all", "Butun davr"]])}
      <section class="blk"><div class="bh"><h2>Yangi havola</h2></div>
        <form class="form" id="new-link">
          <div class="fields">
            <label class="f">Nomi<input class="in" name="name" required maxlength="100" placeholder="Masalan: Instagram, @kanal_nomi reklama"></label>
            <label class="f">Kod <small>ixtiyoriy, lotincha</small><input class="in" name="code" maxlength="24" pattern="[a-z0-9_]{2,24}" placeholder="insta_noyabr"></label>
            <label class="f">Reklama narxi <small>so'm, ixtiyoriy</small><input class="in" name="cost" type="number" min="0" step="1000" placeholder="0"></label>
          </div>
          <label class="f">Izoh <small>ixtiyoriy</small><input class="in" name="note" maxlength="255" placeholder="Qayerda, qachon joylandi"></label>
          <div class="row"><button class="btn primary" type="submit">Havola yaratish</button><span class="muted" style="font-size:12.5px">Havola ikki xil bo'ladi: kuzatuv havolasi bosishlarni ham sanaydi, bot havolasi esa to'g'ridan-to'g'ri botni ochadi.</span></div>
        </form></section>
      <section class="blk"><div class="bh"><h2>Havolalar</h2><p>Foydalanuvchilar — shu havola orqali botga birinchi marta kelganlar; ularning keyingi xaridlari ham shu manbaga yoziladi.
        <label style="margin-left:10px"><input type="checkbox" id="arch" ${S.showArchived ? "checked" : ""}> arxivdagilar</label></p></div>
        ${table(["Havola", ">Bosish", ">Start", ">Yangi", ">Ilovaga kirdi", ">Yasadi", ">Sotib oldi", ">Tushum", ">Reklama narxi", ">ROI"], rows, "Hali havola yo'q. Yuqorida birinchisini yarating.")}</section>
      <section class="blk"><div class="bh"><h2>Boshqa manbalar</h2><p>Havolasiz kelganlar</p></div>
        ${table(["Manba", ">Yangi", ">Ilovaga kirdi", ">Yasadi", ">Sotib oldi", ">Tushum"], groups)}</section>`;
    bindPeriod(main(), render);
    $("#arch").onchange = (e) => { S.showArchived = e.target.checked; render(); };
    $("#new-link").onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      try {
        const r = await api("/api/admin/links", { name: fd.get("name"), code: fd.get("code") || "", cost: +fd.get("cost") || 0, note: fd.get("note") || "" });
        toast("Havola yaratildi"); await render();
        const x = (await api(`/api/admin/sources?all_time=1&archived=1`)).links.find((l) => l.id === r.id);
        if (x) linkSheet(x);
      } catch (err) { toast(err.message, true); }
    };
    $$("[data-link]").forEach((tr) => (tr.onclick = () => linkSheet(d.links.find((x) => x.id === +tr.dataset.link))));
  }
  function linkSheet(x) {
    sheet(`<h2 class="big" id="sheet-title">${esc(x.name)}</h2><p class="muted">Kod: ${esc(x.code)} · yaratilgan ${day(x.created_at)}</p>
      <section><h3>Havolalar</h3>
        <div class="copy"><span>Kuzatuv (tavsiya):</span><code>${esc(x.urls.go)}</code><button type="button" data-copy="${esc(x.urls.go)}">Nusxa</button></div>
        <div class="copy" style="margin-top:6px"><span>Bot havolasi:</span><code>${esc(x.urls.bot)}</code><button type="button" data-copy="${esc(x.urls.bot)}">Nusxa</button></div>
        <p class="muted" style="font-size:12.5px;margin-top:8px">Kuzatuv havolasi bosilganini sanaydi va darhol botga o'tkazadi. Instagram, kanal postlari va bannerlar uchun shu havolani bering.</p></section>
      <section><h3>Natija (tanlangan davr)</h3><div class="stat-line">
        <div><b>${fmt(x.clicks)}</b><span>bosish</span></div><div><b>${fmt(x.starts)}</b><span>start</span></div>
        <div><b>${fmt(x.users)}</b><span>yangi foydalanuvchi</span></div><div><b>${fmt(x.app)}</b><span>ilovaga kirdi</span></div>
        <div><b>${fmt(x.created)}</b><span>yasadi</span></div><div><b>${fmt(x.bought)}</b><span>sotib oldi</span></div>
        <div><b>${som(x.revenue)}</b><span>tushum</span></div></div>
        ${x.cost ? `<p style="margin-top:10px">Bir foydalanuvchi narxi: <b>${som(x.cpu)}</b> · bir xaridor narxi: <b>${som(x.cpb)}</b> · ROI: <b>${x.roi}%</b></p>` : ""}</section>
      <section><h3>Hamkor uchun hisobot</h3>
        <p class="muted" style="font-size:13px;margin-bottom:8px">Kanal egasi yoki bloger faqat shu havola natijalarini ko'radi: bosish, start, yangi foydalanuvchi, ilovaga kirgan, yasagan, sotib olgan va tushum. Hamkor ulushi (%) yozilsa, uning daromadi ham hisoblab ko'rsatiladi. Ismlar va shaxsiy ma'lumotlar ko'rinmaydi.</p>
        ${x.urls.report ? `<div class="copy"><code>${esc(x.urls.report)}</code><button type="button" data-copy="${esc(x.urls.report)}">Nusxa</button><button type="button" data-open="${esc(x.urls.report)}">Ochish</button></div>
          <div class="row" style="margin-top:8px"><button type="button" class="btn sm" id="sh-renew">Yangi havola (eskisi ishlamay qoladi)</button><button type="button" class="btn sm bad" id="sh-off">Hisobotni o'chirish</button></div>`
          : `<button type="button" class="btn" id="sh-on">Hisobot havolasini yaratish</button>`}</section>
      <section><h3>Tahrirlash</h3><form class="form" id="edit-link">
        <label class="f">Nomi<input class="in" name="name" value="${esc(x.name)}" maxlength="100" required></label>
        <label class="f">Reklama narxi (so'm)<input class="in" name="cost" type="number" min="0" step="1000" value="${x.cost || ""}"></label>
        <label class="f">Izoh<input class="in" name="note" value="${esc(x.note || "")}" maxlength="255"></label>
        <label class="f">Hamkor ulushi, % <small>tushumdan hamkorga beriladigan foiz; hisobotda «Sizning ulushingiz» bo'lib chiqadi</small><input class="in" name="share_pct" type="number" min="0" max="100" step="1" value="${x.share_pct || ""}" placeholder="0"></label>
        <div class="row"><button class="btn primary" type="submit">Saqlash</button>
          <button class="btn" type="button" id="arch-link">${x.archived ? "Arxivdan chiqarish" : "Arxivga olish"}</button></div>
      </form></section>`);
    $$("[data-copy]", $("#sheet")).forEach((b) => (b.onclick = () => copy(b.dataset.copy)));
    $$("[data-open]", $("#sheet")).forEach((b) => (b.onclick = () => openExternal(b.dataset.open)));
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
  const PST = { pending: ["Tekshirish kerak", "warn"], new: ["Chek yuborilmagan", ""], approved: ["Tasdiqlangan", "good"], rejected: ["Rad etilgan", "bad"], cancelled: ["Bekor qilingan", "bad"] };
  async function payments(alive) {
    loading("To'lovlar");
    S.payStatus = S.payStatus || "pending";
    const d = await api(`/api/admin/payments?status=${S.payStatus}`);
    if (!alive()) return;
    if (S.payStatus === "pending") { S.pending = d.payments.length; nav(); }
    const rows = d.payments.map((p) => `<tr>
      <td class="num">#${p.id}<span class="sub">${dt(p.created_at)}</span></td>
      <td>${userLink(p)}</td>
      <td class="r num"><b>${som(p.amount)}</b><span class="sub">${p.for_video ? "video uchun" : "balansga"}${p.provider === "click" ? ` · Click${p.ext_id ? ` ${esc(p.ext_id)}` : ""}` : ""}</span></td>
      <td>${tag(PST[p.status][0], PST[p.status][1])}${p.decided_at ? `<span class="sub">${dt(p.decided_at)}${p.admin ? ` · ${esc(p.admin)}` : ""}</span>` : ""}</td>
      <td class="r"><div class="row" style="justify-content:flex-end">
        ${p.receipt ? `<button type="button" class="btn sm" data-receipt="${p.id}">Chek</button>` : ""}
        ${p.status === "pending" || p.status === "new" ? `<button type="button" class="btn sm good" data-ok="${p.id}">Tasdiqlash</button><button type="button" class="btn sm bad" data-no="${p.id}">Rad etish</button>` : ""}
        <button type="button" class="btn sm" data-user="${p.user_id}">Mijoz</button></div></td></tr>`);
    main().innerHTML = `
      <div class="head"><div><h1>To'lovlar</h1><p>Chekni ko'rib, shu yerning o'zida tasdiqlang — mijozga xabar va balans avtomatik boradi.</p></div>
        <button type="button" class="btn" id="exp-pay">To'lovlar CSV</button></div>
      <div class="period" role="group" aria-label="Holat">${[["pending", "Tekshirish kerak"], ["new", "Chek kutilmoqda"], ["approved", "Tasdiqlangan"], ["rejected", "Rad etilgan"], ["all", "Hammasi"]]
        .map(([k, l]) => `<button type="button" class="chip" data-st="${k}" aria-pressed="${S.payStatus === k}">${l}</button>`).join("")}</div>
      <section class="blk">${table(["To'lov", "Mijoz", ">Summa", "Holat", ""], rows, S.payStatus === "pending" ? "Tekshirilishi kerak bo'lgan to'lov yo'q" : "To'lov yo'q")}</section>`;
    $$("[data-st]").forEach((b) => (b.onclick = () => { S.payStatus = b.dataset.st; render(); }));
    $("#exp-pay").onclick = () => download("/api/admin/export/payments.csv");
    $$("[data-user]").forEach((b) => (b.onclick = () => userSheet(+b.dataset.user)));
    $$("[data-receipt]").forEach((b) => (b.onclick = () => receiptSheet(d.payments.find((p) => p.id === +b.dataset.receipt))));
    const decide = async (id, approve, btn) => {
      const p = d.payments.find((x) => x.id === id);
      if (!confirm(`${approve ? "Tasdiqlaysizmi" : "Rad etasizmi"}: #${id}, ${som(p.amount)}, ${p.name || p.user_id}?`)) return;
      btn.disabled = true;
      try { const r = await api(`/api/admin/payments/${id}`, { approve }); toast(r.already ? "Allaqachon ko'rib chiqilgan" : approve ? "Tasdiqlandi, balans to'ldirildi" : "Rad etildi"); closeSheet(); render(); }
      catch (err) { toast(err.message, true); btn.disabled = false; }
    };
    $$("[data-ok]").forEach((b) => (b.onclick = () => decide(+b.dataset.ok, true, b)));
    $$("[data-no]").forEach((b) => (b.onclick = () => decide(+b.dataset.no, false, b)));
    main().decide = decide;
  }
  function receiptSheet(p) {
    sheet(`<h2 class="big" id="sheet-title">Chek #${p.id}</h2><p class="muted">${esc(p.name || "")} · ${som(p.amount)} · ${dt(p.created_at)}</p>
      <section><img class="receipt" src="${withT(`/api/admin/payments/${p.id}/receipt`)}" alt="To'lov cheki"
        onerror="this.replaceWith(Object.assign(document.createElement('p'),{className:'note',textContent:'Chekni ochib bo\\'lmadi (PDF bo\\'lishi mumkin) — Telegramdagi xabardan ko\\'ring.'}))"></section>
      ${p.status === "pending" || p.status === "new" ? `<section class="row"><button type="button" class="btn good" id="r-ok">Tasdiqlash</button><button type="button" class="btn bad" id="r-no">Rad etish</button></section>` : ""}`);
    if ($("#r-ok")) {
      $("#r-ok").onclick = (e) => main().decide(p.id, true, e.target);
      $("#r-no").onclick = (e) => main().decide(p.id, false, e.target);
    }
  }

  // ---------------------------------------------------------------- 5. Foydalanuvchilar
  async function users(alive) {
    S.uq = S.uq || ""; S.usort = S.usort || "new"; S.upage = S.upage || 0;
    if (!$("#u-list")) {
      main().innerHTML = `<div class="head"><div><h1>Foydalanuvchilar</h1><p>Qidiring, mijoz kartasini oching: manbasi, xaridlari, balansi. Balansni tuzatish va xabar yozish mumkin.</p></div>
        <button type="button" class="btn" id="exp-users">Foydalanuvchilar CSV</button></div>
        <div class="row"><input class="in search" id="u-q" type="search" placeholder="Ism, @username yoki ID" value="${esc(S.uq)}" aria-label="Qidiruv">
          <select class="in" id="u-sort" style="width:auto" aria-label="Tartib"><option value="new">Yangi qo'shilganlar</option><option value="seen">Oxirgi faollik</option><option value="balance">Balans</option></select></div>
        <section class="blk" id="u-list"><p class="boot">Yuklanmoqda…</p></section>`;
      $("#u-sort").value = S.usort;
      let t;
      $("#u-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { S.uq = e.target.value; S.upage = 0; render(); }, 300); };
      $("#u-sort").onchange = (e) => { S.usort = e.target.value; S.upage = 0; render(); };
      $("#exp-users").onclick = () => download("/api/admin/export/users.csv");
    }
    const d = await api(`/api/admin/users?q=${encodeURIComponent(S.uq)}&sort=${S.usort}&page=${S.upage}`);
    if (!alive()) return;
    const rows = d.users.map((u) => `<tr class="click" data-user="${u.id}">
      <td>${userLink(u)}</td><td>${esc(u.source)}</td>
      <td class="r num">${fmt(u.sites)}</td><td class="r num">${fmt(u.videos)}</td><td class="r num">${u.spent ? som(u.spent) : "—"}</td>
      <td class="r num hide-m">${som(u.balance)}</td><td class="num hide-m">${day(u.created_at)}<span class="sub">${ago(u.last_seen)}</span></td>
      <td>${u.blocked ? tag("bloklagan", "bad") : ""}</td></tr>`);
    const pages = Math.ceil(d.total / d.size);
    $("#u-list").innerHTML = `<p class="muted" style="margin-bottom:8px">${fmt(d.total)} ta topildi</p>
      ${table(["Foydalanuvchi", "Manba", ">Sayt", ">Video", ">Sarflagan", ">Balans", "Qo'shilgan", ""], rows, "Hech kim topilmadi")}
      ${pages > 1 ? `<div class="row" style="margin-top:10px"><button class="btn sm" id="pg-prev" ${S.upage ? "" : "disabled"}>Oldingi</button>
        <span class="muted">${S.upage + 1} / ${pages}</span><button class="btn sm" id="pg-next" ${S.upage + 1 < pages ? "" : "disabled"}>Keyingi</button></div>` : ""}`;
    $$("[data-user]", $("#u-list")).forEach((tr) => (tr.onclick = () => userSheet(+tr.dataset.user)));
    if ($("#pg-prev")) { $("#pg-prev").onclick = () => { S.upage--; render(); }; $("#pg-next").onclick = () => { S.upage++; render(); }; }
  }
  const TX = { topup: "To'ldirish", video: "Video", site: "Taklifnoma", package: "Mehmon paketi", refund: "Qaytarildi", upgrade: "Tarifni oshirish", admin: "Admin tuzatishi", bonus: "Bonus" };
  const SITE_ST = { draft: ["namuna", "warn"], pending: ["to'lov tekshirilmoqda", "warn"], paid: ["sotib olingan", "good"] };
  const JOB = { free: "Bepul", bonus: "Bonus", paid: "Pullik", package: "Paket", refunded: "Qaytarilgan" };
  const JST = { done: "tayyor", awaiting_payment: "to'lov kutilmoqda", failed: "xato", queued: "navbatda", rendering: "tayyorlanmoqda" };
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
      <section><h3>Videolar</h3>${d.videos.length ? `<p>${d.videos.map((v) => `${JOB[v.charge] || v.charge}, ${JST[v.status] || v.status}: <b>${v.n}</b>`).join("<br>")}</p>` : `<p class="muted">Yo'q</p>`}</section>
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
        <label class="f">Matn<textarea class="in" name="text" maxlength="3500" required placeholder="Xabar matni"></textarea></label>
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
    form.onsubmit = async (e) => {
      e.preventDefault(); const fd = new FormData(form);
      if (!confirm(`Xabar ${fmt(+form.dataset.n || 0)} kishiga yuborilsinmi? Buni ortga qaytarib bo'lmaydi.`)) return;
      try { const r = await api("/api/admin/broadcast", { segment: fd.get("segment"), code: fd.get("code") || "", text: fd.get("text"), button: !!fd.get("button") }); toast(`Boshlandi: ${fmt(r.total)} kishi`); poll(); }
      catch (err) { toast(err.message, true); }
    };
    if (st.running) poll();
    function poll() {
      clearTimeout(poll.t);
      poll.t = setTimeout(async () => { if (S.tab !== "broadcast") return; render(); }, 3000);
    }
  }

  // ---------------------------------------------------------------- 7. Tizim
  async function system(alive) {
    loading("Tizim");
    const d = await api("/api/admin/system");
    if (!alive()) return;
    const q = d.queue;
    main().innerHTML = `
      <div class="head"><div><h1>Tizim</h1><p>Video navbati, xatolar, server joyi va eksport.</p></div></div>
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
          `<tr><td>Narxlar</td><td class="r num">${som(d.prices.standart)} / ${som(d.prices.premium)} / ${som(d.prices.vip)}<span class="sub">video ${som(d.prices.video)} · kuniga ${d.prices.free_per_day} bepul</span></td></tr>`])}</div>
      </section>
      <section class="blk"><div class="bh"><h2>Oxirgi xatolar</h2></div>
        ${table(["Video", "Xato", "Qachon"], d.errors.map((e) => `<tr><td class="num">#${e.id}<span class="sub">${esc(e.design)}</span></td><td style="max-width:520px;word-break:break-word">${esc(e.error) || "—"}</td><td class="num">${dt(e.at)}</td></tr>`), "Xato yo'q")}</section>
      <section class="blk"><div class="bh"><h2>Eksport</h2><p>Excel'da ochiladigan CSV fayllar</p></div>
        <div class="row"><button class="btn" data-exp="users">Foydalanuvchilar</button><button class="btn" data-exp="payments">To'lovlar</button><button class="btn" data-exp="sites">Taklifnomalar</button></div></section>`;
    $$("[data-exp]").forEach((b) => (b.onclick = () => download(`/api/admin/export/${b.dataset.exp}.csv`)));
  }

  const VIEWS = { overview, sources, sales, payments, users, broadcast, system };

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
