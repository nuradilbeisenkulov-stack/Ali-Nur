'use strict';

const state = { tickets: [], taxonomy: { categories: [], priorities: [] }, selected: null, view: 'all', search: '', category: '', priority: '', editing: false, busy: false };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const languageNames = { ru: 'Русский', kk: 'Қазақша', uz: 'Oʻzbekcha', en: 'English', es: 'Español', pt: 'Português', lat: 'Латиница · язык не определён', und: 'Язык не определён' };
let toastTimer;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'icon'); svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`); svg.append(use); return svg;
}
function append(parent, ...children) { children.filter(Boolean).forEach(child => parent.append(child)); return parent; }
function toast(message, error = false) {
  const node = $('#toast'); node.textContent = message; node.classList.toggle('error', error); node.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { node.hidden = true; }, error ? 8000 : 4500);
}
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
  if (!response.ok) {
    let detail = `Ошибка сервиса (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map(item => `${(item.loc || []).slice(1).join('.')}: ${item.msg}`).join('; ');
    } catch (_) { /* Use safe fallback when the response is not JSON. */ }
    throw new Error(detail);
  }
  return response.json();
}
function isDone(item) { return ['sent', 'done', 'completed'].includes(item.status); }
function requiresHuman(item) { return item.status === 'escalated' || !!item.result?.needs_human; }
function categoryTitle(code) { return state.taxonomy.categories.find(item => item.code === code)?.title || code || 'Категория не определена'; }
function priorityTitle(code) { return state.taxonomy.priorities.find(item => item.code === code)?.title || code || '—'; }
function playerText(item) {
  return (item.ticket?.messages || []).filter(message => message.role !== 'admin').map(message => message.text || '').join(' ');
}
function ticketName(item) { return item.ticket?.ticket_id || item.id || 'Без номера'; }
function shortId(item) { const value = String(ticketName(item)); return value.length > 16 ? `${value.slice(0, 13)}…` : value; }
function formatDate(value) {
  if (!value) return 'Время не указано';
  const date = new Date(value); if (Number.isNaN(date.getTime())) return 'Время не указано';
  return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
}
function badge(code) { return el('span', `priority-chip priority-${/^p[0-3]$/.test(code) ? code : 'p3'}`, `${(code || '—').toUpperCase()} · ${priorityTitle(code)}`); }
function itemStatus(item) {
  if (isDone(item)) return { name: 'Завершено локально', css: 'done', icon: 'check' };
  if (requiresHuman(item)) return { name: item.status === 'escalated' ? 'Передано человеку' : 'Нужен человек', css: '', icon: 'user' };
  return { name: 'На проверке', css: 'ready', icon: 'clock' };
}
function filteredTickets() {
  const query = state.search.toLocaleLowerCase();
  return state.tickets.filter(item => {
    if (state.view === 'human' && (!requiresHuman(item) || isDone(item))) return false;
    if (state.view === 'done' && !isDone(item)) return false;
    if (state.category && item.result?.category !== state.category) return false;
    if (state.priority && item.result?.priority !== state.priority) return false;
    if (query) {
      const haystack = [ticketName(item), playerText(item), item.ticket?.reported_nick, categoryTitle(item.result?.category)].filter(Boolean).join(' ').toLocaleLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}
function updateStats() {
  const total = state.tickets.length;
  const human = state.tickets.filter(item => requiresHuman(item) && !isDone(item)).length;
  const done = state.tickets.filter(isDone).length;
  const urgent = state.tickets.filter(item => ['p0', 'p1'].includes(item.result?.priority) && !isDone(item)).length;
  [['#stat-total', total], ['#stat-human', human], ['#stat-done', done], ['#stat-urgent', urgent], ['#nav-total', total], ['#nav-human', human], ['#nav-done', done]].forEach(([id, value]) => { $(id).textContent = value; });
}
function renderList() {
  const list = $('#ticket-list'); list.replaceChildren();
  const items = filteredTickets(); $('#visible-count').textContent = items.length;
  $('#view-title').textContent = ({ all: 'Вся очередь', human: 'Нужен человек', done: 'Завершённые' })[state.view];
  if (!items.length) {
    const empty = el('div', 'empty-list');
    append(empty, icon('search'), el('strong', '', state.tickets.length ? 'Ничего не найдено' : 'Очередь пока пуста'), el('span', '', state.tickets.length ? 'Измените поисковый запрос или фильтры.' : 'Добавьте первое обращение, чтобы начать.')); list.append(empty);
    return;
  }
  items.forEach(item => {
    const result = item.result || {};
    const card = el('button', `ticket-card${String(item.id) === String(state.selected) ? ' selected' : ''}`); card.type = 'button';
    card.setAttribute('aria-pressed', String(String(item.id) === String(state.selected)));
    card.setAttribute('aria-label', `Обращение ${shortId(item)}. ${categoryTitle(result.category)}. ${priorityTitle(result.priority)}`);
    append(card, append(el('div', 'ticket-topline'), el('span', 'ticket-number', `# ${shortId(item)}`), badge(result.priority)), el('strong', 'ticket-title', categoryTitle(result.category)), el('span', 'ticket-snippet', playerText(item) || 'В обращении нет текста игрока.'));
    const meta = append(el('span', 'ticket-meta'), el('span', 'lang-chip', result.lang || 'und'), el('span', 'dot', '·'), el('span', '', item.is_demo ? 'Демо' : formatDate(item.ticket?.created_at)));
    const status = itemStatus(item);
    append(card, append(el('div', 'ticket-bottomline'), meta, append(el('span', `ticket-status ${status.css}`), icon(status.icon), el('span', '', status.name))));
    card.addEventListener('click', () => selectTicket(item.id)); list.append(card);
  });
}
function selectTicket(id) {
  if (state.busy) return;
  if (state.editing && !window.confirm('Несохранённые изменения черновика будут потеряны. Перейти к другому обращению?')) return;
  state.selected = id; state.editing = false; renderList(); renderDetail();
}
function sectionLabel(title, aside) { return append(el('h3', 'section-label', title), aside ? el('span', 'label-aside', aside) : null); }
function renderMessages(item) {
  const section = el('section', 'messages-section'); section.setAttribute('aria-label', 'Исходные сообщения');
  section.append(sectionLabel('Исходное обращение', 'Заявления участников'));
  const messages = item.ticket?.messages || [];
  if (!messages.length) section.append(el('p', 'empty-rules', 'Сообщения не приложены.'));
  messages.forEach(message => {
    const roles = { player: ['Игрок', 'Заявитель', 'И'], reported_player: ['Другой игрок', 'Объяснение участника', 'Д'], admin: ['Администратор', 'Исторический ответ · не использован', 'А'] };
    const [author, role, initials] = roles[message.role] || ['Участник', String(message.role || 'Неизвестная роль'), 'У'];
    const content = el('div', 'message-content');
    append(content, append(el('div', 'message-header'), el('strong', 'message-author', author), el('span', 'message-role', role)), el('p', 'message-text', message.text || '(нет текста)'));
    const attachmentCount = Array.isArray(message.attachments) ? message.attachments.length : typeof message.attachments === 'number' ? message.attachments : message.attachments ? 1 : 0;
    if (attachmentCount) append(content, append(el('p', 'evidence-note'), icon('file'), el('span', '', `Вложений: ${attachmentCount}. Содержимое не анализировалось.`)));
    section.append(append(el('div', `message-block${message.role === 'admin' ? ' admin' : ''}`), el('span', 'avatar', initials), content));
  });
  if (item.ticket?.images_count !== undefined && item.ticket?.images_count !== null) section.append(append(el('p', 'evidence-note'), icon('file'), el('span', '', `В обращении указано вложений: ${item.ticket.images_count}. Их наличие не подтверждает нарушение.`)));
  return section;
}
function renderAnalysis(item) {
  const result = item.result || {}; const extracted = result.extracted || {}; const section = el('section', 'analysis-block');
  const title = append(el('div', 'analysis-heading'), sectionLabel('Разбор обращения'), append(el('span', 'copilot-badge'), icon('grid'), el('span', '', 'COPILOT')));
  section.append(title);
  const facts = el('div', 'facts-grid');
  [['Указанный ник', extracted.nickname || 'Не указан'], ['Вложения', extracted.has_evidence ? 'Есть · не проверены' : 'Не найдены в данных'], ['Сервер', extracted.server || 'Не указан'], ['Язык', languageNames[result.lang] || result.lang || 'Не определён']].forEach(([label, value]) => facts.append(append(el('div', 'fact'), el('span', 'fact-label', label), el('span', 'fact-value', value))));
  section.append(facts);
  const confidence = Number.isFinite(result.confidence) ? Math.max(0, Math.min(1, result.confidence)) : 0;
  const low = confidence < 0.7; const track = el('div', 'confidence-track'); const fill = el('div', `confidence-fill${low ? ' low' : ''}`); fill.style.width = `${confidence * 100}%`; track.append(fill);
  track.setAttribute('role', 'meter'); track.setAttribute('aria-label', 'Уверенность локальной эвристики'); track.setAttribute('aria-valuemin', '0'); track.setAttribute('aria-valuemax', '100'); track.setAttribute('aria-valuenow', String(Math.round(confidence * 100)));
  section.append(append(el('div', 'confidence-row'), el('span', '', 'Уверенность'), track, el('strong', 'confidence-number', `${Math.round(confidence * 100)}%`), append(el('span', `confidence-caption${low ? ' low' : ''}`), icon(low ? 'alert' : 'shield'), el('span', '', low ? 'Низкая · нужна проверка' : 'Оценка эвристики'))));
  const reasons = Array.isArray(result.reasons) ? result.reasons : [];
  if (reasons.length || requiresHuman(item) || result.is_spam_or_duplicate) {
    const box = el('div', 'reason-box');
    box.append(append(el('div', 'reason-heading'), icon('alert'), el('span', '', requiresHuman(item) ? 'Почему нужна проверка человеком' : 'Что учесть при проверке')));
    const list = el('ul'); reasons.forEach(reason => list.append(el('li', '', reason)));
    if (result.is_spam_or_duplicate) list.append(el('li', '', 'Отмечено как спам или возможный дубль. Решение о закрытии принимает администратор.'));
    if (item.status === 'escalated') list.append(el('li', '', 'Администратор вручную передал обращение на дополнительное рассмотрение.'));
    if (!list.children.length) list.append(el('li', '', 'Для этого обращения требуется решение администратора.'));
    box.append(list); section.append(box);
  }
  return section;
}
function renderRules(item) {
  const section = el('section', 'rules-section'); const cited = Array.isArray(item.result?.draft_reply?.cited) ? item.result.draft_reply.cited : [];
  section.append(sectionLabel('Найденные пункты правил', `${cited.length} ${cited.length === 1 ? 'пункт' : 'пунктов'}`));
  if (!cited.length) section.append(el('div', 'empty-rules', 'Подтверждённый релевантный пункт не найден. Черновик не содержит ссылки на правило.'));
  cited.forEach(rule => {
    const value = typeof rule === 'object' && rule !== null ? rule : { ref: String(rule), text: '', section: '' };
    const details = el('details', 'rule-card'); const summary = el('summary');
    append(summary, append(el('span', 'rule-icon'), icon('book')), el('span', 'rule-ref', `Пункт ${value.ref}`), el('span', 'rule-section', value.section || 'База правил'), el('span', 'rule-toggle', '+'));
    append(details, summary, el('p', 'rule-text', value.text || 'Текст пункта не передан сервисом.')); section.append(details);
  });
  if (cited.length) section.append(el('p', 'rules-disclaimer', 'Пункты найдены по тексту заявления. Их применимость и факт нарушения проверяет администратор.'));
  return section;
}
function renderDraft(item) {
  const result = item.result || {}; const section = el('section', 'draft-section');
  append(section, append(el('div', 'draft-header'), sectionLabel('Черновик ответа'), el('span', 'draft-lang', languageNames[result.draft_reply?.lang] || result.draft_reply?.lang || 'Не определён')));
  const aiUsed = (result.reasons || []).some(reason => reason.startsWith('Контекстный черновик'));
  section.append(el('p', 'rules-disclaimer', aiUsed ? 'ИИ · ответ по контексту (модель указана в причинах)' : 'Резервный режим · шаблон, проверьте причины ниже'));
  const regenerate = el('button', 'text-button', 'Проанализировать заново с ИИ'); regenerate.type = 'button'; regenerate.disabled = state.busy || isDone(item) || state.editing;
  regenerate.addEventListener('click', async () => {
    if (state.busy) return; state.busy = true; regenerate.disabled = true; regenerate.textContent = 'ИИ анализирует обращение…';
    try { const updated = await api(`/api/tickets/${encodeURIComponent(item.id)}/reanalyze`, {method:'POST'}); const i = state.tickets.findIndex(t => t.id === item.id); state.tickets[i] = updated; toast('Разбор обновлён. Проверьте черновик и причины.'); } catch (error) { toast(error.message, true); } finally { state.busy = false; renderAll(); }
  }); section.append(regenerate);
  const box = el('div', 'draft-box'); const textarea = el('textarea'); textarea.id = 'draft-text'; textarea.value = item.draft_text ?? result.draft_reply?.text ?? ''; textarea.readOnly = !state.editing; textarea.setAttribute('aria-label', 'Черновик ответа игроку'); textarea.rows = Math.max(4, Math.min(9, Math.ceil(textarea.value.length / 80))); textarea.maxLength = 20000;
  const editButton = append(el('button', 'text-button'), icon('edit'), el('span', '', state.editing ? 'Сохранить правки' : 'Редактировать')); editButton.type = 'button'; editButton.id = 'edit-draft'; editButton.disabled = state.busy;
  editButton.addEventListener('click', async () => {
    if (!state.editing) {
      state.editing = true; textarea.readOnly = false; box.classList.add('editing'); editButton.lastChild.textContent = 'Сохранить правки'; textarea.focus();
    } else if (!textarea.value.trim()) { toast('Черновик не может быть пустым.', true); textarea.focus(); }
    else await mutateTicket(item.id, 'edit', textarea.value);
  });
  const footer = append(el('div', 'draft-footer'), append(el('span', 'draft-notice'), icon('shield'), el('span', '', 'Проверьте текст перед действием')), editButton);
  append(box, textarea, footer); box.classList.toggle('editing', state.editing); section.append(box);
  const escalate = append(el('button', 'button escalate'), icon('user'), el('span', '', item.status === 'escalated' ? 'Уже эскалировано' : 'Эскалировать')); escalate.type = 'button'; escalate.id = 'escalate-ticket'; escalate.disabled = state.busy || item.status === 'escalated' || isDone(item);
  escalate.addEventListener('click', async () => {
    if (state.editing && !window.confirm('Эскалация сохранит текущий черновик локально. Продолжить?')) return;
    await mutateTicket(item.id, 'escalate', state.editing ? textarea.value : undefined);
  });
  const send = append(el('button', 'button button-primary'), icon('send'), el('span', '', isDone(item) ? 'Завершено локально' : 'Отправить · локально')); send.type = 'button'; send.id = 'send-draft'; send.disabled = state.busy || isDone(item); send.title = 'Только изменить статус в этом MVP. Сообщение не отправляется в Grand Mobile.';
  send.addEventListener('click', async () => {
    if (!textarea.value.trim()) { toast('Добавьте текст ответа перед завершением.', true); textarea.focus(); return; }
    await mutateTicket(item.id, 'send', textarea.value);
  });
  append(section, append(el('div', 'draft-actions'), escalate, send), el('p', 'send-disclaimer', '«Отправить» меняет только статус внутри MVP.'));
  if (isDone(item)) section.append(append(el('div', 'local-sent-notice'), icon('check'), el('span', '', 'Ответ сохранён и обращение завершено локально. В Grand Mobile ничего не отправлялось.')));
  return section;
}
function renderDetail() {
  const panel = $('#ticket-detail'); const item = state.tickets.find(ticket => String(ticket.id) === String(state.selected)); panel.replaceChildren();
  if (!item) {
    panel.append(append(el('div', 'detail-placeholder'), append(el('span', 'placeholder-icon'), icon('inbox')), el('h2', '', 'Всё начинается с обращения'), el('p', '', 'Выберите обращение в очереди или создайте новое.'))); return;
  }
  const result = item.result || {}; const header = el('header', 'detail-header');
  append(header, append(el('div', 'detail-topline'), el('span', 'detail-id', `ОБРАЩЕНИЕ # ${ticketName(item)}`), el('span', 'detail-demo', item.is_demo ? 'Синтетический пример' : 'Локальное обращение')), el('h2', '', categoryTitle(result.category)));
  const status = itemStatus(item);
  append(header, append(el('div', 'detail-chips'), badge(result.priority), append(el('span', 'type-chip'), icon('file'), el('span', '', item.ticket?.kind === 'complaint' ? 'Жалоба' : 'Репорт')), append(el('span', `status-chip ${status.css}`), icon(status.icon), el('span', '', status.name))));
  const body = el('div', 'detail-body'); append(body, renderMessages(item), renderAnalysis(item), renderRules(item), renderDraft(item)); append(panel, header, body);
}
function renderAll() { updateStats(); renderList(); renderDetail(); }
async function mutateTicket(id, action, draftText) {
  if (state.busy) return false;
  state.busy = true; $$('.draft-actions button, #edit-draft').forEach(button => { button.disabled = true; });
  try {
    const body = { action }; if (draftText !== undefined) body.draft_text = draftText;
    const updated = await api(`/api/tickets/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) });
    const index = state.tickets.findIndex(item => String(item.id) === String(id)); if (index !== -1) state.tickets[index] = updated;
    state.editing = false; state.busy = false; renderAll();
    toast(({ edit: 'Правки сохранены локально как обратная связь.', send: 'Завершено локально. В Grand Mobile ничего не отправлено.', escalate: 'Обращение передано на рассмотрение человеку.' })[action]);
    return true;
  } catch (error) {
    state.busy = false;
    $$('.draft-actions button, #edit-draft').forEach(button => { button.disabled = false; });
    toast(error.message || 'Не удалось сохранить действие.', true); return false;
  }
}
function populateFilters() {
  const categories = $('#category-filter'); categories.replaceChildren(new Option('Все категории', ''));
  state.taxonomy.categories.forEach(category => categories.append(new Option(category.title, category.code)));
  const priorities = $('#priority-filter'); priorities.replaceChildren(new Option('Приоритет', ''));
  state.taxonomy.priorities.forEach(priority => priorities.append(new Option(`${priority.code.toUpperCase()} · ${priority.title}`, priority.code)));
}
async function load(initial = false) {
  if (state.busy) return;
  const refresh = $('#refresh'); refresh.disabled = true;
  try {
    const [meta, tickets] = await Promise.all([api('/api/meta'), api('/api/tickets')]);
    state.taxonomy = meta.taxonomy || { categories: [], priorities: [] }; state.tickets = Array.isArray(tickets) ? tickets : tickets.items || [];
    if (initial) populateFilters();
    if (!state.tickets.some(item => String(item.id) === String(state.selected))) state.selected = state.tickets[0]?.id ?? null;
    $('#rules-meta').textContent = meta.mode === 'demo' ? 'Демо · официальные правила не подключены' : `${meta.rules_count ?? '—'} пунктов в базе правил`;
    $('#connection-dot').classList.add('online'); $('#connection-dot').classList.remove('offline'); $('#connection-label').textContent = 'Сервис работает локально';
    state.editing = false; renderAll(); if (!initial) toast('Очередь обновлена.');
  } catch (error) {
    $('#connection-dot').classList.remove('online'); $('#connection-dot').classList.add('offline'); $('#connection-label').textContent = 'Сервис недоступен';
    if (initial) { const empty = el('div', 'empty-list'); append(empty, icon('alert'), el('strong', '', 'Не удалось загрузить очередь'), el('span', '', 'Проверьте, запущен ли сервис, и нажмите обновление.')); $('#ticket-list').replaceChildren(empty); }
    toast(error.message || 'Не удалось подключиться к сервису.', true);
  } finally { refresh.disabled = false; }
}
function updateView() {
  $$('.nav-item').forEach(button => { const selected = button.dataset.view === state.view; button.classList.toggle('active', selected); if (selected) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); });
  renderList();
}
$$('.nav-item').forEach(button => button.addEventListener('click', () => { state.view = button.dataset.view; updateView(); }));
$('#search').addEventListener('input', event => { state.search = event.target.value; renderList(); });
$('#category-filter').addEventListener('change', event => { state.category = event.target.value; renderList(); });
$('#priority-filter').addEventListener('change', event => { state.priority = event.target.value; renderList(); });
$('#refresh').addEventListener('click', () => { if (state.editing && !window.confirm('Обновление сбросит несохранённый черновик. Продолжить?')) return; load(); });
const modal = $('#ticket-modal');
$('#new-ticket').addEventListener('click', () => { if (state.editing && !window.confirm('При создании нового обращения несохранённые правки текущего черновика будут потеряны. Продолжить?')) return; $('#form-error').hidden = true; modal.showModal(); setTimeout(() => $('[name="text"]', modal).focus(), 50); });
$('#close-modal').addEventListener('click', () => modal.close());
modal.addEventListener('click', event => { if (event.target === modal) { const rect = modal.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) modal.close(); } });
$('#ticket-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget; if (!form.reportValidity()) return;
  const values = new FormData(form); const text = String(values.get('text') || '').trim();
  if (!text) { $('#form-error').textContent = 'Введите сообщение игрока.'; $('#form-error').hidden = false; return; }
  const ticket = { kind: values.get('kind'), messages: [{ role: 'player', text }] };
  ['lang', 'reported_nick', 'reporter_hash'].forEach(key => { const value = String(values.get(key) || '').trim(); if (value) ticket[key] = value; });
  if (values.get('images_count') !== '') ticket.images_count = Number(values.get('images_count'));
  const createdAt = values.get('created_at'); if (createdAt) ticket.created_at = new Date(String(createdAt)).toISOString();
  const button = $('#create-ticket'); button.disabled = true; $('#form-error').hidden = true;
  try {
    const item = await api('/api/tickets', { method: 'POST', body: JSON.stringify(ticket) }); state.tickets.unshift(item); state.selected = item.id; state.editing = false;
    state.view = 'all'; state.search = ''; state.category = ''; state.priority = ''; $('#search').value = ''; $('#category-filter').value = ''; $('#priority-filter').value = '';
    modal.close(); form.reset(); updateView(); renderAll(); toast('Обращение разобрано и добавлено в очередь.');
  } catch (error) { $('#form-error').textContent = error.message || 'Не удалось создать обращение.'; $('#form-error').hidden = false; }
  finally { button.disabled = false; }
});
window.addEventListener('beforeunload', event => { if (state.editing) { event.preventDefault(); event.returnValue = ''; } });
load(true);
