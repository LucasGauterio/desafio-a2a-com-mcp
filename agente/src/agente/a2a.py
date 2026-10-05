"""Servidor A2A v1.0 (binding JSON-RPC): Agent Card, SendMessage e GetTask."""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .mcp_cliente import ClienteMcp
from .ponte import ErroA2A, Ponte
from .tasks import RepositorioDeTasks


def agent_card(base_url: str) -> dict:
    return {
        "name": "Central de Salas",
        "description": "Reserva salas de reuniao da Hill Valley Tech.",
        "provider": {"organization": "Hill Valley Tech", "url": "https://hillvalley.example"},
        "version": "1.0.0",
        "supportedInterfaces": [{"url": f"{base_url}/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "reservar-sala",
                "name": "Reservar sala",
                "description": "Reserva uma sala em um intervalo. Se houver conflito, pergunta qual alternativa usar.",
                "tags": ["salas", "agenda"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
                "examples": [
                    "reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 "
                    "fim=2026-11-03T15:00:00-03:00 responsavel=Marty"
                ],
            }
        ],
    }


def _erro(id_: object, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})


async def card(request: Request) -> JSONResponse:
    return JSONResponse(agent_card(str(request.base_url).rstrip("/")))


async def rpc(request: Request) -> JSONResponse:
    try:
        corpo = await request.json()
    except json.JSONDecodeError:
        return _erro(None, -32700, "JSON invalido")
    if not isinstance(corpo, dict) or corpo.get("jsonrpc") != "2.0" or not isinstance(corpo.get("method"), str):
        return _erro(corpo.get("id") if isinstance(corpo, dict) else None, -32600, "Requisicao JSON-RPC invalida")
    id_, metodo = corpo.get("id"), corpo["method"]
    params = corpo.get("params")
    params = params if isinstance(params, dict) else {}
    ponte: Ponte = request.app.state.ponte
    try:
        if metodo == "SendMessage":
            mensagem = params.get("message")
            if not isinstance(mensagem, dict) or not isinstance(mensagem.get("parts"), list):
                return _erro(id_, -32602, "params.message com parts e obrigatorio")
            task = await ponte.enviar(mensagem, request.headers.get("traceparent"))
            return JSONResponse({"jsonrpc": "2.0", "id": id_, "result": {"task": task.para_a2a()}})
        if metodo == "GetTask":
            task = ponte.repo.obter(str(params.get("id", "")))
            if task is None:
                return _erro(id_, -32001, f"Task nao encontrada: {params.get('id')}")
            return JSONResponse({"jsonrpc": "2.0", "id": id_, "result": {"task": task.para_a2a()}})
    except ErroA2A as e:
        return _erro(id_, e.code, e.message)
    return _erro(id_, -32601, f"Metodo nao suportado: {metodo}")


@asynccontextmanager
async def lifespan(app: Starlette):
    mcp = ClienteMcp()
    app.state.ponte = Ponte(mcp, RepositorioDeTasks())
    yield
    await mcp.fechar()


app = Starlette(
    routes=[Route("/.well-known/agent-card.json", card), Route("/a2a", rpc, methods=["POST"])],
    lifespan=lifespan,
)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("AGENTE_PORT", "7300")))
