# Histórico da lista de 28/01/2026

- [x] Localizar o cabeçalho e as versões da lista nos dois anexos.
- [x] Confirmar a data, a ordem e o comportamento do parser.
- [x] Gravar as 23 mensagens no histórico sem reaplicar a lista.
- [x] Vincular as 20 entradas ativas à versão final após conferir identidade, posição e convidante.
- [x] Conferir o histórico e as fontes após a gravação.

O cabeçalho `LISTA VOLEI FEEDERICO 28/01` ocorre 23 vezes em cada exportação. A busca por outros cabeçalhos com “lista” ou “vôlei” e “28/01” em 2026 retornou as mesmas 23 ocorrências.

As duas exportações mostram a mesma sequência de mensagens. Os horários coincidem no minuto local. Em 21 pares, o corpo coincide integralmente. Às 12h46 e 14h44 de 28/01, a primeira exportação inclui o marcador `<Mensagem editada>` no final do corpo e a segunda não o inclui. O nome exibido do remetente diverge em seis pares. A segunda exportação distingue por segundos as duas versões de 26/01 às 13h07, que também têm conteúdos diferentes.

O parser semanal rejeita os 23 cabeçalhos porque as expressões regular e implícita exigem `frederico`. Todos os corpos têm ao menos uma entrada e são interpretados como listas semanais de 28/01/2026 ao passar `allow_unrecognized_header=True` e `game_date_hint=date(2026, 1, 28)`, após a seleção pelo cabeçalho. A seleção explícita permite preservar a grafia original no histórico e manter a data correta para a partida.

| Horário de Brasília | Ordinal da primeira exportação | Ordinal de `chat.txt` | Linha de `chat.txt` | Principal | Convidados |
|---|---:|---:|---:|---:|---:|
| 26/01 12:10:46 | 2977 | 1030 | 7308 | 1 | 0 |
| 26/01 12:16:13 | 2978 | 1031 | 7310 | 5 | 0 |
| 26/01 12:17:25 | 2979 | 1032 | 7316 | 5 | 1 |
| 26/01 12:18:04 | 2980 | 1033 | 7325 | 6 | 1 |
| 26/01 12:23:49 | 2981 | 1034 | 7335 | 8 | 1 |
| 26/01 12:39:14 | 2982 | 1035 | 7347 | 9 | 1 |
| 26/01 13:07:38 | 2983 | 1036 | 7360 | 10 | 1 |
| 26/01 13:07:58 | 2984 | 1037 | 7374 | 11 | 1 |
| 27/01 17:26:39 | 2985 | 1038 | 7389 | 12 | 1 |
| 28/01 10:46:43 | 2986 | 1039 | 7405 | 12 | 2 |
| 28/01 12:46:46 | 2987 | 1040 | 7422 | 12 | 2 |
| 28/01 12:53:58 | 2988 | 1041 | 7440 | 11 | 2 |
| 28/01 14:35:07 | 2989 | 1042 | 7459 | 11 | 3 |
| 28/01 14:44:59 | 2990 | 1043 | 7479 | 11 | 4 |
| 28/01 15:14:19 | 2993 | 1046 | 7502 | 12 | 4 |
| 28/01 16:33:18 | 3002 | 1055 | 7532 | 16 | 0 |
| 28/01 16:34:03 | 3003 | 1056 | 7551 | 17 | 0 |
| 28/01 18:14:32 | 3007 | 1060 | 7574 | 16 | 0 |
| 28/01 19:00:41 | 3010 | 1063 | 7596 | 18 | 0 |
| 28/01 19:03:54 | 3011 | 1064 | 7617 | 19 | 0 |
| 28/01 19:10:44 | 3012 | 1065 | 7639 | 20 | 0 |
| 28/01 19:25:25 | 3014 | 1067 | 7663 | 20 | 0 |
| 28/01 23:18:08 | 3032 | 1084 | 7701 | 20 | 0 |

Os ordinais começam em zero. As contagens representam as seções interpretadas pelo parser, e as últimas versões trazem os nomes na seção principal. A vinculação de entradas requer comparação com as linhas existentes da partida. A leitura das duas exportações e a inspeção do parser foram feitas localmente.

## Sincronização aplicada

- As 23 versões de `chat.txt` foram gravadas uma vez em `weekly:2026-01-28`, no namespace `fred-export-history`. Os registros mantêm o texto original, horário com segundos, ordinal e hash do export; IDs WAHA não foram inventados. A grafia original `FEEDERICO` foi preservada.
- As 20 entradas ativas agora apontam para a versão final de 28/01 às 23h18min08s. As identidades e posições coincidem; nos itens 9 e 18, `conv Allan` corresponde ao convidante que já consta na entrada. Essa versão reproduz o conjunto revisado, mas a auditoria disponível não prova qual envio foi consultado na reconstrução de novembro.
- Os 23 registros permanecem históricos (`stale`), sem reaplicar presenças, cobranças, convidados ou alocação. A conferência encontrou 23 mensagens, 20 vínculos e um único `source_message_id` compartilhado pelas entradas da partida.
- Testes automatizados e QA no navegador não foram executados conforme `AGENTS.md`.
