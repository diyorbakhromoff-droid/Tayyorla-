/* Taklifnomalar: tadbirlar, mehmonlar ro'yxati, javoblar, shaxsiy videolar paketi va tadbir vositalari */
(() => {
  "use strict";
  const { $, $$, esc, T, icon, S, api, haptic, notify, toast, money } = App;

  const whenLine = (e) => {
    const parts = [e.who ? e.title : ""];
    if (e.date) parts.push(App.fmtDate(e.date, { weekday: true }) + (e.date2 ? ` – ${App.fmtDate(e.date2)}` : ""));
    if (e.time) parts.push(e.time);
    return parts.filter(Boolean).join(", ");
  };
  function rsvpBar(st) {
    const total = Math.max(st.invited, st.yes + st.no);
    if (!total) return "";
    const y = Math.round((st.yes / total) * 100), n = Math.round((st.no / total) * 100);
    const wait = Math.max(0, total - st.yes - st.no);
    return `<div class="rsvp-bar" role="img" aria-label="${esc(T("ev.bar_label", { y: st.yes, n: st.no, w: wait }))}"><span class="y" style="width:${y}%"></span><span class="n" style="width:${n}%"></span></div>
      <div class="legend"><span><i class="y"></i>${esc(T("ev.yes_n", { n: st.yes }))}</span><span><i class="n"></i>${esc(T("ev.no_n", { n: st.no }))}</span><span><i></i>${esc(T("ev.wait_n", { n: wait }))}</span></div>`;
  }

  // ---------------------------------------------------------------- Taklifnomalar bo'limi
  App.views.events = (p, el) => {
    App.chrome({ tabs: true });
    const kind = p.kind === "video" ? "video" : "site";
    el.innerHTML = `
      <header class="page-head"><h1>${esc(T("ev.title"))}</h1><p>${esc(T("ev.sub"))}</p>
        <div class="seg" role="tablist" style="margin-top:8px">
          <button type="button" role="tab" data-k="site" aria-selected="${kind === "site"}">${esc(App.tx("ev.k_site", "Sayt taklifnoma"))}</button>
          <button type="button" role="tab" data-k="video" aria-selected="${kind === "video"}">${esc(App.tx("ev.k_video", "Video taklifnoma"))}</button></div></header>
      <div id="invCat" class="fade"></div>
      <section class="sec"><div class="sec-h"><h2>${esc(T("ev.mine"))}</h2></div><div class="stack" id="evList"><div class="empty"><span class="spin"></span></div></div></section>
      <section class="sec"><div class="sec-h"><h2>${esc(T("ev.can"))}</h2></div><div class="stack">
        <div class="feat"><span class="ic">${icon("video")}</span><span><b>${esc(T("ev.can1_t"))}</b>${esc(T("ev.can1_s"))}</span></div>
        <div class="feat"><span class="ic g">${icon("check")}</span><span><b>${esc(T("ev.can2_t"))}</b>${esc(T("ev.can2_s"))}</span></div>
        <div class="feat"><span class="ic y">${icon("qr")}</span><span><b>${esc(T("ev.can3_t"))}</b>${esc(T("ev.can3_s"))}</span></div></div></section>`;
    $$("[data-k]", el).forEach((b) => (b.onclick = () => { haptic(); p.kind = b.dataset.k; App.render(); }));
    const cat = $("#invCat");
    if (kind === "site") {
      App.siteCatalog(cat, "toy", p);
      cat.insertAdjacentHTML("beforeend", `<div class="wrap" style="padding-top:16px"><button type="button" class="banner" id="fromVideo">${icon("video")}<span><b>${esc(T("sites.from_video_t"))}</b>${esc(T("sites.from_video_s"))}</span>${icon("chev")}</button></div>`);
      $("#fromVideo").onclick = () => { haptic(); App.pickEventForSite(); };
    } else {
      cat.innerHTML = `<div class="wrap" style="padding-top:16px"><ol class="steps3">
          <li><span>1</span>${esc(T("videos.step1"))}</li><li><span>2</span>${esc(T("videos.step2"))}</li><li><span>3</span>${esc(T("videos.step3"))}</li></ol></div>
        <div class="wrap" style="padding-top:16px">${App.videoGrid(S.vm.designs.filter((d) => d.section === "toy"))}</div>`;
      $$("[data-design]", cat).forEach((b) => (b.onclick = () => { haptic(); App.Draft.set(null); App.go("editor", { design: b.dataset.design }); }));
    }
    const box = $("#evList");
    api("/api/events").then(({ events }) => {
      if (!box.isConnected) return;
      if (!events.length) { box.innerHTML = `<div class="empty"><b>${esc(T("ev.none"))}</b>${esc(T("ev.none_sub"))}</div>`; return; }
      box.innerHTML = events.map((e) => {
        const left = App.daysTo(e.date);
        const st = e.stats || { invited: 0, yes: 0, no: 0 };
        const chips = [e.kind === "video" ? T("ev.f_video") : "", e.site_slug || e.kind === "site" ? T("ev.f_site") : "", st.invited ? T("ev.guests_n", { n: st.invited }) : ""].filter(Boolean);
        return `<button type="button" class="ev" data-slug="${esc(e.slug)}">
          <span class="top"><span><b>${esc(e.who || e.title)}</b><small>${esc(whenLine(e))}</small></span>
            ${left != null && left >= 0 ? `<span class="badge ${left <= 7 ? "pink" : "lilac"}">${esc(App.leftText(left))}</span>` : ""}</span>
          ${st.invited || st.yes || st.no ? rsvpBar(st) : `<span class="hint" style="font-size:13.5px;color:var(--ink2)">${esc(T("ev.add_guests_hint"))}</span>`}
          <span class="chips">${chips.map((c) => `<span class="badge lilac">${esc(c)}</span>`).join("")}</span></button>`;
      }).join("");
      $$("[data-slug]", box).forEach((b) => (b.onclick = () => { haptic(); App.go("event", { slug: b.dataset.slug }); }));
    }).catch((e) => { box.innerHTML = App.errBox(e); });
  };

  // ---------------------------------------------------------------- tadbir sahifasi
  const STATUS = { yes: ["y", "green", "ev.st_yes"], no: ["n", "rose", "ev.st_no"], opened: ["", "lilac", "ev.st_opened"], invited: ["", "lilac", "ev.st_invited"] };
  App.views.event = (p, el) => {
    App.chrome({ night: true });
    el.innerHTML = `<div class="bar"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button><div class="ttl"><b>${esc(T("ev.event"))}</b></div></div>
      <div class="empty"><span class="spin"></span></div>`;
    $("#bk").onclick = App.back;
    api(`/api/events/${encodeURIComponent(p.slug)}`).then((ev) => {
      if (App.current().p !== p) return;
      p.ev = ev;
      drawEvent(p, el, ev);
    }).catch((e) => { el.innerHTML += `<div class="wrap">${App.errBox(e)}</div>`; });
  };

  function drawEvent(p, el, ev) {
    const st = ev.stats;
    const tab = p.tab || "all";
    const guests = ev.guests || [];
    const by = (k) => guests.filter((g) => (k === "wait" ? !["yes", "no"].includes(g.status) : g.status === k));
    const shown = tab === "all" ? guests : by(tab);
    const vids = guests.filter((g) => g.video);
    const vDone = vids.filter((g) => g.video === "done").length;
    const making = vids.length && vDone < vids.length;
    const allLabel = making ? T("ev.videos_making", { done: vDone, n: vids.length }) : vids.length && vDone === guests.length ? T("ev.videos_done") : T("ev.videos_all");
    const card = ev.edit && ev.edit.data && ev.edit.data.toyona && ev.edit.data.karta ? ev.edit.data : null;
    const place = [ev.venue, ev.edit && ev.edit.data && ev.edit.data.manzil].filter(Boolean).join(", ");
    el.innerHTML = `
      <div class="bar"><button type="button" class="icon-btn" id="bk" aria-label="${esc(T("back"))}">${icon("back")}</button><div class="ttl"><b>${esc(T("ev.event"))}</b></div>
        ${ev.has_video ? `<button type="button" class="icon-btn" id="edit" aria-label="${esc(T("ev.edit"))}">${icon("edit")}</button>` : ""}</div>
      <section class="ev-hero"><div><h1>${esc(ev.who || ev.title)}</h1><p>${esc(whenLine(ev))}${place ? "<br>" + esc(place) : ""}</p></div>
        <div class="kpis"><span><b>${st.invited}</b><small>${esc(T("ev.k_guests"))}</small></span><span><b>${st.opened}</b><small>${esc(T("ev.k_opened"))}</small></span>
          <span class="y"><b>${st.yes}</b><small>${esc(T("ev.k_yes", { n: st.people }))}</small></span><span><b>${st.no}</b><small>${esc(T("ev.k_no"))}</small></span></div></section>
      <div class="wrap stack fade" style="padding-top:16px">
        <div class="tiles3">
          <button type="button" class="tile" id="addG"><span class="ic night">${icon("plus")}</span>${esc(T("ev.add_guests"))}</button>
          <button type="button" class="tile" id="allV" ${ev.has_video ? "" : "disabled"}><span class="ic pink">${icon("video")}</span>${esc(allLabel)}</button>
          <button type="button" class="tile" id="shareEv"><span class="ic">${icon("share")}</span>${esc(T("share"))}</button></div>
        ${guests.length ? `<div class="chips scroll">${[["all", guests.length], ["yes", by("yes").length], ["no", by("no").length], ["wait", by("wait").length]]
          .map(([k, n]) => `<button type="button" class="chip" data-tab="${k}" aria-pressed="${tab === k}">${esc(T("ev.tab_" + k))} ${n}</button>`).join("")}</div>
          <ul class="glist">${shown.map((g) => {
            const s = STATUS[g.status] || STATUS.invited;
            const meta = [g.status === "yes" && g.people ? T("ev.people_n", { n: g.people }) : "", g.note ? `«${g.note}»` : "",
              g.video ? T("ev.v_" + (g.video === "done" ? "done" : g.video === "failed" ? "failed" : "making")) : "",
              g.status === "opened" ? T("ev.opened_no_answer") : g.status === "invited" ? T("ev.not_opened") : ""].filter(Boolean).join(", ");
            return `<li><button type="button" data-g="${g.id}"><span class="ini ${s[0]}">${esc(App.initials(g.name))}</span>
              <span class="who"><b>${esc(g.name)}</b><small>${esc(meta)}</small></span><span class="badge ${s[1]}">${esc(T(s[2]))}</span></button></li>`;
          }).join("") || `<li><div class="empty">${esc(T("ev.tab_empty"))}</div></li>`}</ul>`
          : `<div class="empty"><b>${esc(T("ev.no_guests"))}</b>${esc(T("ev.no_guests_sub"))}</div>`}
        ${ev.answers && ev.answers.length ? `<h2 style="font-size:21px;margin-top:6px">${esc(T("ev.other_answers"))}</h2>
          <ul class="glist">${ev.answers.map((a) => `<li><button type="button" tabindex="-1"><span class="ini ${a.attending ? "y" : "n"}">${esc(App.initials(a.name))}</span>
            <span class="who"><b>${esc(a.name || T("ev.anon"))}</b><small>${esc([a.attending && a.people ? T("ev.people_n", { n: a.people }) : "", a.note ? `«${a.note}»` : ""].filter(Boolean).join(", "))}</small></span>
            <span class="badge ${a.attending ? "green" : "rose"}">${esc(T(a.attending ? "ev.st_yes" : "ev.st_no"))}</span></button></li>`).join("")}</ul>` : ""}
        <h2 style="font-size:21px;margin-top:6px">${esc(T("ev.tools"))}</h2>
        <div class="tools">
          <button type="button" id="tQr">${icon("qr")}<b>${esc(T("ev.t_qr"))}</b><small>${esc(T("ev.t_qr_s"))}</small></button>
          <button type="button" id="tCal">${icon("cal")}<b>${esc(T("ev.t_cal"))}</b><small>${esc(T("ev.t_cal_s"))}</small></button>
          <button type="button" id="tCard">${icon("card")}<b>${esc(T("ev.t_card"))}</b><small>${esc(card ? `${String(card.karta).slice(0, 4)} •••• ${String(card.karta).slice(-4)}${card.karta_egasi ? ", " + card.karta_egasi : ""}` : T("ev.t_card_none"))}</small></button>
          <button type="button" id="tLinks">${icon("link")}<b>${esc(T("ev.t_links"))}</b><small>${esc(T("ev.t_links_s"))}</small></button>
          <button type="button" id="tPage">${icon("eye")}<b>${esc(T("ev.t_page"))}</b><small>${esc(T("ev.t_page_s"))}</small></button>
          ${ev.site_slug ? `<button type="button" id="tSite">${icon("globe")}<b>${esc(T("ev.t_site"))}</b><small>${esc(T(ev.paid ? "sites.live" : "sites.sample"))}</small></button>`
            : ev.section === "toy" && ev.has_video ? `<button type="button" id="tMkSite">${icon("globe")}<b>${esc(T("ev.t_mksite"))}</b><small>${esc(T("ev.t_mksite_s"))}</small></button>` : ""}
        </div></div>`;
    const on = (id, fn) => { const b = $("#" + id, el); if (b) b.onclick = (e) => { haptic(); fn(e); }; };
    on("bk", App.back);
    on("edit", () => App.go("editor", { event: ev.slug }));
    on("addG", () => guestsSheet(ev, p));
    on("allV", (e) => guestVideos(ev, p, e.currentTarget));
    on("shareEv", () => App.shareUrl(ev.url, T("ev.share_text", { title: ev.title })));
    on("tQr", () => qrSheet(ev));
    on("tCal", () => App.openLink(ev.ics));
    on("tCard", () => (card ? App.copyText(String(card.karta)) : ev.has_video && App.go("editor", { event: ev.slug })));
    on("tLinks", () => linksSheet(ev));
    on("tPage", () => App.openLink(ev.url));
    on("tSite", () => App.tab("sites", { mine: true }));
    on("tMkSite", () => App.tab("sites", { fromEvent: ev.slug }));
    $$("[data-tab]", el).forEach((b) => (b.onclick = () => { haptic(); p.tab = b.dataset.tab; drawEvent(p, el, ev); }));
    $$("[data-g]", el).forEach((b) => (b.onclick = () => { haptic(); guestSheet(ev, p, guests.find((g) => g.id === +b.dataset.g)); }));
  }
  const reload = async (p) => {
    const ev = await api(`/api/events/${encodeURIComponent(p.slug)}`);
    p.ev = ev;
    if (App.current().p === p) drawEvent(p, App.$("#view"), ev);
  };

  // ---------------------------------------------------------------- mehmonlarni qo'shish
  function guestsSheet(ev, p) {
    let video = ev.has_video, hurmat = !ev.plain_dear;
    const s = App.sheet(`
      <div class="sh-head"><div><h1>${esc(T("ga.title"))}</h1></div><button type="button" class="icon-btn" id="gx" aria-label="${esc(T("close"))}">${icon("close")}</button></div>
      <label class="field"><span style="display:flex;justify-content:space-between"><span>${esc(T("ga.one_per_line"))}</span><span style="color:var(--emerald-ink)" id="gCount"></span></span>
        <textarea id="gText" rows="7" placeholder="${esc(T("ga.ph"))}"></textarea></label>
      <div class="card stack">
        ${ev.has_video ? App.switchHtml("swV", T("ga.video"), T("ga.video_s"), video) : ""}
        ${App.switchHtml("swH", T("ga.hurmat"), T("ga.hurmat_s"), hurmat)}
        <p class="hint">${esc(T("ga.links_note"))}</p></div>
      <p class="note" id="gEx"></p>
      <button type="button" class="btn" id="gGo"></button>
      <p class="hint" style="text-align:center">${esc(T("ga.limit"))}</p>`, { label: T("ga.title") });
    const ta = $("#gText", s.el), go = $("#gGo", s.el);
    const names = () => ta.value.split(/[\n;]+/).map((x) => x.trim()).filter(Boolean);
    const sync = () => {
      const n = names().length;
      $("#gCount", s.el).textContent = T("ga.count", { n });
      $("#gEx", s.el).innerHTML = `${esc(T("ga.example"))} <b style="font:800 16px var(--f-display)">${esc((hurmat ? T("ga.dear", { name: names()[0] || T("ga.sample") }) : (names()[0] || T("ga.sample")) + "!"))}</b>`;
      go.textContent = video && ev.has_video ? T("ga.go_video", { n }) : T("ga.go", { n });
      go.disabled = !n;
    };
    ta.oninput = sync;
    App.bindSwitch($("#swV", s.el), (x) => { video = x; sync(); });
    App.bindSwitch($("#swH", s.el), (x) => { hurmat = x; sync(); });
    $("#gx", s.el).onclick = () => s.close();
    go.onclick = async () => {
      App.busy(go, true);
      try {
        const r = await api(`/api/events/${encodeURIComponent(ev.slug)}/guests`, { text: ta.value, plain: !hurmat });
        notify("success");
        toast(r.skipped ? T("ga.added_skip", { n: r.added, s: r.skipped }) : T("ga.added", { n: r.added }));
        s.close();
        await reload(p);
        if (video && ev.has_video) guestVideos(p.ev, p);
      } catch (e) { App.busy(go, false); toast(e.message); }
    };
    sync();
    setTimeout(() => ta.focus(), 300);
  }

  // ---------------------------------------------------------------- shaxsiy videolar (paket)
  function packageFor(n, pk) { return pk.find((x) => x.size >= n) || null; }
  async function guestVideos(ev, p, btn) {
    const guests = ev.guests || [];
    if (!guests.length) { guestsSheet(ev, p); return; }
    const todo = guests.filter((g) => !g.video || g.video === "failed").length;
    if (!todo) { toast(T("ev.videos_done")); return; }
    const pk = ev.packages || [];
    const need = packageFor(guests.length, pk);
    const paid = (ev.package && ev.package.paid) || 0;
    const cost = need ? Math.max(0, need.price - paid) : 0;
    const bal = (S.me.quota || {}).balance || 0;
    const s = App.sheet(`
      <div class="sh-head"><span class="sh-ic" style="background:var(--atlas-soft);color:var(--atlas)">${icon("video")}</span><div><h1>${esc(T("pk.title"))}</h1>
        <p>${esc(T("pk.text", { n: guests.length }))}</p></div></div>
      <div class="pkgs">${pk.map((x) => `<div class="${need && x.size === need.size ? "on" : ""}"><b>${esc(T("pk.size", { n: x.size }))}</b><small>${esc(money(x.price))}</small></div>`).join("")}</div>
      ${need ? `<div class="card"><div class="total"><span>${esc(paid ? T("pk.upgrade") : T("pk.your", { n: need.size }))}</span><b>${esc(money(cost))}</b></div>
        <p class="hint" style="margin-top:6px">${esc(T("pk.balance", { balance: money(bal) }))}</p></div>` : `<div class="err">${esc(T("err.max_guests", { n: pk.length ? pk[pk.length - 1].size : 300 }))}</div>`}
      ${need ? `<button type="button" class="btn" id="pkGo">${esc(cost <= bal ? (cost ? T("pk.pay", { sum: money(cost) }) : T("pk.start")) : T("pk.topup", { sum: money(cost - bal) }))}</button>` : ""}
      <p class="hint" style="text-align:center">${esc(T("pk.note"))}</p>`, { label: T("pk.title") });
    const go = $("#pkGo", s.el);
    if (go) go.onclick = async () => {
      if (cost > bal) {
        s.close();
        App.topupSheet({ need: cost - bal, title: T("pk.topup_t"), text: T("pk.topup_s", { sum: money(cost), balance: money(bal) }) });
        return;
      }
      App.busy(go, true);
      try {
        const r = await api(`/api/events/${encodeURIComponent(ev.slug)}/guest-videos`, {});
        notify("success");
        s.close();
        await App.refreshMe().catch(() => {});
        toast(T("pk.queued", { n: r.queued }), 4000);
        reload(p);
      } catch (e) {
        App.busy(go, false);
        if (e.status === 402 && e.detail && e.detail.code === "paywall") {
          s.close();
          App.topupSheet({ need: Math.max(0, e.detail.need - e.detail.balance), title: T("pk.topup_t"), text: T("pk.topup_s", { sum: money(e.detail.need), balance: money(e.detail.balance) }) });
        } else toast(e.message);
      }
    };
    if (btn) App.busy(btn, false);
  }

  // ---------------------------------------------------------------- bitta mehmon
  function guestSheet(ev, p, g) {
    if (!g) return;
    const s = App.sheet(`
      <div class="sh-head"><div><h1>${esc(g.name)}</h1><p>${esc(T((STATUS[g.status] || STATUS.invited)[2]))}${g.people ? ", " + esc(T("ev.people_n", { n: g.people })) : ""}</p></div></div>
      ${g.note ? `<p class="quote">«${esc(g.note)}»</p>` : ""}
      <div class="card"><p class="hint" style="margin-bottom:6px">${esc(T("gs.link"))}</p><p style="font-size:13px;word-break:break-all">${esc(g.url)}</p></div>
      <button type="button" class="btn" id="gsShare">${icon("send", "s")}${esc(T("gs.send"))}</button>
      <button type="button" class="btn ghost" id="gsCopy">${icon("copy", "s")}${esc(T("gs.copy"))}</button>
      <button type="button" class="btn ghost" id="gsDel" style="color:var(--rose-ink)">${icon("trash", "s")}${esc(T("gs.delete"))}</button>`);
    $("#gsShare", s.el).onclick = () => App.shareUrl(g.url, T("gs.share_text", { name: g.name, title: ev.title }));
    $("#gsCopy", s.el).onclick = () => App.copyText(g.url);
    $("#gsDel", s.el).onclick = async () => {
      if (!(await App.confirmBox(T("gs.delete_q", { name: g.name })))) return;
      try { await api(`/api/events/${encodeURIComponent(ev.slug)}/guests/${g.id}`, null, { method: "DELETE" }); s.close(); reload(p); }
      catch (e) { toast(e.message); }
    };
  }

  function qrSheet(ev) {
    const s = App.sheet(`<div class="sh-head"><div><h1>${esc(T("ev.t_qr"))}</h1><p>${esc(T("qr.text"))}</p></div></div>
      <div class="qr-box"><img src="/api/qr?text=${encodeURIComponent(ev.url)}" alt="${esc(T("ev.t_qr"))}"></div>
      <p class="hint" style="text-align:center;word-break:break-all">${esc(ev.url)}</p>
      <button type="button" class="btn ghost" id="qrCopy">${icon("copy", "s")}${esc(T("gs.copy"))}</button>
      <button type="button" class="btn ghost" id="qrOpen">${icon("eye", "s")}${esc(T("qr.open"))}</button>`);
    $("#qrCopy", s.el).onclick = () => App.copyText(ev.url);
    $("#qrOpen", s.el).onclick = () => App.openLink(`${location.origin}/api/qr?text=${encodeURIComponent(ev.url)}`);
  }

  function linksSheet(ev) {
    const guests = ev.guests || [];
    const text = guests.map((g) => `${g.name}: ${g.url}`).join("\n");
    const s = App.sheet(`<div class="sh-head"><div><h1>${esc(T("ev.t_links"))}</h1><p>${esc(T("links.text"))}</p></div></div>
      ${guests.length ? `<textarea readonly rows="8" style="font-size:12.5px">${esc(text)}</textarea>
        <button type="button" class="btn" id="lkCopy">${icon("copy", "s")}${esc(T("links.copy_all"))}</button>` : `<div class="empty">${esc(T("ev.no_guests_sub"))}</div>`}`);
    const c = $("#lkCopy", s.el); if (c) c.onclick = () => App.copyText(text);
  }
})();
