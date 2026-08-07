from app.ai.core.base_agent import BaseAgent
from app.ai.core.base_result import BaseResult
from app.ai.core.base_task import BaseTask
from app.ai.core.context import Context
from app.ai.core.capability import Capability
from app.ai.tools.registry import registry

class DianAgent(BaseAgent):

    id = "dian"

    name = "DIAN Agent"

    description = "Agent responsible for DIAN operations"

    async def execute(
        self,
        task: BaseTask,
        context: Context
    ) -> BaseResult:

        tool = self.select_tool(task)

        return await tool.execute(context)

    async def health(self) -> bool:
        return True

    def select_tool(self, task: BaseTask):

        objective = task.objective.lower()

        if "obligaciones" in objective:

            return registry.get("Consultar obligaciones")

        if "rut" in objective:

            return registry.get("Consultar RUT")

        raise ValueError(
            f"No existe una herramienta para '{task.objective}'"
        )

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