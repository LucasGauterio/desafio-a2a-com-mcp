"""Host MCP: fala com o servidor por HTTP puro, sem o cliente do SDK.

O cliente do SDK, com callback de elicitation, responderia a pergunta sozinho e o ciclo
nunca voltaria ao cliente A2A. Aqui o agente enxerga o `input_required` cru. Nenhum estado
de protocolo e guardado entre chamadas: cada request carrega a sua propria `_meta`.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from typing import Any

import httpx

PROTOCOLO = "2026-07-28"
CAPABILITIES = {"elicitation": {"form": {}}}
CLIENT_INFO = {"name": "agente-central-de-salas", "version": "1.0.0"}
URL_PADRAO = "http://127.0.0.1:7301/mcp"


class ErroMcp(Exception):
    """Erro de protocolo (`error` do JSON-RPC) devolvido pelo servidor MCP."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.data = code, message, data


def derivar_traceparent(recebido: str | None) -> str:
    """Mantem o trace-id do cliente A2A e sorteia um span-id novo; sem entrada, abre um trace."""
    partes = (recebido or "").split("-")
    if len(partes) == 4 and len(partes[1]) == 32:
        trace_id, flags = partes[1], partes[3]
    else:
        trace_id, flags = secrets.token_hex(16), "01"
    return f"00-{trace_id}-{secrets.token_hex(8)}-{flags}"


def e_input_required(resultado: dict) -> bool:
    return resultado.get("resultType") == "input_required"


class ClienteMcp:
    def __init__(self, url: str | None = None, http: httpx.AsyncClient | None = None) -> None:
        self.url = url or os.environ.get("MCP_URL", URL_PADRAO)
        self._http = http or httpx.AsyncClient(timeout=30)
        self._tools: dict[str, dict] | None = None
        self._descoberta = asyncio.Lock()

    async def fechar(self) -> None:
        await self._http.aclose()

    async def _request(self, metodo: str, params: dict, nome: str | None, traceparent: str | None) -> dict:
        meta: dict[str, Any] = {
            "io.modelcontextprotocol/protocolVersion": PROTOCOLO,
            "io.modelcontextprotocol/clientInfo": CLIENT_INFO,
            "io.modelcontextprotocol/clientCapabilities": CAPABILITIES,
        }
        if traceparent:
            meta["traceparent"] = traceparent
        cabecalhos = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOLO,
            "Mcp-Method": metodo,
        }
        if nome:
            cabecalhos["Mcp-Name"] = nome
        # id novo a cada request, inclusive no retry: sao requests independentes
        corpo = {"jsonrpc": "2.0", "id": secrets.token_hex(8), "method": metodo, "params": {**params, "_meta": meta}}
        resposta = await self._http.post(self.url, json=corpo, headers=cabecalhos)
        dados = resposta.json()
        if "error" in dados:
            erro = dados["error"]
            raise ErroMcp(erro.get("code", -32603), erro.get("message", ""), erro.get("data"))
        return dados["result"]

    async def descobrir(self, traceparent: str | None = None) -> dict[str, dict]:
        """`tools/list` em runtime, antes da primeira chamada; nao ha lista fixa no codigo."""
        async with self._descoberta:
            if self._tools is None:
                resultado = await self._request("tools/list", {}, None, traceparent)
                self._tools = {t["name"]: t for t in resultado.get("tools", [])}
            return self._tools

    async def versao_da_politica(self, traceparent: str | None = None) -> str:
        """Le o resource `politica://uso` e extrai a versao declarada na primeira linha."""
        resultado = await self._request("resources/read", {"uri": "politica://uso"}, "politica://uso", traceparent)
        texto = resultado["contents"][0]["text"]
        return texto.splitlines()[0].split(":", 1)[1].strip()

    async def chamar_tool(
        self,
        nome: str,
        argumentos: dict,
        traceparent: str | None = None,
        input_responses: dict | None = None,
        request_state: str | None = None,
    ) -> dict:
        """`tools/call` cru. Devolve o resultado como veio, `input_required` incluido."""
        tools = await self.descobrir(traceparent)
        if nome not in tools:
            raise ErroMcp(-32602, f"o servidor nao expoe a tool {nome!r}")
        params: dict[str, Any] = {"name": nome, "arguments": argumentos}
        if input_responses is not None:
            params["inputResponses"] = input_responses
        if request_state is not None:
            params["requestState"] = request_state  # opaco: ecoado sem abrir
        return await self._request("tools/call", params, nome, traceparent)
