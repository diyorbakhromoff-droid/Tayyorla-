/* Videolar: galereya, jonli muharrir, navbat, musiqa va to'lov oynasi */
(() => {
  "use strict";
  const { $, $$, esc, T, icon, S, api, haptic, notify, toast, store, money } = App;
  // to'y videolari «Taklifnomalar» bo'limida
  const SECTIONS = ["osh", "gap", "choy", "tk"];
  const DKEY = "tyr-vdraft";
  const design = (id) => S.vm.designs.find((d) => d.id === id);
  const dname = (d) => App.tx("d." + d.id, d.name);
  const thumbOf = (id) => `/katalog/video/thumb/${id}.jpg`;

  /** Video dizaynlar to'ri (Videolar va Taklifnomalar bo'limlari); bosilganda muharrir ochiladi. */
  App.videoGrid = (list) => `<div class="dgrid">${list.map((d) => `
    <button type="button" class="dcard" data-design="${esc(d.id)}">
      <span class="img"><img src="${esc(d.thumb)}" alt="" loading="lazy">${d.new ? `<span class="badge gold tag">${esc(T("new"))}</span>` : ""}</span>
      <span class="meta"><b>${esc(dname(d))}</b><span>${icon("play", "xs")}0:20</span></span>
      <small>${esc(T("sec." + d.section))}</small></button>`).join("")}</div>`;

  // ---------------------------------------------------------------- Videolar bo'limi
  App.views.videos = (p, el) => {
    if (p.section === "toy" && !p.mine) { App.tab("events", { kind: "video" }); return; }
    App.chrome({ tabs: true });
    const q = S.me.quota || {};
    const tab = p.mine ? "mine" : "designs";
    const sec = SECTIONS.includes(p.section) ? p.section : "";
    const free = q.free_left || 0;
    el.innerHTML = `
      <header class="page-head"><div class="row"><h1>${esc(T("videos.title"))}</h1>
        <span class="badge ${free ? "green" : "gold"}">${icon("gift", "xs")}${esc(free ? T("videos.free_today", { n: free }) : T("videos.free_none"))}</span></div>
        <p>${esc(T("videos.sub"))}</p>
        <div class="seg" role="tablist" style="margin-top:8px">
          <button type="button" role="tab" data-t="designs" aria-selected="${tab === "designs"}">${esc(T("videos.designs"))}</button>
          <button type="button" role="tab" data-t="mine" aria-selected="${tab === "mine"}">${esc(T("videos.mine", { n: S.me.videos || 0 }))}</button></div>
      </header>
      <div id="vbody" class="fade"></div>`;
    $$("[data-t]", el).forEach((b) => (b.onclick = () => { haptic(); p.mine = b.dataset.t === "mine"; App.render(); }));
    const body = $("#vbody");
    if (tab === "designs") {
      const list = S.vm.designs.filter((d) => (sec ? d.section === sec : SECTIONS.includes(d.section)));
      body.innerHTML = `
        <div class="wrap" style="padding-top:14px"><div class="chips scroll">
          <button type="button" class="chip" data-s="" aria-pressed="${!sec}">${esc(T("all"))}</button>
          ${SECTIONS.map((k) => `<button type="button" class="chip" data-s="${k}" aria-pressed="${sec === k}">${esc(T("sec." + k))}</button>`).join("")}</div></div>
        <div class="wrap" style="padding-top:14px"><ol class="steps3">
          <li><span>1</span>${esc(T("videos.step1"))}</li><li><span>2</span>${esc(T("videos.step2"))}</li><li><span>3</span>${esc(T("videos.step3"))}</li></ol></div>
        <div class="wrap" style="padding-top:16px">${App.videoGrid(list)}</div>`;
      $$("[data-s]", body).forEach((b) => (b.onclick = () => { haptic(); p.section = b.dataset.s; App.render(); }));
      $$("[data-design]", body).forEach((b) => (b.onclick = () => { haptic(); App.go("editor", { design: b.dataset.design }); }));
      return;
    }
    body.innerHTML = `<div class="wrap" style="padding-top:16px"><div class="empty"><span class="spin"></span></div></div>`;
    api("/api/videos").then(({ videos }) => {
      if (!body.isConnected) return;
      if (!videos.length) {
        body.innerHTML = `<div class="wrap" style="padding-top:16px"><div class="empty"><b>${esc(T("videos.none"))}</b>${esc(T("videos.none_sub"))}</div>
          <button type="button" class="btn" id="toDesigns">${esc(T("videos.pick"))}</button></div>`;
        $("#toDesigns").onclick = () => { p.mine = false; App.render(); };
        return;
      }
      body.innerHTML = `<div class="wrap stack" style="padding-top:16px">${videos.map(videoRow).join("")}</div>`;
      bindVideoRows(body, videos);
    }).catch((e) => { body.innerHTML = `<div class="wrap" style="padding-top:16px">${App.errBox(e)}</div>`; });
  };

  const STATUS = {
    queued: ["lilac", "st.queued"], rendering: ["lilac", "st.rendering"], awaiting_payment: ["gold", "st.awaiting"],
    failed: ["rose", "st.failed"], refunded: ["rose", "st.failed"],
  };
  function videoRow(v) {
    let badge;
    if (v.status === "done") badge = v.delivered ? ["green", "st.sent"] : ["pink", "st.ready"];
    else badge = STATUS[v.status] || ["lilac", "st.queued"];
    const title = v.names && v.names !== v.title ? v.names : v.title || "";
    const meta = [v.names && v.names !== v.title ? v.title : "", v.date].filter(Boolean).join(", ");
    const acts = [];
    if (v.status === "done" && v.delivered) {
      acts.push(`<button type="button" class="act" data-share="${v.id}">${icon("share", "s")}${esc(T("share"))}</button>`);
      acts.push(`<button type="button" class="act" data-resend="${v.id}">${icon("send", "s")}${esc(T("videos.resend"))}</button>`);
    } else if (["queued", "rendering", "awaiting_payment"].includes(v.status) || (v.status === "done" && !v.delivered)) {
      acts.push(`<button type="button" class="act" data-queue="${v.id}">${icon("clock", "s")}${esc(T("videos.status"))}</button>`);
    }
    if (v.site) {
      acts.push(`<button type="button" class="act" data-event="${esc(v.site)}">${icon("users", "s")}${esc(T("videos.guests"))}</button>`);
      if (v.section === "toy") acts.push(`<button type="button" class="act pink" data-tosite="${esc(v.site)}">${icon("globe", "s")}${esc(T("videos.to_site"))}</button>`);
    }
    return `<div class="vrow"><span class="img"><img src="${esc(thumbOf(v.design))}" alt="" loading="lazy"></span>
      <div><b>${esc(title)}</b><small>${esc(meta)}</small><span class="badge ${badge[0]}">${esc(T(badge[1]))}</span>
        ${acts.length ? `<div class="acts">${acts.join("")}</div>` : ""}</div></div>`;
  }
  function bindVideoRows(box) {
    $$("[data-share]", box).forEach((b) => (b.onclick = () => shareVideo(+b.dataset.share, b)));
    $$("[data-resend]", box).forEach((b) => (b.onclick = async () => {
      App.busy(b, true);
      try { await api(`/api/video/${b.dataset.resend}/resend`, {}); notify("success"); toast(T("videos.resent")); }
      catch (e) { toast(e.message); }
      App.busy(b, false);
    }));
    $$("[data-queue]", box).forEach((b) => (b.onclick = () => { haptic(); App.go("queue", { job: +b.dataset.queue }); }));
    $$("[data-event]", box).forEach((b) => (b.onclick = () => { haptic(); App.go("event", { slug: b.dataset.event }); }));
    $$("[data-tosite]", box).forEach((b) => (b.onclick = () => { haptic(); App.tab("sites", { fromEvent: b.dataset.tosite }); }));
  }
  /** Telegram'ning «ulashish» oynasi: tayyor video xabari istalgan chatga ketadi. */
  async function shareVideo(id, btn) {
    App.busy(btn, true);
    try {
      const { id: prepared } = await api(`/api/video/${id}/share`, {});
      try { App.tg.shareMessage(prepared, () => {}); }
      catch { App.tg.switchInlineQuery("v" + id, ["users", "groups", "channels"]); }
    } catch (e) { toast(e.message); }
    App.busy(btn, false);
  }
  App.shareVideo = shareVideo;

  // ---------------------------------------------------------------- qoralama
  const GROUPS = {
    toy: { event: "marosim", custom: "marosim_nomi", names: ["kuyov", "kelin"] },
    osh: { event: "nomi", custom: "nomi_matn", names: ["sababi"] },
    gap: { event: "nomi", custom: "nomi_matn", names: ["navbat", "kassa"] },
    choy: { event: null, names: ["guruh", "navbat", "kassa"] },
    tk: { event: "sarlavha", names: ["ism", "yosh"] },
  };
  const PREVIEW_DEMO = ["kuyov", "kelin", "ism", "yosh", "guruh", "sana", "vaqt", "joy"];
  const SCENE_OF = { kimga: 0, kuyov: 1, kelin: 1, ism: 1, yosh: 1, guruh: 1, navbat: 1, kassa: 1, sababi: 1, sana: 1, vaqt: 1, sana2: 1,
    joy: 2, manzil: 2, xarita: 2, matn: 2, imzo: 2, karta: 3, karta_egasi: 3 };

  function newDraft(d) {
    const g = GROUPS[d.section];
    const data = {};
    if (g.event) data[g.event] = S.vm.events[d.section][0];
    return { design: d.id, palette: 0, lang: store.get("tyr-card-lang") || "auto", data, music: { mode: "lib", track: null }, site: null };
  }
  function musicFromEvent(m) {
    if (!m) return { mode: "none" };
    if (m.track) return { mode: "lib", track: m.track, start: m.start || 0 };
    return { mode: "own", url: m.file, start: m.start || 0, name: (m.file || "").split("/").pop() };
  }
  const Draft = { get: () => store.json(DKEY), set: (d) => store.put(DKEY, d) };
  App.Draft = Draft;

  // ---------------------------------------------------------------- muharrir
  App.views.editor = (p, el) => {
    App.chrome({ night: true, cta: true });
    if (p.event && !p.loaded) {
      el.innerHTML = `<div class="bar"><button type="button" class="icon-btn" id="bk">${icon("back")}</button></div><div class="empty"><span class="spin"></span></div>`;
      $("#bk").onclick = App.back;
      api(`/api/events/${encodeURIComponent(p.event)}`).then((ev) => {
        if (!ev.edit || !design(ev.edit.design)) throw new Error(T("err.generic"));
        Draft.set({ design: ev.edit.design, palette: ev.edit.palette || 0, lang: ev.edit.lang || "auto", data: ev.edit.data || {},
          music: musicFromEvent(ev.edit.music), site: ev.slug });
        p.loaded = true; p.design = ev.edit.design;
        if (App.current().p === p) App.render();
      }).catch((e) => { el.innerHTML = `<div class="wrap" style="padding-top:20px">${App.errBox(e)}</div>`; });
      return;
    }
    const dz = design(p.design) || S.vm.designs[0];
    let d = Draft.get();
    const same = d && d.design && design(d.design) && design(d.design).section === dz.section;
    if (p.loaded && d) { /* tadbirdan yuklangan */ }
    else if (!d || p.fresh || !same || (d.site && !p.keep)) d = newDraft(dz);
    d.design = dz.id;
    if (p.prefill) { Object.assign(d.data, p.prefill); delete p.prefill; }
    p.keep = true; p.fresh = false;
    Draft.set(d);
    const section = dz.section;
    const spec = Object.fromEntries(S.vm.fields[section].map((f) => [f.key, f]));
    const demo = S.vm.demo[section] || {};
    const g = GROUPS[section];
    const q = S.me.quota || {};
    const pal = dz.palettes[d.palette] ? d.palette : 0;
    d.palette = pal;

    // --- maydonlar
    const ph = (k) => (demo[k] != null && typeof demo[k] !== "boolean" ? String(k === "kassa" ? App.fmtNum(demo[k]) : demo[k]) : "");
    const val = (k) => (d.data[k] == null ? "" : d.data[k]);
    const opt = (k) => (spec[k] && !spec[k].required ? ` <em>${esc(T("optional"))}</em>` : "");
    function input(k) {
      const f = spec[k];
      if (!f) return "";
      const lab = `${esc(T("f." + k))}${opt(k)}`;
      const sc = SCENE_OF[k] ?? "";
      const common = `data-k="${k}" data-scene="${sc}" id="f_${k}"`;
      switch (f.kind) {
        case "date": return `<label class="field">${lab}<input type="date" ${common} value="${esc(val(k))}"></label>`;
        case "time": return `<label class="field">${lab}<input type="time" ${common} value="${esc(val(k))}"></label>`;
        case "int": return `<label class="field">${lab}<input type="number" inputmode="numeric" min="1" max="150" ${common} value="${esc(val(k))}" placeholder="${esc(ph(k))}"></label>`;
        case "money": return `<label class="field">${lab}<input inputmode="numeric" data-money="1" ${common} value="${esc(val(k) ? App.fmtNum(val(k)) : "")}" placeholder="${esc(ph(k))}"></label>`;
        case "card": return `<label class="field">${lab}<input inputmode="numeric" data-card="1" maxlength="19" ${common} value="${esc(fmtCard(val(k)))}" placeholder="8600 0000 0000 0000"></label>`;
        default: return `<label class="field">${lab}<input ${common} maxlength="${f.limit || 100}" value="${esc(val(k))}" placeholder="${esc(ph(k))}"></label>`;
      }
    }
    const fmtCard = (v) => String(v || "").replace(/\D/g, "").slice(0, 16).replace(/(\d{4})(?=\d)/g, "$1 ");
    const eventCard = () => {
      if (!g.event) return "";
      const names = S.vm.event_names[section] || {};
      const cur = d.data[g.event] || S.vm.events[section][0];
      return `<section class="card"><h2>${esc(T("ed.event"))}</h2><div class="chips">
        ${S.vm.events[section].map((k) => `<button type="button" class="chip" data-ev="${k}" aria-pressed="${cur === k}">${esc(names[k] || k)}</button>`).join("")}
        ${g.custom ? `<button type="button" class="chip dashed" data-ev="custom" aria-pressed="${cur === "custom"}">${cur === "custom" ? esc(T("ed.own_name")) : "+ " + esc(T("ed.own_name"))}</button>` : ""}</div>
        ${g.custom && cur === "custom" ? `<div style="height:12px"></div>${input(g.custom)}` : ""}</section>`;
    };
    const musicCard = () => {
      const m = d.music || { mode: "none" };
      let row = "";
      if (m.mode === "lib") {
        const tr = S.music && S.music.tracks.find((x) => x.id === m.track);
        row = `<button type="button" class="track-row" id="toMusic"><span class="disc">${icon("music", "s")}</span>
          <span><b>${esc(tr ? tr.title : T("ed.music_pick"))}</b><small>${esc(tr ? `${T(tr.kind === "vocal" ? "mu.vocal" : "mu.instr")}${tr.subtitle ? ", " + tr.subtitle : ""}` : T("ed.music_lib"))}</small></span>
          <span class="link">${esc(tr ? T("change") : T("choose"))}</span></button>`;
      } else if (m.mode === "own") {
        row = `<button type="button" class="track-row" id="toMusic"><span class="disc">${icon("upload", "s")}</span>
          <span><b>${esc(m.url ? m.name || T("mu.own_file") : T("mu.upload"))}</b><small>${esc(m.url ? T("mu.segment", { from: clock(m.start || 0), to: clock((m.start || 0) + 20) }) : T("mu.upload_sub"))}</small></span>
          <span class="link">${esc(m.url ? T("change") : T("choose"))}</span></button>`;
      } else row = `<p class="hint" style="margin-top:10px">${esc(T("mu.none_text"))}</p>`;
      return `<section class="card"><h2>${esc(T("ed.music"))}</h2>
        <div class="seg">${[["lib", "mu.lib"], ["own", "mu.own"], ["none", "mu.none"]].map(([k, l]) => `<button type="button" data-mu="${k}" aria-pressed="${m.mode === k}">${esc(T(l))}</button>`).join("")}</div>${row}</section>`;
    };
    const langs = [{ key: "auto", name: T("ed.lang_auto") }, ...S.vm.langs];
    const formHtml = () => {
      const ikki = !!d.data.ikki_kunlik;
      return `${eventCard()}
        <section class="card"><h2>${esc(T("ed.names." + section))}</h2>${g.names.map(input).join("")}</section>
        <section class="card"><h2>${esc(T("ed.when"))}</h2><div class="grid2">${input("sana")}${input("vaqt")}</div>
          ${spec.ikki_kunlik ? `<div style="height:12px"></div>${App.switchHtml("swIkki", T("ed.two_days"), T("ed.two_days_sub"), ikki)}${ikki ? `<div style="height:12px"></div>${input("sana2")}` : ""}` : ""}</section>
        <section class="card"><h2>${esc(T("ed.place"))}</h2>${input("joy")}${input("manzil")}
          <div class="with-btn" style="margin-top:12px">${input("xarita").replace('class="field"', 'class="field" style="margin:0"')}
            <button type="button" class="btn ghost sm" id="locBtn">${icon("pin", "s")}${esc(T("ed.my_loc"))}</button></div>
          <p class="hint" style="margin-top:8px">${esc(T("ed.map_hint"))}</p></section>
        <section class="card"><div class="card-h"><h2>${esc(T("ed.text"))}</h2><span class="hint" id="mLen">${String(val("matn")).length}/200</span></div>
          <textarea data-k="matn" data-scene="2" id="f_matn" maxlength="200" rows="3" placeholder="${esc(ph("matn"))}">${esc(val("matn"))}</textarea>
          <button type="button" class="btn night sm" id="aiBtn" style="margin-top:10px">${icon("sparkle", "s")}${esc(val("matn") ? T("ed.ai_again") : T("ed.ai"))}</button>
          <div style="height:12px"></div>${input("imzo")}</section>
        <section class="card"><h2>${esc(T("ed.to_whom"))}</h2>
          <input data-k="kimga" data-scene="0" id="f_kimga" maxlength="60" value="${esc(val("kimga"))}" placeholder="${esc(T("ga.sample"))}" aria-label="${esc(T("f.kimga"))}">
          <button type="button" class="link" id="toGuests" style="margin-top:8px">${esc(T("ed.to_whom_link"))}</button></section>
        <section class="card">${App.switchHtml("swToyona", T(section === "gap" || section === "choy" ? "ed.kassa_card" : "ed.toyona"), T("ed.toyona_sub"), !!d.data.toyona)}
          ${d.data.toyona ? `<div style="height:12px"></div>${input("karta")}${input("karta_egasi")}` : ""}</section>
        <section class="card"><div class="photo-row"><span class="ph">${d.data.rasm ? `<img src="${esc(d.data.rasm)}" alt="">` : icon("photo")}</span>
          <span><b>${esc(T("ed.photo"))}</b>${esc(T("ed.photo_sub"))}</span>
          ${d.data.rasm ? `<button type="button" class="btn ghost xs" id="rmPhoto">${esc(T("remove"))}</button>`
            : `<span class="btn ghost xs upload">${esc(T("choose"))}<input type="file" accept="image/*" id="photoIn"></span>`}</div></section>
        ${musicCard()}
        <section class="card"><h2>${esc(T("ed.lang"))}</h2><div class="chips">
          ${langs.map((l) => `<button type="button" class="chip" data-lang="${l.key}" aria-pressed="${d.lang === l.key}">${esc(l.name)}</button>`).join("")}</div>
          <p class="hint" style="margin-top:10px">${esc(T("ed.lang_hint"))}</p>
          ${d.lang !== "auto" ? `<button type="button" class="btn ghost sm" id="trBtn" style="margin-top:10px">${icon("lang", "s")}${esc(T("ed.translate"))}</button>` : ""}</section>
        ${d.site ? `<p class="hint" style="text-align:center">${esc(T("ed.editing_event"))}</p>` : ""}`;
    };

    // jonli ko'rinish bir marta quriladi; forma o'zgarganda faqat forma qayta chiziladi (video qayta yuklanmaydi)
    el.innerHTML = `
      <div class="bar"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button>
        <div class="ttl"><b>${esc(dname(dz))}</b><span>${esc(T("ed.sub", { sec: T("sec." + section) }))}</span></div>
        <span class="saved" id="saved">${icon("check", "xs")}${esc(T("saved"))}</span></div>
      <section class="stage" aria-label="${esc(T("ed.preview"))}">
        <div class="screen"><iframe id="pv" title="${esc(T("ed.preview"))}" src="/video/${esc(dz.id)}?palette=${pal}&amp;lang=uz"></iframe><div class="loading" id="pvLoad"><span class="spin"></span></div></div>
        <div class="player"><button type="button" class="play" id="pp" aria-label="${esc(T("pause"))}">${icon("pause")}</button>
          <div class="prog">${[0, 1, 2, 3].map(() => "<span><i></i></span>").join("")}</div><span class="time">0:00</span></div>
        <div class="scenes" role="tablist">${["ed.s1", "ed.s2", "ed.s3", "ed.s4"].map((k, i) => `<button type="button" role="tab" data-scene-btn="${i}" aria-selected="${i === 0}">${esc(T(k))}</button>`).join("")}</div>
        <div class="pals"><span>${esc(T("ed.color"))}</span>${dz.palettes.map((x, i) => `<button type="button" data-pal="${i}" aria-pressed="${i === pal}" aria-label="${esc(App.tx("pal." + x.name, x.name))}"
          style="background:conic-gradient(${x.swatch[1]} 0 50%, ${x.swatch[2]} 0 75%, ${x.swatch[0]} 0)"></button>`).join("")}<span class="pname" id="palName">${esc(App.tx("pal." + dz.palettes[pal].name, dz.palettes[pal].name))}</span></div>
      </section>
      <div class="form" id="form"></div>
      <div class="cta"><button type="button" class="btn" id="mkBtn">${icon("play", "s")}${esc(T("ed.create"))}</button><small id="qLine"></small></div>`;

    // --- saqlash va jonli ko'rinish
    const savedEl = $("#saved");
    const persist = App.debounce(() => { Draft.set(d); savedEl.style.opacity = 1; }, 300);
    const changed = () => { savedEl.style.opacity = .35; persist(); refresh(); };
    const iframe = $("#pv");
    let seq = 0, ready = false, playing = true;
    const previewData = () => {
      const out = { ...d.data };
      PREVIEW_DEMO.forEach((k) => { if ((out[k] == null || out[k] === "") && demo[k] != null) out[k] = demo[k]; });
      return out;
    };
    const willBeFree = () => (S.me.quota.free_left || 0) > 0 || (S.me.quota.bonus || 0) > 0;
    const post = (m) => { try { iframe.contentWindow.postMessage(m, "*"); } catch { /* yuklanmoqda */ } };
    const refresh = App.debounce(async () => {
      const my = ++seq;
      try {
        const pl = await api("/api/video/payload", { design: dz.id, data: previewData(), lang: d.lang, palette: d.palette, guest: d.data.kimga || null, ui: App.lang, probe: d.data });
        if (my !== seq || !ready) return;
        pl.f.free = willBeFree();
        post({ type: "tv:payload", payload: pl });
        const ld = $("#pvLoad"); if (ld) setTimeout(() => ld.remove(), 120);
      } catch { /* ko'rinish eskisicha qoladi */ }
    }, 350);
    const segs = $$(".prog i", el), sceneBtns = $$("[data-scene-btn]", el), ppBtn = $("#pp"), timeEl = $(".player .time", el);
    let pendingSeek = null;
    function onMsg(e) {
      if (e.source !== iframe.contentWindow || !e.data) return;
      const m = e.data;
      if (m.type === "tv:ready") {
        ready = true; post({ type: "tv:loop", on: true }); refresh();
        if (pendingSeek !== null) { seekScene(pendingSeek); pendingSeek = null; }
      }
      if (m.type === "tv:time") {
        const t = m.t || 0, sc = Math.min(3, Math.floor(t / 5000));
        segs.forEach((s, i) => (s.style.transform = `scaleX(${i < sc ? 1 : i > sc ? 0 : (t % 5000) / 5000})`));
        sceneBtns.forEach((b, i) => b.setAttribute("aria-selected", i === sc));
        timeEl.textContent = clock(Math.round(t / 1000));
        if (m.playing !== playing) { playing = m.playing; ppBtn.innerHTML = icon(playing ? "pause" : "play"); ppBtn.setAttribute("aria-label", T(playing ? "pause" : "play")); }
      }
    }
    window.addEventListener("message", onMsg);
    App.onLeave(() => window.removeEventListener("message", onMsg));
    function seekScene(i) {
      if (!ready) { pendingSeek = i; return; }
      post({ type: "tv:seek", ms: i * 5000 + 1200 }); post({ type: "tv:play" });
    }
    ppBtn.onclick = () => { haptic(); post({ type: playing ? "tv:pause" : "tv:play" }); };
    sceneBtns.forEach((b) => (b.onclick = () => { haptic(); seekScene(+b.dataset.sceneBtn); }));
    $$("[data-pal]", el).forEach((b) => (b.onclick = () => {
      haptic(); d.palette = +b.dataset.pal;
      $$("[data-pal]", el).forEach((x) => x.setAttribute("aria-pressed", x === b));
      const pn = dz.palettes[d.palette].name; $("#palName").textContent = App.tx("pal." + pn, pn);
      changed();
    }));
    $("#bk").onclick = App.back;

    // --- forma
    function drawForm() {
      const form = $("#form");
      if (!form) return;
      form.innerHTML = formHtml();
      bindForm(form);
    }
    const redraw = () => { Draft.set(d); drawForm(); refresh(); };
    function bindForm(form) {
      $$("[data-k]", form).forEach((inp) => {
        inp.addEventListener("focus", () => { if (inp.dataset.scene !== "") seekScene(+inp.dataset.scene); });
        inp.addEventListener("input", () => {
          const k = inp.dataset.k;
          inp.classList.remove("bad");
          if (inp.dataset.card) { const v = fmtCard(inp.value); if (v !== inp.value) inp.value = v; d.data[k] = v.replace(/\s/g, ""); }
          else if (inp.dataset.money) { const n = inp.value.replace(/\D/g, ""); inp.value = n ? App.fmtNum(n) : ""; d.data[k] = n ? +n : null; }
          else if (spec[k] && spec[k].kind === "int") d.data[k] = inp.value ? +inp.value : null;
          else d.data[k] = inp.value;
          if (k === "matn") { $("#mLen").textContent = `${inp.value.length}/200`; }
          changed();
        });
      });
      $$("[data-ev]", form).forEach((b) => (b.onclick = () => { haptic(); d.data[g.event] = b.dataset.ev; redraw(); seekScene(1); }));
      App.bindSwitch($("#swIkki", form), (on) => { d.data.ikki_kunlik = on; if (!on) delete d.data.sana2; redraw(); seekScene(1); });
      App.bindSwitch($("#swToyona", form), (on) => { d.data.toyona = on; redraw(); seekScene(3); });
      $("#toGuests", form).onclick = () => { haptic(); App.tab("events"); };
      $("#locBtn", form).onclick = async (e) => {
        const btn = e.currentTarget;
        App.busy(btn, true);
        try {
          const c = await locate();
          d.data.xarita = `${(+c.latitude).toFixed(5)}, ${(+c.longitude).toFixed(5)}`;
          $("#f_xarita").value = d.data.xarita; changed(); notify("success");
        } catch { toast(T("ed.loc_fail")); }
        App.busy(btn, false);
      };
      $("#aiBtn", form).onclick = async (e) => {
        const btn = e.currentTarget;
        App.busy(btn, true, T("ed.ai_busy"));
        try {
          const lang = d.lang === "auto" ? App.lang : d.lang;
          const r = await api("/api/video/ai/write", { section, data: d.data, lang, previous: d.data.matn || null });
          d.data.matn = r.text.slice(0, 200);
          $("#f_matn").value = d.data.matn; $("#mLen").textContent = `${d.data.matn.length}/200`;
          changed(); notify("success"); seekScene(2);
        } catch (err) { toast(err.message); }
        App.busy(btn, false);
        btn.innerHTML = `${icon("sparkle", "s")}${esc(T("ed.ai_again"))}`;
      };
      const photoIn = $("#photoIn", form);
      if (photoIn) photoIn.onchange = async () => {
        const f = photoIn.files[0]; if (!f) return;
        const fd = new FormData(); fd.append("file", f);
        toast(T("uploading"));
        try { d.data.rasm = (await api("/api/upload?kind=photo", fd)).url; redraw(); seekScene(1); }
        catch (err) { toast(err.message); }
      };
      const rmPhoto = $("#rmPhoto", form);
      if (rmPhoto) rmPhoto.onclick = () => { delete d.data.rasm; redraw(); };
      $$("[data-mu]", form).forEach((b) => (b.onclick = () => {
        haptic();
        d.music = { ...(d.music || {}), mode: b.dataset.mu };
        Draft.set(d);
        if (b.dataset.mu === "none") drawForm();
        else App.go("music", { mode: b.dataset.mu });
      }));
      const tm = $("#toMusic", form); if (tm) tm.onclick = () => { haptic(); App.go("music", { mode: d.music.mode }); };
      $$("[data-lang]", form).forEach((b) => (b.onclick = () => { haptic(); d.lang = b.dataset.lang; redraw(); seekScene(1); }));
      const trBtn = $("#trBtn", form);
      if (trBtn) trBtn.onclick = async () => {
        if (!(await App.confirmBox(T("ed.translate_q")))) return;
        App.busy(trBtn, true);
        try {
          const r = await api("/api/video/translate", { section, data: d.data, lang: d.lang });
          d.data = { ...d.data, ...r.data }; notify("success"); redraw();
        } catch (err) { App.busy(trBtn, false); toast(err.message); }
      };
    }
    drawForm();
    if (d.music && d.music.mode === "lib" && !S.music) loadMusic().then(() => { if (App.current().p === p) drawForm(); }).catch(() => {});

    // --- yaratish
    const qLine = $("#qLine");
    const ql = quotaLine(q);
    qLine.textContent = ql.text; qLine.className = ql.warn ? "warn" : "";
    $("#mkBtn").onclick = (e) => create(e.currentTarget);

    function validate() {
      const miss = S.vm.fields[section].filter((f) => f.required && (d.data[f.key] == null || String(d.data[f.key]).trim() === ""));
      if (d.data.toyona && String(d.data.karta || "").replace(/\D/g, "").length < 16) miss.push({ key: "karta" });
      if (!miss.length) return true;
      const k = miss[0].key, inp = $("#f_" + k);
      miss.forEach((m) => { const x = $("#f_" + m.key); if (x) x.classList.add("bad"); });
      notify("error");
      toast(T("err.required", { f: T("f." + k) }));
      if (inp) { inp.scrollIntoView({ behavior: "smooth", block: "center" }); setTimeout(() => inp.focus({ preventScroll: true }), 350); }
      return false;
    }
    async function create(btn, pay, topup) {
      if (!validate()) return;
      App.busy(btn, true, T("ed.creating"));
      const m = d.music || { mode: "none" };
      const music = m.mode === "lib" && m.track ? { mode: "lib", track: m.track, start: m.start || 0 }
        : m.mode === "own" && m.url ? { mode: "own", url: m.url, start: m.start || 0 } : { mode: "none" };
      try {
        const r = await api("/api/video", { design: dz.id, data: d.data, lang: d.lang, palette: d.palette, music, site: d.site, pay: pay || "auto", topup: topup || null, ui: App.lang });
        if (r.quota) S.me.quota = r.quota;
        d.site = r.site || d.site; Draft.set(d);
        S.me.videos = (S.me.videos || 0) + (r.status === "sent" ? 0 : 1);
        notify("success");
        App.closeAllSheets();
        App.go("queue", { job: r.job, first: r });
      } catch (err) {
        App.busy(btn, false);
        if (err.status === 402 && err.detail && err.detail.code === "paywall") {
          if (err.detail.quota) S.me.quota = err.detail.quota;
          paywall((p2, t2, b2) => create(b2, p2, t2));
        } else toast(err.message);
      }
    }
  };

  function clock(sec) { sec = Math.max(0, Math.round(sec)); return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`; }
  App.clock = clock;
  function quotaLine(q) {
    if (q.free_left > 0) return { text: T("ed.q_free", { n: q.free_left, total: q.free_per_day }) };
    if (q.bonus > 0) return { text: T("ed.q_bonus", { n: q.bonus }) };
    if (q.balance >= q.price) return { text: T("ed.q_balance", { sum: money(q.price), balance: money(q.balance) }) };
    return { text: T("ed.q_paid", { sum: money(q.price) }), warn: true };
  }
  function locate() {
    return new Promise((res, rej) => {
      const fallback = () => (navigator.geolocation ? navigator.geolocation.getCurrentPosition((x) => res(x.coords), rej, { timeout: 12000 }) : rej());
      const lm = App.tg && App.tg.LocationManager;
      if (!lm || !lm.init) return fallback();
      try {
        lm.init(() => {
          if (!lm.isLocationAvailable) return fallback();
          lm.getLocation((loc) => (loc ? res(loc) : rej()));
        });
      } catch { fallback(); }
    });
  }

  // ---------------------------------------------------------------- to'lov oynasi (bepul tugaganda)
  function paywall(retry) {
    const q = S.me.quota || {};
    const price = q.price || S.vm.price;
    const amounts = (S.vm.topups || []).filter((a) => a > price).slice(0, 3);
    let opt = "balance", amount = amounts[0] || price;
    const OPTS = [
      ["balance", "pw.balance", "pw.balance_note", "", "pw.good"],
      ["once", "pw.once", "pw.once_note", money(price)],
      ["tomorrow", "pw.tomorrow", "pw.tomorrow_note", money(0)],
      ["invite", "pw.invite", "pw.invite_note", money(0)],
    ];
    const s = App.sheet(`
      <div class="sh-head"><span class="sh-ic">${icon("clock")}</span><div><h1>${esc(T("pw.title"))}</h1>
        <p>${esc(T("pw.text", { n: q.free_per_day || 2 }))}</p></div></div>
      <div class="stack" role="radiogroup" style="gap:8px">${OPTS.map(([k, t, n, pr, badge]) => `
        <button type="button" class="opt" role="radio" data-o="${k}" aria-checked="${k === opt}"><span class="dot"></span>
          <span><b>${esc(T(t))}${badge ? ` <span class="badge green">${esc(T(badge))}</span>` : ""}</b><small>${esc(T(n))}</small></span>
          ${pr ? `<span class="pr">${esc(pr)}</span>` : ""}</button>`).join("")}</div>
      <div class="amounts" id="pwAm">${amounts.map((a) => `<button type="button" data-a="${a}" aria-pressed="${a === amount}"><b>${esc(money(a))}</b><small>${esc(T("topup.videos", { n: Math.floor(a / price) }))}</small></button>`).join("")}</div>
      <button type="button" class="btn" id="pwGo"></button>
      <p class="hint" style="text-align:center">${esc(T("pay.note"))}</p>`, { label: T("pw.title") });
    const go = $("#pwGo", s.el), am = $("#pwAm", s.el);
    const sync = () => {
      am.hidden = opt !== "balance" || !amounts.length;
      go.textContent = opt === "balance" ? T("topup.pay", { sum: money(amount) }) : opt === "once" ? T("topup.pay", { sum: money(price) })
        : opt === "tomorrow" ? T("pw.ok") : T("pw.share");
    };
    $$("[data-o]", s.el).forEach((b) => (b.onclick = () => { haptic(); opt = b.dataset.o; $$("[data-o]", s.el).forEach((x) => x.setAttribute("aria-checked", x === b)); sync(); }));
    $$("[data-a]", s.el).forEach((b) => (b.onclick = () => { haptic(); amount = +b.dataset.a; $$("[data-a]", s.el).forEach((x) => x.setAttribute("aria-pressed", x === b)); sync(); }));
    go.onclick = () => {
      if (opt === "tomorrow") { s.close(); toast(T("pw.saved")); return; }
      if (opt === "invite") { App.shareUrl(S.me.ref_link, T("ref.share_text")); return; }
      retry("wait", opt === "balance" ? amount : price, go);
    };
    sync();
  }
  App.videoPaywall = paywall;

  // ---------------------------------------------------------------- navbat va obuna
  App.views.queue = (p, el) => {
    App.chrome({ night: true });
    let job = null, timer = null, claimed = false, stopped = false;
    const r0 = p.first || {};
    if (r0.status === "sent") { job = { id: r0.job, site: r0.site, status: "done", delivered: true, progress: 100 }; }
    App.onLeave(() => { stopped = true; clearTimeout(timer); document.removeEventListener("visibilitychange", onVis); });
    function onVis() { if (document.visibilityState === "visible") tick(true); }
    document.addEventListener("visibilitychange", onVis);
    const ring = (pct, done) => {
      const c = 2 * Math.PI * 56;
      return `<div class="ring ${done ? "done" : ""}"><svg viewBox="0 0 132 132" aria-hidden="true"><circle class="bg" cx="66" cy="66" r="56"/>
        <circle class="fg" cx="66" cy="66" r="56" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${(c * (1 - pct / 100)).toFixed(1)}"/></svg>
        <b>${done ? icon("check") : pct ? pct + "%" : icon("clock")}</b></div>`;
    };
    function draw() {
      const j = job || { status: r0.status || "queued", progress: 0, position: r0.position || 0, need_sub: r0.need_sub, subscribed: r0.subscribed, channel: r0.channel };
      const st = j.status;
      const done = st === "done" && j.delivered;
      const pct = st === "done" ? 100 : st === "rendering" ? Math.max(3, Math.min(99, j.progress || 0)) : 0;
      let title = T("q.making"), sub = "";
      if (st === "queued") sub = j.position > 1 ? T("q.position", { n: j.position, m: Math.max(1, Math.ceil(j.position * 40 / 60)) }) : T("q.next");
      if (st === "rendering") sub = T("q.rendering");
      if (st === "awaiting_payment") { title = T("q.await_t"); sub = T("q.await_s"); }
      if (st === "failed") { title = T("q.failed_t"); sub = T("q.failed_s"); }
      if (st === "done" && !j.delivered) { title = T("q.ready_t"); sub = j.need_sub && !j.subscribed ? T("q.ready_sub") : T("q.sending"); }
      if (done) { title = T("q.sent_t"); sub = T("q.sent_s"); }
      const stepState = (i) => {
        if (done) return "ok";
        if (st === "rendering") return i === 0 ? (pct >= 90 ? "ok" : "on") : i === 1 ? (pct >= 90 ? "on" : "") : "";
        if (st === "done") return i < 2 ? "ok" : "on";
        return "";
      };
      const showSteps = ["queued", "rendering", "done"].includes(st);
      const needSub = j.need_sub && !j.subscribed && st !== "failed" && st !== "awaiting_payment";
      const subOk = j.need_sub && j.subscribed && !done && st !== "failed" && st !== "awaiting_payment";
      const q = S.me.quota || {};
      const nth = r0.charge === "free" ? (q.free_per_day || 2) - (q.free_left || 0) : 0;
      el.innerHTML = `<div class="queue fade">
        <div class="head">${st === "awaiting_payment" ? `<div class="ring"><svg viewBox="0 0 132 132" aria-hidden="true"><circle class="bg" cx="66" cy="66" r="56"/></svg><b>${icon("wallet")}</b></div>` : st === "failed" ? "" : ring(pct, done)}
          <h1>${esc(title)}</h1><p>${esc(sub)}</p></div>
        ${showSteps && !done ? `<ol class="qsteps">${["q.step1", "q.step2", "q.step3"].map((k, i) => `<li class="${stepState(i)}"><span>${stepState(i) === "ok" ? icon("check", "xs") : ""}</span>${esc(T(k))}</li>`).join("")}</ol>` : ""}
        ${needSub ? `<section class="white-card"><div class="row"><span class="ic">${icon("channel")}</span><div><h2>${esc(T("q.sub_t"))}</h2><p>${esc(T("q.sub_s"))}</p></div></div>
          <button type="button" class="btn" id="subBtn">${esc(T("q.sub_btn"))}</button>
          <button type="button" class="btn ghost" id="subCheck">${esc(T("q.sub_check"))}</button><small>${esc(T("q.sub_note"))}</small></section>` : ""}
        ${subOk ? `<section class="white-card"><div class="row"><span class="ic ok">${icon("check")}</span><div><h2>${esc(T("q.sub_ok"))}</h2><p>${esc(T("q.sub_ok_s"))}</p></div></div></section>` : ""}
        <div class="stack">
          ${done ? `<button type="button" class="btn" id="chatBtn">${icon("send", "s")}${esc(T("go_chat"))}</button>
            ${j.id ? `<button type="button" class="btn light" id="shareBtn">${icon("share", "s")}${esc(T("q.share"))}</button>` : ""}` : ""}
          ${st === "awaiting_payment" ? `<button type="button" class="btn" id="chatBtn">${icon("send", "s")}${esc(T("go_chat"))}</button>` : ""}
          ${st === "failed" ? `<button type="button" class="btn" id="againBtn">${esc(T("q.again"))}</button>` : ""}
          ${(done || st === "failed" || st === "awaiting_payment") ? "" : `<button type="button" class="btn line" id="chatBtn2">${esc(T("q.close_ok"))}</button>`}
        </div>
        ${done && (r0.site || j.site) ? `<div class="stack">
          <button type="button" class="banner" id="guestsBtn">${icon("users")}<span><b>${esc(T("q.guests_t"))}</b>${esc(T("q.guests_s"))}</span>${icon("chev")}</button>
          ${sectionOf(j) === "toy" ? `<button type="button" class="banner" id="siteBtn">${icon("globe")}<span><b>${esc(T("q.site_t"))}</b>${esc(T("q.site_s"))}</span>${icon("chev")}</button>` : ""}
          <button type="button" class="btn line" id="editBtn">${icon("edit", "s")}${esc(T("q.edit"))}</button></div>` : ""}
        <p class="foot">${esc(T("q.foot"))}${nth > 0 ? "<br>" + esc(T("q.nth_free", { n: nth })) : ""}</p></div>`;
      const on = (id, fn) => { const b = $("#" + id); if (b) b.onclick = fn; };
      on("chatBtn", () => App.closeApp());
      on("chatBtn2", () => App.closeApp());
      on("shareBtn", (e) => shareVideo(j.id, e.currentTarget));
      on("againBtn", () => App.back());
      on("editBtn", () => App.back());
      on("subBtn", () => { haptic(); App.openLink(j.channel || S.vm.channel); });
      on("subCheck", (e) => { App.busy(e.currentTarget, true); tick(true); });
      on("guestsBtn", () => App.go("event", { slug: j.site || r0.site || slugOf(j) }));
      on("siteBtn", () => App.tab("sites", { fromEvent: j.site || r0.site || slugOf(j) }));
    }
    const sectionOf = (j) => j.section || (design((App.Draft.get() || {}).design) || {}).section;
    const slugOf = (j) => j.site || (App.Draft.get() || {}).site;
    async function tick(now) {
      clearTimeout(timer);
      if (stopped || !p.job) return;
      try {
        job = await api(`/api/video/${p.job}`);
        if (job.status === "done" && !job.delivered && !claimed && (!job.need_sub || job.subscribed)) {
          claimed = true;
          const c = await api(`/api/video/${p.job}/claim`, {});
          if (c.delivered) { job.delivered = true; notify("success"); }
          else claimed = false;
        }
      } catch { /* tarmoq: keyingi urinish */ }
      if (stopped) return;
      draw();
      const live = !job || ["queued", "rendering"].includes(job.status) || (job.status === "done" && !job.delivered) || job.status === "awaiting_payment";
      if (live) timer = setTimeout(tick, job && job.status === "awaiting_payment" ? 6000 : 2500);
    }
    draw();
    if (r0.status !== "sent") tick();
  };

  // ---------------------------------------------------------------- musiqa
  async function loadMusic() { S.music = await api("/api/music"); return S.music; }
  App.views.music = (p, el) => {
    App.chrome({ cta: true });
    const d = Draft.get();
    if (!d) return App.back();
    const dz = design(d.design);
    const m = (d.music = { mode: p.mode || (d.music && d.music.mode) || "lib", ...(d.music || {}) });
    m.mode = p.mode || m.mode;
    let audio = null, playingId = null;
    const stop = () => { if (audio) { audio.pause(); audio = null; } playingId = null; };
    App.onLeave(stop);
    const theme = p.theme || (S.music && S.music.themes.includes(dz.section) ? dz.section : "umumiy");
    const names = d.data.kuyov && d.data.kelin ? `${d.data.kuyov} & ${d.data.kelin}` : d.data.ism || T("sec." + dz.section);
    el.innerHTML = `
      <div class="bar light"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button>
        <div class="ttl"><b>${esc(T("mu.title"))}</b><span>${esc(T("mu.sub", { name: names }))}</span></div></div>
      <div class="wrap stack fade">
        <div class="seg" role="tablist">${[["lib", "mu.lib"], ["own", "mu.own"], ["none", "mu.none"]].map(([k, l]) => `<button type="button" role="tab" data-mode="${k}" aria-selected="${m.mode === k}">${esc(T(l))}</button>`).join("")}</div>
        <div id="mbody"></div></div>
      <div class="cta"><button type="button" class="btn" id="muOk">${esc(T("mu.ok"))}</button></div>`;
    $("#bk").onclick = App.back;
    $$("[data-mode]", el).forEach((b) => (b.onclick = () => { haptic(); stop(); p.mode = b.dataset.mode; m.mode = p.mode; Draft.set(d); App.render(); }));
    const body = $("#mbody");
    const okBtn = $("#muOk");
    okBtn.onclick = () => { Draft.set(d); App.back(); };

    function playBtn(id, url, start) {
      if (playingId === id) { stop(); return false; }
      stop();
      audio = new Audio(url);
      audio.currentTime = start || 0;
      audio.play().catch(() => {});
      const until = (start || 0) + 20;
      audio.ontimeupdate = () => { if (audio && audio.currentTime >= until) stop(); };
      playingId = id;
      return true;
    }

    if (m.mode === "lib") {
      body.innerHTML = `<div class="empty"><span class="spin"></span></div>`;
      (S.music ? Promise.resolve(S.music) : loadMusic()).then((lib) => {
        if (!body.isConnected) return;
        const themes = lib.themes;
        const cur = themes.includes(theme) ? theme : themes[0];
        const of = (kind) => lib.tracks.filter((t) => t.kind === kind && (t.theme === cur || t.theme === "umumiy"));
        const row = (t) => `<div class="trk"><button type="button" class="pl" data-play="${t.id}" aria-label="${esc(T("play"))}">${icon("play", "s")}</button>
          <button type="button" class="pick" role="radio" data-pick="${t.id}" aria-checked="${m.track === t.id}"><span><b>${esc(t.title)}</b><small>${esc(t.subtitle || t.author || "")}</small></span><span class="radio"></span></button></div>`;
        const list = (kind, title, note) => {
          const xs = of(kind);
          return xs.length ? `<h2 style="font-size:20px;margin:6px 0 10px">${esc(T(title))} <span style="font:500 13.5px var(--f-body);color:var(--muted)">${esc(T(note))}</span></h2>
            <div class="trk-list">${xs.map(row).join("")}</div>` : "";
        };
        const any = lib.tracks.length;
        body.innerHTML = `<div class="chips scroll" style="margin-bottom:14px">${themes.map((k) => `<button type="button" class="chip" data-theme="${k}" aria-pressed="${k === cur}">${esc(T("mut." + k))}</button>`).join("")}</div>
          ${any ? list("vocal", "mu.vocal_t", "mu.vocal_n") + `<div style="height:14px"></div>` + list("instr", "mu.instr_t", "mu.instr_n") : ""}
          ${any && !of("vocal").length && !of("instr").length ? `<div class="empty">${esc(T("mu.theme_empty"))}</div>` : ""}
          ${!any ? `<div class="empty"><b>${esc(T("mu.lib_empty"))}</b>${esc(T("mu.lib_empty_s"))}</div>` : ""}
          <p class="hint" style="margin-top:14px">${esc(T("mu.lib_note"))}</p>`;
        $$("[data-theme]", body).forEach((b) => (b.onclick = () => { haptic(); stop(); p.theme = b.dataset.theme; App.render(); }));
        $$("[data-pick]", body).forEach((b) => (b.onclick = () => {
          haptic(); const t = lib.tracks.find((x) => x.id === +b.dataset.pick);
          m.track = t.id; m.start = t.start || 0; Draft.set(d);
          $$("[data-pick]", body).forEach((x) => x.setAttribute("aria-checked", x === b));
        }));
        $$("[data-play]", body).forEach((b) => (b.onclick = () => {
          const t = lib.tracks.find((x) => x.id === +b.dataset.play);
          $$("[data-play]", body).forEach((x) => { x.classList.remove("on"); x.innerHTML = icon("play", "s"); });
          if (playBtn(t.id, t.url, t.start)) { b.classList.add("on"); b.innerHTML = icon("pause", "s"); }
        }));
      }).catch((e) => { body.innerHTML = App.errBox(e); });
      return;
    }
    if (m.mode === "none") {
      body.innerHTML = `<div class="card"><p>${esc(T("mu.none_text"))}</p></div>`;
      return;
    }
    // o'z musiqasi
    const agreed = !!m.agree;
    const dur = m.dur || 0;
    const seed = [...(m.name || "x")].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
    const bars = Array.from({ length: 48 }, (_, i) => 18 + ((seed >> (i % 24)) % 7) * 6 + Math.round(10 * Math.abs(Math.sin(i * 0.7 + seed))));
    const segFrom = m.start || 0;
    body.innerHTML = `
      <span class="drop upload"><span class="ic">${icon("upload")}</span><b>${esc(m.url ? T("mu.replace") : T("mu.upload"))}</b><small>${esc(T("mu.upload_sub"))}</small>
        <input type="file" accept="audio/*" id="muIn"></span>
      ${m.url ? `<div class="card"><div class="card-h"><b style="font-size:13.5px">${esc(m.name || T("mu.own_file"))}</b><span class="hint">${dur ? clock(dur) : ""}</span></div>
        <div class="wave" id="wave">${bars.map((h, i) => `<i style="height:${h}px" data-i="${i}"></i>`).join("")}</div>
        ${dur > 21 ? `<input type="range" id="muStart" min="0" max="${Math.max(0, Math.floor(dur - 20))}" step="1" value="${segFrom}" aria-label="${esc(T("mu.start"))}">` : ""}
        <p class="hint" id="segTxt">${esc(T("mu.segment", { from: clock(segFrom), to: clock(segFrom + 20) }))}</p>
        <button type="button" class="btn ghost sm" id="muPlay" style="margin-top:10px">${icon("play", "s")}${esc(T("mu.listen"))}</button></div>
      <button type="button" class="opt" role="checkbox" id="agree" aria-checked="${agreed}"><span class="dot"></span><span><b>${esc(T("mu.rights"))}</b><small>${esc(T("mu.rights_s"))}</small></span></button>` : ""}`;
    const paint = () => {
      const from = m.start || 0, n = bars.length;
      $$("#wave i", body).forEach((x, i) => { const t = dur ? (i / n) * dur : 0; x.classList.toggle("in", !!dur && t >= from && t <= from + 20); });
    };
    if (m.url) paint();
    okBtn.disabled = !!m.url && !agreed;
    if (!m.url) okBtn.disabled = true;
    const muIn = $("#muIn");
    muIn.onchange = async () => {
      const f = muIn.files[0]; if (!f) return;
      const fd = new FormData(); fd.append("file", f);
      toast(T("uploading"), 8000);
      try {
        const { url } = await api("/api/upload?kind=music", fd);
        const len = await new Promise((res) => { const a = new Audio(url); a.onloadedmetadata = () => res(a.duration || 0); a.onerror = () => res(0); });
        Object.assign(m, { url, name: f.name.slice(0, 60), dur: Math.round(len), start: 0, agree: false });
        Draft.set(d); App.render();
      } catch (e) { toast(e.message); }
    };
    const rs = $("#muStart");
    if (rs) rs.oninput = () => { m.start = +rs.value; $("#segTxt").textContent = T("mu.segment", { from: clock(m.start), to: clock(m.start + 20) }); paint(); Draft.set(d); };
    const mp = $("#muPlay");
    if (mp) mp.onclick = () => { const on = playBtn("own", m.url, m.start || 0); mp.innerHTML = `${icon(on ? "pause" : "play", "s")}${esc(T(on ? "pause" : "mu.listen"))}`; };
    const ag = $("#agree");
    if (ag) ag.onclick = () => { haptic(); m.agree = ag.getAttribute("aria-checked") !== "true"; ag.setAttribute("aria-checked", m.agree); okBtn.disabled = !m.agree; Draft.set(d); };
  };
})();
