"""Cliente MCP puro: descobre, le a politica e completa o ciclo de MRTR na mao.

    python -m agente.demo_mcp sala-garagem 2026-11-03T14:00:00-03:00 2026-11-03T15:00:00-03:00 Marty
"""

from __future__ import annotations

import asyncio
import json
import sys

from .mcp_cliente import ClienteMcp, derivar_traceparent, e_input_required


async def main(sala: str, inicio: str, fim: str, responsavel: str) -> None:
    cliente = ClienteMcp()
    trace = derivar_traceparent(None)
    try:
        print("tools:", sorted(await cliente.descobrir(trace)))
        print("politica:", await cliente.versao_da_politica(trace))
        args = {"sala": sala, "inicio": inicio, "fim": fim, "responsavel": responsavel}
        resultado = await cliente.chamar_tool("reservar_sala", args, trace)
        while e_input_required(resultado):
            chave, pedido = next(iter(resultado["inputRequests"].items()))
            opcoes = pedido["params"]["requestedSchema"]["properties"]["sala"]
            escolha = (opcoes.get("enum") or [opcoes["const"]])[0]
            print(f"input_required: {chave} -> escolhendo {escolha}")
            resultado = await cliente.chamar_tool(
                "reservar_sala", args, trace,
                input_responses={chave: {"action": "accept", "content": {"sala": escolha}}},
                request_state=resultado["requestState"],
            )
        print(json.dumps(resultado.get("structuredContent"), indent=2, ensure_ascii=False))
    finally:
        await cliente.fechar()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:5]))
