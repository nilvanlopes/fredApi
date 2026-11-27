# Retomada do vínculo das fontes

## Fluxo

- [x] 1. Inventariar entradas ativas sem fonte no PostgreSQL.
- [x] 2. Comparar os exports de WhatsApp com cada lista e conferir correções registradas.
- [x] 3. Vincular as 13 entradas de mensal 09/2026 à versão de 23/09.
- [x] 4. Vincular as outras 42 entradas mensais: agora 341/341 têm fonte.
- [x] 5. Vincular 300 entradas semanais a mensagens já existentes.
- [x] 6. Registrar três mensagens especiais no histórico e vincular 46 entradas semanais.
- [x] 7. Reavaliar divergências de identidade e versões antigas; vincular mais 13 entradas.
- [x] 8. Investigar 14/02/2025, identificar o convite importado como lista e arquivar as 12 presenças indevidas.
- [x] 9. Investigar e remover a partida duplicada de 20/02/2025 criada pela importação por IA.
- [ ] 10. Consultar no app e executar os testes conforme `AGENTS.md`.

## Pendências semanais após a gravação

Não há entradas semanais ativas sem fonte. As 25 entradas de 20/02/2025 foram criadas pelo mesmo lote de importação que gravou a partida de 19/02 e foram removidas como duplicata, sem reaplicar a lista em outra data.

14/02/2025 não tinha um cabeçalho de lista com essa data. As 12 entradas vieram de uma importação por IA de 05/08/2026, baseada numa mensagem de Evaldo em 07/02: “Vôlei hj na 14 às 19:00”, seguida pelos 12 nomes. O fingerprint do export confirma a mensagem original. A IA provavelmente interpretou “na 14” como data, embora o grupo use a expressão para o local. Como o texto é um convite, não uma lista no padrão, arquivei as 12 presenças, marquei a mensagem como `ignored` e mantive seu corpo e resultado original. Depois removi a partida falsa do calendário. O registro da remoção preserva a lista de participantes, posições e mensagem-fonte; a mensagem original segue guardada para auditoria.

A operação gerou 12 eventos de saída auditados. As quatro cobranças avulsas existentes continuaram dispensadas, sem alteração; não houve outras cobranças para as 12 pessoas nessa partida. A contagem semanal ativa passou de 1.359 para 1.347.

Em 06/05/2026, os dois exports e a lista aplicada mostram “Gabriel k” na posição 10. Por confirmação do usuário, atribuí somente essa entrada ao perfil Gabriel Krutschok e liguei-a à mensagem. Não juntei os perfis. A mensalidade paga de Krutschok e a cobrança dispensada do perfil genérico Gabriel foram preservadas. A importação de 20/02 foi confirmada como duplicata da versão final de 19/02; a partida e as 25 presenças foram removidas com snapshot integral na auditoria. A mensagem de origem ficou `ignored`, com seu fingerprint e resultado original preservados. As oito cobranças de R$ 7,50 da data eram dispensadas e foram mantidas com suas auditorias. Depois, por confirmação do usuário de que a lista de 20/06/2026 não pertencia ao Fred, removi essa partida e suas 12 presenças. As duas representações da mensagem foram marcadas `ignored`, mantendo o corpo do export, os resultados e fingerprints na auditoria. As 11 cobranças de R$ 7,50 estavam dispensadas, sem pagamento, e foram preservadas. O estado ativo atual tem 1.310 entradas semanais, todas com fonte.

As fontes são registros históricos. As gravações feitas nesta etapa alteraram `source_message_id` e recuperaram `raw_text` de uma mensagem sem texto; não reaplicaram listas, presença, pagamento ou time. A mensagem especial de 28/06 foi registrada na chave correta; a cópia previamente classificada em 01/07 foi mantida intacta.
