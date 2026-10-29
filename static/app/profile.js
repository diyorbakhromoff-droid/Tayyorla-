/* Profil: bepul videolar, balans, do'stlar, til, to'lovlar tarixi va admin paneli */
(() => {
  "use strict";
  const { $, $$, esc, T, icon, S, api, haptic, notify, toast, store, money } = App;
  const LANG_SUB = { uz: "lang.uz_sub", cy: "lang.cy_sub", ru: "lang.ru_sub", en: "lang.en_sub", kaa: "lang.kaa_sub", tg: "lang.tg_sub", kk: "lang.kk_sub" };
  const CONTINUE = { uz: "Davom etish", cy: "Давом этиш", ru: "Продолжить", en: "Continue", kaa: "Dawam etiw", tg: "Идома додан", kk: "Жалғастыру" };
  const langName = (k) => ((S.vm.langs || []).find((l) => l.key === k) || { name: k }).name;

  // ---------------------------------------------------------------- Profil
  App.views.profile = (p, el) => {
    App.chrome({ tabs: true });
    const me = S.me, q = me.quota || {};
    const per = q.free_per_day || 2, left = q.free_left || 0;
    const cardLang = store.get("tyr-card-lang") || "auto";
    el.innerHTML = `
      <header class="prof-head"><span class="av"><b>${esc(App.initials(me.name).slice(0, 1))}</b></span>
        <div><h1>${esc(me.name || "Tayyorla")}</h1><p>${esc(me.stats && me.stats.happy ? T("pr.happy", { n: me.stats.happy }) : T("pr.happy0"))}</p></div></header>
      <div class="wrap stack fade" style="padding-top:16px">
        <section class="wallet">
          <div><span class="l">${esc(T("pr.free_today"))}</span><b>${left} <small>${esc(T("pr.of", { n: per }))}</small></b>
            <span class="bars">${Array.from({ length: per }, (_, i) => `<i class="${i < left ? "on" : ""}"></i>`).join("")}</span>
            <span class="tiny">${esc(q.bonus ? T("pr.bonus", { n: q.bonus }) : T("pr.reset"))}</span></div>
          <div class="dark"><span class="l">${esc(T("pr.balance"))}</span><b>${esc(App.fmtNum(q.balance || 0))} <small>${esc(T("sum"))}</small></b>
            <button type="button" class="btn gold xs" id="topup" style="margin-top:auto">${esc(T("pr.topup"))}</button></div></section>
        <p class="hint">${esc(T("pr.price_note", { sum: money(q.price || S.vm.price) }))}</p>
        <button type="button" class="banner" id="invite">${icon("gift")}<span><b>${esc(T("pr.invite_t"))}</b>${esc(T("pr.invite_s"))}</span>${icon("share")}</button>
        <nav class="menu">
          <button type="button" data-go="people"><span class="ic">${icon("users", "s")}</span><span class="t"><b>${esc(T("pr.people"))}</b><small>${esc(T("pr.people_n", { n: (me.people || []).length }))}</small></span>${icon("chev", "s chev")}</button>
          <button type="button" data-go="language"><span class="ic">${icon("globe", "s")}</span><span class="t"><b>${esc(T("pr.app_lang"))}</b><small>${esc(langName(App.lang))}</small></span>${icon("chev", "s chev")}</button>
          <button type="button" id="cardLang"><span class="ic">Aa</span><span class="t"><b>${esc(T("pr.card_lang"))}</b><small>${esc(cardLang === "auto" ? T("pr.card_auto") : langName(cardLang))}</small></span>${icon("chev", "s chev")}</button>
          <button type="button" data-go="wallet"><span class="ic">${icon("wallet", "s")}</span><span class="t"><b>${esc(T("pr.history"))}</b><small>${esc(T("pr.history_s"))}</small></span>${icon("chev", "s chev")}</button>
          <button type="button" id="channel"><span class="ic">${icon("channel", "s")}</span><span class="t"><b>${esc(T("pr.channel"))}</b><small>${esc(T("pr.channel_s"))}</small></span><span class="badge solid">${esc(T("pr.subscribe"))}</span></button>
          <button type="button" id="help"><span class="ic">${icon("help", "s")}</span><span class="t"><b>${esc(T("pr.help"))}</b><small>${esc(T("pr.help_s"))}</small></span>${icon("chev", "s chev")}</button>
          ${me.admin ? `<button type="button" data-go="admin"><span class="ic">${icon("sliders", "s")}</span><span class="t"><b>${esc(T("pr.admin"))}</b><small>${esc(T("pr.admin_s"))}</small></span>${icon("chev", "s chev")}</button>` : ""}
        </nav>
        ${(me.messages || []).length ? `<h2 style="font-size:21px;margin-top:8px">${esc(T("pr.answers"))}</h2>
          <div class="answers">${me.messages.map((m) => `<p><b>${esc(m.title)}</b>${esc(m.emoji)} ${esc(m.text)}</p>`).join("")}</div>` : ""}
      </div>`;
    $("#topup").onclick = () => { haptic(); App.topupSheet({ onSent: () => App.render() }); };
    $("#invite").onclick = () => { haptic(); App.shareUrl(me.ref_link, T("ref.share_text")); };
    $$("[data-go]", el).forEach((b) => (b.onclick = () => { haptic(); App.go(b.dataset.go); }));
    $("#cardLang").onclick = () => { haptic(); cardLangSheet(); };
    $("#channel").onclick = () => App.openLink(me.channel || S.vm.channel);
    $("#help").onclick = () => App.openLink(`https://t.me/${S.vm.bot}?start=help`);
  };

  function cardLangSheet() {
    const cur = store.get("tyr-card-lang") || "auto";
    const opts = [{ key: "auto", name: T("pr.card_auto") }, ...S.vm.langs];
    const s = App.sheet(`<div class="sh-head"><div><h1>${esc(T("pr.card_lang"))}</h1><p>${esc(T("pr.card_lang_s"))}</p></div></div>
      <div class="lang-list" role="radiogroup">${opts.map((l) => `<button type="button" role="radio" data-l="${l.key}" aria-checked="${l.key === cur}">
        <span class="code">${esc(l.key === "auto" ? "A" : App.LANG_CODE[l.key] || l.key)}</span><span class="t"><b>${esc(l.name)}</b></span><span class="radio"></span></button>`).join("")}</div>`);
    $$("[data-l]", s.el).forEach((b) => (b.onclick = () => {
      haptic();
      store.set("tyr-card-lang", b.dataset.l);
      const d = App.Draft.get();
      if (d && !d.site) { d.lang = b.dataset.l; App.Draft.set(d); }
      s.close(); App.render();
    }));
  }

  // ---------------------------------------------------------------- ilova tili
  App.views.language = (p, el) => {
    App.chrome({ night: true, cta: true });
    let pick = p.pick || App.lang;
    const langs = S.vm.langs;
    el.innerHTML = `
      <div class="bar"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button><div class="ttl"></div></div>
      <header class="lang-head"><h1>${esc(T("lang.title"))}</h1><p>Выберите язык<br>Choose language</p></header>
      <div class="wrap stack fade" style="padding-top:16px">
        <section class="lang-list" role="radiogroup">${langs.map((l) => `<button type="button" role="radio" data-l="${l.key}" aria-checked="${l.key === pick}">
          <span class="code">${esc(App.LANG_CODE[l.key] || l.key)}</span><span class="t"><b>${esc(l.name)}</b><small>${esc(T(LANG_SUB[l.key]))}</small></span><span class="radio"></span></button>`).join("")}</section>
        <p class="hint">${esc(T("lang.note"))}</p></div>
      <div class="cta"><button type="button" class="btn" id="langGo">${esc(CONTINUE[pick] || T("continue"))}</button></div>`;
    $("#bk").onclick = App.back;
    $$("[data-l]", el).forEach((b) => (b.onclick = () => {
      haptic(); pick = b.dataset.l; p.pick = pick;
      $$("[data-l]", el).forEach((x) => x.setAttribute("aria-checked", x === b));
      $("#langGo").textContent = CONTINUE[pick] || T("continue");
    }));
    $("#langGo").onclick = async (e) => {
      App.busy(e.currentTarget, true);
      try {
        if (pick !== App.lang) {
          await api("/api/me/lang", { lang: pick });
          S.me.lang = pick;
          const v = (document.querySelector('script[src*="core.js"]') || {}).src || "";
          await App.loadDict(pick, (v.split("v=")[1] || "1"));
          S.vm = await api(`/api/video/meta?lang=${pick}`);
        }
        notify("success");
        App.tab(App.nav.length > 1 && App.nav[0].v === "profile" ? "profile" : "home");
      } catch (err) { App.busy(e.currentTarget, false); toast(err.message); }
    };
  };

  // ---------------------------------------------------------------- to'lovlar tarixi
  const TX = { topup: "tx.topup", video: "tx.video", site: "tx.site", package: "tx.package", refund: "tx.refund", bonus: "tx.bonus", admin: "tx.admin" };
  App.views.wallet = (p, el) => {
    App.chrome({});
    el.innerHTML = `<div class="bar light"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button>
      <div class="ttl"><b>${esc(T("pr.history"))}</b><span>${esc(T("pr.history_s"))}</span></div></div>
      <div class="wrap stack fade" id="wbody"><div class="empty"><span class="spin"></span></div></div>`;
    $("#bk").onclick = App.back;
    api("/api/wallet").then((w) => {
      S.me.quota = { ...S.me.quota, free_left: w.free_left, bonus: w.bonus, balance: w.balance, price: w.price, free_per_day: w.free_per_day };
      const box = $("#wbody"); if (!box) return;
      box.innerHTML = `
        <section class="wallet"><div class="dark"><span class="l">${esc(T("pr.balance"))}</span><b>${esc(App.fmtNum(w.balance))} <small>${esc(T("sum"))}</small></b></div>
          <div><span class="l">${esc(T("pr.free_today"))}</span><b>${w.free_left} <small>${esc(T("pr.of", { n: w.free_per_day }))}</small></b><span class="tiny">${esc(w.bonus ? T("pr.bonus", { n: w.bonus }) : T("pr.reset"))}</span></div></section>
        <button type="button" class="btn" id="tp">${icon("plus", "s")}${esc(T("pr.topup"))}</button>
        ${w.pending.length ? `<div class="note">${esc(T("w.pending", { n: w.pending.length, sum: money(w.pending.reduce((a, x) => a + x.amount, 0)) }))}</div>` : ""}
        ${w.history.length ? `<ul class="hist">${w.history.map((t) => `<li><span>${esc(T(TX[t.kind] || "tx.other"))}<small>${esc(App.fmtDate(t.at.slice(0, 10), { year: true }))}</small></span>
          <span class="${t.amount > 0 ? "plus" : "minus"}">${t.amount > 0 ? "+" : "−"}${esc(money(Math.abs(t.amount)))}</span></li>`).join("")}</ul>`
          : `<div class="empty"><b>${esc(T("w.empty"))}</b>${esc(T("w.empty_s"))}</div>`}`;
      $("#tp").onclick = () => App.topupSheet({ onSent: () => App.render() });
    }).catch((e) => { const box = $("#wbody"); if (box) box.innerHTML = App.errBox(e); });
  };

  // ---------------------------------------------------------------- admin: statistika va musiqa
  App.views.admin = (p, el) => {
    App.chrome({});
    el.innerHTML = `<div class="bar light"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button>
      <div class="ttl"><b>${esc(T("pr.admin"))}</b><span>${esc(T("pr.admin_s"))}</span></div></div>
      <div class="wrap stack fade">
        <div class="seg" role="tablist"><button type="button" role="tab" data-t="music" aria-selected="${p.tab !== "stats"}">${esc(T("ad.music"))}</button>
          <button type="button" role="tab" data-t="stats" aria-selected="${p.tab === "stats"}">${esc(T("ad.stats"))}</button></div>
        <div id="abody"><div class="empty"><span class="spin"></span></div></div></div>`;
    $("#bk").onclick = App.back;
    $$("[data-t]", el).forEach((b) => (b.onclick = () => { p.tab = b.dataset.t; App.render(); }));
    const box = $("#abody");
    if (p.tab === "stats") {
      api("/api/admin/stats").then((s) => {
        const flat = [];
        const walk = (o, pre) => Object.entries(o).forEach(([k, v]) => (v && typeof v === "object" && !Array.isArray(v) ? walk(v, pre + k + ".") : flat.push([pre + k, v])));
        walk(s, "");
        box.innerHTML = `<div class="statgrid">${flat.map(([k, v]) => `<span><b>${esc(typeof v === "number" ? App.fmtNum(v) : v)}</b><small>${esc(App.tx("ads." + k, k))}</small></span>`).join("")}</div>`;
      }).catch((e) => { box.innerHTML = App.errBox(e); });
      return;
    }
    api("/api/admin/music").then(({ themes, tracks }) => {
      box.innerHTML = `
        <section class="card stack"><h2>${esc(T("ad.add"))}</h2>
          <span class="drop upload" id="adDrop"><span class="ic">${icon("upload")}</span><b id="adFile">${esc(T("ad.file"))}</b><small>${esc(T("ad.file_s"))}</small><input type="file" accept="audio/*" id="adIn"></span>
          <label class="field">${esc(T("ad.t_title"))}<input id="adTitle" maxlength="100" placeholder="${esc(T("ad.t_title_ph"))}"></label>
          <label class="field">${esc(T("ad.t_sub"))} <em>${esc(T("optional"))}</em><input id="adSub" maxlength="150" placeholder="${esc(T("ad.t_sub_ph"))}"></label>
          <div class="field">${esc(T("ad.theme"))}<div class="chips" id="adTheme">${themes.map((k, i) => `<button type="button" class="chip" data-th="${k}" aria-pressed="${i === 0}">${esc(T("mut." + k))}</button>`).join("")}</div></div>
          <div class="field">${esc(T("ad.kind"))}<div class="seg"><button type="button" data-kd="instr" aria-pressed="true">${esc(T("mu.instr_t"))}</button><button type="button" data-kd="vocal" aria-pressed="false">${esc(T("mu.vocal_t"))}</button></div></div>
          <div class="grid2"><label class="field">${esc(T("ad.start"))}<input id="adStart" type="number" min="0" max="1800" value="0" inputmode="numeric"></label>
            <label class="field">${esc(T("ad.author"))} <em>${esc(T("optional"))}</em><input id="adAuthor" maxlength="100"></label></div>
          <button type="button" class="btn" id="adGo">${esc(T("ad.save"))}</button></section>
        <h2 style="font-size:21px">${esc(T("ad.library", { n: tracks.length }))}</h2>
        ${tracks.length ? `<div class="trk-list">${tracks.map((t) => `<div class="admin-row"><button type="button" class="icon-btn" data-play="${t.id}" aria-label="${esc(T("play"))}">${icon("play", "s")}</button>
          <span><b>${esc(t.title)}</b><small>${esc(T("mut." + t.theme))} · ${esc(T(t.kind === "vocal" ? "mu.vocal_t" : "mu.instr_t"))}${t.start ? " · " + App.clock(t.start) : ""}</small></span>
          <button type="button" class="switch" role="switch" data-act="${t.id}" aria-checked="${t.active}" aria-label="${esc(T("ad.active"))}" style="width:auto"><span class="track"></span></button>
          <button type="button" class="icon-btn" data-del="${t.id}" aria-label="${esc(T("remove"))}">${icon("trash", "s")}</button></div>`).join("")}</div>`
          : `<div class="empty">${esc(T("ad.empty"))}</div>`}`;
      let theme = themes[0], kind = "instr", file = null, audio = null;
      App.onLeave(() => { if (audio) audio.pause(); });
      $$("[data-th]", box).forEach((b) => (b.onclick = () => { theme = b.dataset.th; $$("[data-th]", box).forEach((x) => x.setAttribute("aria-pressed", x === b)); }));
      $$("[data-kd]", box).forEach((b) => (b.onclick = () => { kind = b.dataset.kd; $$("[data-kd]", box).forEach((x) => x.setAttribute("aria-pressed", x === b)); }));
      $("#adIn").onchange = (e) => {
        file = e.target.files[0] || null;
        $("#adFile").textContent = file ? file.name : T("ad.file");
        if (file && !$("#adTitle").value) $("#adTitle").value = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").slice(0, 100);
      };
      $("#adGo").onclick = async (e) => {
        const title = $("#adTitle").value.trim();
        if (!file || !title) { notify("error"); toast(T("ad.need")); return; }
        const fd = new FormData();
        fd.append("file", file); fd.append("title", title); fd.append("theme", theme); fd.append("kind", kind);
        fd.append("subtitle", $("#adSub").value.trim()); fd.append("start", String(+$("#adStart").value || 0)); fd.append("author", $("#adAuthor").value.trim());
        App.busy(e.currentTarget, true, T("uploading"));
        try { await api("/api/admin/music", fd); S.music = null; notify("success"); toast(T("ad.saved")); App.render(); }
        catch (err) { App.busy(e.currentTarget, false); toast(err.message); }
      };
      $$("[data-play]", box).forEach((b) => (b.onclick = () => {
        const t = tracks.find((x) => x.id === +b.dataset.play);
        if (audio) { audio.pause(); audio = null; $$("[data-play]", box).forEach((x) => (x.innerHTML = icon("play", "s"))); if (b.dataset.on) { delete b.dataset.on; return; } }
        audio = new Audio(t.url); audio.currentTime = t.start || 0; audio.play().catch(() => {});
        b.dataset.on = "1"; b.innerHTML = icon("pause", "s");
      }));
      $$("[data-act]", box).forEach((b) => (b.onclick = async () => {
        const on = b.getAttribute("aria-checked") !== "true";
        try { await api(`/api/admin/music/${b.dataset.act}`, { active: on }, { method: "PATCH" }); b.setAttribute("aria-checked", on); S.music = null; }
        catch (err) { toast(err.message); }
      }));
      $$("[data-del]", box).forEach((b) => (b.onclick = async () => {
        if (!(await App.confirmBox(T("ad.del_q")))) return;
        try { await api(`/api/admin/music/${b.dataset.del}`, null, { method: "DELETE" }); S.music = null; App.render(); }
        catch (err) { toast(err.message); }
      }));
    }).catch((e) => { box.innerHTML = App.errBox(e); });
  };
})();
