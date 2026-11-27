# Histórico da partida de 09/09/2026

- [x] Localizar a mensagem indicada e as versões seguintes nos anexos.
- [x] Comparar os corpos e fingerprints com o histórico no PostgreSQL.
- [x] Conferir as posições, a data do lote e as correções posteriores por consulta somente leitura.
- [x] Vincular as 24 entradas ativas à última mensagem após revalidar o lote; verificar o vínculo em nova consulta.

O primeiro export termina em 04/08/2026 às 23h52. O segundo (`chat.txt`) contém 25 mensagens com o cabeçalho `LISTA VÔLEI FREDERICO 09/09`. O parser semanal reconhece todas e resolve a data como 09/09/2026. A mensagem citada está na linha 26006, ordinal 4233, enviada às 16h26min02s de 08/09. A versão final está na linha 26479, ordinal 4286, enviada às 18h28min32s de 09/09. Ordinais começam em zero e os horários são de São Paulo.

| Data e hora | Ordinal | Entradas | Seção principal |
|---|---:|---:|---:|
| 08/09 16:26:02 | 4233 | 1 | 1 |
| 08/09 16:26:23 | 4234 | 2 | 2 |
| 08/09 16:29:15 | 4236 | 3 | 3 |
| 08/09 17:22:24 | 4237 | 6 | 4 |
| 08/09 17:34:41 | 4238 | 9 | 7 |
| 08/09 17:40:13 | 4242 | 10 | 8 |
| 08/09 22:53:30 | 4244 | 12 | 9 |
| 09/09 07:16:36 | 4245 | 13 | 10 |
| 09/09 09:09:43 | 4246 | 14 | 11 |
| 09/09 13:50:16 | 4247 | 14 | 11 |
| 09/09 15:11:56 | 4248 | 15 | 12 |
| 09/09 15:12:59 | 4250 | 15 | 12 |
| 09/09 15:31:56 | 4253 | 16 | 12 |
| 09/09 16:15:21 | 4254 | 17 | 13 |
| 09/09 16:50:07 | 4255 | 17 | 17 |
| 09/09 16:56:25 | 4256 | 19 | 19 |
| 09/09 17:02:00 | 4257 | 21 | 21 |
| 09/09 17:10:54 | 4258 | 22 | 22 |
| 09/09 17:44:22 | 4259 | 23 | 23 |
| 09/09 17:45:37 | 4260 | 24 | 24 |
| 09/09 18:11:52 | 4265 | 22 | 22 |
| 09/09 18:18:08 | 4269 | 23 | 23 |
| 09/09 18:24:41 | 4278 | 24 | 24 |
| 09/09 18:27:43 | 4284 | 23 | 23 |
| 09/09 18:28:32 | 4286 | 24 | 24 |

## Vínculo e evidências

As 25 mensagens já constavam no PostgreSQL como `stale` e `whatsapp-export`, na chave `weekly:2026-09-09`. Os 25 corpos são idênticos aos do arquivo e os fingerprints correspondem ao mesmo ordinal. Na consulta inicial, as 24 entradas ativas tinham `source_message_id` vazio. A primeira sincronização gravou as mensagens para consulta no histórico e exigiu auditoria `whatsapp/join` aplicada para vincular as entradas semanais. Essa partida tem quatro registros de correções posteriores e zero eventos `whatsapp/join` por partida ou data.

A versão final coincide em seção, posição, identidade canônica e convidante com 19 das 24 entradas ativas. As 24 entradas compartilham a mesma hora de criação e ingresso, 18h28min31,255325s de 09/09, a 0,744675 s do horário da versão final no export. A versão imediatamente anterior tem 23 entradas. A versão final é a melhor referência para o lote.

| Posição | Diferença entre export e entrada atual | Evidência |
|---|---|---|
| 4 | `Heitor` aparece como `Heitor Cardoso` na entrada. | Evento `requested_data_correction/reassign` documenta a troca de identidade na partida em 11/11. |
| 18 | `Tiago` aparece como `Tiago Almeida` no campo de convidante. | Evento `tiago_review/inviter_identity_correction` identifica a mesma entrada de Keilla e documenta a troca em 11/11. |
| 19 | `Tiago` aparece como `Tiago Almeida` na entrada. | Evento `tiago_review/identity_correction` identifica a entrada e documenta a troca em 11/11. |
| 22 | O nome e a posição coincidem. O banco tem autoatribuição como convidante. | A entrada integra o lote original e tem atualização de 11/11. O texto não especifica convidante e a consulta não encontrou evento de convite para esta entrada. |
| 23 | O nome e a posição coincidem. O banco tem autoatribuição como convidante. | A entrada integra o lote original e `updated_at` coincide com `created_at`. O texto não especifica convidante. |

Os 19 pareamentos exatos sustentam o preenchimento de `source_message_id` com a mensagem final. A hora compartilhada do lote, a correspondência por posição e as três correções documentadas sustentam o vínculo também para as cinco exceções como fonte da presença. Os campos de convidante das posições 22 e 23 não têm confirmação no texto. Em uma gravação, revalidar o lote e preencher somente o campo de fonte das entradas ativas que ainda estejam sem vínculo.

## Correção do vínculo

Revalidei a transação: a mensagem de ordinal 4286 continua como versão final; as 24 entradas ativas ainda não tinham fonte e compartilham o mesmo instante original de criação/entrada. Gravei apenas `source_message_id` nas 24 entradas, apontando para essa mensagem. Uma consulta posterior confirmou 24/24 vinculadas ao mesmo registro. A mensagem permanece `stale` porque veio do export, e nenhum evento de presença, convidante, pagamento ou lista foi reaplicado. A fonte comprova a versão final da presença; o texto não confirma os auto-convidantes nas posições 22 e 23.
