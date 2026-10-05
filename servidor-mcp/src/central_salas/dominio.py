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
