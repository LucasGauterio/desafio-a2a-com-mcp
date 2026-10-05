"""Tools e resource do servidor MCP."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, create_model

from mcp.server import MCPServer
from mcp.server.mcpserver import AcceptedElicitation, Elicit, ElicitationResult, Resolve
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


def _escolha_de(alternativas: list[str]) -> type[BaseModel]:
    """Schema plano da elicitation: uma propriedade `sala` restrita as alternativas."""
    return create_model(
        "EscolhaDeSala",
        sala=(Literal[tuple(alternativas)], Field(title="Sala", description="Sala alternativa escolhida")),  # type: ignore[valid-type]
    )


class SalaLivre(BaseModel):
    """Resultado do resolver quando nao ha conflito: nada a perguntar."""

    sala: str


async def escolha_de_sala(sala: str, inicio: str, fim: str) -> Any:
    """Resolver: so pergunta quando o intervalo pedido conflita; devolve, nao chama de volta."""
    try:
        dados_sala, intervalo = dominio.validar(sala, inicio, fim)
    except dominio.ErroDeRegra as e:
        raise ToolError(str(e)) from None
    if not dominio.conflitos(sala, intervalo):
        return SalaLivre(sala=sala)
    alternativas = dominio.alternativas(dados_sala, intervalo)
    if not alternativas:
        raise ToolError(dominio.ERRO_SEM_ALTERNATIVAS)
    return Elicit("A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa.", _escolha_de(alternativas))


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
    async def reservar_sala(
        sala: str,
        inicio: str,
        fim: str,
        responsavel: str,
        escolha: Annotated[ElicitationResult[BaseModel], Resolve(escolha_de_sala)],
    ) -> ReservaOut:
        """Reserva uma sala. Se o intervalo estiver ocupado, pergunta qual alternativa usar."""
        if not isinstance(escolha, AcceptedElicitation):  # decline ou cancel: conclui sem reservar, sem erro
            return ReservaOut(reservado=False, motivo="recusado")
        destino = escolha.data.sala  # a propria sala (livre) ou a alternativa escolhida
        try:
            _, intervalo = dominio.validar(destino, inicio, fim)
        except dominio.ErroDeRegra as e:
            raise ToolError(str(e)) from None
        if dominio.conflitos(destino, intervalo):
            raise ToolError(dominio.ERRO_SEM_ALTERNATIVAS)
        reserva = dominio.criar_reserva(destino, inicio, fim, responsavel)
        politica = dominio.versao_da_politica(dominio.carregar_politica())
        return ReservaOut(
            reserva=reserva["id"], sala=destino, inicio=inicio, fim=fim, responsavel=responsavel, politica=politica
        )

    @mcp.resource("politica://uso", mime_type="text/markdown")
    def politica_de_uso() -> str:
        """Politica de uso das salas."""
        return dominio.carregar_politica()
