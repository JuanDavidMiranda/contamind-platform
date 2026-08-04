from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class WorkflowExecution:

    workflow_id: str

    status: str = "PENDING"

    started_at: datetime = field(default_factory=datetime.utcnow)

    finished_at: datetime | None = None

    current_step: str | None = None

    result: Any = None