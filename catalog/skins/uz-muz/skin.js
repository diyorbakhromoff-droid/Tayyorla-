var hero = T.$('.mz-hero'), stage = T.$('.mz-stage', hero), cv = T.$('.mz-ice', hero), ctx = cv.getContext('2d'), warmEl = T.$('.mz-warm', hero);
var DPR = Math.min(2, window.devicePixelRatio || 1), S = 0, melted = false, music = false, rubbing = false, lastDrop = 0, lastCheck = 0;
var ice = getComputedStyle(document.documentElement).getPropertyValue('--accent2').trim() || '#A9D8FF';
function rr(c, x, y, w, h, r) { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); }
function frost() {
  S = stage.clientWidth; cv.width = Math.round(S * DPR); cv.height = Math.round(S * DPR);
  var c = ctx; c.setTransform(DPR, 0, 0, DPR, 0, 0); c.globalCompositeOperation = 'source-over'; c.clearRect(0, 0, S, S);
  var g = c.createLinearGradient(0, 0, S, S); g.addColorStop(0, 'rgba(240,250,255,.8)'); g.addColorStop(0.5, 'rgba(205,232,250,.62)'); g.addColorStop(1, 'rgba(175,212,240,.74)');
  rr(c, 0, 0, S, S, 30); c.fillStyle = g; c.fill();
  c.save(); rr(c, 0, 0, S, S, 30); c.clip();
  c.globalAlpha = 0.12; c.fillStyle = ice; c.fillRect(0, 0, S, S); c.globalAlpha = 1;
  for (var i = 0; i < 1600; i++) { c.fillStyle = 'rgba(255,255,255,' + (Math.random() * 0.45) + ')'; var d = Math.random() * 2; c.fillRect(Math.random() * S, Math.random() * S, d, d); }
  c.strokeStyle = 'rgba(255,255,255,.55)'; c.lineCap = 'round';
  for (var k = 0; k < 26; k++) {  /* qirov naqshlari */
    var x = Math.random() * S, y = Math.random() * S, a = Math.random() * 6.28, len = 12 + Math.random() * 40;
    c.lineWidth = 0.6 + Math.random() * 1.1; c.beginPath(); c.moveTo(x, y);
    for (var j = 0; j < 4; j++) { x += Math.cos(a) * len / 4; y += Math.sin(a) * len / 4; c.lineTo(x, y); c.moveTo(x, y); c.lineTo(x + Math.cos(a + 0.8) * len / 5, y + Math.sin(a + 0.8) * len / 5); c.moveTo(x, y); a += (Math.random() - 0.5) * 0.6; }
    c.stroke();
  }
  for (var f = 0; f < 7; f++) { /* qor parchalari */
    var fx = Math.random() * S, fy = Math.random() * S, fr = 5 + Math.random() * 7; c.lineWidth = 1; c.strokeStyle = 'rgba(255,255,255,.7)'; c.beginPath();
    for (var q = 0; q < 6; q++) { var an = q * Math.PI / 3; c.moveTo(fx, fy); c.lineTo(fx + Math.cos(an) * fr, fy + Math.sin(an) * fr); }
    c.stroke();
  }
  c.strokeStyle = 'rgba(255,255,255,.5)'; c.lineWidth = 1.2; c.beginPath(); /* yoriq */
  var cx = S * 0.7, cy = S * 0.15; c.moveTo(cx, cy); for (var m = 0; m < 6; m++) { cx += (Math.random() - 0.3) * 18; cy += 12 + Math.random() * 12; c.lineTo(cx, cy); } c.stroke();
  var hl = c.createLinearGradient(0, 0, 0, S * 0.4); hl.addColorStop(0, 'rgba(255,255,255,.55)'); hl.addColorStop(1, 'rgba(255,255,255,0)');
  c.fillStyle = hl; c.beginPath(); c.moveTo(0, 0); c.lineTo(S, 0); c.lineTo(S, S * 0.12); c.quadraticCurveTo(S * 0.5, S * 0.28, 0, S * 0.16); c.closePath(); c.fill();
  c.restore();
}
function pos(e) { var r = cv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
function rub(p) {
  ctx.globalCompositeOperation = 'destination-out';
  var g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 36); g.addColorStop(0, 'rgba(0,0,0,.95)'); g.addColorStop(.55, 'rgba(0,0,0,.6)'); g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p.x, p.y, 36, 0, 6.29); ctx.fill();
  warmEl.style.transform = 'translate(' + p.x + 'px,' + p.y + 'px)';
  var now = Date.now();
  if (now - lastDrop > 140) { lastDrop = now; var d = document.createElement('i'); d.className = 'mz-drop'; d.style.left = (p.x - 3) + 'px'; d.style.top = (p.y + 8) + 'px'; stage.appendChild(d); setTimeout(function () { d.remove(); }, 1200); }
  if (now - lastCheck > 280) { lastCheck = now; check(); }
}
function check() {
  var w = cv.width, h = cv.height, data = ctx.getImageData(0, 0, w, h).data, tot = 0, clear = 0, st = Math.max(4, Math.round(w / 60));
  for (var y = Math.round(h * 0.1); y < h * 0.9; y += st) for (var x = Math.round(w * 0.1); x < w * 0.9; x += st) { tot++; if (data[(y * w + x) * 4 + 3] < 120) clear++; }
  if (tot && clear / tot > 0.62) melt();
}
function melt() {
  if (melted) return; melted = true; rubbing = false; stage.classList.remove('rub'); hero.classList.add('warm');
  try { if (navigator.vibrate) navigator.vibrate([20, 40, 60]); } catch (e) {}
  setTimeout(function () { var r = stage.getBoundingClientRect(); T.burst(r.left + r.width / 2, r.top + r.height / 2, 60, 'sparkle'); }, 300);
}
cv.addEventListener('pointerdown', function (e) {
  if (melted) return; rubbing = true; stage.classList.add('rub'); try { cv.setPointerCapture(e.pointerId); } catch (err) {}
  if (!music && T.music && T.music.play) { music = true; try { T.music.play(); } catch (err) {} }
  if (T.reduced) { melt(); return; }
  rub(pos(e));
});
cv.addEventListener('pointermove', function (e) { if (rubbing && !melted) rub(pos(e)); });
function end() { rubbing = false; stage.classList.remove('rub'); if (!melted) check(); }
cv.addEventListener('pointerup', end); cv.addEventListener('pointercancel', end);
cv.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); melt(); } });
cv.tabIndex = 0;
/* javob: «ha» — tabrik va yuboruvchiga xabar, «yo'q» — qochib ketadi */
var yes = T.$('.mz-yes', hero), no = T.$('.mz-no', hero), thanks = T.$('.mz-thanks', hero), dodge = 0;
var NO_TEXT = ["Yo'q", 'Ishonchingmi?', "Yana o'ylab ko'r", 'Iltimos...', 'Ha deysan baribir'];
var orig = null;
function moveNo() {
  dodge++; var hr = hero.getBoundingClientRect();
  if (!orig) orig = no.getBoundingClientRect();
  no.textContent = T.typo(NO_TEXT[Math.min(dodge, NO_TEXT.length - 1)]);
  var w = no.offsetWidth, minDx = hr.left + 12 - orig.left, maxDx = hr.right - 12 - (orig.left + w);
  var dx = minDx + Math.random() * Math.max(0, maxDx - minDx), dy = (Math.random() - 0.5) * 100;
  no.style.transform = 'translate(' + dx.toFixed(0) + 'px,' + dy.toFixed(0) + 'px)';
  if (dodge >= NO_TEXT.length + 1) no.remove();
}
if (no) { no.addEventListener('pointerenter', function (e) { if (e.pointerType === 'mouse') moveNo(); }); no.addEventListener('click', moveNo); }
if (yes) yes.addEventListener('click', function () {
  T.$('.mz-btns', hero).remove(); T.$('.mz-ask', hero).remove();
  thanks.textContent = T.typo(T.cfg.javob_matni || T.L('thanks')); thanks.hidden = false;
  T.celebrate(thanks, 'heart');
  try { if (navigator.vibrate) navigator.vibrate([30, 50, 30]); } catch (e) {}
  var m = location.pathname.match(/^\/s\/([a-z0-9]+)$/);
  if (m && !T.cfg.demo) { try { fetch('/s/' + m[1] + '/react', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ emoji: '❤️', message: 'Kechirdim ✅' }) }); } catch (e) {} }
});
frost();
var rt; window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(function () { if (!melted) frost(); }, 200); });
