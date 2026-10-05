# Plano de implementação: A Ponte (A2A + MCP)

Baseado no README do desafio, no `validador/validar.py` e nos exemplos de `exemplos/wire/`.

## Decisões prévias

| Decisão | Recomendação | Por quê |
|---|---|---|
| Linguagem | **Python** (pacote `mcp` v2) | Os exemplos de wire foram capturados de um servidor Python: `__main__:escolha_de_sala` como chave de `inputRequests`, `listar_salasArguments` nos schemas, `ReservaOut` com defaults nulos. Seguir o SDK que gerou o contrato reduz divergências. |
| Lado A2A | **JSON-RPC escrito à mão** sobre Starlette/uvicorn | São só dois métodos (`SendMessage`, `GetTask`), mais o card. A máquina de estados da Task é o que está sendo avaliado, e um SDK A2A esconderia justamente isso. |
| Cliente MCP do agente | **`httpx` direto**, sem o cliente do SDK | O agente precisa ver o `input_required` cru e controlar `_meta`, os headers `Mcp-*` e o id do retry. O cliente do SDK com callback de elicitation responderia sozinho e o ciclo nunca voltaria ao A2A. |
| Estado das Tasks | Dicionário em memória no agente, protegido por lock | Persistência em disco está fora de escopo. Só o `requestState` precisa sobreviver a restart, e ele vive no servidor MCP via HMAC. |

**Primeiro passo técnico:** conferir no Context7 e no PyPI a versão exata do `mcp` v2 (revisão `2026-07-28`), o nome do helper de `requestState` assinado e a API de `input_required`. Só depois travar as versões no `pyproject.toml`.

## Estrutura de arquivos

```
servidor-mcp/
  pyproject.toml
  src/central_salas/
    __main__.py      # sobe na 7301, logging em stderr
    dominio.py       # carga dos JSON, política, conflito, alternativas
    tools.py         # listar_salas, consultar_disponibilidade, reservar_sala
    estado.py        # requestState (HMAC + exp 10 min), lê REQUEST_STATE_SECRET
agente/
  pyproject.toml
  src/agente/
    __main__.py      # sobe na 7300
    a2a.py           # card, JSON-RPC, SendMessage, GetTask
    tasks.py         # máquina de estados + store por Task
    mcp_cliente.py   # host MCP: tools/list, resources/read, tools/call cru
    pedido.py        # parser de "reservar ..." e "escolha=..."
README.md, .gitignore (.env já ignorado)
```

## Fases

Cada fase tem um critério de saída verificável.

### Fase 0: Setup
- Fork do starter, clone, venvs por pacote e versões travadas.
- Gerar `REQUEST_STATE_SECRET` localmente (`python -c "import secrets; print(secrets.token_hex(32))"`) e exportar. Nunca commitar o valor.
- **Saída:** `pip install` limpo nos dois pacotes.

### Fase 1: Servidor MCP, base
- Streamable HTTP na 7301, endpoint `/mcp`, capabilities `tools` e `resources`.
- Middleware que valida `_meta` (`protocolVersion` e `clientCapabilities`). Se faltar, responde `-32602` com HTTP 400. Também valida os headers espelhados (`-32020`).
- Log em stderr por request: `método id traceparent`.
- `listar_salas` com `outputSchema` e `structuredContent` idêntico ao texto.
- Resource `politica://uso` (`text/markdown`). URI inexistente devolve `-32602`.
- **Saída:** checks **1–8** do validador.

### Fase 2: Domínio e validações
- `dominio.py`: parse de ISO 8601 com offset. A janela 08:00–20:00 é avaliada em `-03:00`, e vale para início **e** fim.
- Ordem das validações (a mesma na reserva e na consulta): sala, intervalo invertido, janela, duração.
- `consultar_disponibilidade` devolve `livre` e `conflitos`.
- Alternativas: salas livres com capacidade ≥ a pedida, ordenadas por (capacidade, id), no máximo 3.
- **Saída:** checks **9–12**.

### Fase 3: `reservar_sala` e MRTR
1. Caminho feliz: cria `res-000N`, devolve o `structuredContent` completo (`reserva`, `reservado`, `sala`, `inicio`, `fim`, `responsavel`, `politica`, `motivo`).
2. Conflito: `input_required` com uma entrada de elicitation em form mode, `requestedSchema` plano com `enum`. Sem alternativas, devolve `isError` com `Sem alternativas disponiveis no intervalo`.
3. `requestState`: payload com os argumentos selados e a exp, mais HMAC-SHA256 com o secret do env. Preferir o utilitário do SDK, se existir. Falha na verificação ou expiração devolve `-32602`.
4. Retry: reconstruir tudo **a partir do estado selado**. Os argumentos reenviados são ignorados (cobre o check 18). `accept` reserva na sala escolhida. `decline` ou `cancel` devolve `reservado=false, motivo="recusado"`.
5. Checagem de capability: sem `elicitation.form`, o conflito devolve `-32021` com `data.requiredCapabilities` e HTTP 400.
6. **Saída:** checks **13–20**. Depois reiniciar o servidor no meio do ciclo para confirmar que o retry ainda funciona (passo 12 do avaliador).

### Fase 4: Agente como cliente MCP puro
- Script que faz `tools/list`, lê `politica://uso` e extrai a versão da 1ª linha. Depois chama `reservar_sala`, vê o `input_required` cru e completa o retry com id novo.
- Todo request leva `_meta` (versão, `clientInfo`, capability `{"elicitation":{"form":{}}}`, `traceparent`) e os headers `MCP-Protocol-Version`, `Mcp-Method` e `Mcp-Name`.
- O cliente é um objeto `httpx` vivo, sem estado de protocolo. O `traceparent` entra como parâmetro por chamada.
- **Saída:** log do servidor mostra `tools/list` antes do primeiro `tools/call`.

### Fase 5: Agente como servidor A2A
- `GET /.well-known/agent-card.json`, copiando a forma de `07-a2a-agent-card.json` (`supportedInterfaces[].protocolBinding`, `protocolVersion: "1.0"`, skill `reservar-sala`).
- `POST /a2a`: `SendMessage` e `GetTask` em JSON-RPC.
- Task nova: `id` e `contextId` próprios, `SUBMITTED` → `WORKING` → terminal, com `history` e `artifacts`.
- Mapeamento de resultados:
  - sucesso → `COMPLETED` com o artifact `reserva` (JSON com `politica`)
  - `isError` → `FAILED` com a mensagem exata da tool em `status.message`
- `SendMessage` com `taskId` de Task terminal devolve `error` JSON-RPC.
- **Saída:** checks **21–26, 31 e 35**.

### Fase 6: A ponte
- Ao receber `input_required`, o agente guarda `{requestState, chave, enum, args originais, traceparent}` **na Task**, nunca em um slot global. A Task vai para `INPUT_REQUIRED` com a mensagem exata `alternativas: a, b, c`.
- `escolha=<id>` válido: novo `tools/call` com **id diferente**, `inputResponses` com a mesma chave e o `requestState` ecoado sem abrir.
- `escolha` fora do `enum`: continua em `INPUT_REQUIRED` e repete a lista.
- `escolha=recusar`: `decline` e a Task vai para `CANCELED`.
- O `requestState` nunca aparece em card, artifact, histórico ou erro.
- **Saída:** checks **27–34 e 36**.

### Fase 7: Fechamento
- Rodar o validador com os dois processos **recém-iniciados**: 36/36 e exit code 0.
- Passar os 13 passos do "Fluxo do avaliador" manualmente. Os passos 11 a 13 (adulterar o estado, reiniciar o servidor, tirar a capability) o validador não cobre.
- Conferir `git status` em `dados/`, `validador/` e `exemplos/`, que devem estar intactos.
- README com as 4 seções: como rodar a partir de um clone limpo, onde a ponte acontece (arquivo e função), decisões técnicas e a saída completa do validador.
- Clone limpo em outra pasta, seguir só o README e dar push na `main`.

## Armadilhas que o validador cobra

- **Check 18:** o retry vem com `sala-mirante` às 13h e `responsavel=Biff`, mas o estado selado diz garagem, 09:00 e Doc. Os valores selados têm que vencer.
- **Check 17:** adulterar os últimos 6 caracteres da assinatura tem que dar `-32602`, e não erro 500.
- **Check 33:** o store por Task é o que evita a troca de `requestState` entre duas pausas simultâneas.
- **Check 34:** o validador procura os primeiros 40 caracteres do `requestState` em qualquer resposta do agente.
- **Check 36:** depende da reserva do check 24 (`sala-porao`, 09:00). A pausa precisa ser byte a byte igual nas duas chamadas.
- **Idempotência da execução:** as reservas ficam em memória, então rodar o validador duas vezes sem reiniciar gera falso negativo.
- **Checks 4 e 5:** devem responder HTTP 400 no próprio transporte, antes do roteamento da tool.

## Risco principal

Se o `mcp` v2 não expuser `input_required` e o helper de `requestState` como o README sugere, **documentar a limitação no README com a evidência** em vez de reescrever o protocolo, como o enunciado pede. Por isso a verificação de versão e API vem antes de tudo.
