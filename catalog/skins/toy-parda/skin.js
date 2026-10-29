var hero = T.$('.pd-hero');
T.intros.parda = function () {
  return '<div class="pd-cur" aria-hidden="true"><div class="pd-val"></div><div class="pd-p pd-l"></div><div class="pd-p pd-r"></div></div>';
};
T.ready(function () { setTimeout(function () { hero.classList.add('on'); }, T.reduced ? 0 : 150); });
