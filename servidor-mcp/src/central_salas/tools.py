"""Tools e resource do servidor MCP."""

from __future__ import annotations

from pydantic import BaseModel

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import dominio


class SalaOut(BaseModel):
    id: str
    nome: str
    capacidade: int
    recursos: list[str]


class ListaDeSalas(BaseModel):
    salas: list[SalaOut]


class ConflitoOut(BaseModel):
    id: str
    inicio: str
    fim: str
    responsavel: str


class Disponibilidade(BaseModel):
    sala: str
    livre: bool
    conflitos: list[ConflitoOut]


class ReservaOut(BaseModel):
    reserva: str | None = None
    reservado: bool = True
    sala: str | None = None
    inicio: str | None = None
    fim: str | None = None
    responsavel: str | None = None
    politica: str | None = None
    motivo: str | None = None


def registrar(mcp: MCPServer) -> None:
    @mcp.tool()
    def listar_salas() -> ListaDeSalas:
        """Lista todas as salas com capacidade e recursos."""
        return ListaDeSalas(salas=[SalaOut(**s) for s in dominio.carregar_salas()])

    @mcp.tool()
    def consultar_disponibilidade(sala: str, inicio: str, fim: str) -> Disponibilidade:
        """Diz se uma sala esta livre no intervalo, e quais reservas conflitam."""
        try:
            _, intervalo = dominio.validar(sala, inicio, fim)
        except dominio.ErroDeRegra as e:
            raise ToolError(str(e)) from None
        ocupado = dominio.conflitos(sala, intervalo)
        return Disponibilidade(sala=sala, livre=not ocupado, conflitos=[ConflitoOut(**{k: r[k] for k in ConflitoOut.model_fields}) for r in ocupado])

    @mcp.tool()
    def reservar_sala(sala: str, inicio: str, fim: str, responsavel: str) -> ReservaOut:
        """Reserva uma sala. Se o intervalo estiver ocupado, pergunta qual alternativa usar."""
        try:
            dominio.validar(sala, inicio, fim)
        except dominio.ErroDeRegra as e:
            raise ToolError(str(e)) from None
        raise NotImplementedError("fase 3")

    @mcp.resource("politica://uso", mime_type="text/markdown")
    def politica_de_uso() -> str:
        """Politica de uso das salas."""
        return dominio.carregar_politica()
