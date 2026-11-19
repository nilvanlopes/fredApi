# Revisão responsiva do frontend

Status: revisão visual manual **NÃO EXECUTADA**. Este documento registra os
fluxos e dimensões que devem ser conferidos em navegador depois da
implementação; regras CSS e testes de DOM não comprovam o resultado visual.

## Escopo

- Visão geral do gestor: cartões de métricas, partidas, resumo mensal,
  pendências e movimentações recentes.
- Partidas do gestor: calendário, contadores, lista de participantes, filtros,
  ações, histórico e diálogos de criar/editar/adicionar/remover.
- Financeiro e cadastros do gestor: mensalidades, cobranças, jogadores, contas
  e auditoria; tabelas, filtros, ações por linha, cartões e formulários.
- Portal do jogador: painel, calendário/partidas, lista de assinantes e
  financeiro, incluindo inscrição, troca de mês, filtros e estados vazios.
- Acesso: login, cadastro, Google, alternância login/cadastro e confirmação de
  cadastro.
- Elementos compartilhados: navegação lateral e menu móvel, cabeçalho, menus,
  modais, alertas, listas/tabelas, selects e editor de aliases.

## Matriz manual

| Viewport | Cenários prioritários |
| --- | --- |
| 320 × 640 | Login/cadastro, métricas, títulos longos, botões de cabeçalho, formulário e rodapé de modal, aviso, editor de aliases. Conferir ausência de rolagem horizontal da página. |
| 360 × 800 | Portal jogador, partidas e alternância de mês; tabela com dica e scroll; ações em uma coluna quando necessário. |
| 390 × 844 | Todas as páginas do jogador e telas principais do gestor; filtros em cards e formulário completo. |
| 480 × 800 | Gestor: visão geral, cobranças, cadastros, listas com muitas colunas e modais. |
| 768 × 900 | Largura intermediária com sidebar: overview, calendário com resumo, cabeçalhos de painel e tabelas roláveis. |
| 950 × 900 | Limite entre sidebar e conteúdo estreito: calendário, gráficos/resumos, contadores e tabelas administrativas. |
| 1024 × 768 | Desktop estreito: calendário e contadores devem se reorganizar pelo espaço interno disponível; cabeçalhos e formulários não devem escapar do painel. |
| 1440 × 900 | Visão desktop do gestor e jogador: hierarquia, espaçamentos e animações de entrada sem deslocamento persistente. |
| 844 × 390, paisagem | Navegação lateral aberta e diálogos: rolagem interna utilizável, controles finais alcançáveis e nenhum conteúdo encoberto. |

Em todas as larguras, repetir com nomes, títulos, valores e mensagens longos;
listas vazias e carregando; muitas colunas e filtros ativos; menu aberto; modal
com formulário longo; zoom do navegador em 200% e 400%; e navegação só por
teclado. Confirmar foco visível, ordem de tabulação, escape/fechamento dos
diálogos e que o foco não fica escondido atrás do menu ou do rodapé fixo.

## Movimento e acessibilidade

- Conferir que o conteúdo continua visível sem depender de animação ou hover.
- Repetir com `prefers-reduced-motion: reduce`; novas animações e transições
  devem estar desligadas.
- Verificar que efeitos de hover aparecem só em dispositivos com ponteiro fino
  e que controles touch mantêm feedback por foco/estado.
- Conferir foco do teclado na região de tabela rolável e se a dica de rolagem
  aparece nas larguras estreitas.

## Resultado

Não executar esta revisão como parte de testes automatizados. Marcar a data,
navegador, dimensões e problemas encontrados quando uma pessoa concluir a
verificação manual.
