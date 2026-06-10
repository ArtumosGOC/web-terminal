# Terminal Web — multiusuário, com contas e isolamento por conta

Terminal de verdade no navegador, com **login por conta**. Cada terminal roda em
um **container Podman isolado** e fica **vinculado a uma única conta**: só quem o
criou consegue ver, abrir ou encerrar.

- **Gerenciador (host):** [Flask](https://flask.palletsprojects.com/) — login/registro,
  orquestra os containers e faz **proxy autenticado** do WebSocket até cada terminal.
- **Terminal (container):** Flask + [flask-sock](https://pypi.org/project/flask-sock/)
  com **PTY real** (vim, nano, htop, REPLs, prompts do apt funcionam).
- **Contas e sessões:** PostgreSQL em container separado (acesso via `psycopg`,
  consultas parametrizadas).
- **Frontend:** [xterm.js](https://xtermjs.org/).

---

## Como funciona (arquitetura)

```
        Navegador
           │  (HTTP + WebSocket, ÚNICA porta pública)
           ▼
    app.py  ── Flask (host) ───────────────────────────────────┐
      • /login, /register, sessão por token (cookie HttpOnly)   │
      • /api/sessions: cria/lista/remove containers (Podman)    │
      • /t/<id>/ws: PROXY do WebSocket, confere dono ───────────┼──► container Podman
           │                                                    │     127.0.0.1:aleatória
           ▼                                                    │     (Flask + PTY real)
      PostgreSQL (container) ── psycopg ──► usuários + tokens   │
                                                                └──► (nunca exposto na LAN)
```

Pontos-chave:

1. **Cada terminal é um container Podman** próprio (`podman run` da imagem
   `web-terminal`), com sistema de arquivos e processos isolados.
2. O dono fica gravado no **label `wt-owner`** do container — o `podman ps` é a
   fonte da verdade do que está rodando (sobrevive a reinício do gerenciador).
3. Os containers são publicados **só em `127.0.0.1`**, em porta aleatória. O
   navegador **nunca** fala direto com eles: todo acesso passa pelo proxy do
   Flask, que exige login **e** confere se a conta é dona daquele terminal.
4. **Login obrigatório.** Sessão por **token guardado no Postgres** — o logout
   apaga o token no banco (revogação real, mesmo se o cookie vazar).

---

## Pré-requisitos

- **Podman** instalado e funcionando no host.
- **Python 3.10+** no host (para o gerenciador).
- Acesso à internet na primeira execução (baixa a imagem do Postgres e, no build
  da imagem do terminal, instala pacotes).

> O gerenciador roda **no host** (não em container) porque ele precisa falar com
> o Podman para criar os outros containers.

---

## Passo a passo

### 1. Dependências do gerenciador

```bash
python3 -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configuração

```bash
cp env.example .env
```

Edite o `.env`. No mínimo, defina:

```bash
# gere uma chave forte:
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

- `SECRET_KEY` — cole a chave gerada (assina cookies; obrigatória em produção).
- `PG_PASSWORD` — senha do banco.
- `ADMIN_USER` / `ADMIN_PASSWORD` — conta criada automaticamente na 1ª execução
  (deixe em branco para não criar nenhuma e usar só o cadastro pela tela).
- `MANAGER_HOST` — `127.0.0.1` (só esta máquina) ou `0.0.0.0` (acessível na LAN).
- `ALLOW_REGISTER` — `true`/`false` para liberar o cadastro na tela de login.

### 3. Subir o gerenciador

```bash
python3 app.py
```

Na primeira vez ele: builda a imagem `web-terminal`, sobe o container do
PostgreSQL (volume nomeado, dados persistem), cria o schema e a conta admin.

### 4. Usar

1. Abra `http://localhost:8765` (ou `http://<ip-da-lan>:8765` se usou `0.0.0.0`).
2. Entre com a conta admin, ou crie uma conta na aba **Criar conta**.
3. No gerenciador, escolha o shell (zsh/bash/sh/pwsh) e clique **+ Criar terminal**.
4. Cada **Abrir** leva ao terminal (`/t/<id>`), que é só seu.
5. **Remover** encerra e apaga o container.

---

## Variáveis do `.env`

| Variável | Padrão | Para quê |
|----------|--------|----------|
| `MANAGER_HOST` | `0.0.0.0` | Bind do gerenciador (`127.0.0.1` = só local). |
| `MANAGER_PORT` | `8765` | Porta pública do gerenciador. |
| `SECRET_KEY` | — | Assina cookies. **Obrigatória.** |
| `FORCE_HTTPS` | `false` | Marca cookies como `Secure` (use atrás de HTTPS). |
| `ALLOW_REGISTER` | `true` | Permite cadastro pela tela de login. |
| `ADMIN_USER` / `ADMIN_PASSWORD` | — | Conta semeada na 1ª execução. |
| `IMAGE` | `web-terminal` | Nome da imagem do terminal. |
| `PG_CONTAINER` | `web-terminal-db` | Nome do container do Postgres. |
| `PG_IMAGE` | `postgres:16-alpine` | Imagem do Postgres. |
| `PG_USER` / `PG_PASSWORD` / `PG_DB` | `webterminal` | Credenciais do banco. |
| `PG_PORT` | `5432` | Porta do Postgres (publicada só em `127.0.0.1`). |
| `PG_VOLUME` | `web-terminal-pgdata` | Volume onde os dados persistem. |

---

## Segurança

- **Terminais vinculados à conta:** containers só em `127.0.0.1`; acesso apenas
  pelo proxy autenticado, que confere login + dono (label `wt-owner`).
- **Senhas:** hash com `werkzeug.security` (scrypt/pbkdf2). Nunca em texto puro.
- **SQL:** `psycopg` com parâmetros (`%s`) — sem injeção.
- **Sessões revogáveis:** token no Postgres; logout apaga o token.
- **CSRF:** cookie `csrf` + header `X-CSRF-Token` exigido em toda escrita.
- **WebSocket:** confere `Origin` (bloqueia WS cross-site) além de login + dono.
- **Cabeçalhos:** `Content-Security-Policy` (sem JS inline), `X-Frame-Options`,
  `X-Content-Type-Options`, `Referrer-Policy`; cookies `HttpOnly`/`SameSite=Lax`.
- **Anti-bruteforce:** throttle de login por IP.

> **Produção:** rode atrás de HTTPS (proxy reverso) com `FORCE_HTTPS=true`. O
> `python3 app.py` usa o servidor de desenvolvimento do Flask; para carga real,
> sirva com um WSGI que suporte WebSocket, por exemplo:
> `gunicorn -k gthread --threads 8 -b 0.0.0.0:8765 app:app`.

---

## Seleção de shell

`zsh` (padrão, com oh-my-zsh e tema Y-Kali), `bash`, `sh`, `pwsh` (PowerShell
Core). Escolhido por terminal na hora de criar; o gerenciador traduz para as
variáveis `TERM_SHELL`/`TYPE_SHELL` que o container entende.

---

## Estrutura

| Caminho | Papel |
|---------|-------|
| `app.py` | Gerenciador Flask (host): auth, Podman, Postgres, proxy WS. |
| `templates/` | Páginas (`login`, `manager`, `terminal`) renderizadas por Jinja. |
| `static/` | JS do frontend (separado do HTML por causa da CSP). |
| `server.py` | App de terminal único (Flask + PTY) que roda **dentro** do container. |
| `Containerfile` | Imagem Debian 12 + Python + zsh/bash/pwsh + Flask. |
| `requirements.txt` | Dependências do gerenciador (host). |
| `requirements-container.txt` | Dependências do app do container. |
| `zshrc`, `y-kali.zsh-theme` | Shell zsh e banner dentro do container. |
| `env.example` | Modelo de configuração. |

---

## Operação (Podman)

```bash
# terminais ativos (de todas as contas)
podman ps --filter label=web-terminal-session=1

# logs do banco
podman logs web-terminal-db

# parar tudo (os dados do Postgres ficam no volume)
podman rm -f web-terminal-db
podman ps -a --filter label=web-terminal-session=1 -q | xargs -r podman rm -f

# criar a imagem use
podman build -t web-terminal -f Containerfile .
```

O gerenciador pode ser parado e reiniciado à vontade: ele relê o estado do
Podman e do Postgres. Containers de terminal continuam rodando enquanto não forem
removidos.

---

## Limitações conhecidas

- Reabrir um terminal reinicia a **tela** do PTY (o container e seus arquivos
  continuam; o que estava desenhado na tela não é restaurado).
- O gerenciador precisa rodar no mesmo host do Podman.
