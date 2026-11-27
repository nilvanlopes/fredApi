# Perfis de jogadores

## Escopo consolidado

O menu do avatar oferece **Meu perfil**. O painel de jogador permanece como
destino independente e os dois itens têm ícone. Contas sem pessoa vinculada
podem visualizar perfis públicos, mas não editar perfis ou avaliar jogadores.

Cada jogador tem um link compartilhável `/#profile/<person_id>`, sem catálogo
público. A leitura funciona sem login. Entrar para avaliar preserva esse destino.
`/#my-profile` é a edição autenticada do próprio perfil; o dono vem da sessão,
nunca de um identificador enviado pelo formulário.

O perfil completo contém:

- Foto com recorte quadrado e exibição circular; mover, ampliar, trocar,
  reajustar e remover. Sem imagem, usar as iniciais.
- Nome atual do cadastro, sem edição administrativa nessa página.
- Apelidos públicos de apresentação, independentes dos `PersonAlias` que
  identificam pessoas em listas e reconciliam histórico e cobranças.
- Frase opcional de até 140 caracteres, em uma linha; esconder quando vazia.
- Várias posições de vôlei, com uma principal entre as selecionadas: ponta,
  levantador, central, oposto e líbero. Seleção vazia significa não informado.
- Sexo e mão dominante opcionais: masculino/feminino e
  destro/canhoto/ambidestro, respectivamente.
- Média de estrelas e quantidade de avaliações.
- Radar de habilidades **autodeclaradas**: passe, ataque, defesa, bloqueio
  e saque, cada uma de 0 a 100. Ausência de preenchimento é diferente de zero.

Nas listas de assinantes e de partidas, tanto da gestão quanto do jogador,
passar o mouse sobre o nome abre a prévia no desktop. Em dispositivos de toque,
clicar no nome abre o card. O card contém **foto, nome, estrelas,
quantidade de partidas e Ver perfil**. Sem foto cadastrada, usar as iniciais.
Não mostrar frase, posições,
quantidade de avaliações ou radar nesse card. Sem `person_id`, manter texto.
Os demais controles das linhas preservam seu comportamento.

No desktop, a prévia fica ancorada ao nome e permite mover o mouse até
**Ver perfil**, sem roubar foco nem bloquear a tabela. No toque, abre como
card modal, com fechamento por fora/Esc e retorno de foco ao nome.
O card não exibe botão de fechar; clicar fora o dispensa nos dois modos.

Para assinantes do mês atual em Brasília, o card utiliza o Holo Card
oficial do React Bits. A elegibilidade vem de `is_subscriber` na API do perfil:
inscrição mensal ativa, não removida, independentemente de pagamento. Uma
mensalidade passada ou futura não ativa o efeito no mês atual. A API não expõe
valores ou situação financeira para essa finalidade.

O visual combina o enquadramento de identidade do Profile Card, acabamento
metálico refletivo e a superfície do Holo Card. O padrão repetido **VIP** integra
essa superfície e, junto com o holo, é exclusivo dos assinantes do mês atual.
Inscrições de meses passados ou futuros não concedem esse acabamento.
Não assinantes mantêm o card comum, com foto e os mesmos dados resumidos.

O efeito mantém os mesmos dados do card e não acrescenta selo VIP.
O Holo Card aparece tanto no hover do desktop quanto no card aberto por toque
no celular. A foto preenche o card do assinante e se integra ao fundo verde
por um degradê. O texto VIP se repete em uma camada holográfica sobre a foto
e o fundo, abaixo dos textos e controles para preservar a leitura.
O shader recebe
um fundo decorativo local e os controles HTML permanecem clicáveis; sem WebGL,
o fundo estático preserva a legibilidade. Não há animação ociosa.

## Navegação mobile e React Bits

Até 760 px, a navegação autenticada usa uma barra inferior com cinco ações,
reserva espaço no conteúdo e respeita a área segura do aparelho. O menu
complementar preserva os destinos administrativos, troca de painel, acesso ao
perfil e saída. A navegação lateral permanece no desktop.

No modo jogador, o menu mobile é mais compacto e opaco, com ícone ativo maior
e verde mais intenso. A tabela de participantes da partida oculta as colunas
de número e tipo até 760 px; nomes e ações permanecem disponíveis, sem alterar
a ordem oficial. As tabelas do jogador não exibem o aviso de deslizar no mobile.
As colunas do desktop e as tabelas da gestão preservam seu conteúdo.

O destaque da aba selecionada se desloca com `transform`; a animação do ícone
também usa transformação e cor, sem animar dimensões do layout. A preferência
por movimento reduzido desativa as transições e preserva o estado selecionado.

### Custo dos efeitos no celular

O menu mantém o Glass Surface em modo fosco com blur de 8 px, evitando as três
passagens de deslocamento RGB do modo de refração SVG durante a rolagem.
O Holo Card do modal limita a resolução do canvas ao DPR 1 e o ciclo a 30 quadros por
segundo; os controles e a foto continuam sendo HTML. O efeito deixa de
redesenhar quando o movimento estabiliza e pausa quando a página fica oculta.

Essas são reduções de custo identificadas por inspeção de código. Build e
checagem de tipos não medem FPS nem provam melhora em um aparelho específico;
a medição no dispositivo e os testes continuam pendentes de execução.

A barra utiliza o **Glass Surface oficial do React Bits**, variante
`GlassSurface-TS-CSS`, em `frontend/src/components`. A licença e a atribuição
acompanham os arquivos. O renderer SVG utiliza o fallback de vidro fosco do
componente em navegadores sem suporte à refração SVG; o menu mantém contraste
e não depende de WebGL.

O registro `@react-bits` está em `frontend/components.json`. O MCP instalado
no Codex chama `npx -y shadcn@4.23.0 mcp`, com diretório de trabalho fixado em
`/home/pyu/docker/fred/frontend`. Seu nome é `react-bits`; esta configuração é
específica do frontend Fred. Reinicie o cliente Codex para carregar as
ferramentas na próxima sessão. A configuração pode ser consultada com:

```bash
codex mcp get react-bits
```

A contagem de partidas usa inscrições não removidas na lista principal
(`status=main`, inclusive convidados) de partidas cujo início já passou,
uma vez por partida. Espera, remoções e partidas futuras não contam. É uma
contagem do histórico de listas; não há controle separado de presença física.

## Avaliações

Uma nota geral inteira de 1 a 5 por par avaliador/avaliado. Não depende de
partida, não tem comentário e pode ser atualizada a qualquer momento. Alterar
a nota não aumenta a contagem. Não permitir autoavaliação ou avaliação por
conta sem jogador vinculado. A autorização de divulgar nome e nota é por
avaliação e começa desmarcada; fica guardada para uma futura lista de avaliações.
Nesta versão, a leitura pública mostra somente o agregado, nunca os autores.
Sem avaliações, mostrar estrelas vazias e indicar ausência de avaliações.
No próprio perfil, o painel se chama **Avaliações** e mostra **Nenhuma avaliação**
quando vazio, ou o resumo de média e quantidade quando houver notas. O
formulário **Avaliar jogador** aparece somente ao visualizar outro jogador.

A unicidade do par é garantida no PostgreSQL e a gravação usa upsert. Os
apelidos de apresentação não executam reconciliação de identidade. A união
administrativa de cadastros rejeita uma origem que já tenha perfil ou notas,
para impedir perda silenciosa até existir uma política específica de união.

## API e armazenamento

- `GET /api/public/profiles/{id}`: dados públicos e agregados.
- `GET /api/public/profiles/{id}/avatar`: somente a imagem derivada.
- `GET/PATCH /api/me/profile`: consulta/edição própria; a consulta inclui
  metadados de recorte para o editor, sem publicar chaves do bucket.
- `GET/PUT /api/me/ratings/{id}`: nota e autorização do avaliador autenticado.
- `POST /api/me/profile/photo`: multipart `file` e `crop` JSON com
  `x`, `y`, `width`, `height` em pixels da imagem orientada.
- `PATCH /api/me/profile/photo`: novo recorte JSON do original existente.
- `DELETE /api/me/profile/photo`: remover a foto.
- `GET /api/me/profile/photo/source`: original restrito ao próprio dono.

O original é privado. A API valida JPEG/PNG/WebP, assinatura real, limite de
10 MiB, até 40 milhões de pixels e recorte quadrado dentro dos limites.
Imagens animadas são rejeitadas. A derivada é WebP 512×512 sem metadados de
origem. Objetos têm chaves por pessoa/versão; uploads só substituem as
referências após sucesso. A foto anterior é preservada se a gravação falhar.

O bucket `fred-profile-images` fica privado no Floci. A publicação da derivada
é feita pela API Fred, não por acesso anônimo ao S3 nem pelo proxy público do
FichasRPG. Somente a API Fred recebe a rede `floci-internal`. Credenciais são
configuradas pelas variáveis `FRED_PROFILE_S3_*`, nunca por `VITE_*`.

O Floci existente usa credenciais compartilhadas; não há isolamento IAM por
aplicação configurado. Workloads autorizados nessa rede continuam sendo parte
da zona de confiança. Nenhum bucket ou policy do FichasRPG deve ser alterado.

## Preparação e publicação

A migração `0015_player_profiles` cria os perfis e avaliações. A implementação
não aplica migrações no banco de produção, não publica imagens e não reinicia
serviços. A configuração local `.env` pode reaproveitar o acesso interno já
utilizado pelo FichasRPG; `.env.example` mantém credenciais vazias.

Antes de publicar, o usuário executa as duas suítes completas:

```bash
cd /home/pyu/docker/fred
./docker/test.sh -q
```

```bash
cd /home/pyu/docker/fred/frontend
pnpm install --frozen-lockfile
pnpm test
```

O bucket pode ser preparado separadamente, sem publicar o aplicativo. Para
repetir esse provisionamento em outro ambiente, usar uma imagem da API que
contenha esta implementação e criar exclusivamente o bucket do Fred:

```bash
cd /home/pyu/docker/fred
docker run --rm --network floci-internal --env-file .env \
  --entrypoint /app/.venv/bin/python fred-api:latest \
  -m app.profile_storage_setup
```

Esse comando deve usar a **nova imagem** com esta implementação. Ele cria o
bucket se necessário, ativa os quatro bloqueios públicos e remove eventual
policy do bucket do Fred. Não executar com a imagem antiga. A publicação do
serviço e a migração seguem o procedimento de deploy do projeto, depois da
aprovação das duas suítes completas.

## Critérios de aceite

- Perfil acessível sem sessão; original e mutações protegidos por sessão,
  vínculo e verificações existentes de origem/conta.
- Nenhum contato, dado financeiro, alias histórico, chave S3 ou autor de
  avaliação aparece na resposta pública.
- Edições de um jogador não modificam outro nem reconciliam listas antigas.
- Card com foto, nome, estrelas, partidas e acesso ao perfil, funcionando por teclado.
- Radar e estrelas respondem aos valores salvos; vazio não vira nota zero.
- Upload, recorte, troca e remoção mantêm coerência entre banco e objetos,
  inclusive em falhas de armazenamento.
- Testes criados devem ser executados pelo usuário; compilação e typecheck
  não substituem os resultados dessas suítes.
