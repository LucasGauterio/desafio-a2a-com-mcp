"""Task A2A: identidade, estado e produto. O estado pausado vive aqui, por Task."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

SUBMITTED = "TASK_STATE_SUBMITTED"
WORKING = "TASK_STATE_WORKING"
INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
COMPLETED = "TASK_STATE_COMPLETED"
CANCELED = "TASK_STATE_CANCELED"
FAILED = "TASK_STATE_FAILED"
REJECTED = "TASK_STATE_REJECTED"

TERMINAIS = frozenset({COMPLETED, CANCELED, FAILED, REJECTED})


def novo_id(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_hex(6)}"


@dataclass
class Pausa:
    """O que a ponte guarda ao transformar `input_required` em INPUT_REQUIRED.

    `request_state` e opaco: so e guardado e ecoado. Esta classe nunca e serializada.
    """

    request_state: str
    chave: str
    alternativas: list[str]
    argumentos: dict


@dataclass
class Task:
    id: str
    context_id: str
    estado: str = SUBMITTED
    mensagem_status: dict | None = None
    history: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    pausa: Pausa | None = None
    traceparent: str | None = None

    def mensagem_do_agente(self, texto: str) -> dict:
        return {
            "messageId": novo_id("msg"),
            "role": "ROLE_AGENT",
            "parts": [{"text": texto}],
            "taskId": self.id,
            "contextId": self.context_id,
        }

    def transitar(self, estado: str, texto: str | None = None) -> None:
        """Estado terminal e definitivo: nada volta de COMPLETED, CANCELED, FAILED ou REJECTED."""
        if self.estado in TERMINAIS:
            raise RuntimeError(f"{self.id} ja esta em {self.estado}")
        self.estado = estado
        self.mensagem_status = self.mensagem_do_agente(texto) if texto is not None else None
        if self.mensagem_status:
            self.history.append(self.mensagem_status)

    def para_a2a(self) -> dict:
        """Lista explicita de campos: o `requestState` guardado em `pausa` nunca sai daqui."""
        status: dict = {"state": self.estado, "timestamp": datetime.now(timezone.utc).isoformat()}
        if self.mensagem_status:
            status["message"] = self.mensagem_status
        return {
            "id": self.id,
            "contextId": self.context_id,
            "status": status,
            "history": list(self.history),
            "artifacts": list(self.artifacts),
        }


class RepositorioDeTasks:
    """Em memoria: persistir Tasks em disco esta fora de escopo."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def criar(self, context_id: str | None) -> Task:
        task = Task(id=novo_id("task"), context_id=context_id or novo_id("ctx"))
        self._tasks[task.id] = task
        return task

    def obter(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)
