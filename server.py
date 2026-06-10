#!/usr/bin/env python3
"""
Terminal web — app de TERMINAL UNICO (roda DENTRO de cada container), em Flask.

Cada container Podman e uma sessao isolada: este app expoe um unico terminal
(um PTY REAL por conexao WebSocket) na porta 8765. O gerenciador no host (app.py)
sobe um container destes por sessao, publicado SO em 127.0.0.1, e faz proxy
autenticado do WebSocket. Por isso este app nao tem autenticacao propria — ele
nunca fica exposto na rede.

PTY real: vim, nano, htop, top, less, REPLs e prompts do apt funcionam.
Shell controlado por TERM_SHELL ('pwsh' | 'bash') e TYPE_SHELL (ex.: 'sh').
"""

import json
import os
import struct
import subprocess
import threading

from flask import Flask, Response
from flask_sock import Sock

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))


def shell_command():
    choice = os.environ.get("TERM_SHELL", "").lower().strip()
    if choice == "pwsh":
        return ["pwsh", "-NoLogo"]
    if choice == "bash":
        type_shell = os.environ.get("TYPE_SHELL", "").lower().strip() or "bash"
        return [f"/bin/{type_shell}"]
    return ["/bin/zsh"]


SHELL_CMD = shell_command()


# ---------------------------------------------------------------------------
# PTY real (Linux)
# ---------------------------------------------------------------------------

class PosixPty:
    def __init__(self, argv):
        import pty
        self.master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        home = os.environ.get("HOME") or os.path.expanduser("~")
        self.proc = subprocess.Popen(
            argv,
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            preexec_fn=os.setsid, env=env,
            cwd=home if os.path.isdir(home) else None,
        )
        os.close(slave_fd)

    def read(self):
        try:
            return os.read(self.master_fd, 65536)
        except OSError:
            return b""

    def write(self, data):
        try:
            os.write(self.master_fd, data)
        except OSError:
            pass

    def resize(self, rows, cols):
        import fcntl
        import termios
        try:
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Flask + WebSocket
# ---------------------------------------------------------------------------

PAGE = """<!DOCTYPE html><html lang="pt-br"><head><meta charset="utf-8"/>
<title>Terminal</title></head><body style="background:#0c0c0c;color:#ccc;
font-family:monospace;padding:20px">
Este e o app de terminal de um container. Acesse pelo gerenciador.
</body></html>"""

app = Flask(__name__)
sock = Sock(app)


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


@sock.route("/ws")
def ws_terminal(ws):
    pty = PosixPty(SHELL_CMD)

    def reader():
        while True:
            data = pty.read()
            if not data:
                break
            try:
                ws.send(data)               # bytes -> frame binario
            except Exception:
                break
        try:
            ws.send("\r\n[processo encerrado]\r\n")
            ws.close()
        except Exception:
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        while True:
            msg = ws.receive()              # texto JSON do navegador
            if msg is None:
                break
            try:
                data = json.loads(msg)
            except (ValueError, TypeError):
                continue
            if "i" in data:
                pty.write(data["i"].encode("utf-8"))
            elif "r" in data:
                cols, rows = data["r"]
                pty.resize(int(rows), int(cols))
    except Exception:
        pass
    finally:
        pty.close()


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, threaded=True)
