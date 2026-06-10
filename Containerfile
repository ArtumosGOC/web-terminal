# Terminal Web — imagem Debian 12 com Python 3 + zsh (tema Y-Kali) + bash + PowerShell.
# O shell e escolhido em runtime pela variavel TERM_SHELL (zsh | bash | pwsh).
FROM debian:bookworm-slim

ARG INSTALL_PWSH=1

ENV DEBIAN_FRONTEND=noninteractive \
    HOST=0.0.0.0 \
    PORT=8765 \
    TERM_SHELL=zsh \
    HOME=/root

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-pip ca-certificates curl wget gnupg apt-transport-https \
      less nano vim-tiny procps ncurses-term \
      zsh git net-tools lolcat \
 && if [ "$INSTALL_PWSH" = "1" ]; then \
      wget -q https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
        -O /tmp/ms-prod.deb \
      && dpkg -i /tmp/ms-prod.deb \
      && apt-get update \
      && apt-get install -y --no-install-recommends powershell \
      && rm -f /tmp/ms-prod.deb \
      || echo "AVISO: instalacao do pwsh falhou; somente bash disponivel"; \
    fi \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# oh-my-zsh + tema Y-Kali (estilo Kali Linux)
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
COPY zsh/y-kali.zsh-theme /root/.oh-my-zsh/custom/themes/y-kali.zsh-theme
COPY zsh/zshrc /root/.zshrc

WORKDIR /app
COPY requirements-container.txt /app/
RUN pip install --no-cache-dir --break-system-packages -r requirements-container.txt
COPY server.py /app/

EXPOSE 8765
CMD ["python3", "server.py"]
