/* ===================== 接口封装 ===================== */
const API = (() => {
  async function request(url, options = {}) {
    const res = await fetch(url, options);
    if (!res.ok) {
      let msg = `请求失败（${res.status}）`;
      try {
        const data = await res.json();
        if (data && data.detail) msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      } catch (e) { /* 忽略解析失败 */ }
      throw new Error(msg);
    }
    const ct = res.headers.get('content-type') || '';
    return ct.includes('application/json') ? res.json() : res.text();
  }

  function qs(params) {
    const sp = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v === undefined || v === null || v === '' || v === false) return;
      if (Array.isArray(v)) v.forEach((x) => x && sp.append(k, x));
      else sp.append(k, v);
    });
    return sp.toString();
  }

  return {
    fields: () => request('/api/fields'),
    options: () => request('/api/options'),
    stats: () => request('/api/stats'),

    listTasks: (params) => request('/api/tasks?' + qs(params)),
    getTask: (id) => request(`/api/tasks/${id}`),
    createTask: (data) => request('/api/tasks', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }),
    updateTask: (id, data) => request(`/api/tasks/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }),
    deleteTask: (id) => request(`/api/tasks/${id}`, { method: 'DELETE' }),
    bulkDelete: (ids) => request('/api/tasks/bulk-delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }),
    }),
    clearAll: () => request('/api/tasks/clear', { method: 'POST' }),

    importFile: (file, mode) => {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('mode', mode);
      return request('/api/import', { method: 'POST', body: fd });
    },
    importPreview: (file) => {
      const fd = new FormData();
      fd.append('file', file);
      return request('/api/import/preview', { method: 'POST', body: fd });
    },

    calendarMonth: (year, month) => request(`/api/calendar/month?year=${year}&month=${month}`),
    calendarSync: () => request('/api/calendar/sync', { method: 'POST' }),

    reminders: () => request('/api/reminders/check'),
    snooze: (id, minutes) => request(`/api/reminders/snooze/${id}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ minutes }),
    }),
    testNotify: () => request('/api/reminders/test', { method: 'POST' }),

    getSettings: () => request('/api/settings'),
    saveSettings: (data) => request('/api/settings', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }),
    backup: () => request('/api/system/backup', { method: 'POST' }),
  };
})();
