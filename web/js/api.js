/* ===================== 接口封装 ===================== */
const API = (() => {
  async function request(url, options = {}) {
    let res;
    try {
      res = await fetch(url, options);
    } catch (e) {
      // 网络层中断（服务已退出 / 断网）：交给调用方提示，不误判为登录失效
      throw new Error('无法连接本地服务，请确认应用正在运行');
    }
    if (res.status === 401 && !url.startsWith('/api/auth/')) {
      // 会话失效：通知启动控制器统一跳转登录页
      window.dispatchEvent(new CustomEvent('auth:expired', { detail: { url } }));
    }
    if (!res.ok) {
      let msg = `请求失败（${res.status}）`;
      try {
        const data = await res.json();
        if (data && data.detail) msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      } catch (e) { /* 忽略解析失败 */ }
      const err = new Error(msg);
      err.status = res.status;
      throw err;
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
    // ---- 启动与登录 ----
    ping: () => request('/api/ping'),
    authStatus: () => request('/api/auth/status'),
    authSetup: (data) => request('/api/auth/setup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }),
    authLogin: (data) => request('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }),
    authLogout: () => request('/api/auth/logout', { method: 'POST' }),
    authPassword: (data) => request('/api/auth/password', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }),
    appQuit: () => request('/api/app/quit', { method: 'POST' }),

    fields: () => request('/api/fields'),
    options: () => request('/api/options'),
    stats: () => request('/api/stats'),
    weeklyReport: () => request('/api/report/weekly'),

    listTasks: (params) => request('/api/tasks?' + qs(params)),
    getTask: (id) => request(`/api/tasks/${id}`),
    getHistory: (id) => request(`/api/tasks/${id}/history`),
    createTask: (data) => request('/api/tasks', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }),
    updateTask: (id, data) => request(`/api/tasks/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    }),
    deleteTask: (id, hard) => request(`/api/tasks/${id}${hard ? '?hard=1' : ''}`, { method: 'DELETE' }),
    setParent: (id, parentId) => request(`/api/tasks/${id}/parent`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parent_id: parentId }),
    }),
    bulkDelete: (ids) => request('/api/tasks/bulk-delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }),
    }),
    bulkUpdate: (ids, patch) => request('/api/tasks/bulk-update', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids, patch }),
    }),
    trashRestore: (ids) => request('/api/trash/restore', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }),
    }),
    trashPurge: (ids) => request('/api/trash/purge', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }),
    }),
    trashEmpty: () => request('/api/trash/empty', { method: 'POST' }),
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
