// Gerenciador: lista/cria/remove terminais da conta logada.
(function () {
  function csrf() {
    const m = document.cookie.match(/(?:^|;\s*)csrf=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  async function api(method, url, body) {
    const opt = { method, headers: {} };
    if (body) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    if (method !== 'GET') opt.headers['X-CSRF-Token'] = csrf();
    const res = await fetch(url, opt);
    if (res.status === 401) { location.href = '/login'; throw new Error('auth'); }
    if (res.ok) return res.json();
    let msg = res.statusText;
    try { msg = (await res.json()).error || msg; } catch (_) {}
    throw new Error(msg);
  }

  const listEl = document.getElementById('list');
  const busyEl = document.getElementById('busy');

  function render(sessions) {
    if (!sessions.length) {
      listEl.innerHTML = '<div class="empty">Nenhum terminal. Crie um acima.</div>';
      return;
    }
    listEl.innerHTML = '';
    for (const s of sessions) {
      const card = document.createElement('div');
      card.className = 'card';

      const dot = document.createElement('span');
      dot.className = 'dot' + (s.alive ? ' on' : '');

      const meta = document.createElement('div');
      meta.className = 'meta';
      const id = document.createElement('div');
      id.className = 'id';
      id.textContent = s.id + ' ';
      const badge = document.createElement('span');
      badge.className = 'badge' + (s.alive ? '' : ' off');
      badge.textContent = s.state || '—';
      id.appendChild(badge);
      const sub = document.createElement('div');
      sub.className = 'sub';
      sub.textContent = 'shell: ' + s.shell;
      meta.appendChild(id); meta.appendChild(sub);

      const actions = document.createElement('div');
      actions.className = 'actions';
      const open = document.createElement('button');
      open.textContent = 'Abrir';
      open.disabled = !s.alive;
      open.addEventListener('click', () => window.open('/t/' + encodeURIComponent(s.id), '_blank'));
      const kill = document.createElement('button');
      kill.className = 'danger';
      kill.textContent = 'Remover';
      kill.addEventListener('click', () => removeSession(s.id));
      actions.appendChild(open); actions.appendChild(kill);

      card.appendChild(dot); card.appendChild(meta); card.appendChild(actions);
      listEl.appendChild(card);
    }
  }

  async function refresh() {
    try {
      const { sessions } = await api('GET', '/api/sessions');
      render(sessions);
    } catch (_) { /* 401 ja redireciona */ }
  }

  async function removeSession(id) {
    if (!confirm('Remover o terminal ' + id + '?')) return;
    try { await api('POST', '/api/sessions/' + encodeURIComponent(id) + '/kill'); }
    catch (e) { alert('Falha: ' + e.message); }
    refresh();
  }

  document.getElementById('create').addEventListener('click', async () => {
    const shell = document.getElementById('shell').value;
    busyEl.textContent = 'criando…';
    try {
      const { id } = await api('POST', '/api/sessions', { shell });
      busyEl.textContent = '';
      window.open('/t/' + encodeURIComponent(id), '_blank');
      refresh();
    } catch (e) {
      busyEl.textContent = '';
      alert('Falha ao criar: ' + e.message);
    }
  });

  document.getElementById('logout').addEventListener('click', async () => {
    try { await api('POST', '/api/logout'); } catch (_) {}
    location.href = '/login';
  });

  refresh();
  setInterval(refresh, 2500);
})();
