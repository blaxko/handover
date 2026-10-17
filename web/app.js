/* Handover demo page. No build step. Server text goes in with textContent only. */
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
  const DEFAULT_FOCUS = ['p-tunde'];
  const MAX_FOCUS = 6;
  const COLOURS = {
    Person: { background: '#dbe7fd', border: '#2f6fed' },
    Service: { background: '#d7f0e7', border: '#1f8a70' },
    Ticket: { background: '#fde3cf', border: '#c2410c' },
    Message: { background: '#ebe4f8', border: '#7c5cbf' },
    Team: { background: '#e5e7eb', border: '#6b7280' },
    Entity: { background: '#e5e7eb', border: '#6b7280' },
  };

  // state.view: nodes and edges around the focus ids. state.full: whole graph (lazy).
  // state.hl: what to highlight: {nodes, edges} from an answer, or {mode: 'event', effective}.
  const state = {
    token: null,
    focusIds: DEFAULT_FOCUS,
    view: { nodes: new Map(), edges: new Map() },
    full: null,
    showFull: false,
    hl: null,
    lastQuestion: '',
    network: null,
    nodes: null,
    edges: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const edgeKey = (e) => `${e.from}|${e.to}|${e.type}`;

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
      return setBody(box, [el('p', { text: `${d.message} Pick one:` }), chipRow(d.clarify, d.params)]);
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

  // The highlighted edges: from the answer path, or the open edges an event created.
  function highlightedEdges() {
    if (!state.hl) return [];
    if (state.hl.mode === 'event') {
      return [...state.view.edges.values()].filter((e) =>
        e.valid_from === state.hl.effective && !e.closed);
    }
    return state.hl.edges;
  }

  function highlightedNodeIds() {
    if (!state.hl) return new Set();
    if (state.hl.mode === 'event') {
      const ids = new Set();
      for (const e of highlightedEdges()) { ids.add(e.from); ids.add(e.to); }
      return ids;
    }
    return new Set(state.hl.nodes.map((n) => n.id));
  }

  // Focused subgraph: the answer's path nodes (or, after an event, the people, services and
  // tickets it touched), plus their direct neighbours. Nothing further out.
  function focusedSubgraph() {
    const answerMode = state.hl && state.hl.mode === 'answer';
    const core = answerMode
      ? new Set(state.hl.nodes.map((n) => n.id))
      : new Set(state.focusIds);
    const nodes = new Map();
    const edges = new Map();
    for (const e of state.view.edges.values()) {
      if (core.has(e.from) || core.has(e.to)) edges.set(edgeKey(e), e);
    }
    for (const id of core) {
      const n = state.view.nodes.get(id);
      if (n) nodes.set(id, n);
    }
    for (const e of edges.values()) {
      for (const id of [e.from, e.to]) {
        if (!nodes.has(id) && state.view.nodes.has(id)) nodes.set(id, state.view.nodes.get(id));
      }
    }
    for (const e of highlightedEdges()) edges.set(edgeKey(e), e);
    // Answer path nodes always draw, even if the focus views did not fetch them.
    if (state.hl && state.hl.mode !== 'event') {
      for (const n of state.hl.nodes) if (!nodes.has(n.id)) nodes.set(n.id, n);
    }
    return { nodes, edges };
  }

  function visibleGraph() {
    if (state.showFull && state.full) return state.full;
    return focusedSubgraph();
  }

  function ensureNetwork() {
    if (state.network) return true;
    if (typeof vis === 'undefined') return false;
    state.nodes = new vis.DataSet();
    state.edges = new vis.DataSet();
    state.network = new vis.Network($('#graph'), { nodes: state.nodes, edges: state.edges }, {
      autoResize: true,
      physics: { stabilization: { iterations: 150 }, barnesHut: { gravitationalConstant: -4000, springLength: 130 } },
      nodes: { shape: 'box', margin: 8, font: { size: 14, color: '#15191f' }, borderWidth: 1 },
      edges: { arrows: 'to', smooth: { type: 'dynamic' }, font: { size: 12, align: 'middle', color: '#4b5563', strokeWidth: 0 } },
      interaction: { hover: true, tooltipDelay: 150 },
    });
    state.network.on('stabilizationIterationsDone', () => state.network.fit({ animation: false }));
    return true;
  }

  function draw() {
    // Path text first: it must show even if the canvas cannot draw.
    setPathText();
    const graphBox = $('#graph');
    const { nodes, edges } = visibleGraph();
    const hlNodes = highlightedNodeIds();
    const hlEdges = new Set(highlightedEdges().map(edgeKey));

    if (!ensureNetwork()) {
      showGraphMessage('warn', 'The graph library did not load from cdnjs. The answer path is listed below as text.');
      return;
    }
    showGraphMessage(null, '');

    try {
      const nodeRows = [...nodes.values()].map((n) => {
        const onPath = hlNodes.has(n.id);
        return {
          id: n.id,
          label: n.label === 'Message' ? n.id : n.name,
          title: `${n.label}: ${n.name}`,
          color: COLOURS[n.label] || COLOURS.Entity,
          borderWidth: onPath ? 4 : 1,
          font: { bold: onPath },
          shadow: onPath,
        };
      });
      const edgeRows = [...edges.entries()]
        .filter(([, e]) => nodes.has(e.from) && nodes.has(e.to))
        .map(([key, e]) => {
          const onPath = hlEdges.has(key);
          const closed = !!e.closed;
          let label = '';
          if (onPath) label = closed ? `${e.type} · closed` : e.type;
          else if (closed) label = 'closed';
          return {
            id: key,
            from: e.from,
            to: e.to,
            label,
            dashes: closed ? [6, 4] : false,
            width: onPath ? 4 : closed ? 1.5 : 1.25,
            color: onPath && !closed
              ? { color: '#2f6fed', highlight: '#2f6fed' }
              : closed
                ? { color: '#8a929e', highlight: '#8a929e' }
                : { color: '#1f2937', highlight: '#1f2937' },
            font: { color: closed ? '#5b6370' : '#2f6fed', size: 12, strokeWidth: 0 },
          };
        });
      state.nodes.clear();
      state.nodes.add(nodeRows);
      state.edges.clear();
      state.edges.add(edgeRows);
      state.network.stabilize(150);
    } catch (err) {
      console.error('graph draw failed', err);
      showGraphMessage('err', 'The graph could not be drawn. The answer path is listed below as text.');
    }
  }

  // Messages sit above the canvas, so vis-network's own DOM is never touched.
  function showGraphMessage(kind, text) {
    const box = $('#graph-msg');
    box.hidden = !kind;
    box.className = kind ? `notice ${kind}` : 'notice';
    box.textContent = text;
  }

  // Text version of the highlighted path, so colour is never the only signal.
  function setPathText() {
    const list = $('#path-text');
    const edges = highlightedEdges();
    if (edges.length === 0) {
      return setBody(list, el('li', { text: 'No path for this view. Ask a question to light up its path.' }));
    }
    const names = new Map();
    for (const n of state.view.nodes.values()) names.set(n.id, n.name);
    for (const n of (state.hl && state.hl.nodes) || []) names.set(n.id, n.name);
    setBody(list, edges.map((e) =>
      el('li', { text: `${names.get(e.from) || e.from} —${e.type}${e.closed ? ' (closed)' : ''}→ ${names.get(e.to) || e.to}` })));
  }

  // Fetch the depth-2 views around each focus id and merge them.
  async function loadFocus(ids) {
    const focus = [...new Set(ids)].slice(0, MAX_FOCUS);
    const results = await Promise.all(focus.map((id) =>
      api(`/graph?focus=${encodeURIComponent(id)}&depth=2`)));
    const failed = results.find((r) => !r.ok);
    if (failed) {
      setBody($('#path-text'), el('li', { text: `Graph unavailable: ${failed.message}` }));
      return;
    }
    const nodes = new Map();
    const edges = new Map();
    for (const r of results) {
      for (const n of r.data.nodes) nodes.set(n.id, n);
      for (const e of r.data.edges) edges.set(edgeKey(e), e);
    }
    state.focusIds = focus;
    state.view = { nodes, edges };
    draw();
  }

  async function ensureFullGraph() {
    if (state.full) return true;
    const res = await api('/graph/all');
    if (!res.ok) {
      setBody($('#path-text'), el('li', { text: `Full graph unavailable: ${res.message}` }));
      return false;
    }
    const nodes = new Map(res.data.nodes.map((n) => [n.id, n]));
    const edges = new Map(res.data.edges.map((e) => [edgeKey(e), e]));
    state.full = { nodes, edges };
    return true;
  }

  async function toggleFull() {
    const button = $('#toggle-full');
    if (!state.showFull && !(await ensureFullGraph())) return;
    state.showFull = !state.showFull;
    button.setAttribute('aria-pressed', String(state.showFull));
    button.textContent = state.showFull ? 'Show focused view' : 'Show full graph';
    draw();
  }

  // ---- ask ----

  function setBusy(busy, label) {
    const button = $('#ask-btn');
    button.disabled = busy;
    button.textContent = busy ? label : 'Ask';
    $('#answer-card').setAttribute('aria-busy', String(busy));
    $('#baseline-card').setAttribute('aria-busy', String(busy));
  }

  // Focus on the people, services and tickets the answer path touches.
  function focusFromPath(path) {
    return path.nodes
      .filter((n) => ['Person', 'Service', 'Ticket'].includes(n.label))
      .map((n) => n.id);
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

    if (graph.ok && graph.data.status === 'ok' && graph.data.path && graph.data.path.edges.length) {
      state.hl = { mode: 'answer', nodes: graph.data.path.nodes, edges: graph.data.path.edges };
      await loadFocus(focusFromPath(graph.data.path));
    } else {
      state.hl = null;
      draw();
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
      state.hl = { mode: 'event', effective: d.ids.effective };
      const focus = [d.ids.from, d.ids.to, ...d.ids.services, ...d.ids.tickets];
      state.full = null;
      await loadFocus(focus);
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
    state.hl = null;
    state.full = null;
    setBody($('#answer'), el('p', { class: 'muted', text: 'Demo reset. Ask a question to start again.' }));
    setBody($('#baseline'), el('p', { class: 'muted', text: 'Demo reset.' }));
    $('#event-text').value = DEMO_EVENT;
    setBody($('#event-result'), notice('ok', 'Demo reset: the seed is loaded again.'));
    await loadFocus(DEFAULT_FOCUS);
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
    setBody($('#examples'), EXAMPLES.map((ex) => el('button', { type: 'button', text: ex.label, onclick: () => ask(ex.q) })));

    const cfg = await api('/config');
    if (cfg.ok && cfg.data.demo_token) {
      state.token = cfg.data.demo_token;
    } else {
      showTokenField(true);
    }
    health();
    loadFocus(DEFAULT_FOCUS);
  }

  $('#ask-form').addEventListener('submit', (e) => { e.preventDefault(); ask($('#q').value); });
  $('#apply').addEventListener('click', () => applyEvent({ text: $('#event-text').value.trim() }));
  $('#apply-demo').addEventListener('click', () => applyEvent({ demo: true }));
  $('#reset').addEventListener('click', reset);
  $('#toggle-full').addEventListener('click', toggleFull);
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
