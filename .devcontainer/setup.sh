#!/usr/bin/env bash
# Prepara o Codespace para rodar o gerenciador com Podman ROOTLESS.
# Roda uma vez, no postCreate do devcontainer.
set -euo pipefail

echo "==> Instalando Podman (rootless) e dependencias..."
sudo apt-get update -qq
sudo apt-get install -y -qq podman fuse-overlayfs uidmap slirp4netns

# Rootless precisa de faixas de subuid/subgid para o usuario.
USER_NAME="$(id -un)"
if ! grep -q "^${USER_NAME}:" /etc/subuid; then
  echo "${USER_NAME}:100000:65536" | sudo tee -a /etc/subuid >/dev/null
fi
if ! grep -q "^${USER_NAME}:" /etc/subgid; then
  echo "${USER_NAME}:100000:65536" | sudo tee -a /etc/subgid >/dev/null
fi

# Driver de storage: overlay+fuse-overlayfs (rapido) se houver /dev/fuse;
# senao cai pra vfs (lento, mas funciona em qualquer lugar).
mkdir -p ~/.config/containers
if [ -e /dev/fuse ]; then
  echo "==> Storage: overlay + fuse-overlayfs"
  cat > ~/.config/containers/storage.conf <<'EOF'
[storage]
driver = "overlay"
[storage.options.overlay]
mount_program = "/usr/bin/fuse-overlayfs"
EOF
else
  echo "==> /dev/fuse ausente -> usando storage vfs (mais lento)"
  cat > ~/.config/containers/storage.conf <<'EOF'
[storage]
driver = "vfs"
EOF
fi

# Limpa estado parcial de podman, se houver.
podman system reset -f >/dev/null 2>&1 || true

echo "==> Verificando o Podman..."
podman info >/dev/null && echo "    Podman OK"

echo "==> Instalando dependencias do gerenciador (requirements.txt)..."
pip install --user --no-warn-script-location -r requirements.txt

cat <<'MSG'

==========================================================
 Pronto. Para subir o app:

   python3 app.py

 1) Defina os segredos antes (Codespaces Secrets ou .env):
      SECRET_KEY, PG_PASSWORD, ADMIN_USER, ADMIN_PASSWORD
      (gere a chave:  python3 -c "import secrets;print(secrets.token_urlsafe(48))")
 2) Na aba PORTS, deixe a 8765 como "Public" para abrir fora.
==========================================================
MSG
