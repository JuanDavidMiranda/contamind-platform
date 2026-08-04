from abc import ABC, abstractmethod

from app.ai.core.context import Context
from app.ai.workflows.core.execution import WorkflowExecution


class BaseWorkflow(ABC):

    id: str

    name: str

    description: str

    @abstractmethod
    async def execute(
        self,
        execution: WorkflowExecution,
        context: Context
    ):
        pass