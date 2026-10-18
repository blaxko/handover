/* Shared site behaviour: mobile menu, scroll reveal, magnetic buttons, ripple. Vanilla JS. */
(() => {
  'use strict';
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Mobile menu: a fully opaque full-screen panel.
  const btn = document.querySelector('.menu-btn');
  const panel = document.querySelector('#menu-panel');
  if (btn && panel) {
    const close = () => {
      panel.classList.remove('open');
      panel.setAttribute('aria-hidden', 'true');
      btn.setAttribute('aria-expanded', 'false');
      btn.focus();
    };
    btn.addEventListener('click', () => {
      const open = !panel.classList.contains('open');
      panel.classList.toggle('open', open);
      panel.setAttribute('aria-hidden', String(!open));
      btn.setAttribute('aria-expanded', String(open));
      if (open) panel.querySelector('a, button').focus();
    });
    panel.querySelector('.menu-close').addEventListener('click', close);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && panel.classList.contains('open')) close(); });
    panel.querySelectorAll('a').forEach((a) => a.addEventListener('click', () => { panel.classList.remove('open'); }));
  }

  // Scroll reveal: staggered fade-up, once per element.
  const reveals = document.querySelectorAll('.reveal');
  if (reveals.length && 'IntersectionObserver' in window && !reduce) {
    const io = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) { entry.target.classList.add('in'); io.unobserve(entry.target); }
      }
    }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
    reveals.forEach((el) => io.observe(el));
  } else {
    reveals.forEach((el) => el.classList.add('in'));
  }

  // Magnetic primary buttons and a ripple on click.
  if (!reduce) {
    document.querySelectorAll('.btn-primary').forEach((b) => {
      b.addEventListener('pointermove', (e) => {
        const r = b.getBoundingClientRect();
        const x = (e.clientX - r.left - r.width / 2) * 0.18;
        const y = (e.clientY - r.top - r.height / 2) * 0.25;
        b.style.setProperty('--p', `${x.toFixed(1)}px`);
        b.style.setProperty('--q', `${y.toFixed(1)}px`);
      });
      b.addEventListener('pointerleave', () => { b.style.setProperty('--p', '0px'); b.style.setProperty('--q', '0px'); });
    });
  }
  document.querySelectorAll('.btn').forEach((b) => {
    b.addEventListener('click', (e) => {
      if (reduce) return;
      const r = b.getBoundingClientRect();
      const s = document.createElement('span');
      const size = Math.max(r.width, r.height);
      s.className = 'ripple';
      s.style.width = s.style.height = `${size}px`;
      s.style.left = `${e.clientX - r.left - size / 2}px`;
      s.style.top = `${e.clientY - r.top - size / 2}px`;
      b.appendChild(s);
      setTimeout(() => s.remove(), 750);
    });
  });

  // The hero graph node should pause when the page is hidden or motion is reduced.
  const hands = document.querySelector('.hero-art svg');
  if (hands && typeof hands.pauseAnimations === 'function' && reduce) hands.pauseAnimations();
})();
