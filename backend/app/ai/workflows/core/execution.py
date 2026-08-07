from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class WorkflowExecution:

    workflow_id: str

    status: str = "PENDING"

    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    finished_at: datetime | None = None

    current_step: str | None = None

    result: Any = None