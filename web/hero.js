/* Hero parallax: the top hand drifts up and the bottom hand drifts down as the page scrolls. */
(() => {
  'use strict';
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const stage = document.querySelector('[data-parallax]');
  if (!stage) return;
  const top = stage.querySelector('.hand.top');
  const bottom = stage.querySelector('.hand.bottom');
  let ticking = false;
  const update = () => {
    ticking = false;
    const r = stage.getBoundingClientRect();
    const progress = Math.max(-1, Math.min(1, (window.innerHeight / 2 - (r.top + r.height / 2)) / window.innerHeight));
    top.style.transform = `translate3d(0, ${(-progress * 26).toFixed(1)}px, 0)`;
    bottom.style.transform = `translate3d(0, ${(progress * 26).toFixed(1)}px, 0)`;
  };
  window.addEventListener('scroll', () => {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
  update();
})();
