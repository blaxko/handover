/* Handover demo page. No build step. Renders server text with textContent only. */
(() => {
  'use strict';

  const EXAMPLES = [
    { label: 'Who owns payments-api?', q: 'Who owns payments-api?' },
    { label: 'What breaks if TB leaves?', q: 'What breaks if TB leaves?' },
    { label: 'Who owns payments-api? (after the event)', q: 'Who owns payments-api?' },
    { label: 'Who owned payments-api on 2026-09-01?', q: 'Who owned payments-api on 2026-09-01?' },
    { label: 'Who owned ledger in 2025-06?', q: 'Who owned ledger in 2025-06?' },
  ];
  const DEMO_EVENT =
    "Tunde Bakare's last day was Friday. Ada Okafor takes over payments-api and ledger, effective 2026-10-17.";
  const COLOURS = {
    Person: { background: '#dbe7fd', border: '#2f6fed' },
    Service: { background: '#d7f0e7', border: '#1f8a70' },
    Ticket: { background: '#fde3cf', border: '#c2410c' },
    Message: { background: '#ebe4f8', border: '#7c5cbf' },
    Team: { background: '#e5e7eb', border: '#6b7280' },
    Entity: { background: '#e5e7eb', border: '#6b7280' },
  };

  const state = {
    token: null,
    focusId: 'p-tunde',
    base: null,      // {nodes, edges} from GET /graph
    path: null,      // {nodes, edges} from the last /ask, or null
    lastQuestion: '',
    network: null,
    nodes: null,
    edges: null,
  };

  const $ = (sel) => document.querySelector(sel);

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'onclick') node.addEventListener('click', value);
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of [].concat(children)) {
      if (child === null || child === undefined) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function setBody(container, nodes) {
    container.replaceChildren(...[].concat(nodes).filter(Boolean));
  }

  function notice(kind, text) {
    return el('p', { class: `notice ${kind}`, role: kind === 'err' ? 'alert' : 'status', text });
  }

  // One request helper. Errors carry the server's {error: {message}} text.
  async function api(path, { method = 'GET', body, token } = {}) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) headers['X-Demo-Token'] = token;
    let res;
    try {
      res = await fetch(path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      return { ok: false, status: 0, message: "Can't reach the server. Is it running on this address?" };
    }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      const err = data && data.error;
      let message = (err && err.message) || res.statusText || 'Request failed';
      if (res.status === 429) message = 'Rate limited by the LLM provider. Retry in a few seconds.';
      return { ok: false, status: res.status, message };
    }
    return { ok: true, status: res.status, data };
  }

  // ---- answer card ----

  function sourcesList(sources) {
    if (!sources || sources.length === 0) {
      return el('p', { class: 'muted', text: 'No message sources for this answer.' });
    }
    return el('ul', { class: 'sources', 'aria-label': 'Source messages' }, sources.map((s) =>
      el('li', {}, [
        el('code', { text: s.id }), ' ',
        el('span', { text: s.text }),
        el('div', { class: 'muted', text: [s.ts, s.channel].filter(Boolean).join(' · ') }),
      ])));
  }

  function cypherToggle(cypher) {
    if (!cypher) return null;
    return el('details', { class: 'cypher' }, [
      el('summary', { text: `Show Cypher (${cypher.id})` }),
      el('pre', { text: `// bound params\n${JSON.stringify(cypher.params, null, 2)}` }),
      el('pre', { text: cypher.template }),
    ]);
  }

  // Replace the ambiguous name in the question with the chosen id, then ask again.
  function reaskWith(chosenId, params) {
    let question = state.lastQuestion;
    const values = Object.values(params || {}).filter((v) => typeof v === 'string');
    for (const value of values) {
      const at = question.toLowerCase().indexOf(value.toLowerCase());
      if (at !== -1) {
        question = question.slice(0, at) + chosenId + question.slice(at + value.length);
        break;
      }
    }
    ask(question);
  }

  function chipRow(items, params) {
    return el('div', { class: 'chips' }, items.map((c) =>
      el('button', {
        type: 'button',
        class: 'chip',
        text: `${c.name} · ${c.id}`,
        onclick: () => reaskWith(c.id, params),
      })));
  }

  function renderAnswer(res) {
    const box = $('#answer');
    if (!res.ok) return setBody(box, notice('err', res.message));
    const d = res.data;

    if (d.status === 'ok') {
      const tags = el('div', { class: 'tags' }, [
        el('span', { class: 'tag', text: d.router === 'llm' ? 'via LLM' : 'via keyword router' }),
        el('span', { class: 'tag tag-quiet', text: `tool: ${d.tool}` }),
        d.router === 'keyword' && d.llm_note
          ? el('span', { class: 'tag tag-warn', text: `LLM unavailable, used keyword router (${d.llm_note})` })
          : null,
      ]);
      return setBody(box, [
        el('p', { class: 'answer-text', text: d.answer }),
        tags,
        sourcesList(d.sources),
        cypherToggle(d.cypher),
      ]);
    }
    if (d.status === 'clarify') {
      return setBody(box, [
        el('p', { text: `${d.message} Pick one:` }),
        chipRow(d.clarify, d.params),
      ]);
    }
    if (d.status === 'unknown') {
      const children = [el('p', { text: d.message })];
      if (d.suggestions && d.suggestions.length) {
        children.push(el('p', { class: 'muted', text: 'Did you mean:' }), chipRow(d.suggestions, d.params));
      }
      return setBody(box, children);
    }
    if (d.status === 'no_tool') {
      return setBody(box, [
        el('p', { text: d.message }),
        el('div', { class: 'examples' }, d.examples.map((q) =>
          el('button', { type: 'button', text: q, onclick: () => ask(q) }))),
      ]);
    }
    return setBody(box, notice('err', d.message || 'Something went wrong.'));
  }

  // ---- baseline card ----

  function renderBaseline(res) {
    const box = $('#baseline');
    if (!res.ok) return setBody(box, notice('err', `Baseline unavailable: ${res.message}`));
    const d = res.data;
    if (d.error) return setBody(box, [notice('warn', `Baseline could not phrase an answer: ${d.error}`), snippetList(d.snippets)]);
    return setBody(box, [
      el('p', { class: 'answer-text', text: d.answer || 'No answer.' }),
      el('p', { class: 'muted', text: 'Top 3 matching messages (full-text score and rank):' }),
      snippetList(d.snippets),
    ]);
  }

  function snippetList(snippets) {
    if (!snippets || snippets.length === 0) return el('p', { class: 'muted', text: 'No matching messages.' });
    return el('ul', { class: 'sources', 'aria-label': 'Baseline snippets' }, snippets.map((s) =>
      el('li', {}, [
        el('code', { text: `#${s.rank} ${s.id}` }), ' ',
        el('span', { text: s.text }),
        el('div', { class: 'muted', text: `score ${s.score}` }),
      ])));
  }

  // ---- graph view ----

  const edgeKey = (e) => `${e.from}|${e.to}|${e.type}`;

  function ensureNetwork() {
    if (state.network) return true;
    if (typeof vis === 'undefined') return false;
    state.nodes = new vis.DataSet();
    state.edges = new vis.DataSet();
    state.network = new vis.Network($('#graph'), { nodes: state.nodes, edges: state.edges }, {
      autoResize: true,
      physics: { stabilization: { iterations: 150 }, barnesHut: { gravitationalConstant: -4000, springLength: 130 } },
      nodes: { shape: 'box', margin: 8, font: { size: 13, color: '#15191f' }, borderWidth: 1 },
      edges: { arrows: 'to', smooth: { type: 'dynamic' }, font: { size: 11, align: 'middle', color: '#4b5563', strokeWidth: 0 } },
      interaction: { hover: true, tooltipDelay: 150 },
    });
    // Fit the view once the layout settles, so the graph is never drawn zoomed in.
    state.network.on('stabilizationIterationsDone', () => state.network.fit({ animation: false }));
    return true;
  }

  function drawGraph() {
    const pathNodeIds = new Set(state.path ? state.path.nodes.map((n) => n.id) : []);
    const pathEdgeKeys = new Set(state.path ? state.path.edges.map(edgeKey) : []);

    const nodeMap = new Map();
    for (const n of (state.base ? state.base.nodes : [])) nodeMap.set(n.id, n);
    for (const n of (state.path ? state.path.nodes : [])) nodeMap.set(n.id, n);

    const edgeMap = new Map();
    for (const e of (state.base ? state.base.edges : [])) edgeMap.set(edgeKey(e), e);
    for (const e of (state.path ? state.path.edges : [])) edgeMap.set(edgeKey(e), e);

    const nodeRows = [...nodeMap.values()].map((n) => {
      const colour = COLOURS[n.label] || COLOURS.Entity;
      const onPath = pathNodeIds.has(n.id);
      return {
        id: n.id,
        label: n.name,
        title: `${n.label}: ${n.name}`,
        color: colour,
        borderWidth: onPath ? 4 : 1,
        font: { bold: onPath },
        shadow: onPath,
      };
    });

    const edgeRows = [];
    for (const [key, e] of edgeMap) {
      if (!nodeMap.has(e.from) || !nodeMap.has(e.to)) continue;
      const onPath = pathEdgeKeys.has(key);
      const closed = !!e.closed;
      edgeRows.push({
        id: key,
        from: e.from,
        to: e.to,
        label: closed ? `${e.type} · closed` : e.type,
        dashes: closed ? [6, 4] : false,
        width: onPath ? 4 : 1.5,
        color: closed ? { color: '#8a929e', highlight: '#8a929e' } : { color: onPath ? '#2f6fed' : '#1f2937' },
        font: { color: closed ? '#6b7380' : '#4b5563', size: 11, strokeWidth: 0 },
      });
    }

    if (!ensureNetwork()) {
      setPathText();
      return;
    }
    state.nodes.clear();
    state.nodes.add(nodeRows);
    state.edges.clear();
    state.edges.add(edgeRows);
    state.network.stabilize(150);
    setPathText();
  }

  // Text version of the highlighted path, so colour is never the only signal.
  function setPathText() {
    const list = $('#path-text');
    if (!state.path || state.path.edges.length === 0) {
      return setBody(list, el('li', { text: 'No path for this view.' }));
    }
    const names = new Map(state.path.nodes.map((n) => [n.id, n.name]));
    setBody(list, state.path.edges.map((e) =>
      el('li', { text: `${names.get(e.from) || e.from} —${e.type}${e.closed ? ' (closed)' : ''}→ ${names.get(e.to) || e.to}` })));
  }

  async function loadGraph(focus) {
    const res = await api(`/graph?focus=${encodeURIComponent(focus)}&depth=2`);
    if (!res.ok) {
      setBody($('#path-text'), el('li', { text: `Graph unavailable: ${res.message}` }));
      return;
    }
    state.focusId = focus;
    state.base = res.data;
    drawGraph();
  }

  function focusFor(path) {
    const person = path.nodes.find((n) => n.label === 'Person');
    const service = path.nodes.find((n) => n.label === 'Service');
    return (person || service || path.nodes[0]).id;
  }

  // ---- ask ----

  function setBusy(busy, label) {
    const button = $('#ask-btn');
    button.disabled = busy;
    button.textContent = busy ? label : 'Ask';
    $('#answer-card').setAttribute('aria-busy', String(busy));
    $('#baseline-card').setAttribute('aria-busy', String(busy));
  }

  async function ask(question) {
    const text = (question || '').trim();
    if (!text) return;
    state.lastQuestion = text;
    $('#q').value = text;
    setBusy(true, 'Asking…');
    setBody($('#answer'), el('p', { class: 'muted', text: 'Asking the graph…' }));
    setBody($('#baseline'), el('p', { class: 'muted', text: 'Asking the keyword baseline…' }));

    const [graph, baseline] = await Promise.all([
      api('/ask', { method: 'POST', body: { question: text } }),
      api('/baseline', { method: 'POST', body: { question: text } }),
    ]);
    setBusy(false, '');
    renderAnswer(graph);
    renderBaseline(baseline);

    if (graph.ok && graph.data.status === 'ok' && graph.data.path && graph.data.path.nodes.length) {
      state.path = graph.data.path;
      await loadGraph(focusFor(state.path));
    } else {
      state.path = null;
      drawGraph();
    }
  }

  // ---- change event, reset, token ----

  function showTokenField(show) {
    $('#token-row').hidden = !show;
  }

  // True when no token is known yet. Shows the token field so the user can paste it.
  function needToken() {
    if (state.token) return false;
    showTokenField(true);
    $('#token').focus();
    return true;
  }

  function eventSummary(d) {
    const closed = d.closed.length;
    const opened = d.opened.length;
    const moved = d.tickets_moved.map((t) => t.ticket_id).join(', ') || 'none';
    const to = [...new Set(d.tickets_moved.map((t) => t.to))].join(', ');
    const tail = to ? ` → ${to}` : '';
    return `closed ${closed} · opened ${opened} · moved ${moved}${tail}`;
  }

  async function applyEvent(payload) {
    const out = $('#event-result');
    if (needToken()) {
      out.className = 'notice warn';
      out.textContent = 'Enter the demo token below, then apply again.';
      return;
    }
    out.className = 'notice';
    out.textContent = 'Applying…';
    const res = await api('/events', { method: 'POST', body: payload, token: state.token });
    if (!res.ok) {
      if (res.status === 401) showTokenField(true);
      out.className = 'notice err';
      out.textContent = res.message;
      return;
    }
    const d = res.data;
    if (d.status === 'applied') {
      out.className = 'notice ok';
      out.textContent = eventSummary(d) + (d.notes && d.notes.length ? ` (${d.notes.join('; ')})` : '');
      state.path = null;
      await loadGraph(state.focusId);
    } else if (d.status === 'already_applied') {
      out.className = 'notice warn';
      out.textContent = 'Already applied: this exact event is in the graph, so nothing changed.';
    } else {
      out.className = 'notice err';
      out.textContent = `Not applied: ${(d.reasons || []).join('; ')}`;
    }
  }

  async function reset() {
    if (needToken()) return setBody($('#event-result'), notice('warn', 'Enter the demo token below, then reset again.'));
    const res = await api('/reset', { method: 'POST', token: state.token });
    if (!res.ok) {
      if (res.status === 401) showTokenField(true);
      return setBody($('#event-result'), notice('err', res.message));
    }
    state.path = null;
    setBody($('#answer'), el('p', { class: 'muted', text: 'Demo reset. Ask a question to start again.' }));
    setBody($('#baseline'), el('p', { class: 'muted', text: 'Demo reset.' }));
    $('#event-text').value = DEMO_EVENT;
    setBody($('#event-result'), notice('ok', 'Demo reset: the seed is loaded again.'));
    await loadGraph('p-tunde');
  }

  // ---- boot ----

  async function health() {
    const pill = $('#health');
    const res = await api('/health');
    if (res.ok) {
      pill.dataset.state = 'ok';
      pill.textContent = 'Graph connected';
    } else {
      pill.dataset.state = 'down';
      pill.textContent = res.message;
    }
  }

  async function boot() {
    $('#event-text').value = DEMO_EVENT;
    const examples = $('#examples');
    setBody(examples, EXAMPLES.map((ex) => el('button', { type: 'button', text: ex.label, onclick: () => ask(ex.q) })));

    const cfg = await api('/config');
    if (cfg.ok && cfg.data.demo_token) {
      state.token = cfg.data.demo_token;
    } else {
      showTokenField(true);
    }
    health();
    loadGraph('p-tunde');
  }

  $('#ask-form').addEventListener('submit', (e) => { e.preventDefault(); ask($('#q').value); });
  $('#apply').addEventListener('click', () => applyEvent({ text: $('#event-text').value.trim() }));
  $('#apply-demo').addEventListener('click', () => applyEvent({ demo: true }));
  $('#reset').addEventListener('click', reset);
  $('#token-save').addEventListener('click', () => {
    const value = $('#token').value.trim();
    if (value) {
      state.token = value;
      showTokenField(false);
      $('#token').value = '';
    }
  });

  document.addEventListener('DOMContentLoaded', boot);
})();
