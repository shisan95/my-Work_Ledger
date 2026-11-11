/* ===================== 工作任务台账 · 主逻辑 ===================== */
const App = (() => {
  const state = {
    fields: [],
    listFields: [],
    editableKeys: [],   // 支持单元格内联编辑的字段
    leadOptions: [],
    options: { owner: [], status: [], priority: [] },
    settings: {},
    page: 1,
    pageSize: 20,
    total: 0,
    pageCount: 1,
    editingId: null,     // 弹窗编辑中的任务 id
    inlineEditing: null, // 正在内联编辑的单元格：{ id, key, el }
    seenReminders: new Set(),
    lastRemindKey: '',
    bound: false,        // 事件是否已绑定（退出再登录不重复绑定）
  };

  const timers = [];   // 轮询定时器，退出登录时统一清理

  /* ---------------- 小工具 ---------------- */
  const $ = (sel) => document.querySelector(sel);

  function escapeHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function toast(title, body = '', type = '') {
    const box = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `<div class="tt">${escapeHtml(title)}</div>${body ? `<div class="tb">${escapeHtml(body)}</div>` : ''}`;
    box.appendChild(el);
    setTimeout(() => {
      el.style.transition = 'opacity .3s, transform .3s';
      el.style.opacity = '0';
      el.style.transform = 'translateY(6px)';
      setTimeout(() => el.remove(), 320);
    }, 3600);
  }

  const PRIORITY_CLASS = {
    '重要且紧急': 'red', '重要不紧急': 'amber', '不重要紧急': 'blue', '不重要不紧急': 'gray',
  };
  const STATUS_CLASS = {
    '未开始': 'gray', '进行中': 'blue', '已完成': 'green', '已搁置': 'amber',
  };

  function priorityTag(v) {
    if (!v) return '<span class="muted">—</span>';
    return `<span class="tag ${PRIORITY_CLASS[v] || 'purple'}">${escapeHtml(v)}</span>`;
  }

  function statusTag(v) {
    const list = Array.isArray(v) ? v : (v ? String(v).split('|').filter(Boolean) : []);
    if (!list.length) return '<span class="muted">—</span>';
    return `<span class="tag-group">${list
      .map((s) => `<span class="tag ${STATUS_CLASS[s] || 'gray'}">${escapeHtml(s)}</span>`)
      .join('')}</span>`;
  }

  // 多值字段（状态）统一按 options 顺序规范化，保证比较与存储稳定
  function normalizeMulti(value, options) {
    const picked = (Array.isArray(value) ? value : String(value || '').split('|'))
      .map((s) => String(s).trim()).filter(Boolean);
    const order = options && options.length ? options : picked;
    return order.filter((o) => picked.includes(o));
  }

  /* ---------------- 筛选参数 ---------------- */
  function filters() {
    return {
      q: $('#f-q').value.trim(),
      status: statusFilterValues(),
      priority: $('#f-priority').value,
      due_from: $('#f-due-from').value,
      due_to: $('#f-due-to').value,
      overdue_only: $('#f-overdue').checked,
      page: state.page,
      page_size: state.pageSize,
    };
  }

  /* ---------------- 列表 ---------------- */
  function renderHead() {
    const cols = state.listFields;
    const ths = [
      '<th class="col-check"><input type="checkbox" id="check-all" title="全选" /></th>',
      ...cols.map((f) => {
        const editable = state.editableKeys.includes(f.key) ? ' title="点击单元格可编辑"' : '';
        return `<th data-key="${f.key}"${editable} style="min-width:${f.width || 110}px">${escapeHtml(f.label)}</th>`;
      }),
      '<th style="width:120px;text-align:right">操作</th>',
    ];
    document.querySelector('#task-table thead').innerHTML = `<tr>${ths.join('')}</tr>`;

    const checkAll = document.getElementById('check-all');
    if (checkAll) {
      checkAll.addEventListener('change', (e) => {
        document.querySelectorAll('.row-check').forEach((c) => { c.checked = e.target.checked; });
      });
    }
  }

  /* ---------------- 单元格 ---------------- */
  // 单元格属性：可编辑字段带 .editable-cell，供点击/双击进入编辑态
  function tdAttrs(field, task, extraClass = '') {
    const cls = [extraClass, state.editableKeys.includes(field.key) ? 'editable-cell' : '']
      .filter(Boolean).join(' ');
    const base = `data-key="${field.key}" data-id="${task.id}"${cls ? ` class="${cls}"` : ''}`;
    return state.editableKeys.includes(field.key) ? `${base} title="点击编辑"` : base;
  }

  function cellHtml(field, task) {
    const key = field.key;
    const value = task[key];
    if (key === 'name') {
      const flags = [];
      if (task.is_overdue) flags.push('<span class="pill red">已逾期</span>');
      if (task.is_due_soon && !task.is_overdue) flags.push('<span class="pill">即将到期</span>');
      return `<td ${tdAttrs(field, task, 'name-cell')}>
        <span class="t-name">${escapeHtml(task.name || '(未命名)')}</span>
        ${flags.length ? `<span class="t-sub">${flags.join('')}</span>` : ''}
      </td>`;
    }
    if (key === 'status') return `<td ${tdAttrs(field, task)}>${statusTag(task.status_list || task.status)}</td>`;
    if (key === 'priority') return `<td ${tdAttrs(field, task)}>${priorityTag(task.priority)}</td>`;
    if (key === 'work_content') {
      if (!value) return `<td ${tdAttrs(field, task, 'remark-cell')}><span class="muted">—</span></td>`;
      return `<td ${tdAttrs(field, task, 'remark-cell')}><div class="clamp2" title="${escapeHtml(value)}">${escapeHtml(value)}</div></td>`;
    }
    if (key === 'due_date') {
      if (!task.due_date) {
        return `<td ${tdAttrs(field, task, 'due-cell')}><span class="muted">—</span></td>`;
      }
      const cls = task.is_overdue ? 'over' : (task.is_due_soon ? 'soon' : '');
      return `<td ${tdAttrs(field, task, `due-cell ${cls}`.trim())}>
        <span class="d-date">${escapeHtml(task.due_display)}</span>
        ${task.delta_text ? `<span class="d-delta">${escapeHtml(task.delta_text)}</span>` : ''}
      </td>`;
    }
    if (key === 'start_date') {
      const inner = task.start_date
        ? `<span class="d-date">${escapeHtml(task.start_display)}</span>`
        : '<span class="muted">—</span>';
      return `<td ${tdAttrs(field, task, 'due-cell')}><span class="d-date">${inner}</span></td>`;
    }
    if (key === 'remark') {
      if (!value) return `<td ${tdAttrs(field, task, 'remark-cell')}><span class="muted">—</span></td>`;
      return `<td ${tdAttrs(field, task, 'remark-cell')}><div class="clamp2" title="${escapeHtml(value)}">${escapeHtml(value)}</div></td>`;
    }
    if (!value) return `<td ${tdAttrs(field, task)}><span class="muted">—</span></td>`;
    return `<td ${tdAttrs(field, task)}>${escapeHtml(value)}</td>`;
  }

  function rowHtml(t) {
    const cls = [t.is_overdue ? 'overdue' : '', t.is_done ? 'done' : ''].filter(Boolean).join(' ');
    return `<tr class="${cls}" data-id="${t.id}">
      <td class="col-check"><input type="checkbox" class="row-check" data-id="${t.id}" /></td>
      ${state.listFields.map((f) => cellHtml(f, t)).join('')}
      <td>
        <div class="row-actions">
          <button data-act="edit" data-id="${t.id}">编辑</button>
          <button data-act="done" data-id="${t.id}" title="标记完成/重开">${t.is_done ? '重开' : '完成'}</button>
          <button class="del" data-act="del" data-id="${t.id}">删除</button>
        </div>
      </td>
    </tr>`;
  }

  function renderRows(items) {
    const tbody = document.querySelector('#task-table tbody');
    const empty = document.getElementById('list-empty');
    const table = document.getElementById('task-table');

    if (!items.length) {
      tbody.innerHTML = '';
      table.classList.add('hidden');
      empty.classList.remove('hidden');
      return;
    }
    table.classList.remove('hidden');
    empty.classList.add('hidden');
    tbody.innerHTML = items.map(rowHtml).join('');
  }

  /* ---------------- 单元格内联编辑 ---------------- */
  function fieldOf(key) {
    return state.listFields.find((f) => f.key === key);
  }

  function taskOf(id) {
    return (state.items || []).find((t) => t.id === id);
  }

  function validateInline(field, value, task) {
    const v = String(value || '');
    if (field.key === 'name') {
      if (!v.trim()) return '任务名称不能为空';
      if (v.trim().length > 200) return '任务名称不能超过 200 个字';
    }
    if (field.key === 'work_content' && v.length > 2000) return '详细工作内容不能超过 2000 个字';
    if (field.key === 'remark' && v.length > 2000) return '备注不能超过 2000 个字';
    if (field.type === 'date' && v) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return '日期格式不正确';
      const other = field.key === 'due_date' ? task.start_date : task.due_date;
      if (other) {
        const left = field.key === 'due_date' ? other.slice(0, 10) : v;
        const right = field.key === 'due_date' ? v : other.slice(0, 10);
        if (left > right) {
          return field.key === 'due_date' ? '结束时间不能早于开始时间' : '开始时间不能晚于结束时间';
        }
      }
    }
    return '';
  }

  function restoreCell(td, task, field) {
    const tpl = document.createElement('template');
    tpl.innerHTML = `<table><tbody><tr>${cellHtml(field, task)}</tr></tbody></table>`;
    const fresh = tpl.content.querySelector('td');
    td.className = fresh.className;
    td.innerHTML = fresh.innerHTML;
    td.removeAttribute('data-editing');
    state.inlineEditing = null;
  }

  function startInlineEdit(td) {
    if (state.inlineEditing || state.editingId) return;
    const id = Number(td.dataset.id);
    const key = td.dataset.key;
    const task = taskOf(id);
    const field = fieldOf(key);
    if (!task || !field) return;

    const original = task[key] == null ? '' : String(task[key]);
    const multi = field.type === 'multiselect';
    let input;
    let read = () => String(input.value == null ? '' : input.value);

    if (multi) {
      // 多选：单元格内展开复选面板，勾选后可继续操作，离开时统一保存
      input = document.createElement('div');
      input.className = 'cell-input cell-multi';
      const picked = normalizeMulti(original, field.options);
      input.innerHTML = (field.options || []).map((o) => `
        <label><input type="checkbox" value="${escapeHtml(o)}"${picked.includes(o) ? ' checked' : ''} />
        <span>${escapeHtml(o)}</span></label>`).join('');
      read = () => Array.from(input.querySelectorAll('input:checked')).map((x) => x.value).join('|');
    } else if (field.type === 'select') {
      input = document.createElement('select');
      input.innerHTML = '<option value="">（清空）</option>' +
        (field.options || []).map((o) => `<option value="${escapeHtml(o)}"${o === original ? ' selected' : ''}>${escapeHtml(o)}</option>`).join('');
      input.className = 'cell-input';
    } else if (field.type === 'date') {
      input = document.createElement('input');
      input.type = 'date';
      input.value = original.slice(0, 10);
      input.className = 'cell-input';
    } else if (field.type === 'textarea') {
      input = document.createElement('textarea');
      input.rows = 2;
      input.value = original;
      if (field.maxlength) input.maxLength = field.maxlength;
      input.className = 'cell-input';
    } else {
      input = document.createElement('input');
      input.type = 'text';
      input.value = original;
      if (field.maxlength) input.maxLength = field.maxlength;
      input.className = 'cell-input';
    }

    td.classList.add('editing');
    td.dataset.editing = '1';
    td.innerHTML = '';
    td.appendChild(input);
    state.inlineEditing = { id, key, el: td, original };

    const focusTarget = multi ? input.querySelector('input') : input;
    if (focusTarget) focusTarget.focus();
    if (!multi && typeof input.select === 'function') input.select();
    if (multi) input.addEventListener('mousedown', (ev) => ev.stopPropagation());

    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      input.removeEventListener('blur', onBlur);
      if (!save) {
        restoreCell(td, task, field);
        toast('已取消', `${field.label}保持原值`, '');
        return;
      }
      await commitInlineEdit(task, field, read(), td);
    };
    const onBlur = () => finish(true);

    if (multi) {
      // 面板内部切换焦点不保存；焦点彻底离开面板才提交
      input.addEventListener('focusout', (ev) => {
        if (input.contains(ev.relatedTarget)) return;
        setTimeout(() => {
          if (!input.contains(document.activeElement)) finish(true);
        }, 140);
      });
      input.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') { ev.preventDefault(); finish(false); }
        else if (ev.key === 'Enter') { ev.preventDefault(); finish(true); }
      });
    } else {
      input.addEventListener('blur', onBlur);
      if (input.tagName === 'SELECT') input.addEventListener('change', () => finish(true));
      input.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') { ev.preventDefault(); finish(false); }
        else if (ev.key === 'Enter') {
          // 文本域：Enter 直接保存，Ctrl/Cmd+Enter 也保存
          ev.preventDefault();
          finish(true);
        }
      });
    }
  }

  async function commitInlineEdit(task, field, rawValue, td) {
    let value = String(rawValue == null ? '' : rawValue).trim();
    if (field.type === 'multiselect') {
      value = normalizeMulti(value, field.options).join('|');
    }
    const oldRaw = task[field.key] == null ? '' : String(task[field.key]);
    const oldCmp = field.type === 'date'
      ? oldRaw.slice(0, 10)
      : (field.type === 'multiselect' ? normalizeMulti(oldRaw, field.options).join('|') : oldRaw.trim());

    const err = validateInline(field, value, task);
    if (err) {
      restoreCell(td, task, field);
      toast('未保存', `${err}，已保留原值`, 'err');
      return;
    }
    if (value === oldCmp) {   // 未修改
      restoreCell(td, task, field);
      return;
    }

    try {
      const updated = await API.updateTask(task.id, { [field.key]: value });
      const idx = (state.items || []).findIndex((t) => t.id === task.id);
      if (idx >= 0) state.items[idx] = updated;

      state.inlineEditing = null;
      if (field.key === 'due_date') {
        // 截止日期影响排序与逾期高亮，整表刷新
        await loadList();
      } else {
        const tr = document.querySelector(`#task-table tbody tr[data-id="${task.id}"]`);
        if (tr) {
          const tpl = document.createElement('template');
          tpl.innerHTML = `<table><tbody>${rowHtml(updated)}</tbody></table>`;
          tr.replaceWith(tpl.content.querySelector('tr'));
        }
      }
      toast('已保存', `${field.label}已更新`, 'ok');
      if (['due_date', 'status', 'start_date'].includes(field.key)) {
        refreshStats();
        checkReminders(false);
      }
      if (['priority', 'status', 'work_content'].includes(field.key)) refreshOptions();
    } catch (e) {
      restoreCell(td, task, field);
      toast('保存失败', `${e.message}，已保留原值`, 'err');
    }
  }

  function renderPager() {
    const pager = document.getElementById('pager');
    if (state.total === 0) { pager.innerHTML = ''; return; }
    const from = (state.page - 1) * state.pageSize + 1;
    const to = Math.min(state.page * state.pageSize, state.total);
    pager.innerHTML = `
      <span>第 ${from}-${to} 条，共 ${state.total} 条</span>
      <button ${state.page <= 1 ? 'disabled' : ''} data-page="${state.page - 1}">上一页</button>
      <span class="cur">${state.page} / ${state.pageCount}</span>
      <button ${state.page >= state.pageCount ? 'disabled' : ''} data-page="${state.page + 1}">下一页</button>
      <select id="page-size">
        ${[10, 20, 50, 100].map((n) => `<option value="${n}" ${n === state.pageSize ? 'selected' : ''}>${n} 条/页</option>`).join('')}
      </select>`;
    pager.querySelectorAll('button[data-page]').forEach((b) => {
      b.addEventListener('click', () => {
        state.page = Number(b.dataset.page);
        loadList();
      });
    });
    const ps = document.getElementById('page-size');
    if (ps) {
      ps.addEventListener('change', () => {
        state.pageSize = Number(ps.value);
        state.page = 1;
        loadList();
      });
    }
  }

  async function loadList() {
    try {
      const data = await API.listTasks(filters());
      state.total = data.total;
      state.pageCount = data.page_count || 1;
      state.page = data.page;
      state.items = data.items;
      state.inlineEditing = null;
      renderRows(data.items);
      renderPager();
      const overdueCount = data.items.filter((t) => t.is_overdue).length;
      document.getElementById('list-summary').innerHTML =
        `共 <b>${data.total}</b> 条任务` + (overdueCount ? ` · 当前页 <b style="color:var(--danger)">${overdueCount}</b> 条逾期` : '');
      document.getElementById('brand-sub').textContent =
        `${data.total} 条任务 · 逾期 ${overdueCount} 条（本页）`;
    } catch (err) {
      toast('加载任务失败', err.message, 'err');
    }
  }

  /* ---------------- 表单 ---------------- */
  function dateTimeInputs(key, value) {
    const date = (value || '').slice(0, 10);
    const time = (value || '').length >= 16 ? value.slice(11, 16) : '';
    const isDue = key === 'due_date';
    const fixedTime = isDue ? '23:59' : '00:00';
    const shown = !time || time === fixedTime ? '' : time;
    return `<div class="dt-row">
      <input type="date" class="f-date" data-key="${key}" value="${date}" />
      <input type="time" class="f-time" data-key="${key}" value="${shown}" title="可选，不填表示只按日期" />
    </div>`;
  }

  function fieldControl(field, task) {
    const key = field.key;
    const value = task ? task[key] : '';
    const label = `<label>${escapeHtml(field.label)}${field.required ? '<span class="req">*</span>' : ''}</label>`;
    let control = '';

    if (field.type === 'multiselect') {
      const picked = normalizeMulti(value, field.options);
      control = `<div class="multi-select" data-key="${key}">
        ${(field.options || []).map((o) => `<label class="ms-item">
          <input type="checkbox" value="${escapeHtml(o)}"${picked.includes(o) ? ' checked' : ''} />
          <span>${escapeHtml(o)}</span>
        </label>`).join('')}
      </div>`;
    } else if (field.type === 'select') {
      const opts = field.options || [];
      control = `<select data-key="${key}">
        <option value="">${escapeHtml(field.placeholder || '请选择')}</option>
        ${opts.map((o) => `<option value="${escapeHtml(o)}" ${o === value ? 'selected' : ''}>${escapeHtml(o)}</option>`).join('')}
      </select>`;
    } else if (field.type === 'date') {
      control = dateTimeInputs(key, value);
    } else if (field.type === 'textarea') {
      control = `<textarea data-key="${key}"${field.maxlength ? ` maxlength="${field.maxlength}"` : ''} placeholder="${escapeHtml(field.placeholder || '')}">${escapeHtml(value || '')}</textarea>`;
    } else {
      control = `<input type="text" data-key="${key}" value="${escapeHtml(value || '')}"${field.maxlength ? ` maxlength="${field.maxlength}"` : ''} placeholder="${escapeHtml(field.placeholder || '')}" />`;
    }
    return `<div class="form-item" data-field="${key}">${label}${control}${field.hint ? `<p class="fhint">${escapeHtml(field.hint)}</p>` : ''}</div>`;
  }

  function buildForm(task) {
    const form = document.getElementById('task-form');
    const core = state.fields.filter((f) => !f.custom);
    const customs = state.fields.filter((f) => f.custom);
    const lead = task && task.remind_lead_minutes != null ? String(task.remind_lead_minutes) : '';

    const html = [
      '<div class="form-grid">',
      ...core.map((f) => {
        const full = ['name', 'remark', 'work_content', 'status'].includes(f.key) ? ' full' : '';
        return `<div class="${full.trim()}">${fieldControl(f, task)}</div>`;
      }),
      '<div class="section-title">提醒设置</div>',
      `<div class="form-item">
        <label>开启到期提醒</label>
        <div class="switch-row">
          <input type="checkbox" class="switch" id="remind-toggle" ${!task || task.remind_enabled ? 'checked' : ''} />
          <span class="hint" style="margin:0">按下方提前量在到期前提醒，逾期任务会持续高亮</span>
        </div>
      </div>`,
      `<div class="form-item">
        <label>提醒提前量</label>
        <select id="lead-select">
          <option value="">跟随全局默认（${escapeHtml(leadText(state.settings.default_lead_minutes))}）</option>
          ${state.leadOptions.map((o) => `<option value="${o.minutes}" ${String(o.minutes) === lead ? 'selected' : ''}>${escapeHtml(o.label)}</option>`).join('')}
        </select>
        <p class="fhint">可单独为这个任务设置提前量</p>
      </div>`,
    ];

    if (customs.length) {
      html.push('<div class="section-title">表格扩展字段</div>');
      customs.forEach((f) => html.push(`<div>${fieldControl(f, task)}</div>`));
    }
    html.push('</div>');
    form.innerHTML = html.join('');

    // 提醒开关联动：关闭时禁用提前量选择
    const toggle = document.getElementById('remind-toggle');
    const leadSel = document.getElementById('lead-select');
    const sync = () => { leadSel.disabled = !toggle.checked; };
    toggle.addEventListener('change', sync);
    sync();
  }

  function leadText(minutes) {
    const opt = state.leadOptions.find((o) => o.minutes === Number(minutes));
    if (opt) return opt.label;
    if (minutes == null) return '提前 1 天';
    return `提前 ${minutes} 分钟`;
  }

  function collectForm() {
    const form = document.getElementById('task-form');
    const payload = {};
    // 多选字段：汇总勾选值（竖线分隔）
    form.querySelectorAll('.multi-select[data-key]').forEach((box) => {
      payload[box.dataset.key] = Array.from(box.querySelectorAll('input:checked'))
        .map((i) => i.value).join('|');
    });
    form.querySelectorAll('[data-key]').forEach((el) => {
      if (el.classList.contains('multi-select') || el.closest('.multi-select')) return;
      if (el.classList.contains('f-time')) return;
      const key = el.dataset.key;
      if (el.classList.contains('f-date')) {
        const timeEl = form.querySelector(`.f-time[data-key="${key}"]`);
        const time = timeEl ? timeEl.value : '';
        payload[key] = el.value ? (time ? `${el.value} ${time}` : el.value) : '';
      } else {
        payload[key] = el.value;
      }
    });
    const toggle = document.getElementById('remind-toggle');
    payload.remind_enabled = !!(toggle && toggle.checked);
    const leadSel = document.getElementById('lead-select');
    payload.remind_lead_minutes = leadSel && leadSel.value !== '' ? Number(leadSel.value) : null;
    return payload;
  }

  async function openTask(id) {
    if (id) {
      try {
        const task = await API.getTask(id);
        state.editingId = id;
        document.getElementById('modal-title').textContent = '编辑任务';
        buildForm(task);
      } catch (err) {
        toast('读取任务失败', err.message, 'err');
        return;
      }
    } else {
      state.editingId = null;
      document.getElementById('modal-title').textContent = '新建任务';
      const draft = { status: '未开始', remind_enabled: true };
      buildForm(draft);
    }
    document.getElementById('modal').classList.remove('hidden');
    const first = document.querySelector('#task-form input[type="text"]');
    if (first) setTimeout(() => first.focus(), 60);
  }

  function closeModal() {
    document.getElementById('modal').classList.add('hidden');
    state.editingId = null;
  }

  async function submitForm() {
    const payload = collectForm();
    if (!payload.name || !payload.name.trim()) {
      toast('无法保存', '任务名称不能为空', 'err');
      const input = document.querySelector('#task-form [data-key="name"]');
      if (input) input.focus();
      return;
    }
    try {
      if (state.editingId) {
        await API.updateTask(state.editingId, payload);
        toast('已保存', '任务已更新', 'ok');
      } else {
        await API.createTask(payload);
        toast('已创建', '新任务已加入台账', 'ok');
      }
      closeModal();
      await loadList();
      await refreshOptions();
      refreshStats();
    } catch (err) {
      toast('保存失败', err.message, 'err');
    }
  }

  async function savePatch(id, patch) {
    try {
      await API.updateTask(id, patch);
      await loadList();
      refreshStats();
    } catch (err) {
      toast('更新失败', err.message, 'err');
    }
  }

  async function removeTask(id) {
    const ok = await UI.confirm({
      title: '删除任务',
      message: '确定删除这条任务吗？',
      hint: '删除后不可恢复，建议先导出表格备份。',
      okText: '删除',
      danger: true,
    });
    if (!ok) return;
    try {
      await API.deleteTask(id);
      toast('已删除', '任务已从台账移除', 'ok');
      await loadList();
      refreshStats();
    } catch (err) {
      toast('删除失败', err.message, 'err');
    }
  }

  /* ---------------- 筛选下拉 ---------------- */
  function fillSelect(sel, values, placeholder, current) {
    const el = typeof sel === 'string' ? document.querySelector(sel) : sel;
    const keep = current !== undefined ? current : el.value;
    el.innerHTML = `<option value="">${placeholder}</option>` +
      values.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
    if (keep && values.includes(keep)) el.value = keep;
  }

  // 完成状态多选筛选：勾选值 / 面板渲染 / 按钮文案
  function statusFilterValues() {
    return Array.from(document.querySelectorAll('#f-status-box input:checked')).map((x) => x.value);
  }

  function updateStatusFilterBtn() {
    const btn = document.getElementById('f-status-btn');
    if (!btn) return;
    const picked = statusFilterValues();
    btn.classList.toggle('has-value', picked.length > 0);
    const text = picked.length ? `状态：${picked.join('、')}` : '全部状态';
    btn.innerHTML = `${escapeHtml(text)} <span class="caret">▾</span>`;
  }

  function renderStatusFilter(values) {
    const box = document.getElementById('f-status-box');
    if (!box) return;
    const picked = new Set(statusFilterValues());
    box.innerHTML = (values || []).map((v) => `
      <label class="ms-item"><input type="checkbox" value="${escapeHtml(v)}"${picked.has(v) ? ' checked' : ''} /><span>${escapeHtml(v)}</span></label>`).join('');
    updateStatusFilterBtn();
  }

  function clearStatusFilter() {
    document.querySelectorAll('#f-status-box input:checked').forEach((x) => { x.checked = false; });
    updateStatusFilterBtn();
    state.page = 1;
    loadList();
  }

  function clearStatusFilterSilently() {
    document.querySelectorAll('#f-status-box input:checked').forEach((x) => { x.checked = false; });
    updateStatusFilterBtn();
  }

  async function refreshOptions() {
    try {
      const opts = await API.options();
      state.options = opts;
      renderStatusFilter(opts.status);
      fillSelect('#f-priority', opts.priority, '全部划分');
    } catch (e) { /* 忽略 */ }
  }

  /* ---------------- 提醒 ---------------- */
  function renderReminders(data) {
    const badge = document.getElementById('remind-badge');
    const total = data.count.total;
    badge.textContent = String(total);
    badge.classList.toggle('hidden', total === 0);

    const body = document.getElementById('drawer-body');
    const groups = [
      { key: 'overdue', title: `已逾期（${data.overdue.length}）`, cls: 'overdue' },
      { key: 'due_soon', title: `即将到期（${data.due_soon.length}）`, cls: 'soon' },
    ];
    const html = groups.map((g) => {
      const list = data[g.key];
      if (!list.length) return '';
      return `<div class="remind-group">
        <h4>${g.title}</h4>
        ${list.map((t) => `<div class="remind-item ${g.cls}">
          <div class="ri-name">${escapeHtml(t.name)}</div>
          <div class="ri-meta">${escapeHtml(t.due_display)} · ${escapeHtml(t.delta_text)}${t.work_content ? ' · ' + escapeHtml(t.work_content.slice(0, 24)) : ''}</div>
          <div class="ri-actions">
            <button data-act="open" data-id="${t.id}">查看</button>
            <button data-act="snooze" data-id="${t.id}">稍后提醒</button>
            <button data-act="done" data-id="${t.id}">标记完成</button>
          </div>
        </div>`).join('')}
      </div>`;
    }).join('');

    body.innerHTML = html || '<p class="muted" style="margin-top:20px">暂无需要处理的事项，一切都在计划内。</p>';

    body.querySelectorAll('button[data-act]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = Number(btn.dataset.id);
        if (btn.dataset.act === 'open') { document.getElementById('drawer').classList.add('hidden'); openTask(id); }
        if (btn.dataset.act === 'snooze') {
          await API.snooze(id, state.settings.snooze_minutes || 30);
          toast('已顺延提醒', `将在 ${state.settings.snooze_minutes || 30} 分钟后再次提醒`, 'ok');
          checkReminders();
        }
        if (btn.dataset.act === 'done') {
          const doneStatus = state.settings.done_status || '已完成';
          const task = [...data.overdue, ...data.due_soon].find((x) => x.id === id);
          const rest = ((task && task.status_list) || []).filter((s) => s !== doneStatus);
          await savePatch(id, { status: [...rest, doneStatus].join('|') });
          toast('已标记完成', '', 'ok');
          checkReminders();
        }
      });
    });
  }

  async function checkReminders(showToastForNew = true) {
    try {
      const data = await API.reminders();
      renderReminders(data);
      const items = [...data.overdue.map((t) => ({ ...t, _k: 'o' })), ...data.due_soon.map((t) => ({ ...t, _k: 's' }))];
      const key = items.map((t) => `${t._k}${t.id}`).join(',');
      if (showToastForNew && key && key !== state.lastRemindKey && state.lastRemindKey !== '') {
        const fresh = items.filter((t) => !state.seenReminders.has(`${t._k}${t.id}`));
        fresh.slice(0, 3).forEach((t) => {
          if (t._k === 'o') toast('任务已逾期', `${t.name}｜${t.delta_text}`, 'err');
          else toast('任务即将到期', `${t.name}｜截止 ${t.due_display}`, 'warn');
        });
      }
      items.forEach((t) => state.seenReminders.add(`${t._k}${t.id}`));
      state.lastRemindKey = key;
    } catch (e) { /* 忽略 */ }
  }

  /* ---------------- 统计 ---------------- */
  async function refreshStats() {
    try {
      const s = await API.stats();
      document.getElementById('stat-cards').innerHTML = [
        { k: '任务总数', v: s.total, cls: '' },
        { k: '已完成', v: s.done, cls: 'ok', sub: `完成率 ${s.done_rate}%` },
        { k: '进行中', v: s.by_status['进行中'] || 0, cls: '' },
        { k: '已逾期', v: s.overdue, cls: 'danger' },
        { k: '7 日内到期', v: s.week, cls: 'warn' },
        { k: '无截止日期', v: s.no_due, cls: '' },
      ].map((c) => `<div class="stat-card ${c.cls}">
        <div class="k">${c.k}</div>
        <div class="v">${c.v}${c.sub ? `<small>${c.sub}</small>` : ''}</div>
      </div>`).join('');

      const bars = (obj, order) => {
        const keys = order ? order.filter((k) => obj[k] != null) : Object.keys(obj);
        if (!keys.length) return '<p class="muted">暂无数据</p>';
        const max = Math.max(...keys.map((k) => obj[k] || 0), 1);
        return keys.map((k) => `<div class="row">
          <span class="lb" title="${escapeHtml(k || '未填写')}">${escapeHtml(k || '未填写')}</span>
          <span class="bar"><i style="width:${((obj[k] || 0) / max) * 100}%"></i></span>
          <span class="num">${obj[k] || 0}</span>
        </div>`).join('');
      };
      document.getElementById('stat-status').innerHTML = bars(s.by_status, ['未开始', '进行中', '已完成', '已搁置', '未填写']);
      document.getElementById('stat-priority').innerHTML = bars(s.by_priority,
        ['重要且紧急', '重要不紧急', '不重要紧急', '不重要不紧急']);
      document.getElementById('stat-work').innerHTML = bars(s.work_content || {}, ['已填写', '未填写']);
    } catch (e) { /* 忽略 */ }
  }

  /* ---------------- 设置 ---------------- */
  function renderSettings() {
    const s = state.settings;
    const leadSel = document.getElementById('s-lead');
    leadSel.innerHTML = state.leadOptions
      .map((o) => `<option value="${o.minutes}" ${Number(s.default_lead_minutes) === o.minutes ? 'selected' : ''}>${escapeHtml(o.label)}</option>`)
      .join('');
    document.getElementById('s-notify').checked = !!s.desktop_notify;
    document.getElementById('s-auto-ics').checked = !!s.auto_export_ics;
    document.getElementById('s-ics-path').value = s.ics_path || '';
    document.getElementById('s-snooze').value = String(s.snooze_minutes || 30);
    document.getElementById('s-poll').value = String(s.poll_seconds || 60);
    API.getSettings().then((d) => {
      const st = d.daemon || {};
      document.getElementById('daemon-status').textContent =
        `提醒服务：${st.running ? '运行中' : '未启动'}${st.last_check ? ` · 上次检查 ${st.last_check}` : ''}`
        + (st.last_error ? ` · 异常：${st.last_error}` : '');
    }).catch(() => {});

    const reg = state.fields;
    document.getElementById('field-table').innerHTML = reg.map((f) => {
      const originCls = f.origin === '系统补充' ? 'sys' : (f.origin === '导入新增' ? 'new' : '');
      const typeName = { text: '文本', textarea: '长文本', select: '下拉', multiselect: '多选', date: '日期时间', switch: '开关', lead: '提前量' }[f.type] || f.type;
      return `<div class="fr">
        <span class="k">${escapeHtml(f.label)}</span>
        <span class="v">${typeName}${f.options ? ' · ' + f.options.map(escapeHtml).join('/') : ''}</span>
        <span class="origin ${originCls}">${escapeHtml(f.origin || '表格列')}</span>
      </div>`;
    }).join('');
  }

  async function saveSettings() {
    const patch = {
      default_lead_minutes: Number(document.getElementById('s-lead').value),
      desktop_notify: document.getElementById('s-notify').checked,
      auto_export_ics: document.getElementById('s-auto-ics').checked,
      ics_path: document.getElementById('s-ics-path').value.trim(),
      snooze_minutes: Number(document.getElementById('s-snooze').value),
      poll_seconds: Number(document.getElementById('s-poll').value),
    };
    try {
      const res = await API.saveSettings(patch);
      state.settings = res.settings;
      toast('设置已保存', '', 'ok');
      renderSettings();
      loadList();
    } catch (err) {
      toast('保存设置失败', err.message, 'err');
    }
  }

  /* ---------------- 导入 ---------------- */
  let pendingFile = null;

  function openImport() {
    pendingFile = null;
    document.getElementById('import-preview').classList.add('hidden');
    document.getElementById('btn-do-import').disabled = true;
    document.getElementById('import-modal').classList.remove('hidden');
  }

  async function handleFile(file) {
    if (!file) return;
    pendingFile = file;
    const pv = document.getElementById('import-preview');
    pv.classList.remove('hidden');
    pv.innerHTML = '<p class="muted">正在解析文件…</p>';
    try {
      const data = await API.importPreview(file);
      const mapHtml = data.mapping.map((m) => {
        const isNew = !!m.custom;
        return `<span class="${isNew ? 'new' : ''}">${escapeHtml(m.header)} → ${escapeHtml(m.label)}${isNew ? '（新增字段）' : ''}</span>`;
      }).join('');
      const sample = (data.sample || []).slice(0, 3);
      const head = data.header;
      pv.innerHTML = `<div class="pv-box">
        <div class="pv-title">${escapeHtml(data.file)} · 共 ${data.total} 行数据</div>
        <div>列映射：</div>
        <div class="map">${mapHtml}</div>
        ${sample.length ? `<table>
          <tr>${head.map((h) => `<th>${escapeHtml(h)}</th>`).join('')}</tr>
          ${sample.map((r) => `<tr>${r.map((c) => `<td>${escapeHtml(c)}</td>`).join('')}</tr>`).join('')}
        </table>` : ''}
      </div>`;
      document.getElementById('btn-do-import').disabled = false;
    } catch (err) {
      pv.innerHTML = `<div class="pv-box" style="color:var(--danger)">解析失败：${escapeHtml(err.message)}</div>`;
      document.getElementById('btn-do-import').disabled = true;
    }
  }

  async function doImport() {
    if (!pendingFile) return;
    const mode = document.getElementById('import-mode').value;
    const btn = document.getElementById('btn-do-import');
    btn.disabled = true;
    btn.textContent = '导入中…';
    try {
      const res = await API.importFile(pendingFile, mode);
      toast('导入完成', res.message, 'ok');
      document.getElementById('import-modal').classList.add('hidden');
      await boot(false);
      loadList();
      refreshStats();
      checkReminders(false);
    } catch (err) {
      toast('导入失败', err.message, 'err');
    } finally {
      btn.disabled = false;
      btn.textContent = '开始导入';
    }
  }

  /* ---------------- 导出 ---------------- */
  function exportUrl(fmt) {
    const f = filters();
    const sp = new URLSearchParams();
    ['q', 'due_from', 'due_to'].forEach((k) => { if (f[k]) sp.append(k, f[k]); });
    ['status', 'priority'].forEach((k) => {
      const v = f[k];
      if (Array.isArray(v)) v.forEach((x) => { if (x) sp.append(k, x); });
      else if (v) sp.append(k, v);
    });
    if (f.overdue_only) sp.append('overdue_only', 'true');
    sp.append('format', fmt);
    return '/api/export?' + sp.toString();
  }

  function download(url) {
    const a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  /* ---------------- 视图切换 ---------------- */
  function switchView(name) {
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.view === name));
    document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${name}`));
    if (name === 'calendar') CalendarView.render();
    if (name === 'stats') refreshStats();
    if (name === 'settings') renderSettings();
  }

  /* ---------------- 事件绑定 ---------------- */
  function bind() {
    document.getElementById('tabs').addEventListener('click', (e) => {
      const tab = e.target.closest('.tab');
      if (tab) switchView(tab.dataset.view);
    });

    document.getElementById('btn-new').addEventListener('click', () => openTask(null));
    document.getElementById('btn-save-task').addEventListener('click', submitForm);
    document.getElementById('task-form').addEventListener('submit', (e) => { e.preventDefault(); submitForm(); });

    document.querySelectorAll('[data-close]').forEach((el) => {
      el.addEventListener('click', () => {
        document.getElementById('modal').classList.add('hidden');
        document.getElementById('import-modal').classList.add('hidden');
        state.editingId = null;
      });
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.getElementById('modal').classList.add('hidden');
        document.getElementById('import-modal').classList.add('hidden');
        document.getElementById('drawer').classList.add('hidden');
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !document.getElementById('modal').classList.contains('hidden')) {
        submitForm();
      }
    });

    // 筛选
    let timer = null;
    document.getElementById('f-q').addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => { state.page = 1; loadList(); }, 260);
    });
    // 完成状态多选筛选面板
    const stWrap = document.getElementById('f-status-wrap');
    const stBtn = document.getElementById('f-status-btn');
    const stPop = document.getElementById('f-status-pop');
    if (stBtn && stPop) {
      stBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        stPop.classList.toggle('hidden');
      });
      stPop.addEventListener('click', (ev) => ev.stopPropagation());
      stPop.addEventListener('change', () => {
        state.page = 1;
        updateStatusFilterBtn();
        loadList();
      });
      document.getElementById('f-status-clear').addEventListener('click', clearStatusFilter);
      document.addEventListener('click', (ev) => {
        if (!stPop.classList.contains('hidden') && stWrap && !stWrap.contains(ev.target)) {
          stPop.classList.add('hidden');
        }
      });
    }
    ['f-priority', 'f-due-from', 'f-due-to', 'f-overdue'].forEach((id) => {
      const el = document.getElementById(id);
      el.addEventListener(el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input', () => {
        state.page = 1;
        loadList();
      });
    });
    document.getElementById('btn-reset').addEventListener('click', () => {
      document.getElementById('f-q').value = '';
      clearStatusFilterSilently();
      ['f-priority', 'f-due-from', 'f-due-to'].forEach((id) => { document.getElementById(id).value = ''; });
      document.getElementById('f-overdue').checked = false;
      state.page = 1;
      loadList();
    });

    // 列表事件委托：行内操作按钮 + 单元格内联编辑（点击或双击进入编辑态）
    const tbody = document.querySelector('#task-table tbody');
    tbody.addEventListener('click', (ev) => {
      const btn = ev.target.closest('.row-actions button');
      if (btn) {
        ev.stopPropagation();
        const id = Number(btn.dataset.id);
        const act = btn.dataset.act;
        if (act === 'edit') openTask(id);
        else if (act === 'del') removeTask(id);
        else if (act === 'done') {
          const task = taskOf(id);
          const doneStatus = state.settings.done_status || '已完成';
          const current = task.status_list || [];
          const next = task.is_done
            ? current.filter((s) => s !== doneStatus)
            : [...current.filter((s) => s !== doneStatus), doneStatus];
          savePatch(id, { status: next })
            .then(() => toast('状态已更新', `当前状态：${next.join('、') || '未设置'}`, 'ok'));
        }
        return;
      }
      const cell = ev.target.closest('td.editable-cell');
      if (cell && !cell.dataset.editing) startInlineEdit(cell);
    });
    tbody.addEventListener('dblclick', (ev) => {
      const cell = ev.target.closest('td.editable-cell');
      if (cell && !cell.dataset.editing) startInlineEdit(cell);
    });

    // 导入导出
    document.getElementById('btn-import').addEventListener('click', openImport);
    document.getElementById('btn-import-2').addEventListener('click', openImport);
    document.getElementById('dropzone').addEventListener('click', () => document.getElementById('file-input').click());
    document.getElementById('file-input').addEventListener('change', (e) => handleFile(e.target.files[0]));
    const dz = document.getElementById('dropzone');
    dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('drag'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
    dz.addEventListener('drop', (e) => {
      e.preventDefault();
      dz.classList.remove('drag');
      if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    document.getElementById('btn-do-import').addEventListener('click', doImport);
    document.getElementById('btn-template').addEventListener('click', () => download('/api/export/template?format=xlsx'));
    document.getElementById('btn-export-xlsx').addEventListener('click', () => download(exportUrl('xlsx')));
    document.getElementById('btn-export-csv').addEventListener('click', () => download(exportUrl('csv')));
    document.getElementById('btn-cal-sync').addEventListener('click', async () => {
      try {
        const res = await API.calendarSync();
        toast('日历已生成', res.message + '｜' + res.path, 'ok');
      } catch (err) {
        toast('日历同步失败', err.message, 'err');
      }
    });

    // 提醒
    document.getElementById('btn-remind').addEventListener('click', () => {
      document.getElementById('drawer').classList.toggle('hidden');
      checkReminders(false);
    });
    document.getElementById('drawer-close').addEventListener('click', () => document.getElementById('drawer').classList.add('hidden'));

    // 设置
    document.getElementById('btn-save-settings').addEventListener('click', saveSettings);
    document.getElementById('btn-test-notify').addEventListener('click', async () => {
      try {
        await API.testNotify();
        toast('已发送测试通知', '若未看到通知，请在系统设置中允许终端发送通知', 'ok');
      } catch (err) {
        toast('测试失败', err.message, 'err');
      }
    });
    document.getElementById('btn-sync-now').addEventListener('click', async () => {
      try {
        const res = await API.calendarSync();
        toast('已生成日历文件', res.path, 'ok');
      } catch (err) {
        toast('生成失败', err.message, 'err');
      }
    });
    document.getElementById('btn-copy-feed').addEventListener('click', async () => {
      const url = `${location.origin}/api/calendar/feed.ics`;
      try {
        await navigator.clipboard.writeText(url);
        toast('已复制订阅地址', url, 'ok');
      } catch (e) {
        window.prompt('请手动复制订阅地址：', url);
      }
    });
    document.getElementById('btn-backup').addEventListener('click', async () => {
      try {
        const res = await API.backup();
        toast('备份完成', res.path, 'ok');
      } catch (err) {
        toast('备份失败', err.message, 'err');
      }
    });
    document.getElementById('btn-clear-all').addEventListener('click', async () => {
      const ok = await UI.confirm({
        title: '清空全部任务',
        message: '确定要清空台账中的全部任务吗？',
        hint: '系统会先自动备份到 data/backups/，但仍建议先导出表格留存。',
        okText: '清空',
        danger: true,
      });
      if (!ok) return;
      try {
        const res = await API.clearAll();
        toast('已清空', `共删除 ${res.deleted} 条任务（已自动备份）`, 'ok');
        loadList(); refreshStats(); checkReminders(false);
      } catch (err) {
        toast('清空失败', err.message, 'err');
      }
    });

    document.getElementById('check-all')?.addEventListener('change', () => {});
  }

  /* ---------------- 启动 ---------------- */
  async function boot(first = true) {
    try {
      try {
        const ping = await API.ping();
        state.version = ping.version || '';
      } catch (e) { /* ping 失败不影响主流程 */ }
      const vEl = document.getElementById('app-version');
      if (vEl && state.version) vEl.textContent = `v${state.version}`;

      const meta = await API.fields();
      state.fields = meta.fields;
      state.listFields = meta.list_fields;
      state.editableKeys = meta.editable_fields || [];
      state.leadOptions = meta.lead_options;
      const st = await API.getSettings();
      state.settings = st.settings;
      state.pageSize = state.settings.page_size || 20;
      state.items = state.items || [];

      renderHead();
      await refreshOptions();
    } catch (err) {
      toast('初始化失败', err.message, 'err');
    }
  }

  async function init() {
    await boot(true);
    // 事件只绑定一次：退出登录后重新进入时不再重复绑定
    if (!state.bound) {
      state.bound = true;
      bind();
      CalendarView.init();
    }
    await loadList();
    refreshStats();
    checkReminders(false);
    // 每 60 秒刷新提醒状态
    timers.push(setInterval(() => checkReminders(true), 60000));
    // 每分钟检查是否跨天，刷新一次列表（逾期状态随之更新）
    let lastDay = new Date().getDate();
    timers.push(setInterval(() => {
      const d = new Date().getDate();
      if (d !== lastDay) {
        lastDay = d;
        loadList();
      }
    }, 30000));
  }

  /* 退出登录 / 退出应用时清理：停掉轮询、关闭浮层、清空列表与编辑态 */
  function teardown() {
    timers.forEach((t) => clearInterval(t));
    timers.length = 0;
    state.inlineEditing = null;
    state.editingId = null;
    state.page = 1;
    state.total = 0;
    ['modal', 'import-modal', 'confirm-modal', 'pwd-modal', 'drawer', 'user-dropdown']
      .forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
      });
    const tbody = document.querySelector('#task-table tbody');
    if (tbody) tbody.innerHTML = '';
    const empty = document.getElementById('list-empty');
    if (empty) empty.classList.add('hidden');
    const badge = document.getElementById('remind-badge');
    if (badge) { badge.textContent = '0'; badge.classList.add('hidden'); }
  }

  return {
    init, teardown, openTask, escapeHtml, statusTag, priorityTag, loadList, toast,
    state, checkReminders,
  };
})();
