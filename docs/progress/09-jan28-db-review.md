# Auditoria de fontes da partida de 28/01/2026

- [x] Consultar a partida, as entradas, o histórico, a auditoria e as revisões em transações `READ ONLY`.
- [x] Comparar as versões do WhatsApp com as posições, identidades e convidados do lote revisado.
- [x] Definir a mensagem de referência e as condições de vinculação.

## Evidência no banco

A partida `cf31ffe7-047f-44be-b59b-0e6b6fdc6303` tem 20 pessoas distintas nas posições 1 a 20 da seção principal. Cinco linhas têm convidante explícito. Na leitura inicial, as 20 fontes estavam vazias e não havia mensagem em `weekly:2026-01-28` nem corpo com `FEEDERICO 28/01`.

A partida foi reconstruída em 11/11/2026 às 19h55, no horário de São Paulo. A auditoria `whatsapp_review` contém um evento `create` com a data, a hora de início de 19h30 e o título revisado, 20 eventos `join` aplicados e 20 eventos `allocation`. Nas 20 entradas, `joined_at`, a revisão atual da pessoa na partida e o `join` revisado têm o mesmo instante. O roteiro existente da reconstrução, `/tmp/import_reviewed_games.py`, registra as mesmas 20 posições e mantém os convidados na seção principal, com convidante separado quando conhecido. A leitura encontrou oito cobranças avulsas pendentes da partida.

## Correspondência com o WhatsApp

Cada exportação contém 23 versões da lista com o cabeçalho `LISTA VOLEI FEEDERICO 28/01`. Há 21 pares com minuto e corpo idênticos. Os outros dois pares têm o mesmo minuto e posição relativa e diferem só pelo marcador `<Mensagem editada>` no primeiro arquivo. O segundo export permite conservar os segundos e registrar uma versão de cada par. O parser exige `frederico` no modo estrito. A data explícita do cabeçalho sustenta a associação a `weekly:2026-01-28` em leitura permissiva com a data informada.

As versões de 19h10min44s, 19h25min25s e 23h18min08s de 28/01 contêm as 20 posições revisadas. O parser já ignora uma linha de posição zero na primeira e o marcador `✅` presente na última. Nas posições 9 e 18, ele mantém o sufixo `conv Allan` dentro do nome. Separar o convidante apenas na comparação permite conferir as duas identidades e o convidante já registrado no banco. A versão final das 23h18min08s, ordinal 1084 a partir de zero em `chat.txt`, reproduz as 20 identidades, posições e relações de convite. As três versões têm a mesma assinatura de presença. A versão final é a referência recomendada para os vínculos. A auditoria comprova a reconstrução pelo lote revisado, mas não identifica a versão exata que serviu de leitura naquele momento.

## Condições de gravação

Registrar as mensagens como histórico `stale` no namespace `fred-export-history`, com corpo original, ordem, horário e fingerprint idempotente. A API de histórico aceita esse status. Usar a versão final como referência somente se a transação confirmar novamente as 20 entradas ativas, com o mesmo conjunto de pessoas, posições e convidantes, e os `join` revisados ainda correspondentes a `joined_at` e à revisão. Atualizar exclusivamente `source_message_id` das entradas elegíveis que estiverem sem fonte. Conferir o total do histórico, os vínculos e a contagem de cobranças por leitura posterior.

## Resultado da sincronização

- [x] As 23 versões de `chat.txt` foram gravadas em `weekly:2026-01-28`, com corpo intacto, ordinal, horário local e hash do export. A grafia `FEEDERICO` permanece no conteúdo; os eventos têm status histórico `stale`.
- [x] As 20 entradas ativas foram ligadas ao snapshot final do ordinal 1084 após revalidar identidade, posição, convidante, estado ativo e fonte vazia na mesma transação. Nos itens 9 e 18, `conv Allan` foi tratado como convidante, sem alterar o nome ou o estado da entrada.
- [x] A consulta posterior confirmou 23 mensagens, 20 fontes, um único ID de mensagem e referência final às 23h18min08s. Nenhuma presença ou cobrança foi reaplicada.
- [ ] Testes e QA de navegador continuam pendentes para execução do usuário, conforme `AGENTS.md`.

A versão final reproduz o lote reconstruído e revisado, mas o log não identifica qual dos três envios finais foi usado na reconstrução original. Essa limitação permanece registrada.
