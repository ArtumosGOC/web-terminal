# Rodar no GitHub Codespaces

Este Codespace roda o **gerenciador** ([app.py](../app.py)) com **Podman rootless**
lá dentro — a arquitetura original (1 container por terminal) fica intacta.

## 1. Abrir o Codespace

No GitHub: **Code ▸ Codespaces ▸ Create codespace on main**.
O `postCreate` instala Podman e as dependências automaticamente
(veja [setup.sh](setup.sh)).

## 2. Definir os segredos

Não comite segredos. Use **Codespaces Secrets** (recomendado) ou um `.env` local.

- GitHub ▸ Settings ▸ Codespaces ▸ **Secrets**, ou no repo:
  Settings ▸ Secrets and variables ▸ **Codespaces**.
- Crie:
  - `SECRET_KEY` — `python3 -c "import secrets;print(secrets.token_urlsafe(48))"`
  - `PG_PASSWORD` — senha do Postgres
  - `ADMIN_USER` / `ADMIN_PASSWORD` — conta inicial (opcional)

As variáveis não-secretas (`MANAGER_HOST=0.0.0.0`, `FORCE_HTTPS=true`,
`MANAGER_PORT=8765`, `ALLOW_REGISTER=true`) já vêm no
[devcontainer.json](devcontainer.json).

> `FORCE_HTTPS=true` é correto aqui: a URL pública do Codespaces é HTTPS, então
> os cookies `Secure` funcionam normalmente.

## 3. Subir o app

```bash
python3 app.py
```

Na primeira vez ele builda a imagem `web-terminal` e sobe o Postgres
(containers Podman dentro do Codespace) — pode demorar alguns minutos.

## 4. Acessar de fora

Aba **PORTS** ▸ porta **8765** ▸ botão direito ▸ **Port Visibility ▸ Public**.
Copie a URL `https://...-8765.app.github.dev` e abra no navegador.

## Limitações

- O Codespace **dorme** após ~30 min sem uso e tem limite de horas/mês grátis.
  Bom para demo/teste; não para ficar 24/7 no ar.
- Se o build da imagem reclamar de espaço (storage `vfs`), crie o Codespace com
  mais disco (Machine type) ou rode `podman system prune -af`.
