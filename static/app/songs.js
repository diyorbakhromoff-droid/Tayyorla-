/* Qo'shiq: yaqin odamga shaxsiy AI qo'shiq — so'rovnoma, she'r, 20 soniyalik namuna, to'lov, ikki variant, sayt va videoga qo'yish */
(() => {
  "use strict";
  const { $, $$, esc, T, icon, S, api, haptic, notify, toast, store, money } = App;
  const DKEY = "tyr-song-draft";
  const PEND = "tyr-song-music";  // videoga qo'yiladigan qo'shiq (dizayn tanlangach muharrirga tushadi)

  // server o'zbekcha nomlarni yuboradi — tarjimasi bo'lsa o'sha
  const relName = (k) => App.tx("sgr." + k, ((S.sm && S.sm.relations.find((x) => x.key === k)) || { name: k }).name);
  const occName = (k) => App.tx("sgo." + k, ((S.sm && S.sm.occasions.find((x) => x.key === k)) || { name: k }).name);
  const styleName = (k) => App.tx("sgs." + k, ((S.sm && S.sm.styles.find((x) => x.key === k)) || { name: k }).name);
  const voiceName = (k) => App.tx("sgv." + k, ((S.sm && S.sm.voices.find((x) => x.key === k)) || { name: k }).name);
  const qLabel = (q) => App.tx("sgq." + q.key, q.label);
  const qHint = (q) => App.tx("sgqh." + q.key, q.hint);
  const REL_EM = { sevgilim: "❤️", juftim: "💍", onam: "👩", otam: "👨", opa_singil: "👭", aka_uka: "👬", dostim: "🤝", farzandim: "👶", buvim_bobom: "👵", boshqa: "✨" };
  const OCC_EM = { tugilgan_kun: "🎂", sevgi: "💌", toy: "💍", uzr: "🌷", rahmat: "🙏", bayram: "🎉", shunchaki: "☀️" };
  const STYLE_EM = { pop: "🎤", rep: "🎧", disko90: "🪩", rok: "🎸", shanson: "🪗", klassika: "🎻", klub: "🔊", indi: "🌙", xalqona: "🥁", akustika: "🎶", milliy: "🪕", custom: "✍️" };
  const BUSY = ["preview_queued", "preview_gen", "paid_queued", "paid_gen"];

  // ---------------------------------------------------------------- ma'lumot (kesh bilan)
  let metaAt = 0, listAt = 0;
  App.songMeta = async (force) => {
    if (!force && S.sm && Date.now() - metaAt < 30000) return S.sm;
    S.sm = await api("/api/songs/meta");
    metaAt = Date.now();
    return S.sm;
  };
  App.songList = async (force) => {
    if (!force && S.songs && Date.now() - listAt < 15000) return S.songs;
    S.songs = (await api("/api/songs")).songs;
    listAt = Date.now();
    return S.songs;
  };
  const remember = (song) => {
    if (!song || !S.songs) return;
    const i = S.songs.findIndex((x) => x.id === song.id);
    if (i >= 0) S.songs[i] = song; else S.songs.unshift(song);
  };
  const readySongs = () => (S.songs || []).filter((x) => x.status === "ready" && x.file);
  App.readySongs = readySongs;
  const absUrl = (u) => new URL(u, location.href).href;
  const errMsg = (e) => (e.status === 503 ? T("song.soon_t") : e.status === 502 ? T("song.err_ai") : e.message);
  const songTitle = (s) => s.title || T("song.title");

  function statusBadge(s) {
    if (s.status === "ready") return ["green", "song.st.ready"];
    if (s.status === "preview_ready") return ["pink", "song.st.preview_ready"];
    if (s.status === "failed") return ["rose", "song.st.failed"];
    if (s.status === "paid_queued" || s.status === "paid_gen") return ["gold", "song.st.paid"];
    if (s.status === "preview_queued" || s.status === "preview_gen") return ["lilac", "song.st.preview"];
    return ["lilac", "song.st.lyrics"];
  }
  const disc = (cls = "") => `<span class="sg-disc ${cls}" aria-hidden="true"><i></i></span>`;
  const eqBars = (n = 22) => `<span class="sg-eq" aria-hidden="true">${Array.from({ length: n }, (_, i) =>
    `<i style="animation-delay:${((i * 137) % 1000) / 1000 - 1}s;height:${40 + ((i * 53) % 60)}%"></i>`).join("")}</span>`;

  // ---------------------------------------------------------------- pleyer (Telegram WebView'da ham ishlaydi: oddiy <audio> + o'z tugmalari)
  let players = [];
  const stopPlayers = () => {
    players.forEach((a) => { try { a.pause(); a.removeAttribute("src"); a.load(); } catch { /* e'tiborsiz */ } });
    players = [];
  };
  App.stopSongAudio = stopPlayers;
  const seedOf = (s) => [...String(s)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
  function playerHtml(src, label) {
    const seed = seedOf(src);
    const bars = Array.from({ length: 44 }, (_, i) => {
      const v = Math.abs(Math.sin((i + (seed % 13)) * 0.58) * 0.62 + Math.sin((i + (seed % 7)) * 0.21) * 0.38);
      return 16 + Math.round(84 * v * (0.55 + 0.45 * Math.sin(Math.PI * (i + 1) / 45)));
    });
    return `<div class="splay" data-src="${esc(src)}">
      <button type="button" class="pp" aria-label="${esc(T("play"))}">${icon("play")}</button>
      <div class="sbars" role="slider" tabindex="0" aria-label="${esc(label || T("play"))}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">${bars.map((h) => `<i style="height:${h}%"></i>`).join("")}</div>
      <span class="tm">0:00</span></div>`;
  }
  function bindPlayers(root) {
    $$(".splay", root).forEach((el) => {
      const audio = new Audio();
      audio.preload = "metadata";
      audio.src = el.dataset.src;
      players.push(audio);
      const pp = $(".pp", el), wave = $(".sbars", el), bars = $$(".sbars i", el), tm = $(".tm", el);
      const paint = () => {
        const d = isFinite(audio.duration) ? audio.duration : 0, t = audio.currentTime || 0, k = d ? t / d : 0;
        const n = Math.round(k * bars.length);
        bars.forEach((b, i) => b.classList.toggle("in", i < n));
        tm.textContent = App.clock(t > 0 || !d ? t : d);
        wave.setAttribute("aria-valuenow", Math.round(k * 100));
      };
      const mark = (on) => { pp.innerHTML = icon(on ? "pause" : "play"); pp.setAttribute("aria-label", T(on ? "pause" : "play")); el.classList.toggle("on", on); };
      audio.addEventListener("loadedmetadata", paint);
      audio.addEventListener("timeupdate", paint);
      audio.addEventListener("play", () => mark(true));
      audio.addEventListener("pause", () => mark(false));
      audio.addEventListener("ended", () => { mark(false); audio.currentTime = 0; paint(); });
      pp.onclick = () => {
        haptic();
        if (!audio.paused) { audio.pause(); return; }
        players.forEach((a) => { if (a !== audio && !a.paused) a.pause(); });
        audio.play().catch(() => toast(T("err.generic")));
      };
      const seekTo = (k) => { if (isFinite(audio.duration) && audio.duration) { audio.currentTime = Math.min(1, Math.max(0, k)) * audio.duration; paint(); } };
      wave.onclick = (e) => { const r = wave.getBoundingClientRect(); seekTo((e.clientX - r.left) / r.width); };
      wave.onkeydown = (e) => {
        const d = audio.duration || 0;
        if (!d || !["ArrowLeft", "ArrowRight"].includes(e.key)) return;
        e.preventDefault();
        seekTo((audio.currentTime + (e.key === "ArrowRight" ? 5 : -5)) / d);
      };
    });
  }

  /** Qisqa tinglash (sayt/video musiqasi ro'yxatlari): bitta tugma — ijro/pauza. */
  let quick = null, quickBtn = null;
  const stopQuick = () => {
    if (quick) { quick.pause(); quick = null; }
    if (quickBtn) { quickBtn.classList.remove("on"); quickBtn.innerHTML = icon("play", "s"); quickBtn = null; }
  };
  function quickPlay(btn, url, start) {
    const same = quickBtn === btn;
    stopQuick();
    if (same) return;
    quick = new Audio(url);
    quick.currentTime = start || 0;
    quick.play().catch(() => {});
    quick.onended = stopQuick;
    quickBtn = btn; btn.classList.add("on"); btn.innerHTML = icon("pause", "s");
  }

  /** Tayyor qo'shiqlar ro'yxati (sayt fon musiqasi va video musiqasi tanlovida): tinglash va tanlash. */
  App.songPickList = (box, { selected, onPick }) => {
    const list = readySongs();
    if (!box) return;
    if (!list.length) { box.innerHTML = ""; return; }
    App.onLeave(stopQuick);
    box.innerHTML = `<p class="sg-mini-h">${icon("music", "xs")}${esc(T("song.my"))}</p>
      <div class="trk-list">${list.map((x) => `<div class="trk"><button type="button" class="pl" data-sp="${x.id}" aria-label="${esc(T("play"))}">${icon("play", "s")}</button>
        <button type="button" class="pick" role="radio" data-spick="${x.id}" aria-checked="${x.file === selected}"><span><b>${esc(songTitle(x))}</b>
          <small>${esc(T("song.for", { name: x.recipient }))}</small></span><span class="radio"></span></button></div>`).join("")}</div>`;
    $$("[data-sp]", box).forEach((b) => (b.onclick = () => { const x = list.find((y) => y.id === +b.dataset.sp); quickPlay(b, x.file, x.chorus_at || 0); }));
    $$("[data-spick]", box).forEach((b) => (b.onclick = () => {
      haptic(); stopQuick();
      $$("[data-spick]", box).forEach((x) => x.setAttribute("aria-checked", x === b));
      onPick(list.find((y) => y.id === +b.dataset.spick));
    }));
  };
  /** Videoga qo'yiladigan qo'shiq: naqoratdan 1 soniya oldin boshlanadi. */
  App.songMusic = (s) => ({ mode: "own", url: s.file, name: songTitle(s), dur: 0, start: Math.max(0, (s.chorus_at || 0) - 1), agree: true });
  App.takePendingSongMusic = () => { const m = store.json(PEND); if (m) store.del(PEND); return m; };

  // ---------------------------------------------------------------- bosh sahifa kartochkasi
  const cardState = () => {
    const m = S.sm, on = !m || m.on;
    return {
      on, badge: on ? T("new") : T("song.soon_badge"),
      note: !on ? T("song.soon_t") : m && !m.free_previews ? T("song.from", { sum: money(m.price) }) : T("song.home_free", { n: (m && m.preview_seconds) || 20 }),
    };
  };
  App.songCardHtml = () => {
    const c = cardState(), n = (S.songs || []).length;
    return `<button type="button" class="song-card" id="songCard">
        <span class="sc-top">${disc()}<span class="sc-txt"><span class="badge ${c.on ? "gold" : "lilac"}" id="songBadge">${esc(c.badge)}</span>
          <b>${esc(T("song.home_t"))}</b><small>${esc(T("song.home_s"))}</small></span></span>
        <span class="sc-foot">${eqBars(9)}<span class="sc-note" id="songNote">${esc(c.note)}</span><span class="sc-go">${esc(T("song.home_go"))}${icon("chev", "xs")}</span></span>
      </button>
      <button type="button" class="linkbtn sc-mine" id="songMine" ${n ? "" : "hidden"}>${icon("music", "xs")}<span>${esc(T("song.home_mine", { n }))}</span></button>`;
  };
  App.bindSongCard = (el) => {
    const card = $("#songCard", el), mine = $("#songMine", el);
    if (!card) return;
    card.onclick = () => { haptic(); App.songWizard(); };
    mine.onclick = () => { haptic(); App.go("songs"); };
    Promise.all([App.songMeta(), App.songList()]).then(([, list]) => {
      if (!card.isConnected) return;
      const c = cardState(), b = $("#songBadge", card);
      b.textContent = c.badge; b.className = `badge ${c.on ? "gold" : "lilac"}`;
      $("#songNote", card).textContent = c.note;
      mine.hidden = !list.length;
      $("span", mine).textContent = T("song.home_mine", { n: list.length });
    }).catch(() => {});
  };

  // ---------------------------------------------------------------- qo'shiqlarim
  App.views.songs = (p, el) => {
    App.chrome({});
    el.innerHTML = `<div class="bar light"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button>
        <div class="ttl"><b>${esc(T("song.mine"))}</b><span>${esc(T("song.mine_s"))}</span></div></div>
      <div class="wrap stack fade" id="slBody"><div class="empty"><span class="spin"></span></div></div>`;
    $("#bk").onclick = App.back;
    const box = $("#slBody");
    Promise.all([App.songMeta(true), App.songList(true)]).then(([m, list]) => {
      if (!box.isConnected) return;
      box.innerHTML = `${m.on ? `<button type="button" class="sg-new" id="slNew"><span class="ic">${icon("plus")}</span><span><b>${esc(T("song.new"))}</b>${esc(T("song.new_s"))}</span>${icon("chev")}</button>`
          : `<div class="note">${esc(T("song.soon_t"))}</div>`}
        ${list.length ? list.map((s) => {
          const [cls, key] = statusBadge(s);
          return `<button type="button" class="sg-row" data-song="${s.id}">${disc(s.busy ? "sm rot" : "sm")}
            <span class="t"><b>${esc(songTitle(s))}</b><small>${esc([T("song.for", { name: s.recipient }), s.occasion ? occName(s.occasion) : ""].filter(Boolean).join(" · "))}</small>
              <span class="badge ${cls}">${s.busy ? '<span class="spin" style="width:10px;height:10px;border-width:2px"></span>' : ""}${esc(T(key))}</span></span>${icon("chev", "s chev")}</button>`;
        }).join("") : `<div class="empty"><b>${esc(T("song.none"))}</b>${esc(T("song.none_s"))}</div>`}`;
      const nb = $("#slNew"); if (nb) nb.onclick = () => { haptic(); App.songWizard(); };
      $$("[data-song]", box).forEach((b) => (b.onclick = () => { haptic(); App.go("song", { id: +b.dataset.song }); }));
    }).catch((e) => { box.innerHTML = App.errBox(e); });
  };

  // ---------------------------------------------------------------- so'rovnoma (4 qadam)
  let wiz = null;
  const blank = () => ({ recipient: "", relation: "", occasion: "", style: "", voice: "male", answers: {} });
  const saveW = () => store.put(DKEY, wiz);
  /** Yangi qo'shiq: prefill — {recipient, relation, occasion} (sayt yoki tavsiyadan). */
  App.songWizard = (prefill) => {
    if (prefill) { wiz = { ...blank(), ...Object.fromEntries(Object.entries(prefill).filter(([, v]) => v)) }; saveW(); }
    App.go("song_new", { step: 0 });
  };
  const STEPS = ["song.s1", "song.s2", "song.s3", "song.s4"];

  App.views.song_new = (p, el) => {
    if (!wiz) wiz = { ...blank(), ...(store.json(DKEY) || {}) };
    wiz.answers = wiz.answers || {};
    const step = Math.min(3, p.step || 0);
    const bar = (sub) => `<div class="bar light"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button>
        <div class="ttl"><b>${esc(T("song.title"))}</b><span>${esc(sub)}</span></div></div>`;
    const head = bar(T("song.step", { n: step + 1 }) + " · " + T(STEPS[step]));
    const m = S.sm;
    if (!m) {
      App.chrome({});
      el.innerHTML = head + `<div class="wrap"><div class="empty"><span class="spin"></span></div></div>`;
      $("#bk").onclick = App.back;
      App.songMeta(true).then(() => { if (App.current().p === p) App.render(); })
        .catch((e) => { const w = $(".wrap", el); if (w) w.innerHTML = App.errBox(e) + `<div style="height:12px"></div><button type="button" class="btn" id="rt">${esc(T("retry"))}</button>`; const r = $("#rt"); if (r) r.onclick = () => App.render(); });
      return;
    }
    if (!m.on) {
      App.chrome({});
      el.innerHTML = bar(T("song.home_t")) + `<div class="wrap fade"><div class="sg-soon">${disc("xl")}
        <h1>${esc(T("song.soon_t"))}</h1><p>${esc(T("song.soon_s"))}</p>
        <button type="button" class="btn" id="toHome">${esc(T("song.to_home"))}</button></div></div>`;
      $("#bk").onclick = App.back;
      $("#toHome").onclick = () => App.tab("home");
      return;
    }
    if (p.writing) return writing(el, p);
    App.chrome({ cta: true });
    const dots = `<div class="wrap" style="padding-bottom:6px"><div class="dots">${STEPS.map((_, i) => `<i class="${i <= step ? "on" : ""}"></i>`).join("")}</div></div>`;
    let body = "";
    if (step === 0) {
      body = `<h1>${esc(T("song.q_who"))}</h1><p class="lead">${esc(T("song.q_who_s"))}</p>
        <label class="field">${esc(T("song.name"))}<input id="wName" maxlength="80" autocomplete="off" value="${esc(wiz.recipient)}" placeholder="${esc(T("song.name_ph"))}"></label>
        <div class="field">${esc(T("song.rel"))}<div class="chips">${m.relations.map((r) =>
          `<button type="button" class="chip" data-rel="${esc(r.key)}" aria-pressed="${wiz.relation === r.key}">${REL_EM[r.key] || "✨"} ${esc(relName(r.key))}</button>`).join("")}</div></div>`;
    } else if (step === 1) {
      body = `<h1>${esc(T("song.q_occ"))}</h1><p class="lead">${esc(T("song.q_occ_s", { name: wiz.recipient }))}</p>
        <div class="rels">${m.occasions.map((o) => `<button type="button" class="rel" data-occ="${esc(o.key)}" aria-pressed="${wiz.occasion === o.key}">
          <span class="em">${OCC_EM[o.key] || "🎵"}</span><b>${esc(occName(o.key))}</b></button>`).join("")}</div>`;
    } else if (step === 2) {
      body = `<h1>${esc(T("song.q_about", { name: wiz.recipient }))}</h1><p class="lead">${esc(T("song.q_about_s"))}</p>
        ${m.questions.map((q) => `<label class="card field sg-qcard${q.key === "istak" ? " key" : ""}">
          <span class="ql">${esc(qLabel(q))}${q.key === "istak" ? ` <span class="badge gold">${esc(T("song.important"))}</span>` : ""}</span>
          <textarea rows="2" maxlength="400" data-q="${esc(q.key)}" placeholder="${esc(qHint(q))}">${esc(wiz.answers[q.key] || "")}</textarea></label>`).join("")}`;
    } else {
      const custom = wiz.style === "custom";
      body = `<h1>${esc(T("song.q_style"))}</h1><p class="lead">${esc(T("song.q_style_s"))}</p>
        <section class="card"><h2>${esc(T("song.genre"))}</h2><div class="chips">${m.styles.map((x) =>
          `<button type="button" class="chip" data-style="${esc(x.key)}" aria-pressed="${wiz.style === x.key}">${STYLE_EM[x.key] || "🎵"} ${esc(styleName(x.key))}</button>`).join("")}</div>
          ${custom ? `<label class="field" style="margin-top:12px">${esc(T("song.janr"))}<input id="wJanr" maxlength="120" value="${esc(wiz.answers.janr || "")}" placeholder="${esc(T("song.janr_ph"))}"></label>` : ""}</section>
        <section class="card"><h2>${esc(T("song.voice"))}</h2><div class="seg">${m.voices.map((v) =>
          `<button type="button" data-voice="${esc(v.key)}" aria-pressed="${wiz.voice === v.key}">${esc(voiceName(v.key))}</button>`).join("")}</div></section>
        <section class="card sg-sum"><span>${esc(T("song.for", { name: wiz.recipient }))}</span>
          <b>${esc([relName(wiz.relation), occName(wiz.occasion)].join(" · "))}</b></section>
        ${p.err ? App.errBox(p.err) : ""}
        <p class="hint" style="text-align:center">${esc(T("song.write_note"))}</p>`;
    }
    el.innerHTML = head + dots + `<div class="wrap sg-wiz fade">${body}</div>
      <div class="cta"><div class="two"><button type="button" class="btn ghost back" id="prev" aria-label="${esc(T("back"))}">${icon("back")}</button>
        <button type="button" class="btn" id="next">${step === 3 ? `${icon("sparkle", "s")}${esc(T("song.write"))}` : esc(T("continue"))}</button></div></div>`;
    const go = (n) => App.replace("song_new", { step: n });
    $("#bk").onclick = App.back;
    $("#prev").onclick = () => (step ? go(step - 1) : App.back());
    const name = $("#wName");
    if (name) name.oninput = () => { name.classList.remove("bad"); wiz.recipient = name.value; saveW(); };
    $$("[data-rel]", el).forEach((b) => (b.onclick = () => {
      haptic(); wiz.relation = b.dataset.rel; saveW();
      $$("[data-rel]", el).forEach((x) => x.setAttribute("aria-pressed", x === b));
    }));
    $$("[data-occ]", el).forEach((b) => (b.onclick = () => {
      haptic(); wiz.occasion = b.dataset.occ; saveW();
      $$("[data-occ]", el).forEach((x) => x.setAttribute("aria-pressed", x === b));
      setTimeout(() => { if (App.current().p === p) go(2); }, 220);
    }));
    $$("[data-q]", el).forEach((t) => (t.oninput = () => { wiz.answers[t.dataset.q] = t.value; saveW(); }));
    $$("[data-style]", el).forEach((b) => (b.onclick = () => {
      haptic();
      const was = wiz.style === "custom";
      wiz.style = b.dataset.style; saveW();
      if (was !== (wiz.style === "custom")) { App.render(); if (wiz.style === "custom") setTimeout(() => { const j = $("#wJanr"); if (j) j.focus(); }, 60); return; }
      $$("[data-style]", el).forEach((x) => x.setAttribute("aria-pressed", x === b));
    }));
    const janr = $("#wJanr");
    if (janr) janr.oninput = () => { janr.classList.remove("bad"); wiz.answers.janr = janr.value; saveW(); };
    $$("[data-voice]", el).forEach((b) => (b.onclick = () => {
      haptic(); wiz.voice = b.dataset.voice; saveW();
      $$("[data-voice]", el).forEach((x) => x.setAttribute("aria-pressed", x === b));
    }));
    const need = (key, inp) => { notify("error"); toast(T(key)); if (inp) { inp.classList.add("bad"); inp.focus(); } };
    $("#next").onclick = async () => {
      haptic();
      if (step === 0) {
        wiz.recipient = (wiz.recipient || "").trim();
        if (!wiz.recipient) return need("song.need_name", name);
        if (!wiz.relation) return need("song.need_rel");
        return go(1);
      }
      if (step === 1) return wiz.occasion ? go(2) : need("song.need_occ");
      if (step === 2) {
        if (!String(wiz.answers.istak || "").trim() && !(await App.confirmBox(T("song.istak_q")))) { const t = $('[data-q="istak"]'); if (t) t.focus(); return; }
        return go(3);
      }
      if (!wiz.style) return need("song.need_style");
      if (wiz.style === "custom" && !String(wiz.answers.janr || "").trim()) return need("song.need_janr", janr);
      delete p.err;
      p.writing = true;
      writing(el, p);
      submit(p);
    };
  };

  /** «She'r yozilmoqda…» — so'rov 10–30 soniya davom etadi. */
  function writing(el, p) {
    App.chrome({ night: true });
    el.innerHTML = `<div class="queue sg-writing fade"><div class="head">${disc("xl rot")}
        <h1>${esc(T("song.writing"))}</h1><p>${esc(T("song.writing_s", { name: (wiz && wiz.recipient) || "" }))}</p></div>
      ${eqBars(28)}
      <ol class="qsteps">${["song.w1", "song.w2", "song.w3"].map((k, i) => `<li class="${i ? "" : "on"}"><span></span>${esc(T(k))}</li>`).join("")}</ol>
      <p class="foot">${esc(T("song.writing_foot"))}</p></div>`;
    const items = $$(".qsteps li", el);
    const timers = [7000, 16000].map((ms, i) => setTimeout(() => {
      if (!items[i] || !items[i].isConnected) return;
      items[i].className = "ok"; items[i].firstElementChild.innerHTML = icon("check", "xs");
      if (items[i + 1]) items[i + 1].className = "on";
    }, ms));
    App.onLeave(() => timers.forEach(clearTimeout));
  }
  async function submit(p) {
    const w = wiz;
    const answers = Object.fromEntries(Object.entries(w.answers || {}).map(([k, v]) => [k, String(v || "").trim()])
      .filter(([k, v]) => v && (k !== "janr" || w.style === "custom")));
    try {
      const song = await api("/api/songs", { recipient: w.recipient.trim(), relation: w.relation, occasion: w.occasion, style: w.style, voice: w.voice, answers });
      store.del(DKEY); wiz = null;
      remember(song);
      notify("success");
      if (App.current().p === p) App.replace("song", { id: song.id, song });
      else toast(T("song.lyrics_ready", { name: song.title || song.recipient }), 4000);
    } catch (e) {
      p.writing = false;
      if (e.status === 503 && S.sm) S.sm.on = false;
      p.err = errMsg(e);
      notify("error");
      if (App.current().p === p) App.render();
    }
  }

  // ---------------------------------------------------------------- qo'shiq matni
  function lyricsHtml(text) {
    const secs = [];
    let cur = null;
    String(text || "").replace(/\r/g, "").split("\n").forEach((raw) => {
      const line = raw.trim();
      const m = line.match(/^\[(.{1,30})\]$/);
      if (m) { cur = { head: m[1], lines: [] }; secs.push(cur); return; }
      if (!line) return;
      if (!cur) { cur = { head: "", lines: [] }; secs.push(cur); }
      cur.lines.push(line);
    });
    const isChorus = (h) => /naqorat|chorus|qaytarma/i.test(h);
    return `<div class="lyr">${secs.map((s) => `<div class="ly-sec${isChorus(s.head) ? " ch" : ""}">${s.head ? `<span class="ly-h">${esc(s.head)}</span>` : ""}
      ${s.lines.length ? `<p>${s.lines.map(esc).join("<br>")}</p>` : `<p class="ly-inst">♪ ${esc(T("song.instr"))}</p>`}</div>`).join("")}</div>`;
  }

  // ---------------------------------------------------------------- qo'shiq sahifasi
  App.views.song = (p, el) => {
    App.chrome({ night: true });
    let song = p.song || (S.songs || []).find((x) => x.id === p.id) || null;
    delete p.song;
    let timer = null, stopped = false;
    const onVis = () => { if (document.visibilityState === "visible") tick(); };
    document.addEventListener("visibilitychange", onVis);
    App.onLeave(() => { stopped = true; clearTimeout(timer); stopPlayers(); document.removeEventListener("visibilitychange", onVis); });

    let drawnWithMeta = false;
    const sig = (s) => s && [s.status, s.lyrics, s.title, s.preview, s.chosen, s.site, s.error, (s.variants || []).length].join("|");
    async function tick() {
      clearTimeout(timer);
      if (stopped) return;
      try {
        const [fresh] = await Promise.all([api(`/api/songs/${p.id}`), S.sm ? Promise.resolve(S.sm) : App.songMeta()]);
        if (stopped) return;
        const before = song;
        song = fresh; remember(fresh);
        if (!before || sig(before) !== sig(fresh) || !drawnWithMeta) {
          if (before && before.busy && !fresh.busy) notify(fresh.error ? "error" : "success");
          if (before && !before.paid && fresh.paid) App.refreshMe().catch(() => {});
          draw();
        }
      } catch (e) {
        if (stopped) return;
        if (!song) { el.innerHTML = `<div class="bar"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button></div>
          <div class="wrap" style="padding-top:20px">${App.errBox(e.status === 404 ? T("song.not_found") : e)}</div>`; $("#bk").onclick = App.back; return; }
      }
      // ishlanayotgan bo'lsa — har 4 soniyada; to'lov kutilayotgan bo'lsa — sekinroq
      if (song && song.busy) timer = setTimeout(tick, 4000);
      else if (song && !song.paid && p.awaitPay && Date.now() - p.awaitPay < 15 * 60000) timer = setTimeout(tick, 8000);
    }

    function draw() {
      stopPlayers();
      drawnWithMeta = !!S.sm;
      const s = song, m = S.sm || {};
      const price = s.paid ? s.price : m.price || 0;
      const st = s.status;
      const stepCls = (i) => {
        const at = st === "lyrics" ? 0 : st.startsWith("preview") ? (st === "preview_ready" ? 2 : 1) : st === "ready" ? 3 : 2;
        return i < at ? "ok" : i === at ? "on" : "";
      };
      const janr = s.style === "custom" && s.answers && s.answers.janr;
      const tags = [janr ? String(janr).slice(0, 40) : s.style ? styleName(s.style) : "", s.voice ? voiceName(s.voice) : ""].filter(Boolean);
      const hero = `<div class="bar"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button>
          <div class="ttl"></div><button type="button" class="icon-btn" id="toList" aria-label="${esc(T("song.mine"))}">${icon("music")}</button></div>
        <header class="sg-hero"><div class="row">${disc(s.busy ? "lg rot" : "lg")}
          <div><span class="kick">${esc(T("song.title"))}</span><h1>${esc(songTitle(s))}</h1>
            <p>${esc([T("song.for", { name: s.recipient }), s.occasion ? occName(s.occasion) : ""].filter(Boolean).join(" · "))}</p></div></div>
          ${tags.length ? `<div class="sg-tags">${tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div>` : ""}
          <ol class="sg-steps">${["song.steps1", "song.steps2", "song.steps3"].map((k, i) => `<li class="${stepCls(i)}">${esc(T(k))}</li>`).join("")}</ol></header>`;
      const editable = !s.paid && !s.busy;
      const lyrCard = (edit) => `<section class="card sg-lyr"><div class="card-h"><h2>${esc(T("song.lyrics"))}</h2></div>
          ${edit ? `<div class="sg-acts"><button type="button" class="act" id="edBtn">${icon("edit", "s")}${esc(T("song.edit"))}</button>
            <button type="button" class="act pink" id="aiBtn">${icon("sparkle", "s")}${esc(T("song.ai"))}</button></div>` : ""}
          ${lyricsHtml(s.lyrics)}</section>`;
      const gen = (t, sub) => `<section class="sg-gen" role="status">${eqBars(26)}<h2>${esc(t)}</h2><p>${esc(sub)}</p>
        <button type="button" class="btn line sm" id="toChat">${esc(T("song.close_ok"))}</button></section>`;
      let body = "", cta = "";
      if (s.error && st !== "failed" && !s.busy) body += App.errBox(s.error);
      if (st === "lyrics") {
        body += lyrCard(true) + `<p class="hint" style="text-align:center">${esc(T("song.lyrics_hint"))}</p>`;
        const free = (m.free_previews || 0) > 0;
        cta = free ? `<button type="button" class="btn" id="pvBtn">${icon("headphones", "s")}${esc(T("song.listen", { n: m.preview_seconds || 20 }))}</button>
            <button type="button" class="link sg-buy" id="buyBtn">${esc(T("song.buy_now", { sum: money(price) }))}</button>`
          : `<button type="button" class="btn" id="buyBtn">${esc(T("song.buy", { sum: money(price) }))}</button><small class="warn">${esc(T("song.free_used"))}</small>`;
      } else if (st === "preview_queued" || st === "preview_gen") {
        body += gen(T("song.gen_preview"), T("song.gen_preview_s")) + lyrCard(false);
      } else if (st === "preview_ready") {
        body += `<section class="card sg-pv"><div class="card-h"><h2>${icon("headphones", "s")}${esc(T("song.preview_t", { n: m.preview_seconds || 20 }))}</h2></div>
            ${s.preview ? playerHtml(s.preview, T("song.preview_t", { n: m.preview_seconds || 20 })) : ""}
            <p class="sg-pv-note">${esc(T("song.preview_note", { sum: money(price) }))}</p>
            <ul class="sg-get">${["song.get1", "song.get2", "song.get3"].map((k) => `<li>${icon("check", "s")}${esc(T(k))}</li>`).join("")}</ul></section>`
          + lyrCard(editable);
        cta = `<button type="button" class="btn" id="buyBtn">${esc(T("song.buy_full", { sum: money(price) }))}</button>
          <small>${esc(T("song.balance", { balance: money(m.balance != null ? m.balance : ((S.me.quota || {}).balance || 0)) }))}</small>`;
      } else if (st === "paid_queued" || st === "paid_gen") {
        body += gen(T("song.gen_full"), T("song.gen_full_s")) + lyrCard(false);
      } else if (st === "failed") {
        body += `<section class="card sg-fail" role="alert"><span class="ic">${icon("refresh")}</span><h2>${esc(T("song.failed_t"))}</h2>
            ${s.error ? `<p class="err">${esc(s.error)}</p>` : ""}<p class="hint">${esc(T(s.paid ? "song.failed_s" : "song.failed_s2"))}</p>
            ${s.paid ? `<button type="button" class="btn" id="retryBtn">${icon("refresh", "s")}${esc(T("retry"))}</button>` : ""}</section>` + lyrCard(false);
      } else if (st === "ready") {
        const siteRow = s.site ? (S.me.sites || []).find((x) => x.slug === s.site) : null;
        body += `<div class="sg-ready"><h2>${esc(T("song.ready_t"))}</h2><p>${esc(T("song.ready_s"))}</p></div>
          ${s.variants.map((f, i) => `<section class="sg-var${i === s.chosen ? " on" : ""}" data-var="${i}"><div class="vh"><b>${esc(T("song.variant", { n: i + 1 }))}</b>
              <span class="vstate">${i === s.chosen ? `<span class="badge green">${icon("check", "xs")}${esc(T("song.chosen"))}</span>`
                : `<button type="button" class="btn ghost xs" data-choose="${i}">${esc(T("song.choose"))}</button>`}</span></div>
              ${playerHtml(f, T("song.variant", { n: i + 1 }))}</section>`).join("")}
          <div class="tools sg-tools">
            <button type="button" id="toSite">${icon("globe")}<b>${esc(T("song.to_site"))}</b><small>${esc(T("song.to_site_s"))}</small></button>
            <button type="button" id="toVideo">${icon("video")}<b>${esc(T("song.to_video"))}</b><small>${esc(T("song.to_video_s"))}</small></button>
            <button type="button" id="dlBtn">${icon("download")}<b>${esc(T("song.download"))}</b><small>${esc(T("song.download_s"))}</small></button>
            <button type="button" id="shBtn">${icon("share")}<b>${esc(T("share"))}</b><small>${esc(T("song.share_s"))}</small></button></div>
          ${s.site ? `<div class="note sg-onsite">${icon("check", "s")}<span>${esc(T("song.on_site", { name: siteName(siteRow) || s.site }))}</span>
            ${siteRow ? `<button type="button" class="link" id="openSite">${esc(T("open"))}</button>` : ""}</div>` : ""}
          ${lyrCard(false)}`;
      }
      el.innerHTML = hero + `<div class="wrap stack fade sg-body">${body}${cta ? '<div style="height:28px"></div>' : ""}</div>` + (cta ? `<div class="cta">${cta}</div>` : "");
      App.chrome({ night: true, cta: !!cta });
      bindPlayers(el);
      const on = (id, fn) => { const b = $("#" + id, el); if (b) b.onclick = fn; };
      on("bk", App.back);
      on("toList", () => { haptic(); App.go("songs"); });
      on("toChat", () => App.closeApp());
      on("pvBtn", (e) => preview(e.currentTarget));
      on("buyBtn", (e) => pay(e.currentTarget));
      on("edBtn", () => guardReset(editSheet));
      on("aiBtn", () => guardReset(aiSheet));
      on("retryBtn", (e) => retry(e.currentTarget));
      on("toSite", () => { haptic(); siteSheet(); });
      on("toVideo", () => { haptic(); toVideo(); });
      on("dlBtn", () => { haptic(); download(); });
      on("shBtn", () => { haptic(); App.shareUrl(absUrl(s.file), T("song.share_text", { title: songTitle(s), name: s.recipient })); });
      on("openSite", () => { const r = (S.me.sites || []).find((x) => x.slug === s.site); if (r) App.openLink(r.public || r.url); });
      $$("[data-choose]", el).forEach((b) => (b.onclick = () => choose(+b.dataset.choose, b)));
    }
    const siteName = (x) => {
      if (!x) return "";
      const t = S.cm.templates.find((y) => y.id === x.template);
      return [x.to, t ? App.tx("tpl." + t.id, t.name) : x.to ? "" : x.title].filter(Boolean).join(" — ");
    };

    // --- amallar
    const fail = (e) => { notify("error"); toast(errMsg(e)); };
    async function preview(btn) {
      App.busy(btn, true);
      try {
        song = await api(`/api/songs/${song.id}/preview`, {}); remember(song);
        if (S.sm && song.status !== "lyrics") S.sm.free_previews = Math.max(0, (S.sm.free_previews || 1) - 1);
        notify("success"); draw(); tick();
      } catch (e) {
        App.busy(btn, false);
        if (e.status === 402 && e.detail && e.detail.code === "preview_limit") {
          if (S.sm) { S.sm.free_previews = 0; if (e.detail.price) S.sm.price = e.detail.price; }
          draw(); limitSheet();
        } else fail(e);
      }
    }
    async function pay(btn) {
      const price = (S.sm && S.sm.price) || 0;
      App.busy(btn, true);
      try {
        song = await api(`/api/songs/${song.id}/pay`, {}); remember(song);
        notify("success"); toast(T("song.paid"), 3200);
        App.refreshMe().catch(() => {}); App.songMeta(true).catch(() => {});
        draw(); tick();
      } catch (e) {
        App.busy(btn, false);
        if (e.status === 402 && e.detail && e.detail.code === "paywall") {
          const d = e.detail, need = d.need || price, bal = d.balance || 0;
          App.topupSheet({ song: song.id, need: Math.max(0, need - bal), title: T("sites.need_title"),
            text: T("song.need_text", { sum: money(need), balance: money(bal) }), onSent: () => { p.awaitPay = Date.now(); tick(); } });
          p.awaitPay = Date.now(); clearTimeout(timer); timer = setTimeout(tick, 8000);
        } else fail(e);
      }
    }
    async function retry(btn) {
      App.busy(btn, true);
      try { song = await api(`/api/songs/${song.id}/retry`, {}); remember(song); draw(); tick(); }
      catch (e) { App.busy(btn, false); fail(e); }
    }
    async function choose(i, btn) {
      App.busy(btn, true);
      try {
        song = await api(`/api/songs/${song.id}/choose`, { index: i }); remember(song);
        haptic("medium");
        // pleyer to'xtamasin — faqat belgini almashtiramiz
        $$("[data-var]", el).forEach((card) => {
          const k = +card.dataset.var, onNow = k === song.chosen;
          card.classList.toggle("on", onNow);
          $(".vstate", card).innerHTML = onNow ? `<span class="badge green">${icon("check", "xs")}${esc(T("song.chosen"))}</span>`
            : `<button type="button" class="btn ghost xs" data-choose="${k}">${esc(T("song.choose"))}</button>`;
        });
        $$("[data-choose]", el).forEach((b) => (b.onclick = () => choose(+b.dataset.choose, b)));
        if (song.site) toast(T("song.site_updated"));
      } catch (e) { App.busy(btn, false); fail(e); }
    }
    function limitSheet() {
      const price = (S.sm && S.sm.price) || 0;
      const sh = App.sheet(`<div class="sh-head"><span class="sh-ic">${icon("headphones")}</span><div><h1>${esc(T("song.limit_t"))}</h1>
          <p>${esc(T("song.limit_s"))}</p></div></div>
        <button type="button" class="btn" id="lmBuy">${esc(T("song.buy", { sum: money(price) }))}</button>
        <button type="button" class="btn ghost" id="lmLater">${esc(T("close"))}</button>`, { label: T("song.limit_t") });
      $("#lmBuy", sh.el).onclick = (e) => { sh.close(); pay(e.currentTarget); };
      $("#lmLater", sh.el).onclick = () => sh.close();
    }
    async function guardReset(open) {
      haptic();
      if (song.preview && !(await App.confirmBox(T("song.reset_q")))) return;
      open();
    }
    function editSheet() {
      const sh = App.sheet(`<div class="sh-head"><span class="sh-ic">${icon("edit")}</span><div><h1>${esc(T("song.edit_t"))}</h1>
          <p>${esc(T("song.edit_hint"))}</p></div></div>
        <label class="field">${esc(T("song.name_title"))}<input id="seTitle" maxlength="120" value="${esc(song.title || "")}"></label>
        <textarea id="seText" class="sg-ed" rows="14" maxlength="4000" aria-label="${esc(T("song.lyrics"))}">${esc(song.lyrics || "")}</textarea>
        <div id="seErr"></div>
        <button type="button" class="btn" id="seSave">${esc(T("save"))}</button>`, { label: T("song.edit_t") });
      $("#seSave", sh.el).onclick = async (e) => {
        const text = $("#seText", sh.el).value, title = $("#seTitle", sh.el).value.trim();
        if (text.trim() === String(song.lyrics || "").trim() && title === (song.title || "")) { sh.close(); return; }
        App.busy(e.currentTarget, true);
        try {
          song = await api(`/api/songs/${song.id}/lyrics`, { text, ...(title ? { title } : {}) }); remember(song);
          sh.close(); notify("success"); toast(T("song.saved")); draw();
        } catch (err) { App.busy(e.currentTarget, false); notify("error"); $("#seErr", sh.el).innerHTML = App.errBox(errMsg(err)); }
      };
    }
    function aiSheet() {
      const ideas = ["song.ai_i1", "song.ai_i2", "song.ai_i3", "song.ai_i4", "song.ai_i5"];
      const sh = App.sheet(`<div class="sh-head"><span class="sh-ic" style="background:var(--atlas-soft);color:var(--atlas)">${icon("sparkle")}</span><div>
          <h1>${esc(T("song.ai_t"))}</h1><p>${esc(T("song.ai_s"))}</p></div></div>
        <div class="chips">${ideas.map((k) => `<button type="button" class="chip" data-idea="${k}" aria-pressed="false">${esc(T(k))}</button>`).join("")}</div>
        <textarea id="aiText" rows="3" maxlength="500" placeholder="${esc(T("song.ai_ph"))}" aria-label="${esc(T("song.ai_t"))}"></textarea>
        <div id="aiErr"></div>
        <button type="button" class="btn" id="aiGo">${icon("sparkle", "s")}${esc(T("song.ai_go"))}</button>
        <p class="hint" style="text-align:center">${esc(T("song.ai_note"))}</p>`, { label: T("song.ai_t") });
      const ta = $("#aiText", sh.el);
      $$("[data-idea]", sh.el).forEach((b) => (b.onclick = () => {
        haptic();
        const on = b.getAttribute("aria-pressed") !== "true";
        b.setAttribute("aria-pressed", on);
        const picked = $$('[data-idea][aria-pressed="true"]', sh.el).map((x) => x.textContent.trim());
        const own = ta.value.split(/,\s*/).map((x) => x.trim()).filter((x) => x && !ideas.some((k) => T(k) === x));
        ta.value = [...picked, ...own].join(", ");
      }));
      $("#aiGo", sh.el).onclick = async (e) => {
        const instruction = ta.value.trim();
        if (!instruction) { notify("error"); ta.classList.add("bad"); ta.focus(); return; }
        App.busy(e.currentTarget, true, T("song.ai_busy"));
        try {
          song = await api(`/api/songs/${song.id}/lyrics`, { instruction }); remember(song);
          sh.close(); notify("success"); draw();
        } catch (err) { App.busy(e.currentTarget, false); notify("error"); $("#aiErr", sh.el).innerHTML = App.errBox(errMsg(err)); }
      };
    }
    function siteSheet() {
      const paid = (S.me.sites || []).filter((x) => x.paid);
      if (!paid.length) {
        const sh = App.sheet(`<div class="sh-head"><span class="sh-ic">${icon("globe")}</span><div><h1>${esc(T("song.site_t"))}</h1>
            <p>${esc(T("song.site_none"))}</p></div></div>
          <button type="button" class="btn" id="mkSite">${esc(T("song.site_make"))}</button>
          ${(S.me.sites || []).length ? `<button type="button" class="btn ghost" id="mySites">${esc(T("done.mine"))}</button>` : ""}`);
        $("#mkSite", sh.el).onclick = () => { sh.close(); App.tab("sites"); };
        const ms = $("#mySites", sh.el); if (ms) ms.onclick = () => { sh.close(); App.tab("sites", { mine: true }); };
        return;
      }
      const sh = App.sheet(`<div class="sh-head"><span class="sh-ic">${icon("globe")}</span><div><h1>${esc(T("song.site_t"))}</h1>
          <p>${esc(T("song.site_s", { n: song.chosen + 1 }))}</p></div></div>
        <ul class="glist">${paid.map((x) => `<li><button type="button" data-site="${esc(x.slug)}"><span class="ini" style="background:var(--night)">${icon("globe", "s")}</span>
          <span class="who"><b>${esc(siteName(x))}</b><small>${esc(x.slug === song.site ? T("song.site_now") : T("song.site_pick"))}</small></span>
          ${x.slug === song.site ? `<span class="badge green">${icon("check", "xs")}</span>` : icon("chev")}</button></li>`).join("")}</ul>`, { label: T("song.site_t") });
      $$("[data-site]", sh.el).forEach((b) => (b.onclick = async () => {
        haptic();
        b.disabled = true;
        try {
          song = await api(`/api/songs/${song.id}/attach`, { site: b.dataset.site }); remember(song);
          sh.close(); notify("success"); toast(T("song.site_done")); draw();
        } catch (e) { b.disabled = false; fail(e); }
      }));
    }
    function toVideo() {
      const mus = App.songMusic(song);
      const d = App.Draft.get();
      const dz = d && S.vm.designs.find((x) => x.id === d.design);
      const fresh = () => { store.put(PEND, mus); App.tab("videos"); toast(T("song.video_pick"), 3500); };
      if (!dz) { fresh(); return; }
      const sh = App.sheet(`<div class="sh-head"><span class="sh-ic">${icon("video")}</span><div><h1>${esc(T("song.video_t"))}</h1>
          <p>${esc(T("song.video_s"))}</p></div></div>
        <button type="button" class="btn" id="vCur">${esc(T("song.video_cur", { name: App.tx("d." + dz.id, dz.name) }))}</button>
        <button type="button" class="btn ghost" id="vNew">${esc(T("song.video_new"))}</button>`, { label: T("song.video_t") });
      $("#vCur", sh.el).onclick = () => { d.music = mus; App.Draft.set(d); sh.close(); App.go("editor", { design: d.design, keep: true }); };
      $("#vNew", sh.el).onclick = () => { sh.close(); fresh(); };
    }
    function download() {
      const url = absUrl(song.file), name = `${songTitle(song)} — ${song.chosen + 1}.mp3`;
      const tg = App.tg;
      try {
        if (tg && tg.downloadFile && tg.isVersionAtLeast && tg.isVersionAtLeast("8.0")) { tg.downloadFile({ url, file_name: name }); return; }
      } catch { /* eski Telegram */ }
      App.openLink(url);
    }

    if (song) draw();
    else {
      el.innerHTML = `<div class="bar"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button></div>
        <header class="sg-hero"><div class="row">${disc("lg rot")}<div><span class="kick">${esc(T("song.title"))}</span><h1>${esc(T("loading"))}</h1></div></div></header>`;
      $("#bk").onclick = App.back;
    }
    tick();
  };
})();
