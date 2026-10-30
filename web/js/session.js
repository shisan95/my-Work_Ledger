/* ===================== 启动流程与通用交互 =====================
 * 启动：启动画面 → 连接本地服务 → 校验登录状态 → 首次建号/登录 → 进入主界面
 * 退出：退出确认 → 清理会话与缓存 → 返回登录页；退出应用则关闭本地服务
 */
const UI = (() => {
  const $ = (s) => document.querySelector(s);
  let resolver = null;

  function bindOnce() {
    const ok = $('#confirm-ok');
    const cancel = $('#confirm-cancel');
    const box = $('#confirm-modal');
    const done = (val) => {
      if (!resolver) return;
      const fn = resolver;
      resolver = null;
      box.classList.add('hidden');
      document.removeEventListener('keydown', onKey, true);
      fn(val);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); done(false); }
      else if (e.key === 'Enter') { e.preventDefault(); done(true); }
    };
    ok.addEventListener('click', () => done(true));
    cancel.addEventListener('click', () => done(false));
    box.querySelectorAll('[data-confirm-close]').forEach((el) => el.addEventListener('click', () => done(false)));
    box._done = done;
    box._onKey = onKey;
  }

  function confirm(opts = {}) {
    const box = $('#confirm-modal');
    if (!box._done) bindOnce();
    if (resolver) { const fn = resolver; resolver = null; fn(false); }

    $('#confirm-title').textContent = opts.title || '确认操作';
    $('#confirm-msg').textContent = opts.message || '';
    const hint = $('#confirm-hint');
    if (opts.hint) { hint.textContent = opts.hint; hint.classList.remove('hidden'); }
    else hint.classList.add('hidden');

    const okBtn = $('#confirm-ok');
    okBtn.textContent = opts.okText || '确定';
    okBtn.classList.toggle('danger', !!opts.danger);
    $('#confirm-cancel').textContent = opts.cancelText || '取消';
    $('#confirm-cancel').classList.toggle('hidden', !!opts.hideCancel);

    box.classList.remove('hidden');
    document.addEventListener('keydown', box._onKey, true);
    setTimeout(() => okBtn.focus(), 30);
    return new Promise((resolve) => { resolver = resolve; });
  }

  const alert = (title, message, opts = {}) =>
    confirm({ title, message, okText: opts.okText || '我知道了', hideCancel: true, ...opts });

  return { confirm, alert };
})();

const Boot = (() => {
  const $ = (s) => document.querySelector(s);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const state = {
    user: null,
    running: false,
    entered: false,
    expiredNotice: false,
    startedAt: 0,
  };

  /* ---------------- 启动画面 ---------------- */
  function setStep(text, pct) {
    const step = $('#splash-step');
    const bar = $('#splash-bar');
    if (step) step.textContent = text;
    if (bar) bar.style.width = `${Math.max(4, Math.min(pct, 100))}%`;
  }

  function showSplash() {
    const el = $('#splash');
    el.classList.remove('hide');
    el.style.display = '';
    $('#splash-error').classList.add('hidden');
    document.body.classList.add('booting');
    setStep('正在初始化…', 6);
  }

  async function finishSplash() {
    const elapsed = Date.now() - state.startedAt;
    const wait = Math.max(0, 780 - elapsed); // 避免启动画面一闪而过
    if (wait) await sleep(wait);
    setStep('准备就绪', 100);
    await sleep(160);
    const el = $('#splash');
    el.classList.add('hide');
    document.body.classList.remove('booting');
    setTimeout(() => { el.style.display = 'none'; }, 360);
  }

  function splashError(msg) {
    setStep('启动未能完成', 100);
    $('#splash-err-msg').textContent = msg || '启动失败，请重试';
    $('#splash-error').classList.remove('hidden');
  }

  /* ---------------- 视图切换 ---------------- */
  function hideAllViews() {
    $('#splash').style.display = 'none';
    $('#auth-screen').classList.add('hidden');
    $('#app-shell').classList.add('hidden');
    $('#closed-screen').classList.add('hidden');
  }

  function showAuth(which) {
    hideAllViews();
    document.body.classList.add('auth-locked');
    $('#auth-screen').classList.remove('hidden');
    $('#login-card').classList.toggle('hidden', which !== 'login');
    $('#setup-card').classList.toggle('hidden', which !== 'setup');
    hideAuthErrors();
    if (which === 'login') {
      const last = localStorage.getItem('tl_last_user') || 'admin';
      const input = $('#login-user');
      if (!input.value) input.value = last;
      // 已创建账号时隐藏「创建本机账号」入口
      $('#login-foot-setup').classList.toggle('hidden', state.initialized !== false);
      $('#login-foot-tip').classList.toggle('hidden', state.initialized === false);
      setTimeout(() => (input.value ? $('#login-pass') : input).focus(), 60);
    } else {
      $('#setup-user').value = 'admin';
      setTimeout(() => $('#setup-name').focus(), 60);
    }
  }

  function showLogin(reason) {
    showAuth('login');
    $('#login-pass').value = '';
    if (reason) {
      const err = $('#login-error');
      err.textContent = reason;
      err.classList.remove('hidden');
    }
  }

  function showSetup() {
    showAuth('setup');
    // 已创建过账号时不再显示创建入口
    const canSetup = !state.initialized;
    $('#login-foot-setup').classList.toggle('hidden', !canSetup);
    $('#login-foot-tip').classList.toggle('hidden', canSetup);
  }

  function setUser(user) {
    state.user = user || null;
    const name = (user && (user.display_name || user.username)) || '本机用户';
    $('#user-name').textContent = name;
    $('#user-avatar').textContent = name.slice(0, 1).toUpperCase();
    $('#menu-display').textContent = name;
    $('#menu-account').textContent = '@' + ((user && user.username) || '—');
    $('#brand-sub').textContent = `本机数据 · ${name}`;
  }

  function hideAuthErrors() {
    ['login-error', 'setup-error', 'pwd-error'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) { el.classList.add('hidden'); el.textContent = ''; el.classList.remove('shake'); }
    });
  }

  function authError(id, msg) {
    const el = document.getElementById(id);
    el.textContent = msg;
    el.classList.remove('hidden');
    el.classList.remove('shake');
    void el.offsetWidth;
    el.classList.add('shake');
  }

  function busy(btn, on, text) {
    if (!btn) return;
    if (on) {
      btn.dataset.label = btn.textContent;
      btn.textContent = text || '处理中…';
      btn.disabled = true;
    } else {
      btn.textContent = btn.dataset.label || btn.textContent;
      btn.disabled = false;
    }
  }

  /* ---------------- 进入 / 退出主界面 ---------------- */
  async function enterApp(user) {
    setUser(user);
    hideAllViews();
    $('#app-shell').classList.remove('hidden');
    document.body.classList.remove('auth-locked');
    if (!state.entered) {
      state.entered = true;
      await App.init();
    }
  }

  function leaveApp() {
    try { if (typeof App.teardown === 'function') App.teardown(); } catch (e) { /* 忽略 */ }
    state.entered = false;
    state.user = null;
    hideAllViews();
  }

  function clearClientCache() {
    try { sessionStorage.clear(); } catch (e) { /* 忽略 */ }
    try {
      Object.keys(localStorage)
        .filter((k) => k.startsWith('tl_') && k !== 'tl_last_user')
        .forEach((k) => localStorage.removeItem(k));
    } catch (e) { /* 忽略 */ }
    // 清掉可能残留的页面内数据与草稿
    document.querySelectorAll('#task-table tbody').forEach((el) => { el.innerHTML = ''; });
  }

  async function doLogout(reason, skipConfirm) {
    if (!skipConfirm) {
      const ok = await UI.confirm({
        title: '退出登录',
        message: '确定要退出当前账号吗？',
        hint: '退出后会清除本次会话与本地缓存，重新使用需要再次输入密码。',
        okText: '退出登录',
      });
      if (!ok) return;
    }
    try { await API.authLogout(); } catch (e) { /* 会话可能已失效，继续本地清理 */ }
    clearClientCache();
    leaveApp();
    showLogin(reason || '已退出登录');
  }

  async function doQuit() {
    const ok = await UI.confirm({
      title: '退出应用',
      message: '退出后本地服务将关闭，当前页面会断开连接。',
      hint: '正在编辑的内容请先保存；下次使用双击桌面「任务台账」图标重新启动。',
      okText: '退出应用',
      danger: true,
    });
    if (!ok) return;
    try {
      await API.appQuit();
    } catch (e) { /* 服务可能在响应前退出，属正常 */ }
    clearClientCache();
    leaveApp();
    $('#closed-screen').classList.remove('hidden');
    document.body.classList.remove('auth-locked');
    // 允许浏览器直接关闭该标签页时自动关闭
    setTimeout(() => { try { window.close(); } catch (e) { /* 忽略 */ } }, 400);
  }

  /* ---------------- 登录 / 建号 ---------------- */
  async function submitLogin(ev) {
    ev.preventDefault();
    hideAuthErrors();
    const username = $('#login-user').value.trim();
    const password = $('#login-pass').value;
    const remember = $('#login-remember').checked;
    const btn = $('#btn-login');

    if (!username) { authError('login-error', '请输入用户名'); $('#login-user').focus(); return; }
    if (!password) { authError('login-error', '请输入密码'); $('#login-pass').focus(); return; }

    busy(btn, true, '登录中…');
    try {
      const res = await API.authLogin({ username, password, remember });
      localStorage.setItem('tl_last_user', username);
      await enterApp(res.user);
      showTip('登录成功', `欢迎回来，${(res.user && (res.user.display_name || res.user.username)) || username}`, 'ok');
    } catch (err) {
      authError('login-error', err.message || '登录失败');
      if (err.status === 401) { $('#login-pass').value = ''; $('#login-pass').focus(); }
    } finally {
      busy(btn, false);
    }
  }

  async function submitSetup(ev) {
    ev.preventDefault();
    hideAuthErrors();
    const username = $('#setup-user').value.trim();
    const displayName = $('#setup-name').value.trim();
    const pass = $('#setup-pass').value;
    const pass2 = $('#setup-pass2').value;
    const btn = $('#btn-setup');

    if (username.length < 2) { authError('setup-error', '用户名至少 2 个字符'); return; }
    if (pass.length < 6) { authError('setup-error', '密码至少 6 位'); $('#setup-pass').focus(); return; }
    if (pass !== pass2) { authError('setup-error', '两次输入的密码不一致'); $('#setup-pass2').focus(); return; }

    busy(btn, true, '创建中…');
    try {
      const res = await API.authSetup({ username, password: pass, display_name: displayName, remember: true });
      state.initialized = true;
      localStorage.setItem('tl_last_user', username);
      await enterApp(res.user);
      showTip('账号已创建', '账号仅保存在本机，请牢记密码', 'ok');
    } catch (err) {
      if (err.status === 400 && /已创建/.test(err.message)) {
        state.initialized = true;
        showLogin(err.message);
      } else {
        authError('setup-error', err.message || '创建失败');
      }
    } finally {
      busy(btn, false);
    }
  }

  function showTip(title, body, type) {
    try { App.toast(title, body, type); } catch (e) { /* 主界面未就绪时忽略 */ }
  }

  /* ---------------- 修改密码 ---------------- */
  async function submitPassword() {
    hideAuthErrors();
    const oldPass = $('#pwd-old').value;
    const next = $('#pwd-new').value;
    const next2 = $('#pwd-new2').value;
    if (!oldPass) { authError('pwd-error', '请输入当前密码'); return; }
    if (next.length < 6) { authError('pwd-error', '新密码至少 6 位'); return; }
    if (next !== next2) { authError('pwd-error', '两次输入的新密码不一致'); return; }

    const btn = $('#btn-save-pwd');
    busy(btn, true, '保存中…');
    try {
      await API.authPassword({ old_password: oldPass, new_password: next });
      $('#pwd-modal').classList.add('hidden');
      clearClientCache();
      leaveApp();
      showLogin('密码已更新，请使用新密码登录');
    } catch (err) {
      authError('pwd-error', err.message || '修改失败');
    } finally {
      busy(btn, false);
    }
  }

  /* ---------------- 用户菜单 ---------------- */
  function toggleMenu(force) {
    const menu = $('#user-dropdown');
    const btn = $('#btn-user');
    const show = typeof force === 'boolean' ? force : menu.classList.contains('hidden');
    menu.classList.toggle('hidden', !show);
    btn.setAttribute('aria-expanded', String(show));
  }

  function bindUi() {
    // 登录 / 建号
    $('#login-form').addEventListener('submit', submitLogin);
    $('#setup-form').addEventListener('submit', submitSetup);
    $('#to-setup').addEventListener('click', () => showAuth('setup'));
    $('#login-foot-setup').classList.add('hidden');

    ['login-eye', 'setup-eye'].forEach((id) => {
      const btn = document.getElementById(id);
      btn.addEventListener('click', () => {
        const wrap = btn.closest('.pwd-wrap');
        const input = wrap.querySelector('input');
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        btn.textContent = show ? '隐藏' : '显示';
        btn.setAttribute('aria-label', show ? '隐藏密码' : '显示密码');
      });
    });

    $('#setup-pass').addEventListener('input', (e) => {
      const v = e.target.value;
      const meter = $('#setup-meter');
      meter.classList.remove('s1', 's2', 's3');
      if (!v) return;
      const strong = v.length >= 10 && /[A-Za-z]/.test(v) && /\d/.test(v);
      const mid = v.length >= 8 || (/[A-Za-z]/.test(v) && /\d/.test(v));
      meter.classList.add(strong ? 's3' : mid ? 's2' : 's1');
    });

    $('#btn-forgot').addEventListener('click', () => {
      UI.alert(
        '忘记密码',
        '本机账号密码无法找回。可关闭应用后删除 data/auth.json，重新启动时会要求创建新的本机账号（任务数据不会丢失）。',
        { okText: '我知道了' }
      );
    });

    // 启动错误处理
    $('#btn-boot-retry').addEventListener('click', () => {
      $('#splash-error').classList.add('hidden');
      run(true);
    });
    $('#btn-boot-help').addEventListener('click', () => {
      UI.alert(
        '无法连接本地服务',
        '1）确认「任务台账」应用已启动（双击桌面图标）；\n2）若刚启动，请等待几秒后重试；\n3）仍失败可查看 data/logs/ 下的日志，或改用命令行 ./run.sh 启动。',
        { okText: '我知道了' }
      );
    });

    // 用户菜单
    $('#btn-user').addEventListener('click', (e) => { e.stopPropagation(); toggleMenu(); });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#user-menu')) toggleMenu(false);
    });
    $('#menu-lock').addEventListener('click', () => { toggleMenu(false); doLogout(); });
    $('#menu-quit').addEventListener('click', () => { toggleMenu(false); doQuit(); });
    $('#menu-change-pwd').addEventListener('click', () => {
      toggleMenu(false);
      hideAuthErrors();
      ['pwd-old', 'pwd-new', 'pwd-new2'].forEach((id) => { document.getElementById(id).value = ''; });
      $('#pwd-modal').classList.remove('hidden');
      setTimeout(() => $('#pwd-old').focus(), 60);
    });
    $('#btn-save-pwd').addEventListener('click', submitPassword);
    $('#pwd-form').addEventListener('submit', (e) => { e.preventDefault(); submitPassword(); });
    document.querySelectorAll('[data-pwd-close]').forEach((el) => {
      el.addEventListener('click', () => $('#pwd-modal').classList.add('hidden'));
    });

    $('#btn-reopen').addEventListener('click', () => {
      UI.alert('重新启动应用', '请双击桌面或项目目录中的「任务台账」图标启动，随后刷新此页面。', { okText: '好' });
    });

    // Esc：优先关闭最上层浮层
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (!$('#confirm-modal').classList.contains('hidden')) return; // 由确认弹窗自身处理
      if (!$('#pwd-modal').classList.contains('hidden')) { $('#pwd-modal').classList.add('hidden'); return; }
      if (!$('#user-dropdown').classList.contains('hidden')) { toggleMenu(false); }
    });

    // 会话失效：统一回到登录页
    window.addEventListener('auth:expired', () => {
      if (state.expiredNotice) return;
      state.expiredNotice = true;
      clearClientCache();
      leaveApp();
      showLogin('登录状态已过期，请重新登录');
      setTimeout(() => { state.expiredNotice = false; }, 1500);
    });
  }

  /* ---------------- 启动主流程 ---------------- */
  async function run(isRetry) {
    if (state.running) return;
    state.running = true;
    state.startedAt = Date.now();
    if (!isRetry) showSplash(); else setStep('正在重试连接…', 10);
    if (!state.uiBound) { state.uiBound = true; bindUi(); } // 交互只绑定一次

    try {
      setStep('正在准备界面资源…', 18);
      await sleep(180);

      setStep('正在连接本地服务…', 32);
      const ping = await API.ping();
      setStep('本地服务已就绪', 46);

      setStep('正在校验登录状态…', 60);
      const st = await API.authStatus();
      state.initialized = !!st.initialized;

      if (!st.initialized) {
        await finishSplash();
        showAuth('setup');
        return;
      }

      if (!st.authenticated) {
        await finishSplash();
        showAuth('login');
        return;
      }

      setStep('正在加载任务数据…', 80);
      await enterApp(st.user);
      setStep('准备就绪', 100);
      await finishSplash();
      if (isRetry) showTip('已恢复连接', '本地服务运行正常', 'ok');
      if (ping && ping.version) $('#splash-version').textContent = ping.version;
    } catch (err) {
      splashError(err && err.message ? err.message : '启动过程中发生未知错误');
    } finally {
      state.running = false;
    }
  }

  return { run, showLogin, showSetup, doLogout, doQuit, setUser, state, clearClientCache };
})();

document.addEventListener('DOMContentLoaded', () => {
  Boot.run();
});
