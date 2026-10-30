/* Saytlar: katalog, mening saytlarim va 5 qadamli buyurtma (dizayn, tarif, ma'lumot, surat, tayyor) */
(() => {
  "use strict";
  const { $, $$, esc, T, icon, S, api, haptic, notify, toast, store, money } = App;
  const OKEY = "tayyorla-order";
  const tplName = (t) => App.tx("tpl." + t.id, t.name);
  const tplDesc = (t) => App.tx("tpld." + t.id, t.desc);
  const secTitle = (s) => App.tx("csec." + s.key, s.title);
  const tierTitle = (x) => App.tx("tier." + x.key, x.title);
  const tierFeat = (x, i, f) => App.tx(`tierf.${x.key}.${i}`, f);
  const tierShort = (x) => App.tx("tiers." + x.key, x.features[0]);
  // ba'zi maydonlar bo'limga qarab boshqacha nomlanadi (to'yda «kimga» — mehmon, tug'ilgan kunda — tabriklanuvchi)
  // tarifli (v2) shablonlarning maydonlari alohida kalitlarda tarjima qilinadi
  const fLabel = (f) => (tpl().v2 ? App.tx(`cf2.${tpl().section}.${f.key}`, f.label)
    : App.tx(`cf.${tpl().section}.${f.key}`, App.tx("cf." + f.key, f.label)));
  const fHint = (f) => (!f.hint ? "" : tpl().v2 ? App.tx(`cfh2.${tpl().section}.${f.key}`, f.hint)
    : App.tx(`cfh.${tpl().section}.${f.key}`, App.tx("cfh." + f.key, f.hint)));
  const tierOf = (t) => t.tier || (t.vip ? "vip" : t.premium ? "premium" : "standart");
  const blockTitle = (sec, b) => App.tx(`cb.${sec}.${b.key}`, b.title);

  /** Katalog kartochkasi (galereya va tavsiyalar). */
  App.tcard = (t) => `<button type="button" class="tcard" data-tpl="${esc(t.id)}">
      <span class="img"><img src="${esc(t.thumb)}" alt="" loading="lazy">${t.vip ? '<span class="badge gold">VIP</span>' : t.premium ? `<span class="badge solid">${esc(t.new ? T("new") + " · Premium" : "Premium")}</span>` : t.new ? `<span class="badge gold">${esc(T("new"))}</span>` : ""}</span>
      <b>${esc(tplName(t))}</b><small>${esc(tplDesc(t))}</small></button>`;

  // ---------------------------------------------------------------- Saytlar bo'limi
  App.views.sites = (p, el) => {
    App.chrome({ tabs: true });
    const sites = S.me.sites || [];
    const tab = p.mine ? "mine" : "designs";
    const secs = S.cm.sections;
    const sec = secs.some((s) => s.key === p.section) ? p.section : { toy: "toy" }[p.section] || secs[0].key;
    el.innerHTML = `
      <header class="page-head"><h1>${esc(T("sites.title"))}</h1><p>${esc(T("sites.sub"))}</p>
        <div class="seg" role="tablist" style="margin-top:8px">
          <button type="button" role="tab" data-t="designs" aria-selected="${tab === "designs"}">${esc(T("videos.designs"))}</button>
          <button type="button" role="tab" data-t="mine" aria-selected="${tab === "mine"}">${esc(T("sites.mine", { n: sites.length }))}</button></div></header>
      <div id="sbody" class="fade"></div>`;
    $$("[data-t]", el).forEach((b) => (b.onclick = () => { haptic(); p.mine = b.dataset.t === "mine"; App.render(); }));
    const body = $("#sbody");
    if (p.fromEvent) { const slug = p.fromEvent; delete p.fromEvent; fromEvent(slug); }
    if (tab === "designs") {
      const list = S.cm.templates.filter((t) => t.section === sec);
      const tiers = S.cm.tiers;
      // Premium birinchi (eng ko'p tanlanadi), keyin VIP, oxirida Standart
      const groups = ["premium", "vip", "standart"].map((k) => ({
        tier: tiers.find((x) => x.key === k),
        items: list.filter((t) => tierOf(t) === k).sort((a, b) => (a.order || 50) - (b.order || 50)),
      })).filter((g) => g.items.length && g.tier);
      body.innerHTML = `
        <div class="wrap" style="padding-top:14px"><div class="tiers3">${tiers.map((x, i) => `
          <div class="${x.key === "premium" ? "pop" : x.key === "vip" ? "vip" : ""}">${x.key === "premium" ? `<span class="flag">${esc(T("sites.popular"))}</span>` : ""}
            <b>${esc(tierTitle(x))}</b><span>${esc(App.fmtNum(x.price))}</span><small>${esc(T("sites.tier_" + (i + 1)))}</small></div>`).join("")}</div></div>
        <div class="wrap" style="padding-top:12px"><button type="button" class="banner" id="fromVideo">${icon("video")}<span><b>${esc(T("sites.from_video_t"))}</b>${esc(T("sites.from_video_s"))}</span>${icon("chev")}</button></div>
        <div class="wrap" style="padding-top:16px"><div class="chips scroll">${secs.map((s) => `<button type="button" class="chip" data-s="${s.key}" aria-pressed="${s.key === sec}">${esc(secTitle(s))}</button>`).join("")}</div></div>
        ${groups.map((g) => `<div class="wrap tgroup ${g.tier.key}" style="padding-top:18px">
          <div class="tg-head"><h2>${esc(tierTitle(g.tier))}</h2>${g.tier.key === "premium" ? `<span class="badge solid">${esc(T("sites.popular"))}</span>` : ""}
            <span class="tg-price">${esc(money(g.tier.price))}</span></div>
          <p class="hint">${esc(App.tx("sites.tg_" + g.tier.key, ""))}</p>
          <div class="tgrid">${g.items.map(App.tcard).join("")}</div></div>`).join("")}`;
      $$("[data-s]", body).forEach((b) => (b.onclick = () => { haptic(); p.section = b.dataset.s; App.render(); }));
      $$("[data-tpl]", body).forEach((b) => (b.onclick = () => {
        haptic();
        const pre = {};
        if (S.me.name) pre.kimdan = S.me.name;
        startOrder(b.dataset.tpl, pre, "");
      }));
      $("#fromVideo").onclick = () => { haptic(); pickEvent(); };
      return;
    }
    if (!sites.length) {
      body.innerHTML = `<div class="wrap" style="padding-top:16px"><div class="empty"><b>${esc(T("sites.none"))}</b>${esc(T("sites.none_sub"))}</div>
        <button type="button" class="btn" id="toDesigns">${esc(T("sites.pick"))}</button></div>`;
      $("#toDesigns").onclick = () => { p.mine = false; App.render(); };
      return;
    }
    body.innerHTML = `<div class="wrap stack" style="padding-top:16px">${sites.map((x) => {
      const t = S.cm.templates.find((y) => y.id === x.template);
      const title = [x.to, t ? tplName(t) : x.title].filter(Boolean).join(" — ");
      return `<div class="srow"><div class="top"><b>${esc(title)}</b><span class="badge ${x.paid ? "green" : "gold"}">${esc(T(x.paid ? "sites.live" : "sites.sample"))}</span></div>
        ${x.paid ? `<div class="mini3"><span><b>${x.views}</b><small>${esc(T("sites.views"))}</small></span><span><b>${x.reactions}</b><small>${esc(T("sites.replies"))}</small></span>
          <span><b>${esc(tierTitle(S.cm.tiers.find((y) => y.key === x.tarif) || { key: x.tarif, title: x.tarif || "" }))}</b><small>${esc(T("sites.tier"))}</small></span></div>`
          : `<p class="hint">${esc(T("sites.sample_note"))}</p>`}
        <div class="acts" style="display:flex;gap:8px;flex-wrap:wrap">
          ${x.paid ? "" : `<button type="button" class="btn sm" data-pay="${esc(x.slug)}" data-price="${x.price}">${esc(T("sites.pay", { sum: money(x.price) }))}</button>`}
          <button type="button" class="act" data-open="${esc(x.url)}">${icon("eye", "s")}${esc(T("open"))}</button>
          ${x.paid ? `<button type="button" class="act" data-share="${esc(x.public)}">${icon("share", "s")}${esc(T("share"))}</button>` : ""}
          ${x.event ? `<button type="button" class="act" data-event="${esc(x.event)}">${icon("users", "s")}${esc(T("videos.guests"))}</button>` : ""}</div></div>`;
    }).join("")}</div>`;
    $$("[data-open]", body).forEach((b) => (b.onclick = () => App.openLink(b.dataset.open)));
    $$("[data-share]", body).forEach((b) => (b.onclick = () => App.shareUrl(b.dataset.share, T("sites.share_text"))));
    $$("[data-event]", body).forEach((b) => (b.onclick = () => App.go("event", { slug: b.dataset.event })));
    $$("[data-pay]", body).forEach((b) => (b.onclick = () => paySite(b.dataset.pay, +b.dataset.price, b)));
  };

  async function paySite(slug, price, btn) {
    App.busy(btn, true);
    try {
      await api(`/api/sites/${encodeURIComponent(slug)}/pay`, {});
      notify("success"); toast(T("sites.paid"));
      await App.refreshMe(); App.render();
    } catch (e) {
      App.busy(btn, false);
      if (e.status === 402 && e.detail && e.detail.code === "paywall") {
        App.topupSheet({ need: Math.max(0, (e.detail.need || price) - (e.detail.balance || 0)), title: T("sites.need_title"),
          text: T("sites.need_text", { sum: money(e.detail.need || price), balance: money(e.detail.balance || 0) }) });
      } else toast(e.message);
    }
  }
  App.paySite = paySite;

  // ---------------------------------------------------------------- videodagi ma'lumotlardan sayt
  const coords = /^\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$/;
  function fromVideoData(data) {
    const pre = {
      kuyov: data.kuyov, kelin: data.kelin, sana: data.sana, vaqt: data.vaqt, manzil_nomi: data.joy, manzil: data.manzil,
      taklif_qiluvchilar: data.imzo, matn: data.matn,
    };
    const m = String(data.xarita || "").match(coords);
    pre.xarita = m ? `https://yandex.uz/maps/?pt=${m[2]},${m[1]}&z=17&l=map` : /^https:\/\//.test(data.xarita || "") ? data.xarita : "";
    return Object.fromEntries(Object.entries(pre).filter(([, v]) => v));
  }
  async function fromEvent(slug) {
    try {
      const ev = await api(`/api/events/${encodeURIComponent(slug)}`);
      if (ev.site_slug) { toast(T("sites.already")); return; }
      if (!ev.edit || ev.section !== "toy") { toast(T("sites.only_toy")); return; }
      const sheet = App.sheet(`<div class="sh-head"><div><h1>${esc(T("sites.from_video_t"))}</h1><p>${esc(T("sites.pick_tpl", { name: ev.who || ev.title }))}</p></div></div>
        <div class="carousel" style="margin:0 -18px">${S.cm.templates.filter((t) => t.section === "toy").map(App.tcard).join("")}</div>`);
      $$("[data-tpl]", sheet.el).forEach((b) => (b.onclick = () => { sheet.close(); startOrder(b.dataset.tpl, fromVideoData(ev.edit.data), "", slug); }));
    } catch (e) { toast(e.message); }
  }
  App.siteFromEvent = fromEvent;
  async function pickEvent() {
    let list = [];
    try { list = (await api("/api/events")).events.filter((e) => e.kind === "video" && e.section === "toy" && !e.site_slug); } catch { /* bo'sh */ }
    if (!list.length) {
      const s = App.sheet(`<div class="sh-head"><div><h1>${esc(T("sites.from_video_t"))}</h1><p>${esc(T("sites.no_video"))}</p></div></div>
        <button type="button" class="btn" id="mkV">${esc(T("sites.make_video"))}</button>`);
      $("#mkV", s.el).onclick = () => { s.close(); App.tab("videos", { section: "toy" }); };
      return;
    }
    const s = App.sheet(`<div class="sh-head"><div><h1>${esc(T("sites.which_event"))}</h1></div></div>
      <ul class="glist">${list.map((e) => `<li><button type="button" data-ev="${esc(e.slug)}"><span class="ini" style="background:var(--night)">${esc(App.initials(e.who || e.title))}</span>
        <span class="who"><b>${esc(e.who || e.title)}</b><small>${esc(e.title)}${e.date ? ", " + esc(App.fmtDate(e.date)) : ""}</small></span>${icon("chev")}</button></li>`).join("")}</ul>`);
    $$("[data-ev]", s.el).forEach((b) => (b.onclick = () => { s.close(); fromEvent(b.dataset.ev); }));
  }

  // ---------------------------------------------------------------- buyurtma
  let order = null;
  const tpl = () => S.cm.templates.find((t) => t.id === order.template);
  const tier = (k = order.tarif) => S.cm.tiers.find((t) => t.key === k);
  const colorLimit = () => Math.min(tpl().colors.length, tier().colors);
  const fields = () => S.cm.fields[tpl().section].filter((f) => f.tier <= tier().level && (!f.only.length || f.only.includes(order.template)));
  const save = () => store.put(OKEY, order);

  function startOrder(id, pre, tone, eventSlug) {
    const t = S.cm.templates.find((x) => x.id === id);
    if (!t) return;
    const prev = store.json(OKEY);
    const keys = new Set(t.v2 ? t.fields : S.cm.fields[t.section].map((f) => f.key));
    const data = Object.fromEntries(Object.entries(pre || {}).filter(([k]) => keys.has(k)));
    const reuse = prev && prev.template === t.id && !eventSlug && !Object.keys(pre || {}).filter((k) => k !== "kimdan").length;
    order = reuse ? prev : { template: t.id, tarif: t.vip ? "vip" : "premium", rang: 1, data, photos: [], music: null, unlock_at: null, _brief: tone ? `Uslub: ${tone}. ` : "", event: eventSlug || null };
    if (t.vip) order.tarif = "vip";
    if (t.premium && order.tarif === "standart") order.tarif = "premium";
    if (t.v2) { order.tarif = t.tier; order.hidden = order.hidden || []; }
    save();
    App.go("order", { step: 0 });
  }
  App.startOrder = startOrder;

  const STEP_KEYS = ["ord.s1", "ord.s2", "ord.s3", "ord.s4", "ord.s5"];
  // tarifli shablonda tarif tanlanmaydi: dizayn → ma'lumot va bloklar → suratlar → tayyor
  const STEP_KEYS2 = ["ord.s1", "ord.s3", "ord.s4", "ord.s5"];
  const KINDS = ["design", "tier", "data", "photos", "final"], KINDS2 = ["design", "data2", "photos", "final"];
  App.views.order = (p, el) => {
    if (!order) order = store.json(OKEY);
    if (!order || !tpl()) return App.back();
    App.chrome({ cta: true });
    const step = p.step || 0;
    const t = tpl();
    const kind = (t.v2 ? KINDS2 : KINDS)[step] || "final";
    const head = (title, sub) => `<div class="bar light"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button>
        <div class="ttl"><b>${esc(title)}</b><span>${esc(sub)}</span></div></div>
      <div class="wrap" style="padding-bottom:12px"><div class="dots">${(t.v2 ? STEP_KEYS2 : STEP_KEYS).map((_, i) => `<i class="${i <= step ? "on" : ""}"></i>`).join("")}</div></div>`;
    const cta = (label) => `<div class="cta"><div class="two"><button type="button" class="btn ghost back" id="prev" aria-label="${esc(T("back"))}">${icon("back")}</button>
      <button type="button" class="btn" id="next">${esc(label)}</button></div></div>`;
    const go = (n) => App.replace("order", { step: n });
    const demoUrl = () => `${t.demo}#${order.tarif}-${order.rang}`;
    const bindNav = (label, onNext) => {
      $("#bk").onclick = App.back;
      $("#prev").onclick = () => (step ? go(step - 1) : App.back());
      $("#next").onclick = (e) => { haptic(); onNext(e.currentTarget); };
    };

    if (kind === "design") {
      const tierCard = t.v2 ? `<section class="card" style="margin-top:14px"><div class="total"><span>${esc(tierTitle(tier()))}</span><b>${esc(money(tier().price))}</b></div>
          <ul class="tfeat">${tier().features.map((f, i) => `<li>${esc(tierFeat(tier(), i, f))}</li>`).join("")}</ul></section>` : "";
      el.innerHTML = head(tplName(t), T("ord.live")) + `
        <div class="wrap fade"><div class="phone"><div class="loading">${esc(T("loading"))}</div><iframe id="demo" src="${esc(t.v2 ? t.demo : demoUrl())}" title="${esc(T("ord.live"))}"></iframe></div>
          <p class="hint" style="text-align:center;margin-top:12px">${esc(T("ord.try"))}</p>${tierCard}</div>` + cta(T("ord.choose"));
      $("#demo").onload = () => { const l = $(".phone .loading"); if (l) l.remove(); };
      bindNav(0, () => go(1));
      return;
    }
    if (kind === "data2") return dataStep2(el, t, head, cta, bindNav, go);
    if (kind === "tier") {
      if (order.rang > colorLimit()) order.rang = 1;
      const lim = colorLimit();
      el.innerHTML = head(T("ord.s2"), tplName(t)) + `
        <div class="wrap stack fade">
          <div class="phone" style="width:min(190px,52vw)"><div class="loading">…</div><iframe id="demo" src="${esc(demoUrl())}" title="${esc(T("ord.live"))}"></iframe></div>
          <section class="card"><h2>${esc(T("ord.tier"))}</h2>
            <p class="hint" style="margin-bottom:10px">${esc(t.vip ? T("ord.only_vip") : t.premium ? T("ord.only_prem") : T("ord.tier_hint"))}</p>
            <div class="tiers" role="radiogroup">${S.cm.tiers.map((x) => `
              <button type="button" class="tier" role="radio" data-k="${x.key}" aria-checked="${x.key === order.tarif}" ${(t.vip && x.key !== "vip") || (t.premium && x.key === "standart") ? "disabled" : ""}>
                <span class="r1"><b>${esc(tierTitle(x))}</b><span>${esc(money(x.price))}</span></span>
                <ul>${x.features.map((f, i) => `<li>${esc(tierFeat(x, i, f))}</li>`).join("")}</ul></button>`).join("")}</div></section>
          <section class="card"><h2>${esc(T("ord.color"))}</h2><p class="hint" style="margin-bottom:10px">${esc(T("ord.colors", { tier: tierTitle(tier()), n: lim }))}</p>
            <div class="swatches">${t.swatch.slice(0, lim).map((c, i) => `
              <button type="button" class="sw" data-r="${i + 1}" aria-pressed="${order.rang === i + 1}" title="${esc(t.colors[i])}">
                <i style="background:conic-gradient(${c[1]} 0 50%, ${c[2]} 0 75%, ${c[0]} 0)"></i><span>${esc(t.colors[i])}</span></button>`).join("")}</div>
            ${lim < t.colors.length ? `<p class="hint" style="text-align:center;margin-top:10px">${esc(T("ord.more_colors", { n: t.colors.length - lim }))}</p>` : ""}</section></div>` +
        cta(T("ord.next_sum", { sum: money(tier().price) }));
      $("#demo").onload = () => { const l = $(".phone .loading"); if (l) l.remove(); };
      $$(".tier", el).forEach((b) => (b.onclick = () => { if (b.disabled) return; haptic(); order.tarif = b.dataset.k; save(); App.render(); }));
      $$(".sw", el).forEach((b) => (b.onclick = () => {
        haptic(); order.rang = +b.dataset.r; save();
        $$(".sw", el).forEach((x) => x.setAttribute("aria-pressed", x === b));
        $("#demo").src = demoUrl();
      }));
      bindNav(1, () => go(2));
      return;
    }
    if (kind === "data") {
      const fs = fields();
      const base = fs.filter((f) => f.tier === 1), extra = fs.filter((f) => f.tier > 1);
      el.innerHTML = head(T("ord.s3"), tplName(t)) + `<div class="wrap stack fade">
        <section class="card stack">${base.map(fieldHtml).join("")}</section>
        ${extra.length ? `<section class="card stack"><h2>${esc(T("ord.extra", { tier: tierTitle(tier()) }))}</h2><p class="hint">${esc(T("ord.extra_hint"))}</p>${extra.map(fieldHtml).join("")}</section>` : ""}</div>` +
        cta(T("continue"));
      bindInfo(el, fs);
      bindNav(2, () => {
        const miss = fs.find((f) => f.required && (order.data[f.key] == null || String(order.data[f.key]).trim() === ""));
        if (miss) { notify("error"); toast(T("err.required", { f: fLabel(miss) })); const x = $(`[data-k="${miss.key}"]`, el); if (x) { x.classList.add("bad"); x.scrollIntoView({ block: "center", behavior: "smooth" }); } return; }
        go(3);
      });
      return;
    }
    if (kind === "photos") {
      const lim = t.v2 ? Math.min(tier().photos, Math.max(t.slots || 1, 6)) : tier().photos;
      el.innerHTML = head(T("ord.s4"), tplName(t)) + `<div class="wrap stack fade">
        <section class="card"><h2>${esc(T("ord.photos"))}</h2><p class="hint">${esc(T("ord.photos_hint", { tier: tierTitle(tier()), n: lim }))}</p>
          <span class="btn ghost upload" id="photoUp" style="margin-top:10px">${icon("plus", "s")}${esc(T("ord.add_photo"))}<input type="file" id="photoIn" accept="image/*" multiple></span>
          <div class="photos" id="photos"></div></section>
        <section class="card"><h2>${esc(T("ord.music"))}</h2><p class="hint">${esc(T("ord.music_hint"))}</p><div id="music" style="margin-top:10px"></div></section></div>` +
        cta(T("ord.preview"));
      let pending = 0;
      const drawPhotos = () => {
        const box = $("#photos");
        box.innerHTML = order.photos.map((u, i) => `<div><img src="${esc(u)}" alt=""><button type="button" data-i="${i}" aria-label="${esc(T("remove"))}">✕</button></div>`).join("")
          + `<div class="wait"><span class="spin"></span></div>`.repeat(pending);
        $$("button", box).forEach((b) => (b.onclick = () => { order.photos.splice(+b.dataset.i, 1); save(); drawPhotos(); }));
        $("#photoUp").hidden = order.photos.length >= lim;
      };
      const drawMusic = () => {
        const box = $("#music");
        if (order.music) {
          box.innerHTML = `<audio controls src="${esc(order.music)}" style="width:100%"></audio><button type="button" class="btn ghost sm" id="rmMusic" style="margin-top:8px">${esc(T("remove"))}</button>`;
          $("#rmMusic").onclick = () => { order.music = null; save(); drawMusic(); };
        } else {
          box.innerHTML = `<span class="btn ghost upload" id="musicUp">${icon("music", "s")}${esc(T("ord.pick_music"))}<input type="file" id="musicIn" accept="audio/*"></span>`;
          $("#musicIn").onchange = async (e) => {
            const f = e.target.files[0]; if (!f) return;
            $("#musicUp").innerHTML = `<span class="spin"></span>`;
            const fd = new FormData(); fd.append("file", f);
            try { order.music = (await api("/api/upload?kind=music", fd)).url; save(); } catch (err) { toast(err.message); }
            drawMusic();
          };
        }
      };
      drawPhotos(); drawMusic();
      $("#photoIn").onchange = async (e) => {
        const files = [...e.target.files].slice(0, lim - order.photos.length);
        e.target.value = "";
        if (!files.length) { toast(T("ord.max_photos", { n: lim })); return; }
        pending = files.length; drawPhotos();
        for (const f of files) {
          const fd = new FormData(); fd.append("file", f);
          try { const { url } = await api("/api/upload?kind=photo", fd); order.photos.push(url); save(); } catch (err) { toast(err.message); }
          pending--; if ($("#photos")) drawPhotos();
        }
      };
      bindNav(step, () => { if (pending) { toast(T("ord.wait_photos")); return; } go(step + 1); });
      return;
    }
    // 5. ko'rish va yaratish
    el.innerHTML = head(T("ord.s5"), tplName(t)) + `<div class="wrap stack fade">
      <div class="phone"><div class="loading"><span class="spin"></span></div><iframe id="pv" title="${esc(T("ord.preview"))}"></iframe></div>
      <p class="hint" style="text-align:center">${esc(T("ord.sample_note"))}</p>
      <section class="card">${App.switchHtml("swSurp", T("ord.surprise"), T("ord.surprise_sub"), !!order.unlock_at)}
        <div class="grid2" id="surpBox" style="margin-top:12px" ${order.unlock_at ? "" : "hidden"}>
          <input type="date" id="surpDate" value="${esc((order.unlock_at || "").slice(0, 10))}" aria-label="${esc(T("ord.surprise_date"))}">
          <input type="time" id="surpTime" value="${esc((order.unlock_at || "T00:00").slice(11, 16) || "00:00")}" aria-label="${esc(T("ord.surprise_time"))}"></div></section>
      <section class="card"><div class="total"><span>${esc(tplName(t))}, ${esc(tierTitle(tier()))}</span><b>${esc(money(tier().price))}</b></div>
        <p class="hint" style="margin-top:6px">${esc(T("ord.pay_hint", { balance: money((S.me.quota || {}).balance || 0) }))}</p></section></div>` +
      cta(T("ord.create"));
    const surp = () => {
      const on = $("#swSurp").getAttribute("aria-checked") === "true", dt = $("#surpDate").value, tm = $("#surpTime").value || "00:00";
      $("#surpBox").hidden = !on;
      order.unlock_at = on && dt ? `${dt}T${tm}` : null; save();
    };
    App.bindSwitch($("#swSurp"), (on) => {
      if (on && !$("#surpDate").value) { const s = order.data.sana, td = new Date().toISOString().slice(0, 10); if (s && s > td) $("#surpDate").value = s; }
      surp();
    });
    $("#surpDate").onchange = surp; $("#surpTime").onchange = surp;
    bindNav(step, (btn) => create(btn));
    api("/api/catalog/preview", order, { raw: true }).then((html) => {
      const pv = $("#pv"); if (!pv) return;
      pv.srcdoc = html; pv.onload = () => { const l = $(".phone .loading"); if (l) l.remove(); };
    }).catch((e) => { const l = $(".phone .loading"); if (l) l.textContent = e.message; });
  };

  // ---------------------------------------------------------------- tarifli shablon: ma'lumot va bloklar
  function dataStep2(el, t, head, cta, bindNav, go) {
    const sec = t.section;
    const byKey = Object.fromEntries(S.cm.fields2[sec].filter((f) => t.fields.includes(f.key)).map((f) => [f.key, f]));
    order.hidden = (order.hidden || []).filter((k) => t.blocks.some((b) => b.key === k));
    const hero = t.hero.map((k) => byKey[k]).filter(Boolean);
    const shown = t.blocks.filter((b) => !order.hidden.includes(b.key));
    const gone = t.blocks.filter((b) => order.hidden.includes(b.key));
    const bFields = (b) => b.fields.map((k) => byKey[k]).filter(Boolean);
    const note = (b) => b.needs.includes("@photos") ? App.tx("ord.b_photos", "Suratlar keyingi qadamda qo'shiladi.")
      : b.needs.includes("@music") ? App.tx("ord.b_music", "Musiqa keyingi qadamda qo'shiladi.")
      : App.tx("ord.b_ready", "Ma'lumot kerak emas — saytda tayyor holda chiqadi.");
    const upsell = t.tier === "standart" && S.cm.templates.some((x) => x.section === sec && tierOf(x) === "premium")
      ? `<button type="button" class="banner" id="tryPrem">${icon("sparkle")}<span><b>${esc(App.tx("ord.try_prem", "Premium'da ko'ring"))}</b>${esc(App.tx("ord.try_prem_s", "Shu ma'lumotlar bilan saytingiz Premium dizaynda qanday ko'rinadi"))}</span>${icon("chev")}</button>` : "";
    el.innerHTML = head(T("ord.s3"), tplName(t)) + `<div class="wrap stack fade">${upsell}
      <section class="card stack"><h2>${esc(App.tx("ord.main", "Asosiy"))}</h2>${hero.map(fieldHtml).join("")}</section>
      <p class="hint">${esc(App.tx("ord.b_hint", "Ma'lumot topa olmasangiz, blokni olib tashlang — sayt baribir chiroyli qoladi. Keyin qaytarish mumkin."))}</p>
      ${shown.map((b) => `<section class="card stack blk"><div class="blk-head"><h2>${esc(blockTitle(sec, b))}</h2>
          <button type="button" class="btn ghost sm" data-rmblk="${esc(b.key)}" aria-label="${esc(App.tx("ord.b_remove", "Olib tashlash") + ": " + blockTitle(sec, b))}">✕ ${esc(App.tx("ord.b_remove", "Olib tashlash"))}</button></div>
          ${bFields(b).map(fieldHtml).join("") || `<p class="hint">${esc(note(b))}</p>`}</section>`).join("")}
      ${gone.length ? `<section class="card"><h2>${esc(App.tx("ord.b_gone", "Olib tashlanganlar"))}</h2><ul class="gone">${gone.map((b) =>
        `<li><span>${esc(blockTitle(sec, b))}</span><button type="button" class="btn ghost sm" data-backblk="${esc(b.key)}">${esc(App.tx("ord.b_back", "Qaytarish"))}</button></li>`).join("")}</ul></section>` : ""}
      </div>` + cta(T("continue"));
    const fs = hero.concat(...shown.map(bFields));
    bindInfo(el, fs);
    $$("[data-rmblk]", el).forEach((b) => (b.onclick = () => {
      haptic(); order.hidden.push(b.dataset.rmblk); save();
      toast(App.tx("ord.b_removed", "Blok olib tashlandi")); App.render();
    }));
    $$("[data-backblk]", el).forEach((b) => (b.onclick = () => {
      haptic(); order.hidden = order.hidden.filter((k) => k !== b.dataset.backblk); save(); App.render();
    }));
    const tp = $("#tryPrem");
    if (tp) tp.onclick = () => {
      haptic();
      const list = S.cm.templates.filter((x) => x.section === sec && tierOf(x) === "premium").sort((a, b) => (a.order || 50) - (b.order || 50));
      const sh = App.sheet(`<div class="sh-head"><div><h1>${esc(App.tx("ord.try_prem", "Premium'da ko'ring"))}</h1>
          <p>${esc(App.tx("ord.try_prem_p", "Tanlang — kiritgan ma'lumotlaringiz saqlanadi"))}</p></div></div>
        <div class="carousel" style="margin:0 -18px">${list.map(App.tcard).join("")}</div>`);
      $$("[data-tpl]", sh.el).forEach((x) => (x.onclick = () => {
        const nt = S.cm.templates.find((y) => y.id === x.dataset.tpl);
        sh.close(); haptic();
        order.template = nt.id; order.tarif = nt.tier; order.hidden = []; save();
        App.replace("order", { step: 0 });
      }));
    };
    bindNav(1, () => {
      const miss = hero.find((f) => f.required && (order.data[f.key] == null || String(order.data[f.key]).trim() === ""));
      if (miss) { notify("error"); toast(T("err.required", { f: fLabel(miss) })); const x = $(`[data-k="${miss.key}"]`, el); if (x) { x.classList.add("bad"); x.scrollIntoView({ block: "center", behavior: "smooth" }); } return; }
      go(2);
    });
  }

  function fieldHtml(f) {
    const v = order.data[f.key];
    const tag = f.tier > 1 ? ` <span class="badge gold" style="padding:1px 7px;font-size:10px">${f.tier === 2 ? "Premium" : "VIP"}</span>` : "";
    const lab = `${esc(fLabel(f))}${f.required ? "" : ` <em>${esc(T("optional"))}</em>`}${tag}`;
    const hint = fHint(f) ? `<small>${esc(fHint(f))}</small>` : "";
    const k = esc(f.key);
    switch (f.kind) {
      case "choice":
        return `<div class="field">${lab}<div class="chips">${Object.entries(f.options).map(([val, txt]) =>
          `<button type="button" class="chip" data-choice="${k}" data-v="${esc(val)}" aria-pressed="${v === val}">${esc(App.tx(`cfo.${f.key}.${val}`, txt))}</button>`).join("")}</div>${hint}</div>`;
      case "date": return `<label class="field">${lab}<input type="date" data-k="${k}" value="${esc(v || "")}">${hint}</label>`;
      case "time": return `<label class="field">${lab}<input type="time" data-k="${k}" value="${esc(v || "")}">${hint}</label>`;
      case "url": return `<label class="field">${lab}<input type="url" inputmode="url" placeholder="https://" data-k="${k}" value="${esc(v || "")}">${hint}</label>`;
      case "tel": return `<label class="field">${lab}<input type="tel" placeholder="+998 90 123 45 67" data-k="${k}" value="${esc(v || "")}">${hint}</label>`;
      case "lines": return `<label class="field">${lab}<textarea rows="4" data-k="${k}" data-lines="1">${esc((v || []).join("\n"))}</textarea>${hint}</label>`;
      case "photo": return `<div class="field">${lab}${v ? `<div class="photos" style="grid-template-columns:1fr 2fr"><div><img src="${esc(v)}" alt=""><button type="button" data-rmphoto="${k}">✕</button></div></div>` : ""}
        <span class="btn ghost sm upload" style="margin-top:8px">${icon("photo", "s")}${esc(T("ord.pick_photo"))}<input type="file" accept="image/*" data-photo="${k}"></span>${hint}</div>`;
      case "items": return `<div class="field">${lab}${hint}<div data-items="${k}"></div><button type="button" class="btn ghost sm" data-add="${k}">+ ${esc(T("add"))}</button></div>`;
      case "textarea":
        if (f.ai) return `<div class="field">${lab}
          <div class="ai-box"><p>${icon("sparkle", "xs")} ${esc(T("ord.ai_title"))}</p>
            <textarea rows="2" id="brief" placeholder="${esc(T("ord.ai_ph"))}">${esc(order._brief || "")}</textarea>
            <button type="button" class="btn sm" id="aiBtn" data-ai="${k}">${esc(v ? T("ed.ai_again") : T("ed.ai"))}</button></div>
          <textarea rows="8" data-k="${k}" maxlength="3000" placeholder="${esc(T("ord.text_ph"))}">${esc(v || "")}</textarea>${hint}</div>`;
        return `<label class="field">${lab}<textarea rows="3" data-k="${k}">${esc(v || "")}</textarea>${hint}</label>`;
      default: return `<label class="field">${lab}<input data-k="${k}" maxlength="300" value="${esc(v || "")}">${hint}</label>`;
    }
  }
  function drawItems(f, box) {
    const rows = order.data[f.key] || [];
    box.innerHTML = rows.map((row, i) => `<div class="item"><button type="button" class="rm" data-rm="${i}" aria-label="${esc(T("remove"))}">✕</button>${f.sub.map(([sk, sl, kind]) => {
      let val = row[sk];
      if (kind === "csv") val = (val || []).join(", ");
      if (kind === "index") val = (val ?? 0) + 1;
      const type = kind === "time" ? "time" : kind === "index" ? "number" : "text";
      return `<input type="${type}" placeholder="${esc(App.tx(`cfs.${f.key}.${sk}`, sl))}" data-i="${i}" data-sk="${esc(sk)}" data-kind="${kind}" value="${esc(val ?? "")}" ${kind === "index" ? 'min="1" max="6"' : ""}>`;
    }).join("")}</div>`).join("");
    $$("input", box).forEach((x) => (x.oninput = () => {
      const row = order.data[f.key][+x.dataset.i];
      if (x.dataset.kind === "csv") row[x.dataset.sk] = x.value.split(",").map((s) => s.trim()).filter(Boolean);
      else if (x.dataset.kind === "index") row[x.dataset.sk] = Math.max(0, (+x.value || 1) - 1);
      else row[x.dataset.sk] = x.value;
      save();
    }));
    $$("[data-rm]", box).forEach((b) => (b.onclick = () => { order.data[f.key].splice(+b.dataset.rm, 1); save(); drawItems(f, box); }));
  }
  function bindInfo(el, fs) {
    $$("[data-k]", el).forEach((x) => (x.oninput = () => { x.classList.remove("bad"); order.data[x.dataset.k] = x.dataset.lines ? x.value.split("\n") : x.value; save(); }));
    $$("[data-choice]", el).forEach((b) => (b.onclick = () => {
      haptic(); order.data[b.dataset.choice] = b.dataset.v; save();
      $$(`[data-choice="${b.dataset.choice}"]`, el).forEach((x) => x.setAttribute("aria-pressed", x === b));
    }));
    fs.filter((f) => f.kind === "items").forEach((f) => {
      const box = $(`[data-items="${f.key}"]`, el);
      drawItems(f, box);
      $(`[data-add="${f.key}"]`, el).onclick = () => {
        haptic(); (order.data[f.key] = order.data[f.key] || []).push(Object.fromEntries(f.sub.map(([sk, , kind]) => [sk, kind === "csv" ? [] : kind === "index" ? 0 : ""])));
        save(); drawItems(f, box);
      };
    });
    $$("[data-photo]", el).forEach((inp) => (inp.onchange = async () => {
      const file = inp.files[0]; if (!file) return;
      const fd = new FormData(); fd.append("file", file);
      try { order.data[inp.dataset.photo] = (await api("/api/upload?kind=photo", fd)).url; save(); App.render(); } catch (e) { toast(e.message); }
    }));
    $$("[data-rmphoto]", el).forEach((b) => (b.onclick = () => { delete order.data[b.dataset.rmphoto]; save(); App.render(); }));
    const brief = $("#brief"); if (brief) brief.oninput = () => { order._brief = brief.value; save(); };
    const aiBtn = $("#aiBtn");
    if (aiBtn) aiBtn.onclick = async () => {
      const key = aiBtn.dataset.ai, ta = $(`[data-k="${key}"]`, el);
      App.busy(aiBtn, true, T("ed.ai_busy"));
      try {
        const r = await api("/api/catalog/ai/write", { template: order.template, data: order.data, brief: order._brief || "", previous: order.data[key] || null });
        order.data[key] = r.text; ta.value = r.text; save(); notify("success");
      } catch (e) { toast(e.message); }
      App.busy(aiBtn, false);
      aiBtn.textContent = order.data[key] ? T("ed.ai_again") : T("ed.ai");
    };
  }

  async function create(btn) {
    App.busy(btn, true, T("ord.creating"));
    try {
      const res = await api("/api/catalog/sites", order);
      store.del(OKEY);
      const who = order.data.kimga || order.data.kuyov || "";
      order = null;
      notify("success");
      await App.refreshMe().catch(() => {});
      App.replace("order_done", { url: res.url, slug: res.slug, who });
    } catch (e) { App.busy(btn, false); toast(e.message); }
  }

  App.views.order_done = (p, el) => {
    App.chrome({});
    const conf = [["#D02670", -80, -90, 200], ["#F5B20A", 70, -110, -160], ["#0F7A59", -30, -130, 120], ["#D02670", 100, -50, 240], ["#F5B20A", -110, -30, -200], ["#211C52", 30, -150, 180]];
    const site = (S.me.sites || []).find((x) => x.slug === p.slug);
    const bal = (S.me.quota || {}).balance || 0;
    el.innerHTML = `<div class="done fade">
      <svg class="gift" viewBox="0 0 200 170" aria-hidden="true">
        <defs><pattern id="ik2" width="24" height="48" patternUnits="userSpaceOnUse"><rect width="24" height="48" fill="#D02670"/><path d="M12 2l3 6-1.5 1 4.5 7-1.5 1 4.5 7-4.5 7 1.5 1-4.5 7 1.5 1-3 6-3-6 1.5-1-4.5-7 1.5-1-4.5-7 4.5-7-1.5-1 4.5-7-1.5-1z" fill="#F5B20A"/></pattern></defs>
        <g class="burst">${conf.map(([c, dx, dy, r]) => `<rect x="96" y="70" width="8" height="14" rx="2" fill="${c}" style="--dx:${dx}px;--dy:${dy}px;--r:${r}deg"/>`).join("")}</g>
        <rect x="45" y="80" width="110" height="80" rx="10" fill="var(--surface)"/><rect x="88" y="80" width="24" height="80" fill="url(#ik2)"/>
        <g class="lid"><rect x="36" y="58" width="128" height="26" rx="8" fill="var(--surface2)"/><rect x="88" y="58" width="24" height="26" fill="url(#ik2)"/></g></svg>
      <h1>${esc(p.who ? T("done.title_who", { name: p.who }) : T("done.title"))}</h1>
      <p>${esc(T("done.text"))}</p>
      <div class="stack" style="width:100%;max-width:420px">
        ${site && !site.paid ? `<button type="button" class="btn" id="payNow">${esc(T("sites.pay", { sum: money(site.price) }))}</button>
          <p class="hint">${esc(T("done.balance", { balance: money(bal) }))}</p>` : ""}
        <button type="button" class="btn ${site && !site.paid ? "ghost" : ""}" id="openSite">${icon("eye", "s")}${esc(T("done.open"))}</button>
        <button type="button" class="btn ghost" id="toChat">${esc(T("go_chat"))}</button>
        <button type="button" class="btn ghost" id="toMine">${esc(T("done.mine"))}</button></div></div>`;
    $("#openSite").onclick = () => App.openLink(p.url);
    $("#toChat").onclick = () => App.closeApp();
    $("#toMine").onclick = () => App.tab("sites", { mine: true });
    const pay = $("#payNow");
    if (pay) pay.onclick = () => paySite(p.slug, site.price, pay);
  };
})();
