from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class BaseTask:

    objective: str

    payload: dict[str, Any] = field(default_factory=dict)

    task_id: str = field(default_factory=lambda: str(uuid4()))