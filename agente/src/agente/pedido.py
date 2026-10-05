"""Formatos fixos de entrada: nao ha linguagem natural e nao ha LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass

_RESERVA = re.compile(r"^\s*reservar\s+sala=(\S+)\s+inicio=(\S+)\s+fim=(\S+)\s+responsavel=(.+?)\s*$")
_ESCOLHA = re.compile(r"^\s*escolha=(\S+)\s*$")

FORMATO = "reservar sala=<id> inicio=<iso8601> fim=<iso8601> responsavel=<nome>"
RECUSAR = "recusar"


@dataclass(frozen=True)
class PedidoDeReserva:
    sala: str
    inicio: str
    fim: str
    responsavel: str

    def argumentos(self) -> dict:
        return {"sala": self.sala, "inicio": self.inicio, "fim": self.fim, "responsavel": self.responsavel}


def ler_reserva(texto: str) -> PedidoDeReserva | None:
    m = _RESERVA.match(texto)
    return PedidoDeReserva(*m.groups()) if m else None


def ler_escolha(texto: str) -> str | None:
    m = _ESCOLHA.match(texto)
    return m.group(1) if m else None
