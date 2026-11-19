# Instruções do projeto Fred

## Testes e entrega

- Crie ou atualize os testes necessários para cada alteração.
- Deixe a execução dos testes com o usuário. Não execute suítes automatizadas,
  testes individuais ou QA manual/no navegador, salvo solicitação expressa dele.
- Quando a implementação e os testes estiverem prontos, avise o usuário de que
  chegou a hora de executá-los e informe os comandos abaixo.
- Informe claramente que os testes ainda não foram executados. Não apresente
  build ou checagem de tipos como evidência de aprovação dos testes.
- Build, checagem de tipos e análise estática sem execução de testes podem ser
  usados para preparar a entrega.

## Comandos para o usuário executar

### Backend

```bash
cd /home/pyu/docker/fred
./docker/test.sh -q
```

O script constrói uma imagem de testes separada, cria PostgreSQL e rede Docker
temporários, aplica as migrações e executa a suíte completa, incluindo os testes
de integração. Ao encerrar, remove os recursos temporários. Não usa o banco,
os volumes ou a imagem de produção. Requer Docker disponível.

Argumentos adicionais são encaminhados ao pytest. Para executar só a suíte de
gestão:

```bash
./docker/test.sh -q tests/test_management_integration.py
```

### Frontend

```bash
cd /home/pyu/docker/fred/frontend
pnpm install --frozen-lockfile
pnpm test
```

Requer Node.js e pnpm nas versões indicadas pelo projeto.
