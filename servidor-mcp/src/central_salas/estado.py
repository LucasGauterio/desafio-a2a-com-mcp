"""Protecao do requestState: chave vinda do ambiente, nunca do codigo."""

from __future__ import annotations

import os

from mcp.server.mcpserver import RequestStateSecurity

TTL_SEGUNDOS = 600.0  # 10 min, dentro da faixa de 5 a 30 min exigida
MIN_BYTES = 32


def seguranca_do_request_state() -> RequestStateSecurity:
    bruto = os.environ.get("REQUEST_STATE_SECRET", "").strip()
    if not bruto:
        raise SystemExit(
            "REQUEST_STATE_SECRET nao definido. Gere com: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )
    try:
        chave = bytes.fromhex(bruto)
    except ValueError:
        raise SystemExit("REQUEST_STATE_SECRET deve ser hexadecimal (token_hex(32))") from None
    if len(chave) < MIN_BYTES:
        raise SystemExit(f"REQUEST_STATE_SECRET precisa de no minimo {MIN_BYTES} bytes ({MIN_BYTES * 2} caracteres hex)")
    return RequestStateSecurity(keys=[chave], ttl=TTL_SEGUNDOS)
