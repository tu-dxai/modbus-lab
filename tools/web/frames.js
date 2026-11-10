// KHUNG TIN (Modbus TCP / RTU, SNMP, BACnet/IP) — danh sách cặp hỏi/đáp (một dòng mỗi cặp) + chi tiết từng byte.
// Dùng trên trang collector: "Gửi" là byte collector gửi tới thiết bị, "Nhận" là byte thiết bị trả về.
// Cần /i18n.js và /ui.js trước. Trang gọi initFrames({ devices, deviceName, pointName }) rồi pollFrames()
// sau mỗi lần đọc/ghi — không tự gọi định kỳ.
//
// Phần tử trang cần có: #frames (tbody), #detail, #n-frames, #f-device, #f-function, #f-errors,
// #f-pause, #f-clear, #f-paused.

// gen: tăng mỗi lần đổi bộ lọc/xóa; kết quả của yêu cầu gửi trước đó bị bỏ, tránh lẫn bộ lọc cũ.
const FR = { since: 0, paused: false, items: [], max: 300, gen: 0, sel: null, opts: null };

const hex2 = (n) => n.toString(16).padStart(2, '0').toUpperCase();
const fmtFrame = (v) => v === null || v === undefined ? '?' : fmtNum(v, 3);

function fillFrameDevices() {
  const sel = $('#f-device'), keep = sel.value;
  sel.replaceChildren(el('option', '', t('frames.all_devices')));
  sel.firstChild.value = '';
  for (const d of FR.opts.devices()) {
    const o = el('option', '', tr(d.label) || d.name);
    o.value = d.name;
    sel.append(o);
  }
  sel.value = keep;
}

function frameQuery() {
  const q = new URLSearchParams({ since: FR.since, limit: FR.max });
  if ($('#f-device').value) q.set('device', $('#f-device').value);
  if ($('#f-function').value) q.set('function', $('#f-function').value);
  if ($('#f-errors').checked) q.set('errors', '1');
  return q;
}

async function pollFrames() {
  if (FR.paused) return;
  const gen = FR.gen;
  const res = await fetch('/api/frames?' + frameQuery(), { cache: 'no-store' });
  const { frames } = await res.json();
  if (gen !== FR.gen) return;                       // bộ lọc đã đổi trong lúc chờ: bỏ kết quả cũ
  const fresh = frames.filter(f => f.seq > FR.since);   // hai lần tải chồng nhau: không thêm trùng
  if (!fresh.length) return;
  FR.since = fresh[fresh.length - 1].seq;
  FR.items = FR.items.concat(fresh).slice(-FR.max);
  renderFrames();
}

function restartFrames() {
  FR.gen++;
  FR.since = 0; FR.items = []; FR.sel = null;
  renderFrames();
  pollFrames().catch(() => {});
}

function frameBad(f) {
  return f.exception !== null || f.status !== null || (f.request && f.request.malformed)
         || (f.response && f.response.malformed);
}

function frameDevice(f) {
  if (f.device) return FR.opts.deviceName(f.device);
  return f.protocol && f.protocol !== 'modbus' ? t('frames.unknown_endpoint', { endpoint: f.site_endpoint })
    : t('frames.unknown_device', { id: f.device_id, endpoint: f.site_endpoint });
}

// Cột "Lệnh": FC03 (Modbus) / GET (SNMP) / RP, WP (BACnet ReadProperty, WriteProperty).
const FN_SHORT = { get: 'GET', 'get-next': 'GETNEXT', 'read-property': 'RP', 'write-property': 'WP' };
function fnLabel(f) {
  if (f.function === null || f.function === undefined) return '—';
  if (typeof f.function === 'number') return `FC${String(f.function).padStart(2, '0')}`;
  return FN_SHORT[f.function] || f.function;
}

// SNMP / BACnet: "OID 1.3.6…4.0 → Mức pin = 100 %" / "BACnet analog-value,1 ← 21.5 · P8 → …"
function udpSummary(f) {
  const r = f.request;
  const ref = el('span', 'reg-ref');
  const snmp = f.protocol === 'snmp';
  const abbr = el('abbr', '', snmp ? 'OID' : 'BACnet');
  abbr.title = t(snmp ? 'ui.oid_title' : 'ui.bacnet_title');
  ref.append(abbr, ' ' + (r.ref || '?').replace(/^OID /, ''));
  if (r.write) {
    ref.append(r.write.value === null ? ' ← NULL' : ` ← ${fmtFrame(r.write.value)}`);
    if (r.write.priority) ref.append(` · P${r.write.priority}`);
  }
  return ref;
}

// Tóm tắt ngắn kiểu công cụ Modbus: "IR 100–101 → Mức pin = 80 %"; câu đầy đủ xem khi rê chuột.
function shortSummary(f) {
  const r = f.request;
  if (!r) return [null, t(f.status.key, f.status.params)];
  if (f.protocol && f.protocol !== 'modbus' && !r.malformed) return [udpSummary(f), valueText(f)];
  if (r.malformed || (!r.start && r.start !== 0)) return [null, t(r.summary.key, r.summary.params)];
  const area = f.function === 4 ? 'IR' : 'HR';
  const range = r.quantity > 1 ? `${r.start}–${r.start + r.quantity - 1}` : String(r.start);
  let ref = `${area} ${range}`;
  if (f.function === 6 || f.function === 16) ref += ` ← ${r.registers.join(', ')}`;
  return [ref, valueText(f)];
}

function valueText(f) {
  if (f.values.length) {
    const v = f.values[0];
    return ` → ${FR.opts.pointName(v.key)} = ${fmtFrame(v.value)} ${v.unit}` +
           (f.values.length > 1 ? ` · ${t('ui.more_values', { n: f.values.length - 1 })}` : '');
  }
  if (f.status) return ` → ${t(f.status.key, f.status.params)}`;
  if (f.response && f.exception !== null) return ` → ${t(f.response.summary.key, f.response.summary.params)}`;
  return '';
}

function resultMark(f) {
  if (!frameBad(f)) { const d = el('span', 'dot'); d.title = t(f.response.summary.key, f.response.summary.params); return d; }
  let text, title;
  if (f.status) {
    text = t(f.request ? 'frames.no_response' : 'frames.unreachable');
    title = t(f.status.key, f.status.params);
  } else {
    text = t('common.error') + (typeof f.exception === 'number' ? ' ' + hex2(f.exception) : '');
    title = t(f.response.summary.key, f.response.summary.params);
  }
  const b = el('span', 'badge err', text);
  b.title = title;
  return b;
}

function frameRow(f) {
  const row = el('tr', 'clickable' + (f.seq === FR.sel ? ' sel' : ''));
  const fc = el('td', 'mono', fnLabel(f));
  fc.title = f.function ? t(f.fc_key) : '';
  const [ref, rest] = shortSummary(f);
  const sum = el('td', 'sum');
  if (ref instanceof Node) sum.append(ref, el('span', 'val', rest));                       // OID / BACnet
  else if (ref) sum.append(regRef(ref.slice(0, 2), ref.slice(3)), el('span', 'val', rest));   // HR/IR có chú thích
  else sum.textContent = rest;
  sum.title = f.request ? t(f.request.summary.key, f.request.summary.params) +
    (f.response ? ` · ${t(f.response.summary.key, f.response.summary.params)}` : '') : '';
  const res = el('td');
  res.append(resultMark(f));
  const dev = el('td', '', frameDevice(f));
  dev.title = `${f.device || ''} @ ${f.site_endpoint}`;
  row.append(el('td', 'muted num', String(f.seq)), el('td', 'num', f.at.slice(11)), dev, fc, sum, res,
             el('td', 'r num muted', String(f.ms)));
  row.onclick = () => { FR.sel = f.seq; renderFrames(); };
  return row;
}

// Trường tô đỏ khi phản hồi báo lỗi (Modbus mã lỗi, SNMP error-status / noSuchObject, BACnet Error).
const ERR_FIELDS = new Set(['exception', 'function', 'error_status', 'error_index', 'error_class', 'error_code',
                            'reason', 'apdu_type']);

function byteLine(dir, cls, part, bad) {
  const line = el('div', 'line');
  const bytes = el('div', 'bytes');
  for (const f of part.fields) {
    const g = el('span', 'grp' + (bad && ERR_FIELDS.has(f.name) ? ' exc' : ''));
    g.append(el('b', '', f.hex), el('i', '', t(`frame.f.${f.name}`)));   // khóa ghép: frame.f.transaction, ...
    bytes.append(g);
  }
  line.append(el('span', 'dir ' + cls, dir), bytes);
  return [line, el('div', 'sum', t(part.summary.key, part.summary.params))];
}

function missingLine(dir, cls, status) {
  const line = el('div', 'line');
  line.append(el('span', 'dir ' + cls, dir), el('div', 'missing', t(status.key, status.params)));
  return [line];
}

function renderDetail() {
  const box = $('#detail');
  const f = FR.items.find(x => x.seq === FR.sel);
  if (!f) {
    box.className = 'detail';
    box.replaceChildren(el('div', 'empty-box', t('ui.select_frame')), el('div', 'legend', t('frames.hint')));
    return;
  }
  const bad = frameBad(f);
  box.className = 'detail' + (bad ? ' bad' : '');
  const head = el('div', 'head');
  head.append(el('span', 'muted num', `#${f.seq} · ${f.at.slice(11)}`), el('span', 'dev', frameDevice(f)),
              el('span', 'muted mono small', `@ ${f.site_endpoint}`));
  if (f.function) head.append(el('span', '', t(f.fc_key)));
  head.append(el('span', 'muted num', `${f.ms} ms`));
  box.replaceChildren(head);
  box.append(...(f.request ? byteLine(t('frames.sent'), 'sent', f.request, false)
                           : missingLine(t('frames.sent'), 'sent', f.status)));
  if (f.request) box.append(...(f.response ? byteLine(t('frames.received'), 'recv', f.response, bad)
                                           : missingLine(t('frames.received'), 'recv', f.status)));
  for (const v of f.values) {
    const key = v.kind ? `frame.explain_${v.kind}`
      : v.hex.split(' ').length === 2 ? 'frame.explain_16' : 'frame.explain_32';
    const text = t(key, { hex: '\u0000', raw: v.raw, scale: v.scale, name: tr(v.label) || v.key,
      value: fmtFrame(v.value), unit: v.unit, type: v.type, order: v.byte_order });
    const [before, after] = text.split('\u0000');               // tách để đặt byte vào thẻ code monospace
    const line = el('div', 'explain', before);
    line.append(el('code', '', v.hex), after);
    box.append(line);
  }
  box.append(el('div', 'legend', t('frames.hint')));
}

function renderFrames() {
  const body = $('#frames');
  $('#n-frames').textContent = FR.items.length || '';
  if (!FR.items.length) {
    const row = el('tr', 'empty-row'), td = el('td', '', t('frames.empty'));
    td.colSpan = 7; row.append(td); body.replaceChildren(row);
  } else {
    body.replaceChildren(...FR.items.slice().reverse().map(frameRow));
  }
  renderDetail();
}

// opts: { devices() -> [{name, label}], deviceName(name), pointName(key) }
function initFrames(opts) {
  FR.opts = opts;
  $('#f-device').onchange = restartFrames;
  $('#f-function').onchange = restartFrames;
  $('#f-errors').onchange = restartFrames;
  $('#f-pause').onclick = () => {
    FR.paused = !FR.paused;
    const b = $('#f-pause'), label = b.querySelector('span');
    label.dataset.i18n = FR.paused ? 'frames.resume' : 'frames.pause';
    label.textContent = t(label.dataset.i18n);
    b.querySelector('svg.icon')?.replaceWith(icon(FR.paused ? 'play' : 'pause'));
    b.classList.toggle('on', FR.paused);
    $('#f-paused').hidden = !FR.paused;
    if (!FR.paused) pollFrames().catch(() => {});
  };
  $('#f-clear').onclick = async () => {
    await fetch('/api/frames', { method: 'DELETE' });
    restartFrames();
  };
}
