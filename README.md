# A Ponte: um agente A2A com MCP por dentro

Entrega do desafio **A Ponte** (MBA Engenharia de Software com IA, curso de MCP e A2A).

Dois processos separados, conversando por HTTP:

| Processo | Porta | Endpoint | O que é |
|---|---|---|---|
| `servidor-mcp/` | `7301` | `/mcp` | Servidor MCP (Streamable HTTP) com 3 tools, 1 resource e o ciclo de MRTR na reserva |
| `agente/` | `7300` | `/a2a`, `/.well-known/agent-card.json` | Agente A2A v1.0 (JSON-RPC) que é host MCP por dentro. Sem LLM |

Stack: Python, pacote `mcp` **2.3.0** (revisão `2026-07-28` da spec) no servidor; `httpx`, `starlette` e `uvicorn` no agente. Versões travadas nos dois `pyproject.toml`.

## Como rodar

Pré-requisito: Python 3.10 ou superior. Os comandos abaixo partem de um clone limpo, na raiz do repositório.

**1. Ambiente e dependências** (um único venv atende os dois processos)

```bash
# Linux / macOS / Git Bash
python3 -m venv .venv
source .venv/bin/activate          # Git Bash no Windows: source .venv/Scripts/activate
pip install -e servidor-mcp -e agente
```

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e servidor-mcp -e agente
```

**2. Segredo do `requestState`.** Gere o seu e exporte antes de subir o servidor MCP. O valor nunca vai para o repositório (`.env` está no `.gitignore`):

```bash
export REQUEST_STATE_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

```powershell
$env:REQUEST_STATE_SECRET = python -c "import secrets; print(secrets.token_hex(32))"
```

Sem a variável, ou com menos de 32 bytes, o servidor se recusa a subir. Para o servidor sobreviver a um restart mantendo `requestState` válido, **reexporte o mesmo valor**. Um valor novo invalida os estados já emitidos.

**3. Servidor MCP** (terminal 1, deixe o stderr visível)

```bash
python -m central_salas
```

**4. Agente** (terminal 2, no mesmo venv)

```bash
python -m agente
```

**5. Validador** (terminal 3, com os dois processos recém-iniciados)

```bash
python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301
```

O validador deixa reservas no servidor. Para repetir a execução, reinicie os dois processos antes.

Variáveis opcionais (os padrões são os do enunciado): `MCP_PORT` (7301), `AGENTE_PORT` (7300), `MCP_URL` (`http://127.0.0.1:7301/mcp`, lido pelo agente) e `DADOS_DIR`.

### Fluxo manual

```bash
curl http://localhost:7300/.well-known/agent-card.json

curl -s -X POST http://localhost:7300/a2a -H 'Content-Type: application/json' \
  -H 'traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01' \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"messageId":"m1","role":"ROLE_USER","parts":[{"text":"reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 fim=2026-11-03T15:00:00-03:00 responsavel=Marty"}]}}}'
```

A Task volta em `TASK_STATE_INPUT_REQUIRED` com `alternativas: sala-fusca, sala-mirante`. Continue com o mesmo `taskId` e o texto `escolha=sala-mirante` (ou `escolha=recusar`).

## Onde a ponte acontece

Tudo está em `agente/src/agente/ponte.py`. **Ida:** em `Ponte._interpretar`, quando o resultado do `tools/call` tem `resultType: input_required`, o agente lê a chave de `inputRequests` e o `enum` da elicitation, guarda o `requestState` recebido na `Pausa` da Task (`agente/src/agente/tasks.py`) e leva a Task para `TASK_STATE_INPUT_REQUIRED`, com a mensagem `alternativas: <ids na ordem do enum>`. **Volta:** em `Ponte._continuar`, o `SendMessage` com `taskId` e `escolha=<id>` vira `inputResponses` na mesma chave (`accept` com `{"sala": <id>}`, ou `decline` para `recusar`), e `Ponte._chamar` repete o `tools/call` original com um **id de JSON-RPC novo** (sorteado a cada request em `mcp_cliente.py`) e o `requestState` ecoado sem abrir. O agente usa HTTP puro, sem o cliente do SDK, para enxergar o `input_required` cru em vez de deixar um callback de elicitation responder sozinho. Do lado do servidor, o `input_required` nasce no resolver `escolha_de_sala` (`servidor-mcp/src/central_salas/tools.py`), que **devolve** a pergunta em vez de chamar o cliente de volta.

## Decisões técnicas

**Proteção do `requestState`.** O servidor usa o `RequestStateSecurity` do SDK (`servidor-mcp/src/central_salas/estado.py`): o token é cifrado e autenticado com AES-GCM, chave derivada por HKDF da `REQUEST_STATE_SECRET`. Cifrar é opcional no enunciado, mas o SDK já entrega assim, e a adulteração é detectada: trocar um caractere devolve `-32602` (HTTP 400). Além da integridade, o selo amarra o token à janela de tempo, ao nome do servidor, à tool e a um digest dos argumentos. No retry, argumentos divergentes do pedido original são rejeitados. A chave vem de `REQUEST_STATE_SECRET` (hexadecimal, mínimo 32 bytes, validado na subida) e não há segredo no código. Como o estado viaja no token e o servidor não guarda nada entre o `input_required` e o retry, um retry depois de reiniciar o processo funciona, desde que a mesma chave seja reexportada.

**Validade.** 600 segundos (10 minutos), dentro da faixa de 5 a 30 minutos. Token expirado devolve `-32602`.

**Estado das Tasks.** Em memória no agente (`RepositorioDeTasks`, em `tasks.py`), um dicionário por `id`. O estado pausado (`requestState`, chave da elicitation, alternativas e argumentos originais) fica na própria Task, nunca em um slot global, então duas Tasks pausadas ao mesmo tempo não trocam de `requestState`. A serialização para A2A (`Task.para_a2a`) lista os campos explicitamente, e o `requestState` não aparece no card, nos artifacts, no histórico nem em erros. Tasks em estado terminal recusam novas mensagens com o erro `-32004`. Persistir Tasks em disco está fora de escopo, então elas se perdem no restart do agente.

**Fronteira entre os dois lados.** O agente não conhece regra de sala. Conflito, política e alternativas são decididos pelo servidor MCP. O agente lê a versão da política do resource `politica://uso` para o artifact e traduz os resultados em estados A2A: `complete` com reserva vira `COMPLETED`, `isError` vira `FAILED` com a mensagem exata da tool, e `decline` vira `CANCELED`. Um pedido fora do formato fixo termina em `TASK_STATE_REJECTED` (o enunciado não define esse caso).

**Observações sobre o SDK.**
- A chave de `inputRequests` é gerada pelo SDK (`central_salas.tools:escolha_de_sala`). O enunciado não a fixa, e o agente a devolve sem interpretar.
- Com uma única alternativa, o schema da elicitation usa `const` em vez de `enum`. O agente trata os dois.
- O log no stderr é um middleware do SDK. Requests que o SDK rejeita antes do roteamento (por exemplo `_meta` incompleto) respondem `-32602` mas não chegam a ser logados. Os requests com `tools/list`, `tools/call` e `resources/read` são todos registrados com método, id e `traceparent`.
- Reapresentar um `requestState` depois que o estado do mundo mudou (a sala escolhida já foi reservada) faz o resolver recalcular as alternativas e pedir de novo, com um `requestState` novo.

**Sem LLM e sem sessão.** Nenhuma dependência de provedor de LLM nos `pyproject.toml`. O agente decide por regra e os dois lados mandam `_meta` completo em cada request, sem inferir nada de requests anteriores.

## Saída do validador

Execução com os dois processos recém-iniciados, a partir de um clone limpo:

```text
SAIDA_DO_VALIDADOR
```
