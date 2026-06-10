#Author : JeffreyYAJ (https://github.com/JeffreyYAJ)
# Tema "Y-Kali" — visual estilo Kali Linux para oh-my-zsh.

HOSTNAME=$(hostname)
length=$(echo -n "$HOSTNAME" | wc -c)

setopt PROMPT_SUBST
get_ip() {
  echo "%{$fg[green]%}$(hostname -I | awk '{print $1}') %{$reset_color%}"
}

shorten_path() {
  local path=$(pwd)
  local path_length=${#path}

  if (( path_length > 45 )); then
    echo "...${path: -40}"
  else
    echo "$path"
  fi
}

function git_prompt_info() {
  local ref=$(git symbolic-ref --short HEAD 2> /dev/null)
  if [ -n "$ref" ]; then
    echo " %F{yellow}(git:$ref)%f"
  fi
}

if (( length < 15 )); then
  PROMPT=$'
┌─[%B%F{blue}'"${USER}"' '"${HOSTNAME}"'  $(shorten_path "$PWD")%f%b] [%F{green} 🛜  $(get_ip)%f] $(git_prompt_info)
└─%B%F$%f%b '
else
  PROMPT=$'
┌─[%F{blue}'"${USER}"'  %~%f] [%F{green} $(get_ip)%f] $(git_prompt_info)
└─%B%F$%f%b '
fi

RPROMPT='%(?..%F{red}Exit %?%f)'

ZSH_THEME_GIT_PROMPT_PREFIX="%F{magenta}git:(%F{red}"
ZSH_THEME_GIT_PROMPT_SUFFIX="%f"
ZSH_THEME_GIT_PROMPT_DIRTY="%F{yellow}*%f"
ZSH_THEME_GIT_PROMPT_CLEAN="%F{magenta})%f"
