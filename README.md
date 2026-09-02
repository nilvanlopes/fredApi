# Fred

API para processar listas mensais, presença semanal e exports de conversa do
WhatsApp do Volei Frederico.

## Stack

- **Python 3.12**
- **FastAPI** para a API HTTP
- **Uvicorn** como servidor ASGI
- **SQLAlchemy 2** com suporte assíncrono
- **asyncpg** como driver PostgreSQL
- **Alembic** para migrations
- **PostgreSQL 16** como banco de dados
- **Docker Swarm** para execução local via stack
- **Docker Compose** para build da imagem e comandos auxiliares
- **uv** para gerenciamento de dependências e build da imagem
- **pytest** para testes
- **MCP Python SDK** para consultas seguras do banco pela LLM

## O que o projeto faz

O serviço recebe uma mensagem de texto com a lista mensal de assinantes, interpreta o conteúdo e grava no banco a situação de cada posição da lista.

Hoje o fluxo implementado funciona assim:

1. A API recebe um texto em `POST /messages/process`.
2. O parser identifica o mês, o ano e as linhas numeradas da mensagem.
3. Cada linha vira um registro de assinante mensal.
4. O serviço cria, atualiza ou remove registros em `monthly_subscribers`.
5. A resposta informa o que foi criado, atualizado, removido ou mantido.

O importador de conversa lê o export do WhatsApp em ordem cronológica,
classifica cada mensagem e encaminha somente eventos validados para esses
mesmos serviços de domínio.

## Endpoints

- `GET /health`
  - Retorna `{"status":"ok"}` para health check.
- `POST /messages/process`
  - Processa a mensagem enviada no corpo da requisição.
- `POST /messages/monthly-subscribers/process`
  - Processa explicitamente uma lista mensal.
- `POST /messages/weekly-attendance/process`
  - Processa explicitamente uma lista semanal.
- `POST /weekly-attendance/promote-due`
  - Executa as promoções de convidados vencidas e retorna o texto atualizado
    da lista para envio ao WhatsApp.
- `GET /weekly-attendance/message`
  - Retorna o texto da lista persistida na data atual, após quaisquer promoções.
  - Aceita `game_date=YYYY-MM-DD` para consultar uma data específica.
- `GET /messages/templates/monthly-subscribers`
  - Gera a mensagem inicial de assinantes para o mês atual.
- `GET /messages/templates/weekly-attendance`
  - Gera a mensagem inicial da lista para a quarta-feira atual ou seguinte.
- `POST /conversation-imports`
  - Recebe um export UTF-8 do WhatsApp como `text/plain`.

Os endpoints de template aceitam `reference_date=YYYY-MM-DD` para pré-visualização
determinística. Sem o parâmetro, usam a data atual em `America/Sao_Paulo`. Eles
somente geram o texto; o agendamento fica no n8n e o envio é feito pelo WAHA.

Exemplo de payload:

```json
{
  "text": "LISTA DE ASSINANTES DO MES DE ABRIL\n1. pyu ✅\n2. Daniel ✅\n3. Grid ✅",
  "received_at": "2026-04-22T00:00:00"
}
```

## Importar uma conversa do WhatsApp

Execute primeiro em `preview`, que simula as alterações e faz rollback:

```bash
curl --data-binary @"/caminho/Conversa do WhatsApp.txt" \
  -H "Content-Type: text/plain; charset=utf-8" \
  "http://localhost:8001/conversation-imports?mode=preview&analysis_mode=hybrid&chat_id=fred"
```

Depois de revisar `changed_messages`, `review_required_messages`, `warnings` e
`results`, use `mode=apply` para confirmar uma única transação:

```bash
curl --data-binary @"/caminho/Conversa do WhatsApp.txt" \
  -H "Content-Type: text/plain; charset=utf-8" \
  "http://localhost:8001/conversation-imports?mode=apply&analysis_mode=hybrid&chat_id=fred"
```

Modos de análise:

- `rules`: usa somente formatos locais validados.
- `hybrid`: usa os parsers locais primeiro, manda para a IA somente mensagens
  que as regras ignoraram e usa IA para limpar nomes semanais finais. Sem
  provedor, executa as regras e inclui um aviso explícito na resposta.
- `ai`: exige provedor configurado; caso contrário retorna `503`.

O provedor deve expor uma API compatível com
`POST {CONVERSATION_AI_BASE_URL}/chat/completions`. Configure URL, modelo e,
quando necessário, chave em `.env`. O texto da conversa é tratado como dado não
confiável, e a IA nunca recebe acesso ao banco ou a ferramentas.

No modo `hybrid` ou `ai`, a IA tambem e usada para limpar semanticamente nomes
das listas semanais finais antes de salvar. Ela pode remover emojis e
observacoes como `depois das 20`, `mais tarde` ou `bem provavelmente`, mas a API
valida a resposta e rejeita qualquer limpeza que introduza tokens que nao
existiam no texto original.

Para usar o Ollama local compartilhado, a API pode subir o container sob demanda
quando `analysis_mode=hybrid` ou `analysis_mode=ai`. Por padrao ela usa o socket
Docker montado em `/var/run/docker.sock`, cria o container `fred-ollama`, usa o
volume `ollama_ollama-data`, garante o modelo configurado e para/remove o
container ao final se foi ela que iniciou. O fallback fora do container usa
`docker-compose.ollama.yml`. Quando `OLLAMA_ENABLE_GPU=true`, o container e
criado com reserva NVIDIA equivalente a `gpus: all`.

Cada evento mensal ou semanal aceito recebe um fingerprint por conversa.
Eventos já aplicados são ignorados em exports posteriores, e eventos mais
antigos que o último estado de um mês ou jogo são marcados como `stale` para
impedir regressão. Mensagens ignoradas ou pendentes continuam elegíveis para
reanálise quando o modelo ou o prompt mudar.

O importador tambem guarda a posicao da ultima mensagem mensal ou semanal com
status `applied` ou `unchanged`. Ao receber novamente o export completo da
conversa, ele inicia o processamento depois dessa posicao, evitando reanalisar
todo o historico. Mensagens em revisao e transacoes que falharam nao avancam
essa posicao.

Listas semanais sem data explicita sao agrupadas na quarta-feira atual/proxima.
Quando varias versoes da mesma lista aparecem no export, somente a ultima versao
daquela quarta-feira atualiza o banco; as anteriores ficam como `stale`.

## Modelo de dados

A tabela principal hoje é `monthly_subscribers`, com:

- `id`
- `position`
- `name`
- `normalized_name`

## Aliases de nomes

Apelidos podem ser cadastrados pela API e passam a alimentar o `normalized_name`
nas próximas mensagens. O cadastro também atualiza os registros materializados
existentes, incluindo `invited_by` semanal, sem alterar o texto original do
ledger de mensagens processadas:

```bash
curl -X POST http://localhost:8001/person-aliases \
  -H 'Content-Type: application/json' \
  -d '{"alias":"moges","canonical_name":"Gomes"}'
```

O nome recebido continua no campo `name`; somente sua forma normalizada passa a
ser `gomes`. Aliases já cadastrados ou conflitos retornam `409`.
- `month`
- `year`
- `has_paid`
- `created_at`
- `updated_at`

Há uma restrição única por `month + year + position`, para manter uma posição por mês.

As listas semanais ficam em `weekly_attendances` e
`weekly_attendance_entries`. Quando um nome vem com emoji numerico de time,
como `Leal(conv)3️⃣`, o nome e limpo e o time pre-montado e salvo na coluna
`weekly_attendance_entries.prebuilt_team_number`.

## Estrutura do projeto

- `app/main.py` - rotas FastAPI
- `app/parser.py` - leitura e normalização da mensagem
- `app/services.py` - regra de criação/atualização/exclusão
- `app/models.py` - modelos SQLAlchemy
- `app/schemas.py` - schemas Pydantic
- `app/database.py` - engine e sessão async
- `app/mcp_server.py` - servidor MCP somente leitura para consultas do Fred
- `alembic/` - migrations
- `tests/` - testes do parser

## MCP do Fred

O Fred inclui um servidor MCP separado da API HTTP. Ele expõe somente
ferramentas de domínio e nunca aceita SQL arbitrário ou operações de escrita.
As ferramentas disponíveis são:

- `get_weekly_attendance`: consulta a lista principal e a fila de espera.
- `list_waiting_guests`: consulta os convidados que ainda aguardam vaga.
- `get_monthly_subscribers`: consulta os assinantes de um mês e ano.
- `search_person`: busca uma pessoa nas listas mensais e semanais.

O servidor roda dentro do Docker e usa a mesma `DATABASE_URL` do serviço da
API. Depois de subir o Fred e construir a imagem, o cliente MCP pode iniciar o
servidor por stdio com:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml run --rm -T mcp
```

Para clientes que aceitam configuração de comando, use o equivalente:

```json
{
  "mcpServers": {
    "fred": {
      "command": "docker",
      "args": [
        "compose", "-f", "/caminho/para/fred/docker-compose.yml",
        "-f", "/caminho/para/fred/docker-compose.mcp.yml",
        "run", "--rm", "-T", "mcp"
      ]
    }
  }
}
```

O cliente envia perguntas como “quem está aguardando vaga nesta quarta?”;
a LLM escolhe a ferramenta apropriada e recebe dados estruturados do Fred.
Credenciais do banco permanecem dentro do ambiente Docker.

## Configuração

Variável de ambiente principal:

- `DATABASE_URL`

Variáveis do importador:

- `CONVERSATION_IMPORT_MAX_BYTES`
- `CONVERSATION_AI_BASE_URL`
- `CONVERSATION_AI_API_KEY`
- `CONVERSATION_AI_MODEL`
- `CONVERSATION_AI_CONFIDENCE_THRESHOLD`
- `CONVERSATION_AI_BATCH_MESSAGES`
- `CONVERSATION_AI_BATCH_CHARS`
- `CONVERSATION_AI_ATTEMPTS`
- `CONVERSATION_AI_TIMEOUT_SECONDS`
- `OLLAMA_MANAGE_SERVICE`
- `OLLAMA_SHUTDOWN_WHEN_DONE`
- `OLLAMA_PULL_MODEL_WHEN_MISSING`
- `OLLAMA_ENABLE_GPU`
- `OLLAMA_STARTUP_TIMEOUT_SECONDS`
- `OLLAMA_POLL_INTERVAL_SECONDS`
- `OLLAMA_COMPOSE_FILE`
- `OLLAMA_DOCKER_SOCKET`
- `OLLAMA_CONTAINER_NAME`
- `OLLAMA_IMAGE`
- `OLLAMA_VOLUME`

Valor padrão para Docker Compose:

```env
DATABASE_URL=postgresql+asyncpg://fred:fred@postgres:5432/fred
```

O projeto está configurado para rodar a API dentro do Docker Compose. Por isso, o host do banco na URL é `postgres`, que é o nome do serviço PostgreSQL na rede Docker.

## Como rodar com Docker Swarm

```bash
docker swarm init
docker network create --driver=overlay --attachable traefik-local
docker compose build api
docker stack deploy --detach=true -c docker-compose.yml fred
```

Isso sobe:

- a API em `http://localhost:8001` no host, encaminhando para `8000` dentro do container
- o PostgreSQL em `localhost:5433`

Se o Swarm ja estiver inicializado ou a rede ja existir, os dois primeiros
comandos podem retornar erro de recurso existente; nesse caso siga para o build
e o deploy da stack.

Para ver o estado dos servicos:

```bash
docker stack services fred
docker service ps fred_api
```

Para acompanhar logs:

```bash
docker service logs -f fred_api
```

## Rede local

Quando a API é consumida pelo Traefik local, ela também entra na rede externa `traefik-local` e fica acessível pelo alias `fred-api` dentro do Docker Swarm. Nessa rota, o acesso externo continua em `http://fred.localnetwork:8181`.

Para subir esse modo, use `make deploy-fred` no repositório raiz `docker/`. Esse fluxo publica o Fred como stack no Swarm para que o Traefik local consiga resolver o alias via rede overlay.

## Testes

```bash
docker compose run --rm api pytest
```

## Migrations

Aplicar migrations:

```bash
docker compose run --rm api alembic upgrade head
```

Criar uma nova migration:

```bash
docker compose run --rm api alembic revision --autogenerate -m "descricao"
```

## Observações

- O parser mensal aceita `LISTA DE ASSINANTES DO MES DE ...`,
  `Lista pagamento mensal Frederico`, `Lista Pagamento Frederico` e
  `Lista Participantes`.
- O parser semanal aceita `LISTA VOLEI FREDERICO DD/MM` e o formato histórico
  `Volei Frederico 19h30`, usando o timestamp do export quando a data não existe
  no cabeçalho.
- Em listas semanais, sufixos com emoji numerico, como `3️⃣`, indicam time
  pre-montado no grupo do WhatsApp.
- Linhas numeradas sem nome são interpretadas como remoção da posição.
- Na lista semanal, linha com posicao `0` e ignorada porque nao e posicao valida.
- O símbolo `✅` indica pagamento.
