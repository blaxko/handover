/* Dashboard extras: the services and people tree, KPIs, people pills, and the current-answer card.
   app.js still owns asking, drawing and the event panel; this file only reads and forwards. */
(() => {
  'use strict';
  const $ = (sel) => document.querySelector(sel);

  function item(label, onClick) {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    b.addEventListener('click', onClick);
    li.appendChild(b);
    return li;
  }

  // Forward a question through the same form app.js listens to.
  function ask(question) {
    $('#q').value = question;
    $('#ask-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    $('#answer-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function initials(name) {
    return name.split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
  }

  function fill(data) {
    const services = data.nodes.filter((n) => n.label === 'Service');
    const people = data.nodes.filter((n) => n.label === 'Person');
    const openTickets = new Set(data.edges.filter((e) => e.type === 'ASSIGNED_TO' && !e.valid_to).map((e) => e.from));
    const handovers = new Set(data.edges.filter((e) => e.source && e.source.startsWith('evt-')).map((e) => e.source));

    $('#kpi-services').textContent = String(services.length);
    $('#kpi-tickets').textContent = String(openTickets.size);
    $('#kpi-handovers').textContent = String(handovers.size);

    const treeServices = $('#tree-services');
    const treePeople = $('#tree-people');
    const pills = $('#people-pills');
    treeServices.replaceChildren(...services.map((s) => item(s.name, () => ask(`Who owns ${s.name}?`))));
    treePeople.replaceChildren(...people.map((p) => item(p.name, () => ask(`What breaks if ${p.name} leaves?`))));
    pills.replaceChildren(...people.map((p) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = p.name;
      b.setAttribute('data-initials', initials(p.name));
      b.addEventListener('click', () => ask(`What breaks if ${p.name} leaves?`));
      return b;
    }));
  }

  // The dark card mirrors whatever answer app.js last rendered.
  function watchAnswer() {
    const target = $('#answer');
    const hero = $('#hero-answer');
    const sync = () => {
      const first = target.querySelector('.answer-text') || target.querySelector('p');
      hero.textContent = first ? first.textContent : 'Ask a question to see it here.';
    };
    new MutationObserver(sync).observe(target, { childList: true, subtree: true });
  }

  async function refresh() {
    try {
      const res = await fetch('/graph/all');
      if (res.ok) fill(await res.json());
    } catch (e) {
      // The page still works without the tree and KPIs.
    }
  }

  async function boot() {
    watchAnswer();
    refresh();
    // After a handover, the counts and the tree should show the new state.
    let last = '';
    new MutationObserver(() => {
      const text = #event-result.textContent;
      if (text && text !== last && !text.startsWith('Applying')) { last = text; refresh(); }
    }).observe(#event-result, { childList: true, characterData: true, subtree: true });
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
