# Auditoria da segunda exportação do WhatsApp

- [x] Identificar o formato, o fuso e a cobertura de `chat.txt`.
- [x] Classificar as listas pelos parsers atuais do Fred.
- [x] Cruzar os candidatos com o histórico no PostgreSQL em transação somente leitura.

## Formato e cobertura

O segundo arquivo usa cabeçalhos no formato `[M/D/AA, h:mm:ss AM/PM]`, com mês antes do dia e resolução de segundos. O primeiro arquivo usa dia antes do mês, relógio de 24 horas e resolução de minutos. A leitura do segundo arquivo usou `America/Sao_Paulo` e preservou a ordem e as quebras de linha internas dos corpos. O arquivo cobre 01/11/2025 às 14h08min39s a 12/11/2026 às 14h29min06s.

| Classificação | Mensagens | Referências |
|---|---:|---:|
| Mensal | 419 | 13 competências |
| Semanal | 1.314 | 52 partidas |
| Para revisão | 13 | |
| Demais mensagens | 3.820 | |
| Total | 5.566 | |

Os parsers identificaram 1.733 mensagens de listas com período definido. A janela do segundo arquivo estende a cobertura até novembro de 2026. A lacuna de fevereiro a outubro de 2025 indicada na auditoria do primeiro export permanece fora da cobertura do segundo.

## Cruzamento com o histórico

A leitura encontrou 1.548 registros com corpo preenchido, dos quais 1.545 vieram da primeira exportação. Em `chat_id='fred'`, 11 mensagens do segundo arquivo têm fingerprint exato com segundos e 740 têm fingerprint exato ao reduzir o horário ao minuto. Todos os registros encontrados por esses dois cruzamentos já têm corpo preenchido.

| Correspondência por agregado, minuto local e corpo integral | Mensagens |
|---|---:|
| Uma ocorrência em cada fonte | 1.118 |
| Duas ocorrências em cada fonte | 4 |
| Ausentes dessa chave no banco | 611 |
| Total de listas com período | 1.733 |

Os quatro casos ambíguos correspondem a dois pares com o mesmo corpo e minuto em cada fonte. As quatro ocorrências já têm contrapartidas no banco em quantidade, mas o vínculo individual entre exportações pode depender da ordem ou do remetente. Os 611 candidatos sem correspondência se dividem em 134 mensagens mensais de 13 competências e 477 semanais de 44 partidas. Desse total, 486 foram enviados entre agosto e novembro de 2026.

Entre os 611 candidatos, 79 têm o mesmo agregado, minuto e autor de uma mensagem existente com corpo diferente. A comparação após normalizar espaços e caracteres invisíveis não acrescentou correspondências. Três candidatos têm corpo igual a uma mensagem de outro minuto, com diferenças de 1 segundo, 12 minutos e 24 segundos, e 7 horas, 27 minutos e 26 segundos. No caso de 1 segundo, os remetentes exibidos são diferentes. A proximidade de horário sozinha é insuficiente para fundir essas ocorrências.

Para a deduplicação, converter os horários do banco e do arquivo ao mesmo fuso antes de comparar o minuto. Cruzar primeiro o fingerprint legado e depois a chave composta pelo agregado, minuto e corpo. O nome exibido do remetente pode variar entre exportações. Nas correspondências de 1 para 1, manter o registro existente. Nos dois grupos de 2 para 2, preservar a contagem existente e deixar a associação individual para revisão. Para novos registros, usar fingerprint estável com o horário completo e conservar o ordinal de origem para ordenar o histórico.

Um snapshot presente no arquivo comprova a circulação da lista no grupo. Atribuir uma mensagem como origem de uma entrada ativa exige evidência de aplicação no resultado legado ou na auditoria do WhatsApp. Sem essa evidência, o snapshot pode integrar a navegação do histórico com o status `stale`.

## Sincronização aplicada

- [x] Foram gravados 611 snapshots novos reconhecidos por regra (134 mensais, 477 semanais), mais 13 listas semanais mencionando presença virtual, guardadas apenas como histórico `stale`. Total: 624 registros, sem reaplicar listas.
- [x] 1.118 correspondências únicas reutilizaram registros existentes; quatro ocorrências em dois grupos 2:2 foram preservadas sem pareamento individual. O fingerprint isolado torna a operação idempotente; a segunda prévia encontrou zero snapshots novos. Os 624 registros ocupam 57 referências e seus períodos conferem em `America/Sao_Paulo`.
- [x] A execução n8n 52043 confirmou o snapshot mensal de 11/11/2026 às 17h46min24s, ordinal 5548. O corpo coincide exatamente, os 24 eventos aplicados e as revisões ocorreram 1,665 s depois, e a resposta original foi recuperada. 23 entradas ativas foram vinculadas; a mensagem recebeu ID WAHA, remetente e resultado verificado.
- [x] Nenhuma entrada semanal adicional recebeu fonte: as 243 correspondências sem fonte não têm auditoria de aplicação `whatsapp/join`. Elas permanecem sem vínculo, embora suas mensagens estejam na navegação do histórico.
- [ ] Testes automatizados e QA no navegador não foram executados conforme `AGENTS.md`.
