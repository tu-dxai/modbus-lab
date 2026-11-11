// THÀNH PHẦN GIAO DIỆN DÙNG CHUNG — trang collector và trang điều khiển simulator (cần /i18n.js trước).
//   el(...)                 tạo phần tử
//   groupDevices(list)      nhóm thiết bị theo địa chỉ: nhiều thiết bị = gateway, một thiết bị = TCP trực tiếp
//   renderSidebar(...)      cột trái: ô tìm + "Tất cả" + danh sách thiết bị theo nhóm
//   sparkline(...)          đường xu hướng nhỏ
//   toast(...)              thông báo nổi góc phải dưới
//   selectedDevice()/selectDevice()  thiết bị đang chọn, lưu trên URL (#dev=...) để chia sẻ được đường dẫn
//   initResizer(key)        thanh ngăn kéo đổi chiều cao thẻ dưới (#resizer, #traffic, #content)
const $ = (s) => document.querySelector(s);
const SVG_NS = 'http://www.w3.org/2000/svg';
const ALL = '*';

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

function groupDevices(devices) {
  const groups = new Map();
  for (const d of devices) {
    if (!groups.has(d.endpoint)) groups.set(d.endpoint, { endpoint: d.endpoint, site: d.site_endpoint, devices: [] });
    groups.get(d.endpoint).devices.push(d);
  }
  return [...groups.values()].map(g => ({ ...g, gateway: g.devices.length > 1 }));
}

function deviceMatches(d, q) {
  if (!q) return true;
  const text = [d.name, d.endpoint, d.site_endpoint, ...(d.label ? Object.values(d.label) : [])].join(' ').toLowerCase();
  return q.toLowerCase().split(/\s+/).every(w => text.includes(w));
}

// opts: { selected, query, allMeta, itemMeta(d), itemDot(d) -> 'ok'|'warn'|'err'|'idle'|null, onSelect(name) }
function renderSidebar(box, devices, opts) {
  box.replaceChildren();
  const all = el('button', 'item all' + (opts.selected === ALL ? ' sel' : ''));
  all.append(el('span', 'name', t('ui.all_devices')), el('span', 'meta num', opts.allMeta || ''));
  all.onclick = () => opts.onSelect(ALL);
  box.append(all);
  let shown = 0;
  for (const g of groupDevices(devices)) {
    const list = g.devices.filter(d => deviceMatches(d, opts.query));
    if (!list.length) continue;
    const head = el('div', 'group');
    const proto = g.devices[0].meta && g.devices[0].meta.protocol;
    const kind = proto === 'snmp' ? 'ui.snmp_agent' : proto === 'bacnet' ? 'ui.bacnet_ip'
      : g.endpoint.startsWith('rtu:') ? 'ui.serial_bus' : g.gateway ? 'ui.gateway' : 'ui.direct';
    head.append(document.createTextNode(t(kind, { endpoint: '' })), el('span', 'mono', g.site.replace(/^rtu:/, '')));
    head.title = g.site !== g.endpoint ? `${g.site} → ${g.endpoint}` : g.endpoint;
    box.append(head);
    for (const d of list) {
      shown++;
      const item = el('button', 'item' + (opts.selected === d.name ? ' sel' : ''));
      const dot = opts.itemDot ? opts.itemDot(d) : null;
      if (dot) item.append(el('span', 'dot ' + dot));
      item.append(el('span', 'name', tr(d.label) || d.name), el('span', 'meta', opts.itemMeta ? opts.itemMeta(d) : ''));
      item.title = d.name;
      item.onclick = () => opts.onSelect(d.name);
      box.append(item);
    }
  }
  if (!shown) box.append(el('div', 'empty', t('ui.no_match')));
}

function selectedDevice() {
  const m = location.hash.match(/dev=([^&]+)/);
  return m ? decodeURIComponent(m[1]) : ALL;
}

function selectDevice(name) {
  history.replaceState(null, '', name === ALL ? location.pathname + location.search
                                              : `#dev=${encodeURIComponent(name)}`);
}

function sparkline(svg, vals) {
  let line = svg.firstChild;
  if (!line) {
    svg.setAttribute('viewBox', '0 0 96 24');
    svg.setAttribute('preserveAspectRatio', 'none');
    line = document.createElementNS(SVG_NS, 'polyline');
    svg.append(line);
  }
  const v = vals.filter(x => x !== null);
  if (v.length < 2) { line.setAttribute('points', ''); return; }
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1, step = 96 / (vals.length - 1);
  line.setAttribute('points', vals.map((x, i) => x === null ? null
    : `${(i * step).toFixed(1)},${(21 - (x - lo) / span * 18).toFixed(1)}`).filter(Boolean).join(' '));
}

function newSpark() {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'spark');
  return svg;
}

let toastTimer;
function toast(msg, kind) {
  let box = $('#toast');
  if (!box) { box = el('div', 'toast'); box.id = 'toast'; document.body.append(box); }
  box.textContent = msg;
  box.className = 'toast ' + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.className = 'toast'; }, 5000);
}

function fmtNum(v, digits = 2) {
  return v === null || v === undefined ? '—' : Number(v).toLocaleString(locale(), { maximumFractionDigits: digits });
}

// Kéo thanh ngăn để đổi chiều cao thẻ dưới; nhấp đúp để về tự động. Lưu theo từng trang (key).
function initResizer(key) {
  const bar = $('#resizer'), lower = $('#traffic'), content = $('#content');
  try {
    const h = localStorage.getItem(key);
    if (h) { lower.style.height = h; content.classList.add('manual'); }
  } catch (e) { /* bỏ qua */ }
  bar.ondblclick = () => {
    lower.style.height = '';
    content.classList.remove('manual');
    try { localStorage.removeItem(key); } catch (e) { /* bỏ qua */ }
  };
  bar.onmousedown = (e) => {
    e.preventDefault();
    bar.classList.add('drag');
    content.classList.add('manual');
    const move = (ev) => {
      const box = content.getBoundingClientRect();
      lower.style.height = Math.min(Math.max(box.bottom - ev.clientY, 170), box.height - 150) + 'px';
    };
    const up = () => {
      bar.classList.remove('drag');
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      try { localStorage.setItem(key, lower.style.height); } catch (e) { /* bỏ qua */ }
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  };
}

// ---------- icon SVG tự vẽ (24x24, nét 2px) — không dùng thư viện ngoài ----------
const ICONS = {
  sidebar: 'M3 4h18v16H3z M9 4v16',
  pencil: 'M4 20h4L19 9l-4-4L4 16v4z M14 6l4 4',
  read: 'M20 11a8 8 0 1 0-2.34 5.66 M20 4v7h-7',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  x: 'M6 6l12 12 M18 6L6 18',
  help: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M9.6 9.2a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.6 M12 16.8v.4',
  reset: 'M4 11a8 8 0 1 1 2.34 5.66 M4 4v7h7',
  pause: 'M8 5v14 M16 5v14',
  play: 'M7 5l12 7-12 7z',
  trash: 'M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M20 20l-4.2-4.2',
  undo: 'M9 14L4 9l5-5 M4 9h10a6 6 0 0 1 0 12h-3',
  power: 'M12 3v8 M7.05 6.05a7 7 0 1 0 9.9 0',
};

function icon(name, cls) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'icon' + (cls ? ' ' + cls : ''));
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', ICONS[name]);
  svg.append(path);
  return svg;
}

// Nút chỉ có icon: chú thích (title + aria-label) lấy từ từ điển, dịch lại khi đổi ngôn ngữ.
function iconButton(name, titleKey, cls) {
  const b = el('button', 'icon-btn' + (cls ? ' ' + cls : ''));
  b.type = 'button';
  b.dataset.i18nTitle = titleKey;
  b.title = t(titleKey);
  b.setAttribute('aria-label', t(titleKey));
  b.append(icon(name));
  return b;
}

// Gắn icon vào các phần tử có data-icon="tên" (đặt trước chữ nếu có).
function applyIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach(e => {
    if (!e.querySelector(':scope > svg.icon')) e.prepend(icon(e.dataset.icon));
  });
}

// Chỗ của điểm trong thiết bị theo giao thức: "HR 4 · int16" / "OID 1.3.6..." / "BACnet analog-value,1 · P8".
function pointRef(p, protocol) {
  if (p.table) return regRef(p.table, p.address, ` · ${p.type}`);
  const span = el('span', 'reg-ref');
  const snmp = protocol === 'snmp';
  const abbr = el('abbr', '', snmp ? 'OID' : 'BACnet');
  abbr.title = t(snmp ? 'ui.oid_title' : 'ui.bacnet_title');
  span.append(abbr, ' ' + (p.ref || '').replace(/^OID /, ''));
  if (p.priority) {
    const pr = el('abbr', '', `P${p.priority}`);
    pr.title = t('ui.priority_title', { priority: p.priority });
    span.append(' · ', pr);
  }
  return span;
}

// Dòng mô tả thiết bị theo giao thức (meta = device_meta trong Point Map).
function deviceMetaText(d, meta, site) {
  const base = { endpoint: d.endpoint, site };
  if (meta.protocol === 'snmp') return t('common.device_meta_snmp', { ...base, version: meta.version });
  if (meta.protocol === 'bacnet') return t('common.device_meta_bacnet', { ...base, instance: meta.instance });
  return t('common.device_meta', { ...base, id: meta.id, order: meta.order });
}

// Nhãn ngắn ở cột thiết bị: "id 1" / "SNMP v2c" / "BACnet 5001".
function deviceShort(meta) {
  if (meta.protocol === 'snmp') return `SNMP v${meta.version}`;
  if (meta.protocol === 'bacnet') return `BACnet ${meta.instance}`;
  return t('ui.device_id', { id: meta.id });
}

// "HR 4" / "IR 100" kèm chú thích khi rê chuột: HR = Holding Register, IR = Input Register.
function regRef(table, address, extra) {
  const span = el('span', 'reg-ref');
  const abbr = el('abbr', '', table === 'holding' || table === 'HR' ? 'HR' : 'IR');
  abbr.title = t(abbr.textContent === 'HR' ? 'ui.hr_title' : 'ui.ir_title');
  span.append(abbr, ` ${address}${extra || ''}`);
  return span;
}

// ---------- khung: thu/mở cột thiết bị, hướng dẫn cho người mới ----------
// page: 'dash' | 'sim' — lưu lựa chọn riêng cho từng trang; lần đầu mở trang thì tự hiện hướng dẫn.
function initShell(page) {
  const app = $('.app');
  const keySide = `${page}SideHidden`, keyHelp = `${page}HelpSeen`;
  const setSide = (hidden) => {
    app.classList.toggle('side-hidden', hidden);
    try { localStorage.setItem(keySide, hidden ? '1' : ''); } catch (e) { /* bỏ qua */ }
  };
  try { app.classList.toggle('side-hidden', localStorage.getItem(keySide) === '1'); } catch (e) { /* bỏ qua */ }
  $('#side-toggle').onclick = () => setSide(!app.classList.contains('side-hidden'));

  const help = $('#help');
  const openHelp = () => { renderHelp(page); help.hidden = false; $('#help .icon-btn').focus(); };
  const closeHelp = () => {
    help.hidden = true;
    try { localStorage.setItem(keyHelp, '1'); } catch (e) { /* bỏ qua */ }
  };
  $('#help-open').onclick = openHelp;
  $('#help .drawer-head .icon-btn').onclick = closeHelp;
  help.onclick = (e) => { if (e.target === help) closeHelp(); };
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !help.hidden) { closeHelp(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey || /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
    if (e.key === '?') { e.preventDefault(); help.hidden ? openHelp() : closeHelp(); }
    if (e.key === '[') { e.preventDefault(); setSide(!app.classList.contains('side-hidden')); }
  });
  help._close = closeHelp;
  let seen = false;
  try { seen = localStorage.getItem(keyHelp) === '1'; } catch (e) { seen = true; }
  if (!seen) openHelp();
  applyIcons();
}

function renderHelp(page) {
  const box = $('#help .drawer-body');
  if (!box) return;
  const section = (titleKey, ...nodes) => {
    const s = el('section');
    s.append(el('h3', '', t(titleKey)), ...nodes);
    return s;
  };
  const steps = el('ol', 'steps');
  for (let i = 1; i <= 4; i++) steps.append(el('li', '', t(`help.${page}_step${i}`)));
  const terms = el('dl', 'terms');
  for (const k of ['hr', 'ir', 'fc', 'unit', 'order', 'scale', 'gateway', 'oid', 'priority']) {
    terms.append(el('dt', '', t(`help.term_${k}`)), el('dd', '', t(`help.def_${k}`)));
  }
  $('#help h2').textContent = t(`help.${page}_title`);
  box.replaceChildren(el('p', 'intro', t(`help.${page}_intro`)), section('help.steps', steps),
                      section('help.terms', terms), section('help.keys', el('p', 'keys', t(`help.${page}_keys`))));
}

// ---------- sửa tại chỗ: bấm ✎ -> ô nhập ngay trong ô bảng; Enter lưu, Esc hủy ----------
// opts: { value, hint, unit, choices?: [giá trị], onSave(v) -> Promise (ném Error(message) nếu lỗi) }
function openEditor(cell, opts) {
  if (cell.querySelector('.editor')) return;
  const keep = [...cell.childNodes];
  const box = el('div', 'editor');
  const msg = el('div', 'editor-msg');
  const close = () => cell.replaceChildren(...keep);
  const save = async (v) => {
    msg.textContent = '';
    box.classList.add('busy');
    try { await opts.onSave(v); close(); }
    catch (e) { msg.textContent = e.message; box.classList.remove('busy'); }
  };
  if (opts.choices) {
    for (const v of opts.choices) {
      const b = el('button', 'btn sm' + (Number(v) === Number(opts.value) ? ' on' : ''), String(v));
      b.type = 'button';
      b.onclick = () => save(v);
      box.append(b);
    }
  } else {
    const inp = el('input', 'field');
    inp.type = 'number'; inp.step = 'any';
    inp.value = opts.value ?? '';
    inp.placeholder = opts.hint || '';
    inp.onkeydown = (e) => {
      if (e.key === 'Enter' && inp.value !== '') save(Number(inp.value));
      if (e.key === 'Escape') { e.stopPropagation(); close(); }
    };
    const ok = iconButton('check', 'ui.save', 'ok');
    ok.onclick = () => inp.value !== '' && save(Number(inp.value));
    box.append(inp);
    if (opts.unit) box.append(el('span', 'unit', opts.unit));
    box.append(ok);
    setTimeout(() => { inp.focus(); inp.select(); });
  }
  const cancel = iconButton('x', 'ui.cancel');
  cancel.onclick = close;
  box.append(cancel);
  if (opts.hint && opts.choices) box.title = opts.hint;
  cell.replaceChildren(box, msg);
}
