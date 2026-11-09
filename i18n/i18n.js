// SONG NGỮ vi / ja cho trang web — dùng chung cho trang collector và trang điều khiển simulator.
// Tải từ điển /i18n.json (sinh từ i18n/messages.yml), chọn ngôn ngữ, dịch chữ cố định và lỗi server.
//
//   <span data-i18n="khóa">            chữ cố định, dịch khi tải trang và khi đổi ngôn ngữ
//   data-i18n-title / -placeholder      dịch thuộc tính title / placeholder
//   t('khóa', { tên: giá trị })          dịch trong mã JS
//   tr({ vi, ja })                       nhãn song ngữ từ Point Map
//   errText(json)                       lỗi server: dịch theo code + params, không có code thì dùng error
//
// Chọn ngôn ngữ: ?lang=vi|ja trên URL > lựa chọn đã lưu > ngôn ngữ trình duyệt (ja nếu tiếng Nhật, còn lại vi).
const I18N = { lang: 'vi', dict: {}, onChange: null };
const LANGS = ['vi', 'ja'];

function pickLang() {
  const q = new URLSearchParams(location.search).get('lang');
  if (LANGS.includes(q)) return q;
  try {
    const saved = localStorage.getItem('lang');
    if (LANGS.includes(saved)) return saved;
  } catch (e) { /* trình duyệt chặn lưu trữ: bỏ qua */ }
  return (navigator.language || '').toLowerCase().startsWith('ja') ? 'ja' : 'vi';
}

function showParam(v) {
  return Array.isArray(v) ? v.join(', ') : String(v);
}

function t(key, params = {}) {
  const text = (I18N.dict[I18N.lang] || {})[key] ?? (I18N.dict.vi || {})[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (m, k) => (k in params ? showParam(params[k]) : m));
}

function tr(obj) {
  return obj ? (obj[I18N.lang] || obj.vi || '') : '';
}

function errText(j) {
  if (!j) return '';
  return j.code ? t(j.code, j.params || {}) : (j.error || '');
}

function locale() {
  return I18N.lang === 'ja' ? 'ja-JP' : 'vi-VN';
}

function applyStatic() {
  document.documentElement.lang = I18N.lang;
  document.querySelectorAll('[data-i18n]').forEach(e => { e.textContent = t(e.dataset.i18n); });
  document.querySelectorAll('[data-i18n-title]').forEach(e => { e.title = t(e.dataset.i18nTitle); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(e => { e.placeholder = t(e.dataset.i18nPlaceholder); });
  document.querySelectorAll('.langs button').forEach(b => b.classList.toggle('on', b.dataset.lang === I18N.lang));
}

function setLang(lang) {
  I18N.lang = lang;
  try { localStorage.setItem('lang', lang); } catch (e) { /* không lưu được thì chỉ áp cho lần này */ }
  applyStatic();
  if (I18N.onChange) I18N.onChange();
}

async function initI18n(onChange) {
  I18N.onChange = onChange;
  I18N.lang = pickLang();
  try {
    I18N.dict = await (await fetch('/i18n.json', { cache: 'no-store' })).json();
  } catch (e) { /* không tải được từ điển: t() trả về khóa, trang vẫn chạy */ }
  document.querySelectorAll('.langs button').forEach(b => { b.onclick = () => setLang(b.dataset.lang); });
  applyStatic();
}
