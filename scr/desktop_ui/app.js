'use strict';
(() => {
  const root = document.getElementById('desktop');
  const byId = id => document.getElementById(id);
  const panel = byId('result-panel');
  const layer = byId('dialog-layer');
  const keys = ['pressure', 'vna', 'boundary', 'top10', 'delta', 'rh', 'economics'];
  const titles = {pressure:'Перепады давления', vna:'ВНА', boundary:'Параметры на границах периодов', top10:'ТОП-10 ВНА', delta:'Деградация', rh:'Расходная характеристика', economics:'Экономика'};
  const icons = {
    activity:'<path d="M2 12h4l3-8 6 16 3-8h4"/>',
    'file-sheet':'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8M12 13v8"/>',
    'file-text':'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>',
    folder:'<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v2M3 7h17l-3 13H4a2 2 0 0 1-2-2z"/>',
    play:'<path d="m8 5 11 7-11 7z"/>',
    terminal:'<path d="m4 6 6 6-6 6M13 18h7"/>',
    chevron:'<path d="m6 9 6 6 6-6"/>',
    flag:'<path d="M4 22V3c5-4 10 4 16 0v12c-6 4-11-4-16 0"/>',
    chart:'<path d="M3 3v18h18M7 15l4-5 4 3 6-8"/>',
    close:'<path d="m6 6 12 12M6 18 18 6"/>',
  };
  function fillIcons(scope = root) {
    scope.querySelectorAll('[data-icon]').forEach(node => {
      const shape = icons[node.dataset.icon];
      if (shape) node.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${shape}</svg>`;
    });
  }
  const views = {}, zoom = {}, scrolls = {};
  let backend = null, model = null, selected = 'pressure', dialogPayload = null;
  function initializeSidebarResize() {
    const layout = root.querySelector('.gtu-layout');
    const sidebar = byId('settings-panel');
    const separator = byId('sidebar-resizer');
    const defaults = {width:324, min:280, max:560, workspace:500, divider:8, step:16};
    const storageKey = 'gtu.sidebar.width.v1';
    let preferred = defaults.width;
    try {
      const saved = Number(localStorage.getItem(storageKey));
      if (Number.isFinite(saved) && saved >= defaults.min && saved <= defaults.max) preferred = saved;
    } catch (_error) { /* Сохранение UI-настроек может быть запрещено профилем. */ }
    function maximum() { return Math.max(defaults.min, Math.min(defaults.max, layout.clientWidth - defaults.workspace - defaults.divider)); }
    function applyWidth(width, remember = false) {
      const actual = Math.round(Math.max(defaults.min, Math.min(maximum(), width)));
      layout.style.setProperty('--gtu-sidebar-width', `${actual}px`);
      separator.setAttribute('aria-valuenow', String(actual));
      separator.setAttribute('aria-valuemax', String(maximum()));
      separator.setAttribute('aria-valuetext', `${actual} пикселей`);
      if (remember) {
        preferred = actual;
        try { localStorage.setItem(storageKey, String(preferred)); } catch (_error) {}
      }
    }
    let drag = null;
    separator.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      event.preventDefault();
      drag = {x:event.clientX, width:sidebar.getBoundingClientRect().width, pointer:event.pointerId};
      separator.setPointerCapture(event.pointerId);
      separator.classList.add('dragging');
      document.body.classList.add('gtu-resizing');
    });
    separator.addEventListener('pointermove', event => {
      if (drag && event.pointerId === drag.pointer) applyWidth(drag.width + event.clientX - drag.x);
    });
    function endDrag(event) {
      if (!drag || event.pointerId !== drag.pointer) return;
      applyWidth(sidebar.getBoundingClientRect().width, true);
      if (separator.hasPointerCapture(event.pointerId)) separator.releasePointerCapture(event.pointerId);
      drag = null;
      separator.classList.remove('dragging');
      document.body.classList.remove('gtu-resizing');
    }
    separator.addEventListener('pointerup', endDrag);
    separator.addEventListener('pointercancel', endDrag);
    separator.addEventListener('lostpointercapture', endDrag);
    separator.addEventListener('dblclick', () => applyWidth(defaults.width, true));
    separator.addEventListener('keydown', event => {
      const current = sidebar.getBoundingClientRect().width;
      const width = event.key === 'ArrowLeft' ? current - defaults.step : event.key === 'ArrowRight' ? current + defaults.step : event.key === 'Home' ? defaults.width : event.key === 'End' ? maximum() : null;
      if (width !== null) { event.preventDefault(); applyWidth(width, true); }
    });
    applyWidth(preferred);
    new ResizeObserver(() => applyWidth(preferred)).observe(layout);
  }
  function send(name, data = {}) { if (backend) backend.action(name, JSON.stringify(data)); }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function setOptions(select, values, chosen, placeholder = '') {
    const expected = JSON.stringify([values, placeholder]);
    if (select.dataset.options !== expected) {
      select.replaceChildren();
      if (placeholder) select.append(new Option(placeholder, ''));
      values.forEach(value => select.append(new Option(value, value)));
      select.dataset.options = expected;
    }
    if (select.value !== chosen) select.value = chosen;
  }
  function rememberScroll() {
    const viewport = panel.querySelector('.gtu-view-viewport');
    if (viewport) scrolls[selected] = [viewport.scrollLeft, viewport.scrollTop];
  }
  function emptyState() {
    const fragment = byId('empty-template').content.cloneNode(true);
    const running = model?.running;
    fragment.querySelector('#empty-title').textContent = running ? 'Расчёт выполняется' : model?.file ? 'Всё готово к расчету' : 'Начните с исходных данных';
    fragment.querySelector('#empty-description').textContent = running ? 'Подготавливаем графики и таблицы. Ход расчёта — в журнале ниже.' : model?.file ? 'Нажмите «Расчет» в панели подготовки. Перед вычислением можно проверить и изменить периоды.' : 'Выберите Excel-книгу и ТЭЦ в панели подготовки. Здесь появятся графики и таблицы расчёта.';
    panel.replaceChildren(fragment);
    fillIcons(panel);
  }
  function makeTable(data) {
    if (!data.rows.length) return element('p', 'gtu-caption', 'Нет данных для отображения');
    const wrap = element('div', 'gtu-table-wrap');
    const table = element('table', 'gtu-data-table');
    table.setAttribute('aria-label', titles[selected]);
    const row = table.createTHead().insertRow();
    data.columns.forEach(name => { const th = element('th', '', name); th.scope = 'col'; row.append(th); });
    const body = table.createTBody();
    data.rows.forEach(values => { const row = body.insertRow(); values.forEach(value => { row.insertCell().textContent = value; }); });
    wrap.append(table);
    return wrap;
  }
  function renderView(keepScroll = true) {
    if (keepScroll) rememberScroll();
    panel.setAttribute('aria-labelledby', `tab-${selected}`);
    root.querySelectorAll('[data-tab]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.tab === selected)));
    const data = views[selected];
    if (!data) { emptyState(); return; }
    const heading = element('div', 'gtu-chart-head');
    const title = element('div');
    title.append(element('h3', '', titles[selected]));
    heading.append(title);
    const viewport = element('div', 'gtu-view-viewport');
    panel.replaceChildren(heading, viewport);
    if (data.type === 'figure') {
      title.append(element('p', '', 'Колесо мыши — масштаб · 100 % — по ширине'));
      const controls = element('div', 'gtu-row');
      const reset = element('button', 'gtu-action', '100 %');
      reset.type = 'button'; reset.setAttribute('aria-label', 'Вернуть масштаб по ширине');
      const label = element('span', 'gtu-caption');
      controls.append(label, reset); heading.append(controls);
      const stage = element('div', 'gtu-figure-stage');
      const image = element('img', 'gtu-figure');
      image.alt = titles[selected]; image.draggable = false;
      stage.append(image); viewport.append(stage);
      const key = selected;
      zoom[key] = zoom[key] || 1;
      function resize() { stage.style.width = `${viewport.clientWidth * zoom[key]}px`; label.textContent = `${Math.round(zoom[key] * 100)} %`; }
      reset.onclick = () => { zoom[key] = 1; resize(); viewport.scrollTo(0, 0); };
      viewport.addEventListener('wheel', event => {
        event.preventDefault();
        const bounds = viewport.getBoundingClientRect();
        const x = event.clientX - bounds.left, y = event.clientY - bounds.top;
        const old = zoom[key];
        zoom[key] = Math.min(2.5, Math.max(.5, old * (event.deltaY < 0 ? 1.15 : 1 / 1.15)));
        const contentX = (viewport.scrollLeft + x) / old;
        const contentY = (viewport.scrollTop + y) / old;
        resize(); viewport.scrollTo(contentX * zoom[key] - x, contentY * zoom[key] - y);
      }, {passive:false});
      image.onload = () => { resize(); const saved = scrolls[key] || [0, 0]; viewport.scrollTo(...saved); };
      image.src = data.src;
      viewport._resizeFigure = resize;
    } else if (data.type === 'table') {
      title.append(element('p', '', `${data.rows.length} строк`));
      viewport.append(makeTable(data));
    } else {
      data.tables.forEach(data => {
        const section = element('section', 'gtu-table-section');
        section.append(element('h4', '', data.title), makeTable(data));
        viewport.append(section);
      });
      if (!data.tables.length) viewport.append(element('p', 'gtu-caption', 'Нет таблиц ТОП-10 для отображения'));
    }
    if (data.type !== 'figure') requestAnimationFrame(() => viewport.scrollTo(...(scrolls[selected] || [0, 0])));
  }
  function applyState(next) {
    model = next;
    root.querySelectorAll('[data-control]').forEach(node => {
      const control = model.controls[node.dataset.control];
      node.disabled = control?.state === 'disabled';
    });
    const values = model.values;
    setOptions(byId('station'), model.stations, values.station_var, 'Выберите ТЭЦ');
    setOptions(byId('sheet'), model.controls.raw_sheet_combo.values || [], values.selected_raw_sheet);
    const inputFields = {gas:'gas_tariff_var', electricity:'electricity_tariff_var', cost:'electricity_cost_var'};
    Object.entries(inputFields).forEach(([id, key]) => { const input = byId(id); if (document.activeElement !== input) input.value = values[key]; input.disabled = model.tariffsDisabled; });
    root.querySelectorAll('input[name="mode"]').forEach(input => { input.checked = input.value === values.calculation_mode; input.disabled = model.modeDisabled; });
    byId('import-controls').hidden = values.calculation_mode !== 'import';
    byId('filename').textContent = model.filename || 'Файл не выбран';
    byId('filename').title = model.file || '';
    byId('choose-label').textContent = model.file ? 'Изменить файл' : 'Выбрать Excel-файл';
    byId('station-hint').textContent = model.controls.station_hint.text || '';
    byId('raw-label').textContent = model.controls.raw_label.text || '';
    byId('run-label').textContent = model.controls.run_button.text || 'Расчет';
    byId('events-label').textContent = model.controls.events_button.text || 'События графика (0)';
    byId('status').textContent = model.controls.status_label.text || '';
    byId('status-dot').className = `gtu-dot ${model.running || model.exporting ? 'busy' : model.hasResult ? '' : 'waiting'}`;
    byId('progress').hidden = !model.controls.progress.active;
    byId('journal-status').textContent = model.running ? 'Выполняется' : model.exporting ? 'Экспорт' : model.hasResult ? 'Завершён' : 'Ожидание данных';
    byId('workspace-title').textContent = model.file && model.station ? `${model.station}${model.unit ? ` · ГТ-${model.unit}` : ''}` : 'Рабочее пространство';
    byId('workspace-subtitle').textContent = model.filename || 'Графики, таблицы и отчёты';
    if (selected !== model.tab) { rememberScroll(); selected = model.tab; renderView(false); }
    else if (!views[selected]) emptyState();
  }
  function closeDialogLocally() {
    layer.hidden = true; layer.replaceChildren(); layer.classList.remove('periods');
    root.querySelector('.gtu-settings').inert = false;
    root.querySelector('main').inert = false;
    dialogPayload = null;
  }
  function showDialog(payload) {
    if (!payload) { closeDialogLocally(); return; }
    dialogPayload = payload;
    const periods = payload.kind === 'periods';
    layer.classList.toggle('periods', periods);
    root.querySelector('.gtu-settings').inert = !periods;
    root.querySelector('main').inert = !periods;
    const dialog = element('section', 'gtu-dialog');
    dialog.dataset.kind = payload.kind;
    dialog.role = 'dialog'; dialog.setAttribute('aria-modal', String(!periods));
    dialog.setAttribute('aria-label', payload.title);
    const header = element('div', 'gtu-dialog-head');
    header.append(element('h3', '', payload.title));
    if (periods) {
      const collapse = element('button', 'gtu-action', 'Свернуть'); collapse.type = 'button';
      collapse.onclick = () => { const collapsed = dialog.classList.toggle('collapsed'); collapse.textContent = collapsed ? 'Развернуть' : 'Свернуть'; };
      header.append(collapse);
      header.onpointerdown = event => {
        if (event.target.closest('button')) return;
        const bounds = dialog.getBoundingClientRect(), container = layer.getBoundingClientRect();
        const offsetX = event.clientX - bounds.left, offsetY = event.clientY - bounds.top;
        dialog.style.position = 'absolute'; dialog.style.left = `${bounds.left - container.left}px`; dialog.style.top = `${bounds.top - container.top}px`;
        header.setPointerCapture(event.pointerId);
        header.onpointermove = e => { if (!header.hasPointerCapture(e.pointerId)) return; dialog.style.left = `${Math.max(0, Math.min(container.width - dialog.offsetWidth, e.clientX - container.left - offsetX))}px`; dialog.style.top = `${Math.max(0, Math.min(container.height - dialog.offsetHeight, e.clientY - container.top - offsetY))}px`; };
        header.onpointerup = e => header.releasePointerCapture(e.pointerId);
      };
    }
    const body = element('div', 'gtu-dialog-body');
    const description = element('p');
    description.textContent = periods ? 'Проверьте автоматическую разбивку. Одна строка — один период: дата начала; дата конца. График остаётся доступен.' : payload.kind === 'events' ? 'Каждая строка: дата; подпись события. Например: 01.05.2026; Замена ВЛО. Можно указать время.' : payload.kind === 'gasPassport' ? 'Значения относятся к указанным ТЭЦ и ГТ. Допустимы точка и запятая. Состав — молярные доли 0..1; пустые компоненты не сохраняются.' : 'Проверьте каналы, колонки листа «Данные» и коэффициенты перевода единиц. Колонку можно ввести вручную по букве.';
    body.append(description);
    if (payload.kind === 'corrections') {
      description.textContent = `63 коэффициента выбранной ГТ. Точка, запятая и запись 1,23E-5 допустимы. Можно вставить диапазон значений из Excel начиная с выбранного поля. Версия: ${payload.revision}. Источник: ${payload.source}`;
    }
    let editor = null;
    const mappingInputs = [];
    const gasInputs = [];
    const coefficientInputs = [];
    if (payload.kind === 'mapping') {
      const choices = element('datalist'); choices.id = 'target-options';
      payload.choices.forEach(value => choices.append(new Option(value, value)));
      const table = element('table', 'gtu-mapping-table');
      const row = table.createTHead().insertRow();
      ['Канал выгрузки', 'Колонка «Данные»', 'Коэффициент'].forEach(title => row.append(element('th', '', title)));
      const tbody = table.createTBody();
      payload.rows.forEach((data, index) => {
        const row = tbody.insertRow(); row.insertCell().textContent = data.source;
        const target = element('input', 'gtu-field'); target.value = data.target; target.setAttribute('list', 'target-options'); target.setAttribute('aria-label', `Колонка для ${data.source}`);
        const factor = element('input', 'gtu-field'); factor.value = data.factor; factor.inputMode = 'decimal'; factor.setAttribute('aria-label', `Коэффициент для ${data.source}`);
        row.insertCell().append(target); row.insertCell().append(factor);
        mappingInputs.push({target, factor});
      });
      body.append(choices, table);
    } else if (payload.kind === 'gasPassport') {
      if (payload.warning) body.append(element('p', 'gtu-caption', payload.warning));
      const table = element('table', 'gtu-mapping-table');
      const head = table.createTHead().insertRow();
      ['Параметр', 'Значение', 'Единицы'].forEach(title => head.append(element('th', '', title)));
      const rows = table.createTBody();
      payload.fields.forEach(field => {
        const row = rows.insertRow(); row.insertCell().textContent = field.label;
        const input = element('input', 'gtu-field'); input.value = field.value;
        input.inputMode = 'decimal'; input.setAttribute('aria-label', field.label);
        input.dataset.gasKey = field.key;
        row.insertCell().append(input); row.insertCell().textContent = field.unit;
        gasInputs.push({key:field.key, input});
      });
      body.append(table);
    } else if (payload.kind === 'corrections') {
      const pasteStatus = element('p', 'gtu-caption'); pasteStatus.setAttribute('aria-live','polite');
      body.append(pasteStatus);
      payload.groups.forEach((group, index) => {
        const section = element('details', 'gtu-coefficient-group'); section.open = index === 0;
        section.append(element('summary','',`${group.title} (${group.fields.length})`));
        section.append(element('p','gtu-caption',group.formula));
        const table = element('table','gtu-mapping-table');
        const head = table.createTHead().insertRow();
        ['Коэффициент','Значение','Подсказка'].forEach(text => head.append(element('th','',text)));
        const rows = table.createTBody();
        group.fields.forEach(field => {
          const row = rows.insertRow(); row.insertCell().textContent = field.label;
          const input = element('input','gtu-field'); input.value = field.value; input.inputMode = 'decimal';
          input.dataset.coefficientKey = field.key; input.setAttribute('aria-label',`${group.title}: ${field.label}`);
          row.insertCell().append(input); row.insertCell().textContent = field.hint;
          const position = coefficientInputs.length; coefficientInputs.push({key:field.key,input});
          input.addEventListener('paste', event => {
            const text = event.clipboardData.getData('text');
            if (!/[\t\r\n]/.test(text)) return;
            event.preventDefault();
            const values = text.split(/\r\n|\r|\n|\t/); while (values.length && !values[values.length-1].trim()) values.pop();
            if (values.length > coefficientInputs.length-position) {
              pasteStatus.textContent = 'В диапазоне больше значений, чем оставшихся полей. Вставка отменена.'; return;
            }
            values.forEach((value,i) => { coefficientInputs[position+i].input.value = value.trim(); });
            pasteStatus.textContent = `Вставлено значений: ${values.length}. Проверьте порядок коэффициентов перед сохранением.`;
          });
        });
        section.append(table); body.append(section);
      });
    } else {
      editor = element('textarea'); editor.value = payload.text; editor.spellcheck = false; editor.setAttribute('aria-label', payload.kind === 'periods' ? 'Периоды расчёта' : 'События на графике'); body.append(editor);
    }
    const actions = element('div', 'gtu-dialog-actions');
    if (payload.kind === 'events') {
      const clear = element('button', 'gtu-action', 'Очистить'); clear.type = 'button'; clear.style.marginRight = 'auto'; clear.onclick = () => { editor.value = ''; editor.focus(); }; actions.append(clear);
    }
    const cancel = element('button', 'gtu-action', periods ? 'Автоматические периоды' : 'Отмена'); cancel.type = 'button';
    cancel.onclick = () => send('dialog', {action: periods ? 'auto' : 'cancel'});
    const accept = element('button', 'gtu-action gtu-primary', periods ? 'Применить периоды' : ['gasPassport','corrections'].includes(payload.kind) ? 'Сохранить' : 'Применить'); accept.type = 'button';
    accept.onclick = () => send('dialog', {action: periods ? 'manual' : 'accept', text: editor?.value || '', rows: mappingInputs.map(({target, factor}) => ({target:target.value, factor:factor.value})), values:Object.fromEntries([...gasInputs,...coefficientInputs].map(({key, input}) => [key, input.value]))});
    actions.append(cancel, accept); dialog.append(header, body, actions); layer.replaceChildren(dialog); layer.hidden = false;
    requestAnimationFrame(() => (editor || dialog.querySelector('input') || accept).focus());
    dialog.onkeydown = event => {
      if (event.key === 'Escape') { event.preventDefault(); cancel.click(); }
      if (event.ctrlKey && event.key === 'Enter') { event.preventDefault(); accept.click(); }
      if (!periods && event.key === 'Tab') {
        const controls = [...dialog.querySelectorAll('input, textarea, button')];
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
  }
  root.addEventListener('click', event => {
    if (event.target.closest('#dialog-layer')) return;
    const tab = event.target.closest('[data-tab]');
    if (tab) send('tab', {key:tab.dataset.tab});
    const button = event.target.closest('[data-action]');
    if (button && !button.disabled) send(button.dataset.action);
  });
  root.addEventListener('change', event => {
    if (event.target.matches('input[name="mode"]')) send('value', {key:'mode', value:event.target.value});
    if (event.target.matches('select[data-field]')) send('value', {key:event.target.dataset.field, value:event.target.value});
  });
  root.addEventListener('input', event => { if (event.target.matches('input[data-field]')) send('value', {key:event.target.dataset.field, value:event.target.value}); });
  root.querySelector('[role="tablist"]').addEventListener('keydown', event => {
    const index = keys.indexOf(selected);
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (step) { event.preventDefault(); const key = keys[(index + step + keys.length) % keys.length]; byId(`tab-${key}`).focus(); send('tab', {key}); }
  });
  document.addEventListener('keydown', event => {
    if (event.ctrlKey && event.key === 'Tab' && !dialogPayload) { event.preventDefault(); send('tab', {key:keys[(keys.indexOf(selected) + (event.shiftKey ? keys.length - 1 : 1)) % keys.length]}); }
  });
  new ResizeObserver(() => panel.querySelector('.gtu-view-viewport')?._resizeFigure?.()).observe(panel);
  initializeSidebarResize(); fillIcons(); emptyState();
  new QWebChannel(qt.webChannelTransport, channel => {
    backend = channel.objects.backend;
    backend.state_changed.connect(json => applyState(JSON.parse(json)));
    backend.view_changed.connect(json => {
      const event = JSON.parse(json);
      if (event.clear) { Object.keys(views).forEach(key => delete views[key]); Object.keys(scrolls).forEach(key => delete scrolls[key]); renderView(false); }
      else { views[event.key] = event.view; zoom[event.key] = 1; if (event.key === selected) renderView(); }
    });
    backend.log_changed.connect(json => { const data = JSON.parse(json), log = byId('log'); if ('replace' in data) log.textContent = data.replace; else log.textContent += data.append; log.scrollTop = log.scrollHeight; });
    backend.dialog_changed.connect(json => showDialog(JSON.parse(json)));
    backend.connect_ui();
  });
})();
