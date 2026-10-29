var hero = T.$('.fq-hero'), box = T.$('.fq-box', hero), sky = T.$('.fq-sky', hero), dots = T.$$('.fq-taps i', hero);
var jins = T.cfg.jins === 'ogil' ? 'ogil' : T.cfg.jins === 'qiz' ? 'qiz' : 'neutral';
hero.classList.add(jins);
T.$('.fq-is', hero).textContent = T.typo(jins === 'ogil' ? "O'g'il!" : jins === 'qiz' ? 'Qiz!' : 'Farzand!');
T.$$('.fq-facts li', hero).forEach(function (li) { if (!T.$('b', li)) li.remove(); });
var taps = 0, music = false;
function vib(p) { try { if (navigator.vibrate) navigator.vibrate(p); } catch (e) {} }
function balloons() {
  var cs = getComputedStyle(hero), cols = ['--b1', '--b2', '--b3'].map(function (k) { return cs.getPropertyValue(k).trim(); }).concat(['#FFFFFF']);
  var n = T.reduced ? 6 : 18;
  for (var i = 0; i < n; i++) {
    var b = document.createElement('i'); b.className = 'fq-bal';
    b.style.setProperty('--c', cols[i % 4 === 3 ? 3 : i % 3]);
    b.style.setProperty('--w', (34 + Math.random() * 26) + 'px');
    b.style.setProperty('--x', ((Math.random() - 0.5) * innerWidth * 1.1) + 'px');
    b.style.setProperty('--t', (5 + Math.random() * 3) + 's');
    b.style.setProperty('--d', (i * 0.09) + 's');
    sky.appendChild(b);
  }
  setTimeout(function () { sky.innerHTML = ''; }, 9500);
}
function open() {
  hero.classList.add('open'); vib([40, 50, 90]);
  balloons();
  var r = box.getBoundingClientRect();
  setTimeout(function () { T.burst(r.left + r.width / 2, r.top + r.height * 0.3, 130, 'confetti'); }, 120);
  setTimeout(function () { T.celebrate(T.$('.fq-is', hero)); }, 900);
  box.setAttribute('aria-label', T.typo('Sharlarni yana uchirish'));
}
box.addEventListener('click', function () {
  if (!music && T.music && T.music.play) { music = true; try { T.music.play(); } catch (e) {} }
  if (hero.classList.contains('open')) { balloons(); vib(20); return; }
  taps++; if (dots[taps - 1]) dots[taps - 1].classList.add('on');
  box.classList.remove('s1', 's2'); void box.offsetWidth;
  if (taps === 1) { box.classList.add('s1'); vib(15); }
  else if (taps === 2) { box.classList.add('s2'); hero.classList.add('peek'); vib([20, 40, 20]); }
  else open();
});
