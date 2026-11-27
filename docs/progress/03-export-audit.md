# Auditoria da exportação do grupo

- [x] Ler a exportação local e conferir o formato dos cabeçalhos e das mensagens multilinha.
- [x] Contar as listas reconhecidas pelas regras atuais, as referências cobertas e os empates de horário.
- [x] Documentar as lacunas e os casos que exigem confirmação antes de vincular uma entrada.

## Cobertura

O arquivo UTF-8 tem 731.180 bytes, 33.023 linhas e 5.856 registros reconhecidos pelo parser de exportação. Há 5.766 registros com campo de remetente preenchido. O primeiro registro com remetente é de 09/12/2024 e o último é de 04/08/2026 às 23h52, considerando `America/Sao_Paulo`. Entre 19/02/2025 e 22/10/2025 há um hiato de 245 dias entre registros com remetente e corpo. A data mais antiga do arquivo, 20/10/2024, pertence ao aviso de criação do grupo.

| Tipo | Mensagens aceitas pelas regras | Referências | Intervalo de referência |
| --- | ---: | ---: | --- |
| Mensal | 375 | 13 meses | 12/2024 a 08/2026 |
| Semanal | 1.170 | 50 partidas | 11/12/2024 a 05/08/2026 |

Os meses reconhecidos são dezembro de 2024, janeiro e fevereiro de 2025, novembro e dezembro de 2025 e janeiro a agosto de 2026. Os totais mostram a cobertura do arquivo com o classificador por regras. O cruzamento com as entradas existentes é necessário para contar quantos vínculos podem ser recuperados.

## Identidade e ordem das mensagens

- Os cabeçalhos do export registram data, horário com precisão de minuto, remetente conforme exibido pelo WhatsApp e corpo. O arquivo não traz ID do WAHA nem identificador estável do remetente. Use data e hora para ordenar o histórico e a posição no export para desempatar mensagens da mesma referência no mesmo minuto. Há 42 mensagens mensais em 18 grupos de empate e 119 semanais em 57 grupos. O arquivo também tem cinco inversões entre horários consecutivos.
- Entre as 1.545 mensagens aceitas, não há duas com a mesma combinação de timestamp, remetente e texto. Há 40 repetições de corpo dentro da mesma referência em ocorrências distintas. Mensagens com o mesmo texto ainda podem representar envios separados.
- O parser separa as linhas do cabeçalho, preserva as quebras internas e aplica `.strip()` ao corpo. Neste arquivo, a remoção de espaços nas bordas não alterou o corpo de nenhuma das 1.545 mensagens aceitas. Há 116 listas reconhecidas com o marcador `<Mensagem editada>`. O arquivo contém a versão visível na exportação, sem as versões anteriores à edição. Mensagens apagadas e mídia omitida aparecem apenas como marcadores.
- O fingerprint original usa `chat_id`, timestamp em ISO com fuso, remetente e texto. Se o mesmo export tiver sido importado antes, uma coincidência de fingerprint no chat correto permite recuperar o corpo usando a identidade e a referência já registradas. A exportação não permite afirmar que uma mensagem enviada no mesmo minuto foi um evento WAHA específico.

## Casos para revisão

- O parser semanal normaliza a data para quarta-feira. Em 56 candidatos com data explícita, o dia ou mês resultante difere do título. Em 33 mensagens com `28/06`, a referência resultante é 01/07/2026. Em 23 com `10/11`, o parser usa 10/12/2025. Outras três mensagens com data explícita foram enviadas mais de sete dias depois da referência. Prefira a referência registrada para um fingerprint confirmado. Sem essa evidência, revise os títulos conflitantes antes de usá-los como fonte de uma entrada.
- Quatro mensagens mensais foram enviadas depois da competência indicada no título. O mês do título deve prevalecer quando o parser o reconhecer.
- O classificador de regras encaminharia 13 listas semanais com `virtualmente` para revisão. Outras 58 mensagens têm pelo menos quatro linhas numeradas e título com `lista` ou `vôlei`, mas não passam pelos parsers atuais. Esse grupo pode conter listas antigas em formatos diferentes ou mensagens de outra natureza.
- Para linhas sem fonte, uma coincidência de referência, identidade canônica e posição/seção fornece uma candidata. A seleção deve respeitar fontes já existentes e as revisões da entrada. Em particular, uma mensagem mensal que ainda não traz o `✅` não comprova a mudança posterior para pago. Se o vínculo não for seguro, a mensagem pode continuar disponível no histórico da lista, com a entrada sem fonte.

## Cruzamento com o banco

A leitura do banco encontrou 1.545 fingerprints exatos da exportação no chat legado `fred`, todos sem corpo e sem conflito de conteúdo. A prévia de vínculos considerou apenas mensagens aplicadas/inalteradas cujo `result` persistido comprovava o mesmo registro que continua ativo.

Depois da primeira gravação, 263/341 entradas mensais ativas e 931/1.359 semanais ativas tinham fonte. O corpo foi recuperado em 1.545 registros existentes, sem reaplicar listas. O segundo export acrescentou 611 snapshots reconhecidos por regra e 13 textos semanais de presença virtual em modo histórico, mais 23 vínculos mensais corroborados pela execução n8n 52043. Os totais atuais são 286/341 mensais e 931/1.359 semanais. Uma nova prévia encontrou zero alterações. Um registro semanal do primeiro export tem divergência entre a referência histórica/result aplicada (`2026-07-29`) e o período que o parser atual infere do corpo (`2026-08-05`); sua chave histórica foi preservada e ele não foi usado para atribuir fonte.

Testes automatizados e QA no navegador não foram executados conforme `AGENTS.md`.
