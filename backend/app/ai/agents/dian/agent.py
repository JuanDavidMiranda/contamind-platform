from app.ai.core.base_agent import BaseAgent
from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.core.context import Context
from app.ai.agents.dian.handlers import DianHandler
from app.ai.core.capability import Capability

class DianAgent(BaseAgent):

    id = "dian"

    name = "DIAN Agent"

    description = "Agent responsible for DIAN operations"

    def __init__(self):

        self.handler = DianHandler()

    async def execute(
        self,
        task: BaseTask,
        context: Context
    ) -> BaseResult:

        return self.handler.handle(task.objective)

    async def health(self) -> bool:

        return True


    @property
    def capabilities(self):

        return [

            Capability(
                name="Exógena",
                description="Procesos relacionados con información exógena.",
                keywords=[
                    "exogena",
                    "exógena",
                    "medios magnéticos"
                ]
            ),

            Capability(
                name="RUT",
                description="Consultas relacionadas con el RUT.",
                keywords=[
                    "rut"
                ]
            ),

            Capability(
                name="Facturación Electrónica",
                description="Facturación electrónica DIAN.",
                keywords=[
                    "factura",
                    "facturación",
                    "electrónica"
                ]
            )

        ]