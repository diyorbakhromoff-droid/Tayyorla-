var hero = T.$('.sl-hero'), cv = T.$('.sl-sky', hero), ctx = cv.getContext('2d'), nameEl = T.$('.sl-name', hero);
var age = T.$('.sl-age', hero); if (age && !T.$('b', age)) age.remove();
var DPR = Math.min(2, window.devicePixelRatio || 1), W = 0, H = 0;
function size() { var r = hero.getBoundingClientRect(); W = r.width; H = r.height; cv.width = Math.round(W * DPR); cv.height = Math.round(H * DPR); ctx.setTransform(DPR, 0, 0, DPR, 0, 0); }
function fitName() {
  if (!nameEl) return; nameEl.style.fontSize = '';
  var max = hero.clientWidth * 0.9, w = nameEl.offsetWidth;
  if (w > max) nameEl.style.fontSize = Math.floor(parseFloat(getComputedStyle(nameEl).fontSize) * max / w) + 'px';
}
var cs = getComputedStyle(document.documentElement);
var COLS = ['--fx1', '--fx2', '--fx3'].map(function (k) { return cs.getPropertyValue(k).trim() || '#fff'; }).concat(['#FFFFFF']);
function pick() { return COLS[Math.floor(Math.random() * COLS.length)]; }
function rnd(a, b) { return a + Math.random() * (b - a); }

var parts = [], rockets = [], flashes = [], raf = 0, textForm = null;
function P(x, y, vx, vy, c, max, sz, t) { return { x: x, y: y, px: x, py: y, vx: vx, vy: vy, c: c, life: 0, max: max, sz: sz, t: t }; }
function explode(x, y, kind) {
  var c1 = pick(), c2 = pick(), n = kind === 'ring' ? 72 : kind === 'willow' ? 90 : 120;
  for (var i = 0; i < n; i++) {
    var a = kind === 'ring' ? i / n * Math.PI * 2 : Math.random() * Math.PI * 2;
    var sp = kind === 'ring' ? 3.6 : Math.sqrt(Math.random()) * (kind === 'willow' ? 3.3 : 4.6);
    parts.push(P(x, y, Math.cos(a) * sp, Math.sin(a) * sp, kind === 'willow' ? '#FFD98A' : (i % 4 ? c1 : c2), kind === 'willow' ? rnd(110, 150) : rnd(55, 85), kind === 'willow' ? 1.8 : 2.8, kind));
  }
  flashes.push({ x: x, y: y, life: 0 });
}
function launch(tx, ty, kind, cb) {
  rockets.push({ x: tx + rnd(-30, 30), y: H + 8, sx: 0, tx: tx, ty: ty, kind: kind || ['peony', 'ring', 'willow', 'peony'][Math.floor(Math.random() * 4)], cb: cb, c: pick() });
  run();
}
/* uchqunlar yig'ilib ismni yozadi */
function samplePoints() {
  var r = nameEl.getBoundingClientRect(), hr = hero.getBoundingClientRect(), st = getComputedStyle(nameEl), fs = parseFloat(st.fontSize);
  var off = document.createElement('canvas'), pad = 20; off.width = Math.ceil(r.width) + pad * 2; off.height = Math.ceil(r.height) + pad * 2;
  var o = off.getContext('2d'); o.font = st.fontWeight + ' ' + fs + 'px ' + st.fontFamily; o.textAlign = 'center'; o.textBaseline = 'middle'; o.fillStyle = '#000';
  o.fillText(nameEl.textContent, off.width / 2, off.height / 2 + fs * 0.03);
  var d = o.getImageData(0, 0, off.width, off.height).data, gap = Math.max(3, Math.round(fs / 24)), pts = [];
  for (var y = 0; y < off.height; y += gap) for (var x = 0; x < off.width; x += gap) if (d[(y * off.width + x) * 4 + 3] > 140) pts.push({ x: r.left - hr.left - pad + x, y: r.top - hr.top - pad + y });
  while (pts.length > 1300) pts = pts.filter(function (_, i) { return i % 2 === 0; });
  return pts;
}
function formName(cx, cy) {
  var pts = samplePoints();
  textForm = { n: pts.length, done: false, fade: 0 };
  pts.forEach(function (p) {
    var a = Math.random() * Math.PI * 2, sp = rnd(1.5, 6.5);
    var q = P(cx, cy, Math.cos(a) * sp, Math.sin(a) * sp, pick(), 1e9, 1.8, 'txt'); q.tx = p.x; q.ty = p.y; q.delay = rnd(16, 30); parts.push(q);
  });
  flashes.push({ x: cx, y: cy, life: 0, big: true });
  setTimeout(function () { hero.classList.add('lit'); if (textForm) textForm.done = true; autoShow(); }, 1500);
}
function step() {
  ctx.clearRect(0, 0, W, H);
  ctx.globalCompositeOperation = 'lighter'; ctx.lineCap = 'round';
  for (var i = rockets.length - 1; i >= 0; i--) {
    var k = rockets[i], dy = (k.ty - k.y) * 0.075, dx = (k.tx - k.x) * 0.075;
    k.px = k.x; k.py = k.y; k.x += dx; k.y += Math.min(-2.2, dy);
    ctx.strokeStyle = k.c; ctx.globalAlpha = 0.9; ctx.lineWidth = 2.2; ctx.beginPath(); ctx.moveTo(k.px, k.py + 10); ctx.lineTo(k.x, k.y); ctx.stroke();
    if (Math.random() < 0.6) parts.push(P(k.x, k.y + 4, rnd(-0.4, 0.4), rnd(0.5, 1.4), '#FFE3A3', rnd(14, 24), 1.1, 'trail'));
    if (k.y - k.ty < 6) { rockets.splice(i, 1); if (k.cb) k.cb(k.x, k.y); else explode(k.x, k.y, k.kind); }
  }
  for (var j = parts.length - 1; j >= 0; j--) {
    var p = parts[j]; p.life++; p.px = p.x; p.py = p.y; var a;
    if (p.t === 'txt') {
      if (p.life < p.delay) { p.vx *= 0.92; p.vy *= 0.92; p.x += p.vx; p.y += p.vy; }
      else { p.x += (p.tx - p.x) * 0.13; p.y += (p.ty - p.y) * 0.13; }
      a = textForm && textForm.done ? Math.max(0, 1 - textForm.fade / 50) : 1;
      if (a <= 0) { parts.splice(j, 1); continue; }
      ctx.globalAlpha = a * (0.75 + Math.random() * 0.25); ctx.fillStyle = p.c; ctx.fillRect(p.x - 1, p.y - 1, p.sz, p.sz);
      continue;
    }
    p.vy += p.t === 'willow' ? 0.028 : p.t === 'trail' ? 0.02 : 0.05; p.vx *= 0.982; p.vy *= 0.982; p.x += p.vx; p.y += p.vy;
    a = 1 - p.life / p.max; if (a <= 0) { parts.splice(j, 1); continue; }
    ctx.globalAlpha = a; ctx.strokeStyle = p.c; ctx.lineWidth = p.sz * (p.t === 'willow' ? 1 : a * 0.7 + 0.5);
    ctx.beginPath(); ctx.moveTo(p.px - p.vx * 3, p.py - p.vy * 3); ctx.lineTo(p.x, p.y); ctx.stroke();
    if (p.t !== 'trail' && Math.random() < 0.04) { ctx.globalAlpha = a; ctx.fillStyle = '#fff'; ctx.fillRect(p.x - 1, p.y - 1, 2, 2); }
  }
  if (textForm && textForm.done) textForm.fade++;
  for (var f = flashes.length - 1; f >= 0; f--) {
    var fl = flashes[f]; fl.life++; var R = (fl.big ? 160 : 90) * (0.4 + fl.life / 14), al = Math.max(0, 0.32 - fl.life / 40);
    if (al <= 0) { flashes.splice(f, 1); continue; }
    var g = ctx.createRadialGradient(fl.x, fl.y, 0, fl.x, fl.y, R); g.addColorStop(0, 'rgba(255,240,210,' + al + ')'); g.addColorStop(1, 'rgba(255,240,210,0)');
    ctx.globalAlpha = 1; ctx.fillStyle = g; ctx.fillRect(fl.x - R, fl.y - R, R * 2, R * 2);
  }
  ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
  if (parts.length || rockets.length || flashes.length) raf = requestAnimationFrame(step); else { raf = 0; ctx.clearRect(0, 0, W, H); }
}
function run() { if (!raf) raf = requestAnimationFrame(step); }
var visible = true;
if ('IntersectionObserver' in window) new IntersectionObserver(function (e) { visible = e[0].isIntersecting; }).observe(hero);
function autoShow() {
  var n = 0;
  (function next() {
    if (n++ >= 7) return;
    if (visible && !document.hidden) launch(rnd(W * 0.15, W * 0.85), rnd(H * 0.12, H * 0.42));
    setTimeout(next, rnd(1300, 2200));
  })();
}
var musicOn = false;
hero.addEventListener('pointerdown', function (e) {
  if (e.target.closest('a,button')) return;
  var r = hero.getBoundingClientRect(); hero.classList.add('tapped');
  if (!musicOn && T.music && T.music.play) { musicOn = true; try { T.music.play(); } catch (err) {} }
  launch(e.clientX - r.left, Math.min(e.clientY - r.top, H - 160));
  try { if (navigator.vibrate) navigator.vibrate(12); } catch (err) {}
});
size(); fitName();
window.addEventListener('resize', function () { size(); fitName(); });
T.ready(function () {
  if (T.reduced || !nameEl) { hero.classList.add('lit'); return; }
  var go = function () {
    size(); fitName();
    var r = nameEl.getBoundingClientRect(), hr = hero.getBoundingClientRect();
    var cx = r.left - hr.left + r.width / 2, cy = r.top - hr.top + r.height / 2;
    setTimeout(function () { launch(cx, cy, 'peony', formName); }, 350);
  };
  if (document.fonts && document.fonts.load) Promise.race([document.fonts.load('900 100px "Big Shoulders Display"'), new Promise(function (r) { setTimeout(r, 1500); })]).then(go, go); else go();
});
