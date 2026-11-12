/* A viewport-bounded list. Reopening always shows every option, not the current value as a query. */
window.GtuChoiceField = (() => {
  let active = null, serial = 0;
  const enhanced = new WeakMap();
  function close() { if (active) active(); }
  function create({root, choices, value = '', label, editable = false}) {
    const wrapper = document.createElement('div'); wrapper.className = 'gtu-choice';
    const input = document.createElement('input'); input.className = 'gtu-field';
    input.value = value; input.readOnly = !editable; input.autocomplete = 'off';
    input.setAttribute('aria-label', label); input.setAttribute('role', 'combobox');
    input.setAttribute('aria-haspopup', 'listbox'); input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-autocomplete', editable ? 'list' : 'none');
    const button = document.createElement('button'); button.type = 'button'; button.tabIndex = -1;
    button.className = 'gtu-choice-toggle'; button.textContent = '⌄'; button.setAttribute('aria-label', `Открыть список: ${label}`);
    wrapper.append(input, button); wrapper.input = input;
    let popup = null, filtered = [], index = -1;
    const id = `gtu-options-${++serial}`; input.setAttribute('aria-controls', id);
    function shutdown() {
      if (!popup) return;
      popup.remove(); popup = null; input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      document.removeEventListener('pointerdown', outside, true);
      document.removeEventListener('scroll', position, true); window.removeEventListener('resize', position);
      if (active === shutdown) active = null;
    }
    function outside(event) { if (!wrapper.contains(event.target) && !popup?.contains(event.target)) shutdown(); }
    function position(event) {
      if (!popup || (event?.target instanceof Node && popup.contains(event.target))) return;
      const rect = wrapper.getBoundingClientRect(), viewport = {width:window.innerWidth, height:window.innerHeight};
      const body = wrapper.closest('.gtu-dialog-body'), clip = body?.getBoundingClientRect();
      if (!wrapper.isConnected || rect.bottom <= 0 || rect.top >= viewport.height ||
          (clip && (rect.bottom <= clip.top || rect.top >= clip.bottom))) { shutdown(); return; }
      const below = viewport.height - rect.bottom - 12, above = rect.top - 12;
      const upward = below < 220 && above > below;
      const height = Math.max(24, Math.min(320, upward ? above : below));
      const width = Math.min(Math.max(rect.width, editable ? 330 : 190), viewport.width - 24);
      popup.style.width = `${width}px`; popup.style.maxHeight = `${height}px`;
      popup.style.left = `${Math.max(12, Math.min(rect.left, viewport.width - width - 12))}px`;
      popup.style.top = `${upward ? Math.max(12, rect.top - popup.offsetHeight - 4) : rect.bottom + 4}px`;
      popup.dataset.direction = upward ? 'up' : 'down';
    }
    function highlight(next, scroll = true) {
      if (!popup) return;
      index = next;
      [...popup.querySelectorAll('[role=option]')].forEach((option, i) => option.dataset.active = String(i === index));
      const option = popup.querySelectorAll('[role=option]')[index];
      if (option) { input.setAttribute('aria-activedescendant', option.id); if (scroll) option.scrollIntoView({block:'nearest'}); }
      else input.removeAttribute('aria-activedescendant');
    }
    function choose(i) {
      if (!filtered[i] || filtered[i].disabled) return;
      input.value = filtered[i].value; shutdown(); input.focus();
      input.dispatchEvent(new Event('change', {bubbles:true}));
    }
    function render(query) {
      filtered = choices.map(item => typeof item === 'string' ? {value:item,label:item} : item)
        .filter(item => !query || item.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
      popup.replaceChildren();
      const title = document.createElement('div'); title.className='gtu-choice-title'; title.textContent=label; popup.append(title);
      filtered.forEach((item, i) => {
        const option = document.createElement('div'); option.role = 'option'; option.id = `${id}-${i}`;
        option.textContent = item.label; option.className = 'gtu-choice-option';
        option.setAttribute('aria-selected', String(item.value === input.value));
        option.setAttribute('aria-disabled', String(Boolean(item.disabled)));
        option.title = item.label;
        option.onpointerdown = event => { event.preventDefault(); choose(i); };
        option.onpointermove = () => highlight(i, false); popup.append(option);
      });
      if (!filtered.length) { const empty = document.createElement('div'); empty.className='gtu-choice-empty'; empty.textContent=editable?'Нет совпадений. Можно ввести букву колонки.':'Нет доступных вариантов.'; popup.append(empty); }
      position(); highlight(Math.max(0, filtered.findIndex(item => item.value === input.value)));
    }
    function open(query = '') {
      if (input.disabled) return;
      if (!popup) {
        close(); popup = document.createElement('div'); popup.className = 'gtu-choice-popup'; popup.id = id;
        popup.role = 'listbox'; popup.setAttribute('aria-label', label); (root.querySelector('.gtu-app') || root).append(popup);
        input.setAttribute('aria-expanded', 'true'); active = shutdown;
        document.addEventListener('pointerdown', outside, true);
        document.addEventListener('scroll', position, true); window.addEventListener('resize', position);
      }
      render(query);
    }
    input.onclick = () => { if (editable) {input.select();open();} else if(popup)shutdown();else open(); };
    input.oninput = () => open(input.value.trim());
    input.onblur = () => shutdown();
    button.onpointerdown = event => event.preventDefault();
    button.onclick = () => { input.focus(); if (popup) shutdown(); else open(); };
    input.onkeydown = event => {
      if (event.key === 'Escape') { if (popup) { event.preventDefault(); event.stopPropagation(); shutdown(); } return; }
      if (event.key === 'Tab') { shutdown(); return; }
      if (!popup && !editable && ['Enter',' '].includes(event.key)) {event.preventDefault();open();return;}
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault(); if (!popup) open();
        else highlight(Math.max(0, Math.min(filtered.length-1, index+(event.key==='ArrowDown'?1:-1))));
      } else if (popup && ['Home','End','Enter'].includes(event.key)) {
        event.preventDefault();
        if (event.key === 'Enter') choose(index);
        else highlight(event.key==='Home'?0:filtered.length-1);
      }
    };
    wrapper.setChoices = values => {choices=values;if(popup)render(editable?input.value.trim():'');};
    return wrapper;
  }
  function enhanceSelect(select, {root, label} = {}) {
    let wrapper=enhanced.get(select);
    root=root || document.getElementById('desktop');
    const options=[...select.options].map(option=>({value:option.textContent,label:option.textContent,disabled:option.disabled}));
    const value=select.options[select.selectedIndex]?.textContent || '';
    if(!wrapper) {
      label=label || select.getAttribute('aria-label') || select.labels?.[0]?.textContent.trim() || 'Выберите вариант';
      wrapper=create({root,choices:options,value,label});wrapper.classList.add('gtu-select-choice');
      select.classList.forEach(name=>{if(name!=='gtu-field')wrapper.classList.add(name);});
      wrapper.input.id=`${select.id || `gtu-select-${++serial}`}-choice`;
      [...(select.labels || [])].forEach(item=>item.htmlFor=wrapper.input.id);
      const parent=select.parentNode;if(parent)parent.replaceChild(wrapper,select);
      select.hidden=true;select.setAttribute('aria-hidden','true');select.tabIndex=-1;wrapper.append(select);
      wrapper.input.addEventListener('change',()=>{
        const option=[...select.options].find(item=>item.textContent===wrapper.input.value);
        if(option){select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}));}
      });
      select.addEventListener('change',()=>{wrapper.input.value=select.options[select.selectedIndex]?.textContent || '';});
      enhanced.set(select,wrapper);
    }
    const key=JSON.stringify(options);
    if(wrapper.dataset.options!==key){wrapper.dataset.options=key;wrapper.setChoices(options);}
    wrapper.input.value=value;
    wrapper.input.disabled=wrapper.querySelector('button').disabled=select.disabled;
    wrapper.setAttribute('aria-disabled',String(select.disabled));
    if(select.disabled && wrapper.input.getAttribute('aria-expanded')==='true')close();
    return wrapper;
  }
  function sync(root) {root.querySelectorAll('select.gtu-field').forEach(select=>enhanceSelect(select,{root}));}
  return {create,close,enhanceSelect,sync};
})();
