from abc import ABC, abstractmethod

from app.ai.core.context import Context
from app.ai.core.base_result import BaseResult


class BaseWorkflow(ABC):

    id: str

    name: str

    description: str

    @abstractmethod
    async def execute(
        self,
        context: Context
    ) -> BaseResult:
        pass