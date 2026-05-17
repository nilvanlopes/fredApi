# Requisitos do Sistema de Lista do Volei Frederico

## Objetivo

O sistema deve organizar a lista mensal de assinantes, o controle de pagamento e a lista de presenca dos jogos de volei das quartas-feiras.

O sistema deve diferenciar assinantes e nao assinantes, aplicar a regra de prioridade ate as 16h de quarta-feira e controlar quem entra na lista principal ou na lista de espera.

## Valores configuraveis

Os seguintes valores devem ser configuraveis:

- Valor mensal do assinante: `R$ 12,50`.
- Valor avulso por quarta para nao assinante: `R$ 7,50`.
- Limite mensal de assinantes: `24`.
- Capacidade maxima de jogadores por quarta-feira.
- Horario de fechamento da prioridade dos assinantes: `16h de quarta-feira`.

## Regras de assinantes

- A lista de assinantes e mensal.
- O sistema deve permitir ate 24 assinantes por mes.
- Cada assinante deve ter nome e status de pagamento no mes.
- Um assinante marcado como pago deve aparecer com indicador de pagamento, como `✅`.
- Um assinante que pagou a mensalidade pode jogar todas as quartas do mes sem pagar valor avulso.
- Um assinante que ainda nao pagou pode existir na lista, mas seu status deve deixar claro que o pagamento esta pendente.

Exemplo:

```text
LISTA DE ASSINANTES DO MES DE ABRIL
1. pyu ✅
2. Daniel ✅
3. Grid ✅
4. Jessica
5. Klesley ✅
```

## Regras de nao assinantes e convidados

- Quem nao e assinante deve pagar o valor avulso para jogar em uma quarta-feira.
- O valor avulso inicial e `R$ 7,50`, mas deve ser configuravel.
- Antes das 16h de quarta-feira, nao assinantes nao entram diretamente na lista principal.
- Antes das 16h, nao assinantes entram em uma lista de espera chamada `Convidados`.
- O sistema deve permitir informar quem convidou o nao assinante.
- O nome do convidado pode aparecer no formato `Nome (conv. Assinante)`.

Exemplo:

```text
Convidados
1. Thyago (conv. Viegas)
2. Flavio (conv. pyu)
3. Kruts (conv. pyu)
```

## Regras da lista de presenca antes das 16h

- Cada quarta-feira deve ter uma lista de presenca propria.
- A lista deve identificar a data do jogo.
- Antes das 16h de quarta-feira, assinantes tem prioridade.
- Assinante que colocar o nome na lista principal ate as 16h tem lugar garantido, respeitando a capacidade maxima configurada.
- Convidados e nao assinantes que colocarem nome antes das 16h devem ficar na lista de espera.
- A lista de espera deve manter a ordem de entrada.

Exemplo antes das 16h:

```text
LISTA VOLEI FREDERICO 22/04
1. pyu
2. Joao Victor
3. Gomes
4. Murilo
5. Guilherme V
6. Viegas
7. Tiago
8. Ramequi
9. Kaka
10. Daniel
11. Grid
12. Heitor

Convidados
1. Thyago (conv. Viegas)
2. Flavio (conv. pyu)
3. Kruts (conv. pyu)
4. Maldito (conv. pyu)
5. Jordan (conv. pyu)
```

## Regra das 16h de quarta-feira

- As 16h de quarta-feira, a prioridade exclusiva dos assinantes termina.
- Nesse horario, o sistema deve verificar quantas vagas ainda existem na lista principal.
- Se houver vagas, os nomes da lista de espera devem subir para a lista principal na ordem em que entraram.
- Depois que a lista de espera existente for processada, qualquer nova entrada deve seguir ordem de chegada.
- Depois das 16h, assinantes e nao assinantes entram na mesma ordem de chegada.
- Assinante que nao colocou nome na lista ate as 16h nao tem mais vaga garantida naquela quarta.
- Convidado que subir para a lista principal continua devendo o valor avulso da quarta.

Exemplo depois das 16h:

```text
LISTA VOLEI FREDERICO 22/04
1. pyu
2. Joao Victor
3. Gomes
4. Murilo
5. Guilherme V
6. Viegas
7. Tiago
8. Ramequi
9. Kaka
10. Daniel
11. Grid
12. Heitor
13. Jessica
14. Thyago (conv. Viegas)
15. Flavio (conv. pyu)
16. Kruts (conv. pyu)
17. Maldito (conv. pyu)
18. Jordan (conv. pyu)
19. Henrique (conv. Viegas)
20. Ellissandro (conv. pyu)
21. Lauro (conv. pyu)
22. Guilherme (conv. Gui)
```

## Regras de pagamento

- O sistema deve registrar pagamento mensal de cada assinante.
- O sistema deve registrar pagamento avulso de cada nao assinante por quarta-feira.
- O valor mensal e o valor avulso devem ser configuraveis.
- A alteracao dos valores deve afetar novos registros, sem apagar historico anterior.
- O sistema deve permitir identificar quem esta pago e quem esta pendente.

## Cenarios de aceite

- Dado que uma pessoa e assinante do mes, quando ela pagar a mensalidade, entao deve aparecer como paga na lista de assinantes.
- Dado que um assinante colocou o nome antes das 16h de quarta, quando houver capacidade disponivel, entao ele deve ficar na lista principal com vaga garantida.
- Dado que um convidado colocou o nome antes das 16h de quarta, entao ele deve ficar na lista de espera.
- Dado que chegou 16h de quarta e existem vagas abertas, quando houver pessoas na lista de espera, entao elas devem subir para a lista principal na ordem de entrada.
- Dado que ja passou das 16h de quarta, quando qualquer pessoa pedir para entrar na lista, entao ela deve entrar por ordem de chegada, sendo assinante ou nao.
- Dado que um nao assinante entrou na lista principal, entao o sistema deve registrar que ele deve pagar o valor avulso da quarta.
- Dado que os valores configuraveis forem alterados, entao o sistema deve usar os novos valores para novos registros.

