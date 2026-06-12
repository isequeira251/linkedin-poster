// Scene player — builds DOM from a scene spec and runs a timed animation pass.
// render.js calls window.renderScene(spec, durationMs) and waits for it to resolve.

const stage = () => document.getElementById('stage');

const CURSOR_SVG = `<svg viewBox="0 0 24 24" width="34" height="34">
  <path d="M5 2 L5 19 L9.5 15.5 L12.5 22 L15 21 L12 14.5 L18 14 Z" fill="#fff" stroke="#222" stroke-width="1.4"/></svg>`;

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

function chrome(extra) {
  stage().appendChild(el('div', 'watermark', 'PORTAL OPS'));
  stage().appendChild(el('div', 'brand-bar'));
  if (extra) stage().appendChild(el('div', 'sim-note', extra));
}

// Reveal .fade children spread across the scene duration (leading/trailing gaps).
async function staggerIn(nodes, durationMs) {
  const lead = Math.min(800, durationMs * 0.1);
  const span = durationMs * 0.62;
  await sleep(lead);
  for (let i = 0; i < nodes.length; i++) {
    nodes[i].classList.add('in');
    if (i < nodes.length - 1) await sleep(span / Math.max(1, nodes.length - 1));
  }
}

// ---------- templates ----------

async function tplTitle(spec, dur) {
  const w = el('div', 't-wrap');
  const k = el('div', 't-kicker fade', spec.kicker || 'HubSpot Admin');
  const t = el('div', 't-title fade', spec.title);
  w.append(k, t);
  let nodes = [k, t];
  if (spec.subtitle) { const s = el('div', 't-sub fade', spec.subtitle); w.appendChild(s); nodes.push(s); }
  stage().appendChild(w); chrome();
  await staggerIn(nodes, dur);
}

async function tplBullets(spec, dur) {
  const w = el('div', 'b-wrap');
  const h = el('div', 'b-head fade', spec.title);
  w.appendChild(h);
  const nodes = [h];
  (spec.bullets || []).forEach((b, i) => {
    const item = el('div', 'b-item fade');
    item.append(el('div', 'b-dot', String(i + 1)), el('div', 'b-text', b));
    w.appendChild(item); nodes.push(item);
  });
  stage().appendChild(w); chrome();
  await staggerIn(nodes, dur);
}

async function tplCode(spec, dur) {
  const w = el('div', 'c-wrap');
  if (spec.title) w.appendChild(el('div', 'c-head', spec.title));
  const box = el('div', 'c-box');
  const tb = el('div', 'c-titlebar');
  ['#ff5f57', '#febc2e', '#28c840'].forEach(c => {
    const d = el('div', 'c-dot'); d.style.background = c; tb.appendChild(d);
  });
  tb.appendChild(el('div', 'c-file', spec.file || 'script.py'));
  const code = el('div', 'c-code');
  box.append(tb, code); w.appendChild(box);
  stage().appendChild(w); chrome();

  // type the code out over ~70% of the scene
  const text = spec.code || '';
  const caret = el('span', 'caret');
  code.appendChild(caret);
  const typeSpan = dur * 0.7;
  const chunk = Math.max(1, Math.ceil(text.length / (typeSpan / 24)));
  let pos = 0;
  while (pos < text.length) {
    pos = Math.min(text.length, pos + chunk);
    caret.remove();
    code.innerHTML = highlight(text.slice(0, pos));
    code.appendChild(caret);
    await sleep(24);
  }
}

function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
// Single-pass tokenizer — sequential .replace() passes corrupt earlier spans'
// attributes (the string regex matches the "cm" in class="cm").
function highlight(src) {
  const re = /(#[^\n]*)|("[^"\n]*"|'[^'\n]*')|\b(import|from|def|return|if|else|for|in|await|async|const|let|not|None|True|False)\b|\b(\d+)\b/g;
  let out = '', last = 0, m;
  while ((m = re.exec(src))) {
    out += esc(src.slice(last, m.index));
    if (m[1]) out += '<span class="cm">' + esc(m[1]) + '</span>';
    else if (m[2]) out += '<span class="str">' + esc(m[2]) + '</span>';
    else if (m[3]) out += '<span class="kw">' + esc(m[3]) + '</span>';
    else out += '<span class="num">' + esc(m[4]) + '</span>';
    last = re.lastIndex;
  }
  return out + esc(src.slice(last));
}

async function tplDiagram(spec, dur) {
  const w = el('div', 'd-wrap');
  const h = el('div', 'd-head fade', spec.title);
  w.appendChild(h);
  const row = el('div', 'd-row');
  const nodes = [h];
  (spec.boxes || []).forEach((b, i) => {
    if (i > 0) { const a = el('div', 'd-arrow fade', '→'); row.appendChild(a); nodes.push(a); }
    const box = el('div', 'd-box fade' + (b.accent ? ' accent' : ''));
    box.append(el('div', 'big', b.title), el('div', 'small', b.detail || ''));
    row.appendChild(box); nodes.push(box);
  });
  w.appendChild(row);
  stage().appendChild(w); chrome();
  await staggerIn(nodes, dur);
}

// HubSpot-style CRM mock with cursor choreography.
async function tplUI(spec, dur) {
  const frame = el('div', 'hs-frame');
  const top = el('div', 'hs-top');
  top.appendChild(el('div', 'hs-logo'));
  (spec.nav || ['Contacts', 'Companies', 'Deals', 'Automation', 'Reporting']).forEach((n, i) => {
    top.appendChild(el('div', 'hs-nav' + (i === (spec.activeNav ?? 0) ? ' active' : ''), n));
  });
  const body = el('div', 'hs-body');
  body.appendChild(el('div', 'hs-h1', spec.title || 'Contacts'));
  if (spec.subtitle) body.appendChild(el('div', 'hs-h2', spec.subtitle));

  const table = el('table', 'hs');
  const thead = el('tr');
  (spec.columns || []).forEach(c => thead.appendChild(el('th', null, c)));
  table.appendChild(thead);
  (spec.rows || []).forEach((r, ri) => {
    const tr = el('tr'); tr.id = 'row-' + ri;
    r.forEach((cell, ci) => {
      const td = el('td', ci === 0 ? 'link' : null);
      td.innerHTML = cell;            // cells may carry <span class="pill ...">
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });
  body.appendChild(table);
  frame.appendChild(body);

  // modal (hidden until an action shows it)
  const modal = el('div', 'hs-modal');
  const panel = el('div', 'panel');
  modal.appendChild(panel);
  frame.appendChild(modal);

  const cursor = el('div', null, CURSOR_SVG); cursor.id = 'cursor';
  stage().appendChild(frame);
  stage().appendChild(cursor);
  chrome('Simulated interface for demonstration');

  // choreography: actions run at fractions of the scene duration
  const acts = spec.actions || [];
  let elapsed = 0;
  for (const a of acts) {
    const at = (a.at ?? 0) * dur;
    if (at > elapsed) { await sleep(at - elapsed); elapsed = at; }
    if (a.type === 'cursor') {
      const t = document.querySelector(a.sel);
      if (t) {
        const r = t.getBoundingClientRect();
        cursor.style.left = (r.left + Math.min(r.width - 20, a.dx ?? r.width / 2)) + 'px';
        cursor.style.top = (r.top + r.height / 2) + 'px';
      }
    } else if (a.type === 'click') {
      cursor.classList.add('click');
      setTimeout(() => cursor.classList.remove('click'), 380);
      if (a.sel) document.querySelector(a.sel)?.classList.add('hl');
    } else if (a.type === 'highlight') {
      document.querySelectorAll(a.sel).forEach(n => n.classList.add('hl'));
    } else if (a.type === 'modal') {
      panel.innerHTML = '<h3>' + a.title + '</h3>' + (a.body || []).map(p => '<p>' + p + '</p>').join('') +
        '<div class="btnrow"><div class="btn primary">' + (a.primary || 'Confirm') +
        '</div><div class="btn ghost">Cancel</div></div>';
      modal.classList.add('in');
    } else if (a.type === 'closeModal') {
      modal.classList.remove('in');
    }
  }
}

const TEMPLATES = { title: tplTitle, outro: tplTitle, bullets: tplBullets, code: tplCode, diagram: tplDiagram, ui: tplUI };

window.renderScene = async function (spec, durationMs) {
  stage().innerHTML = '';
  document.body.style.background = (spec.template === 'ui') ? '#1a2a3d' : '#0b1623';
  const fn = TEMPLATES[spec.template];
  if (!fn) throw new Error('unknown template: ' + spec.template);
  await fn(spec, durationMs);
  return 'done';
};
