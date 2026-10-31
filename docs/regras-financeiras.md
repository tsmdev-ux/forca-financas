# Regras financeiras

Todas as regras estão em [`forca/finance.py`](../forca/finance.py) e são cobertas por testes.

## O limite do dia

Cada real pertence ao orçamento de um mês (`budget_month`):

```
sobra para gastar = renda − contas fixas − dívidas − metas − parcelas antigas − estouro do mês anterior
limite de hoje    = (sobra − gasto até ontem) ÷ dias restantes, contando hoje
ainda cabe hoje   = limite de hoje − gasto de hoje
```

**Exemplo:** renda de R$ 5.000, aluguel de R$ 1.500 e internet de R$ 100. Em 11 de novembro restam 20 dias e a sobra é de R$ 3.400, então o limite do dia é **R$ 170**.

Um mercado de R$ 50 deixa R$ 120 para hoje. O limite de hoje não muda ao longo do dia; o que muda é quanto ainda cabe, e o de amanhã é recalculado: (3.400 − 50) ÷ 19 = R$ 176.

Se você gasta menos, os próximos dias ganham folga. Se gasta mais, diminuem. Por isso o número continua verdadeiro sem exigir disciplina perfeita.

## Valor real e previsto

Enquanto uma conta ou renda não foi lançada, vale o valor previsto. Quando é lançada, vale o real. `aluguel 1500` é reconhecido como a conta fixa "Aluguel", dentro de uma faixa de valor, e **não conta duas vezes**.

## Cartão de crédito

Uma compra no cartão pesa **no mês em que foi feita**, não no mês da fatura. Pagar a fatura é só transferência, não um gasto novo. Sem essa regra, a fatura vira surpresa e o limite do dia passa semanas sendo falso.

A fatura que recebe a compra depende de duas datas:

| Cartão | Compra | Vence em |
|---|---|---|
| Fecha dia 3, vence dia 10 | 2 de novembro | novembro |
| Fecha dia 3, vence dia 10 | 3 de novembro | dezembro |
| Fecha dia 25, vence dia 5 | 20 de novembro | dezembro |
| Fecha dia 25, vence dia 5 | 26 de novembro | janeiro |

Dia 31 em um mês mais curto cai no último dia, como fazem os bancos.

### Parcelas

Cada parcela é uma linha, e o centavo que sobra da divisão fica na primeira: R$ 1.000 em 3x viram 333,34 + 333,33 + 333,33. A primeira pesa como gasto do mês; as seguintes entram como **compromisso** dos meses futuros e já reduzem a sobra deles.

### A fatura que já existia

Quem começa a usar o app já tem uma fatura em aberto. Ela entra como compromisso do mês em que vence, para não ser confundida com gasto novo.

## Estouro do mês anterior

Se um mês fecha negativo, o déficit passa para o seguinte. **Sobra não passa:** uma sobra no papel pode não estar na conta, então nunca aumenta o que o app diz que dá para gastar.

O mês em que o uso começou pela metade não gera déficit, porque a renda e as contas dele vieram de antes do app. Pelo mesmo motivo, nos últimos 3 dias desse mês o app não mostra limite: o número não teria significado.

## Dívidas

A simulação (`simulate_debts`) roda mês a mês: soma os juros, paga os mínimos e aplica o restante no alvo da estratégia. Quando uma dívida termina, o que ela consumia passa para a próxima.

| Estratégia | Ordem | Quando faz sentido |
|---|---|---|
| Maior juro antes | Maior taxa primeiro | Paga menos juros no total |
| Menor dívida antes | Menor saldo primeiro | Dá vitórias mais rápidas |

**Exemplo:** R$ 1.000 a 10% ao mês, pagando R$ 600: 1.100 − 600 = 500; 550 − 550 = 0. Termina em 2 meses, com R$ 150 de juros.

O plano é considerado inviável quando não quita em 30 anos. Se o pagamento mínimo é igual ou menor que os juros, o app avisa que aquela dívida não diminui. Dívidas em atraso vêm antes de qualquer estratégia.

No dia 1º, um mês de juros é somado ao saldo. Dívidas cadastradas há menos de 20 dias ficam de fora, porque o saldo informado já está atualizado.

## Metas

Guardar **não é gastar**, mas o dinheiro tem destino: o valor mensal planejado sai da sobra. No mês atual e nos futuros, conta o maior entre o planejado e o já guardado; em meses passados, só o que foi guardado de fato.

Com prazo e sem valor mensal, o app divide o que falta pelos meses até o prazo, arredondando para cima. A sugestão de reserva de emergência é de 3 meses de contas fixas e parcelas de dívida.

## Freio de impulso

Para `posso comprar X?`, o veredito é calculado, não opinado:

- **Não cabe:** o mês fecharia negativo, ou ele já não fecha.
- **Eu esperaria:** passa do que cabe hoje e equivale a 2 dias ou mais de limite; ou existe dívida a 3% ao mês ou mais e a compra é maior que o limite do dia.
- **Cabe:** nos demais casos.

A resposta mostra o efeito no limite diário e, se houver dívida, quanto aquele valor custaria em juros em 12 meses.

## Importação de valores

`1.200`, `1.200,50`, `87,50`, `87.50`, `2k` e `2 mil` são lidos corretamente. Frases com mais de um número ou com verbos de comando (`exclui`, `corrige`, `muda`) nunca viram lançamento: vão para o agente. Valores acima de 3 vezes a renda, com mínimo de R$ 20 mil, pedem confirmação.
