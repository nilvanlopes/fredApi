# Vínculo da lista mensal de setembro de 2026

- [x] Localizar a mensagem inicial de 01/09 às 18h25min12s e conferir as 18 versões no export.
- [x] Comparar a versão final com as 13 entradas ativas, suas posições e pagamentos.
- [x] Ligar as entradas à mensagem final e verificar os vínculos no PostgreSQL.

A mensagem inicial (ordinal 4155) contém apenas `1. pyu ✅`. Por isso, ela representa somente a primeira versão da lista. A última versão disponível é de 23/09 às 17h20min14s, ordinal 4368, com 13 entradas. O parser reconhece o cabeçalho mensal.

As 13 posições, os nomes exibidos e os estados de pagamento da versão final coincidem com a lista ativa de setembro. O banco tinha 13 entradas sem `source_message_id`, apesar das 18 versões já estarem preservadas como histórico `stale`. O importador de export não reaplicou mensagens antigas nem atribuiu suas fontes por padrão.

Após revalidar o corpo e a lista na transação, gravei apenas `source_message_id` nas 13 entradas, apontando ao ordinal 4368. A consulta posterior confirmou 13/13 entradas ligadas ao mesmo snapshot. O status continua `stale`; não reapliquei a lista nem alterei pagamentos.
