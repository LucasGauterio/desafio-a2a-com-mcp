"""Sobe o servidor MCP (Streamable HTTP) na porta 7301."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from mcp.server import MCPServer, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult

from . import estado, tools

log = logging.getLogger("central_salas")


async def registrar_request(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
    """Uma linha no stderr por request: metodo, id e traceparent do _meta."""
    params = ctx.params if isinstance(ctx.params, dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    log.info("request metodo=%s id=%s traceparent=%s", ctx.method, ctx.request_id, meta.get("traceparent", "-"))
    return await call_next(ctx)


def criar_servidor() -> MCPServer:
    mcp = MCPServer("central-de-salas", version="1.0.0", request_state_security=estado.seguranca_do_request_state(), middleware=[registrar_request])
    tools.registrar(mcp)
    return mcp


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    porta = int(os.environ.get("MCP_PORT", "7301"))
    criar_servidor().run(transport="streamable-http", host="127.0.0.1", port=porta)


if __name__ == "__main__":
    main()
