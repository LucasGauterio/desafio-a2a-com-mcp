"""A ponte: onde o `input_required` do MCP vira TASK_STATE_INPUT_REQUIRED, e volta.

Duas costuras, uma em cada sentido:

* `_interpretar`: recebe o resultado do `tools/call`. Se for `input_required`, guarda o
  `requestState` na Task (`Pausa`) e pausa a Task, devolvendo as alternativas ao cliente A2A.
* `_continuar`: recebe o `escolha=...` do cliente A2A, repete o `tools/call` com id novo,
  `inputResponses` na mesma chave e o `requestState` ecoado sem modificacao.

O agente traduz protocolo, nao dominio: conflito, politica e alternativas sao do servidor.
"""

from __future__ import annotations

import json
import logging

import httpx

from . import pedido
from .mcp_cliente import ClienteMcp, ErroMcp, derivar_traceparent, e_input_required
from .tasks import (
    CANCELED,
    COMPLETED,
    FAILED,
    INPUT_REQUIRED,
    REJECTED,
    TERMINAIS,
    WORKING,
    Pausa,
    RepositorioDeTasks,
    Task,
    novo_id,
)

log = logging.getLogger("agente.ponte")

TOOL = "reservar_sala"


class ErroA2A(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _texto(mensagem: dict) -> str:
    return " ".join(p.get("text", "") for p in mensagem.get("parts", []) if isinstance(p, dict))


def _texto_da_tool(resultado: dict) -> str:
    return " ".join(c.get("text", "") for c in resultado.get("content", []) if c.get("type") == "text")


class Ponte:
    def __init__(self, mcp: ClienteMcp, repositorio: RepositorioDeTasks) -> None:
        self.mcp = mcp
        self.repo = repositorio

    # -- SendMessage ----------------------------------------------------------

    async def enviar(self, mensagem: dict, traceparent: str | None) -> Task:
        task_id = mensagem.get("taskId")
        if not task_id:
            return await self._abrir(mensagem, traceparent)
        task = self.repo.obter(task_id)
        if task is None:
            raise ErroA2A(-32001, f"Task nao encontrada: {task_id}")
        return await self._continuar(task, mensagem, traceparent)

    async def _abrir(self, mensagem: dict, traceparent: str | None) -> Task:
        task = self.repo.criar(mensagem.get("contextId"))
        task.traceparent = traceparent
        task.history.append(mensagem)
        pedido_reserva = pedido.ler_reserva(_texto(mensagem))
        if pedido_reserva is None:
            task.transitar(REJECTED, f"Pedido invalido. Formato esperado: {pedido.FORMATO}")
            return task
        task.transitar(WORKING)
        await self._chamar(task, pedido_reserva.argumentos(), traceparent)
        return task

    async def _continuar(self, task: Task, mensagem: dict, traceparent: str | None) -> Task:
        if task.estado in TERMINAIS:
            raise ErroA2A(-32004, f"Task {task.id} esta em estado terminal ({task.estado}) e nao aceita mensagens")
        if task.estado != INPUT_REQUIRED or task.pausa is None:
            raise ErroA2A(-32004, f"Task {task.id} esta em {task.estado} e nao aguarda resposta")
        task.history.append(mensagem)
        pausa = task.pausa
        escolha = pedido.ler_escolha(_texto(mensagem))
        if escolha is None or (escolha != pedido.RECUSAR and escolha not in pausa.alternativas):
            # escolha fora do enum: a Task continua pausada e repete a lista
            task.transitar(INPUT_REQUIRED, self._linha_de_alternativas(pausa))
            return task
        if escolha == pedido.RECUSAR:
            resposta = {"action": "decline"}
        else:
            resposta = {"action": "accept", "content": {"sala": escolha}}
        task.pausa = None
        task.transitar(WORKING)
        # PONTE, volta: mesmo tools/call, id novo (o cliente MCP sorteia um por request),
        # inputResponses na MESMA chave de inputRequests e requestState ecoado sem abrir
        await self._chamar(
            task,
            pausa.argumentos,
            traceparent or task.traceparent,
            input_responses={pausa.chave: resposta},
            request_state=pausa.request_state,
        )
        return task

    # -- chamada ao servidor MCP ---------------------------------------------

    async def _chamar(
        self,
        task: Task,
        argumentos: dict,
        traceparent: str | None,
        input_responses: dict | None = None,
        request_state: str | None = None,
    ) -> None:
        try:
            resultado = await self.mcp.chamar_tool(
                TOOL, argumentos, derivar_traceparent(traceparent), input_responses, request_state
            )
            await self._interpretar(task, resultado, argumentos, traceparent)
        except ErroMcp as e:
            log.warning("erro de protocolo do servidor MCP: %s", e)
            task.transitar(FAILED, f"Erro do servidor MCP ({e.code}): {e.message}")
        except httpx.HTTPError as e:
            log.warning("servidor MCP inacessivel: %s", e)
            task.transitar(FAILED, "Servidor MCP indisponivel")

    async def _interpretar(self, task: Task, resultado: dict, argumentos: dict, traceparent: str | None) -> None:
        if e_input_required(resultado):
            # PONTE, ida: o input_required do MCP vira pausa da Task
            chave, requisicao = next(iter(resultado["inputRequests"].items()))
            campo = requisicao["params"]["requestedSchema"]["properties"]["sala"]
            alternativas = campo.get("enum") or [campo["const"]]
            task.pausa = Pausa(
                request_state=resultado["requestState"],
                chave=chave,
                alternativas=list(alternativas),
                argumentos=argumentos,
            )
            task.transitar(INPUT_REQUIRED, self._linha_de_alternativas(task.pausa))
            return
        if resultado.get("isError"):
            task.transitar(FAILED, _texto_da_tool(resultado))
            return
        dados = resultado.get("structuredContent") or {}
        if not dados.get("reservado"):
            task.transitar(CANCELED, f"Reserva nao realizada: {dados.get('motivo') or 'recusada'}")
            return
        politica = await self.mcp.versao_da_politica(derivar_traceparent(traceparent))
        reserva = {
            "reserva": dados["reserva"],
            "sala": dados["sala"],
            "inicio": dados["inicio"],
            "fim": dados["fim"],
            "responsavel": dados["responsavel"],
            "politica": politica,
        }
        task.artifacts.append(
            {"artifactId": novo_id("art"), "name": "reserva", "parts": [{"text": json.dumps(reserva)}]}
        )
        task.transitar(COMPLETED, f"Reserva {reserva['reserva']} confirmada na {reserva['sala']}.")

    @staticmethod
    def _linha_de_alternativas(pausa: Pausa) -> str:
        return "alternativas: " + ", ".join(pausa.alternativas)
