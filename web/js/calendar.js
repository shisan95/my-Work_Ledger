/* ===================== 日历视图 ===================== */
const CalendarView = (() => {
  const state = {
    year: new Date().getFullYear(),
    month: new Date().getMonth() + 1,
    selected: null,
    days: {},
  };

  const WEEK_LABEL = ['一', '二', '三', '四', '五', '六', '日'];

  function key(y, m, d) {
    return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
  }

  function chipClass(task) {
    if (task.is_done) return 'done';
    if (task.is_overdue) return 'overdue';
    if (task.is_due_soon) return 'soon';
    return '';
  }

  async function render() {
    const grid = document.getElementById('cal-grid');
    const label = document.getElementById('cal-label');
    label.textContent = `${state.year} 年 ${state.month} 月`;

    let data;
    try {
      data = await API.calendarMonth(state.year, state.month);
    } catch (err) {
      grid.innerHTML = `<div class="muted" style="grid-column:1/-1">日历加载失败：${err.message}</div>`;
      return;
    }
    state.days = data.days || {};

    const first = new Date(state.year, state.month - 1, 1);
    const startWeekday = (first.getDay() + 6) % 7;      // 周一为一周起点
    const daysInMonth = new Date(state.year, state.month, 0).getDate();
    const prevDays = new Date(state.year, state.month - 1, 0).getDate();
    const today = new Date();
    const todayKey = key(today.getFullYear(), today.getMonth() + 1, today.getDate());

    const cells = [];
    // 上月末补齐
    for (let i = startWeekday - 1; i >= 0; i -= 1) {
      const d = prevDays - i;
      const pm = state.month === 1 ? 12 : state.month - 1;
      const py = state.month === 1 ? state.year - 1 : state.year;
      cells.push({ y: py, m: pm, d, other: true });
    }
    for (let d = 1; d <= daysInMonth; d += 1) {
      cells.push({ y: state.year, m: state.month, d, other: false });
    }
    while (cells.length % 7 !== 0) {
      const last = cells[cells.length - 1];
      let nd = last.d + 1, nm = last.m, ny = last.y;
      const max = new Date(ny, nm, 0).getDate();
      if (nd > max) { nd = 1; nm += 1; if (nm > 12) { nm = 1; ny += 1; } }
      cells.push({ y: ny, m: nm, d: nd, other: true });
    }

    grid.innerHTML = cells.map((c) => {
      const k = key(c.y, c.m, c.d);
      const list = state.days[k] || [];
      const shown = list.slice(0, 3);
      const chips = shown.map((t) => {
        const cls = chipClass(t);
        const name = App.escapeHtml(t.name);
        const statusText = (t.status_list || []).join('、');
        return `<span class="cal-chip ${cls}" data-id="${t.id}" title="${name}${statusText ? '｜' + statusText : ''}">${name}</span>`;
      }).join('');
      const more = list.length > shown.length ? `<div class="cal-more">还有 ${list.length - shown.length} 项</div>` : '';
      const cls = ['cal-cell'];
      if (c.other) cls.push('other');
      if (k === todayKey) cls.push('today');
      if (k === state.selected) cls.push('selected');
      return `<div class="${cls.join(' ')}" data-date="${k}" data-y="${c.y}" data-m="${c.m}" data-d="${c.d}">
        <div class="dnum"><span class="n">${c.d}</span>${list.length ? `<span class="cnt">${list.length}</span>` : ''}</div>
        ${chips}${more}
      </div>`;
    }).join('');

    grid.querySelectorAll('.cal-cell').forEach((cell) => {
      cell.addEventListener('click', (ev) => {
        const chip = ev.target.closest('.cal-chip');
        if (chip) {
          ev.stopPropagation();
          App.openTask(Number(chip.dataset.id));
          return;
        }
        state.selected = cell.dataset.date;
        grid.querySelectorAll('.cal-cell.selected').forEach((x) => x.classList.remove('selected'));
        cell.classList.add('selected');
        renderSide(cell.dataset.date);
      });
    });

    if (state.selected) renderSide(state.selected);
    else {
      const todayCells = state.days[todayKey];
      if (todayCells && state.month === today.getMonth() + 1) {
        state.selected = todayKey;
        renderSide(todayKey);
      } else {
        document.getElementById('cal-side-title').textContent = '当日任务';
        document.getElementById('cal-side-count').textContent = '0';
        document.getElementById('cal-side-body').innerHTML = '<p class="muted">点击日历中的某一天查看任务</p>';
      }
    }
  }

  function renderSide(dateKey) {
    const list = state.days[dateKey] || [];
    const d = new Date(dateKey + 'T00:00:00');
    document.getElementById('cal-side-title').textContent =
      `${d.getMonth() + 1} 月 ${d.getDate()} 日 周${WEEK_LABEL[(d.getDay() + 6) % 7]}`;
    document.getElementById('cal-side-count').textContent = String(list.length);

    const body = document.getElementById('cal-side-body');
    if (!list.length) {
      body.innerHTML = '<p class="muted">当天没有任务</p>';
      return;
    }
    body.innerHTML = list.map((t) => {
      const cls = t.is_overdue ? 'overdue' : '';
      const meta = [
        t.work_content ? `内容 ${App.escapeHtml(t.work_content.slice(0, 30))}` : '',
        t.priority ? App.escapeHtml(t.priority) : '',
        t.due_display ? `截止 ${t.due_display}` : '',
      ].filter(Boolean).join(' · ');
      return `<div class="side-task ${cls}" data-id="${t.id}">
        <div class="st-name">${App.escapeHtml(t.name)}</div>
        <div class="st-meta">${meta}</div>
        <div class="st-meta" style="margin-top:4px">${App.statusTag(t.status_list || t.status)}${t.delta_text ? `<span>${t.delta_text}</span>` : ''}</div>
      </div>`;
    }).join('');

    body.querySelectorAll('.side-task').forEach((el) => {
      el.addEventListener('click', () => App.openTask(Number(el.dataset.id)));
    });
  }

  function shift(delta) {
    let m = state.month + delta;
    let y = state.year;
    if (m < 1) { m = 12; y -= 1; }
    if (m > 12) { m = 1; y += 1; }
    state.month = m;
    state.year = y;
    state.selected = null;
    render();
  }

  function init() {
    document.getElementById('cal-prev').addEventListener('click', () => shift(-1));
    document.getElementById('cal-next').addEventListener('click', () => shift(1));
    document.getElementById('cal-today').addEventListener('click', () => {
      const now = new Date();
      state.year = now.getFullYear();
      state.month = now.getMonth() + 1;
      state.selected = null;
      render();
    });
  }

  return { state, render, init };
})();
