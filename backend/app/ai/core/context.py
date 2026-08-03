from dataclasses import dataclass, field
from typing import Any


@dataclass
class Context:

    user: str | None = None

    company: str | None = None

    session_id: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)