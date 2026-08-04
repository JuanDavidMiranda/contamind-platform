from dataclasses import dataclass, field
from typing import Any


@dataclass
class Context:

    # Información de la conversación
    conversation_id: str | None = None

    user_id: str | None = None

    company_id: str | None = None

    # Último mensaje recibido
    user_message: str = ""

    # Workflow activo
    workflow: str | None = None

    # Estado actual del workflow
    state: str = "START"

    # Variables recolectadas
    variables: dict[str, Any] = field(default_factory=dict)

    # Información adicional
    metadata: dict[str, Any] = field(default_factory=dict)

    entities: dict = field(default_factory=dict)