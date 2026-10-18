/* Dashboard extras: KPIs, the services and people tree, people pills, and the dark "current answer" card.
   app.js still owns asking, drawing and the event panel. This file reads /api/overview (always JSON)
   and listens for the handover:answer, handover:event and handover:reset events that app.js dispatches. */
(() => {
  'use strict';
  const $ = (sel) => document.querySelector(sel);
  const DEFAULT_OWNER_SERVICE = 's-payments';

  const state = { overview: null, onPath: new Set() };

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

  // JSON only. A non-JSON reply (an HTML page, an error page) counts as a failure, not as "no data".
  async function getJson(path) {
    let delay = 400;
    let lastError = 'no response';
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const res = await fetch(path, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
        const type = res.headers.get('content-type') || '';
        if (res.ok && type.includes('application/json')) return await res.json();
        lastError = `HTTP ${res.status} (${type || 'no content type'})`;
      } catch (e) {
        lastError = e.message;
      }
      await new Promise((r) => setTimeout(r, delay));
      delay *= 3;
    }
    throw new Error(lastError);
  }

  function setError(show) {
    $('#kpi-error').hidden = !show;
    if (show) {
      ['#kpi-services', '#kpi-tickets', '#kpi-handovers'].forEach((id) => { $(id).textContent = '—'; });
    }
  }

  function renderPeople(people) {
    const pills = $('#people-pills');
    pills.replaceChildren(...people.map((p) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = p.name;
      b.setAttribute('data-initials', p.initials);
      if (state.onPath.has(p.id)) {
        b.classList.add('on-path');
        b.setAttribute('aria-current', 'true');
      }
      b.addEventListener('click', () => ask(`What breaks if ${p.name} leaves?`));
      return b;
    }));
  }

  function renderOverview(data) {
    state.overview = data;
    setError(false);
    $('#kpi-services').textContent = String(data.services.length);
    $('#kpi-tickets').textContent = String(data.open_tickets);
    $('#kpi-handovers').textContent = String(data.handovers);
    $('#tree-services').replaceChildren(...data.services.map((s) => item(s.name, () => ask(`Who owns ${s.name}?`))));
    $('#tree-people').replaceChildren(...data.people.map((p) => item(p.name, () => ask(`What breaks if ${p.name} leaves?`))));
    renderPeople(data.people);
  }

  async function refresh() {
    try {
      renderOverview(await getJson('/api/overview'));
    } catch (e) {
      console.error('Dashboard: could not load /api/overview:', e.message);
      setError(true);
    }
  }

  function setOwnerLine(text) {
    $('#hero-answer').textContent = text;
  }

  function ownerLine(person, since, source) {
    return `${person} · since ${since || 'unknown'} · [${source || 'seed data'}]`;
  }

  // The dark card follows the latest answer: an owner line when the answer names one, otherwise its text.
  function onAnswer(event) {
    const data = event.detail;
    state.onPath = new Set();
    if (data && data.path) {
      state.onPath = new Set(data.path.nodes.filter((n) => n.label === 'Person').map((n) => n.id));
    }
    if (state.overview) renderPeople(state.overview.people);
    if (!data) return setOwnerLine('Ask a question to see it here.');
    if (data.status === 'ok' && data.rows && data.rows.length && data.rows[0].person && data.rows[0].valid_from) {
      const row = data.rows[0];
      return setOwnerLine(ownerLine(row.person, row.valid_from, row.source));
    }
    if (data.status === 'ok') return setOwnerLine(data.answer || 'No answer.');
    return setOwnerLine(data.message || 'Pick one of the options in the answer.');
  }

  // After a handover, the new owner of the services it moved is the current answer.
  async function onEvent(event) {
    const d = event.detail;
    state.onPath = new Set([d.ids.to]);
    await refresh();
    setOwnerLine(ownerLine(d.event.to, d.event.effective, d.event_id));
  }

  function showDefaultOwner() {
    const owner = state.overview && state.overview.owners[DEFAULT_OWNER_SERVICE];
    if (owner) setOwnerLine(ownerLine(owner.person, owner.since, owner.source));
    else setOwnerLine('Ask a question to see it here.');
  }

  async function boot() {
    $('#kpi-retry').addEventListener('click', refresh);
    document.addEventListener('handover:answer', onAnswer);
    document.addEventListener('handover:event', onEvent);
    document.addEventListener('handover:reset', () => {
      state.onPath = new Set();
      refresh().then(showDefaultOwner);
    });
    await refresh();
    showDefaultOwner();
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
