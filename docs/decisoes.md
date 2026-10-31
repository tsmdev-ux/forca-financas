# Decisões técnicas

Cada decisão registra o contexto, a escolha e o que se abriu mão.

## 1. PWA em vez de app nativo

**Contexto:** o app precisa estar na tela inicial do Android e evoluir com frequência.

**Decisão:** PWA em JavaScript puro, sem etapa de build.

**Custo aceito:** sem publicação em loja e com menos integração com o sistema. As notificações vão pelo Telegram, onde já funcionam bem; um app Flutter exigiria reinstalar a cada atualização.

## 2. Parser local antes da IA

**Contexto:** a maior parte das mensagens é algo como `mercado 87`.

**Decisão:** um parser determinístico resolve o caso comum. O agente entra só quando ele não entende.

**Ganho:** resposta instantânea, custo zero e funcionamento sem rede. Parser e agente têm papéis separados, e testes garantem que frases de comando nunca virem lançamento.

## 3. A IA nunca faz contas

**Contexto:** um número errado em um app financeiro destrói a confiança nele.

**Decisão:** toda aritmética fica em `finance.py`. O agente acessa os valores por ferramentas e as instruções proíbem citar número que não veio delas.

**Ganho:** as regras são testáveis e não dependem do modelo. Trocar de provedor de IA não mudou nenhum cálculo.

## 4. SQLite em vez de Postgres

**Contexto:** um usuário, um servidor, poucas escritas.

**Decisão:** SQLite em modo WAL, com uma conexão por operação.

**Custo aceito:** não escala para múltiplos usuários nem para várias réplicas. Em troca, não há servidor de banco para operar, e o backup é uma cópia de arquivo.

## 5. Dinheiro em centavos inteiros

**Decisão:** `amount_cents INTEGER` em todo o sistema. Porcentagens e arredondamentos ficam em pontos explícitos do código.

**Motivo:** ponto flutuante acumula erro. Parcelas precisam somar exatamente o total da compra.

## 6. Extrato em vez de Open Finance

**Contexto:** a conexão automática com bancos parece a solução natural para a dificuldade de registrar.

**Decisão:** registro manual rápido, mais importação de OFX, CSV e PDF.

**Motivo:** o serviço tem custo mensal, exige contratar um agregador, e o dado chega com atraso. O alerta mais útil é o que vem *antes* do gasto. A conciliação cobre o que foi esquecido.

## 7. Long polling em vez de webhook

**Decisão:** o bot busca as mensagens no Telegram, em vez de recebê-las.

**Ganho:** não precisa de porta pública para o bot. O offset é gravado antes de tratar cada mensagem, então uma mensagem problemática não trava o bot em um laço.

## 8. Transcrição de voz no servidor

**Decisão:** faster-whisper com modelo pequeno, em CPU e carregado sob demanda.

**Motivo:** a voz não sai da máquina e não há custo por uso. O preço é cerca de 400 MB de memória a partir do primeiro áudio, com limite de 1 GB no container.

## 9. Backup criptografado pelo Telegram

**Contexto:** cópias só no servidor se perdem junto com ele.

**Decisão:** uma cópia semanal criptografada (AES-256-GCM, chave por scrypt) enviada ao chat do dono.

**Motivo:** fica fora do servidor sem criar outra conta nem credencial. A chave vem da senha do app, que não fica no arquivo.

**Custo aceito:** se a senha for perdida junto com o servidor, as cópias não abrem. Ao trocar a senha, as cópias antigas continuam abrindo só com a anterior.

## 10. Avisos com teto

**Decisão:** no máximo 3 avisos opcionais por dia, silêncio à noite e um botão para pausar.

**Motivo:** um app que incomoda é desinstalado. Vencimentos ficam fora do teto, porque são a razão de o aviso existir.

## 11. Provedor de IA substituível

**Decisão:** toda a chamada ao modelo fica em `ai.py`, sem SDK específico, usando a API de chat compatível.

**Ganho:** o app começou planejado para um provedor e foi trocado para o DeepSeek tocando só esse módulo e seus testes.

## O que o uso real ensinou

No primeiro uso, "ganhou 4.000.000 todo dia 5" virou uma conta fixa de R$ 4 milhões, e "exclui essa conta" com um valor virou um gasto. Os testes passavam, mas cobriam só frases previstas. Daí vieram três mudanças:

- Verbos de comando nunca geram lançamento e vão para o agente.
- Valores fora da realidade pedem confirmação antes de gravar.
- As telas foram reduzidas: uma ação principal em cada, com o detalhe a um toque de distância.

A lição é que um registro silencioso e errado custa mais do que uma pergunta a mais.
