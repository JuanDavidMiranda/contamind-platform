from abc import ABC, abstractmethod

from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.core.context import Context


class BaseAgent(ABC):

    id: str

    name: str

    description: str

    version: str = "1.0.0"

    @abstractmethod
    async def execute(
        self,
        task: BaseTask,
        context: Context
    ) -> BaseResult:
        """
        Ejecuta una tarea.
        """
        pass

    @abstractmethod
    async def health(self) -> bool:
        """
        Verifica el estado del agente.
        """
        pass

    @property
    @abstractmethod
    def capabilities(self) -> list:
        pass