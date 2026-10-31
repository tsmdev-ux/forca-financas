#!/usr/bin/env bash
# Instala ou atualiza a Força em um servidor com Docker e um proxy reverso.
# As variáveis vêm de .deploy.env (fora do git; ver .deploy.env.example).
set -euo pipefail
cd "$(dirname "$0")"

[ -f .deploy.env ] && . ./.deploy.env
: "${FORCA_HOST:?defina FORCA_HOST em .deploy.env}"
: "${FORCA_DOMAIN:?defina FORCA_DOMAIN em .deploy.env}"
: "${FORCA_EDGE_NETWORK:?defina FORCA_EDGE_NETWORK em .deploy.env}"
REMOTE_DIR="${FORCA_REMOTE_DIR:-forca}"

remote() { ssh -o BatchMode=yes "$FORCA_HOST" "$@"; }

echo "→ Preparando $FORCA_HOST:$REMOTE_DIR"
remote "mkdir -p $REMOTE_DIR/data && chown 1000 $REMOTE_DIR/data && umask 077 && cd $REMOTE_DIR && [ -f .env ] || cat > .env <<CONF
FORCA_DOMAIN=$FORCA_DOMAIN
FORCA_EDGE_NETWORK=$FORCA_EDGE_NETWORK
FORCA_PASSWORD=
FORCA_SECRET=\$(openssl rand -hex 32)
FORCA_PAIR_CODE=\$(openssl rand -hex 8)
TELEGRAM_BOT_TOKEN=
DEEPSEEK_API_KEY=
FORCA_MODEL=deepseek-flash
FORCA_TZ=America/Sao_Paulo
FORCA_WHISPER_MODEL=base
CONF"
remote "cd $REMOTE_DIR && grep -q '^FORCA_EDGE_NETWORK=' .env || echo 'FORCA_EDGE_NETWORK=$FORCA_EDGE_NETWORK' >> .env"

echo "→ Enviando arquivos"
COPYFILE_DISABLE=1 tar czf - --exclude='__pycache__' --exclude='*.pyc' forca Dockerfile docker-compose.yml requirements.txt \
  | remote "tar xzf - --no-same-owner -C $REMOTE_DIR"

echo "→ Construindo e subindo o container"
remote "cd $REMOTE_DIR && docker compose up -d --build --remove-orphans"

# Com um Caddy compartilhado, FORCA_CADDY_DIR e FORCA_CADDY_CONTAINER adicionam o bloco do app.
if [ -n "${FORCA_CADDY_DIR:-}" ] && [ -n "${FORCA_CADDY_CONTAINER:-}" ]; then
  if remote "grep -qF '$FORCA_DOMAIN {' $FORCA_CADDY_DIR/Caddyfile"; then
    echo "→ O Caddy já conhece $FORCA_DOMAIN"
  else
    echo "→ Adicionando $FORCA_DOMAIN ao Caddy"
    remote "set -e
      cd $FORCA_CADDY_DIR
      cp -p Caddyfile Caddyfile.bak-\$(date +%Y%m%d-%H%M%S)
      { cat Caddyfile; printf '\n$FORCA_DOMAIN {\n    reverse_proxy forca-app:8000\n}\n'; } > /tmp/Caddyfile.forca
      docker exec -i $FORCA_CADDY_CONTAINER sh -c 'cat > /tmp/Caddyfile.novo && caddy validate --adapter caddyfile --config /tmp/Caddyfile.novo' < /tmp/Caddyfile.forca
      # O arquivo é montado direto no container: precisa gravar por cima, sem trocar o inode.
      cat /tmp/Caddyfile.forca > Caddyfile
      rm -f /tmp/Caddyfile.forca
      docker exec $FORCA_CADDY_CONTAINER caddy reload --adapter caddyfile --config /etc/caddy/Caddyfile"
  fi
fi

echo "→ Esperando o HTTPS"
for _ in $(seq 1 36); do
  if curl -fsS -o /dev/null --max-time 5 "https://$FORCA_DOMAIN/manifest.webmanifest"; then
    echo "Pronto: https://$FORCA_DOMAIN"
    exit 0
  fi
  sleep 5
done
echo "O app não respondeu em https://$FORCA_DOMAIN. Veja: ssh $FORCA_HOST 'docker logs --tail=30 forca-app'"
exit 1
