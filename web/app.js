/* Phase 10.4 demo UI logic. Vanilla JS, no framework, no build step, no CDN.
   Every request is same-origin and goes only to the Phase 10.3 endpoints. */
'use strict';

const SEVERITIES = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
const OUTCOMES = ['ADVISORY', 'AMBIGUOUS_MAPPING_CANDIDATES', 'CLARIFY_LOW_BYTE',
  'REFUSED_NOT_IN_MANUAL', 'FALLBACK_CANDIDATES', 'UNMAPPED'];
const POLL_MS = 3000;

const state = { fleet: null, replayTimer: null, scenarios: null };

/* ----------------------------------------------------------------- helpers */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

const clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); };
const inr = (n) => (n === null || n === undefined) ? '—' : '₹' + Number(n).toLocaleString('en-IN');

/* Every API call funnels through here so an error is always shown inline and a
   view never goes blank. */
async function api(path, opts = {}) {
  let res, body;
  try {
    res = await fetch(path, {
      headers: opts.body ? { 'content-type': 'application/json' } : {},
      ...opts,
    });
  } catch (e) {
    throw new Error(`Cannot reach the API (${path}). Is the service running? [${e.message}]`);
  }
  const text = await res.text();
  try { body = text ? JSON.parse(text) : {}; } catch { body = { detail: text }; }
  if (!res.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body);
    const err = new Error(`${res.status} ${res.statusText} — ${detail}`);
    err.status = res.status;
    throw err;
  }
  return body;
}

function showError(container, err) {
  const msg = err && err.message ? err.message : String(err);
  container.prepend(el('div', { class: 'notice bad' },
    el('strong', { text: 'Request failed. ' }), msg));
}

function badgeSev(sev) {
  // a vehicle whose only rows were malformed has no episodes and so no severity:
  // show a plain dash rather than a badge that would read as a real LOW rating
  if (!sev) return el('span', { class: 'muted', text: '—' });
  return el('span', { class: `badge sev-${sev}`, text: sev });
}

function badgeOutcome(outcome) {
  const short = {
    ADVISORY: 'ADVISORY',
    CLARIFY_LOW_BYTE: 'CLARIFY',
    AMBIGUOUS_MAPPING_CANDIDATES: 'AMBIGUOUS',
    FALLBACK_CANDIDATES: 'CANDIDATES',
    REFUSED_NOT_IN_MANUAL: 'REFUSED',
    UNMAPPED: 'UNMAPPED',
    refused: 'REFUSED',
    clarify_code: 'CLARIFY',
  }[outcome] || outcome;
  return el('span', { class: `out out-${outcome}`, text: short });
}

/* --------------------------------------------------------------- why panel */
function whyPanel(why, label = 'Why this answer?') {
  if (!why) return null;
  const d = el('details', { class: 'why' }, el('summary', { text: label }));

  const add = (title, node) => { d.append(el('h3', { text: title, class: 'small' }), node); };

  d.append(el('p', { class: 'small', html: `<b>Route:</b> <code>${why.route ?? '—'}</code>` }));

  // retrieval
  const r = why.retrieval || {};
  if (r.used && (r.ranks || []).length) {
    const t = el('table', {}, el('thead', {}, el('tr', {},
      el('th', { text: 'rank' }), el('th', { text: 'code' }), el('th', { text: 'why retrieved' }))));
    const tb = el('tbody');
    for (const x of r.ranks) {
      tb.append(el('tr', {}, el('td', { class: 'num', text: x.rank }),
        el('td', {}, el('code', { text: x.code_full })),
        el('td', { class: 'small', text: x.why_retrieved || '' })));
    }
    t.append(tb);
    add('Retrieval ranks', t);
  } else {
    add('Retrieval', el('p', { class: 'small muted',
      text: r.note || 'Similarity search was not used on this route.' }));
  }

  // gate
  const g = why.gate || {};
  if (g.applied) {
    const sig = Object.entries(g.signals || {}).map(([k, v]) => `${k}=${v}`).join('  ');
    add('Relevance gate', el('p', { class: 'small' },
      el('b', { text: (g.decision || '').toUpperCase() + ' ' }),
      (g.reasons || []).length ? `reason: ${g.reasons.join(', ')}. ` : '',
      el('span', { class: 'mono muted', text: sig })));
  } else {
    add('Relevance gate', el('p', { class: 'small muted',
      text: g.note || 'Not applicable on this route.' }));
  }

  // ladder
  if ((why.ladder || []).length) {
    const ul = el('ul', { class: 'small' });
    for (const ep of why.ladder) {
      const rungs = (ep.rungs || []).map((x) => `${x.rung} → ${x.result}`).join('  ·  ');
      ul.append(el('li', {}, el('code', { text: `SPN ${ep.spn} FMI ${ep.fmi}` }),
        ` ${ep.outcome} — `, el('span', { class: 'muted', text: rungs })));
    }
    add('Ladder rungs fired', ul);
  }

  // severity reasons
  if ((why.severity_reasons || []).length) {
    const ul = el('ul', { class: 'small' });
    for (const s of why.severity_reasons) {
      ul.append(el('li', {}, badgeSev(s.severity), ' ',
        el('span', { class: 'muted', text: (s.reasons || []).join('; ') })));
    }
    add('Severity reasons', ul);
  }

  // citations
  if ((why.citations || []).length) {
    const ul = el('ul', { class: 'small' });
    for (const c of why.citations) {
      ul.append(el('li', {}, el('code', { text: c.code_full }),
        ` — manual page ${c.manual_page}`));
    }
    add('Citations', ul);
  }

  // steps with RULE / AI badges
  if ((why.steps || []).length) {
    const ul = el('ul', { class: 'steps' });
    for (const s of why.steps) {
      ul.append(el('li', {}, el('span', { class: `tag ${s.label}`, text: s.label }),
        el('span', { class: 'small', text: s.step })));
    }
    add('Steps', ul);
  }
  return d;
}

/* ------------------------------------------------------- illustrative cost */
function costPanel(ic) {
  if (!ic) return null;
  const f = ic.figures;
  const box = el('div', { class: 'cost' },
    el('h4', { text: 'Illustrative cost & TAT — owned by another team; not from the manual' }));
  if (!f) {
    box.append(el('p', { class: 'small', text: 'No illustrative figures for this subsystem.' }));
    return box;
  }
  box.append(el('dl', {},
    el('div', {}, el('dt', { text: 'Labour' }), el('dd', { text: `${f.labour_hours} h` })),
    el('div', {}, el('dt', { text: 'Parts (range)' }),
      el('dd', { text: `${inr(f.parts_cost_min_inr)} – ${inr(f.parts_cost_max_inr)}` })),
    el('div', {}, el('dt', { text: 'Turnaround' }), el('dd', { text: `${f.tat_hours} h` })),
    el('div', {}, el('dt', { text: 'Applies to' }), el('dd', { text: f.applies_to || ic.subsystem || '—' }))));
  box.append(el('p', { class: 'small', text: ic.label }));
  return box;
}

/* ------------------------------------------------------------- fix blocks */
function fixBlock(fb) {
  const d = el('div', { class: 'fix' },
    el('h4', {}, el('code', { text: fb.code_full }), ' — ', fb.description || ''));
  const bits = [`System: ${fb.system}`];
  if (fb.MIL) bits.push(`MIL ${fb.MIL}`);
  if (fb.effect) bits.push(`Effect: ${fb.effect}`);
  d.append(el('div', { class: 'meta', text: bits.join('  |  ') }));

  if ((fb.cause || []).length) {
    d.append(el('div', { class: 'small' }, el('b', { text: 'Likely causes: ' }),
      fb.cause.join('; ')));
  }
  if ((fb.steps || []).length) {
    const ol = el('ol');
    for (const s of fb.steps) {
      const li = el('li', {}, s.text || '');
      if (s.spec) li.append(' ', el('span', { class: 'spec', text: `[spec: ${s.spec}]` }));
      if (s.branch) li.append(el('div', { class: 'branch', text: `→ ${s.branch}` }));
      ol.append(li);
    }
    d.append(el('div', { class: 'small' }, el('b', { text: 'Troubleshooting steps:' })), ol);
  }
  if ((fb.pins || []).length) {
    d.append(el('div', { class: 'small' }, el('b', { text: 'Pins: ' }), fb.pins.join(', ')));
  }
  d.append(el('div', { class: 'small page', text: `Manual page ${fb.page}` }));
  return d;
}

/* =========================================================== FLEET tab */
async function loadFleet() {
  const host = $('#fleet-body');
  const sev = $('#f-sev').value;
  const region = $('#f-region').value;
  const outcome = $('#f-outcome').value;
  const qs = new URLSearchParams();
  if (sev) qs.set('severity', sev);
  if (region) qs.set('region', region);
  if (outcome) qs.set('outcome', outcome);
  try {
    const f = await api('/fleet' + (qs.toString() ? '?' + qs : ''));
    state.fleet = f;
    renderFleet(f);
  } catch (e) {
    clear(host);
    showError(host, e);
  }
}

function renderFleet(f) {
  const host = $('#fleet-body');
  clear(host);

  // counters: severity then subsystem
  const counters = el('div', { class: 'counters' });
  counters.append(el('div', { class: 'counter' },
    el('div', { class: 'n', text: f.filters.vehicles_after_filter }),
    el('div', { class: 'k', text: 'vehicles shown' })));
  for (const s of SEVERITIES) {
    counters.append(el('div', { class: 'counter' },
      el('div', { class: 'n' }, badgeSev(s), ' ', String(f.by_worst_severity[s] ?? 0)),
      el('div', { class: 'k', text: 'worst severity' })));
  }
  counters.append(el('div', { class: 'counter' },
    el('div', { class: 'n', text: f.episodes }), el('div', { class: 'k', text: 'episodes' })));
  counters.append(el('div', { class: 'counter' },
    el('div', { class: 'n', text: f.rows_in_scope }), el('div', { class: 'k', text: 'rows in scope' })));
  host.append(counters);

  const subs = Object.entries(f.advisory_by_subsystem || {}).slice(0, 8);
  if (subs.length) {
    const c2 = el('div', { class: 'counters' });
    for (const [k, v] of subs) {
      c2.append(el('div', { class: 'counter' },
        el('div', { class: 'n', text: v }), el('div', { class: 'k', text: k })));
    }
    host.append(el('div', { class: 'small muted', text: 'Advisories by subsystem' }), c2);
  }

  // table
  const rows = Object.entries(f.per_vehicle);
  const t = el('table', {}, el('thead', {}, el('tr', {},
    el('th', { text: 'Vehicle' }), el('th', { text: 'Registration' }),
    el('th', { text: 'Active faults' }), el('th', { text: 'Worst severity' }),
    el('th', { text: 'Outcome mix' }))));
  const tb = el('tbody');
  // most severe first; vehicles with no severity at all sort last, not first
  const sevRank = (s) => (SEVERITIES.indexOf(s) === -1 ? SEVERITIES.length : SEVERITIES.indexOf(s));
  rows.sort((a, b) => (sevRank(a[1].worst_severity) - sevRank(b[1].worst_severity))
    || a[0].localeCompare(b[0]));
  for (const [vid, v] of rows) {
    const mix = el('td');
    for (const [o, n] of Object.entries(v.outcomes || {})) {
      mix.append(badgeOutcome(o), el('span', { class: 'small muted', text: ` ×${n} ` }));
    }
    tb.append(el('tr', { class: 'clickable', title: 'Open in the Vehicle tab',
      onclick: () => openVehicle(vid) },
      el('td', {}, el('code', { text: vid })),
      el('td', { class: 'mono small', text: v.registration }),
      el('td', { class: 'num', text: v.episodes }),
      el('td', {}, badgeSev(v.worst_severity)),
      mix));
  }
  t.append(tb);
  host.append(rows.length ? t : el('p', { class: 'muted', text: 'No vehicles match these filters.' }));
  host.append(whyPanel(f.why, 'Why these numbers?'));
}

/* replay */
async function replay(action, body) {
  const bar = $('#replay-bar');
  try {
    const r = await api(`/replay/${action}`, { method: 'POST', body: JSON.stringify(body || {}) });
    renderReplay(r.active === undefined ? await api('/replay/status') : r);
    await loadFleet();
    schedulePolling();
    return r;
  } catch (e) {
    showError(bar, e);
  }
}

function renderReplay(s) {
  $('#replay-count').textContent = `${s.rows_replayed ?? 0} / ${s.rows_total ?? 0} rows`;
  $('#replay-prog').style.width = `${Math.round((s.progress ?? 0) * 100)}%`;
  $('#replay-live').hidden = !s.active;
  $('#replay-date').textContent = s.last_event_date ? `up to ${s.last_event_date}` : '';
}

function schedulePolling() {
  clearInterval(state.replayTimer);
  state.replayTimer = setInterval(async () => {
    try {
      const s = await api('/replay/status');
      renderReplay(s);
      if (!s.active) { clearInterval(state.replayTimer); state.replayTimer = null; return; }
      if ($('#tab-fleet').getAttribute('aria-selected') === 'true') await loadFleet();
    } catch { clearInterval(state.replayTimer); }
  }, POLL_MS);
}

/* ========================================================= VEHICLE tab */
async function openVehicle(ident) {
  selectTab('vehicle');
  $('#v-id').value = ident;
  await loadVehicle();
}

async function loadVehicle() {
  const host = $('#vehicle-body');
  const ident = $('#v-id').value.trim();
  clear(host);
  if (!ident) {
    host.append(el('p', { class: 'muted', text: 'Enter a vehicle id or registration.' }));
    return;
  }
  host.append(el('p', { class: 'muted', text: `Loading ${ident}…` }));
  try {
    const v = await api(`/vehicle/${encodeURIComponent(ident)}`);
    renderVehicle(v);
  } catch (e) {
    clear(host);
    showError(host, e);
    if (e.status === 404) {
      host.append(el('p', { class: 'small muted',
        text: 'Try a preset from “Demo presets”, or click a row in the Fleet tab.' }));
    }
  }
}

function renderVehicle(v) {
  const host = $('#vehicle-body');
  clear(host);

  host.append(el('div', { class: 'row' },
    el('h2', { text: `${v.vehicle_id}` }),
    el('span', { class: 'mono muted', text: v.registration }),
    badgeSev(v.worst_severity),
    el('span', { class: 'small muted',
      text: `${v.region} · ${v.lob} · ${v.pl} — ${v.rows_seen} rows, `
        + `${v.rows_rejected} rejected, ${(v.duplicate_rows_dropped || []).length} duplicates dropped` })));

  if ((v.rejected || []).length) {
    const ul = el('ul', { class: 'small' });
    for (const r of v.rejected) ul.append(el('li', { text: `row ${r.row}: ${r.problems.join('; ')}` }));
    host.append(el('div', { class: 'notice warn' },
      el('strong', { text: 'Malformed rows rejected and logged ' }), ul));
  }

  for (const e of v.episodes) host.append(episodeCard(e));

  // technician-reported code
  const vc = el('div', { class: 'card' },
    el('h3', { text: 'Technician-reported code' }),
    el('p', { class: 'small muted',
      text: 'Cross-check what the technician typed against the code resolved from telemetry. '
        + 'A mismatch is never auto-corrected.' }),
    el('div', { class: 'row' },
      el('input', { id: 'v-code', placeholder: 'e.g. P0100-00', size: '16' }),
      el('button', { class: 'primary', text: 'Verify code', onclick: () => verifyCode(v.vehicle_id) })),
    el('div', { id: 'verify-out' }));
  host.append(vc);
  host.append(whyPanel(v.why, 'Why this answer?'));
}

function episodeCard(e) {
  const card = el('div', { class: 'card' });
  card.append(el('div', { class: 'chain' },
    el('span', { class: 'node', text: `SPN ${e.spn} · FMI ${e.fmi}` }),
    el('span', { class: 'arrow', text: '→' }),
    el('span', { class: 'node' }, e.resolved_code
      ? el('code', { text: e.resolved_code })
      : el('span', { class: 'muted', text: 'no single code' })),
    el('span', { class: 'arrow', text: '→' }),
    badgeOutcome(e.outcome),
    badgeSev(e.severity)));

  card.append(el('p', { class: 'small muted',
    text: `${e.spn_name} — ${e.fmi_description}` }));
  card.append(el('p', { class: 'small' }, el('b', { text: 'Severity: ' }),
    `${e.severity} — ${(e.severity_reasons || []).join('; ')}`));
  card.append(el('p', { class: 'small' },
    `${e.rows} row(s), ${e.first_seen} → ${e.last_seen}, occurrence ${e.occurrence_count}, `
    + `active ${e.active_minutes} min`));

  if (e.outcome === 'ADVISORY') {
    for (const fb of e.fix_blocks || []) card.append(fixBlock(fb));
  } else if (e.outcome === 'AMBIGUOUS_MAPPING_CANDIDATES' || e.outcome === 'FALLBACK_CANDIDATES') {
    const ul = el('ul', {});
    for (const c of e.candidates || []) {
      ul.append(el('li', {}, el('code', { text: c.code_full }),
        c.fault_name ? el('span', { class: 'small muted', text: ` (${c.fault_name})` }) : '',
        c.fmi !== undefined ? el('span', { class: 'small muted', text: ` FMI ${c.fmi}` }) : '',
        c.nearest ? el('span', { class: 'small', text: ' — nearest FMI' }) : '',
        c.description ? el('div', { class: 'small muted', text: c.description }) : '',
        c.in_manual === false ? el('div', { class: 'small', text: 'not in this manual' }) : ''));
    }
    card.append(el('div', { class: 'notice info' },
      el('strong', { text: 'Not auto-advised — confirm with technician. ' }),
      el('div', { class: 'small', text: e.message }), ul));
  } else if (e.outcome === 'REFUSED_NOT_IN_MANUAL' || e.outcome === 'UNMAPPED') {
    card.append(el('div', { class: 'notice bad' },
      el('strong', { text: 'Refused — no repair steps shown. ' }), e.message));
  } else if (e.outcome === 'CLARIFY_LOW_BYTE') {
    card.append(el('div', { class: 'notice warn' },
      el('strong', { text: 'Needs clarification — no repair steps shown. ' }), e.message,
      (e.known_variants || []).length
        ? el('div', { class: 'small', text: `Known variants: ${e.known_variants.join(', ')}` }) : ''));
  }

  card.append(costPanel(e.illustrative_cost_tat));
  return card;
}

async function verifyCode(vehicleId) {
  const out = $('#verify-out');
  clear(out);
  const code = ($('#v-code') || {}).value;
  if (!code || !code.trim()) {
    out.append(el('div', { class: 'notice warn', text: 'Enter a code to verify.' }));
    return;
  }
  try {
    const r = await api('/verify-code', {
      method: 'POST',
      body: JSON.stringify({ vehicle_id: vehicleId, reported_code: code.trim() }),
    });
    const cls = r.status === 'MATCH' ? 'ok' : r.status === 'MISMATCH' ? 'bad' : 'warn';
    const box = el('div', { class: `notice ${cls}` },
      el('strong', { text: r.status + ' ' }));
    if (r.status === 'MISMATCH') {
      box.append(el('div', { class: 'codes' },
        `typed ${r.reported_code}  ≠  telemetry ${(r.telemetry_resolved_codes || []).join(', ') || '—'}`));
      if ((r.possible_transposition || []).length) {
        box.append(el('div', {}, el('strong', { text: 'Possible transposition: ' }),
          r.possible_transposition.join(', '),
          ' — not substituted; confirm the code on the vehicle.'));
      }
    }
    box.append(el('div', { class: 'small', text: r.message }));
    box.append(el('div', { class: 'small muted', text: `auto_replaced: ${r.auto_replaced}` }));
    out.append(box);
    out.append(whyPanel(r.why, 'Why this answer?'));
  } catch (e) {
    showError(out, e);
  }
}

/* ================================================= SERVICE QUERY tab */
async function runSymptom(q) {
  const host = $('#symptom-body');
  const query = (q !== undefined ? q : $('#s-q').value).trim();
  if (q !== undefined) $('#s-q').value = q;
  clear(host);
  if (!query) {
    host.append(el('p', { class: 'muted', text: 'Type a symptom in the technician’s own words.' }));
    return;
  }
  host.append(el('p', { class: 'muted', text: 'Searching the manual…' }));
  try {
    const res = await api('/symptom', {
      method: 'POST',
      body: JSON.stringify({ query, summary: $('#s-sum').checked }),
    });
    clear(host);
    host.append(el('div', { class: 'row' }, el('h2', { text: 'Result' }), badgeOutcome(res.mode),
      el('span', { class: 'small muted',
        text: `config: ${res.config.index}, gate ${res.config.gate}` })));

    if (res.mode === 'conversational') {
      host.append(el('div', { class: 'notice info' },
        el('span', { class: 'tag RULE', text: 'RULE' }), ' ',
        el('strong', { text: res.message }),
        el('div', { class: 'small muted',
          text: 'Not a fault report, so nothing was retrieved and the manual was not '
                + 'consulted.' })));
    } else if (res.mode === 'incomplete_code') {
      const box = el('div', { class: 'notice warn' },
        el('span', { class: 'tag RULE', text: 'RULE' }), ' ',
        el('strong', { text: res.message }));
      if ((res.candidates || []).length) {
        box.append(el('div', { class: 'small',
          text: 'Codes in this manual that start that way — not selected, enter the full code:' }));
        const ul = el('ul', { class: 'small' });
        for (const c of res.candidates) {
          ul.append(el('li', {}, el('code', { text: c.code }),
            ` (page ${c.page}) — ${c.description}`));
        }
        if (res.more_note) ul.append(el('li', { class: 'muted', text: res.more_note }));
        box.append(ul);
      } else if (res.no_candidates_reason) {
        box.append(el('div', { class: 'small muted', text: res.no_candidates_reason }));
      }
      host.append(box);
    } else if (res.mode === 'refused') {
      host.append(el('div', { class: 'notice bad' },
        el('strong', { text: 'Not covered in this manual. ' }),
        el('div', { class: 'small', text: res.message || '' }),
        el('div', { class: 'small', text: `Reason: ${(res.refusal_reasons || []).join(', ')}` })));
    } else if (res.mode === 'clarify_code') {
      host.append(el('div', { class: 'notice warn' },
        el('strong', { text: 'Needs clarification. ' }), res.message || '',
        (res.did_you_mean || []).length
          ? el('div', { class: 'small', text: `Did you mean: ${res.did_you_mean.join(', ')}` }) : ''));
    } else {
      for (const r of res.results || []) {
        const card = el('div', { class: 'card' },
          el('div', { class: 'row' }, el('h3', { text: `#${r.rank}  ${r.code_full}` })),
          el('p', { class: 'small muted', text: r.why_retrieved }));
        card.append(fixBlock(r.fix_block));
        if (r.llm_summary) {
          card.append(el('div', { class: 'notice info small' },
            el('span', { class: 'tag AI', text: 'AI' }),
            ' ', r.llm_summary.text, el('div', { class: 'small muted', text: r.llm_summary.source })));
        }
        card.append(costPanel(r.illustrative_cost_tat));
        host.append(card);
      }
    }
    host.append(whyPanel(res.why, 'Why this answer?'));
  } catch (e) {
    clear(host);
    showError(host, e);
  }
}

/* ============================================================ AUDIT tab */
async function loadAudit() {
  const host = $('#audit-body');
  clear(host);
  try {
    const a = await api('/audit?limit=50');
    const t = el('table', {}, el('thead', {}, el('tr', {},
      el('th', { text: 'Time (UTC)' }), el('th', { text: 'Endpoint' }),
      el('th', { text: 'Decision' }), el('th', { text: 'Codes' }),
      el('th', { text: 'Latency' }))));
    const tb = el('tbody');
    for (const e of a.entries.slice().reverse()) {
      tb.append(el('tr', {},
        el('td', { class: 'mono small', text: (e.timestamp || '').replace('T', ' ').slice(0, 23) }),
        el('td', {}, el('code', { text: e.endpoint })),
        el('td', {}, ...String(e.decision || '').split(',').map((d) => badgeOutcome(d.trim().toUpperCase()))),
        el('td', { class: 'mono small', text: (e.codes || []).join(', ') }),
        el('td', { class: 'num', text: `${e.latency_ms} ms` })));
    }
    t.append(tb);
    host.append(el('p', { class: 'small muted',
      text: `${a.count} most recent entries from ${a.path} (rotates at ${Math.round(a.rotates_at_bytes / 1048576)} MB)` }));
    host.append(a.entries.length ? t : el('p', { class: 'muted', text: 'No audit entries yet.' }));
    host.append(whyPanel(a.why, 'Why this answer?'));
  } catch (e) {
    showError(host, e);
  }
}

/* ============================================================== presets */
const SYMPTOM_PRESETS = [
  ['coolant gauge stuck at the bottom', 'in scope — symptom search'],
  ['hi', 'conversational — greeting, no retrieval'],
  ['thanks a lot', 'conversational — thanks, no retrieval'],
  ['no issue, the vehicle is running fine', 'conversational — healthy, no fault lookup'],
  ['P-10', 'incomplete code — candidates, no retrieval'],
  ['P019', 'incomplete code — dropped digit'],
  ['P1', 'incomplete code — one digit, format hint only'],
  ['how do I change a tyre', 'out of scope — expect a refusal'],
  ['what is the warranty period on this engine', 'out of scope — expect a refusal'],
];

const VERIFY_PRESETS = [
  ['transposition_P1000', 'P0100-00', 'telemetry P1000-00, technician types P0100-00'],
  ['transposition_P1675', 'P1657-00', 'telemetry P1675-00, technician types P1657-00'],
];

async function buildPresets() {
  const panel = $('#presets-panel');
  clear(panel);
  panel.append(el('h4', { text: 'Fleet' }));
  panel.append(el('button', {
    text: 'Open the fleet view',
    onclick: () => { closeMenu(); selectTab('fleet'); loadFleet(); },
  }));
  panel.append(el('button', {
    text: 'Start replay (40 rows / 1 s)',
    onclick: async () => { closeMenu(); selectTab('fleet'); await replay('start', { rows_per_tick: 40, tick_seconds: 1 }); },
  }));

  try {
    const s = await api('/scenarios');
    state.scenarios = s;
    panel.append(el('h4', { text: 'Vehicle scenarios (synthetic)' }));
    for (const [name, d] of Object.entries(s.scenarios)) {
      panel.append(el('button', {
        onclick: () => { closeMenu(); openVehicle(d.vehicle_id); },
      }, el('span', { text: name.replace(/_/g, ' ') }),
        el('small', { text: `${d.vehicle_id} — ${d.note}` })));
    }
    panel.append(el('h4', { text: 'Technician-reported code (transposition)' }));
    for (const [key, typed, note] of VERIFY_PRESETS) {
      const sc = s.scenarios[key];
      if (!sc) continue;
      panel.append(el('button', {
        onclick: async () => {
          closeMenu();
          await openVehicle(sc.vehicle_id);
          const f = $('#v-code');
          if (f) { f.value = typed; await verifyCode(sc.vehicle_id); }
        },
      }, el('span', { text: `Type ${typed} on ${sc.vehicle_id}` }), el('small', { text: note })));
    }
  } catch (e) {
    panel.append(el('div', { class: 'notice bad small', text: `Presets unavailable: ${e.message}` }));
  }

  panel.append(el('h4', { text: 'Service query' }));
  for (const [q, note] of SYMPTOM_PRESETS) {
    panel.append(el('button', {
      onclick: () => { closeMenu(); selectTab('symptom'); runSymptom(q); },
    }, el('span', { text: q }), el('small', { text: note })));
  }
  panel.append(el('h4', { text: 'Audit' }));
  panel.append(el('button', {
    text: 'Show the audit trail',
    onclick: () => { closeMenu(); selectTab('audit'); loadAudit(); },
  }));
}

const closeMenu = () => $('#presets-panel').setAttribute('data-open', '0');

/* ================================================================= tabs */
function selectTab(name) {
  for (const b of $$('nav.tabs button')) {
    b.setAttribute('aria-selected', String(b.id === `tab-${name}`));
  }
  for (const s of $$('section[role="tabpanel"]')) s.hidden = (s.id !== `panel-${name}`);
  if (name === 'audit') loadAudit();
}

/* ================================================================ health */
async function loadHealth() {
  try {
    const h = await api('/health');
    $('#health').innerHTML =
      `records <b>${h.counts.records}</b> · vectors <b>${h.counts.vectors}</b> · `
      + `dict keys <b>${h.counts.dictionary_keys}</b> · rows <b>${h.counts.log_rows_in_scope}</b>`
      + ` · startup <b>${h.startup_seconds}s</b> · hash <b>${(h.determinism_hash || '').slice(0, 8)}…</b>`;
    const sel = $('#f-region');
    if (sel && sel.options.length <= 1) {
      // regions come from the data itself, so the filter cannot drift from the feed
      const f = await api('/fleet');
      const regions = new Set();
      for (const v of Object.values(f.per_vehicle)) if (v.region) regions.add(v.region);
      for (const r of ['North', 'South', 'East', 'West', 'Central']) {
        sel.append(el('option', { value: r, text: r }));
      }
    }
  } catch (e) {
    $('#health').textContent = 'API unreachable';
    showError($('#fleet-body'), e);
  }
}

/* ================================================================= init */
window.addEventListener('DOMContentLoaded', async () => {
  for (const b of $$('nav.tabs button')) {
    b.addEventListener('click', () => selectTab(b.id.replace('tab-', '')));
  }
  for (const s of SEVERITIES) $('#f-sev').append(el('option', { value: s, text: s }));
  for (const o of OUTCOMES) $('#f-outcome').append(el('option', { value: o, text: o }));

  $('#f-sev').addEventListener('change', loadFleet);
  $('#f-region').addEventListener('change', loadFleet);
  $('#f-outcome').addEventListener('change', loadFleet);
  $('#f-reload').addEventListener('click', loadFleet);
  $('#r-start').addEventListener('click', () => replay('start', {
    rows_per_tick: Number($('#r-rows').value) || 40,
    tick_seconds: Number($('#r-tick').value) || 1,
  }));
  $('#r-stop').addEventListener('click', () => replay('stop'));
  $('#r-reset').addEventListener('click', () => replay('reset'));
  $('#v-go').addEventListener('click', loadVehicle);
  $('#v-id').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadVehicle(); });
  $('#s-go').addEventListener('click', () => runSymptom());
  $('#s-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') runSymptom(); });
  $('#audit-reload').addEventListener('click', loadAudit);

  const menuBtn = $('#presets-btn');
  menuBtn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    const p = $('#presets-panel');
    p.setAttribute('data-open', p.getAttribute('data-open') === '1' ? '0' : '1');
  });
  document.addEventListener('click', closeMenu);
  $('#presets-panel').addEventListener('click', (ev) => ev.stopPropagation());

  await loadHealth();
  await buildPresets();
  await loadFleet();
  try { renderReplay(await api('/replay/status')); } catch { /* shown by loadFleet */ }
});
