// Tela de login/registro. Lê o token CSRF do cookie e envia no header.
(function () {
  function csrf() {
    const m = document.cookie.match(/(?:^|;\s*)csrf=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  const card = document.querySelector('.card');
  const allowRegister = card.dataset.allowRegister === 'true';
  const tabLogin = document.getElementById('tab-login');
  const tabReg = document.getElementById('tab-register');
  const submit = document.getElementById('submit');
  const msg = document.getElementById('msg');
  let mode = 'login';

  if (!allowRegister) tabReg.style.display = 'none';

  function setMode(m) {
    mode = m;
    tabLogin.classList.toggle('active', m === 'login');
    tabReg.classList.toggle('active', m === 'register');
    submit.textContent = m === 'login' ? 'Entrar' : 'Criar conta';
    msg.textContent = '';
  }
  tabLogin.addEventListener('click', () => setMode('login'));
  tabReg.addEventListener('click', () => setMode('register'));

  document.getElementById('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;
    const url = mode === 'login' ? '/api/login' : '/api/register';
    msg.style.color = '#ff8a80';
    msg.textContent = '…';
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf() },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { msg.textContent = data.error || 'Falhou.'; return; }
      msg.style.color = '#79d68b';
      msg.textContent = 'OK, entrando…';
      location.href = '/';
    } catch (_) {
      msg.textContent = 'Erro de conexão.';
    }
  });
})();
