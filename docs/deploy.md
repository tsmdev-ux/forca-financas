# Deploy

Pré-requisitos: um servidor com Docker e Compose, acesso por SSH, um domínio apontando para ele e um proxy reverso com HTTPS. Os exemplos usam Caddy.

Recursos: cerca de 1 GB de RAM livre, com o modelo de voz carregado.

## 1. Credenciais

| Item | Onde obter | Obrigatório |
|---|---|---|
| Token do bot | [@BotFather](https://t.me/BotFather), comando `/newbot` | Para bot e avisos |
| Chave do DeepSeek | [platform.deepseek.com](https://platform.deepseek.com) | Só para conversa livre e leitura de PDF e foto |

## 2. Configuração local

```bash
cp .deploy.env.example .deploy.env
```

Ajuste os valores. Esse arquivo fica fora do git.

| Variável | Descrição |
|---|---|
| `FORCA_HOST` | Destino SSH, como `usuario@servidor` |
| `FORCA_DOMAIN` | Domínio do app |
| `FORCA_EDGE_NETWORK` | Rede Docker em que o proxy reverso está |
| `FORCA_REMOTE_DIR` | Pasta no servidor |
| `FORCA_CADDY_DIR`, `FORCA_CADDY_CONTAINER` | Opcionais: fazem o deploy adicionar o bloco a um Caddy existente, com backup e validação antes do reload |

Sem as duas últimas, adicione o bloco manualmente, como em [`deploy/Caddyfile.example`](../deploy/Caddyfile.example).

## 3. Publicar

```bash
./deploy.sh
./set-secrets.sh
```

O `set-secrets.sh` pede senha e tokens sem exibi-los. Eles vão por SSH para o `.env` do servidor, com permissão 600, e nunca passam pela linha de comando.

## 4. Instalar no Android

1. Abra o domínio no Chrome e entre com a senha.
2. Toque em **Instalar** ou em **⋮ → Instalar app**.
3. Toque em **Conectar** para parear o Telegram. O primeiro chat pareado vira o dono.

## Operação

```bash
ssh servidor 'docker logs --tail=50 forca-app'     # ver logs
ssh servidor 'ls forca/data/backups'               # cópias diárias, 14 dias
```

### Restaurar um backup

As cópias diárias ficam em `data/backups`. A cópia semanal criptografada chega pelo Telegram, como `forca-AAAA-MM-DD.forca`:

```bash
python -m forca.restore forca-2026-11-01.forca restaurado.db
```

O comando pede a senha do app da época do backup. Com o container parado, substitua `data/forca.db` pelo arquivo restaurado e suba de novo.

## Variáveis do app

| Variável | Padrão | Descrição |
|---|---|---|
| `FORCA_DOMAIN` | | Domínio público |
| `FORCA_EDGE_NETWORK` | | Rede Docker do proxy |
| `FORCA_PASSWORD` | | Senha do app; sem ela, o login fica bloqueado |
| `FORCA_SECRET` | | Assina as sessões |
| `FORCA_PAIR_CODE` | | Código de pareamento do Telegram |
| `TELEGRAM_BOT_TOKEN` | | Sem ele, bot e avisos ficam desligados |
| `DEEPSEEK_API_KEY` | | Sem ela, conversa e leitura de PDF e foto ficam desligadas |
| `FORCA_MODEL` | `deepseek-flash` | Modelo de IA |
| `FORCA_TZ` | `America/Sao_Paulo` | Fuso dos avisos |
| `FORCA_WHISPER_MODEL` | `base` | Modelo de voz; `tiny` usa menos memória |
