// Terminal: xterm.js conectado ao proxy WS autenticado do gerenciador.
(function () {
  const cid = document.body.dataset.cid;
  const dot = document.getElementById('dot');
  const status = document.getElementById('status');

  const term = new Terminal({
    cursorBlink: true, fontSize: 14, scrollback: 5000,
    fontFamily: "'Cascadia Code', Consolas, monospace",
    theme: { background: '#0c0c0c', foreground: '#e0e0e0', cursor: '#2ecc71' }
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(document.getElementById('term'));
  fit.fit();

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(proto + '://' + location.host + '/t/' + encodeURIComponent(cid) + '/ws');
  ws.binaryType = 'arraybuffer';

  function sendResize() {
    if (ws.readyState === 1) ws.send(JSON.stringify({ r: [term.cols, term.rows] }));
  }

  ws.onopen = () => {
    dot.classList.add('on');
    status.textContent = 'conectado — ' + term.cols + 'x' + term.rows;
    sendResize();
    term.focus();
  };
  ws.onmessage = (ev) => {
    if (typeof ev.data === 'string') term.write(ev.data);
    else term.write(new Uint8Array(ev.data));
  };
  ws.onclose = () => { dot.classList.remove('on'); status.textContent = 'desconectado'; };

  term.onData((d) => { if (ws.readyState === 1) ws.send(JSON.stringify({ i: d })); });
  window.addEventListener('resize', () => fit.fit());
  term.onResize(() => {
    status.textContent = 'conectado — ' + term.cols + 'x' + term.rows;
    sendResize();
  });
})();
