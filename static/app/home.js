/* Asosiy: bosh sahifa, tanishuv, yaqinlar va ularga tavsiyalar */
(() => {
  "use strict";
  const { $, $$, esc, T, icon, S, api, haptic, notify, toast } = App;

  const kindLabel = (p) => (p.kind === "other" ? p.title || p.event : T("kind." + p.kind));
  const LANG_CODE = { uz: "UZ", cy: "ЎЗ", ru: "RU", en: "EN", kaa: "QA", tg: "ТҶ", kk: "ҚЗ" };
  const relTitle = (r) => App.tx("rel." + r.key, r.title);
  const relWhy = (r) => App.tx("relw." + r.key, r.why);
  Object.assign(App, { kindLabel, LANG_CODE, relTitle });

  /** Video bo'limlari (Videolar) va sayt bo'limlari (Saytlar) bir qatorda. */
  const OCCASIONS = [
    ["toy", "videos", "toy"], ["osh", "videos", "osh", true], ["gap", "videos", "gap", true], ["choy", "videos", "choy", true],
    ["tk", "videos", "tk"], ["sevgi", "sites", "sevgi"], ["farzand", "sites", "farzand"], ["uzr", "sites", "uzr"],
  ];
  const vthumb = (d) => `<button type="button" class="vthumb" data-design="${esc(d.id)}">
      <span class="img"><img src="${esc(d.thumb)}" alt="" loading="lazy"><span class="dur">${icon("play", "xs")}0:20</span></span>
      <b>${esc(App.tx("d." + d.id, d.name))}</b><small>${esc(T("sec." + d.section))}</small></button>`;
  App.vthumb = vthumb;

  function personCard(p) {
    const hot = p.days_left <= 7;
    return `<button type="button" class="person" data-person="${p.id}">
      <span class="av ${hot ? "hot" : ""}">${esc(App.initials(p.name).slice(0, 1))}</span>
      <b>${esc(p.name)}</b><small>${esc(kindLabel(p))}, ${esc(App.fmtDate(p.date))}</small>
      <span class="badge ${hot ? "solid" : "lilac"}">${esc(App.leftText(p.days_left))}</span></button>`;
  }

  // ---------------------------------------------------------------- bosh sahifa
  App.views.home = (p, el) => {
    App.chrome({ tabs: true, night: true });
    const me = S.me;
    const people = me.people || [];
    const soon = people.find((x) => x.days_left <= 30);
    const q = me.quota || {};
    const designs = [...S.vm.designs].sort((a, b) => (b.new ? 1 : 0) - (a.new ? 1 : 0)).slice(0, 8);
    const minSite = Math.min(...S.cm.tiers.map((t) => t.price));
    el.innerHTML = `
      <header class="hero">
        <div class="top"><span class="wordmark">Tayyorla</span>
          <button type="button" class="lang-pill" id="langBtn" aria-label="${esc(T("lang.change"))}">${icon("globe", "s")}${esc(LANG_CODE[App.lang] || "UZ")}</button></div>
        <div><p class="hi">${esc(me.name ? T("home.hi", { name: me.name }) : T("home.hi_anon"))}</p><h1>${esc(T("home.title"))}</h1></div>
        ${soon ? `<div class="soon"><span class="ikat"><b>${soon.days_left}</b></span>
          <div><p>${esc(soon.name)}: ${esc(kindLabel(soon).toLowerCase())}</p><p>${esc(App.fmtDate(soon.date))}, ${esc(App.leftText(soon.days_left).toLowerCase())}</p></div>
          <button type="button" class="btn sm" data-person="${soon.id}">${esc(T("home.prepare"))}</button></div>` : ""}
        <p class="counter" id="statLine" ${S.stats && S.stats.created >= 10 ? "" : "hidden"}><i></i><span id="statCount">${S.stats ? esc(T("home.counter", { n: App.fmtNum(S.stats.created) })) : ""}</span></p>
      </header>

      <section class="sec"><div class="sec-h"><h2>${esc(T("home.what"))}</h2></div>
        <div class="duo">
          <button type="button" class="big-card" data-go="videos"><span class="ic">${icon("play")}</span><b>${esc(T("home.video_title"))}</b>
            <small>${esc(T("home.video_sub"))}</small><span class="badge green">${esc(T("home.video_free", { n: q.free_per_day || 2 }))}</span></button>
          <button type="button" class="big-card" data-go="sites"><span class="ic pink">${icon("globe")}</span><b>${esc(T("home.site_title"))}</b>
            <small>${esc(T("home.site_sub"))}</small><span class="badge lilac">${esc(T("home.site_from", { sum: App.money(minSite) }))}</span></button>
        </div></section>

      <section class="sec"><div class="sec-h"><h2>${esc(T("home.which"))}</h2></div>
        <div class="occ">${OCCASIONS.map(([k, , , isNew]) => `<button type="button" data-occ="${k}">${isNew ? `<span class="badge new">${esc(T("new"))}</span>` : ""}${icon(k)}${esc(T("sec." + k))}</button>`).join("")}</div></section>

      <section class="sec" style="padding-left:0;padding-right:0"><div class="sec-h" style="padding:0 16px"><h2>${esc(T("home.days"))}</h2>
        ${people.length ? `<button type="button" id="allPeople">${esc(T("all"))}</button>` : ""}</div>
        <div class="strip">${people.slice(0, 10).map(personCard).join("")}
          <button type="button" class="person add" id="addPerson">${icon("plus")}${esc(T("add"))}</button></div>
        ${people.length ? "" : `<p class="hint" style="padding:8px 16px 0">${esc(T("home.days_hint"))}</p>`}</section>

      <section class="sec" style="padding-left:0;padding-right:0"><div class="sec-h" style="padding:0 16px"><h2>${esc(T("home.new_designs"))}</h2>
        <button type="button" data-go="videos">${esc(T("all"))}</button></div>
        <div class="strip">${designs.map(vthumb).join("")}</div></section>`;

    $("#langBtn").onclick = () => { haptic(); App.go("language"); };
    $$("[data-person]", el).forEach((b) => (b.onclick = () => { haptic(); App.go("rec", { person: +b.dataset.person }); }));
    $$("[data-go]", el).forEach((b) => (b.onclick = () => { haptic(); App.tab(b.dataset.go); }));
    $$("[data-occ]", el).forEach((b) => (b.onclick = () => {
      haptic();
      const [, tab, section] = OCCASIONS.find((o) => o[0] === b.dataset.occ);
      App.tab(tab, { section });
    }));
    $$("[data-design]", el).forEach((b) => (b.onclick = () => { haptic(); App.go("editor", { design: b.dataset.design }); }));
    $("#addPerson").onclick = () => { haptic(); personSheet(); };
    const all = $("#allPeople"); if (all) all.onclick = () => { haptic(); App.go("people"); };
  };

  // ---------------------------------------------------------------- yaqinlar ro'yxati
  App.views.people = (p, el) => {
    App.chrome({ night: false });
    const people = S.me.people || [];
    el.innerHTML = `
      <div class="bar light"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button>
        <div class="ttl"><b>${esc(T("people.title"))}</b><span>${esc(T("people.sub"))}</span></div></div>
      <div class="wrap stack fade">
        ${people.length ? `<ul class="glist">${people.map((x) => `<li><button type="button" data-person="${x.id}">
            <span class="ini" style="background:var(--night)">${esc(App.initials(x.name).slice(0, 1))}</span>
            <span class="who"><b>${esc(x.name)}</b><small>${esc(kindLabel(x))}, ${esc(App.fmtDate(x.date))}${x.turns ? " · " + esc(T(x.kind === "birthday" ? "age_n" : "years_n", { n: x.turns })) : ""}</small></span>
            <span class="badge ${x.days_left <= 7 ? "solid" : "lilac"}">${esc(App.leftText(x.days_left))}</span></button></li>`).join("")}</ul>`
          : `<div class="empty"><b>${esc(T("people.empty"))}</b>${esc(T("home.days_hint"))}</div>`}
        <button type="button" class="btn" id="addP">${icon("plus")}${esc(T("people.add"))}</button>
        <button type="button" class="btn ghost" id="reOnb">${esc(T("people.edit_rel"))}</button>
      </div>`;
    $("#bk").onclick = App.back;
    $$("[data-person]", el).forEach((b) => (b.onclick = () => { haptic(); App.go("rec", { person: +b.dataset.person }); }));
    $("#addP").onclick = () => { haptic(); personSheet(); };
    $("#reOnb").onclick = () => { haptic(); App.go("onb", { step: 0, again: true }); };
  };

  function personSheet() {
    const rels = S.cm.relations.filter((r) => r.key !== "mehmonlar");
    const st = { relation: (S.me.relations || [])[0] || "", kind: "birthday" };
    const s = App.sheet(`
      <div class="sh-head"><div><h1>${esc(T("person.title"))}</h1><p>${esc(T("person.sub"))}</p></div></div>
      <label class="field">${esc(T("person.name"))}<input id="pName" maxlength="100" placeholder="${esc(T("person.name_ph"))}"></label>
      <div class="field">${esc(T("person.who"))}<div class="chips">${rels.map((r) =>
        `<button type="button" class="chip" data-pr="${r.key}" aria-pressed="${r.key === st.relation}">${r.emoji} ${esc(relTitle(r))}</button>`).join("")}</div></div>
      <div class="field">${esc(T("person.kind"))}<div class="chips">
        <button type="button" class="chip" data-pk="birthday" aria-pressed="true">🎂 ${esc(T("kind.birthday"))}</button>
        <button type="button" class="chip" data-pk="anniversary" aria-pressed="false">💍 ${esc(T("kind.anniversary"))}</button></div></div>
      <label class="field">${esc(T("person.date"))}<input type="date" id="pDate"></label>
      <div id="pErr"></div>
      <button type="button" class="btn" id="pSave">${esc(T("save"))}</button>`, { label: T("person.title") });
    const pick = (attr, key) => $$(`[${attr}]`, s.el).forEach((b) => (b.onclick = () => {
      haptic(); st[key] = b.dataset[attr === "data-pr" ? "pr" : "pk"];
      $$(`[${attr}]`, s.el).forEach((x) => x.setAttribute("aria-pressed", x === b));
    }));
    pick("data-pr", "relation"); pick("data-pk", "kind");
    $("#pSave", s.el).onclick = async (e) => {
      const name = $("#pName", s.el).value.trim(), date = $("#pDate", s.el).value;
      if (!name || !date) { $("#pErr", s.el).innerHTML = App.errBox(T("person.need")); notify("error"); return; }
      const [y, m, d] = date.split("-").map(Number);
      App.busy(e.currentTarget, true);
      try {
        await api("/api/people", { name, relation: st.relation, kind: st.kind, day: d, month: m, year: y });
        await App.refreshMe();
        notify("success"); s.close(); App.render();
      } catch (err) { App.busy(e.currentTarget, false); $("#pErr", s.el).innerHTML = App.errBox(err); }
    };
  }
  App.personSheet = personSheet;

  // ---------------------------------------------------------------- yaqin kishi uchun tavsiyalar
  App.views.rec = (p, el) => {
    App.chrome({ night: true });
    const person = p.person ? (S.me.people || []).find((x) => x.id === p.person) : null;
    const rel = S.cm.relations.find((r) => r.key === (p.rel || (person && person.relation)));
    let picks = rel ? rel.picks : S.cm.templates.filter((t) => t.section === (p.section || "tugilgan-kun")).map((t) => t.id);
    if (person && person.kind === "anniversary") picks = ["sv-hikoya", "sv-konvert", "sv-maktub", "tk-polaroid", "sv-yulduz"];
    const list = picks.map((id) => S.cm.templates.find((t) => t.id === id)).filter(Boolean);
    const title = person ? T("rec.for", { name: person.name }) : rel ? relTitle(rel) : T("rec.for", { name: (p.prefill || {}).kimga || "" });
    const sub = person ? `${kindLabel(person)}, ${App.fmtDate(person.date)} — ${App.leftText(person.days_left).toLowerCase()}` : rel ? relWhy(rel) : T("rec.sub");
    const party = !person || person.kind === "birthday";
    el.innerHTML = `
      <div class="bar"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button><div class="ttl"></div></div>
      <div class="rechead"><span class="em">${rel ? rel.emoji : person ? "🎁" : "🎁"}</span><h1>${esc(title)}</h1><p>${esc(sub)}</p></div>
      <section class="sec" style="padding-left:0;padding-right:0"><div class="sec-h" style="padding:0 16px"><h2>${esc(T("rec.sites"))}</h2></div>
        <div class="carousel fade">${list.map((t) => App.tcard(t)).join("")}</div>
        <p class="hint" style="text-align:center;padding:0 16px">${esc(T("rec.tap"))}</p></section>
      ${party ? `<section class="sec"><button type="button" class="banner" id="toVideo">${icon("video")}<span><b>${esc(T("rec.video_t"))}</b>${esc(T("rec.video_s"))}</span>${icon("chev")}</button></section>` : ""}
      ${person ? `<section class="sec"><button type="button" class="btn ghost" id="rmP">${icon("trash", "s")}${esc(T("rec.remove"))}</button></section>` : ""}`;
    $("#bk").onclick = App.back;
    $$("[data-tpl]", el).forEach((b) => (b.onclick = () => {
      haptic();
      const pre = {};
      if (person) { pre.kimga = person.name; pre.sana = person.date; if (person.born) pre.tugilgan_sana = person.born; }
      else if (rel && rel.kimga) pre.kimga = rel.kimga;
      else Object.assign(pre, p.prefill || {});
      if (S.me.name) pre.kimdan = S.me.name;
      App.startOrder(b.dataset.tpl, pre, rel ? rel.tone : "");
    }));
    const tv = $("#toVideo");
    if (tv) tv.onclick = () => {
      haptic();
      const data = person ? { ism: person.name, sana: person.date, ...(person.turns ? { yosh: person.turns } : {}) } : {};
      App.go("editor", { design: (S.vm.designs.find((d) => d.section === "tk") || S.vm.designs[0]).id, prefill: data, fresh: true });
    };
    const rm = $("#rmP");
    if (rm) rm.onclick = async () => {
      if (!(await App.confirmBox(T("rec.remove_q", { name: person.name })))) return;
      try { await api(`/api/people/${person.id}`, null, { method: "DELETE" }); await App.refreshMe(); App.back(); }
      catch (e) { toast(e.message); }
    };
  };

  // ---------------------------------------------------------------- tanishuv (birinchi ochilish)
  const ONB_PEOPLE = ["ona", "ota", "jufti", "sevgili", "farzand", "qarindosh", "dost", "ustoz", "hamkasb"];
  let onb = null;
  App.views.onb = (p, el) => {
    App.chrome({ cta: true });
    const i = p.step || 0;
    if (!onb) onb = { relations: new Set(S.me.relations || []), people: {} };
    const rels = S.cm.relations;
    const dots = `<div class="dots" style="max-width:120px">${[0, 1, 2].map((n) => `<i class="${n <= i ? "on" : ""}"></i>`).join("")}</div>`;
    const name = S.me.name || "";
    let body = "", cta = T("continue"), next;
    if (i === 0) {
      body = `<h1>${esc(name ? T("onb.q1_name", { name }) : T("onb.q1"))}</h1><p class="lead">${esc(T("onb.q1_sub"))}</p>
        <div class="rels">${rels.map((r) => `<button type="button" class="rel" data-r="${r.key}" aria-pressed="${onb.relations.has(r.key)}"><span class="em">${r.emoji}</span><b>${esc(relTitle(r))}</b></button>`).join("")}</div>`;
      next = () => App.replace("onb", { step: 1, again: p.again });
    } else if (i === 1) {
      const keys = [...onb.relations].filter((k) => ONB_PEOPLE.includes(k)).slice(0, 6);
      if (!keys.length) return App.replace("onb", { step: 2, again: p.again });
      body = `<h1>${esc(T("onb.q2"))}</h1><p class="lead">${esc(T("onb.q2_sub"))}</p>
        ${keys.map((k) => { const r = rels.find((x) => x.key === k), v = onb.people[k] || {}; return `
          <div class="prow"><b><span>${r.emoji}</span>${esc(relTitle(r))}</b>
            <div class="two"><input placeholder="${esc(T("person.name"))}" maxlength="100" data-pn="${k}" value="${esc(v.name || "")}">
            <input type="date" data-pd="${k}" value="${esc(v.date || "")}" aria-label="${esc(relTitle(r))}"></div></div>`; }).join("")}
        <p class="hint">${esc(T("onb.q2_hint"))}</p>`;
      next = () => App.replace("onb", { step: 2, again: p.again });
    } else {
      const ready = Object.entries(onb.people).filter(([k, v]) => onb.relations.has(k) && v.name && v.name.trim() && v.date);
      body = `<h1>${esc(name ? T("onb.done_name", { name }) : T("onb.done"))}</h1>
        <p class="lead">${esc(ready.length ? T("onb.remember") : T("onb.later"))}</p>
        ${ready.length ? `<ul class="summary">${ready.map(([k, v]) => `<li><span>${rels.find((r) => r.key === k).emoji}</span><div><b>${esc(v.name)}</b><br><small class="hint">${esc(App.fmtDate(v.date))}, ${esc(T("kind.birthday").toLowerCase())}</small></div></li>`).join("")}</ul>` : ""}
        <div class="card" style="background:var(--night);color:var(--on-night);border:0"><h2 style="color:inherit">${esc(T("onb.how"))}</h2>
          <p style="color:var(--night-muted);font-size:14px">${esc(T("onb.how_text"))}</p></div>`;
      cta = T("onb.start");
      next = async (btn) => {
        App.busy(btn, true);
        try {
          await api("/api/me/onboard", {
            relations: [...onb.relations],
            people: ready.map(([k, v]) => { const [y, m, d] = v.date.split("-").map(Number); return { name: v.name.trim(), relation: k, kind: "birthday", day: d, month: m, year: y }; }),
          });
          await App.refreshMe();
          onb = null; notify("success"); App.tab("home");
        } catch (e) { App.busy(btn, false); toast(e.message); }
      };
    }
    el.innerHTML = `<div class="onb fade">${dots}${body}</div>
      <div class="cta"><div class="two">${i > 0 || p.again ? `<button type="button" class="btn ghost back" id="obBack" aria-label="${esc(T("back"))}">${icon("back")}</button>` : ""}
        <button type="button" class="btn" id="obNext">${esc(cta)}</button></div></div>`;
    const nextBtn = $("#obNext");
    if (i === 0) {
      nextBtn.disabled = !onb.relations.size;
      $$("[data-r]", el).forEach((b) => (b.onclick = () => {
        haptic();
        const on = b.getAttribute("aria-pressed") !== "true";
        b.setAttribute("aria-pressed", on);
        on ? onb.relations.add(b.dataset.r) : onb.relations.delete(b.dataset.r);
        nextBtn.disabled = !onb.relations.size;
      }));
    }
    $$("[data-pn]", el).forEach((x) => (x.oninput = () => { (onb.people[x.dataset.pn] ||= {}).name = x.value; }));
    $$("[data-pd]", el).forEach((x) => (x.oninput = () => { (onb.people[x.dataset.pd] ||= {}).date = x.value; }));
    nextBtn.onclick = () => { haptic(); next(nextBtn); };
    const bk = $("#obBack");
    if (bk) bk.onclick = () => (i > 0 ? App.replace("onb", { step: i - 1, again: p.again }) : App.back());
  };
})();
