"""Dados do dominio: salas e politica de uso, lidos de dados/."""

from __future__ import annotations

import json
import os
from pathlib import Path

DADOS_DIR = Path(os.environ.get("DADOS_DIR") or Path(__file__).resolve().parents[3] / "dados")


def carregar_salas() -> list[dict]:
    return json.loads((DADOS_DIR / "salas.json").read_text(encoding="utf-8"))


def carregar_politica() -> str:
    return (DADOS_DIR / "politica-de-uso.md").read_text(encoding="utf-8")


def versao_da_politica(texto: str) -> str:
    primeira = texto.splitlines()[0]
    return primeira.split(":", 1)[1].strip()


# --- regras de uso -----------------------------------------------------------

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

FUSO = timezone(timedelta(hours=-3))
ABERTURA, FECHAMENTO = time(8, 0), time(20, 0)
DURACAO_MAXIMA = timedelta(hours=2)
MAX_ALTERNATIVAS = 3

ERRO_JANELA = "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00"
ERRO_DURACAO = "Duracao acima do limite: a politica permite no maximo 2 horas"
ERRO_INTERVALO = "Intervalo invalido: fim deve ser posterior a inicio"
ERRO_SEM_ALTERNATIVAS = "Sem alternativas disponiveis no intervalo"


class ErroDeRegra(Exception):
    """Violacao de regra de negocio; a mensagem e a do enunciado, sem prefixo."""


@dataclass(frozen=True)
class Intervalo:
    inicio: datetime
    fim: datetime


def _parse(valor: str) -> datetime:
    try:
        dt = datetime.fromisoformat(valor)
    except (TypeError, ValueError):
        raise ErroDeRegra(ERRO_INTERVALO) from None
    return dt if dt.tzinfo else dt.replace(tzinfo=FUSO)


def sala_por_id(sala: str) -> dict:
    for s in carregar_salas():
        if s["id"] == sala:
            return s
    raise ErroDeRegra(f"Sala inexistente: {sala}")


def validar(sala: str, inicio: str, fim: str) -> tuple[dict, Intervalo]:
    """Sala, intervalo, janela e duracao, nessa ordem. Mesmas regras na consulta e na reserva."""
    dados_sala = sala_por_id(sala)
    ini, fi = _parse(inicio), _parse(fim)
    if fi <= ini:
        raise ErroDeRegra(ERRO_INTERVALO)
    ini_sp, fi_sp = ini.astimezone(FUSO), fi.astimezone(FUSO)
    if ini_sp.date() != fi_sp.date() or ini_sp.time() < ABERTURA or fi_sp.time() > FECHAMENTO:
        raise ErroDeRegra(ERRO_JANELA)
    if fi - ini > DURACAO_MAXIMA:
        raise ErroDeRegra(ERRO_DURACAO)
    return dados_sala, Intervalo(ini, fi)


# --- reservas (em memoria; somem no restart) ---------------------------------

_reservas: list[dict] = json.loads((DADOS_DIR / "reservas.json").read_text(encoding="utf-8"))


def _sobrepoe(reserva: dict, intervalo: Intervalo) -> bool:
    return _parse(reserva["inicio"]) < intervalo.fim and intervalo.inicio < _parse(reserva["fim"])


def conflitos(sala: str, intervalo: Intervalo) -> list[dict]:
    return [r for r in _reservas if r["sala"] == sala and _sobrepoe(r, intervalo)]


def alternativas(sala: dict, intervalo: Intervalo) -> list[str]:
    """Salas livres com capacidade >= a pedida, por (capacidade, id), no maximo tres."""
    candidatas = [
        s for s in carregar_salas()
        if s["id"] != sala["id"] and s["capacidade"] >= sala["capacidade"] and not conflitos(s["id"], intervalo)
    ]
    candidatas.sort(key=lambda s: (s["capacidade"], s["id"]))
    return [s["id"] for s in candidatas[:MAX_ALTERNATIVAS]]


def criar_reserva(sala: str, intervalo_inicio: str, intervalo_fim: str, responsavel: str) -> dict:
    reserva = {
        "id": f"res-{len(_reservas) + 1:04d}",
        "sala": sala,
        "inicio": intervalo_inicio,
        "fim": intervalo_fim,
        "responsavel": responsavel,
    }
    _reservas.append(reserva)
    return reserva
