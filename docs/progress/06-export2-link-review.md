# Revisão de fontes do segundo export

## Identidade das mensagens

- [x] Comparar as duas exportações com horário em `America/Sao_Paulo`. O segundo arquivo usa mês/dia/ano, AM/PM e segundos. O cruzamento dos anexos encontrou 2.992 mensagens com corpo idêntico no mesmo minuto entre 3.792 registros com remetente no intervalo comum. Normalizar espaços à direita e marcas de direção de texto não acrescentou correspondências.
- [x] Conferir a deduplicação proposta para o histórico. Das 1.733 listas reconhecidas no segundo arquivo, 1.122 têm corpo idêntico no mesmo minuto de uma mensagem já armazenada. Dois grupos têm duas ocorrências em cada lado e abrangem quatro mensagens do segundo export. Tentar primeiro remetente idêntico. Entre os registros restantes, aceitar corpo e minuto quando o pareamento for único no mesmo grupo. Preservar os registros existentes nos grupos ambíguos. As 611 ocorrências sem coincidência de corpo e minuto são candidatas a registros novos. Conferir capturas WAHA e exceções temporais antes de gravar.
- [x] Identificar os campos para a gravação histórica. Para as mensagens inéditas sem prova de aplicação, usar `source='whatsapp-export'`, `status='stale'`, tipo e período identificados, texto multilinha, horário e ordinal do anexo. Usar um namespace estável para o fingerprint que isole o histórico dos cursores do importador. Guardar o hash do anexo nos metadados. Preservar mensagens repetidas em instantes distintos e deixar identificadores do provedor vazios quando a origem não os fornece.

## Evidência de vínculo a uma entrada atual

O cruzamento no PostgreSQL em transação `READ ONLY` examinou as 484 listas reconhecidas após o fim do primeiro export, sendo 100 mensais e 384 semanais.

| Evidência no recorte | Mensais | Semanais |
| --- | ---: | ---: |
| Entradas ativas sem fonte em período coberto | 62 | 264 |
| Identidade canônica e posição correspondem à lista | 60 | 243 |
| Auditoria WhatsApp aplicada coincide com a revisão atual e a mensagem foi confirmada no n8n | 23 | 0 |

- [x] Confirmar o lote de novembro de 2026. A execução 52043 do Router terminou com sucesso. O corpo recebido do WAHA e o texto entregue ao Fred coincidem com a mensagem do export de 11/11 às 17h46min24s, ordinal 5548 a partir de zero. O `received_at` do Router, 17h46min25,665s, é o instante dos 24 `upsert` aplicados e de suas revisões atuais. As 24 pessoas e os estados de pagamento no lote auditado coincidem com a mensagem. O Fred respondeu com três linhas atualizadas e 21 inalteradas. Entre as pessoas do lote, 23 têm entradas ativas e coincidem em identidade e posição.
- [x] Corroborar os metadados e recuperar o resultado original. O WAHA fornece ID serializado, chat e remetente. Como `fromMe` está ativo, o chat consta em `payload.to` e no ID serializado. O nome exibido vem do export. O JSON original da resposta do Fred confirma `status='applied'` pelo mesmo critério usado na ingestão. O namespace histórico isola o registro dos cursores do importador normal.
- [x] Conferir o outro lote mensal auditado. O export de 11/11 às 11h40min42s tem uma mensagem próxima do lote das 11h40min43,108s. O conjunto de pessoas e pagamentos diverge. Esse horário sozinho não sustenta vínculo adicional.
- [x] Conferir o recorte semanal. Nenhuma das 243 entradas sem fonte com assinatura correspondente no export tem `whatsapp/join` aplicado que comprove a origem. Guardar as mensagens como versões históricas até existir evidência de aplicação à entrada.

Para o lote mensal comprovado, vincular só as entradas ativas com `source_message_id` nulo e identidade, competência, posição e revisão iguais às da prévia. Revalidar essas condições na mesma transação da escrita. Usar `UPDATE` de `source_message_id` explícito para evitar `updated_at` automático do ORM. A aplicação original pode ser identificada em `analysis` pela execução do n8n. Os demais snapshots novos continuam navegáveis pelo histórico de sua competência ou partida.

- [x] Adicionar também as 13 mensagens semanais marcadas para revisão por presença virtual, apenas como texto histórico `stale`; não alterar a lista de presença atual.

- [x] Conferir os vínculos após a sincronização. Em nova consulta `READ ONLY`, as 23 entradas ativas do lote apontam para uma única mensagem mensal de novembro de 2026. O SHA-256 do corpo coincide com o da mensagem original no arquivo.

As consultas ao PostgreSQL do Fred e do n8n foram feitas em transações de leitura. Testes automatizados e QA de navegador não foram executados.
