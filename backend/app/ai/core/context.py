from dataclasses import dataclass, field
from typing import Any


@dataclass
class Context:

    user_id: str | None = None

    company_id: str | None = None

    conversation_id: str | None = None

    user_message: str = ""

    workflow: str | None = None

    variables: dict[str, Any] = field(default_factory=dict)

    metadata: dict[str, Any] = field(default_factory=dict)