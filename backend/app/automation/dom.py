"""Scripts evaluated inside the page (Playwright `evaluate`).

EXTRACT_FIELDS describes every fillable control under a root element and tags
it with a `data-ajh` handle. Labels come from, in order: aria-labelledby,
aria-label, <label> (for= or wrapping), <legend>, the text just before the
control since the previous control ("nearby text"), placeholder and title.
Radio/checkbox inputs sharing a name, role="radiogroup" widgets and pairs of
Yes/No buttons become one choice field. Hidden helper inputs, honeypots and
controls without any name or label (which a form would not submit) are left out.
"""

EXTRACT_FIELDS = r"""
(root) => {
  root = root || document.body;
  const ATTR = 'data-ajh';
  const doc = root.ownerDocument || document;
  let seq = Number(doc.documentElement.getAttribute('data-ajh-seq') || 0);
  const handleOf = (el) => {
    if (!el.hasAttribute(ATTR)) el.setAttribute(ATTR, 'f' + (++seq));
    return el.getAttribute(ATTR);
  };
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const SKIP_TEXT = 'script,style,noscript,template,select,option,[role=listbox],[role=option],button,[aria-hidden=true]';
  const textOf = (node) => {
    if (!node) return '';
    const parts = [];
    const walker = doc.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const t = walker.currentNode;
      if (t.parentElement && t.parentElement.closest(SKIP_TEXT) && !node.matches?.(SKIP_TEXT)) continue;
      parts.push(t.nodeValue);
    }
    return clean(parts.join(' '));
  };
  const shown = (el) => {
    if (!el.isConnected) return false;
    if (el.checkVisibility) return el.checkVisibility({checkOpacity: false, checkVisibilityCSS: true});
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden';
  };
  const CONTROL = 'input,select,textarea,[role=combobox],[role=radiogroup],[role=checkbox],[contenteditable=true]';
  const isControl = (n) => n.nodeType === 1 && n.matches(CONTROL);

  // Text between the previous control and this one, climbing until found.
  const nearbyText = (el, members) => {
    let node = el.parentElement;
    for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) {
      if (node === root.parentElement || node.tagName === 'FORM' && depth > 0 && node !== root) break;
      let buf = [];
      const walker = doc.createTreeWalker(node, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
      let reached = false;
      while (walker.nextNode()) {
        const n = walker.currentNode;
        if (n === el || members.includes(n)) { reached = true; break; }
        if (n.nodeType === 1) {
          if (isControl(n) && !members.includes(n) && n.type !== 'hidden') buf = [];
          continue;
        }
        const p = n.parentElement;
        if (!p || p.closest(SKIP_TEXT)) continue;
        if (members.some(m => m.labels && [...m.labels].some(l => l.contains(n)))) continue;
        const t = clean(n.nodeValue);
        if (t) buf.push(t);
      }
      const text = clean(buf.join(' '));
      if (reached && text && text.length <= 600) return text;
      if (text.length > 600) return text.slice(-600);
    }
    return '';
  };
  const errorNear = (el) => {
    const ids = (el.getAttribute('aria-describedby') || '') + ' ' + (el.getAttribute('aria-errormessage') || '');
    const texts = ids.split(/\s+/).filter(Boolean).map(id => doc.getElementById(id))
      .filter(n => n && shown(n) && /error|invalid|required/i.test((n.className || '') + ' ' + n.id + ' ' + n.textContent))
      .map(n => clean(n.textContent));
    let box = el.parentElement;
    for (let i = 0; box && i < 3 && !texts.length; i++, box = box.parentElement) {
      if (box.querySelectorAll(CONTROL).length > 3) break;
      for (const n of box.querySelectorAll('[role=alert],[class*=error],[class*=Error],[id*=error]')) {
        if (shown(n) && clean(n.textContent) && !n.contains(el)) texts.push(clean(n.textContent));
      }
    }
    return [...new Set(texts)].join(' ').slice(0, 300);
  };
  const labelsOf = (el, members) => {
    const out = [];
    const by = el.getAttribute('aria-labelledby');
    if (by) out.push(by.split(/\s+/).map(id => textOf(doc.getElementById(id))).join(' '));
    if (el.getAttribute('aria-label')) out.push(el.getAttribute('aria-label'));
    if (el.labels) for (const l of el.labels) out.push(textOf(l));
    const fs = el.closest('fieldset');
    if (fs && root.contains(fs)) { const lg = fs.querySelector('legend'); if (lg) out.push(textOf(lg)); }
    out.push(nearbyText(el, members || [el]));
    if (el.placeholder) out.push(el.placeholder);
    if (el.title) out.push(el.title);
    return out.map(clean).filter(Boolean);
  };
  const groupLabels = (members, container) => {
    const out = [];
    if (container) {
      const by = container.getAttribute('aria-labelledby');
      if (by) out.push(by.split(/\s+/).map(id => textOf(doc.getElementById(id))).join(' '));
      if (container.getAttribute('aria-label')) out.push(container.getAttribute('aria-label'));
    }
    const fs = members[0].closest('fieldset');
    if (fs && members.every(m => fs.contains(m))) { const lg = fs.querySelector('legend'); if (lg) out.push(textOf(lg)); }
    out.push(nearbyText(members[0], members));
    return out.map(clean).filter(Boolean);
  };
  const optionLabel = (el) => {
    const parts = [];
    if (el.labels) for (const l of el.labels) parts.push(textOf(l));
    if (!parts.length && el.getAttribute('aria-label')) parts.push(el.getAttribute('aria-label'));
    if (!parts.length) parts.push(clean(el.textContent || el.value));
    return clean(parts.join(' '));
  };
  // Required: the attribute, ARIA, or a label styled as required (an asterisk drawn by CSS).
  const requiredLabel = (lbl) => !!lbl && /(^|[^a-z])required/i.test(String(lbl.className || ''));
  const requiredOf = (el) => el.required || el.getAttribute('aria-required') === 'true'
    || (el.labels && [...el.labels].some(requiredLabel));
  const keyOf = (el, label) => el.getAttribute('name') || el.id || ('label:' + label.toLowerCase().slice(0, 80));

  const fields = [];
  const seen = new Set();
  const all = [...root.querySelectorAll(CONTROL)];

  // Pairs of Yes/No buttons (custom boolean widgets, e.g. Ashby).
  for (const btn of root.querySelectorAll('button')) {
    if (seen.has(btn) || !/^yes$/i.test(clean(btn.textContent))) continue;
    const box = btn.parentElement;
    const buttons = [...box.querySelectorAll(':scope > button, :scope > * > button')];
    const no = buttons.find(b => /^no$/i.test(clean(b.textContent)));
    if (!no || buttons.length !== 2) continue;
    buttons.forEach(b => seen.add(b));
    const hidden = box.parentElement && [...box.parentElement.querySelectorAll('input[type=checkbox]')];
    let field = box;
    for (let i = 0; field && i < 3 && !field.querySelector('label'); i++) field = field.parentElement;
    const styledRequired = !!field && requiredLabel(field.querySelector('label'));
    (hidden || []).forEach(h => seen.add(h));
    const labels = groupLabels([btn, no], null);
    const pressed = buttons.find(b => b.getAttribute('aria-pressed') === 'true' || /selected|active/i.test(b.className));
    const name = hidden && hidden[0] && hidden[0].getAttribute('name');
    fields.push({
      key: name || ('label:' + (labels[0] || '').toLowerCase().slice(0, 80)), handle: handleOf(btn),
      kind: 'yes_no', labels, hints: name ? [name] : [],
      required: styledRequired || (hidden || []).some(requiredOf) || /[*✱]\s*$/.test(labels[0] || ''),
      options: buttons.map(b => ({label: clean(b.textContent), value: clean(b.textContent), handle: handleOf(b)})),
      value: pressed ? clean(pressed.textContent) : '', filled: !!pressed, visible: shown(btn),
      invalid: false, error: errorNear(box),
    });
  }

  for (const el of all) {
    if (seen.has(el) || el.disabled) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const role = el.getAttribute('role');
    if (tag === 'input' && ['hidden', 'submit', 'button', 'reset', 'image', 'search'].includes(type)) continue;

    // ---- groups: radio / checkbox by name, role=radiogroup
    if (role === 'radiogroup') {
      const items = [...el.querySelectorAll('[role=radio]')];
      items.forEach(i => seen.add(i)); seen.add(el);
      if (!items.length) continue;
      const labels = groupLabels(items, el);
      const checked = items.find(i => i.getAttribute('aria-checked') === 'true');
      fields.push({key: el.id || ('label:' + (labels[0] || '').toLowerCase().slice(0, 80)), handle: handleOf(el),
        kind: 'radio', labels, hints: [], required: requiredOf(el),
        options: items.map(i => ({label: optionLabel(i), value: optionLabel(i), handle: handleOf(i)})),
        value: checked ? optionLabel(checked) : '', filled: !!checked, visible: shown(el), invalid: el.getAttribute('aria-invalid') === 'true', error: errorNear(el)});
      continue;
    }
    if (tag === 'input' && (type === 'radio' || type === 'checkbox')) {
      const name = el.getAttribute('name');
      const members = name ? all.filter(o => o.tagName === 'INPUT' && o.type === type && o.getAttribute('name') === name) : [el];
      members.forEach(m => seen.add(m));
      const visibleMember = members.some(m => shown(m) || (m.labels && [...m.labels].some(shown)));
      if (!visibleMember) continue;
      if (type === 'checkbox' && members.length === 1) {
        const own = optionLabel(el);
        const labels = [own, ...groupLabels(members, null)].filter(Boolean);
        fields.push({key: keyOf(el, labels[0] || ''), handle: handleOf(el), kind: 'checkbox', labels, hints: [],
          required: requiredOf(el), options: [], value: el.checked ? 'checked' : '', filled: el.checked,
          visible: true, invalid: el.getAttribute('aria-invalid') === 'true', error: errorNear(el)});
        continue;
      }
      const labels = groupLabels(members, el.closest('[role=group],[role=radiogroup]'));
      const checked = members.filter(m => m.checked);
      fields.push({key: name || keyOf(el, labels[0] || ''), handle: handleOf(el),
        kind: type === 'radio' ? 'radio' : 'checkbox_group', labels, hints: [],
        required: members.some(requiredOf), multiple: type === 'checkbox',
        options: members.map(m => ({label: optionLabel(m), value: m.value, handle: handleOf(m)})),
        value: checked.map(optionLabel).join(', '), filled: checked.length > 0, visible: true,
        invalid: members.some(m => m.getAttribute('aria-invalid') === 'true'), error: errorNear(el)});
      continue;
    }

    // ---- single controls
    seen.add(el);
    const isFile = tag === 'input' && type === 'file';
    const isCombo = role === 'combobox' || el.getAttribute('aria-autocomplete') === 'list';
    const labels = labelsOf(el);
    const named = el.getAttribute('name') || el.id || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || (el.labels && el.labels.length);
    if (!named && !isCombo) continue;
    if (!isFile && !shown(el)) continue;
    let kind;
    if (isFile) kind = 'file';
    else if (tag === 'select') kind = 'select';
    else if (isCombo) kind = 'combobox';
    else if (tag === 'textarea' || el.getAttribute('contenteditable') === 'true') kind = 'textarea';
    else if (['email', 'tel', 'url', 'number', 'date'].includes(type)) kind = type;
    else kind = 'text';
    let value = '', filled = false, options = [];
    if (kind === 'file') {
      value = [...(el.files || [])].map(f => f.name).join(', ');
      filled = (el.files || []).length > 0;
    } else if (kind === 'select') {
      options = [...el.options].filter(o => !o.disabled && o.value !== '' && clean(o.textContent))
        .map(o => ({label: clean(o.textContent), value: o.value, handle: ''}));
      const sel = el.selectedOptions[0];
      value = sel && sel.value !== '' ? clean(sel.textContent) : '';
      filled = !!value;
    } else if (kind === 'combobox') {
      let box = el.parentElement; let shownValue = '';
      for (let i = 0; box && i < 4 && !shownValue; i++, box = box.parentElement) {
        const v = box.querySelector('[class*=single-value],[class*=singleValue],[class*=multi-value__label],[class*=multiValue]');
        if (v) shownValue = clean(v.textContent);
      }
      value = clean(el.value) || shownValue;
      filled = !!value;
    } else {
      value = el.getAttribute('contenteditable') === 'true' ? clean(el.textContent) : el.value;
      filled = clean(value) !== '';
    }
    fields.push({
      key: keyOf(el, labels[0] || ''), handle: handleOf(el), kind, labels,
      hints: [el.getAttribute('name') || '', el.id || ''].filter(Boolean),
      required: requiredOf(el), options, multiple: !!el.multiple,
      accept: el.getAttribute('accept') || '', autocomplete: el.getAttribute('autocomplete') || '',
      value, filled, visible: shown(el),
      invalid: el.getAttribute('aria-invalid') === 'true' || (filled && el.willValidate && !el.checkValidity()),
      error: errorNear(el) || (filled && el.willValidate && !el.checkValidity() ? el.validationMessage : ''),
    });
  }
  doc.documentElement.setAttribute('data-ajh-seq', String(seq));
  return fields;
}
"""

# Visible error messages anywhere in the form (after a submit attempt or a
# client-side validation pass).
PAGE_ERRORS = r"""
(root) => {
  root = root || document.body;
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const out = [];
  // Alerts anywhere on the page (a banner above the form), error styling inside the form.
  const nodes = [...document.querySelectorAll('[role=alert],[aria-live=assertive]'),
                 ...root.querySelectorAll('[class*=error],[class*=Error]')];
  for (const n of nodes) {
    if (n.closest('[aria-hidden=true]')) continue;
    if (n.checkVisibility ? !n.checkVisibility({checkVisibilityCSS: true}) : getComputedStyle(n).display === 'none') continue;
    if (n.querySelector('input,select,textarea')) continue;  // a wrapper, not a message
    const t = clean(n.textContent);
    if (t && t.length < 300 && !out.includes(t)) out.push(t);
  }
  return out.slice(0, 20);
}
"""

# Is a CAPTCHA challenge showing (not just the invisible badge)?
CAPTCHA_VISIBLE = r"""
() => {
  const frames = [...document.querySelectorAll('iframe')];
  return frames.some(f => {
    const src = f.src || '';
    if (!/recaptcha|hcaptcha|turnstile|challenges\.cloudflare/.test(src)) return false;
    if (/anchor|invisible|size=invisible/.test(src) && !/bframe|challenge/.test(src)) return false;
    const r = f.getBoundingClientRect();
    const s = getComputedStyle(f);
    return r.width > 50 && r.height > 50 && s.visibility !== 'hidden' && s.display !== 'none';
  });
}
"""
