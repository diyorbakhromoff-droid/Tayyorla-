(() => {
  const S = window.SITE || {};
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const css = getComputedStyle(document.documentElement);
  const colors = [css.getPropertyValue("--primary"), css.getPropertyValue("--accent"), "#ffd166", "#ffffff"].map(c => c.trim());

  // ---------- Musiqa ----------
  const audio = $("#bgMusic");
  const musicBtn = $("#musicBtn");
  const playMusic = () => audio && audio.play().then(() => musicBtn.classList.add("playing")).catch(() => {});
  if (musicBtn) musicBtn.onclick = () => {
    if (audio.paused) playMusic(); else { audio.pause(); musicBtn.classList.remove("playing"); }
  };

  // ---------- Canvas effektlari (konfetti, gulbarglar) ----------
  const canvas = $("#fx");
  const ctx = canvas.getContext("2d");
  let parts = [];
  const resize = () => { canvas.width = innerWidth * devicePixelRatio; canvas.height = innerHeight * devicePixelRatio; ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0); };
  resize(); addEventListener("resize", resize);

  function confetti(n = 160, x = innerWidth / 2, y = innerHeight / 3) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, v = 4 + Math.random() * 9;
      parts.push({ kind: "conf", x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 5, r: 4 + Math.random() * 5,
        rot: Math.random() * 6, vr: (Math.random() - .5) * .3, c: colors[i % colors.length], life: 200 });
    }
  }
  function petal() {
    parts.push({ kind: "petal", x: Math.random() * innerWidth, y: -20, vx: (Math.random() - .3) * 1.2, vy: 1 + Math.random() * 1.4,
      r: 7 + Math.random() * 6, rot: Math.random() * 6, vr: (Math.random() - .5) * .05, c: colors[Math.random() < .6 ? 1 : 0], life: 1200, sway: Math.random() * 6 });
  }
  (function loop() {
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    parts = parts.filter(p => p.life-- > 0 && p.y < innerHeight + 40);
    for (const p of parts) {
      if (p.kind === "conf") { p.vy += .18; p.vx *= .985; }
      else { p.sway += .02; p.x += Math.sin(p.sway) * .6; }
      p.x += p.vx; p.y += p.vy; p.rot += p.vr;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.fillStyle = p.c;
      if (p.kind === "conf") ctx.fillRect(-p.r / 2, -p.r / 4, p.r, p.r / 2);
      else { ctx.globalAlpha = .85; ctx.beginPath(); ctx.ellipse(0, 0, p.r, p.r / 2, 0, 0, Math.PI * 2); ctx.fill(); }
      ctx.restore();
    }
    requestAnimationFrame(loop);
  })();

  // ---------- DOM uchuvchilar (sharlar, yuraklar) ----------
  function floater(html, cls = "") {
    const el = document.createElement("div");
    el.className = "floater " + cls;
    el.innerHTML = html;
    el.style.left = Math.random() * 92 + "vw";
    el.style.setProperty("--dx", (Math.random() - .5) * 120 + "px");
    el.style.setProperty("--rot", (Math.random() - .5) * 40 + "deg");
    el.style.animationDuration = 7 + Math.random() * 6 + "s";
    document.body.appendChild(el);
    el.addEventListener("animationend", () => el.remove());
    return el;
  }
  const balloon = () => { const b = floater("", ""); b.innerHTML = `<div class="balloon" style="background:${colors[Math.floor(Math.random() * 3)]}"></div>`; };
  const heart = (big) => { const h = floater(["💖", "💕", "❤️", "💗"][Math.floor(Math.random() * 4)]); h.style.fontSize = (big ? 30 : 16) + Math.random() * 20 + "px"; };

  const star = () => { const st = floater(["⭐", "✨", "🌟", "💫"][Math.floor(Math.random() * 4)]); st.style.fontSize = 14 + Math.random() * 22 + "px"; };

  function startAmbient() {
    if (S.f.balloons) { for (let i = 0; i < 8; i++) setTimeout(balloon, i * 350); setInterval(balloon, 3500); }
    if (S.f.hearts) { setInterval(() => heart(false), 900); }
    if (S.f.stars) { setInterval(star, 700); }
    if (S.f.petals) { setInterval(petal, 380); }
    if (S.f.confetti) { confetti(220); }
  }

  // ---------- Kirish (konvert) ----------
  const intro = $("#intro");
  let started = false;
  function openSite() {
    if (started) return; started = true;
    playMusic();
    const env = $(".envelope");
    if (env) env.classList.add("open");
    setTimeout(() => { intro && intro.classList.add("gone"); document.body.classList.remove("locked"); startAmbient(); }, intro ? 1500 : 0);
  }
  if (intro) { document.body.classList.add("locked"); intro.addEventListener("click", openSite); }
  else { document.addEventListener("click", playMusic, { once: true }); startAmbient(); started = true; }

  // ---------- Taymerlar ----------
  const pad = n => String(n).padStart(2, "0");
  function tick() {
    $$("[data-countdown]").forEach(el => {
      let d = Math.max(0, new Date(el.dataset.countdown) - new Date()) / 1000;
      const v = [Math.floor(d / 86400), Math.floor(d % 86400 / 3600), Math.floor(d % 3600 / 60), Math.floor(d % 60)];
      $$("b", el).forEach((b, i) => b.textContent = i ? pad(v[i]) : v[i]);
    });
    $$("[data-since]").forEach(el => {
      let d = Math.max(0, new Date() - new Date(el.dataset.since)) / 1000;
      const v = [Math.floor(d / 86400), Math.floor(d % 86400 / 3600), Math.floor(d % 3600 / 60), Math.floor(d % 60)];
      $$("b", el).forEach((b, i) => b.textContent = i ? pad(v[i]) : v[i]);
    });
  }
  tick(); setInterval(tick, 1000);

  // ---------- Galereya ----------
  const lb = $(".lightbox");
  $$(".gallery img").forEach(img => img.onclick = () => { $("img", lb).src = img.src; lb.classList.add("open"); });
  if (lb) lb.onclick = () => lb.classList.remove("open");

  // ---------- Tort shamlari ----------
  const candles = $$(".candle");
  candles.forEach(c => c.onclick = () => {
    c.classList.add("out");
    if (candles.every(x => x.classList.contains("out"))) {
      const r = c.getBoundingClientRect();
      confetti(250, r.left, r.top);
      $("#wishDone") && ($("#wishDone").hidden = false);
    }
  });

  // ---------- «Meni sevasanmi?» ----------
  const no = $("#noBtn"), yes = $("#yesBtn");
  if (no) {
    const run = (e) => {
      e.preventDefault();
      const w = innerWidth - 140, h = 220;
      no.style.transform = `translate(${(Math.random() - .5) * w * .8}px, ${(Math.random() - .5) * h}px)`;
    };
    no.addEventListener("mouseenter", run); no.addEventListener("touchstart", run, { passive: false }); no.addEventListener("click", run);
    yes.onclick = () => { for (let i = 0; i < 40; i++) setTimeout(() => heart(true), i * 60); confetti(200); $("#yesAnswer").hidden = false; no.hidden = true; };
  }

  // ---------- RSVP ----------
  const form = $("#rsvpForm");
  if (form) form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("button", form); btn.disabled = true;
    const data = Object.fromEntries(new FormData(form));
    try {
      const r = await fetch(`/s/${S.slug}/rsvp`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
      if (!r.ok) throw 0;
      form.innerHTML = `<p style="text-align:center;font-size:18px">${data.attending === "yes" ? "Rahmat! Sizni intiqlik bilan kutamiz 🤍" : "Javobingiz uchun rahmat 🤍"}</p>`;
      if (data.attending === "yes") confetti(150);
    } catch { btn.disabled = false; alert("Xatolik yuz berdi, qayta urinib ko'ring"); }
  };

  // ---------- Scroll animatsiyasi ----------
  const io = new IntersectionObserver(es => es.forEach(e => e.isIntersecting && e.target.classList.add("in")), { threshold: .15 });
  $$(".reveal").forEach(el => io.observe(el));
})();
