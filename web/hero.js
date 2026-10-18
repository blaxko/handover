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

/* The "Ada Okafor" tag glides in and settles just under the word "current" (desktop only). */
(() => {
  'use strict';
  const card = document.querySelector('.about');
  const ada = card && card.querySelector('.cursor-ada');
  const word = document.querySelector('#word-current');
  if (!card || !ada || !word) return;
  const desktop = window.matchMedia('(min-width: 769px)');
  const place = () => {
    if (!desktop.matches) return;
    const c = card.getBoundingClientRect();
    const w = word.getBoundingClientRect();
    const x = w.left + w.width / 2 - c.left - 20;
    const y = w.bottom - c.top + 12;
    ada.style.setProperty('--ax', `${x.toFixed(0)}px`);
    ada.style.setProperty('--ay', `${y.toFixed(0)}px`);
  };
  window.addEventListener('resize', place);
  place();
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(place);
})();
