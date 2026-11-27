# Rastreio e histórico das listas do WhatsApp

Objetivo: para cada entrada das listas mensal e semanal, permitir abrir a mensagem WhatsApp que originou a entrada e navegar cronologicamente pelos snapshots completos que alteraram aquela lista.

## Fluxo sequencial

- [x] 1. Inspecionar as instruções do projeto, estado do repositório e memória específica do Fred; preservar alterações existentes.
- [x] 2. Mapear WAHA → n8n → API → banco, confirmando conteúdo integral, identidade estável da mensagem e momento de ingestão. (docs/progress/01-waha-n8n-db.md)
- [x] 3. Mapear listas mensal/semanal, ações por entrada, endpoints e padrões do frontend. (docs/progress/02-ui-api.md)
- [x] 4. Consolidar o desenho de dados e API: snapshots imutáveis, vínculo da mensagem de origem e ordenação/deduplicação; decidir como tratar mensagem editada/apagada, reenviada e alterações manuais.
- [x] 5. Ajustar o envelope do Router ativo e registrar retornos de envio dos workflows programados/de promoção, com backup e publicação n8n versionada. (docs/progress/01-waha-n8n-db.md)
- [x] 6. Implementar migração, gravação de mensagem completa em importação/tempo real/saída WAHA e vínculo por entrada, com idempotência.
- [x] 7. Expor endpoints para histórico navegável e mensagem fonte por entrada nas listas mensal e semanal.
- [x] 8. Adicionar navegação anterior/próxima e ação “Ver fonte” com modal acessível para lista/entrada; cobrir estados sem fonte e histórico vazio.
- [x] 9. Criar/atualizar testes focados de backend e frontend e revisar os diffs. Não executados conforme a instrução do projeto.
- [x] 10. Entregar comandos de teste ao usuário. A execução continua pendente para o usuário, conforme AGENTS.md.

## Decisões e evidências

- `ProcessedConversationMessage` será o registro imutável por mensagem, acrescido do corpo bruto e metadados WAHA. O seu resultado atual não reconstrói a mensagem: para mensal é delta, e para semanal é o estado efetivo da lista depois da alocação. Uma rota separada registra mensagens enviadas sem reaplicar o conteúdo ao domínio.
- As rotas genérica e especializadas e o importador `apply` persistirão o conteúdo na mesma transação do processamento. O histórico navegará as mensagens capturadas para a mesma chave `monthly:YYYY-MM` ou `weekly:YYYY-MM-DD`, por `occurred_at`, com desempate estável por registro.
- `MonthlySubscriber` e `WeeklyAttendanceEntry` guardarão `source_message_id` opcional para abrir a última mensagem válida recebida ou enviada que continha aquela entrada. A atualização desse vínculo respeitará o cursor de revisão; evento mais antigo não substitui fonte mais nova. Entradas criadas manualmente ou legadas retornam sem fonte.
- ID de mensagem do WAHA será a chave de idempotência dentro do chat. Uma redelivery não cria novo snapshot nem altera a origem já registrada. Exportações sem ID do provedor continuam deduplicadas pelo fingerprint atual.
- As 106 execuções anteriores encaminharam o conteúdo sem perda observável; o Router ativo agora guarda o texto original sem trim, usa o timestamp WAHA em segundos convertido para ISO UTC, e escolhe `payload.from` para entrada ou `payload.to` para saída. Foram observados 46 IDs duplicados e 13 HTTP 500 cuja causa continua sem diagnóstico; o novo Fred deduplica pelo ID WAHA e chat.
- As mensagens enviadas pelos dois fluxos ativos (agendamento e promoção) agora registram o recibo em `POST /messages/record-sent`. Backups e versões ativas estão em docs/progress/01-waha-n8n-db.md. Nenhum envio ou recibo real foi executado durante a alteração; a persistência do primeiro recibo será confirmada no próximo envio natural.
- A API chamada pelo n8n e seu PostgreSQL foram conferidos depois da publicação: schema em `0009_whatsapp_list_history`, com `raw_text`, `provider_message_id` e ambos os `source_message_id` disponíveis.
- WAHA assina eventos `message` e `message.any`, mas não edição/revogação. O workflow ainda não configura uma lista allowlist de grupos; a entrada grava o chat correto recebido e o histórico combina mensagens que alteram a mesma referência de mês ou partida. Qualquer restrição a um grupo específico precisa ser definida separadamente.
- Alterações manuais não entram no histórico de mensagens WhatsApp; continuam no histórico de auditoria. Mensagens apagadas/edições WAHA não são atualmente assinadas e não serão inventadas como snapshots. Reenvio distinto do mesmo texto conta como nova mensagem se tiver outro ID WAHA.
- O legado sem corpo não será apresentado como se fosse rastreável: botão desabilitado/estado “Fonte indisponível”. Preenchimento retroativo só seria seguro com exportação original verificável.

## Restrições

- Não executar testes nem QA manual/browser; o `AGENTS.md` do projeto deixa a execução para o usuário. Criar cobertura e deixar os comandos prontos.

## Recuperação do export fornecido

- [x] Analisar o arquivo do grupo e comparar fingerprints exatos no banco; plano detalhado em `03-export-audit.md` e `04-replay-design.md`.
- [x] Recuperar 1.545 corpos nos registros legados correspondentes sem reaplicar estado de lista.
- [x] Vincular 263 entradas mensais e 907 semanais a snapshots aplicados, confirmados pelo resultado persistido e por período, identidade e posição/seção.
- [x] Conferir idempotência da primeira e segunda exportação: novas prévias encontraram zero registros a inserir.
- [x] Sincronizar o segundo formato de exportação com AM/PM; adicionar 624 snapshots históricos (incluindo 13 mensagens semanais de presença virtual guardadas sem aplicar) e 23 vínculos mensais verificados contra o n8n. A revisão está em `05-export2-audit.md` e `06-export2-link-review.md`.
- [x] Recontar as fontes ativas: 286/341 entradas mensais e 931/1.359 semanais têm fonte. Restam 55 mensais e 428 semanais sem evidência suficiente.
- [ ] A lacuna entre fevereiro e outubro de 2025 permanece fora dos dois arquivos; mensagens não cobertas e os casos ambíguos precisam de outro export ou revisão.
- [ ] Testes backend/frontend continuam para execução do usuário, conforme `AGENTS.md`; não foram executados nesta recuperação.
