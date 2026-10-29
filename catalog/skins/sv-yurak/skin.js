var hero = T.$('.hr-hero'), heart = T.$('.hr-heart', hero), liq = T.$('.hr-liq', hero), bar = T.$('.hr-meter i', hero);
var FILL_MS = 3400, prog = 0, holding = false, done = false, phase = 0, last = 0, lastBeat = 0, music = false;
var cs = getComputedStyle(document.documentElement), C = [cs.getPropertyValue('--accent').trim(), cs.getPropertyValue('--accent2').trim()];
function beat(t) { return Math.exp(-Math.pow((t - 0.08) / 0.05, 2)) + 0.55 * Math.exp(-Math.pow((t - 0.3) / 0.06, 2)); }
function floatHeart() {
  var r = heart.getBoundingClientRect(), hr = hero.getBoundingClientRect(), s = document.createElement('span');
  s.className = 'hr-float'; s.textContent = '♥';
  s.style.left = (r.left - hr.left + r.width * (0.2 + Math.random() * 0.6)) + 'px'; s.style.top = (r.top - hr.top + r.height * 0.35) + 'px';
  s.style.setProperty('--s', (12 + Math.random() * 18) + 'px'); s.style.setProperty('--c', C[Math.random() < 0.6 ? 0 : 1]);
  s.style.setProperty('--x', (Math.random() * 80 - 40) + 'px'); s.style.setProperty('--r', (Math.random() * 50 - 25) + 'deg'); s.style.setProperty('--d', (1.2 + Math.random() * 0.8) + 's');
  hero.appendChild(s); setTimeout(function () { s.remove(); }, 2200);
}
function finish() {
  done = true; holding = false; prog = 1; hero.classList.add('done');
  var r = heart.getBoundingClientRect();
  T.burst(r.left + r.width / 2, r.top + r.height / 2, 150, 'heart');
  setTimeout(function () { T.celebrate(T.$('.hr-title', hero), 'heart'); }, 500);
  try { if (navigator.vibrate) navigator.vibrate([30, 60, 30, 60, 120]); } catch (e) {}
}
function frame(now) {
  var dt = Math.min(50, now - (last || now)); last = now;
  if (!done) {
    prog = holding ? Math.min(1, prog + dt / FILL_MS) : Math.max(0, prog - dt / (FILL_MS * 2.5));
    if (prog >= 1) finish();
  }
  var period = done ? 1100 : 1000 - prog * 640;
  phase = (phase + dt / period) % 1;
  var b = beat(phase), amp = done ? 0.05 : 0.04 + prog * 0.1;
  heart.style.transform = 'scale(' + (1 + b * amp) + ')';
  liq.setAttribute('transform', 'translate(0 ' + (106 - prog * 112).toFixed(1) + ')');
  bar.style.transform = 'scaleX(' + prog.toFixed(3) + ')';
  if (holding && phase < lastBeat) {
    try { if (navigator.vibrate) navigator.vibrate(prog > 0.6 ? 22 : 14); } catch (e) {}
    for (var i = 0; i < 1 + Math.round(prog * 3); i++) floatHeart();
  }
  lastBeat = phase;
  requestAnimationFrame(frame);
}
function start(e) {
  if (done) return; if (e && e.cancelable) e.preventDefault(); holding = true;
  if (!music && T.music && T.music.play) { music = true; try { T.music.play(); } catch (err) {} }
  if (T.reduced) finish();
}
function stop() { holding = false; }
heart.addEventListener('pointerdown', function (e) { try { heart.setPointerCapture(e.pointerId); } catch (err) {} start(e); });
heart.addEventListener('pointerup', stop); heart.addEventListener('pointercancel', stop); heart.addEventListener('lostpointercapture', stop);
heart.addEventListener('contextmenu', function (e) { e.preventDefault(); });
heart.addEventListener('keydown', function (e) { if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); start(); } });
heart.addEventListener('keyup', function (e) { if (e.key === ' ' || e.key === 'Enter') stop(); });
requestAnimationFrame(frame);
