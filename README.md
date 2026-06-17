# Fred

API para processar mensagens de lista mensal de assinantes do Volei Frederico.

## Stack

- **Python 3.12**
- **FastAPI** para a API HTTP
- **Uvicorn** como servidor ASGI
- **SQLAlchemy 2** com suporte assíncrono
- **asyncpg** como driver PostgreSQL
- **Alembic** para migrations
- **PostgreSQL 16** como banco de dados
- **Docker** e **Docker Compose** para ambiente local
- **uv** para gerenciamento de dependências e build da imagem
- **pytest** para testes

## O que o projeto faz

O serviço recebe uma mensagem de texto com a lista mensal de assinantes, interpreta o conteúdo e grava no banco a situação de cada posição da lista.

Hoje o fluxo implementado funciona assim:

1. A API recebe um texto em `POST /messages/process`.
2. O parser identifica o mês, o ano e as linhas numeradas da mensagem.
3. Cada linha vira um registro de assinante mensal.
4. O serviço cria, atualiza ou remove registros em `monthly_subscribers`.
5. A resposta informa o que foi criado, atualizado, removido ou mantido.

## Endpoints

- `GET /health`
  - Retorna `{"status":"ok"}` para health check.
- `POST /messages/process`
  - Processa a mensagem enviada no corpo da requisição.

Exemplo de payload:

```json
{
  "text": "LISTA DE ASSINANTES DO MES DE ABRIL\n1. pyu ✅\n2. Daniel ✅\n3. Grid ✅",
  "received_at": "2026-04-22T00:00:00"
}
```

## Modelo de dados

A tabela principal hoje é `monthly_subscribers`, com:

- `id`
- `position`
- `name`
- `normalized_name`
- `month`
- `year`
- `has_paid`
- `created_at`
- `updated_at`

Há uma restrição única por `month + year + position`, para manter uma posição por mês.

## Estrutura do projeto

- `app/main.py` - rotas FastAPI
- `app/parser.py` - leitura e normalização da mensagem
- `app/services.py` - regra de criação/atualização/exclusão
- `app/models.py` - modelos SQLAlchemy
- `app/schemas.py` - schemas Pydantic
- `app/database.py` - engine e sessão async
- `alembic/` - migrations
- `tests/` - testes do parser

## Configuração

Variável de ambiente principal:

- `DATABASE_URL`

Valor padrão para Docker Compose:

```env
DATABASE_URL=postgresql+asyncpg://fred:fred@postgres:5432/fred
```

O projeto está configurado para rodar a API dentro do Docker Compose. Por isso, o host do banco na URL é `postgres`, que é o nome do serviço PostgreSQL na rede Docker.

## Como rodar com Docker

```bash
docker compose up --build
```

Isso sobe:

- a API em `http://localhost:8000`
- o PostgreSQL em `localhost:5433`

## Rede local

Quando a API é consumida pelo Traefik local, ela também entra na rede externa `traefik-local` e fica acessível pelo alias `fred-api` dentro do Docker. Nessa rota, o acesso externo continua em `http://fred.localnetwork:8181`.

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

- O parser aceita mensagens com cabeçalho no formato `LISTA DE ASSINANTES DO MES DE ...`.
- Linhas numeradas sem nome são interpretadas como remoção da posição.
- O símbolo `✅` indica pagamento.
