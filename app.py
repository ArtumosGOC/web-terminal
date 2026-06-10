#!/usr/bin/env python3
"""
Gerenciador de terminais — backend Flask (roda no HOST).

Arquitetura:
  - Cada terminal e um container Podman ISOLADO, publicado SO em 127.0.0.1
    (nunca exposto na rede). O navegador nao fala direto com o container.
  - O Flask autentica a conta (token de sessao no Postgres) e faz PROXY do
    WebSocket ate o container, conferindo se a conta e a dona daquele terminal.
    Assim cada terminal fica vinculado a UMA conta de verdade.
  - Contas e tokens ficam num PostgreSQL (container separado), acessado por
    psycopg com consultas parametrizadas (sem injecao).
  - O dono de cada terminal e gravado no label `wt-owner` do container, entao o
    `podman ps` continua sendo a fonte da verdade do que esta rodando.
"""

import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time

from flask import (Flask, request, session, redirect, jsonify, abort,
                   render_template, make_response)
from flask_sock import Sock
import simple_websocket
import psycopg
from psycopg_pool import ConnectionPool
from werkzeug.security import generate_password_hash, check_password_hash

HERE = os.path.dirname(os.path.abspath(__file__))
LABEL = "web-terminal-session"
CONTAINER_PORT = "8765"
TOKEN_TTL_DAYS = 7


# ---------------------------------------------------------------------------
# Configuracao (.env + variaveis de ambiente)
# ---------------------------------------------------------------------------

def load_dotenv():
    path = os.path.join(HERE, ".env")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()


def env(key, default=""):
    return os.environ.get(key, default)


HOST = env("MANAGER_HOST", "127.0.0.1")
PORT = int(env("MANAGER_PORT", "8765"))
IMAGE = env("IMAGE", "web-terminal")
ALLOW_REGISTER = env("ALLOW_REGISTER", "true").lower() == "true"
ADMIN_USER = env("ADMIN_USER", "")
ADMIN_PASSWORD = env("ADMIN_PASSWORD", "")
FORCE_HTTPS = env("FORCE_HTTPS", "false").lower() == "true"

SECRET_KEY = env("SECRET_KEY", "")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(48)
    print("[AVISO] SECRET_KEY ausente no .env — gerada uma efemera "
          "(sessoes/CSRF nao sobrevivem a reinicio). Defina SECRET_KEY no .env.")

PG_CONTAINER = env("PG_CONTAINER", "web-terminal-db")
PG_IMAGE = env("PG_IMAGE", "docker.io/library/postgres:16-alpine")
PG_USER = env("PG_USER", "webterminal")
PG_PASSWORD = env("PG_PASSWORD", "webterminal")
PG_DB = env("PG_DB", "webterminal")
PG_PORT = env("PG_PORT", "5432")
PG_VOLUME = env("PG_VOLUME", "web-terminal-pgdata")

SHELL_ENV = {
    "zsh":  {},
    "bash": {"TERM_SHELL": "bash", "TYPE_SHELL": "bash"},
    "sh":   {"TERM_SHELL": "bash", "TYPE_SHELL": "sh"},
    "pwsh": {"TERM_SHELL": "pwsh"},
}

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
_build_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Podman
# ---------------------------------------------------------------------------

def podman(args, **kw):
    return subprocess.run(["podman", *args], capture_output=True, text=True, **kw)


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def ensure_image():
    if podman(["image", "exists", IMAGE]).returncode == 0:
        return
    with _build_lock:
        if podman(["image", "exists", IMAGE]).returncode == 0:
            return
        print(f"==> Construindo imagem '{IMAGE}' (primeira vez)...")
        r = podman(["build", "-t", IMAGE, "."], cwd=HERE)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "falha no build da imagem")


# ---------------------------------------------------------------------------
# PostgreSQL (container) + psycopg
# ---------------------------------------------------------------------------

POOL = None  # ConnectionPool, aberto em ensure_postgres()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  username   TEXT PRIMARY KEY,
  password   TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS auth_tokens (
  token      TEXT PRIMARY KEY,
  username   TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def db_exec(sql, params=()):
    with POOL.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def db_query(sql, params=()):
    with POOL.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def ensure_postgres():
    global POOL
    r = podman(["ps", "-a", "--filter", f"name=^{PG_CONTAINER}$",
                "--format", "{{.State}}"])
    state = r.stdout.strip()
    if state == "":
        print(f"==> Subindo PostgreSQL '{PG_CONTAINER}'...")
        run = podman(["run", "-d", "--name", PG_CONTAINER,
                      "-e", f"POSTGRES_USER={PG_USER}",
                      "-e", f"POSTGRES_PASSWORD={PG_PASSWORD}",
                      "-e", f"POSTGRES_DB={PG_DB}",
                      "-p", f"127.0.0.1:{PG_PORT}:5432",
                      "-v", f"{PG_VOLUME}:/var/lib/postgresql/data",
                      PG_IMAGE])
        if run.returncode != 0:
            raise RuntimeError(run.stderr.strip() or "falha ao subir o Postgres")
    elif state != "running":
        podman(["start", PG_CONTAINER])

    print("==> Aguardando o PostgreSQL ficar pronto...")
    for _ in range(60):
        if podman(["exec", PG_CONTAINER, "pg_isready", "-U", PG_USER,
                   "-d", PG_DB]).returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("PostgreSQL nao ficou pronto a tempo")

    dsn = (f"host=127.0.0.1 port={PG_PORT} dbname={PG_DB} "
           f"user={PG_USER} password={PG_PASSWORD}")
    POOL = ConnectionPool(dsn, min_size=1, max_size=8, kwargs={"autocommit": True})
    POOL.wait(timeout=30)

    db_exec(SCHEMA_SQL)
    if ADMIN_USER and ADMIN_PASSWORD and not get_user(ADMIN_USER):
        create_user(ADMIN_USER, ADMIN_PASSWORD)
        print(f"==> Conta admin '{ADMIN_USER}' criada.")


# ---------------------------------------------------------------------------
# Contas / autenticacao
# ---------------------------------------------------------------------------

def get_user(username):
    rows = db_query("SELECT username, password FROM users WHERE username = %s",
                    (username,))
    return {"username": rows[0][0], "password": rows[0][1]} if rows else None


def create_user(username, password):
    db_exec("INSERT INTO users (username, password) VALUES (%s, %s)",
            (username, generate_password_hash(password)))


def make_token(username):
    token = secrets.token_urlsafe(32)
    db_exec("INSERT INTO auth_tokens (token, username) VALUES (%s, %s)",
            (token, username))
    return token


def user_for_token(token):
    if not token:
        return None
    rows = db_query(
        "SELECT username FROM auth_tokens "
        "WHERE token = %s AND created_at > now() - %s::interval",
        (token, f"{TOKEN_TTL_DAYS} days"))
    return rows[0][0] if rows else None


def drop_token(token):
    if token:
        db_exec("DELETE FROM auth_tokens WHERE token = %s", (token,))


# ---------------------------------------------------------------------------
# Containers de terminal
# ---------------------------------------------------------------------------

def create_container(shell, owner):
    shell = (shell or "zsh").lower().strip()
    if shell not in SHELL_ENV:
        shell = "zsh"
    ensure_image()
    name = "wt-" + secrets.token_hex(4)
    port = free_port()
    args = ["run", "-d", "--name", name,
            "--label", f"{LABEL}=1",
            "--label", f"wt-shell={shell}",
            "--label", f"wt-owner={owner}",
            "-p", f"127.0.0.1:{port}:{CONTAINER_PORT}"]
    for k, v in SHELL_ENV[shell].items():
        args += ["-e", f"{k}={v}"]
    args.append(IMAGE)
    r = podman(args)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "falha ao iniciar o container")
    return {"id": name, "shell": shell}


def list_containers(owner):
    r = podman(["ps", "-a",
                "--filter", f"label={LABEL}=1",
                "--filter", f"label=wt-owner={owner}",
                "--format", "json"])
    if r.returncode != 0:
        return []
    try:
        data = json.loads(r.stdout or "[]")
    except ValueError:
        return []
    out = []
    for c in data:
        names = c.get("Names") or [c.get("Id", "")[:12]]
        state = (c.get("State") or "").lower()
        labels = c.get("Labels") or {}
        out.append({"id": names[0], "shell": labels.get("wt-shell", "?"),
                    "state": state, "alive": state == "running"})
    out.sort(key=lambda s: s["id"])
    return out


def container_owner(cid):
    r = podman(["inspect", "--format",
                '{{ index .Config.Labels "wt-owner" }}', cid])
    return r.stdout.strip() if r.returncode == 0 else None


def container_addr(cid):
    r = podman(["port", cid, CONTAINER_PORT])
    line = next((l for l in (r.stdout or "").splitlines() if l.strip()), "")
    host, _, port = line.strip().rpartition(":")
    if not port.isdigit():
        return None
    return (host or "127.0.0.1", int(port))


def remove_container(cid, owner):
    if container_owner(cid) != owner:
        return False
    return podman(["rm", "-f", cid]).returncode == 0


# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=FORCE_HTTPS,
)
sock = Sock(app)

_login_hits = {}          # ip -> [timestamps]  (throttle simples de login)
_login_lock = threading.Lock()


def current_user():
    return user_for_token(request.cookies.get("wt_token"))


def login_throttled(ip):
    now = time.time()
    with _login_lock:
        hits = [t for t in _login_hits.get(ip, []) if now - t < 300]
        _login_hits[ip] = hits
        if len(hits) >= 10:          # 10 tentativas / 5 min
            return True
        hits.append(now)
        return False


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "img-src 'self' data:; font-src https://cdn.jsdelivr.net data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'"
    )
    if "csrf" not in request.cookies:
        resp.set_cookie("csrf", secrets.token_urlsafe(32),
                        samesite="Lax", secure=FORCE_HTTPS)
    return resp


@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        sent = request.headers.get("X-CSRF-Token", "")
        cookie = request.cookies.get("csrf", "")
        if not sent or not cookie or not secrets.compare_digest(sent, cookie):
            return jsonify(error="csrf"), 403


# --- paginas -----------------------------------------------------------------

@app.get("/login")
def login_page():
    if current_user():
        return redirect("/")
    return render_template("login.html", allow_register=ALLOW_REGISTER)


@app.get("/")
def manager_page():
    user = current_user()
    if not user:
        return redirect("/login")
    return render_template("manager.html", username=user)


@app.get("/t/<cid>")
def terminal_page(cid):
    user = current_user()
    if not user:
        return redirect("/login")
    if container_owner(cid) != user:
        abort(403)
    return render_template("terminal.html", cid=cid)


# --- API auth ----------------------------------------------------------------

@app.post("/api/register")
def api_register():
    if not ALLOW_REGISTER:
        return jsonify(error="registro desabilitado"), 403
    data = request.get_json(silent=True) or {}
    u = (data.get("username") or "").strip()
    p = data.get("password") or ""
    if not USERNAME_RE.match(u):
        return jsonify(error="usuario invalido (3-32: letras, numeros, . _ -)"), 400
    if len(p) < 6:
        return jsonify(error="senha precisa de ao menos 6 caracteres"), 400
    if get_user(u):
        return jsonify(error="usuario ja existe"), 409
    create_user(u, p)
    resp = make_response(jsonify(ok=True, username=u), 201)
    _set_auth_cookie(resp, make_token(u))
    return resp


@app.post("/api/login")
def api_login():
    if login_throttled(request.remote_addr or "?"):
        return jsonify(error="muitas tentativas, tente em alguns minutos"), 429
    data = request.get_json(silent=True) or {}
    u = (data.get("username") or "").strip()
    p = data.get("password") or ""
    user = get_user(u)
    if not user or not check_password_hash(user["password"], p):
        return jsonify(error="usuario ou senha invalidos"), 401
    resp = make_response(jsonify(ok=True, username=u))
    _set_auth_cookie(resp, make_token(u))
    return resp


@app.post("/api/logout")
def api_logout():
    drop_token(request.cookies.get("wt_token"))
    resp = make_response(jsonify(ok=True))
    resp.set_cookie("wt_token", "", max_age=0, path="/")
    return resp


@app.get("/api/me")
def api_me():
    user = current_user()
    return jsonify(username=user) if user else (jsonify(error="auth"), 401)


def _set_auth_cookie(resp, token):
    resp.set_cookie("wt_token", token, httponly=True, samesite="Lax",
                    secure=FORCE_HTTPS, max_age=TOKEN_TTL_DAYS * 86400, path="/")


# --- API sessoes (terminais) -------------------------------------------------

@app.get("/api/sessions")
def api_list():
    user = current_user()
    if not user:
        return jsonify(error="auth"), 401
    return jsonify(sessions=list_containers(user))


@app.post("/api/sessions")
def api_create():
    user = current_user()
    if not user:
        return jsonify(error="auth"), 401
    data = request.get_json(silent=True) or {}
    try:
        info = create_container(data.get("shell"), user)
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(info), 201


@app.post("/api/sessions/<cid>/kill")
def api_kill(cid):
    user = current_user()
    if not user:
        return jsonify(error="auth"), 401
    ok = remove_container(cid, user)
    return (jsonify(ok=True), 200) if ok else (jsonify(ok=False), 404)


# --- proxy WebSocket ---------------------------------------------------------

@sock.route("/t/<cid>/ws")
def terminal_ws(ws, cid):
    user = current_user()
    if not user or container_owner(cid) != user:
        ws.close()
        return
    # protege contra WebSocket cross-site (CSRF de WS)
    origin = request.headers.get("Origin", "")
    if origin and request.host not in origin:
        ws.close()
        return
    addr = container_addr(cid)
    if not addr:
        ws.close()
        return
    try:
        upstream = simple_websocket.Client(f"ws://{addr[0]}:{addr[1]}/ws")
    except Exception:
        ws.close()
        return

    alive = threading.Event()
    alive.set()

    def upstream_to_browser():
        try:
            while alive.is_set():
                data = upstream.receive()
                if data is None:
                    break
                ws.send(data)
        except Exception:
            pass
        finally:
            alive.clear()
            try:
                ws.close()
            except Exception:
                pass

    t = threading.Thread(target=upstream_to_browser, daemon=True)
    t.start()
    try:
        while alive.is_set():
            data = ws.receive()
            if data is None:
                break
            upstream.send(data)
    except Exception:
        pass
    finally:
        alive.clear()
        try:
            upstream.close()
        except Exception:
            pass


def init():
    """Checa o Podman e sobe o Postgres + schema. Roda tanto no `python3 app.py`
    (via main) quanto no import por um servidor WSGI como o gunicorn."""
    if podman(["--version"]).returncode != 0:
        raise SystemExit("Podman nao encontrado no host. Instale o podman.")
    ensure_postgres()


def main():
    init()
    shown = "localhost" if HOST in ("0.0.0.0", "127.0.0.1") else HOST
    print(f"Gerenciador em: http://{shown}:{PORT}  (bind {HOST})")
    print("Login obrigatorio. Cada terminal = 1 container Podman, so 127.0.0.1,")
    print("acessivel apenas pela conta dona (proxy autenticado). Ctrl+C para parar.")
    app.run(host=HOST, port=PORT, threaded=True)


# Sob um WSGI (gunicorn: `app:app`) o main() nao roda, entao a inicializacao
# precisa acontecer no import. No `python3 app.py` quem inicializa e o main(),
# evitando rodar duas vezes.
if __name__ != "__main__":
    init()


if __name__ == "__main__":
    main()
