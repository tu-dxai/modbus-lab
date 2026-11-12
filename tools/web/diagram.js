// SƠ ĐỒ DC — hai tab trên trang simulator, dữ liệu từ GET /api/topology (tools/simulator/topology.py):
//   renderArchitecture: thiết bị theo hệ thống (EPMS, BMS) -> kết nối -> Edge Site Stack -> MQTT -> trung tâm
//   renderPowerLine:    sơ đồ đơn tuyến điện theo Point Map mục topology, kèm đường làm mát
// Phần mềm chưa có vẽ nét đứt, mờ. Cấu trúc dựng lại khi đổi dữ liệu / ngôn ngữ; giá trị và trạng thái
// bật / tắt cập nhật mỗi lần gọi updateDiagram(points) (trang gọi sau mỗi lần tải /api/state).
// Cần /i18n.js và /ui.js trước. Trang gọi initDiagram({ deviceLabel(name), onOpen(name), onPower(name, on),
//   powerTitle(name, off) }) — powerTitle: chú thích nút bật / tắt (thiết bị tắt sẽ phản ứng thế nào).

const DG = { opts: null, box: null, view: null, model: null, shape: '', wires: [], cards: {}, values: {} };

const LINK_ICON = { gateway: 'plug', rtu: 'plug', direct: 'plug', snmp: 'plug', bacnet: 'plug' };
const KIND_ICON = { grid: 'bolt', panel: 'panel', ups: 'ups', battery: 'battery', load: 'rack', cooling: 'fan' };
const key = (id) => id.replace(/-/g, '_');            // id có gạch ngang -> khóa từ điển
const PART_ICON = { 'point-map': 'panel', telegraf: 'server', 'bacnet-collector': 'server', 'write-service': 'pencil',
                    alerts: 'help', collector: 'read', mqtt: 'cloud', dcim: 'cloud', itsm: 'cloud' };

function initDiagram(opts) {
  DG.opts = opts;
  window.addEventListener('resize', () => DG.box && drawWires());
}

// ---------- phần dùng chung ----------
function pointLabel(points, key) {
  const p = points[key];
  return p ? tr(p.label) || key.split('.')[1] : key;
}

function deviceOnIn(points, name) {
  const p = Object.values(points).find(x => x.device === name);
  return !p || p.on !== false;
}

function statusBadge(status) {
  const b = el('span', 'badge dg-status ' + status, t(`topo.status.${status}`));
  b.title = t(`topo.status_hint.${status}`);
  return b;
}

// Thẻ thiết bị: tên, mã, chấm trạng thái, giá trị (cập nhật mỗi giây), nút bật / tắt.
function deviceCard(name, points, keys) {
  const card = el('div', 'dg-card dg-device');
  card.dataset.node = name;
  const head = el('div', 'dg-head');
  const dot = el('span', 'dot');
  head.append(dot, el('span', 'dg-name', DG.opts.deviceLabel(name)));
  const pw = iconButton('power', 'simui.turn_on_hint', 'dg-power');
  pw.onclick = (e) => { e.stopPropagation(); DG.opts.onPower(name, !deviceOnIn(DG.points, name)); };
  head.append(pw);
  const sub = el('div', 'dg-code', name);
  const vals = el('div', 'dg-vals');
  card.append(head, sub, vals);
  card.onclick = () => DG.opts.onOpen(name);
  card.title = t('topo.open_device');
  DG.cards[name] = { card, dot, pw, vals, keys };
  return card;
}

function partCard(part) {
  const card = el('div', 'dg-card dg-part ' + part.status);
  card.dataset.node = part.id;
  const head = el('div', 'dg-head');
  head.append(icon(PART_ICON[part.id] || 'server'), el('span', 'dg-name', t(`topo.part.${key(part.id)}`)));
  card.append(head, el('div', 'dg-note', t(`topo.note.${key(part.id)}`)));
  const foot = el('div', 'dg-foot');
  foot.append(statusBadge(part.status));
  if (part.path) foot.append(el('code', 'dg-path', part.path));
  card.append(foot);
  return card;
}

function column(titleKey, params, ...children) {
  const col = el('div', 'dg-col');
  col.append(el('h4', '', t(titleKey, params)), ...children);
  return col;
}

// ---------- dây nối: lớp SVG phủ lên sơ đồ, tính lại khi đổi kích thước ----------
function wireLayer(host) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'dg-wires');
  const defs = document.createElementNS(SVG_NS, 'defs');
  for (const [id, cls] of [['dg-arrow', 'arrow'], ['dg-arrow-cool', 'arrow cool']]) {
    const m = document.createElementNS(SVG_NS, 'marker');
    m.setAttribute('id', id); m.setAttribute('viewBox', '0 0 10 10'); m.setAttribute('refX', '9'); m.setAttribute('refY', '5');
    m.setAttribute('markerWidth', '7'); m.setAttribute('markerHeight', '7'); m.setAttribute('orient', 'auto-start-reverse');
    const p = document.createElementNS(SVG_NS, 'path');
    p.setAttribute('d', 'M0 0L10 5L0 10z'); p.setAttribute('class', cls);
    m.append(p); defs.append(m);
  }
  svg.append(defs);
  host.append(svg);
  return svg;
}

// w: { from, to, style: 'flow'|'planned'|'power'|'cool', mode: 'curve'|'elbow', label }
function drawWires() {
  const host = DG.box && DG.box.querySelector('.dg-canvas');
  if (!host) return;
  const svg = host.querySelector('svg.dg-wires');
  [...svg.querySelectorAll('path.wire, text.wire-label')].forEach(x => x.remove());
  svg.setAttribute('width', host.scrollWidth); svg.setAttribute('height', host.scrollHeight);
  const base = host.getBoundingClientRect();
  const box = (id) => {
    const n = host.querySelector(`[data-node="${CSS.escape(id)}"]`);
    if (!n) return null;
    const r = n.getBoundingClientRect();
    return { l: r.left - base.left + host.scrollLeft, r: r.right - base.left + host.scrollLeft,
             t: r.top - base.top + host.scrollTop, b: r.bottom - base.top + host.scrollTop };
  };
  for (const w of DG.wires) {
    const a = box(w.from), b = box(w.to);
    if (!a || !b) continue;
    let d, lx, ly;
    if (w.mode === 'elbow') {                            // đơn tuyến: từ đáy nút trên xuống đỉnh nút dưới
      const x1 = (a.l + a.r) / 2, y1 = a.b, x2 = (b.l + b.r) / 2, y2 = b.t, ym = y1 + (y2 - y1) / 2;
      d = `M${x1} ${y1}V${ym}H${x2}V${y2}`;
    } else if (Math.abs((a.l + a.r) / 2 - (b.l + b.r) / 2) < 40) {     // cùng cột: nối dọc
      const x = (a.l + a.r) / 2;
      d = `M${x} ${a.b}V${b.t}`;
    } else {                                             // khác cột: đường cong từ cạnh phải sang cạnh trái
      const fwd = b.l >= a.r;
      const x1 = fwd ? a.r : a.l, y1 = (a.t + a.b) / 2, x2 = fwd ? b.l : b.r, y2 = (b.t + b.b) / 2;
      const c = Math.max(30, Math.abs(x2 - x1) / 2) * (fwd ? 1 : -1);
      d = `M${x1} ${y1}C${x1 + c} ${y1} ${x2 - c} ${y2} ${x2} ${y2}`;
      lx = (x1 + x2) / 2; ly = (y1 + y2) / 2 - 6;
    }
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', d);
    path.setAttribute('class', `wire ${w.style}`);
    if (w.style !== 'power') path.setAttribute('marker-end', `url(#${w.style === 'cool' ? 'dg-arrow-cool' : 'dg-arrow'})`);
    svg.append(path);
    if (w.label && lx !== undefined) {
      const txt = document.createElementNS(SVG_NS, 'text');
      txt.setAttribute('x', lx); txt.setAttribute('y', ly); txt.setAttribute('class', `wire-label ${w.style}`);
      txt.textContent = w.label;
      svg.append(txt);
    }
  }
}

// ---------- tab kiến trúc ----------
function renderArchitecture(box, model, points) {
  DG.box = box; DG.model = model; DG.points = points; DG.wires = []; DG.cards = {};
  const canvas = el('div', 'dg-canvas dg-arch');
  const parts = Object.fromEntries([...model.edge, ...model.center].map(p => [p.id, p]));

  const field = column('topo.col.field', {});
  for (const s of model.systems) {
    const g = el('div', 'dg-group sys-' + s.id);
    const head = el('div', 'dg-group-head');
    const sid = s.id.toLowerCase();
    head.append(el('b', '', s.id === 'other' ? '—' : s.id), el('span', '', t(`topo.system.${sid}`)));
    g.append(head, el('p', 'dg-group-desc', t(`topo.system_desc.${sid}`)),
             ...s.devices.map(n => deviceCard(n, points, firstKeys(points, n, 1))));
    field.append(g);
  }

  const links = column('topo.col.links', {});
  for (const l of model.links) {
    const card = el('div', 'dg-card dg-link');
    card.dataset.node = l.id;
    const head = el('div', 'dg-head');
    head.append(icon(LINK_ICON[l.kind]), el('span', 'dg-name', t(`topo.link.${l.kind}`)));
    card.append(head, el('div', 'dg-code', l.site_endpoint.replace(/^rtu:/, '')));
    card.title = t(`topo.link_hint.${l.kind}`);
    links.append(card);
    for (const dev of l.devices) DG.wires.push({ from: dev, to: l.id, style: 'flow' });
    DG.wires.push({ from: l.id, to: l.to, style: 'flow' });
  }

  const edgeGroup = el('div', 'dg-group edge');
  const eh = el('div', 'dg-group-head');
  eh.append(el('b', '', 'Edge'), el('span', '', t('topo.edge_hint')));
  edgeGroup.append(eh, ...model.edge.map(partCard));
  const edge = column('topo.col.edge', { site: model.site }, edgeGroup);

  const up = column('topo.col.uplink', {}, ...model.center.filter(p => p.id === 'mqtt').map(partCard));
  const center = column('topo.col.center', {}, ...model.center.filter(p => p.id !== 'mqtt').map(partCard));
  for (const f of model.flows) {
    DG.wires.push({ from: f.from, to: f.to, style: parts[f.to].status === 'planned' ? 'planned' : 'flow' });
  }

  canvas.append(field, links, edge, up, center);
  const legend = el('div', 'dg-legend');
  legend.append(glossaryButton(), statusBadge('ready'), statusBadge('partial'), statusBadge('planned'),
                el('span', 'muted', t('topo.legend_arch')));
  box.replaceChildren(legend, canvas);
  wireLayer(canvas);
  updateDiagram(points);
  requestAnimationFrame(drawWires);
}

// Nút mở hướng dẫn tại phần "Các hệ thống trong data center" (EPMS, BMS, DCIM, ITSM...).
function glossaryButton() {
  const b = el('button', 'btn sm dg-glossary');
  b.append(icon('help'), el('span', '', t('topo.glossary_link')));
  b.onclick = () => window.openHelpAt && window.openHelpAt('help-systems');
  return b;
}

function firstKeys(points, name, n) {
  return Object.keys(points).filter(k => k.startsWith(name + '.')).slice(0, n);
}

// ---------- tab đơn tuyến ----------
const NODE_W = 210, NODE_H = 112, GAP_X = 34, GAP_Y = 40;

function layoutTree(nodes) {
  const kids = {};
  for (const n of nodes) (kids[n.parent] = kids[n.parent] || []).push(n);
  const pos = {};
  let next = 0;
  const place = (n) => {
    const c = kids[n.id] || [];
    c.forEach(place);
    const x = c.length ? (pos[c[0].id].x + pos[c[c.length - 1].id].x) / 2 : next++;
    pos[n.id] = { x, y: n.depth };
  };
  (kids[null] || []).forEach(place);
  return { pos, cols: Math.max(next, 1), rows: Math.max(0, ...nodes.map(n => n.depth)) + 1 };
}

function renderPowerLine(box, model, points) {
  DG.box = box; DG.model = model; DG.points = points; DG.wires = []; DG.cards = {};
  const head = el('div', 'dg-legend');
  head.append(glossaryButton());
  if (model.assumed) {
    const warn = el('div', 'dg-assumed');
    warn.append(icon('help'), el('span', '', t('topo.assumed')));
    head.append(warn);
  }
  if (!model.power.length) {
    box.replaceChildren(head, el('div', 'empty-box', t('topo.no_power')));
    return;
  }
  const { pos, cols, rows } = layoutTree(model.power);
  const canvas = el('div', 'dg-canvas dg-powerline');
  const inner = el('div', 'dg-tree');
  inner.style.width = `${cols * (NODE_W + GAP_X)}px`;
  inner.style.height = `${rows * (NODE_H + GAP_Y)}px`;
  for (const n of model.power) {
    const card = el('div', `dg-card dg-pnode kind-${n.kind}`);
    card.dataset.node = n.id;
    card.style.left = `${pos[n.id].x * (NODE_W + GAP_X)}px`;
    card.style.top = `${pos[n.id].y * (NODE_H + GAP_Y)}px`;
    card.style.width = `${NODE_W}px`;
    const h = el('div', 'dg-head');
    h.append(icon(KIND_ICON[n.kind]), el('span', 'dg-name', tr(n.label)));
    const dot = el('span', 'dot');
    if (n.device) h.prepend(dot);
    card.append(h, el('div', 'dg-code', t(`topo.kind.${n.kind}`)));
    const vals = el('div', 'dg-vals');
    card.append(vals);
    const meters = el('div', 'dg-meters');
    for (const m of n.meters) {
      const chip = el('button', 'dg-meter');
      chip.append(icon('read'), document.createTextNode(m));
      chip.title = t('topo.meter_hint', { device: DG.opts.deviceLabel(m) });
      chip.onclick = (e) => { e.stopPropagation(); DG.opts.onOpen(m); };
      meters.append(chip);
    }
    if (n.meters.length) card.append(meters);
    if (n.device) { card.onclick = () => DG.opts.onOpen(n.device); card.title = t('topo.open_device'); }
    DG.cards[n.id] = { card, dot: n.device ? dot : null, vals, keys: n.show, device: n.device, meters: n.meters };
    inner.append(card);
    if (n.parent) DG.wires.push({ from: n.parent, to: n.id, style: 'power', mode: 'elbow' });
  }
  for (const c of model.cooling) {
    const src = model.power.find(n => n.device === c.device);
    if (src) DG.wires.push({ from: src.id, to: c.serves, style: 'cool', label: t('topo.cooling') });
  }
  canvas.append(inner);
  box.replaceChildren(head, canvas);
  wireLayer(canvas);
  updateDiagram(points);
  requestAnimationFrame(drawWires);
}

// ---------- cập nhật giá trị và bật / tắt (mỗi giây) ----------
function updateDiagram(points) {
  DG.points = points;
  for (const [id, c] of Object.entries(DG.cards)) {
    const devs = c.device !== undefined ? [c.device, ...(c.meters || [])].filter(Boolean) : [id];
    const off = devs.some(n => !deviceOnIn(points, n));
    c.card.classList.toggle('off', off);
    if (c.dot) c.dot.className = 'dot ' + (off ? 'idle' : 'ok');
    if (c.pw) {
      c.pw.classList.toggle('is-off', off);
      c.pw.title = DG.opts.powerTitle(id, off);
    }
    c.vals.replaceChildren(...c.keys.map(k => {
      const p = points[k];
      const row = el('div', 'dg-val');
      const down = p && p.on === false;
      row.append(el('span', 'k', pointLabel(points, k)),
                 el('span', 'v', !p || down ? '—' : `${fmtNum(p.value, 2)} ${p.unit || ''}`.trim()));
      return row;
    }));
  }
}
