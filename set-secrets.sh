#!/usr/bin/env bash
# Grava senha e tokens no servidor sem passar pela linha de comando nem pelo histórico.
# Enter em branco mantém o valor atual.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .deploy.env ] && . ./.deploy.env
: "${FORCA_HOST:?defina FORCA_HOST em .deploy.env}"
REMOTE_DIR="${FORCA_REMOTE_DIR:-forca}"

read -r -s -p "Senha para entrar no app: " PASSWORD; echo
read -r -s -p "Token do bot (@BotFather): " TELEGRAM; echo
read -r -s -p "Chave do DeepSeek: " DEEPSEEK; echo

printf 'FORCA_PASSWORD=%s\nTELEGRAM_BOT_TOKEN=%s\nDEEPSEEK_API_KEY=%s\n' "$PASSWORD" "$TELEGRAM" "$DEEPSEEK" \
  | ssh "$FORCA_HOST" "set -e
    cd $REMOTE_DIR
    while IFS= read -r line; do
      key=\"\${line%%=*}\"
      [ -n \"\${line#*=}\" ] || continue
      { grep -v \"^\$key=\" .env || true; printf '%s\n' \"\$line\"; } > .env.tmp
      cat .env.tmp > .env
      rm -f .env.tmp
    done
    chmod 600 .env
    docker compose up -d"
echo "Pronto. O app reiniciou com os novos valores."
