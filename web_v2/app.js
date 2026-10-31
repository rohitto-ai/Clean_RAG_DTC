/* ===========================================================================
   DTC Workshop (UI v2) — offline, no build step, no dependencies.
   Consumes ONLY the existing Phase 10.3 / 13.1 / 13.3 endpoints:
     /health /fleet /vehicle/{id} /verify-code /symptom /audit
     /replay/start|stop|reset|status /scenarios
   Every decision shown here is made by the API; this file only renders it.
   =========================================================================== */
'use strict';

/* ------------------------------------------------------------------ utils */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'text') n.textContent = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === '') continue;
    n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return n;
}
const clear = (n) => { while (n.firstChild) n.removeChild(n.firstChild); };
const icon = (id, cls) => {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  if (cls) s.setAttribute('class', cls);
  s.setAttribute('aria-hidden', 'true');
  const u = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  u.setAttribute('href', `#${id}`);
  s.append(u);
  return s;
};
const say = (msg) => { $('#live').textContent = msg; };
const num = (n) => (n === null || n === undefined ? '—' : Number(n).toLocaleString());

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'content-type': 'application/json' },
    ...opts,
  });
  let body = null;
  const txt = await res.text();
  try { body = txt ? JSON.parse(txt) : null; } catch { body = { detail: txt }; }
  if (!res.ok) {
    const detail = body && (body.detail || body.message) ? (body.detail || body.message) : res.statusText;
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.status = res.status;
    throw err;
  }
  return body;
}

/* --------------------------------------------------------- shared pieces */
const SEVERITIES = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

/* A severity is never colour alone: the chip always prints its name. A vehicle
   with no rated rows gets a plain dash, not a grey LOW, which would read as a
   real rating. */
function sevChip(sev) {
  if (!sev) return el('span', { class: 'muted', text: '—' });
  return el('span', { class: `chip ${sev}`, text: sev });
}
const outcomeChip = (o) => (o
  ? el('span', { class: `chip plain ${o}`, text: o.replace(/_/g, ' ') })
  : el('span', { class: 'muted', text: '—' }));

function skeleton(kind = 'line', n = 3) {
  const box = el('div');
  for (let i = 0; i < n; i += 1) box.append(el('div', { class: `skel ${kind}` }));
  return box;
}
const emptyState = (text, hint) => el('div', { class: 'empty' },
  icon('i-search'), el('p', { text }), hint ? el('p', { class: 'small', text: hint }) : null);

function showError(host, e) {
  clear(host);
  host.append(el('div', { class: 'msg error' },
    el('div', {}, el('div', { class: 'msg-label', text: 'Could not load' }),
      el('div', { text: e.status === 404 ? 'Not found. Check the vehicle id or registration.' : e.message }),
      el('div', { class: 'small', text: 'The server may still be warming up — try again in a moment.' }))));
}

/* The illustrative cost panel is always visibly separate and always labelled:
   it is owned by another team and is not in the manual. */
function costPanel(c) {
  if (!c || !c.figures) return null;
  const f = c.figures;
  return el('div', { class: 'cost' },
    el('div', { class: 'cost-label', text: c.label || 'Illustrative — not from the manual' }),
    el('dl', {},
      el('dt', { text: 'Labour' }), el('dd', { text: `${f.labour_hours ?? '—'} h` }),
      el('dt', { text: 'Parts (INR)' }),
      el('dd', { text: `${num(f.parts_cost_min_inr)} – ${num(f.parts_cost_max_inr)}` }),
      el('dt', { text: 'Turnaround' }), el('dd', { text: `${f.tat_hours ?? '—'} h` }),
      el('dt', { text: 'Applies to' }), el('dd', { text: f.applies_to || c.subsystem || '—' })),
    el('p', { class: 'small muted', text: f.basis || c.basis || '' }));
}

/* A branch is read as pass or fail from the manual's own words. */
function branchClass(text) {
  return /if no\b|if not\b|unavailable|still present|fail/i.test(text) ? 'fail' : 'pass';
}

function repairTimeline(fb) {
  const ol = el('ol', { class: 'timeline' });
  for (const s of fb.steps || []) {
    const li = el('li', { 'data-n': s.n });
    li.append(el('div', { text: s.text }));
    if (s.spec) li.append(el('div', { class: 'spec', text: `spec: ${s.spec}` }));
    if (s.branch) {
      li.append(el('span', { class: `branch ${branchClass(s.branch)}` },
        el('span', { text: s.branch })));
    }
    ol.append(li);
  }
  return ol;
}

function fixBlockBody(fb) {
  const box = el('div');
  box.append(el('div', { class: 'row small muted' },
    el('span', { text: `System: ${fb.system}` }),
    el('span', { text: `MIL: ${fb.MIL}` }),
    el('span', { text: `Effect: ${fb.effect}` })));
  if ((fb.cause || []).length) {
    box.append(el('h4', { text: 'Likely causes' }),
      el('ul', { class: 'small' }, (fb.cause || []).map((c) => el('li', { text: c }))));
  }
  if ((fb.checkpoints || []).length) {
    box.append(el('h4', { text: 'Checkpoints' }),
      el('ul', { class: 'small' }, (fb.checkpoints || []).map((c) => el('li', { text: c }))));
  }
  if ((fb.steps || []).length) {
    box.append(el('h4', { text: 'Repair procedure' }), repairTimeline(fb));
  }
  const foot = el('div', { class: 'row small muted' });
  if ((fb.pins || []).length) {
    foot.append(el('span', { text: 'Pins:' }),
      el('span', { class: 'pins' }, (fb.pins || []).map((p) => el('span', { class: 'pin', text: p }))));
  }
  foot.append(el('span', { text: `Manual page ${fb.page}` }));
  if (fb.schematic_page) foot.append(el('span', { text: `Schematic page ${fb.schematic_page}` }));
  box.append(foot);
  return box;
}

/* ------------------------------------------------------------ job card */
function printJobCard(fb, cost, context) {
  const host = $('#jobcard');
  clear(host);
  host.append(
    el('div', { class: 'jc-head' },
      el('h1', { text: `Job card — ${fb.code_full}` }),
      el('div', { class: 'jc-grid' },
        el('div', { text: `Fault: ${fb.description}` }),
        el('div', { text: `System: ${fb.system}` }),
        el('div', { text: `Manual page: ${fb.page}` }),
        el('div', { text: `MIL: ${fb.MIL}   Effect: ${fb.effect}` }),
        el('div', { text: context || '' }),
        el('div', { text: `Printed: ${new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC` }))),
    (fb.cause || []).length ? el('div', {}, el('strong', { text: 'Likely causes: ' }),
      (fb.cause || []).join('; ')) : null,
    (fb.checkpoints || []).length ? el('div', {}, el('strong', { text: 'Checkpoints: ' }),
      (fb.checkpoints || []).join('; ')) : null,
    el('div', {}, el('strong', { text: 'Procedure' })),
    el('ol', {}, (fb.steps || []).map((s) => el('li', {
      text: `${s.text}${s.spec ? ` (spec: ${s.spec})` : ''}${s.branch ? ` — ${s.branch}` : ''}`,
    }))),
    (fb.pins || []).length ? el('div', {}, el('strong', { text: 'Pins: ' }), fb.pins.join(', ')) : null,
    cost && cost.figures ? el('div', { class: 'jc-note' },
      `ILLUSTRATIVE, not from the manual — labour ${cost.figures.labour_hours} h, parts INR `
      + `${num(cost.figures.parts_cost_min_inr)}–${num(cost.figures.parts_cost_max_inr)}, `
      + `turnaround ${cost.figures.tat_hours} h.`) : null,
    el('div', { class: 'jc-note',
      text: 'Synthetic — illustrative demo data. No proprietary TATA data is used. '
            + 'Steps are reproduced verbatim from the manual record; no text is model-generated.' }),
    el('div', { class: 'jc-sign' },
      el('div', { text: 'Technician' }), el('div', { text: 'Supervisor' })));
  window.print();
}

/* ------------------------------------------------------------ why panel */
function openWhy(why) {
  const body = $('#why-body');
  clear(body);
  if (!why) { body.append(emptyState('No trace for this view.')); }
  else {
    const sect = (title, ...kids) => el('div', { class: 'why-sect' },
      el('h3', { text: title }), ...kids);
    body.append(sect('Route', el('div', { class: 'mono', text: why.route || '—' })));

    if ((why.ladder || []).length) {
      body.append(sect('Ladder', el('ol', { class: 'small' }, why.ladder.map((r) => el('li', {
        text: typeof r === 'string' ? r
          : `${r.rung || r.outcome || ''}${r.result ? ` → ${r.result}` : ''}`,
      })))));
    }
    const ret = why.retrieval || {};
    const retBox = el('div', { class: 'small' },
      el('div', { text: `used: ${ret.used === true ? 'yes' : 'no'}` }),
      ret.router_mode ? el('div', { text: `router mode: ${ret.router_mode}` }) : null,
      ret.note ? el('div', { class: 'muted', text: ret.note }) : null);
    if ((ret.ranks || []).length) {
      retBox.append(el('ol', { class: 'small' }, ret.ranks.map((r) => el('li', {},
        el('code', { text: r.code_full }), ' ', el('span', { class: 'muted', text: r.why_retrieved || '' })))));
    }
    body.append(sect('Retrieval', retBox));

    const g = why.gate || {};
    body.append(sect('Relevance gate', el('div', { class: 'small' },
      el('div', { text: `applied: ${g.applied ? 'yes' : 'no'} — decision: ${g.decision || '—'}` }),
      (g.reasons || []).filter(Boolean).length
        ? el('div', { text: `reasons: ${g.reasons.filter(Boolean).join(', ')}` }) : null,
      Object.keys(g.signals || {}).length
        ? el('div', { class: 'mono', text: Object.entries(g.signals)
          .map(([k, v]) => `${k}=${typeof v === 'number' ? v.toFixed(3) : v}`).join('  ') }) : null)));

    if ((why.citations || []).length) {
      body.append(sect('Citations', el('ul', { class: 'small' }, why.citations.map((c) => el('li', {
        text: c.citation || `${c.code_full}, manual page ${c.manual_page}`,
      })))));
    }
    if ((why.severity_reasons || []).length) {
      body.append(sect('Severity', el('ul', { class: 'small' }, why.severity_reasons.map((r) => el('li', {
        text: typeof r === 'string' ? r
          : `SPN ${r.spn}/${r.fmi} → ${r.severity}: ${(r.reasons || []).join(', ')}`,
      })))));
    }
    body.append(sect('Every step, labelled',
      el('ul', { class: 'steps' }, (why.steps || []).map((s) => el('li', {},
        el('span', { class: `tag ${s.label === 'AI' ? 'MODEL' : 'RULE'}`,
          text: s.label === 'AI' ? 'MODEL' : 'RULE' }),
        el('span', { text: s.step }))))));
  }
  openDrawer('why');
}

/* -------------------------------------------------------------- drawers */
let lastFocus = null;
function openDrawer(id) {
  lastFocus = document.activeElement;
  $(`#${id}`).setAttribute('data-open', '1');
  $('#scrim').hidden = false;
  const btn = $(`#${id} .btn.icon`);
  if (btn) btn.focus();
}
function closeDrawers() {
  for (const d of $$('.drawer')) d.setAttribute('data-open', '0');
  $('#scrim').hidden = true;
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}

/* ============================================================ FLEET view */
const fleetState = { severity: '', region: '', outcome: '', sort: 'vehicle', dir: 1, data: null,
  timer: null, paused: false };

function fleetQuery() {
  const p = new URLSearchParams();
  for (const k of ['severity', 'outcome']) if (fleetState[k]) p.set(k, fleetState[k]);
  const q = p.toString();
  return `/fleet${q ? `?${q}` : ''}`;
}

async function viewFleet() {
  const host = $('#view');
  clear(host);
  host.append(el('div', { class: 'view-head' }, el('h1', { text: 'Fleet' }),
    el('p', { text: 'Synthetic telematics, resolved by rule into advisories. Click a row to open the vehicle.' })));
  const kpis = el('div', { class: 'kpis' }, skeleton('tile', 4));
  const controls = el('div', { class: 'card' }, skeleton('line', 1));
  const tableHost = el('div', {}, skeleton('block', 1));
  host.append(kpis, controls, tableHost);
  try {
    const f = await api(fleetQuery());
    fleetState.data = f;
    renderFleet(kpis, controls, tableHost, f);
  } catch (e) { showError(tableHost, e); }
}

function renderFleet(kpis, controls, tableHost, f) {
  const sev = f.by_worst_severity || {};
  clear(kpis);
  const withFaults = Object.values(f.per_vehicle || {}).filter((v) => v.episodes > 0).length;
  kpis.append(
    kpiTile('Vehicles with active faults', withFaults, ''),
    kpiTile('Critical', sev.CRITICAL || 0, 'is-crit'),
    kpiTile('High', sev.HIGH || 0, 'is-high'),
    kpiTile('Medium', sev.MEDIUM || 0, 'is-med'),
    kpiTile('Low', sev.LOW || 0, 'is-low'),
    kpiTile('Episodes', f.episodes, ''));

  clear(controls);
  const outcomes = Object.keys(f.by_outcome || {}).sort();
  const sel = (label, key, opts) => {
    const s = el('select', { 'aria-label': label, onchange: (ev) => {
      fleetState[key] = ev.target.value; viewFleet();
    } }, el('option', { value: '', text: `${label}: all` }),
    opts.map((o) => el('option', { value: o, text: o.replace(/_/g, ' '), selected: fleetState[key] === o })));
    return s;
  };
  controls.append(el('div', { class: 'row spread' },
    el('div', { class: 'row' },
      sel('Severity', 'severity', SEVERITIES),
      sel('Outcome', 'outcome', outcomes),
      el('button', { class: 'btn small', text: 'Clear filters', onclick: () => {
        fleetState.severity = ''; fleetState.region = ''; fleetState.outcome = ''; viewFleet();
      } })),
    el('button', { class: 'btn small', onclick: () => openWhy(f.why) },
      icon('i-why'), ' Why this answer?')));
  controls.append(replayBar());

  clear(tableHost);
  const rows = Object.entries(f.per_vehicle || {}).map(([id, v]) => ({
    vehicle: id, registration: v.registration || '',
    episodes: v.episodes || 0, severity: v.worst_severity || '',
    outcomes: Object.entries(v.outcomes || {}).map(([k, n]) => `${k.replace(/_/g, ' ')}×${n}`).join(', '),
  }));
  if (!rows.length) {
    tableHost.append(emptyState('No vehicles match these filters.', 'Clear the filters to see the whole fleet.'));
    return;
  }
  const rank = (s) => (s ? SEVERITIES.indexOf(s) : SEVERITIES.length);
  rows.sort((a, b) => {
    const k = fleetState.sort;
    const va = k === 'severity' ? rank(a.severity) : a[k];
    const vb = k === 'severity' ? rank(b.severity) : b[k];
    if (va === vb) return a.vehicle.localeCompare(b.vehicle);
    return (va > vb ? 1 : -1) * fleetState.dir;
  });
  const th = (label, key, cls) => el('th', { class: cls }, el('button', {
    'aria-label': `Sort by ${label}`,
    onclick: () => {
      if (fleetState.sort === key) fleetState.dir *= -1; else { fleetState.sort = key; fleetState.dir = 1; }
      viewFleet();
    },
  }, el('span', { text: label }),
  fleetState.sort === key ? el('span', { text: fleetState.dir > 0 ? '▲' : '▼' }) : null));
  const tbody = el('tbody');
  for (const r of rows) {
    tbody.append(el('tr', { class: 'clickable', tabindex: '0', role: 'button',
      'aria-label': `Open ${r.vehicle}`,
      onclick: () => openVehicle(r.vehicle),
      onkeydown: (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openVehicle(r.vehicle); } } },
    el('td', { class: 'mono', text: r.vehicle }),
    el('td', { class: 'mono', text: r.registration }),
    el('td', { class: 'num', text: r.episodes }),
    el('td', {}, sevChip(r.severity)),
    el('td', { class: 'small muted', text: r.outcomes })));
  }
  tableHost.append(el('div', { class: 'table-wrap' },
    el('table', {}, el('thead', {}, el('tr', {},
      th('Vehicle', 'vehicle'), th('Registration', 'registration'),
      th('Faults', 'episodes', 'num'), th('Worst severity', 'severity'),
      el('th', { text: 'Outcomes' }))), tbody)),
  el('p', { class: 'small muted', text: `${rows.length} vehicles · ${num(f.rows)} rows in scope · `
      + `${num(f.rows_rejected)} rejected · ${f.label || 'synthetic — illustrative'}` }));
}

const kpiTile = (k, n, cls) => el('div', { class: `kpi ${cls}` },
  el('div', { class: 'n', text: num(n) }), el('div', { class: 'k', text: k }));

function replayBar() {
  const box = el('div', { class: 'replay', id: 'replay-bar' });
  const bar = el('div', { class: 'bar' }, el('i', { id: 'replay-fill' }));
  const label = el('span', { class: 'small muted', id: 'replay-label', text: 'Replay idle' });
  const start = el('button', { class: 'btn small primary', text: 'Start replay',
    onclick: () => replay('start', { rows_per_tick: 40, tick_seconds: 1 }) });
  const pause = el('button', { class: 'btn small', text: 'Pause', onclick: () => replay('stop') });
  const resume = el('button', { class: 'btn small',
    text: 'Resume (restarts the feed)',
    title: 'The API has no resume: POST /replay/start begins the pass again from the first row.',
    onclick: () => replay('start', { rows_per_tick: 40, tick_seconds: 1 }) });
  const reset = el('button', { class: 'btn small', text: 'Reset', onclick: () => replay('reset') });
  box.append(start, pause, resume, reset, bar, label);
  pollReplay();
  return box;
}

async function replay(action, body) {
  try {
    await api(`/replay/${action}`, { method: 'POST', body: JSON.stringify(body || {}) });
    say(`Replay ${action}`);
  } catch (e) { say(`Replay ${action}: ${e.message}`); }
  pollReplay();
  if (action !== 'start') viewFleet();
}

async function pollReplay() {
  if (fleetState.timer) { clearTimeout(fleetState.timer); fleetState.timer = null; }
  let st;
  try { st = await api('/replay/status'); } catch { return; }
  const fill = $('#replay-fill');
  const label = $('#replay-label');
  if (!fill || !label) return;
  const pct = Math.round((st.progress || 0) * 100);
  fill.style.width = `${pct}%`;
  label.textContent = st.active
    ? `● LIVE ${num(st.rows_replayed)} / ${num(st.rows_total)} rows (${pct}%)`
    : (st.rows_replayed ? `Paused at ${num(st.rows_replayed)} / ${num(st.rows_total)} rows` : 'Replay idle');
  label.className = st.active ? 'small live-dot' : 'small muted';
  /* poll /fleet only while a replay is actually running (same rule as the classic UI) */
  if (st.active) {
    fleetState.timer = setTimeout(() => { if ($('#replay-bar')) { viewFleet(); } }, 3000);
  }
}

/* ========================================================== VEHICLE view */
async function openVehicle(ident) {
  selectNav('vehicle');
  const host = $('#view');
  clear(host);
  host.append(el('div', { class: 'view-head' }, el('h1', { text: 'Vehicle' }),
    el('p', { text: 'Each fault episode is shown as the chain the rules walked: SPN/FMI → P-code → ladder outcome → advisory.' })));
  const form = el('form', { class: 'row', onsubmit: (ev) => { ev.preventDefault(); openVehicle($('#v-id').value.trim()); } },
    el('label', { class: 'sr-only', for: 'v-id', text: 'Vehicle id or registration' }),
    el('input', { id: 'v-id', value: ident || '', placeholder: 'DEMO-MAT-0001 or a registration' }),
    el('button', { class: 'btn primary', type: 'submit', text: 'Open' }));
  host.append(el('div', { class: 'card' }, form));
  if (!ident) { host.append(emptyState('Enter a vehicle id or registration.', 'Or pick a row in the Fleet view.')); return; }
  const body = el('div', {}, skeleton('block', 2));
  host.append(body);
  try {
    const v = await api(`/vehicle/${encodeURIComponent(ident)}`);
    renderVehicle(body, v);
  } catch (e) { showError(body, e); }
}

function renderVehicle(host, v) {
  clear(host);
  host.append(el('div', { class: 'card' }, el('div', { class: 'row spread' },
    el('div', { class: 'row' },
      el('h2', { text: v.vehicle_id }), el('span', { class: 'mono muted', text: v.registration || '' }),
      sevChip(v.worst_severity)),
    el('button', { class: 'btn small', onclick: () => openWhy(v.why) }, icon('i-why'), ' Why this answer?')),
  el('div', { class: 'row small muted' },
    el('span', { text: `Region: ${v.region || '—'}` }), el('span', { text: `LOB: ${v.lob || '—'}` }),
    el('span', { text: `Rows seen: ${num(v.rows_seen)}` }),
    el('span', { text: `Rejected: ${num(v.rows_rejected)}` }),
    el('span', { text: v.label || 'synthetic — illustrative' }))));

  host.append(technicianCheck(v));

  if (!(v.episodes || []).length) {
    host.append(emptyState('No fault episodes for this vehicle.', 'Its rows were clean, duplicated or rejected.'));
    return;
  }
  for (const ep of v.episodes) host.append(episodeCard(ep, v));
}

function technicianCheck(v) {
  const card = el('div', { class: 'card' },
    el('h2', { text: 'Technician-reported code' }),
    el('p', { class: 'small muted', text: 'Typed by hand at the counter and cross-checked against the telemetry-resolved code. Never auto-replaced.' }));
  const out = el('div', { id: 'v-check' });
  const form = el('form', { class: 'row', onsubmit: async (ev) => {
    ev.preventDefault();
    clear(out); out.append(skeleton('line', 1));
    try {
      const r = await api('/verify-code', { method: 'POST',
        body: JSON.stringify({ vehicle_id: v.vehicle_id, reported_code: $('#v-code').value.trim() }) });
      clear(out);
      const bad = r.status === 'MISMATCH';
      out.append(el('div', { class: `banner ${bad ? 'bad' : 'good'}` },
        el('div', {},
          el('strong', { text: bad ? `MISMATCH — ${r.reported_code} is not what the telemetry resolved`
            : `${r.status} — ${r.reported_code}` }),
          el('div', { class: 'small', text: r.message }),
          (r.possible_transposition || []).length
            ? el('div', { class: 'small', text: `Possible transposition of: ${r.possible_transposition.join(', ')}` })
            : null,
          el('div', { class: 'small', text: `Telemetry resolved: ${(r.telemetry_resolved_codes || []).join(', ') || '—'}` }),
          el('div', { class: 'small', text: r.auto_replaced ? 'Auto-replaced' : 'Not auto-replaced — confirm with the technician' }))));
      out.append(el('button', { class: 'btn small', onclick: () => openWhy(r.why) },
        icon('i-why'), ' Why this answer?'));
    } catch (e) { showError(out, e); }
  } },
  el('label', { class: 'sr-only', for: 'v-code', text: 'Reported code' }),
  el('input', { id: 'v-code', placeholder: 'P0100-00' }),
  el('button', { class: 'btn', type: 'submit', text: 'Check code' }));
  card.append(form, out);
  return card;
}

function episodeCard(ep, v) {
  const card = el('div', { class: 'card' });
  const ladderOut = (ep.ladder || []).map((r) => r.rung).join(' → ');
  card.append(el('div', { class: 'stepper' },
    step('Telemetry', `SPN ${ep.spn} · FMI ${ep.fmi}`, ep.spn_name),
    step('Resolved code', ep.resolved_code || '—', ep.fmi_description),
    step('Ladder outcome', (ep.outcome || '').replace(/_/g, ' '), ladderOut),
    step('Advisory', ep.severity || '—', (ep.severity_reasons || []).join(', '))));

  card.append(el('div', { class: 'row' }, outcomeChip(ep.outcome), sevChip(ep.severity),
    el('span', { class: 'small muted', text: `${ep.occurrence_count || ep.rows} occurrence(s), `
      + `${ep.first_seen} → ${ep.last_seen}` })));

  if (ep.message) {
    /* The style must follow the OUTCOME, not merely the presence of a message:
       an ADVISORY carries an explanatory note, and dressing that as "needs
       confirmation" would misread a resolved fault as an open question. */
    let kind = '';
    let label = 'Note';
    if (/REFUSED|UNMAPPED/.test(ep.outcome)) { kind = 'refusal'; label = 'Not in this manual'; }
    else if (/CANDIDATES|CLARIFY|AMBIGUOUS/.test(ep.outcome)) { kind = 'clarify'; label = 'Needs confirmation'; }
    card.append(el('div', { class: `msg ${kind}` }, el('div', {},
      el('div', { class: 'msg-label', text: label }),
      el('div', { text: ep.message }))));
  }
  for (const c of ep.candidates || []) {
    card.append(el('div', { class: 'small' }, el('code', { text: c.code_full || c.code }), ' ',
      c.description || '', el('span', { class: 'muted', text: ' — not auto-advised, confirm with technician' })));
  }
  for (const fb of ep.fix_blocks || []) {
    card.append(el('details', { class: 'disc' },
      el('summary', {}, icon('i-chevron'), el('span', { text: `${fb.code_full} — ${fb.description}` })),
      fixBlockBody(fb),
      el('div', { class: 'row' },
        el('button', { class: 'btn small', onclick: () => printJobCard(fb, ep.illustrative_cost_tat,
          `Vehicle ${v.vehicle_id} (${v.registration || '—'}) · SPN ${ep.spn}/FMI ${ep.fmi} · severity ${ep.severity}`) },
        icon('i-print'), ' Print job card'))));
  }
  const cost = costPanel(ep.illustrative_cost_tat);
  if (cost) card.append(cost);
  return card;
}

const step = (lbl, val, note) => el('div', { class: 'step done' },
  el('span', { class: 'lbl', text: lbl }), el('span', { class: 'val', text: val }),
  note ? el('span', { class: 'small muted', text: note }) : null);

/* ==================================================== SERVICE QUERY view */
async function viewSymptom(prefill) {
  selectNav('symptom');
  const host = $('#view');
  clear(host);
  host.append(el('div', { class: 'view-head' }, el('h1', { text: 'Service query' }),
    el('p', { text: 'A symptom in the technician’s own words, or a code. Out-of-scope questions are refused, not answered.' })));
  const form = el('form', { class: 'row', onsubmit: (ev) => { ev.preventDefault(); runSymptom($('#s-q').value); } },
    el('label', { class: 'sr-only', for: 's-q', text: 'Symptom or code' }),
    el('input', { id: 's-q', value: prefill || '', placeholder: 'coolant gauge stuck at the bottom' }),
    el('label', { class: 'row small' }, el('input', { id: 's-sum', type: 'checkbox' }),
      el('span', { text: 'one-line model summary' })),
    el('button', { class: 'btn primary', type: 'submit', text: 'Search' }));
  host.append(el('div', { class: 'card' }, form), el('div', { id: 'symptom-body' }));
  if (prefill) runSymptom(prefill);
}

async function runSymptom(q) {
  const query = (q || '').trim();
  if (!query) return;
  if ($('#s-q')) $('#s-q').value = query;
  const host = $('#symptom-body');
  clear(host);
  host.append(skeleton('block', 2));
  try {
    const res = await api('/symptom', { method: 'POST',
      body: JSON.stringify({ query, summary: $('#s-sum') ? $('#s-sum').checked : false }) });
    clear(host);
    host.append(el('div', { class: 'row spread' },
      el('div', { class: 'row' }, el('h2', { text: 'Result' }),
        el('span', { class: 'chip plain', text: (res.mode || '').replace(/_/g, ' ') }),
        el('span', { class: 'small muted', text: `config: ${res.config.index}, gate ${res.config.gate}` })),
      el('button', { class: 'btn small', onclick: () => openWhy(res.why) }, icon('i-why'), ' Why this answer?')));

    /* Four distinct, friendly styles. None of these is an error. */
    if (res.mode === 'conversational') {
      host.append(el('div', { class: 'msg friendly' }, el('div', {},
        el('div', { class: 'row' }, el('span', { class: 'tag RULE', text: 'RULE' }),
          el('span', { class: 'msg-label', text: `conversational · ${res.conversational}` })),
        el('div', { text: res.message }),
        el('div', { class: 'small', text: 'Not a fault report, so nothing was retrieved and the manual was not consulted.' }))));
    } else if (res.mode === 'incomplete_code' || res.mode === 'invalid_code') {
      /* 13.3 and 13.4 are the same kind of answer — "that is not a usable code,
         here is what one looks like" — so they share one style. */
      const box = el('div', { class: 'msg clarify' }, el('div', {},
        el('div', { class: 'row' }, el('span', { class: 'tag RULE', text: 'RULE' }),
          el('span', { class: 'msg-label',
            text: res.mode === 'invalid_code' ? 'invalid code' : 'incomplete code' })),
        el('div', { text: res.message })));
      const inner = box.firstChild;
      if ((res.candidates || []).length) {
        inner.append(el('div', { class: 'small',
          text: res.candidates_note
            || 'Codes in this manual that start that way — not selected, enter the full code:' }),
          el('ul', { class: 'small' }, res.candidates.map((c) => el('li', {},
            el('code', { text: c.code }), ` (page ${c.page}) — ${c.description}`)),
          res.more_note ? el('li', { class: 'muted', text: res.more_note }) : null));
      } else if (res.no_candidates_reason) {
        inner.append(el('div', { class: 'small', text: res.no_candidates_reason }));
      }
      host.append(box);
    } else if (res.mode === 'refused') {
      host.append(el('div', { class: 'msg refusal' }, el('div', {},
        el('div', { class: 'msg-label', text: 'Not covered in this manual' }),
        el('div', { text: res.message || 'No fault in this manual matches that.' }),
        (res.refusal_reasons || []).length
          ? el('div', { class: 'small', text: `Reason: ${res.refusal_reasons.join(', ')}` }) : null)));
    } else if (res.mode === 'clarify_code') {
      host.append(el('div', { class: 'msg clarify' }, el('div', {},
        el('div', { class: 'msg-label', text: 'Needs clarification' }),
        el('div', { text: res.message || '' }),
        (res.did_you_mean || []).length
          ? el('div', { class: 'small', text: `Did you mean: ${res.did_you_mean.join(', ')}` }) : null)));
    } else {
      for (const r of res.results || []) {
        const fb = r.fix_block;
        const card = el('div', { class: 'card' },
          el('div', { class: 'row spread' },
            el('div', { class: 'row' }, el('h3', { text: `#${r.rank}  ${fb.code_full}` }),
              el('span', { class: 'chip plain', text: fb.system })),
            el('button', { class: 'btn small',
              onclick: () => printJobCard(fb, r.illustrative_cost_tat, `Service query: "${res.input}"`) },
            icon('i-print'), ' Print job card')),
          el('p', { class: 'small', text: fb.description }),
          el('p', { class: 'small muted', text: r.why_retrieved }));
        if (r.llm_summary) {
          card.append(el('div', { class: 'msg' }, el('div', {},
            el('div', { class: 'row' }, el('span', { class: 'tag MODEL', text: 'MODEL' }),
              el('span', { class: 'msg-label', text: 'phrasing only' })),
            el('div', { text: r.llm_summary.text }),
            el('div', { class: 'small muted', text: r.llm_summary.source || '' }))));
        }
        card.append(el('details', { class: 'disc' },
          el('summary', {}, icon('i-chevron'),
            el('span', { text: 'Causes, checkpoints and the repair procedure' })),
          fixBlockBody(fb)));
        const cost = costPanel(r.illustrative_cost_tat);
        if (cost) card.append(cost);
        host.append(card);
      }
      if (!(res.results || []).length) host.append(emptyState('Nothing to show for that query.'));
    }
  } catch (e) { showError(host, e); }
}

/* ============================================================ AUDIT view */
async function viewAudit() {
  const host = $('#view');
  clear(host);
  host.append(el('div', { class: 'view-head' }, el('h1', { text: 'Audit' }),
    el('p', { text: 'One append-only line per request: route, decision, codes, latency, commit and determinism hash.' })));
  const body = el('div', {}, skeleton('block', 1));
  host.append(body);
  try {
    const a = await api('/audit?limit=50');
    clear(body);
    body.append(el('div', { class: 'row spread' },
      el('p', { class: 'small muted', text: `${a.count} most recent entries from ${a.path}` }),
      el('button', { class: 'btn small', onclick: () => openWhy(a.why) }, icon('i-why'), ' Why this answer?')));
    if (!(a.entries || []).length) { body.append(emptyState('No audit entries yet.')); return; }
    const tbody = el('tbody');
    for (const e of a.entries.slice().reverse()) {
      tbody.append(el('tr', {},
        el('td', { class: 'mono small', text: (e.timestamp || '').replace('T', ' ').slice(0, 23) }),
        el('td', {}, el('code', { text: e.endpoint })),
        el('td', {}, el('span', { class: 'chip plain', text: String(e.decision || '').replace(/_/g, ' ') })),
        el('td', { class: 'mono small', text: (e.codes || []).join(', ') }),
        el('td', { class: 'num', text: `${e.latency_ms} ms` })));
    }
    body.append(el('div', { class: 'table-wrap' }, el('table', {},
      el('thead', {}, el('tr', {}, el('th', { text: 'Time (UTC)' }), el('th', { text: 'Endpoint' }),
        el('th', { text: 'Decision' }), el('th', { text: 'Codes' }), el('th', { class: 'num', text: 'Latency' }))),
      tbody)));
  } catch (e) { showError(body, e); }
}

/* =============================================================== presets */
const SYMPTOM_PRESETS = [
  ['coolant gauge stuck at the bottom', 'in scope — symptom search'],
  ['how do I change a tyre', 'out of scope — expect a refusal'],
  ['what is the warranty period on this engine', 'out of scope — expect a refusal'],
  ['hi', 'conversational — greeting, no retrieval'],
  ['thanks a lot', 'conversational — thanks, no retrieval'],
  ['no issue, the vehicle is running fine', 'conversational — healthy, no fault lookup'],
  ['P-10', 'incomplete code — candidates, no retrieval'],
  ['P019', 'incomplete code — dropped digit'],
  ['P1', 'incomplete code — one digit, format hint only'],
  ['P1023473efa234rgddhdhdfgddhy', 'invalid code — over-long token, no retrieval'],
  ['U0100zzzz', 'invalid code — illegal characters'],
];
const VERIFY_PRESETS = [
  ['transposition_P1000', 'P0100-00', 'telemetry P1000-00, technician types P0100-00'],
  ['transposition_P1675', 'P1657-00', 'telemetry P1675-00, technician types P1657-00'],
];

async function buildPresets() {
  const body = $('#presets-body');
  clear(body);
  body.append(el('h4', { text: 'Fleet' }),
    el('button', { class: 'btn preset', onclick: () => { closeDrawers(); selectNav('fleet'); viewFleet(); } },
      el('span', { text: 'Open the fleet view' })),
    el('button', { class: 'btn preset', onclick: async () => {
      closeDrawers(); selectNav('fleet'); await viewFleet();
      replay('start', { rows_per_tick: 40, tick_seconds: 1 });
    } }, el('span', { text: 'Start replay (40 rows / 1 s)' })));
  try {
    const s = await api('/scenarios');
    body.append(el('h4', { text: 'Vehicle scenarios (synthetic)' }));
    for (const [name, d] of Object.entries(s.scenarios || {})) {
      body.append(el('button', { class: 'btn preset',
        onclick: () => { closeDrawers(); openVehicle(d.vehicle_id); } },
      el('span', { text: name.replace(/_/g, ' ') }),
      el('small', { text: `${d.vehicle_id} — ${d.note}` })));
    }
    body.append(el('h4', { text: 'Technician-reported code (transposition)' }));
    for (const [key, typed, note] of VERIFY_PRESETS) {
      const sc = (s.scenarios || {})[key];
      if (!sc) continue;
      body.append(el('button', { class: 'btn preset', onclick: async () => {
        closeDrawers(); await openVehicle(sc.vehicle_id);
        const f = $('#v-code');
        if (f) { f.value = typed; f.form.requestSubmit(); }
      } }, el('span', { text: `Type ${typed} on ${sc.vehicle_id}` }), el('small', { text: note })));
    }
  } catch (e) {
    body.append(el('div', { class: 'msg error small', text: `Presets unavailable: ${e.message}` }));
  }
  body.append(el('h4', { text: 'Service query' }));
  for (const [q, note] of SYMPTOM_PRESETS) {
    body.append(el('button', { class: 'btn preset',
      onclick: () => { closeDrawers(); viewSymptom(q); } },
    el('span', { text: q }), el('small', { text: note })));
  }
  body.append(el('h4', { text: 'Audit' }),
    el('button', { class: 'btn preset', onclick: () => { closeDrawers(); selectNav('audit'); viewAudit(); } },
      el('span', { text: 'Show the audit trail' })));
}

/* ============================================================ navigation */
const VIEWS = { fleet: viewFleet, vehicle: () => openVehicle(''), symptom: () => viewSymptom(''), audit: viewAudit };

function selectNav(name) {
  for (const b of $$('.nav-item')) {
    const on = b.dataset.view === name;
    if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  }
  if (fleetState.timer && name !== 'fleet') { clearTimeout(fleetState.timer); fleetState.timer = null; }
}
function go(name) { selectNav(name); (VIEWS[name] || viewFleet)(); say(`${name} view`); }

/* The one search box routes by rule: a complete-looking code or a code attempt
   goes to the service query (the router owns codes); a vehicle id or a
   registration opens that vehicle; anything else is a symptom. */
const RE_CODE = /^[PUBC]\s?[-_.]?\s?[0-9A-F]{1,4}(\s?[-_.]\s?[0-9A-F]{1,2})?$/i;
const RE_VEHICLE = /^DEMO-[A-Z]{2,4}-\d{3,5}$/i;
const RE_REG = /^[A-Z]{2}\d{2}[A-Z]{2}\d{3,4}$/i;

function dispatchSearch(raw) {
  const q = (raw || '').trim();
  if (!q) return;
  if (RE_VEHICLE.test(q) || RE_REG.test(q)) { openVehicle(q); return; }
  if (RE_CODE.test(q)) { viewSymptom(q); return; }
  viewSymptom(q);
}

/* ================================================================= theme */
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  $('#theme').setAttribute('aria-pressed', String(t === 'dark'));
  try { localStorage.setItem('dtc.theme', t); } catch { /* private mode */ }
}

/* ================================================================== boot */
function init() {
  let t = 'light';
  try { t = localStorage.getItem('dtc.theme') || (window.matchMedia
    && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); } catch { /* ignore */ }
  applyTheme(t);
  $('#theme').addEventListener('click', () => applyTheme(
    document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'));

  for (const b of $$('.nav-item')) b.addEventListener('click', () => go(b.dataset.view));
  $('#search-form').addEventListener('submit', (ev) => { ev.preventDefault(); dispatchSearch($('#q').value); });
  $('#presets-btn').addEventListener('click', () => { buildPresets(); openDrawer('presets'); });
  for (const b of $$('[data-close]')) b.addEventListener('click', closeDrawers);
  $('#scrim').addEventListener('click', closeDrawers);
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') closeDrawers(); });

  api('/health').then((h) => {
    $('#build').textContent = `${h.versions.phase} · ${h.determinism_hash} · `
      + `${num(h.counts.records)} records`;
  }).catch(() => { $('#build').textContent = 'server not ready'; });

  go('fleet');
}
document.addEventListener('DOMContentLoaded', init);
